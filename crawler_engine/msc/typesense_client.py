"""Small stdlib Typesense v30 client and versioned collection lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import ssl
from time import perf_counter
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import TypesenseConfig
from .exception_ledger import record_exception
from .typesense_schema import (
    LOGICAL_ALIASES,
    SEARCH_CONFIGS,
    canonical_to_typesense_document,
    collection_schema,
    physical_collection_name,
    schema_contract_mismatches,
    validate_generation_id,
)

TYPESENSE_CONNECT_ERROR = "TYPESENSE_CONNECT_ERROR"
TYPESENSE_SCHEMA_ERROR = "TYPESENSE_SCHEMA_ERROR"
TYPESENSE_IMPORT_ERROR = "TYPESENSE_IMPORT_ERROR"
TYPESENSE_PARTIAL_IMPORT = "TYPESENSE_PARTIAL_IMPORT"
TYPESENSE_IDENTITY_CONFLICT = "TYPESENSE_IDENTITY_CONFLICT"
TYPESENSE_ALIAS_ERROR = "TYPESENSE_ALIAS_ERROR"


class TypesenseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class TypesenseHttpError(TypesenseError):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(code, message)


def validate_checkpoint_provenance_continuity(
    checkpoint_path: str | Path,
    provenance_path: str | Path,
    generation_id: str,
) -> dict[str, Any]:
    """Read-only proof that operational state exists for a cutover target."""

    checkpoint = Path(checkpoint_path)
    provenance = Path(provenance_path)
    if not checkpoint.is_file() or not provenance.is_file():
        raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "checkpoint and provenance databases are required for cutover")
    sink_target = f"typesense:{generation_id}"
    try:
        checkpoint_connection = sqlite3.connect(
            f"file:{checkpoint.resolve().as_posix()}?mode=ro", uri=True
        )
        try:
            checkpoint_quick_check = checkpoint_connection.execute("PRAGMA quick_check").fetchone()[0]
            tables = {
                row[0] for row in checkpoint_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "ingestion_checkpoint" not in tables:
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "checkpoint database lacks ingestion_checkpoint")
            checkpoint_rows = int(checkpoint_connection.execute(
                "SELECT count(*) FROM ingestion_checkpoint WHERE sink_target=? AND status IN ('COMPLETED','VALIDATED')",
                (sink_target,),
            ).fetchone()[0])
        finally:
            checkpoint_connection.close()

        provenance_connection = sqlite3.connect(
            f"file:{provenance.resolve().as_posix()}?mode=ro", uri=True
        )
        try:
            provenance_quick_check = provenance_connection.execute("PRAGMA quick_check").fetchone()[0]
            tables = {
                row[0] for row in provenance_connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"uuid_provenance", "uuid_conflict"}.issubset(tables):
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "provenance database lacks required audit tables")
            conflicts = int(provenance_connection.execute("SELECT count(*) FROM uuid_conflict").fetchone()[0])
        finally:
            provenance_connection.close()
    except TypesenseError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"checkpoint/provenance continuity check failed: {exc}") from exc
    if checkpoint_quick_check != "ok" or provenance_quick_check != "ok":
        raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "checkpoint/provenance quick_check failed")
    if checkpoint_rows <= 0:
        raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"no completed checkpoint state for {sink_target}")
    if conflicts != 0:
        raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"provenance conflict count is {conflicts}")
    return {
        "checkpoint_quick_check": checkpoint_quick_check,
        "checkpoint_rows": checkpoint_rows,
        "provenance_quick_check": provenance_quick_check,
        "provenance_conflicts": conflicts,
    }


def _persist_generation_exception(
    checkpoint_path: str | Path,
    *,
    operation_id: str,
    source_id: str,
    logical_group: str,
    category: str,
    reason: str,
) -> None:
    connection = sqlite3.connect(str(checkpoint_path))
    try:
        record_exception(
            connection,
            operation_id=operation_id,
            source_id=source_id,
            logical_group=logical_group,
            category=category,
            reason=reason,
        )
    finally:
        connection.close()


@dataclass(frozen=True)
class ImportResult:
    attempted_count: int
    accepted_count: int
    rejected_count: int
    errors: tuple[str, ...] = ()
    error_code: str | None = None
    elapsed_seconds: float = 0.0


def serialize_ndjson(documents: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for document in documents
    )


def parse_import_response(response_text: str, attempted_count: int) -> ImportResult:
    """Parse every Typesense import result line, including HTTP-200 failures."""

    if attempted_count < 0:
        raise ValueError("attempted_count cannot be negative")
    lines = response_text.splitlines() if response_text else []
    accepted = 0
    errors: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip():
            errors.append(f"response line {index + 1} is empty")
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"response line {index + 1} is not valid JSON")
            continue
        if not isinstance(result, dict):
            errors.append(f"response line {index + 1} is not an object")
            continue
        if result.get("success") is True:
            accepted += 1
        else:
            message = result.get("error") or result.get("message") or "success was not true"
            errors.append(f"document[{index}] import failed: {str(message)[:500]}")
    if len(lines) != attempted_count:
        errors.append(f"import response line count {len(lines)} does not match attempted {attempted_count}")
    rejected = attempted_count - accepted
    if errors and rejected <= 0:
        rejected = 1
    code = None
    if errors:
        code = TYPESENSE_PARTIAL_IMPORT if len(lines) == attempted_count and accepted < attempted_count else TYPESENSE_IMPORT_ERROR
    return ImportResult(attempted_count, accepted, rejected, tuple(errors), code)


def validate_identity_union(record_groups: Sequence[Sequence[Mapping[str, Any]]]) -> None:
    """Reject a UUID reused by incompatible MSC source provenance."""

    seen: dict[str, tuple[Any, Any]] = {}
    for records in record_groups:
        for record in records:
            record_id = record.get("id")
            provenance = (record.get("data_group"), record.get("source_key"))
            if not isinstance(record_id, str) or not record_id:
                raise TypesenseError(TYPESENSE_IDENTITY_CONFLICT, "canonical record has no non-empty id")
            if record_id in seen and seen[record_id] != provenance:
                raise TypesenseError(
                    TYPESENSE_IDENTITY_CONFLICT,
                    f"UUID {record_id} has incompatible provenance {seen[record_id]} and {provenance}",
                )
            seen[record_id] = provenance


class TypesenseClient:
    """Narrow admin/search client for standard HTTP(S) Typesense transport."""

    def __init__(self, config: TypesenseConfig, *, opener: Callable[..., Any] | None = None) -> None:
        self.config = config
        self._opener = opener or urlopen

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    @staticmethod
    def _error_message(body: bytes) -> str:
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body.decode("utf-8", errors="replace")[:1000] or "Typesense request failed"
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or "Typesense request failed")[:1000]
        return str(payload)[:1000]

    def _request_raw(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        content_type: str = "application/json",
        error_code: str = TYPESENSE_CONNECT_ERROR,
        timeout_seconds: float | None = None,
    ) -> bytes:
        request = Request(
            self._url(path), data=body, method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
                "X-TYPESENSE-API-KEY": self.config.api_key,
            },
        )
        try:
            kwargs: dict[str, Any] = {
                "timeout": self.config.timeout_seconds if timeout_seconds is None else timeout_seconds,
            }
            if self.config.protocol == "https":
                kwargs["context"] = ssl.create_default_context()
            with self._opener(request, **kwargs) as response:
                return response.read()
        except HTTPError as exc:
            try:
                message = self._error_message(exc.read())
            except OSError:
                message = "Typesense HTTP request failed"
            raise TypesenseHttpError(error_code, f"HTTP {exc.code}: {message}", exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TypesenseError(TYPESENSE_CONNECT_ERROR, f"Typesense request failed: {type(exc).__name__}: {exc}") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        error_code: str = TYPESENSE_CONNECT_ERROR,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        raw = self._request_raw(method, path, body, error_code=error_code, timeout_seconds=timeout_seconds)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TypesenseError(error_code, "Typesense returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise TypesenseError(error_code, "Typesense returned a non-object JSON response")
        return parsed

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health", error_code=TYPESENSE_CONNECT_ERROR)

    def metrics(self) -> dict[str, Any]:
        """Read optional Typesense metrics for capacity preflight."""

        return self._request_json("GET", "/metrics.json", error_code=TYPESENSE_CONNECT_ERROR)

    def snapshot(self, snapshot_path: str | Path) -> dict[str, Any]:
        """Create a supported point-in-time snapshot on the Typesense host."""

        path = str(snapshot_path)
        if not path or not path.startswith("/"):
            raise ValueError("snapshot_path must be an absolute path on the Typesense host")
        return self._request_json(
            "POST",
            f"/operations/snapshot?{urlencode({'snapshot_path': path})}",
            error_code=TYPESENSE_CONNECT_ERROR,
            timeout_seconds=self.config.snapshot_timeout_seconds,
        )

    def get_collection(self, name: str) -> dict[str, Any] | None:
        try:
            return self._request_json("GET", f"/collections/{quote(name, safe='')}", error_code=TYPESENSE_SCHEMA_ERROR)
        except TypesenseHttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def list_collections(self) -> list[dict[str, Any]]:
        raw = self._request_raw("GET", "/collections", error_code=TYPESENSE_SCHEMA_ERROR)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "Typesense returned invalid collection JSON") from exc
        collections = payload.get("collections", []) if isinstance(payload, dict) else payload
        if not isinstance(collections, list) or not all(isinstance(item, dict) for item in collections):
            raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "Typesense returned invalid collection list")
        return collections

    def create_collection(self, schema: Mapping[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "POST", "/collections", schema, error_code=TYPESENSE_SCHEMA_ERROR,
        )

    def update_collection_schema(
        self,
        collection: str,
        schema_update: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Apply a synchronous Typesense collection schema alteration."""

        if not collection or not isinstance(schema_update, Mapping):
            raise ValueError("collection and schema_update are required")
        return self._request_json(
            "PATCH",
            f"/collections/{quote(collection, safe='')}",
            schema_update,
            error_code=TYPESENSE_SCHEMA_ERROR,
            timeout_seconds=timeout_seconds,
        )

    def clone_collection(
        self,
        source: str,
        destination: str,
        *,
        copy_documents: bool = True,
        metadata: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Clone one collection server-side, optionally including documents."""

        if not source or not destination or source == destination:
            raise ValueError("clone source and destination must be distinct non-empty names")
        payload: dict[str, Any] = {"name": destination}
        if metadata is not None:
            payload["metadata"] = dict(metadata)
        query = urlencode({"src_name": source, "copy_documents": str(copy_documents).lower()})
        return self._request_json(
            "POST", f"/collections?{query}", payload, error_code=TYPESENSE_SCHEMA_ERROR,
            timeout_seconds=timeout_seconds,
        )

    def get_alias(self, alias: str) -> dict[str, Any] | None:
        try:
            return self._request_json("GET", f"/aliases/{quote(alias, safe='')}", error_code=TYPESENSE_ALIAS_ERROR)
        except TypesenseHttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def list_aliases(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/aliases", error_code=TYPESENSE_ALIAS_ERROR)
        aliases = payload.get("aliases", payload)
        return aliases if isinstance(aliases, list) else []

    def upsert_alias(self, alias: str, collection_name: str) -> dict[str, Any]:
        return self._request_json(
            "PUT", f"/aliases/{quote(alias, safe='')}", {"collection_name": collection_name}, error_code=TYPESENSE_ALIAS_ERROR,
        )

    def delete_alias(self, alias: str) -> dict[str, Any] | None:
        try:
            return self._request_json("DELETE", f"/aliases/{quote(alias, safe='')}", error_code=TYPESENSE_ALIAS_ERROR)
        except TypesenseHttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def delete_collection(self, name: str, *, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        try:
            return self._request_json(
                "DELETE",
                f"/collections/{quote(name, safe='')}",
                error_code=TYPESENSE_SCHEMA_ERROR,
                timeout_seconds=timeout_seconds,
            )
        except TypesenseHttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def delete_document(self, collection: str, document_id: str) -> dict[str, Any]:
        """Delete one proven document ID; callers must provide exact IDs."""

        return self._request_json(
            "DELETE",
            f"/collections/{quote(collection, safe='')}/documents/{quote(str(document_id), safe='')}",
            error_code=TYPESENSE_IMPORT_ERROR,
        )

    def import_documents(
        self,
        collection: str,
        documents: Sequence[Mapping[str, Any]],
        *,
        action: str = "upsert",
        timeout_seconds: float | None = None,
    ) -> ImportResult:
        if action not in {"upsert", "update"}:
            raise ValueError("Typesense import action must be upsert or update")
        started = perf_counter()
        try:
            raw = self._request_raw(
                "POST",
                f"/collections/{quote(collection, safe='')}/documents/import?{urlencode({'action': action})}",
                serialize_ndjson(documents),
                content_type="application/jsonl",
                error_code=TYPESENSE_IMPORT_ERROR,
                timeout_seconds=timeout_seconds,
            )
        except TypesenseError as exc:
            return ImportResult(len(documents), 0, len(documents), (str(exc),), exc.code, perf_counter() - started)
        result = parse_import_response(raw.decode("utf-8", errors="replace"), len(documents))
        return ImportResult(
            result.attempted_count, result.accepted_count, result.rejected_count, result.errors,
            result.error_code, perf_counter() - started,
        )

    def export_documents(
        self,
        collection: str,
        *,
        include_fields: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream one collection export without buffering its documents in RAM."""

        query = ""
        if include_fields:
            fields = tuple(str(field).strip() for field in include_fields if str(field).strip())
            if fields:
                query = f"?{urlencode({'include_fields': ','.join(fields)})}"
        request = Request(
            self._url(f"/collections/{quote(collection, safe='')}/documents/export{query}"),
            method="GET",
            headers={
                "Accept": "application/jsonl",
                "X-TYPESENSE-API-KEY": self.config.api_key,
            },
        )
        try:
            kwargs: dict[str, Any] = {
                "timeout": self.config.timeout_seconds if timeout_seconds is None else timeout_seconds,
            }
            if self.config.protocol == "https":
                kwargs["context"] = ssl.create_default_context()
            with self._opener(request, **kwargs) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        document = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise TypesenseError(TYPESENSE_IMPORT_ERROR, "Typesense export returned invalid JSON") from exc
                    if not isinstance(document, dict):
                        raise TypesenseError(TYPESENSE_IMPORT_ERROR, "Typesense export returned a non-object document")
                    yield document
        except HTTPError as exc:
            try:
                message = self._error_message(exc.read())
            except OSError:
                message = "Typesense export failed"
            raise TypesenseHttpError(TYPESENSE_IMPORT_ERROR, f"HTTP {exc.code}: {message}", exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TypesenseError(TYPESENSE_CONNECT_ERROR, f"Typesense export failed: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _validate_filter_fields(logical_group: str, filter_by: str | None) -> None:
        if not filter_by:
            return
        allowed = SEARCH_CONFIGS[logical_group].filter_fields
        clauses = re.split(r"\s*(?:&&|\|\|)\s*", filter_by)
        for clause in clauses:
            field = clause.strip().lstrip("(!").split(":", 1)[0].strip()
            if field and field not in allowed:
                raise ValueError(f"filter field is not allowed for {logical_group}: {field}")

    @staticmethod
    def _validate_sort_fields(logical_group: str, sort_by: str | None) -> None:
        if not sort_by:
            return
        allowed = SEARCH_CONFIGS[logical_group].sort_fields
        for clause in sort_by.split(","):
            field = clause.strip().split(":", 1)[0]
            if field not in allowed:
                raise ValueError(f"sort field is not allowed for {logical_group}: {field}")

    def search_group(
        self,
        logical_group: str,
        query: str,
        *,
        filter_by: str | None = None,
        sort_by: str | None = None,
        facet_by: str | None = None,
        per_page: int = 20,
        collection: str | None = None,
    ) -> dict[str, Any]:
        if logical_group not in SEARCH_CONFIGS:
            raise ValueError(f"unknown logical group: {logical_group}")
        if per_page <= 0:
            raise ValueError("per_page must be positive")
        self._validate_filter_fields(logical_group, filter_by)
        self._validate_sort_fields(logical_group, sort_by)
        params: dict[str, Any] = {
            "q": query or "*",
            "query_by": ",".join(SEARCH_CONFIGS[logical_group].query_by),
            "per_page": per_page,
        }
        if filter_by:
            params["filter_by"] = filter_by
        if sort_by:
            params["sort_by"] = sort_by
        if facet_by:
            params["facet_by"] = facet_by
        encoded = urlencode(params)
        return self._request_json(
            "GET",
            f"/collections/{quote(collection or SEARCH_CONFIGS[logical_group].alias, safe='')}/documents/search?{encoded}",
            error_code=TYPESENSE_CONNECT_ERROR,
        )

    def multi_search_all(self, query: str, *, filter_by: Mapping[str, str] | None = None, sort_by: Mapping[str, str] | None = None, per_page: int = 20, union: bool = False, generation_id: str | None = None) -> dict[str, Any]:
        if per_page <= 0:
            raise ValueError("per_page must be positive")
        searches = []
        for group, config in SEARCH_CONFIGS.items():
            group_filter = filter_by.get(group) if filter_by else None
            group_sort = sort_by.get(group) if sort_by else None
            self._validate_filter_fields(group, group_filter)
            self._validate_sort_fields(group, group_sort)
            item: dict[str, Any] = {
                "collection": physical_collection_name(group, generation_id) if generation_id is not None else config.alias,
                "q": query or "*",
                "query_by": ",".join(config.query_by),
                "per_page": per_page,
            }
            if group_filter:
                item["filter_by"] = group_filter
            if group_sort:
                item["sort_by"] = group_sort
            searches.append(item)
        payload: dict[str, Any] = {"searches": searches}
        if union:
            payload["union"] = True
        return self._request_json("POST", "/multi_search", payload, error_code=TYPESENSE_CONNECT_ERROR)

    def get_document(self, collection: str, document_id: str) -> dict[str, Any] | None:
        try:
            return self._request_json(
                "GET", f"/collections/{quote(collection, safe='')}/documents/{quote(document_id, safe='')}",
                error_code=TYPESENSE_CONNECT_ERROR,
            )
        except TypesenseHttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def document_count(self, collection: str) -> int:
        details = self.get_collection(collection)
        if details is None:
            raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"collection {collection} does not exist")
        count = details.get("num_documents")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"collection {collection} returned invalid num_documents")
        return count


class TypesenseCollectionManager:
    """Create, validate, activate, inspect, and roll back generation aliases."""

    def __init__(self, client: TypesenseClient) -> None:
        self.client = client

    @staticmethod
    def _compatible(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
        return not schema_contract_mismatches(actual, expected)

    def _validate_collections(self, generation_id: str) -> dict[str, dict[str, Any]]:
        validate_generation_id(generation_id)
        result: dict[str, dict[str, Any]] = {}
        for group in LOGICAL_ALIASES:
            expected = collection_schema(group, generation_id)
            actual = self.client.get_collection(expected["name"])
            if actual is None:
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"collection {expected['name']} does not exist")
            mismatches = schema_contract_mismatches(actual, expected)
            if mismatches:
                raise TypesenseError(
                    TYPESENSE_SCHEMA_ERROR,
                    f"collection {expected['name']} failed canonical schema/metadata validation: {'; '.join(mismatches)}",
                )
            result[group] = {
                "collection": expected["name"],
                "num_documents": actual.get("num_documents", 0),
                "metadata": actual.get("metadata", {}),
            }
        return result

    def preflight_generation(
        self,
        generation_id: str,
        *,
        source_generation: str | None = None,
        expected_counts: Mapping[str, int] | None = None,
        count_tolerance: int = 0,
        checkpoint_path: str | Path | None = None,
        provenance_path: str | Path | None = None,
        continuity_generation: str | None = None,
        require_target: bool = False,
        require_continuity: bool = False,
    ) -> dict[str, Any]:
        """Validate all cutover/incremental gates before work or alias writes."""

        validate_generation_id(generation_id)
        if count_tolerance < 0:
            raise ValueError("count_tolerance cannot be negative")
        target: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for group in LOGICAL_ALIASES:
            expected = collection_schema(group, generation_id)
            actual = self.client.get_collection(expected["name"])
            if actual is None:
                missing.append(group)
                continue
            mismatches = schema_contract_mismatches(actual, expected)
            if mismatches:
                raise TypesenseError(
                    TYPESENSE_SCHEMA_ERROR,
                    f"preflight failed for {group}: {'; '.join(mismatches)}",
                )
            target[group] = {
                "collection": expected["name"],
                "num_documents": actual.get("num_documents", 0),
                "metadata": actual.get("metadata", {}),
            }
        if require_target and missing:
            raise TypesenseError(
                TYPESENSE_SCHEMA_ERROR,
                f"preflight target generation is incomplete; missing groups: {', '.join(missing)}",
            )

        source: dict[str, dict[str, Any]] = {}
        if source_generation is not None:
            validate_generation_id(source_generation)
            if source_generation == generation_id:
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "source and target generations must be distinct")
            source = self._validate_collections(source_generation)
            if set(source) != set(LOGICAL_ALIASES):
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "source and target logical groups do not match")

        counts: dict[str, dict[str, int | bool]] = {}
        if expected_counts is not None:
            if set(expected_counts) != set(LOGICAL_ALIASES):
                raise TypesenseError(
                    TYPESENSE_SCHEMA_ERROR,
                    "expected_counts must contain exactly goods, medicines, and traditional_medicine",
                )
            if missing:
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "cannot validate counts for a missing target collection")
            for group in LOGICAL_ALIASES:
                actual_count = self.client.document_count(target[group]["collection"])
                expected_count = expected_counts[group]
                if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
                    raise ValueError("expected document counts must be non-negative integers")
                difference = abs(actual_count - expected_count)
                counts[group] = {
                    "expected": expected_count,
                    "actual": actual_count,
                    "difference": difference,
                    "within_tolerance": difference <= count_tolerance,
                }
                if difference > count_tolerance:
                    raise TypesenseError(
                        TYPESENSE_SCHEMA_ERROR,
                        f"preflight count mismatch for {group}: {actual_count} != {expected_count} +/- {count_tolerance}",
                    )

        continuity: dict[str, Any] | None = None
        if require_continuity:
            if checkpoint_path is None or provenance_path is None:
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, "checkpoint and provenance paths are required for cutover")
            continuity = validate_checkpoint_provenance_continuity(
                checkpoint_path, provenance_path, continuity_generation or generation_id
            )
        return {
            "generation": generation_id,
            "schema_contract": "PASS",
            "required_metadata": "PASS",
            "source_generation": source_generation,
            "source_logical_groups": sorted(source),
            "target_logical_groups": sorted(target),
            "missing_target_groups": missing,
            "incremental_compatibility": "PASS" if not missing else "PENDING_TARGET",
            "counts": counts,
            "checkpoint_provenance_continuity": continuity or "NOT_REQUIRED",
            "collections": target,
        }

    def create_generation(self, generation_id: str) -> dict[str, str]:
        validate_generation_id(generation_id)
        self.preflight_generation(generation_id)
        created: dict[str, str] = {}
        for group in LOGICAL_ALIASES:
            expected = collection_schema(group, generation_id)
            actual = self.client.get_collection(expected["name"])
            if actual is None:
                self.client.create_collection(expected)
            elif not self._compatible(actual, expected):
                raise TypesenseError(TYPESENSE_SCHEMA_ERROR, f"existing collection {expected['name']} has incompatible schema or metadata")
            created[group] = expected["name"]
        return created

    def validate_generation(self, generation_id: str) -> dict[str, dict[str, Any]]:
        return self._validate_collections(generation_id)

    def activate_generation(
        self,
        generation_id: str,
        *,
        expected_counts: Mapping[str, int],
        count_tolerance: int = 0,
        checkpoint_path: str | Path,
        provenance_path: str | Path,
        source_generation: str | None = None,
    ) -> dict[str, str]:
        self.preflight_generation(
            generation_id,
            source_generation=source_generation,
            expected_counts=expected_counts,
            count_tolerance=count_tolerance,
            checkpoint_path=checkpoint_path,
            provenance_path=provenance_path,
            require_target=True,
            require_continuity=True,
        )
        activated: dict[str, str] = {}
        for group, alias in LOGICAL_ALIASES.items():
            physical = physical_collection_name(group, generation_id)
            self.client.upsert_alias(alias, physical)
            activated[alias] = physical
        return activated

    def point_alias(
        self,
        logical_group: str,
        collection_name: str,
        *,
        expected_counts: Mapping[str, int],
        count_tolerance: int = 0,
        checkpoint_path: str | Path,
        provenance_path: str | Path,
        source_generation: str | None = None,
    ) -> dict[str, Any]:
        if logical_group not in LOGICAL_ALIASES:
            raise ValueError(f"unknown logical group: {logical_group}")
        prefix = f"{LOGICAL_ALIASES[logical_group]}_v1_"
        if not collection_name.startswith(prefix):
            raise TypesenseError(TYPESENSE_ALIAS_ERROR, f"collection {collection_name} does not belong to {logical_group}")
        generation_id = collection_name[len(prefix):]
        self.preflight_generation(
            generation_id,
            source_generation=source_generation,
            expected_counts=expected_counts,
            count_tolerance=count_tolerance,
            checkpoint_path=checkpoint_path,
            provenance_path=provenance_path,
            require_target=True,
            require_continuity=True,
        )
        return self.client.upsert_alias(LOGICAL_ALIASES[logical_group], collection_name)

    def rollback_alias(
        self,
        logical_group: str,
        generation_id: str,
        *,
        expected_counts: Mapping[str, int],
        count_tolerance: int = 0,
        checkpoint_path: str | Path,
        provenance_path: str | Path,
    ) -> dict[str, Any]:
        return self.point_alias(
            logical_group,
            physical_collection_name(logical_group, generation_id),
            expected_counts=expected_counts,
            count_tolerance=count_tolerance,
            checkpoint_path=checkpoint_path,
            provenance_path=provenance_path,
        )

    def inspect(self) -> dict[str, Any]:
        aliases: dict[str, Any] = {}
        for alias in LOGICAL_ALIASES.values():
            target = self.client.get_alias(alias)
            collection_name = target.get("collection_name") if target else None
            aliases[alias] = {
                "collection_name": collection_name,
                "num_documents": self.client.document_count(collection_name) if collection_name else None,
            }
        return {"aliases": aliases}
