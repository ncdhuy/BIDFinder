"""Current-serving generation bootstrap and bounded incremental continuation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

from .backfill import (
    AuditedSink,
    BackfillRunner,
    UUIDProvenanceStore,
    atomic_write_json,
    build_manifest,
    checkpoint_audit,
    group_totals,
    source_population_preflight,
    typesense_schema_fingerprints,
)
from .checkpoint import CheckpointStore
from .client import MSCClient
from .config import MSCConfig, TypesenseConfig
from .contracts import SOURCE_CONTRACTS
from .engine import MSCIngestionEngine, operational_today, parse_partition_date
from .models import IngestionStatus
from .sink import TypesenseSink
from .typesense_client import TypesenseClient, TypesenseCollectionManager, TypesenseError
from .typesense_schema import (
    LOGICAL_ALIASES,
    collection_schema,
    physical_collection_name,
    validate_generation_id,
)

HISTORICAL_GENERATION = "hist_v1_20260829"
HISTORICAL_END = date(2026, 8, 29)
INCREMENTAL_START = HISTORICAL_END + timedelta(days=1)
SERVING_GENERATION_PREFIX = "serving_v1_"
DEFAULT_LOOKBACK_DAYS = 3
EXPECTED_HISTORICAL_GROUP_COUNTS = {
    "goods": 9_183_726,
    "medicines": 585_426,
    "traditional_medicine": 32_022,
}


def require_serving_generation(generation: str) -> str:
    """Reject immutable or non-serving targets at the incremental boundary."""

    validate_generation_id(generation)
    if generation == HISTORICAL_GENERATION:
        raise ValueError("historical generation is immutable and cannot be an incremental target")
    if not generation.startswith(SERVING_GENERATION_PREFIX):
        raise ValueError(f"incremental target must start with {SERVING_GENERATION_PREFIX}")
    return generation


def require_retirable_generation(generation: str) -> str:
    validate_generation_id(generation)
    if generation == HISTORICAL_GENERATION:
        raise ValueError("historical generation cannot be retired")
    if not generation.startswith(("local_canary_", SERVING_GENERATION_PREFIX)):
        raise ValueError("only local canary or serving generations can be retired")
    return generation


def latest_closed_day(now: date | None = None) -> date:
    return (now or operational_today()) - timedelta(days=1)


def incremental_window(
    from_date: str | date,
    to_date: str | date,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[date, date, date]:
    requested_start = parse_partition_date(from_date)
    end = parse_partition_date(to_date)
    if requested_start < INCREMENTAL_START:
        raise ValueError(f"incremental start must be on or after {INCREMENTAL_START.isoformat()}")
    if end < requested_start:
        raise ValueError("incremental from date cannot be after to date")
    if end >= operational_today():
        raise ValueError("incremental range cannot include the current/open Vietnam calendar day")
    if lookback_days < 0:
        raise ValueError("lookback_days cannot be negative")
    effective_start = max(INCREMENTAL_START, requested_start - timedelta(days=lookback_days))
    return requested_start, effective_start, end


def _copy_sqlite(source: str | Path, destination: str | Path) -> None:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if destination_path.exists():
        raise FileExistsError(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination_path.name}.", suffix=".tmp", dir=destination_path.parent, delete=False
        ) as handle:
            temporary = handle.name
        source_db = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        target_db = sqlite3.connect(temporary)
        try:
            source_db.backup(target_db)
            target_db.commit()
            integrity = target_db.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"copied SQLite database failed integrity check: {integrity}")
        finally:
            target_db.close()
            source_db.close()
        os.replace(temporary, destination_path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def bootstrap_checkpoint(
    source: str | Path,
    destination: str | Path,
    *,
    base_generation: str = HISTORICAL_GENERATION,
    serving_generation: str,
) -> dict[str, Any]:
    require_serving_generation(serving_generation)
    source_sink = f"typesense:{base_generation}"
    serving_sink = f"typesense:{serving_generation}"
    _copy_sqlite(source, destination)
    connection = sqlite3.connect(destination)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("serving checkpoint failed integrity check")
        connection.execute("BEGIN IMMEDIATE")
        source_rows = int(connection.execute(
            "SELECT COUNT(*) FROM ingestion_checkpoint WHERE sink_target=?", (source_sink,)
        ).fetchone()[0])
        if not source_rows:
            connection.rollback()
            raise ValueError(f"historical checkpoint has no rows for {source_sink}")
        remapped = connection.execute(
            "UPDATE ingestion_checkpoint SET sink_target=? WHERE sink_target=?",
            (serving_sink, source_sink),
        ).rowcount
        connection.commit()
        remaining_base = int(connection.execute(
            "SELECT COUNT(*) FROM ingestion_checkpoint WHERE sink_target=?", (source_sink,)
        ).fetchone()[0])
        serving_rows = int(connection.execute(
            "SELECT COUNT(*) FROM ingestion_checkpoint WHERE sink_target=?", (serving_sink,)
        ).fetchone()[0])
        if remaining_base or serving_rows != source_rows or remapped != source_rows:
            raise ValueError("checkpoint sink-target remap was incomplete")
        return {
            "integrity": "ok",
            "source_rows": source_rows,
            "rows_remapped": int(remapped),
            "sink_target": serving_sink,
        }
    finally:
        connection.close()


def bootstrap_provenance(
    source: str | Path,
    destination: str | Path,
    *,
    serving_generation: str,
) -> dict[str, Any]:
    require_serving_generation(serving_generation)
    _copy_sqlite(source, destination)
    connection = sqlite3.connect(destination)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        groups = {
            str(group): int(count)
            for group, count in connection.execute(
                "SELECT data_group, COUNT(*) FROM uuid_provenance GROUP BY data_group"
            ).fetchall()
        }
        total = int(connection.execute("SELECT COUNT(*) FROM uuid_provenance").fetchone()[0])
        conflicts = int(connection.execute("SELECT COUNT(*) FROM uuid_conflict").fetchone()[0])
    finally:
        connection.close()
    if integrity != "ok":
        raise ValueError(f"serving provenance failed integrity check: {integrity}")
    return {
        "integrity": integrity,
        "generation": serving_generation,
        "total": total,
        "group_counts": {group: groups.get(group, 0) for group in LOGICAL_ALIASES},
        "conflicts": conflicts,
    }


def _sample_ids(provenance_path: str | Path, group: str, limit: int = 3) -> tuple[str, ...]:
    connection = sqlite3.connect(f"file:{Path(provenance_path)}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT uuid FROM uuid_provenance WHERE data_group=? ORDER BY uuid LIMIT ?", (group, limit)
        ).fetchall()
    finally:
        connection.close()
    return tuple(str(row[0]) for row in rows)


def clone_generation(
    client: TypesenseClient,
    base_generation: str,
    serving_generation: str,
    *,
    provenance_path: str | Path,
    base_manifest_fingerprint: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    require_serving_generation(serving_generation)
    validate_generation_id(base_generation)
    if base_generation == serving_generation:
        raise ValueError("base and serving generations must be distinct")
    manager = TypesenseCollectionManager(client)
    manager.validate_generation(base_generation)
    created = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    result: dict[str, Any] = {
        "method": "Typesense server-side clone with copy_documents=true",
        "base_generation": base_generation,
        "serving_generation": serving_generation,
        "groups": {},
    }
    for group in LOGICAL_ALIASES:
        group_started = time.perf_counter()
        source = physical_collection_name(group, base_generation)
        destination = physical_collection_name(group, serving_generation)
        if client.get_collection(destination) is not None:
            raise ValueError(f"serving destination already exists: {destination}")
        source_details = client.get_collection(source)
        if source_details is None:
            raise TypesenseError("TYPESENSE_SCHEMA_ERROR", f"historical source collection is missing: {source}")
        source_count = int(source_details.get("num_documents", -1))
        samples = _sample_ids(provenance_path, group)
        expected = collection_schema(group, serving_generation)
        metadata = {
            **expected["metadata"],
            "role": "serving",
            "base_generation": base_generation,
            "base_historical_through": HISTORICAL_END.isoformat(),
            "base_manifest_fingerprint": base_manifest_fingerprint,
            "created_at": created,
            "current_coverage_through": HISTORICAL_END.isoformat(),
        }
        client.clone_collection(source, destination, copy_documents=True, metadata=metadata)
        actual = client.get_collection(destination)
        if actual is None or not TypesenseCollectionManager._compatible(actual, expected):
            raise TypesenseError("TYPESENSE_SCHEMA_ERROR", f"clone schema or metadata validation failed: {destination}")
        actual_count = client.document_count(destination)
        if actual_count != source_count:
            raise ValueError(f"clone count mismatch for {group}: {actual_count} != {source_count}")
        sample_parity: list[str] = []
        for record_id in samples:
            source_doc = client.get_document(source, record_id)
            destination_doc = client.get_document(destination, record_id)
            if source_doc is not None and source_doc != destination_doc:
                raise ValueError(f"clone document mismatch for {group}:{record_id}")
            if source_doc is not None:
                sample_parity.append(record_id)
        search = client.search_group(group, "*", per_page=1, collection=destination)
        result["groups"][group] = {
            "source_collection": source,
            "destination_collection": destination,
            "source_count": source_count,
            "destination_count": actual_count,
            "metadata": actual.get("metadata", {}),
            "lineage_metadata": metadata,
            "metadata_status": "persisted" if actual.get("metadata") else "operational-report-only",
            "sample_ids": sample_parity,
            "search_found": search.get("found"),
            "duration_seconds": round(time.perf_counter() - group_started, 3),
            "parity": source_count == actual_count,
        }
    return result


def safe_retire_generation(client: TypesenseClient, generation: str) -> dict[str, Any]:
    generation = require_retirable_generation(generation)
    names = {group: physical_collection_name(group, generation) for group in LOGICAL_ALIASES}
    aliases: dict[str, str | None] = {}
    for group, alias in LOGICAL_ALIASES.items():
        target = client.get_alias(alias)
        aliases[alias] = target.get("collection_name") if target else None
        if aliases[alias] in names.values():
            raise ValueError(f"cannot retire {generation}; stable alias {alias} points to it")
    missing = [name for name in names.values() if client.get_collection(name) is None]
    if missing:
        raise ValueError(f"retirement target is incomplete; missing collections: {', '.join(missing)}")
    deleted = [client.delete_collection(names[group]) for group in LOGICAL_ALIASES]
    remaining = [name for name in names.values() if client.get_collection(name) is not None]
    if remaining:
        raise ValueError(f"retirement incomplete: {', '.join(remaining)}")
    return {"generation": generation, "collections": list(names.values()), "aliases_before": aliases, "deleted": len(deleted)}


def live_generations(client: TypesenseClient) -> tuple[str, ...]:
    generations: set[str] = set()
    for item in client.list_collections():
        name = str(item.get("name", ""))
        for alias in LOGICAL_ALIASES.values():
            prefix = f"{alias}_v1_"
            if name.startswith(prefix):
                generations.add(name[len(prefix):])
    return tuple(sorted(generations))


def next_incremental_start(store: CheckpointStore, generation: str) -> date:
    sink_target = f"typesense:{require_serving_generation(generation)}"
    day = INCREMENTAL_START
    while all(
        (checkpoint := store.get(source_key, day.isoformat(), sink_target)) is not None
        and checkpoint.status == IngestionStatus.COMPLETED
        for source_key in SOURCE_CONTRACTS
    ):
        day += timedelta(days=1)
    return day


def build_serving_report(
    *,
    serving_generation: str,
    base_manifest_fingerprint: str,
    requested_range: Mapping[str, Any],
    effective_range: Mapping[str, Any],
    source_counts: Mapping[str, int],
    checkpoint_state: Mapping[str, Any],
    provenance_counts: Mapping[str, Any],
    physical_counts: Mapping[str, int],
    last_successful_run: str | None,
    unresolved_errors: Sequence[str] = (),
    **extra: Any,
) -> dict[str, Any]:
    require_serving_generation(serving_generation)
    report = {
        "audit_version": "phase-3c-incremental-serving-v1",
        "overall_status": "PASS" if not unresolved_errors else "FAIL",
        "serving_generation": serving_generation,
        "base_generation": HISTORICAL_GENERATION,
        "base_historical_through": HISTORICAL_END.isoformat(),
        "base_manifest_fingerprint": base_manifest_fingerprint,
        "incremental_start": INCREMENTAL_START.isoformat(),
        "requested_range": dict(requested_range),
        "effective_range": dict(effective_range),
        "source_counts": dict(source_counts),
        "group_source_counts": group_totals(source_counts),
        "checkpoint_state": dict(checkpoint_state),
        "provenance": dict(provenance_counts),
        "physical_counts": dict(physical_counts),
        "schema_fingerprints": typesense_schema_fingerprints(),
        "last_successful_incremental_run": last_successful_run,
        "unresolved_errors": list(unresolved_errors),
    }
    report.update(extra)
    return report


def render_serving_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 3C incremental serving audit",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Serving generation: `{report.get('serving_generation')}`",
        f"- Base generation: `{report.get('base_generation')}` through `{report.get('base_historical_through')}`",
        f"- Catch-up range: `{report.get('effective_range')}`",
        f"- Incremental start: `{report.get('incremental_start')}`",
        "",
        "Generated from the compact JSON audit; runtime databases and snapshots stay outside Git.",
        "",
    ]
    return "\n".join(lines)


def run_incremental(
    *,
    generation: str,
    from_date: str | date,
    to_date: str | date,
    checkpoint_path: str | Path,
    provenance_path: str | Path,
    report_path: str | Path,
    base_manifest_fingerprint: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    force: bool = False,
    resume: bool = True,
    max_partitions: int | None = None,
    msc_config: MSCConfig | None = None,
    typesense_config: TypesenseConfig | None = None,
) -> dict[str, Any]:
    generation = require_serving_generation(generation)
    requested_start, effective_start, end = incremental_window(
        from_date, to_date, lookback_days=lookback_days
    )
    if max_partitions is None:
        raise ValueError("incremental run requires explicit max_partitions")
    config = msc_config or MSCConfig()
    ts_config = typesense_config or TypesenseConfig.from_env()
    msc_client = MSCClient(config)
    source_preflight = source_population_preflight(msc_client, effective_start, end)
    manifest = build_manifest(
        effective_start,
        end,
        generation,
        source_preflight["source_totals"],
        page_size=config.page_size,
        typesense_batch_size=ts_config.batch_size,
    )
    client = TypesenseClient(ts_config)
    TypesenseCollectionManager(client).validate_generation(generation)
    run_report_path = Path(checkpoint_path).with_name(f".{generation}.backfill.json")
    with CheckpointStore(checkpoint_path) as checkpoints, UUIDProvenanceStore(provenance_path) as provenance:
        sink = AuditedSink(TypesenseSink(client, generation, batch_size=ts_config.batch_size), provenance)
        engine = MSCIngestionEngine(msc_client, checkpoints, sink, config)
        results = BackfillRunner(
            engine,
            checkpoints,
            manifest,
            report_path=run_report_path,
            resume=resume,
            force=force,
            max_partitions=max_partitions,
            replace_existing=True,
            replace_existing_before=requested_start,
        ).run()
        state = checkpoint_audit(checkpoints, effective_start, end, manifest["sources"], sink.sink_target)
        provenance_counts = {
            "unique_total": provenance.total_count(),
            "group_counts": provenance.group_counts(),
            "conflicts": provenance.conflict_count(),
        }
    physical_counts = {
        group: client.document_count(physical_collection_name(group, generation))
        for group in LOGICAL_ALIASES
    }
    errors = [
        f"{result.source_key}:{result.partition_date}:{result.error_code or result.status.value}"
        for result in results
        if result.status in {IngestionStatus.FAILED, IngestionStatus.QUARANTINED}
    ]
    report = build_serving_report(
        serving_generation=generation,
        base_manifest_fingerprint=base_manifest_fingerprint,
        requested_range={"from": requested_start.isoformat(), "to": end.isoformat(), "closed": True},
        effective_range={"from": effective_start.isoformat(), "to": end.isoformat(), "closed": True},
        source_counts=source_preflight["source_totals"],
        checkpoint_state=state,
        provenance_counts=provenance_counts,
        physical_counts=physical_counts,
        last_successful_run=datetime.now(timezone.utc).isoformat(timespec="seconds") if not errors else None,
        unresolved_errors=errors,
        results=[result.as_dict() for result in results],
        source_preflight=source_preflight,
        lookback_days=lookback_days,
        force=force,
    )
    atomic_write_json(report_path, report)
    return report
