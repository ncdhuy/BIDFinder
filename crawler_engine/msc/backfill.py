"""Historical backfill readiness, control-plane, and audit helpers.

This module deliberately sits above :mod:`engine`: retrieval, partitioning,
normalization, and Typesense import remain owned by the Phase 2/3A code.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from .checkpoint import Checkpoint, CheckpointStore
from .config import (
    DEFAULT_TYPESENSE_BATCH_SIZE,
    ENGINE_VERSION,
    SCHEMA_VERSION,
)
from .contracts import (
    SOURCE_CONTRACTS,
    SOURCE_COVERAGE_REGISTRY_VERSION,
    SOURCE_COVERAGE_FLOORS,
    get_contract,
)
from .engine import MSCIngestionEngine, operational_today, parse_partition_date
from .models import IngestionStatus, PartitionContext, PartitionResult, SearchInterval, SinkWriteResult
from .sink import Sink
from .typesense_client import (
    TYPESENSE_ALIAS_ERROR,
    TYPESENSE_CONNECT_ERROR,
    TYPESENSE_IDENTITY_CONFLICT,
    TYPESENSE_IMPORT_ERROR,
    TYPESENSE_PARTIAL_IMPORT,
    TYPESENSE_SCHEMA_ERROR,
    TypesenseClient,
    TypesenseCollectionManager,
    TypesenseError,
)
from .typesense_schema import SEARCH_CONFIGS, canonical_to_typesense_document, physical_collection_name, schema_for_group, validate_generation_id
from .partitioning import official_day_interval
from .local_target import FULL_RUN_AUTHORIZATION_PHRASE

BACKFILL_MANIFEST_VERSION = "msc-backfill-plan-v1"
BACKFILL_REPORT_VERSION = "msc-backfill-report-v1"
HISTORICAL_START = date(2023, 2, 1)
LOGICAL_GROUPS = ("goods", "medicines", "traditional_medicine")
DEFAULT_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "docs" / "msc-contracts"
DEFAULT_SAFETY_MARGIN = 0.50
_STALE_RUNNING_SECONDS = 3600


class BackfillControlError(ValueError):
    """Invalid or unsafe backfill control-plane input."""


def require_full_run_authorization(value: str | None) -> None:
    """Require an explicit phrase before any historical write is allowed."""

    if value != FULL_RUN_AUTHORIZATION_PHRASE:
        raise BackfillControlError(
            "actual historical backfill requires --authorize-full-run "
            f"{FULL_RUN_AUTHORIZATION_PHRASE}"
        )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return value.value
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def ordered_source_keys(source_keys: Iterable[str] | None = None) -> tuple[str, ...]:
    requested = set(SOURCE_CONTRACTS if source_keys is None else source_keys)
    unknown = requested - set(SOURCE_CONTRACTS)
    if unknown:
        raise BackfillControlError(f"unknown source key(s): {', '.join(sorted(unknown))}")
    return tuple(key for key in SOURCE_CONTRACTS if key in requested)


def validate_closed_range(from_date: str | date, to_date: str | date) -> tuple[date, date]:
    start = parse_partition_date(from_date)
    end = parse_partition_date(to_date)
    if start > end:
        raise BackfillControlError("from date cannot be after to date")
    if end >= operational_today():
        raise BackfillControlError("backfill range must end before the current Vietnam calendar day")
    return start, end


def iter_parent_partitions(
    from_date: str | date,
    to_date: str | date,
    source_keys: Iterable[str],
) -> Iterable[tuple[str, str]]:
    start, end = validate_closed_range(from_date, to_date)
    sources = ordered_source_keys(source_keys)
    day = start
    while day <= end:
        for source_key in sources:
            yield source_key, day.isoformat()
        day += timedelta(days=1)


def closed_range_interval(from_date: str | date, to_date: str | date) -> SearchInterval:
    start, end = validate_closed_range(from_date, to_date)
    first = official_day_interval(start)
    last = official_day_interval(end)
    return SearchInterval(first.from_value, last.to_value, depth=0)


def group_totals(source_totals: Mapping[str, int]) -> dict[str, int]:
    result = {group: 0 for group in LOGICAL_GROUPS}
    for source_key, value in source_totals.items():
        result[get_contract(source_key).data_group] += int(value)
    return result


def source_contract_payload(source_key: str) -> dict[str, Any]:
    contract = get_contract(source_key)
    return _jsonable(contract)


def source_contract_fingerprints(source_keys: Iterable[str] | None = None) -> dict[str, str]:
    return {
        key: fingerprint(source_contract_payload(key))
        for key in ordered_source_keys(source_keys)
    }


def canonical_schema_payload(group: str, source_keys: Iterable[str] | None = None) -> dict[str, Any]:
    if group not in LOGICAL_GROUPS:
        raise BackfillControlError(f"unknown logical group: {group}")
    contracts = [get_contract(key) for key in ordered_source_keys(source_keys) if get_contract(key).data_group == group]
    mappings = {
        contract.key: [
            {"canonical_key": item.canonical_key, "source_field": item.source_field, "optional": item.optional}
            for item in contract.canonical_mapping
        ]
        for contract in contracts
    }
    fields = sorted({item.canonical_key for contract in contracts for item in contract.canonical_mapping})
    return {"logical_group": group, "fields": fields, "source_mappings": mappings}


def canonical_schema_fingerprints(source_keys: Iterable[str] | None = None) -> dict[str, str]:
    return {
        group: fingerprint(canonical_schema_payload(group, source_keys))
        for group in LOGICAL_GROUPS
    }


def typesense_schema_payload(group: str) -> dict[str, Any]:
    return {
        "schema": schema_for_group(group),
        "search": _jsonable(SEARCH_CONFIGS[group]),
    }


def typesense_schema_fingerprints() -> dict[str, str]:
    return {group: fingerprint(typesense_schema_payload(group)) for group in LOGICAL_GROUPS}


def build_manifest(
    from_date: str | date,
    to_date: str | date,
    generation: str,
    source_totals: Mapping[str, int],
    *,
    page_size: int = 1000,
    typesense_batch_size: int = DEFAULT_TYPESENSE_BATCH_SIZE,
    safe_search_threshold: int = 9500,
    created_at: str | None = None,
    source_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    start, end = validate_closed_range(from_date, to_date)
    validate_generation_id(generation)
    if page_size <= 0 or typesense_batch_size <= 0 or safe_search_threshold <= 0:
        raise BackfillControlError("page_size, typesense_batch_size, and safe_search_threshold must be positive")
    sources = ordered_source_keys(source_keys)
    missing = set(sources) - set(source_totals)
    if missing:
        raise BackfillControlError(f"source totals missing: {', '.join(sorted(missing))}")
    normalized_totals = {key: int(source_totals[key]) for key in sources}
    if any(value < 0 for value in normalized_totals.values()):
        raise BackfillControlError("source totals must be non-negative")
    groups = group_totals(normalized_totals)
    return {
        "manifest_version": BACKFILL_MANIFEST_VERSION,
        "generation": generation,
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "source_range": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "closed_upper_boundary": True,
            "calendar": "Asia/Ho_Chi_Minh",
        },
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": list(sources),
        "source_coverage_registry_version": SOURCE_COVERAGE_REGISTRY_VERSION,
        "source_coverage_floors": {
            key: SOURCE_COVERAGE_FLOORS[key].isoformat() for key in sources
        },
        "source_totals": normalized_totals,
        "group_totals": groups,
        "expected_overall_total": sum(normalized_totals.values()),
        "page_size": int(page_size),
        "typesense_batch_size": int(typesense_batch_size),
        "safe_msc_search_threshold": int(safe_search_threshold),
        "source_contract_fingerprints": source_contract_fingerprints(sources),
        "canonical_schema_fingerprints": canonical_schema_fingerprints(sources),
        "typesense_schema_fingerprints": typesense_schema_fingerprints(),
    }


def verify_manifest(manifest: Mapping[str, Any], *, generation: str | None = None) -> None:
    if manifest.get("manifest_version") != BACKFILL_MANIFEST_VERSION:
        raise BackfillControlError("unsupported or missing backfill manifest version")
    if generation is not None and manifest.get("generation") != generation:
        raise BackfillControlError("manifest generation does not match requested generation")
    sources = ordered_source_keys(manifest.get("sources", ()))
    if manifest.get("source_contract_fingerprints") != source_contract_fingerprints(sources):
        raise BackfillControlError("source contract fingerprints do not match current frozen contracts")
    if manifest.get("canonical_schema_fingerprints") != canonical_schema_fingerprints(sources):
        raise BackfillControlError("canonical schema fingerprints do not match current schema")
    if manifest.get("typesense_schema_fingerprints") != typesense_schema_fingerprints():
        raise BackfillControlError("Typesense schema fingerprints do not match current schema")


def source_population_preflight(
    client: Any,
    from_date: str | date,
    to_date: str | date,
    source_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Read exactly one aggregation count per selected source contract."""

    start, end = validate_closed_range(from_date, to_date)
    sources = ordered_source_keys(source_keys)
    interval = closed_range_interval(start, end)
    request_before = getattr(getattr(client, "stats", None), "request_count", 0)
    totals: dict[str, int] = {}
    for source_key in sources:
        totals[source_key] = int(client.count_interval(get_contract(source_key), interval))
    request_after = getattr(getattr(client, "stats", None), "request_count", request_before)
    groups = group_totals(totals)
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "closed": True},
        "source_totals": totals,
        "group_totals": groups,
        "overall_total": sum(totals.values()),
        "msc_requests": request_after - request_before,
        "records_paginated": False,
    }


