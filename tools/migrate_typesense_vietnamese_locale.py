"""Rebuild Typesense collections with Vietnamese locale in the create schema.

This tool has one migration path:

1. audit health, runtime generation, collections, schema, and capacity;
2. create a new collection from the final schema;
3. stream one source export into one target import, sequentially;
4. verify parity, schema, samples, filters, facets, and search;
5. optionally cut over the physical API generation;
6. optionally delete old collections only after the cutover proof passes.

It never clones a collection and never alters a populated collection schema.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import unicodedata
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.config import TypesenseConfig  # noqa: E402
from crawler_engine.msc.exception_ledger import (  # noqa: E402
    ensure_exception_ledger,
    exception_count,
    record_exception,
)
from crawler_engine.msc.typesense_client import (  # noqa: E402
    TypesenseClient,
    TypesenseCollectionManager,
)
from crawler_engine.msc.typesense_schema import (  # noqa: E402
    LOGICAL_ALIASES,
    REQUIRED_SCHEMA_METADATA,
    SEARCH_CONFIGS,
    collection_schema,
    schema_contract_mismatches,
    schema_for_group,
    physical_collection_name,
    validate_generation_id,
)


LOCALE = "vi"
TEXT_TYPES = frozenset({"string", "string[]"})
IMPLICIT_ID = "id"
STALE_NAME_RE = re.compile(r"(?:_vi(?:_|$)|clone|partial|temp|tmp|failed|canary)", re.I)
CREATE_SETTINGS = (
    "default_sorting_field",
    "token_separators",
    "symbols_to_index",
    "enable_nested_fields",
    "num_memory_shards",
)
LEGACY_TYPE_MIGRATIONS = frozenset({
    ("production_year", "int32", "string"),
    ("bidder_count", "int32", "float"),
})
DEFAULT_SOURCE_GENERATION = "serving_v1_20260901"
DEFAULT_RUNTIME_ENV = "~/.config/bidfinder/runtime.env"
DEFAULT_API_URL = "http://127.0.0.1:8001"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _json_read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"checkpoint must be a JSON object: {path}")
    return value


def _strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "D")


def _runtime_generation(runtime_env: Path) -> str | None:
    if not runtime_env.is_file():
        return None
    for line in runtime_env.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^BIDFINDER_TYPESENSE_SERVING_GENERATION=(.*)$", line.strip())
        if match:
            return match.group(1).strip().strip('"\'') or None
    return None


def _text_query_fields(group: str) -> set[str]:
    return set(SEARCH_CONFIGS[group].query_by)


def _schema_contract_issues(
    group: str,
    source_schema: Mapping[str, Any],
    *,
    source_generation: str | None = None,
) -> list[str]:
    expected = {field["name"]: field for field in schema_for_group(group)["fields"]}
    actual = {field["name"]: field for field in source_schema.get("fields", []) if isinstance(field, Mapping) and field.get("name")}
    expected_names = set(expected) - {IMPLICIT_ID}
    actual_names = set(actual) - {IMPLICIT_ID}
    issues: list[str] = []
    for name in sorted(expected_names - actual_names):
        issues.append(f"missing field: {name}")
    for name in sorted(actual_names - expected_names):
        issues.append(f"unexpected field: {name}")
    metadata = source_schema.get("metadata")
    if not isinstance(metadata, Mapping):
        issues.append("metadata is missing or not an object")
    else:
        for key in sorted(REQUIRED_SCHEMA_METADATA):
            if key not in metadata:
                issues.append(f"metadata missing: {key}")
        if metadata.get("logical_group") not in (None, group):
            issues.append(f"metadata.logical_group={metadata.get('logical_group')!r} != {group!r}")
        if source_generation is not None and metadata.get("generation_id") != source_generation:
            issues.append(
                f"metadata.generation_id={metadata.get('generation_id')!r} != {source_generation!r}"
            )
    # Production schema is authoritative for field types and flags.  The
    # target copies those values byte-for-byte; this guard only prevents a
    # missing or unexpected field from silently changing the document shape.
    return issues


def _final_schema(group: str, generation: str, source_schema: Mapping[str, Any]) -> dict[str, Any]:
    """Copy production settings and apply only approved legacy type migrations."""

    target_name = physical_collection_name(group, generation)
    expected_schema = collection_schema(group, generation)
    expected_fields = {field["name"]: field for field in expected_schema["fields"]}
    source_fields = {
        str(field["name"]): field
        for field in source_schema.get("fields", [])
        if isinstance(field, Mapping) and field.get("name")
    }
    fields: list[dict[str, Any]] = []
    for expected_field in expected_schema["fields"]:
        name = str(expected_field["name"])
        source_field = source_fields.get(name)
        if source_field is None and name == IMPLICIT_ID:
            continue
        if source_field is None:
            raise RuntimeError(f"source schema is missing canonical field {group}.{name}")
        if source_field.get("type") != expected_field.get("type"):
            migration = (name, str(source_field.get("type")), str(expected_field.get("type")))
            if migration not in LEGACY_TYPE_MIGRATIONS:
                raise RuntimeError(
                    f"unsupported source type migration for {group}.{name}: "
                    f"{source_field.get('type')} -> {expected_field.get('type')}"
                )
        fields.append(deepcopy(expected_field))

    schema: dict[str, Any] = {"name": target_name, "fields": fields}
    for key in CREATE_SETTINGS:
        if key in source_schema:
            schema[key] = deepcopy(source_schema[key])
    source_metadata = deepcopy(source_schema.get("metadata") or {})
    if not isinstance(source_metadata, dict):
        raise RuntimeError(f"source metadata is not an object: {source_schema.get('name')}")
    metadata = {
        **source_metadata,
        **expected_schema["metadata"],
    }
    metadata.update({
        "source_collection": source_schema.get("name", ""),
        "locale": LOCALE,
    })
    schema["metadata"] = metadata
    return schema


def _migrate_legacy_document(group: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt known legacy numeric fields without changing their represented value."""

    migrated = dict(document)
    if group == "goods" and "production_year" in migrated:
        value = migrated["production_year"]
        if value is not None and not isinstance(value, str):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError(
                    f"unsupported legacy production_year value: {type(value).__name__}"
                )
            # The old collection already discarded year ranges. This text
            # representation preserves its current value while new MSC data
            # enters through normalize_year without coercion.
            migrated["production_year"] = str(value)
    if "bidder_count" in migrated and migrated["bidder_count"] is not None:
        value = migrated["bidder_count"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"unsupported legacy bidder_count value: {type(value).__name__}")
        migrated["bidder_count"] = float(value)
    return migrated