def reconcile_completed_prefix(
    client: Any,
    store: CheckpointStore,
    source_key: str,
    from_date: str | date,
    to_date: str | date,
    sink_target: str,
) -> dict[str, Any]:
    """Locate completed-date count drift with deterministic count-only splits."""

    start, end = validate_closed_range(from_date, to_date)
    checkpoints = {
        row.partition_date: row
        for row in store.list(sink_target)
        if row.source_key == source_key
    }
    prefix_end: date | None = None
    day = start
    while day <= end:
        checkpoint = checkpoints.get(day.isoformat())
        if checkpoint is None or checkpoint.status != IngestionStatus.COMPLETED:
            break
        prefix_end = day
        day += timedelta(days=1)
    if prefix_end is None:
        return {
            "source_key": source_key,
            "status": "NO_COMPLETED_PREFIX",
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "prefix_end": None,
            "checkpoint_sum": 0,
            "observed_count": 0,
            "requests": 0,
            "intervals": [],
            "changed_partitions": [],
        }

    intervals: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    def stored_sum(left: date, right: date) -> int:
        cursor = left
        total = 0
        while cursor <= right:
            checkpoint = checkpoints.get(cursor.isoformat())
            if checkpoint and checkpoint.status == IngestionStatus.COMPLETED:
                total += int(checkpoint.parent_pre_count or 0)
            cursor += timedelta(days=1)
        return total

    def visit(left: date, right: date) -> int:
        stored = stored_sum(left, right)
        observed = int(client.count_interval(get_contract(source_key), closed_range_interval(left, right)))
        node = {
            "from": left.isoformat(),
            "to": right.isoformat(),
            "checkpoint_sum": stored,
            "current_count": observed,
        }
        intervals.append(node)
        if stored == observed:
            node["status"] = "CLEAN"
            return observed
        if left == right:
            node["status"] = "CHANGED"
            checkpoint = checkpoints.get(left.isoformat())
            if checkpoint and checkpoint.status == IngestionStatus.COMPLETED:
                changed.append({
                    "source_key": source_key,
                    "partition_date": left.isoformat(),
                    "previous_count": int(checkpoint.parent_pre_count or 0),
                    "current_count": observed,
                    "delta": observed - int(checkpoint.parent_pre_count or 0),
                })
            return observed
        midpoint = left + (right - left) // 2
        visit(left, midpoint)
        visit(midpoint + timedelta(days=1), right)
        node["status"] = "SPLIT"
        return observed

    observed_count = visit(start, prefix_end)
    checkpoint_sum = stored_sum(start, prefix_end)
    return {
        "source_key": source_key,
        "status": "CHANGED" if changed else "CLEAN",
        "range": {"from": start.isoformat(), "to": prefix_end.isoformat()},
        "prefix_end": prefix_end.isoformat(),
        "checkpoint_sum": checkpoint_sum,
        "observed_count": observed_count,
        "requests": len(intervals),
        "intervals": intervals,
        "changed_partitions": changed,
    }