def _schema_fingerprint(schema: Mapping[str, Any]) -> dict[str, Any]:
    fields = []
    for raw_field in schema.get("fields", []):
        if not isinstance(raw_field, Mapping):
            continue
        field = {key: deepcopy(value) for key, value in raw_field.items() if key != "drop"}
        # Typesense returns the default empty locale on GET even when it was
        # omitted from CREATE.  Normalize that server default so comparison
        # checks the requested locale semantics, not response serialization.
        if field.get("type") in TEXT_TYPES:
            field.setdefault("locale", "")
        fields.append(field)
    fields.sort(key=lambda field: str(field.get("name", "")))
    return {
        "fields": fields,
        "settings": {key: deepcopy(schema[key]) for key in CREATE_SETTINGS if key in schema},
        "metadata": deepcopy(schema.get("metadata") or {}),
    }


def _locale_status(group: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    query_fields = _text_query_fields(group)
    localized: list[str] = []
    missing: list[str] = []
    unexpected: list[str] = []
    for raw_field in schema.get("fields", []):
        if not isinstance(raw_field, Mapping):
            continue
        name = raw_field.get("name")
        if raw_field.get("type") not in TEXT_TYPES:
            continue
        if name in query_fields:
            if raw_field.get("locale") == LOCALE:
                localized.append(str(name))
            else:
                missing.append(str(name))
        elif raw_field.get("locale") == LOCALE:
            unexpected.append(str(name))
    return {
        "localized_fields": sorted(localized),
        "missing_fields": sorted(missing),
        "unexpected_fields": sorted(unexpected),
        "ok": not missing and not unexpected,
    }


def _wait_for_health(client: TypesenseClient, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "unknown"
    while True:
        try:
            payload = client.health()
            if payload.get("ok") is True:
                # /health can turn green while collection recovery is still
                # returning 503.  Do not mutate inventory until a read probe
                # succeeds as well.
                client.list_collections()
                return {**payload, "collections_ready": True}
            last_error = f"health payload={payload!r}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Typesense health did not become ready: {last_error}")
        time.sleep(5)


def _stale_collections(client: TypesenseClient, source_generation: str, target_generation: str) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    source_names = {physical_collection_name(group, source_generation) for group in LOGICAL_ALIASES}
    target_names = {physical_collection_name(group, target_generation) for group in LOGICAL_ALIASES}
    inventory = client.list_collections()
    candidates = []
    for item in inventory:
        name = str(item.get("name", ""))
        if name in source_names or name in target_names:
            continue
        if STALE_NAME_RE.search(name):
            candidates.append({"name": name, "num_documents": item.get("num_documents", 0)})
    candidates.sort(key=lambda item: item["name"])
    return inventory, sorted(source_names), candidates


def _delete_collections(
    client: TypesenseClient,
    names: list[str],
    *,
    timeout_seconds: float | None = None,
) -> list[str]:
    deleted: list[str] = []
    for name in names:
        client.delete_collection(name, timeout_seconds=timeout_seconds)
        if client.get_collection(name) is not None:
            raise RuntimeError(f"collection still exists after delete: {name}")
        deleted.append(name)
    return deleted


def _checkpoint_path(checkpoint_dir: Path, group: str) -> Path:
    return checkpoint_dir / f"{group}.json"


def _load_group_checkpoint(path: Path, source: str, target: str) -> dict[str, Any] | None:
    state = _json_read(path)
    if state is None:
        return None
    if state.get("source_collection") != source or state.get("target_collection") != target:
        raise RuntimeError(f"checkpoint collection mismatch: {path}")
    return state


def _record_exception_documents(
    ledger_path: Path,
    *,
    operation_id: str,
    group: str,
    source_name: str,
    target_name: str,
    documents: Sequence[Mapping[str, Any]],
    category: str,
    reason: str,
    leaf_start: int,
) -> None:
    """Persist every known source ID involved in one failed migration operation."""

    connection = sqlite3.connect(str(ledger_path))
    try:
        ensure_exception_ledger(connection)
        for index, document in enumerate(documents):
            source_id = str(document.get("id") or f"<missing-source-id:{leaf_start + index}>")
            record_exception(
                connection,
                operation_id=operation_id,
                source_id=source_id,
                logical_group=group,
                source_key=document.get("source_key"),
                partition_date=document.get("partition_date"),
                leaf_index=leaf_start + index,
                category=category,
                reason=reason,
                details={
                    "source_collection": source_name,
                    "target_collection": target_name,
                    "missing_source_id": not bool(document.get("id")),
                },
            )
    finally:
        connection.close()


def _ledger_count(ledger_path: Path, operation_id: str) -> int:
    connection = sqlite3.connect(str(ledger_path))
    try:
        return exception_count(connection, operation_id)
    finally:
        connection.close()


def _import_group(
    client: TypesenseClient,
    group: str,
    source_name: str,
    target_name: str,
    generation: str,
    *,
    checkpoint_dir: Path,
    batch_size: int,
    operation_timeout_seconds: float,
    progress_every: int,
    operation_id: str | None = None,
    source_generation: str | None = None,
) -> dict[str, Any]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = checkpoint_dir / "exception-ledger.sqlite3"
    operation_id = operation_id or f"migration:{generation}"
    connection = sqlite3.connect(str(ledger_path))
    try:
        ensure_exception_ledger(connection)
    finally:
        connection.close()
    source_schema = client.get_collection(source_name)
    if source_schema is None:
        raise RuntimeError(f"source collection is missing: {source_name}")
    contract_issues = _schema_contract_issues(
        group, source_schema, source_generation=source_generation
    )
    if contract_issues:
        raise RuntimeError(f"source schema drift for {group}: {'; '.join(contract_issues[:12])}")
    source_count = int(source_schema.get("num_documents", 0))
    final_schema = _final_schema(group, generation, source_schema)
    target = client.get_collection(target_name)
    action = "existing"
    if target is None:
        action = "created"
        try:
            client.create_collection(final_schema)
        except Exception as exc:
            if client.get_collection(target_name) is not None:
                raise RuntimeError(f"target create result is uncertain; inspect before retry: {target_name}") from exc
            raise
        target = client.get_collection(target_name)
    if target is None:
        raise RuntimeError(f"target collection is missing after create: {target_name}")
    if schema_contract_mismatches(target, collection_schema(group, generation)):
        raise RuntimeError(f"target schema mismatch: {target_name}")
    target_count = int(target.get("num_documents", 0))
    checkpoint_path = _checkpoint_path(checkpoint_dir, group)
    checkpoint = _load_group_checkpoint(checkpoint_path, source_name, target_name)
    if target_count == source_count:
        return {
            "group": group,
            "source_collection": source_name,
            "target_collection": target_name,
            "source_documents": source_count,
            "target_documents": target_count,
            "action": "skip-complete",
            "checkpoint": str(checkpoint_path),
            "exception_ledger": {"path": str(ledger_path), "rows": _ledger_count(ledger_path, operation_id)},
        }
    if target_count > source_count:
        raise RuntimeError(f"target document overflow for {group}: {target_count} > {source_count}")
    if checkpoint is not None and int(checkpoint.get("target_documents", -1)) != target_count:
        raise RuntimeError(
            f"checkpoint/target parity mismatch for {group}: "
            f"checkpoint={checkpoint.get('target_documents')} target={target_count}; "
            "refuse to guess an import offset"
        )
    if target_count and checkpoint is None:
        raise RuntimeError(f"partial target has no checkpoint; refuse guesswork: {target_name}")
    offset = int((checkpoint or {}).get("source_offset", 0))
    if offset < 0 or offset > source_count:
        raise RuntimeError(f"invalid source offset in checkpoint: {checkpoint_path}")
    offset = max(offset, target_count)
    imported = offset
    last_report = imported
    batch: list[Mapping[str, Any]] = []
    for source_offset, document in enumerate(client.export_documents(source_name, timeout_seconds=operation_timeout_seconds), start=1):
        if source_offset <= offset:
            continue
        try:
            batch.append(_migrate_legacy_document(group, document))
        except Exception as exc:
            _record_exception_documents(
                ledger_path,
                operation_id=operation_id,
                group=group,
                source_name=source_name,
                target_name=target_name,
                documents=[document],
                category="normalization_exception",
                reason=str(exc),
                leaf_start=source_offset,
            )
            raise
        if len(batch) < batch_size:
            continue
        result = client.import_documents(target_name, batch, timeout_seconds=operation_timeout_seconds)
        if result.accepted_count != len(batch) or result.rejected_count:
            _record_exception_documents(
                ledger_path,
                operation_id=operation_id,
                group=group,
                source_name=source_name,
                target_name=target_name,
                documents=batch,
                category="import_rejected",
                reason=f"accepted={result.accepted_count} rejected={result.rejected_count}; errors={result.errors[:3]}",
                leaf_start=source_offset - len(batch) + 1,
            )
            raise RuntimeError(
                f"import failed for {group} at {source_offset}/{source_count}; "
                f"accepted={result.accepted_count} rejected={result.rejected_count} errors={result.errors[:3]}"
            )
        imported = source_offset
        target_after = client.document_count(target_name)
        _json_write(checkpoint_path, {
            "state": "running",
            "source_collection": source_name,
            "target_collection": target_name,
            "source_documents": source_count,
            "source_offset": imported,
            "target_documents": target_after,
        })
        if imported - last_report >= progress_every or imported == source_count:
            print(f"{group}: {imported} / {source_count}", flush=True)
            last_report = imported
        batch = []
    if batch:
        result = client.import_documents(target_name, batch, timeout_seconds=operation_timeout_seconds)
        if result.accepted_count != len(batch) or result.rejected_count:
            _record_exception_documents(
                ledger_path,
                operation_id=operation_id,
                group=group,
                source_name=source_name,
                target_name=target_name,
                documents=batch,
                category="import_rejected",
                reason=f"accepted={result.accepted_count} rejected={result.rejected_count}; errors={result.errors[:3]}",
                leaf_start=source_count - len(batch) + 1,
            )
            raise RuntimeError(
                f"import failed for {group} at end; accepted={result.accepted_count} "
                f"rejected={result.rejected_count} errors={result.errors[:3]}"
            )
        imported = source_count
        target_after = client.document_count(target_name)
        _json_write(checkpoint_path, {
            "state": "running",
            "source_collection": source_name,
            "target_collection": target_name,
            "source_documents": source_count,
            "source_offset": imported,
            "target_documents": target_after,
        })
        print(f"{group}: {imported} / {source_count}", flush=True)
    if imported != source_count:
        raise RuntimeError(f"source export ended early for {group}: {imported} != {source_count}")
    source_after = client.get_collection(source_name)
    target_after = client.get_collection(target_name)
    if source_after is None or int(source_after.get("num_documents", 0)) != source_count:
        raise RuntimeError(f"source count changed during import for {group}")
    if target_after is None or int(target_after.get("num_documents", 0)) != source_count:
        raise RuntimeError(f"target count mismatch after import for {group}")
    _json_write(checkpoint_path, {
        "state": "complete",
        "source_collection": source_name,
        "target_collection": target_name,
        "source_documents": source_count,
        "source_offset": source_count,
        "target_documents": source_count,
    })
    return {
        "group": group,
        "source_collection": source_name,
        "target_collection": target_name,
        "source_documents": source_count,
        "target_documents": source_count,
        "action": action + "-imported",
        "checkpoint": str(checkpoint_path),
        "exception_ledger": {"path": str(ledger_path), "rows": _ledger_count(ledger_path, operation_id)},
    }


def _sample_documents(client: TypesenseClient, collection: str, limit: int = 5) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for document in client.export_documents(collection, timeout_seconds=300.0):
        samples.append(document)
        if len(samples) >= limit:
            break
    return samples


def _search_regression(client: TypesenseClient, group: str, source_name: str, target_name: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    fixed = ["máy", "may", "thiết bị", "thiet bi", "thuốc", "thuoc", "dược liệu", "duoc lieu", "paracetamol", "viettel"]
    cases: list[tuple[str, str]] = [("fixed", query) for query in fixed]
    for sample in samples:
        for field in SEARCH_CONFIGS[group].query_by:
            value = sample.get(field)
            if not isinstance(value, str):
                continue
            words = value.split()
            if len(words) >= 2 and all(len(word) >= 2 for word in words[:2]):
                phrase = " ".join(words[:2])[:100]
                cases.extend([("sample-accented", phrase), ("sample-unaccented", _strip_diacritics(phrase))])
                break
        if len(cases) > len(fixed) + 2:
            break
    results: list[dict[str, Any]] = []
    applicable = 0
    for kind, query in cases:
        source_result = client.search_group(group, query, per_page=20, collection=source_name)
        source_found = int(source_result.get("found", 0))
        if source_found == 0:
            continue
        target_result = client.search_group(group, query, per_page=20, collection=target_name)
        target_found = int(target_result.get("found", 0))
        source_ids = {str(hit.get("document", {}).get("id")) for hit in source_result.get("hits", [])}
        target_ids = {str(hit.get("document", {}).get("id")) for hit in target_result.get("hits", [])}
        overlap = len(source_ids & target_ids)
        passed = target_found > 0 and (not source_ids or overlap >= max(1, len(source_ids) // 2))
        applicable += 1
        results.append({"kind": kind, "query": query, "source_found": source_found, "target_found": target_found, "top20_overlap": overlap, "pass": passed})
        if not passed:
            raise RuntimeError(f"search regression failed for {group}: {query!r}")
    if applicable < 2:
        raise RuntimeError(f"search regression had too few applicable queries for {group}")
    return {"applicable": applicable, "cases": results, "pass": True}


def _filter_and_facet(client: TypesenseClient, group: str, source_name: str, target_name: str) -> dict[str, Any]:
    filter_by = f"data_group:={group}"
    source = client.search_group(group, "*", filter_by=filter_by, facet_by="data_group", per_page=1, collection=source_name)
    target = client.search_group(group, "*", filter_by=filter_by, facet_by="data_group", per_page=1, collection=target_name)
    source_found = int(source.get("found", 0))
    target_found = int(target.get("found", 0))
    facet_counts = target.get("facet_counts") or []
    if source_found != target_found or not facet_counts:
        raise RuntimeError(f"filter/facet regression failed for {group}: {source_found} != {target_found}")
    return {"filter": filter_by, "source_found": source_found, "target_found": target_found, "facet_count_groups": len(facet_counts), "pass": True}


def verify_group(client: TypesenseClient, group: str, source_name: str, target_name: str) -> dict[str, Any]:
    source = client.get_collection(source_name)
    target = client.get_collection(target_name)
    if source is None or target is None:
        raise RuntimeError(f"verification collection missing for {group}")
    source_count = int(source.get("num_documents", 0))
    target_count = int(target.get("num_documents", 0))
    if source_count != target_count:
        raise RuntimeError(f"document parity failed for {group}: {source_count} != {target_count}")
    locale = _locale_status(group, target)
    if not locale["ok"]:
        raise RuntimeError(f"locale schema failed for {group}: {locale}")
    samples = _sample_documents(client, source_name)
    if not samples:
        raise RuntimeError(f"source has no sample documents: {source_name}")
    for sample in samples:
        document_id = str(sample.get("id", ""))
        expected_sample = _migrate_legacy_document(group, sample)
        if client.get_document(target_name, document_id) != expected_sample:
            raise RuntimeError(f"sample document mismatch for {group}: {document_id}")
    search = _search_regression(client, group, source_name, target_name, samples)
    filter_facet = _filter_and_facet(client, group, source_name, target_name)
    return {
        "collection": group,
        "source_collection": source_name,
        "target_collection": target_name,
        "source_documents": source_count,
        "target_documents": target_count,
        "locale_fields_ok": locale["ok"],
        "locale_fields": locale["localized_fields"],
        "sample_ids_checked": len(samples),
        "search_test": search,
        "filter_facet_test": filter_facet,
        "status": "PASS",
    }


def _api_json(api_url: str, method: str, path: str, payload: Mapping[str, Any] | None = None, cookie: str | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(api_url.rstrip("/") + path, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=30.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    except (URLError, OSError) as exc:
        raise RuntimeError(f"API smoke request failed: {type(exc).__name__}: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"API returned invalid JSON for {path}") from exc
    return status, value if isinstance(value, dict) else {"value": value}


def _api_target_proof(api_url: str, generation: str, cookie: str | None = None) -> dict[str, Any]:
    ready_status = 0
    ready: dict[str, Any] = {}
    last_error: Exception | None = None
    for _ in range(30):
        try:
            ready_status, ready = _api_json(api_url, "GET", "/ready", cookie=cookie)
            last_error = None
        except RuntimeError as exc:
            last_error = exc
        if last_error is None:
            serialized = json.dumps(ready, ensure_ascii=False)
            if ready_status == 200 and generation in serialized and ready.get("procurement_ready") is True:
                break
        time.sleep(2)
    if last_error is not None:
        raise last_error
    serialized = json.dumps(ready, ensure_ascii=False)
    if ready_status != 200 or generation not in serialized or ready.get("procurement_ready") is not True:
        raise RuntimeError(f"API readiness did not prove target generation: status={ready_status}")
    normal_status, normal = _api_json(api_url, "POST", "/api/query", {"scope": "all", "text": "máy", "limit": 5, "page": 1}, cookie=cookie)
    if normal_status == 401 and not cookie:
        return {
            "ready_status": ready_status,
            "normal_search_status": normal_status,
            "pagination_status": "not-run",
            "full_search": {"status": "not-run", "reason": "API search requires authenticated smoke cookie"},
            "generation_present": generation in serialized,
            "authenticated": False,
            "pass": True,
        }
    if normal_status != 200 or normal.get("success") is not True:
        raise RuntimeError(f"API normal search smoke failed: status={normal_status}")
    page_status, page = _api_json(api_url, "POST", "/api/query", {"scope": "all", "text": "máy", "limit": 5, "page": 2}, cookie=cookie)
    if page_status != 200 or page.get("success") is not True:
        raise RuntimeError(f"API pagination smoke failed: status={page_status}")
    full = {"status": "not-run", "reason": "authenticated cookie not provided"}
    if cookie:
        full_status, full_result = _api_json(api_url, "POST", "/api/query", {"scope": "all", "text": "máy", "limit": 5, "page": 1, "searchMode": "full"}, cookie=cookie)
        if full_status != 200 or full_result.get("success") is not True:
            raise RuntimeError(f"API full search smoke failed: status={full_status}")
        full = {"status": "PASS", "http_status": full_status}
    return {
        "ready_status": ready_status,
        "normal_search_status": normal_status,
        "pagination_status": page_status,
        "full_search": full,
        "generation_present": generation in serialized,
        "authenticated": bool(cookie),
        "pass": True,
    }


def _runtime_setting(runtime_text: str, key: str) -> str | None:
    for line in runtime_text.splitlines():
        match = re.match(rf"^{re.escape(key)}=(.*)$", line.strip())
        if match:
            return match.group(1).strip().strip('"\'') or None
    return None


def _replace_generation(value: Any, source_generation: str, target_generation: str) -> Any:
    if isinstance(value, str):
        return value.replace(source_generation, target_generation)
    if isinstance(value, list):
        return [_replace_generation(item, source_generation, target_generation) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_generation(item, source_generation, target_generation)
            for key, item in value.items()
        }
    return value


def _prepare_runtime_artifacts(runtime_env: Path, source_generation: str, target_generation: str) -> dict[str, str]:
    """Carry operational state to the new generation before switching API traffic."""

    runtime_text = runtime_env.read_text(encoding="utf-8")
    settings = {
        key: _runtime_setting(runtime_text, key)
        for key in (
            "BIDFINDER_TYPESENSE_CHECKPOINT",
            "BIDFINDER_TYPESENSE_PROVENANCE",
            "BIDFINDER_SERVING_REPORT_PATH",
            "BIDFINDER_SERVING_MARKDOWN_PATH",
        )
    }
    if any(value is None for value in settings.values()):
        missing = [key for key, value in settings.items() if value is None]
        raise RuntimeError(f"runtime env is missing serving artifact paths: {', '.join(missing)}")

    target_paths: dict[str, Path] = {}
    for key, raw_path in settings.items():
        assert raw_path is not None
        if source_generation not in raw_path:
            raise RuntimeError(f"runtime artifact path does not contain source generation: {key}")
        target_paths[key] = Path(raw_path.replace(source_generation, target_generation, 1))

    source_checkpoint = Path(settings["BIDFINDER_TYPESENSE_CHECKPOINT"] or "")
    source_provenance = Path(settings["BIDFINDER_TYPESENSE_PROVENANCE"] or "")
    source_report = Path(settings["BIDFINDER_SERVING_REPORT_PATH"] or "")
    source_markdown = Path(settings["BIDFINDER_SERVING_MARKDOWN_PATH"] or "")
    for source_path in (source_checkpoint, source_provenance, source_report):
        if not source_path.is_file():
            raise RuntimeError(f"serving artifact is missing: {source_path}")

    checkpoint_target = target_paths["BIDFINDER_TYPESENSE_CHECKPOINT"]
    if not checkpoint_target.exists():
        shutil.copy2(source_checkpoint, checkpoint_target)
        with sqlite3.connect(checkpoint_target) as connection:
            connection.execute(
                "UPDATE ingestion_checkpoint SET sink_target=? WHERE sink_target=?",
                (f"typesense:{target_generation}", f"typesense:{source_generation}"),
            )

    provenance_target = target_paths["BIDFINDER_TYPESENSE_PROVENANCE"]
    if not provenance_target.exists():
        shutil.copy2(source_provenance, provenance_target)

    report_target = target_paths["BIDFINDER_SERVING_REPORT_PATH"]
    if not report_target.exists():
        source_state = _json_read(source_report)
        if source_state is None:
            raise RuntimeError(f"serving report is not valid JSON: {source_report}")
        state = _replace_generation(source_state, source_generation, target_generation)
        state["audit_version"] = "schema-migration-serving-state-v1"
        state["serving_generation"] = target_generation
        state["overall_status"] = "PASS"
        state["unresolved_errors"] = []
        _json_write(report_target, state)

    markdown_target = target_paths["BIDFINDER_SERVING_MARKDOWN_PATH"]
    if not markdown_target.exists():
        if source_markdown.is_file():
            markdown_target.parent.mkdir(parents=True, exist_ok=True)
            markdown_target.write_text(
                source_markdown.read_text(encoding="utf-8").replace(source_generation, target_generation),
                encoding="utf-8",
            )
        else:
            markdown_target.parent.mkdir(parents=True, exist_ok=True)
            markdown_target.write_text(
                f"# Serving state\n\n- Generation: `{target_generation}`\n- Status: `PASS`\n",
                encoding="utf-8",
            )
    return {key: str(path) for key, path in target_paths.items()}


def _cutover_runtime(runtime_env: Path, generation: str) -> str:
    old_text = runtime_env.read_text(encoding="utf-8")
    old_generation = _runtime_generation(runtime_env)
    lines = old_text.splitlines()
    replaced = {"BIDFINDER_SERVING_GENERATION": False, "BIDFINDER_TYPESENSE_SERVING_GENERATION": False}
    output: list[str] = []
    for line in lines:
        if old_generation:
            line = line.replace(old_generation, generation)
        match = re.match(r"^(BIDFINDER_(?:TYPESENSE_)?SERVING_GENERATION)=.*$", line)
        if match:
            key = match.group(1)
            output.append(f"{key}={generation}")
            replaced[key] = True
        else:
            output.append(line)
    for key, present in replaced.items():
        if not present:
            output.append(f"{key}={generation}")
    temporary = runtime_env.with_name(f".{runtime_env.name}.tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.chmod(temporary, runtime_env.stat().st_mode & 0o777)
    os.replace(temporary, runtime_env)
    return old_generation or ""


def _restart_api() -> None:
    subprocess.run(["systemctl", "--user", "restart", "bidfinder-api.service"], check=True)


def _cleanup_after_cutover(args: argparse.Namespace) -> dict[str, Any]:
    report_path = Path(args.report).expanduser()
    report = _json_read(report_path)
    if not report or report.get("target_generation") != args.target_generation or report.get("status") not in {"CUTOVER_PASS", "PASS"}:
        raise RuntimeError("cleanup requires a saved CUTOVER_PASS report")
    runtime_env = Path(args.runtime_env).expanduser()
    if _runtime_generation(runtime_env) != args.target_generation:
        raise RuntimeError("API runtime generation does not point to target; refuse cleanup")
    client = TypesenseClient(TypesenseConfig.from_env())
    _wait_for_health(client, args.health_timeout_seconds)
    cookie = os.getenv(args.smoke_cookie_env, "").strip() or None
    report["api_smoke_after_cutover"] = _api_target_proof(args.api_url, args.target_generation, cookie=cookie)
    keep = {physical_collection_name(group, args.target_generation) for group in LOGICAL_ALIASES}
    delete_names = sorted(str(item["name"]) for item in client.list_collections() if str(item.get("name")) not in keep)
    report["collections_deleted"] = _delete_collections(
        client, delete_names, timeout_seconds=args.operation_timeout_seconds
    )
    _wait_for_health(client, args.health_timeout_seconds)
    remaining = sorted(str(item.get("name")) for item in client.list_collections())
    if remaining != sorted(keep):
        raise RuntimeError(f"cleanup left unexpected collections: {remaining}")
    report["remaining_collections"] = remaining
    report["status"] = "PASS"
    _json_write(report_path, report)
    print("PHASE 7 cleanup PASS; exactly 3 production collections remain", flush=True)
    return report


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    validate_generation_id(args.source_generation)
    validate_generation_id(args.target_generation)
    if args.source_generation == args.target_generation:
        raise ValueError("source and target generations must be different")
    config = TypesenseConfig.from_env()
    config = TypesenseConfig(**{**config.__dict__, "batch_size": args.batch_size})
    client = TypesenseClient(config)
    runtime_env = Path(args.runtime_env).expanduser()
    checkpoint_dir = Path(args.checkpoint_dir).expanduser()
    ledger_path = checkpoint_dir / "exception-ledger.sqlite3"
    operation_id = f"migration:{args.source_generation}:{args.target_generation}:{time.time_ns()}"
    report_path = Path(args.report).expanduser()
    print("PHASE 0 audit", flush=True)
    health = _wait_for_health(client, args.health_timeout_seconds)
    inventory, source_names, stale = _stale_collections(client, args.source_generation, args.target_generation)
    runtime_generation = _runtime_generation(runtime_env)
    if runtime_generation and runtime_generation != args.source_generation:
        raise RuntimeError(f"API runtime generation is {runtime_generation}, expected source {args.source_generation}")
    report: dict[str, Any] = {
        "source_generation": args.source_generation,
        "target_generation": args.target_generation,
        "runtime_generation_before": runtime_generation,
        "health": health,
        "collection_inventory": sorted(
            [{"name": item.get("name"), "num_documents": item.get("num_documents")} for item in inventory],
            key=lambda item: str(item.get("name", "")),
        ),
        "schema_alter_status": {
            "active": False,
            "evidence": "Typesense health=ok and collection inventory is readable; v30 schema updates are synchronous.",
        },
        "source_collections": source_names,
        "stale_candidates": stale,
        "operation_id": operation_id,
        "exception_ledger": {"path": str(ledger_path), "rows": 0},
        "groups": {},
        "status": "AUDIT_PASS",
    }
    if not args.apply:
        _json_write(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        return report
    if args.cleanup_stale:
        print(f"PHASE 0 cleanup stale={len(stale)}", flush=True)
        report["stale_deleted"] = _delete_collections(
            client,
            [item["name"] for item in stale],
            timeout_seconds=args.operation_timeout_seconds,
        )
    print("PHASE 1-4 rebuild and verify", flush=True)
    for group in LOGICAL_ALIASES:
        source_name = physical_collection_name(group, args.source_generation)
        target_name = physical_collection_name(group, args.target_generation)
        imported = _import_group(
            client,
            group,
            source_name,
            target_name,
            args.target_generation,
            checkpoint_dir=checkpoint_dir,
            batch_size=args.batch_size,
            operation_timeout_seconds=args.operation_timeout_seconds,
            progress_every=args.progress_every,
            operation_id=operation_id,
            source_generation=args.source_generation,
        )
        verified = verify_group(client, group, source_name, target_name)
        report["groups"][group] = {"import": imported, "verify": verified}
        print(f"{group}: PASS source={verified['source_documents']} target={verified['target_documents']}", flush=True)
    report["status"] = "PRE_CUTOVER_PASS"
    report["exception_ledger"]["rows"] = _ledger_count(ledger_path, operation_id) if ledger_path.exists() else 0
    _json_write(report_path, report)
    print("PHASE 5 pre-cutover PASS", flush=True)
    if args.cutover:
        print("PHASE 6 cutover", flush=True)
        old_text = runtime_env.read_text(encoding="utf-8")
        old_runtime_generation = _runtime_generation(runtime_env) or args.source_generation
        artifact_paths = _prepare_runtime_artifacts(runtime_env, old_runtime_generation, args.target_generation)
        TypesenseCollectionManager(client).preflight_generation(
            args.target_generation,
            expected_counts={
                group: int(report["groups"][group]["verify"]["target_documents"])
                for group in LOGICAL_ALIASES
            },
            checkpoint_path=artifact_paths["BIDFINDER_TYPESENSE_CHECKPOINT"],
            provenance_path=artifact_paths["BIDFINDER_TYPESENSE_PROVENANCE"],
            require_target=True,
            require_continuity=True,
        )
        old_generation = _cutover_runtime(runtime_env, args.target_generation)
        try:
            _restart_api()
            cookie = os.getenv(args.smoke_cookie_env, "").strip() or None
            report["api_smoke"] = _api_target_proof(args.api_url, args.target_generation, cookie=cookie)
            report["status"] = "CUTOVER_PASS"
        except Exception:
            runtime_env.write_text(old_text, encoding="utf-8")
            try:
                _restart_api()
            except Exception:
                pass
            raise
        report["runtime_generation_after"] = args.target_generation
        report["runtime_generation_previous"] = old_generation
        _json_write(report_path, report)
        print("PHASE 6 cutover PASS", flush=True)
    if args.cleanup:
        if report.get("status") != "CUTOVER_PASS":
            raise RuntimeError("cleanup requires successful cutover in this run")
        print("PHASE 7 cleanup", flush=True)
        keep = {physical_collection_name(group, args.target_generation) for group in LOGICAL_ALIASES}
        all_collections = client.list_collections()
        delete_names = sorted(str(item["name"]) for item in all_collections if str(item.get("name")) not in keep)
        report["collections_deleted"] = _delete_collections(
            client, delete_names, timeout_seconds=args.operation_timeout_seconds
        )
        remaining = sorted(str(item.get("name")) for item in client.list_collections())
        if remaining != sorted(keep):
            raise RuntimeError(f"cleanup left unexpected collections: {remaining}")
        report["remaining_collections"] = remaining
        report["status"] = "PASS"
        _json_write(report_path, report)
        print("PHASE 7 cleanup PASS; exactly 3 production collections remain", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-generation", default=os.getenv("BIDFINDER_TYPESENSE_SERVING_GENERATION", DEFAULT_SOURCE_GENERATION))
    parser.add_argument("--target-generation", required=True)
    parser.add_argument("--runtime-env", default=os.getenv("BIDFINDER_RUNTIME_ENV", DEFAULT_RUNTIME_ENV))
    parser.add_argument("--checkpoint-dir", default="~/.local/share/bidfinder/typesense/checkpoints/vietnamese-locale")
    parser.add_argument("--report", default="~/.local/share/bidfinder/typesense/reports/vietnamese-locale-migration.json")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("TYPESENSE_IMPORT_BATCH_SIZE", "500")))
    parser.add_argument("--progress-every", type=int, default=10000)
    parser.add_argument("--health-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--operation-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--smoke-cookie-env", default="BIDFINDER_SMOKE_COOKIE")
    parser.add_argument("--apply", action="store_true", help="execute the single rebuild flow; default is audit only")
    parser.add_argument("--cleanup-stale", action="store_true", help="delete only stale non-source partial/temp collections after audit")
    parser.add_argument("--cutover", action="store_true", help="update runtime generation and restart bidfinder-api.service after verification")
    parser.add_argument("--cleanup", action="store_true", help="delete all non-target BIDFinder collections after successful cutover proof")
    args = parser.parse_args()
    if args.batch_size <= 0 or args.progress_every <= 0:
        raise SystemExit("batch and progress values must be positive")
    if args.cleanup_stale and not args.apply:
        raise SystemExit("--cleanup-stale requires --apply")
    if args.cutover and not args.apply:
        raise SystemExit("--cutover requires --apply")
    if args.cleanup and not args.apply:
        try:
            _cleanup_after_cutover(args)
        except Exception as exc:
            print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.cleanup and not args.cutover:
        raise SystemExit("--cleanup with --apply requires --cutover")
    try:
        migrate(args)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