def _extract_fixture_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        page = payload.get("page")
        if isinstance(page, dict) and isinstance(page.get("content"), list):
            return [item for item in page["content"] if isinstance(item, dict)]
        if isinstance(payload.get("content"), list):
            return [item for item in payload["content"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def load_fixture_samples(
    sample_dir: str | Path = DEFAULT_SAMPLE_DIR,
    *,
    sample_limit: int = 100,
    sample_date: str = "2026-08-28",
    source_keys: Iterable[str] | None = None,
) -> dict[str, tuple[dict[str, Any], ...]]:
    from .normalize import normalize_record

    if sample_limit <= 0:
        raise BackfillControlError("sample_limit must be positive")
    root = Path(sample_dir)
    samples: dict[str, tuple[dict[str, Any], ...]] = {}
    for source_key in ordered_source_keys(source_keys):
        path = root / get_contract(source_key).fixture_slug / "search-response-sample.json"
        if not path.exists():
            raise BackfillControlError(f"sample fixture missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        normalized = [
            normalize_record(get_contract(source_key), raw, sample_date)
            for raw in _extract_fixture_records(payload)[:sample_limit]
        ]
        if not normalized:
            raise BackfillControlError(f"sample fixture has no records: {path}")
        samples[source_key] = tuple(normalized)
    return samples


def field_index_classification(group: str) -> dict[str, str]:
    query_by = set(SEARCH_CONFIGS[group].query_by)
    result: dict[str, str] = {}
    for field in schema_for_group(group)["fields"]:
        name = field["name"]
        labels = []
        if name in query_by:
            labels.append("full-text searchable")
        if field.get("facet"):
            labels.append("filterable/facet")
        if field.get("sort"):
            labels.append("sortable")
        result[name] = ", ".join(labels) if labels else "display-only"
    return result


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def estimate_capacity(
    source_totals: Mapping[str, int],
    samples_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    typesense_batch_size: int = DEFAULT_TYPESENSE_BATCH_SIZE,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
) -> dict[str, Any]:
    if not 0 <= safety_margin < 10:
        raise BackfillControlError("safety_margin must be between 0 and 10")
    if typesense_batch_size <= 0:
        raise BackfillControlError("typesense_batch_size must be positive")
    source_keys = ordered_source_keys(source_totals)
    per_group: dict[str, dict[str, Any]] = {}
    overall_raw = overall_indexed = 0
    sample_total = 0
    for group in LOGICAL_GROUPS:
        raw_sizes: list[int] = []
        indexed_sizes: list[int] = []
        sample_sources = []
        indexed_names = {
            field["name"]
            for field in schema_for_group(group)["fields"]
            if field["name"] in set(SEARCH_CONFIGS[group].query_by)
            or field.get("facet")
            or field.get("sort")
        }
        for source_key in source_keys:
            contract = get_contract(source_key)
            if contract.data_group != group:
                continue
            records = tuple(samples_by_source.get(source_key, ()))
            for record in records:
                document = canonical_to_typesense_document(record, group)
                indexed = {key: value for key, value in document.items() if key in indexed_names}
                raw_sizes.append(len(canonical_json(record).encode("utf-8")))
                indexed_sizes.append(len(canonical_json(indexed).encode("utf-8")))
            if records:
                sample_sources.append(source_key)
        if not raw_sizes:
            raise BackfillControlError(f"no capacity samples for logical group: {group}")
        count = sum(int(source_totals[key]) for key in source_keys if get_contract(key).data_group == group)
        avg_raw = sum(raw_sizes) / len(raw_sizes)
        avg_indexed = sum(indexed_sizes) / len(indexed_sizes)
        projected_raw = round(count * avg_raw)
        projected_indexed = round(count * avg_indexed)
        overall_raw += projected_raw
        overall_indexed += projected_indexed
        sample_total += len(raw_sizes)
        per_group[group] = {
            "sampled_canonical_documents": len(raw_sizes),
            "sample_sources": sample_sources,
            "canonical_document_bytes": {
                "average": round(avg_raw, 2),
                "p50_like": _percentile(raw_sizes, 0.50),
                "p95_like": _percentile(raw_sizes, 0.95),
            },
            "indexed_searchable_filterable_sortable_bytes": {
                "average": round(avg_indexed, 2),
                "p50_like": _percentile(indexed_sizes, 0.50),
                "p95_like": _percentile(indexed_sizes, 0.95),
                "fields": sorted(indexed_names),
            },
            "projected_raw_dataset_bytes": projected_raw,
            "projected_indexed_field_bytes": projected_indexed,
            "keyword_search_ram_estimate_bytes": {
                "minimum_2x": projected_indexed * 2,
                "upper_3x": projected_indexed * 3,
                "estimate_only": True,
            },
            "minimum_raw_data_disk_bytes": projected_raw,
            "raw_disk_with_operational_margin_bytes": round(projected_raw * (1 + safety_margin)),
            "field_classification": field_index_classification(group),
        }
    return {
        "estimate_only": True,
        "sample_total": sample_total,
        "safety_margin": {"fraction": safety_margin, "applies_to": "raw disk recommendation only"},
        "groups": per_group,
        "overall": {
            "projected_raw_dataset_bytes": overall_raw,
            "projected_indexed_field_bytes": overall_indexed,
            "keyword_search_ram_estimate_bytes": {
                "minimum_2x": overall_indexed * 2,
                "upper_3x": overall_indexed * 3,
                "estimate_only": True,
            },
            "minimum_raw_data_disk_bytes": overall_raw,
            "raw_disk_with_operational_margin_bytes": round(overall_raw * (1 + safety_margin)),
            "estimated_typesense_batches": math.ceil(sum(int(value) for value in source_totals.values()) / typesense_batch_size),
        },
        "production_recommendation": {
            "preferred_target": "Typesense Cloud with HA enabled",
            "alternative": "self-hosted Typesense 30.2 HA with persistent SSD",
            "self_hosted_starting_shape": {
                "nodes": 3,
                "ram_gb_per_node": 32,
                "vcpus_per_node": "4-8",
                "persistent_ssd_gb_per_node": 200,
            },
            "scale_threshold": "review when sustained RAM exceeds 80% or free SSD falls below 40%; validate with a larger sample",
            "basis": "current projection plus operational headroom; not a guarantee",
        },
        "operational_note": "RAM rule of thumb is keyword-search RAM ~= 2x-3x indexed/searchable/filterable field bytes; benchmark before sizing production.",
    }


def atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


class UUIDConflictError(OSError):
    code = TYPESENSE_IDENTITY_CONFLICT


class UUIDProvenanceStore:
    """Disk-backed UUID identity/content audit; never holds the UUID set in RAM."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=30.0)
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS uuid_provenance (
                uuid TEXT PRIMARY KEY,
                data_group TEXT NOT NULL,
                source_key TEXT NOT NULL,
                partition_date TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS uuid_conflict (
                conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL,
                detail TEXT NOT NULL,
                detected_at TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def begin_partition(
        self,
        context: PartitionContext,
        records: Sequence[Mapping[str, Any]],
        *,
        replace_partition: bool = False,
    ) -> None:
        try:
            self._connection.execute("BEGIN")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for record in records:
                record_id = record.get("id")
                if not isinstance(record_id, str) or not record_id:
                    raise UUIDConflictError("canonical record has no non-empty id")
                content = fingerprint(record)
                existing = self._connection.execute(
                    "SELECT data_group, source_key, partition_date, content_fingerprint FROM uuid_provenance WHERE uuid=?",
                    (record_id,),
                ).fetchone()
                provenance = (context.contract.data_group, context.source_key, context.partition_date, content)
                if existing is not None:
                    existing_provenance = tuple(existing)
                    same_partition = existing_provenance[:3] == provenance[:3]
                    if not same_partition or not replace_partition and existing_provenance != provenance:
                        raise UUIDConflictError(
                            f"UUID {record_id} conflicts: existing provenance/content={existing_provenance} new={provenance}"
                        )
                    if replace_partition and existing_provenance[3] != provenance[3]:
                        self._connection.execute(
                            "UPDATE uuid_provenance SET content_fingerprint=? WHERE uuid=?",
                            (provenance[3], record_id),
                        )
                if existing is None:
                    self._connection.execute(
                        "INSERT INTO uuid_provenance (uuid, data_group, source_key, partition_date, content_fingerprint, first_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (record_id, *provenance, now),
                    )
        except UUIDConflictError as exc:
            self.rollback()
            self._connection.execute(
                "INSERT INTO uuid_conflict (uuid, detail, detected_at) VALUES (?, ?, ?)",
                (str(record_id) if "record_id" in locals() else "", str(exc)[:4000], datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            self._connection.commit()
            raise
        except Exception:
            self.rollback()
            raise

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()

    def partition_uuids(self, source_key: str, partition_date: str) -> set[str]:
        """Read the disk-backed UUID set owned by one source/date partition."""

        rows = self._connection.execute(
            "SELECT uuid FROM uuid_provenance WHERE source_key=? AND partition_date=?",
            (source_key, partition_date),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def remove_uuids(self, uuids: Iterable[str]) -> int:
        """Remove exact UUIDs from the current transaction."""

        values = sorted({str(value) for value in uuids})
        removed = 0
        for offset in range(0, len(values), 500):
            batch = values[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            cursor = self._connection.execute(
                f"DELETE FROM uuid_provenance WHERE uuid IN ({placeholders})",
                batch,
            )
            removed += int(cursor.rowcount)
        return removed

    def group_counts(self) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT data_group, COUNT(*) FROM uuid_provenance GROUP BY data_group"
        ).fetchall()
        return {group: int(count) for group, count in rows}

    def total_count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM uuid_provenance").fetchone()[0])

    def conflict_count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM uuid_conflict").fetchone()[0])

    def close(self) -> None:
        self.rollback()
        self._connection.close()

    def __enter__(self) -> "UUIDProvenanceStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AuditedSink:
    """Stage UUID provenance transactionally around an existing sink."""

    def __init__(self, sink: Sink, provenance: UUIDProvenanceStore) -> None:
        self.sink = sink
        self.provenance = provenance
        self.sink_target = getattr(sink, "sink_target", "unknown")

    def write_partition(self, context: PartitionContext, records: Sequence[Mapping[str, Any]]) -> SinkWriteResult:
        self.provenance.begin_partition(context, records)
        try:
            result = self.sink.write_partition(context, records)
        except BaseException:
            self.provenance.rollback()
            raise
        if result.rejected_count or result.accepted_count != len(records):
            self.provenance.rollback()
        else:
            self.provenance.commit()
        return result

    def replace_partition(
        self,
        context: PartitionContext,
        records: Sequence[Mapping[str, Any]],
        stale_uuids: Iterable[str],
    ) -> SinkWriteResult:
        """Upsert current records and remove only stale UUIDs for this partition."""

        delete = getattr(self.sink, "delete_documents", None)
        if not callable(delete):
            raise OSError("partition replacement requires an exact-delete-capable sink")
        stale = tuple(sorted({str(value) for value in stale_uuids}))
        self.provenance.begin_partition(context, records, replace_partition=True)
        try:
            result = self.sink.write_partition(context, records)
            if result.rejected_count or result.accepted_count != len(records):
                self.provenance.rollback()
                return result
            delete(context, stale)
            self.provenance.remove_uuids(stale)
            self.provenance.commit()
            return result
        except KeyboardInterrupt:
            self.provenance.rollback()
            raise
        except Exception as exc:
            self.provenance.rollback()
            if isinstance(exc, OSError):
                raise
            raise OSError(str(exc)) from exc


class BackfillReport:
    """Small atomic JSON report; no record UUIDs are persisted here."""

    def __init__(self, path: str | Path, manifest: Mapping[str, Any], checkpoint_path: str) -> None:
        self.path = Path(path)
        self.manifest = dict(manifest)
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._started_monotonic = time.monotonic()
        sources = self.manifest["sources"]
        source_totals = self.manifest["source_totals"]
        total = len(list(iter_parent_partitions(
            self.manifest["source_range"]["from"], self.manifest["source_range"]["to"], sources
        )))
        self.data: dict[str, Any] = {
            "report_version": BACKFILL_REPORT_VERSION,
            "generation": self.manifest["generation"],
            "range": self.manifest["source_range"],
            "start_at": self.started_at,
            "updated_at": self.started_at,
            "checkpoint_db_path": checkpoint_path,
            "sink_target": f"typesense:{self.manifest['generation']}",
            "state": "PENDING",
            "counts": {
                "parent_partitions_total": total,
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "quarantined": 0,
                "records_expected": int(self.manifest["expected_overall_total"]),
                "normalized_documents": 0,
                "typesense_attempted": 0,
                "typesense_rejected": 0,
                "records_accepted": 0,
                "typesense_batches": 0,
                "msc_requests": 0,
                "retries": 0,
                "elapsed_seconds": 0.0,
            },
            "source_progress": {
                key: {
                    "data_group": get_contract(key).data_group,
                    "records_expected": int(source_totals[key]),
                    "parent_partitions_total": total // len(sources),
                    "completed": 0,
                    "skipped": 0,
                    "failed": 0,
                    "quarantined": 0,
                    "records_accepted": 0,
                }
                for key in sources
            },
            "group_progress": {
                group: {
                    "records_expected": int(self.manifest["group_totals"][group]),
                    "completed": 0,
                    "skipped": 0,
                    "failed": 0,
                    "quarantined": 0,
                    "records_accepted": 0,
                }
                for group in LOGICAL_GROUPS
            },
            "errors": [],
            "quarantined_partitions": [],
            "last_completed_partition": None,
            "current_partition": None,
            "schema_drift": {"additive_fields_by_source": {}, "breaking": []},
            "resource_monitoring": {"samples": [], "last": None},
        }

    def set_state(self, state: str, *, current_partition: str | None = None) -> None:
        self.data["state"] = state
        self.data["current_partition"] = current_partition
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.data["counts"]["elapsed_seconds"] = round(time.monotonic() - self._started_monotonic, 3)

    def update(self, result: PartitionResult) -> None:
        counts = self.data["counts"]
        source = self.data["source_progress"][result.source_key]
        group = self.data["group_progress"][source["data_group"]]
        if result.skipped:
            counts["skipped"] += 1
            source["skipped"] += 1
            group["skipped"] += 1
        elif result.status == IngestionStatus.COMPLETED:
            counts["completed"] += 1
            source["completed"] += 1
            group["completed"] += 1
        elif result.status == IngestionStatus.QUARANTINED:
            counts["quarantined"] += 1
            source["quarantined"] += 1
            group["quarantined"] += 1
        elif result.status == IngestionStatus.FAILED:
            counts["failed"] += 1
            source["failed"] += 1
            group["failed"] += 1
        if result.status == IngestionStatus.COMPLETED:
            accepted = int(result.sink_accepted_count)
            counts["records_accepted"] += accepted
            source["records_accepted"] += accepted
            group["records_accepted"] += accepted
            self.data["last_completed_partition"] = {
                "source_key": result.source_key,
                "partition_date": result.partition_date,
            }
        counts["normalized_documents"] += int(result.normalized_count)
        accepted = int(result.sink_accepted_count)
        attempted = max(int(result.sink_attempted_count), accepted)
        rejected = max(attempted - accepted, 0)
        counts["typesense_attempted"] += attempted
        counts["typesense_rejected"] += rejected
        counts["typesense_batches"] += int(result.sink_batch_count)
        counts["msc_requests"] += int(result.request_count)
        counts["retries"] += int(result.retry_count)
        if result.drift.additive_fields:
            additive = self.data["schema_drift"]["additive_fields_by_source"].setdefault(result.source_key, [])
            for field in result.drift.additive_fields:
                if field not in additive:
                    additive.append(field)
        if result.error_code:
            error = {
                "source_key": result.source_key,
                "partition_date": result.partition_date,
                "category": classify_failure(result.error_code),
                "code": result.error_code,
                "message": (result.error_message or "")[:2000],
            }
            self.data["errors"].append(error)
            if result.status == IngestionStatus.QUARANTINED:
                self.data["quarantined_partitions"].append(error)
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.data["counts"]["elapsed_seconds"] = round(time.monotonic() - self._started_monotonic, 3)

    def write(self) -> None:
        atomic_write_json(self.path, self.data)


def classify_failure(code: str) -> str:
    if code in {TYPESENSE_CONNECT_ERROR, TYPESENSE_IMPORT_ERROR, TYPESENSE_PARTIAL_IMPORT}:
        return "typesense_infrastructure"
    if code in {TYPESENSE_SCHEMA_ERROR, TYPESENSE_ALIAS_ERROR}:
        return "typesense_configuration"
    if code == TYPESENSE_IDENTITY_CONFLICT or code == "NORMALIZATION_ERROR":
        return "data"
    if code.startswith("MSC_") or code == "SEARCH_WINDOW_OVERFLOW":
        return "msc_source"
    return "data"


def _checkpoint_skip_result(checkpoint: Checkpoint) -> PartitionResult:
    return PartitionResult(
        checkpoint.source_key,
        checkpoint.partition_date,
        IngestionStatus.COMPLETED,
        parent_pre_count=checkpoint.parent_pre_count,
        parent_post_count=checkpoint.parent_post_count,
        raw_fetched_count=checkpoint.raw_fetched_count or 0,
        unique_source_count=checkpoint.unique_uuid_count or 0,
        normalized_count=checkpoint.normalized_count or 0,
        sink_accepted_count=checkpoint.sink_accepted_count or 0,
        skipped=True,
        sink_target=checkpoint.sink_target,
        sink_attempted_count=checkpoint.sink_accepted_count or 0,
    )


class BackfillRunner:
    """Sequential date/source coordinator over the existing ingestion engine."""

    def __init__(
        self,
        engine: MSCIngestionEngine,
        checkpoint_store: CheckpointStore,
        manifest: Mapping[str, Any],
        *,
        report_path: str | Path,
        resume: bool = False,
        force: bool = False,
        max_partitions: int | None = None,
        replace_existing: bool = False,
        replace_existing_before: date | None = None,
        replace_existing_dates: set[tuple[str, date]] | None = None,
        on_before_partition: Callable[[str, str, "BackfillReport"], None] | None = None,
        on_partition_boundary: Callable[[PartitionResult, "BackfillReport"], None] | None = None,
    ) -> None:
        verify_manifest(manifest)
        self.engine = engine
        self.checkpoint_store = checkpoint_store
        self.manifest = dict(manifest)
        self.report = BackfillReport(report_path, manifest, checkpoint_store.path)
        self.resume = resume
        self.force = force
        self.max_partitions = max_partitions
        self.replace_existing = replace_existing
        self.replace_existing_before = replace_existing_before
        self.replace_existing_dates = replace_existing_dates or set()
        self.on_before_partition = on_before_partition
        self.on_partition_boundary = on_partition_boundary

    def run(self) -> tuple[PartitionResult, ...]:
        partitions = tuple(iter_parent_partitions(
            self.manifest["source_range"]["from"],
            self.manifest["source_range"]["to"],
            self.manifest["sources"],
        ))
        if self.max_partitions is None:
            raise BackfillControlError("actual backfill requires explicit --max-partitions")
        if self.max_partitions <= 0 or len(partitions) > self.max_partitions:
            raise BackfillControlError(f"requested partitions {len(partitions)} exceed --max-partitions {self.max_partitions}")
        self.report.set_state("RUNNING")
        self.report.write()
        results: list[PartitionResult] = []
        try:
            for source_key, partition_date in partitions:
                self.report.set_state("RUNNING", current_partition=f"{source_key}:{partition_date}")
                if self.on_before_partition is not None:
                    self.on_before_partition(source_key, partition_date, self.report)
                checkpoint = self.checkpoint_store.get(source_key, partition_date, getattr(self.engine.sink, "sink_target", ""))
                should_replace = (
                    checkpoint is not None
                    and checkpoint.status == IngestionStatus.COMPLETED
                    and (
                        self.force
                        or (
                            self.replace_existing
                            and (
                                self.replace_existing_before is None
                                or parse_partition_date(partition_date) < self.replace_existing_before
                            )
                        )
                        or (source_key, parse_partition_date(partition_date)) in self.replace_existing_dates
                    )
                )
                if checkpoint and checkpoint.status == IngestionStatus.COMPLETED and not self.force and not should_replace:
                    if not self.resume:
                        raise BackfillControlError(
                            f"completed partition {source_key}:{partition_date} requires --resume or --force"
                        )
                    result = _checkpoint_skip_result(checkpoint)
                else:
                    result = self.engine.ingest_partition(
                        source_key,
                        partition_date,
                        force=self.force or should_replace,
                        allow_open_day=False,
                        replace_existing=should_replace,
                    )
                results.append(result)
                self.report.update(result)
                self.report.write()
                if self.on_partition_boundary is not None and not result.skipped:
                    self.on_partition_boundary(result, self.report)
                    self.report.write()
                if result.status in {IngestionStatus.FAILED, IngestionStatus.QUARANTINED}:
                    self.report.set_state("FAILED", current_partition=f"{source_key}:{partition_date}")
                    self.report.write()
                    break
            else:
                self.report.set_state("COMPLETED")
                self.report.write()
        except KeyboardInterrupt:
            self.report.set_state("INTERRUPTED", current_partition=self.report.data.get("current_partition"))
            self.report.write()
            raise
        except BaseException:
            self.report.set_state("FAILED", current_partition=self.report.data.get("current_partition"))
            self.report.write()
            raise
        return tuple(results)


def checkpoint_audit(
    store: CheckpointStore,
    from_date: str | date,
    to_date: str | date,
    source_keys: Iterable[str],
    sink_target: str,
) -> dict[str, Any]:
    start, end = validate_closed_range(from_date, to_date)
    sources = ordered_source_keys(source_keys)
    per_source: dict[str, Any] = {}
    for source_key in sources:
        rows: list[Checkpoint] = []
        day = start
        while day <= end:
            checkpoint = store.get(source_key, day.isoformat(), sink_target)
            if checkpoint:
                rows.append(checkpoint)
            day += timedelta(days=1)
        expected = (end - start).days + 1
        status_counts = {status.value.lower(): 0 for status in IngestionStatus}
        sum_completed = 0
        for row in rows:
            status_counts[row.status.value.lower()] += 1
            if row.status == IngestionStatus.COMPLETED:
                sum_completed += int(row.parent_pre_count or 0)
        running = [row for row in rows if row.status == IngestionStatus.RUNNING]
        stale = [
            row for row in running
            if _is_stale(row.updated_at if hasattr(row, "updated_at") else row.started_at)
        ]
        per_source[source_key] = {
            "data_group": get_contract(source_key).data_group,
            "expected_date_partitions": expected,
            "completed": status_counts["completed"],
            "failed": status_counts["failed"],
            "quarantined": status_counts["quarantined"],
            "pending": expected - len(rows),
            "running": status_counts["running"],
            "stale_running": len(stale),
            "sum_completed_parent_pre_count": sum_completed,
        }
    return {
        "sink_target": sink_target,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "sources": per_source,
        "expected_parent_partitions": sum(item["expected_date_partitions"] for item in per_source.values()),
        "completed_parent_partitions": sum(item["completed"] for item in per_source.values()),
    }


def source_coverage_checkpoint_audit(
    store: CheckpointStore,
    through: str | date,
    source_keys: Iterable[str],
    sink_target: str,
) -> dict[str, Any]:
    """Audit each source from its registered floor through one closed date."""

    end = parse_partition_date(through)
    sources = ordered_source_keys(source_keys)
    per_source: dict[str, Any] = {}
    for source_key in sources:
        start = SOURCE_COVERAGE_FLOORS[source_key]
        per_source[source_key] = checkpoint_audit(store, start, end, (source_key,), sink_target)["sources"][source_key]
    return {
        "sink_target": sink_target,
        "coverage_through": end.isoformat(),
        "sources": per_source,
        "expected_parent_partitions": sum(item["expected_date_partitions"] for item in per_source.values()),
        "completed_parent_partitions": sum(item["completed"] for item in per_source.values()),
        "failed_parent_partitions": sum(item["failed"] for item in per_source.values()),
        "quarantined_parent_partitions": sum(item["quarantined"] for item in per_source.values()),
        "pending_parent_partitions": sum(item["pending"] for item in per_source.values()),
        "stale_running_partitions": sum(item["stale_running"] for item in per_source.values()),
        "source_sums": {
            source_key: item["sum_completed_parent_pre_count"]
            for source_key, item in per_source.items()
        },
    }


def _is_stale(value: str | None) -> bool:
    if not value:
        return False
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp).total_seconds() > _STALE_RUNNING_SECONDS
    except ValueError:
        return False


def historical_backfill_audit(
    manifest: Mapping[str, Any],
    checkpoint_store: CheckpointStore,
    uuid_store: UUIDProvenanceStore,
    *,
    typesense_client: TypesenseClient | None = None,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_manifest(manifest)
    generation = str(manifest["generation"])
    sink_target = f"typesense:{generation}"
    coverage = checkpoint_audit(
        checkpoint_store,
        manifest["source_range"]["from"],
        manifest["source_range"]["to"],
        manifest["sources"],
        sink_target,
    )
    source_coverage: dict[str, Any] = {}
    for source_key in manifest["sources"]:
        expected = int(manifest["source_totals"][source_key])
        actual = coverage["sources"][source_key]["sum_completed_parent_pre_count"]
        source_coverage[source_key] = {
            "broad_range_count": expected,
            "sum_completed_parent_source_counts": actual,
            "parity": expected == actual,
        }
    expected_groups = {group: int(value) for group, value in uuid_store.group_counts().items()}
    expected_groups = {group: expected_groups.get(group, 0) for group in LOGICAL_GROUPS}
    actual_groups: dict[str, int | None] = {group: None for group in LOGICAL_GROUPS}
    server_version: str | None = None
    schema_drift: dict[str, Any] = {"status": "not_checked", "mismatches": []}
    if typesense_client is not None:
        health = typesense_client.health()
        server_version = health.get("version") or health.get("server_version")
        manager = TypesenseCollectionManager(typesense_client)
        try:
            schema_result = manager.validate_generation(generation)
            schema_drift = {"status": "PASS", "mismatches": [], "validation": schema_result}
        except TypesenseError as exc:
            schema_drift = {"status": "FAIL", "mismatches": [str(exc)]}
        from .typesense_schema import physical_collection_name
        for group in LOGICAL_GROUPS:
            actual_groups[group] = typesense_client.document_count(physical_collection_name(group, generation))
    count_parity = {
        group: actual_groups[group] is not None and actual_groups[group] == expected_groups[group]
        for group in LOGICAL_GROUPS
    }
    counts = {
        "completed_partitions": coverage["completed_parent_partitions"],
        "failed_partitions": sum(item["failed"] for item in coverage["sources"].values()),
        "quarantined_partitions": sum(item["quarantined"] for item in coverage["sources"].values()),
        "rejected_documents": sum(
            max(int(row.get("normalized_count") or 0) - int(row.get("sink_accepted_count") or 0), 0)
            for row in (
                (report or {}).get("checkpoint_rows", [])
                or [
                    {
                        "normalized_count": checkpoint.normalized_count,
                        "sink_accepted_count": checkpoint.sink_accepted_count,
                    }
                    for checkpoint in checkpoint_store.list(sink_target)
                ]
            )
        ),
        "import_batches": int((report or {}).get("counts", {}).get("typesense_batches", 0)),
        "retries": int((report or {}).get("counts", {}).get("retries", 0)),
    }
    coverage_pass = all(item["parity"] for item in source_coverage.values()) and counts["failed_partitions"] == 0 and counts["quarantined_partitions"] == 0
    overall = coverage_pass and uuid_store.conflict_count() == 0 and all(count_parity.values()) and schema_drift["status"] == "PASS"
    return {
        "audit_version": "msc-historical-backfill-audit-v1",
        "overall_status": "PASS" if overall else "FAIL",
        "generation": generation,
        "range": manifest["source_range"],
        "typesense_server_version": server_version,
        "source_broad_counts": manifest["source_totals"],
        "source_completed_parent_count_sums": {key: value["sum_completed_parent_pre_count"] for key, value in coverage["sources"].items()},
        "source_coverage_parity": source_coverage,
        "group_expected_unique_counts": expected_groups,
        "group_typesense_actual_counts": actual_groups,
        "typesense_count_parity": count_parity,
        "uuid_conflict_count": uuid_store.conflict_count(),
        "uuid_audit_total": uuid_store.total_count(),
        "completed_partition_count": coverage["completed_parent_partitions"],
        "failed_partition_count": counts["failed_partitions"],
        "quarantined_partition_count": counts["quarantined_partitions"],
        "rejected_document_count": counts["rejected_documents"],
        "import_batch_total": counts["import_batches"],
        "retry_total": counts["retries"],
        "schema_drift_diagnostics": schema_drift,
        "sampling_validation": {
            "status": "PLANNED",
            "seed": 20230830,
            "bands": ["early", "middle", "recent_closed"],
            "source_tabs": list(manifest["sources"]),
        },
        "search_benchmark": {
            "status": "PLANNED",
            "query_set": ["item/medicine name", "active ingredient", "manufacturer", "bidder", "tender code", "source tab", "price range", "sort", "multi-search all"],
            "latency": ["p50-like", "p95-like"],
        },
        "checkpoint_audit": coverage,
        "counts": counts,
    }


def plan_summary(
    manifest: Mapping[str, Any],
    checkpoint_store: CheckpointStore,
    *,
    source_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    verify_manifest(manifest)
    sources = ordered_source_keys(source_keys or manifest["sources"])
    if tuple(sources) != tuple(manifest["sources"]):
        raise BackfillControlError("selected sources do not match manifest source set")
    partitions = tuple(iter_parent_partitions(
        manifest["source_range"]["from"], manifest["source_range"]["to"], sources
    ))
    target = f"typesense:{manifest['generation']}"
    completed = sum(
        1 for source_key, day in partitions
        if (checkpoint_store.get(source_key, day, target) or Checkpoint(
            source_key, day, target, IngestionStatus.PENDING, 0, None, None, None, None, None, None, None, None, None, None, ENGINE_VERSION, SCHEMA_VERSION
        )).status == IngestionStatus.COMPLETED
    )
    expected = int(manifest["expected_overall_total"])
    page_size = int(manifest["page_size"])
    batch_size = int(manifest["typesense_batch_size"])
    pages = sum(math.ceil(int(value) / page_size) for value in manifest["source_totals"].values())
    return {
        "requested_range": manifest["source_range"],
        "source_set": list(sources),
        "source_date_parent_partitions": len(partitions),
        "broad_range_source_counts": manifest["source_totals"],
        "expected_total_documents": expected,
        "checkpoint_completed_count": completed,
        "remaining_partitions": len(partitions) - completed,
        "estimated_msc_requests": {
            "lower_bound": len(partitions) * 2 + pages,
            "method": "two parent count requests plus one page per page-size chunk; adaptive split counts add requests",
        },
        "estimated_typesense_batches": math.ceil(expected / batch_size),
        "wall_clock": "not estimated; throughput depends on MSC, network, normalization, and Typesense backpressure",
        "sink_target": target,
    }


def capacity_preflight(
    estimate: Mapping[str, Any],
    *,
    typesense_client: TypesenseClient | None = None,
    local_path: str | Path | None = None,
) -> dict[str, Any]:
    overall = estimate["overall"]
    result: dict[str, Any] = {
        "decision": "REVIEW",
        "required_estimated_indexed_bytes": overall["projected_indexed_field_bytes"],
        "required_estimated_raw_disk_bytes": overall["minimum_raw_data_disk_bytes"],
        "required_raw_disk_with_margin_bytes": overall["raw_disk_with_operational_margin_bytes"],
        "local_disk": None,
        "remote_metrics": None,
        "remote_metrics_error": None,
        "operator_acknowledgement_required": True,
    }
    if local_path is not None:
        usage = shutil.disk_usage(Path(local_path))
        result["local_disk"] = {"free_bytes": usage.free, "path": str(local_path)}
        if usage.free < overall["raw_disk_with_operational_margin_bytes"]:
            result["decision"] = "FAIL"
    if typesense_client is not None:
        try:
            result["remote_metrics"] = typesense_client.metrics()
        except TypesenseError as exc:
            result["remote_metrics_error"] = str(exc)
    return result


BENCHMARK_CASES = (
    ("goods", "máy bơm"),
    ("medicines", "amlodipin"),
    ("traditional_medicine", "bạch linh"),
    ("medicines", "dược hậu giang"),
    ("goods", "nhà thầu"),
    ("goods", "IB2600"),
    ("traditional_medicine", "dược liệu"),
)


def _float_percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def run_search_benchmark(
    client: TypesenseClient,
    generation: str,
    *,
    repeats: int = 3,
) -> dict[str, Any]:
    """Run a small physical-generation query benchmark; never writes."""

    validate_generation_id(generation)
    if repeats <= 0 or repeats > 20:
        raise BackfillControlError("benchmark repeats must be between 1 and 20")
    samples: list[float] = []
    errors: list[str] = []
    cases = [{"group": group, "query": query} for group, query in BENCHMARK_CASES]
    for group, query in BENCHMARK_CASES:
        for _ in range(repeats):
            started = time.perf_counter()
            try:
                client.search_group(group, query, collection=physical_collection_name(group, generation))
                samples.append((time.perf_counter() - started) * 1000)
            except TypesenseError as exc:
                errors.append(f"{group}:{query}: {exc}")
    for sort_order in ("asc", "desc"):
        for _ in range(repeats):
            started = time.perf_counter()
            try:
                client.search_group(
                    "goods", "*", filter_by="winning_unit_price:>0",
                    sort_by=f"winning_unit_price:{sort_order}",
                    collection=physical_collection_name("goods", generation),
                )
                samples.append((time.perf_counter() - started) * 1000)
            except TypesenseError as exc:
                errors.append(f"goods:price_{sort_order}: {exc}")
        cases.append({"group": "goods", "query": "*", "filter_by": "winning_unit_price:>0", "sort_by": f"winning_unit_price:{sort_order}"})
    for _ in range(repeats):
        started = time.perf_counter()
        try:
            client.search_group(
                "goods", "*", filter_by="source_tab:HANG_HOA",
                collection=physical_collection_name("goods", generation),
            )
            samples.append((time.perf_counter() - started) * 1000)
        except TypesenseError as exc:
            errors.append(f"goods:source_tab_filter: {exc}")
    cases.append({"group": "goods", "query": "*", "filter_by": "source_tab:HANG_HOA"})
    for _ in range(repeats):
        started = time.perf_counter()
        try:
            client.multi_search_all("thuốc", generation_id=generation)
            samples.append((time.perf_counter() - started) * 1000)
        except TypesenseError as exc:
            errors.append(f"multi_search_all: {exc}")
    return {
        "generation": generation,
        "bounded": True,
        "cases": cases + [{"operation": "multi_search_all", "query": "thuốc"}],
        "repeats": repeats,
        "successful_samples": len(samples),
        "errors": errors,
        "latency_ms": {
            "p50_like": _float_percentile(samples, 0.50),
            "p95_like": _float_percentile(samples, 0.95),
        },
        "note": "Run after physical backfill and before alias activation; latency is a bounded sample, not a capacity guarantee.",
    }
