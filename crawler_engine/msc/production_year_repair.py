"""Targeted, resumable repair of historical goods ``production_year`` values.

The repair deliberately has no crawler or sink of its own.  It reuses the
verified MSC client, source contracts, partition planner, and year parser,
then sends Typesense ``action=update`` imports containing only ``id`` and
``production_year``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable, Mapping, Sequence

from .client import MSCClient
from .config import MSCConfig, TypesenseConfig
from .contracts import get_contract
from .models import SearchInterval
from .normalize import normalize_year
from .partitioning import PartitioningError, official_day_interval, plan_partition
from .typesense_client import TypesenseClient, TypesenseError
from .typesense_schema import physical_collection_name
from .validation import calculate_required_pages, parse_search_count

LOGGER = logging.getLogger(__name__)

REPAIR_VERSION = "production-year-repair-v1"
GOODS_SOURCE_KEYS = ("goods_general", "medical_devices")
DEFAULT_HISTORICAL_THROUGH = "2026-09-01"
_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


class RepairError(RuntimeError):
    """A repair cannot safely continue and must be resumed after inspection."""


def source_production_year(source_key: str, raw_record: Mapping[str, Any]) -> str | None:
    """Return the current-contract value for one goods source row."""

    contract = get_contract(source_key)
    mapping = next(
        (item for item in contract.canonical_mapping if item.canonical_key == "production_year"),
        None,
    )
    if mapping is None:
        raise RepairError(f"source contract {source_key} has no production_year mapping")
    return normalize_year(raw_record.get(mapping.source_field))


def current_year_is_missing_or_corrupt(value: Any) -> bool:
    """Recognize the old loss bucket without replacing valid current values."""

    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value == 0
    if not isinstance(value, str):
        return True
    text = value.strip()
    if not text or text == "0":
        return True
    return normalize_year(text) is None


def repair_decision(source_value: str | None, current_value: Any) -> tuple[str, bool]:
    """Return a stable reason and whether a production-year-only patch is needed."""

    if source_value is None:
        return "source_empty_or_invalid", False
    if current_year_is_missing_or_corrupt(current_value):
        return "current_missing_or_corrupt", True
    if str(current_value).strip() == source_value:
        return "already_correct", False
    return "current_valid_different", False


@dataclass
class RepairStats:
    source_rows_scanned: int = 0
    source_rows_with_production_year: int = 0
    source_rows_empty_or_invalid: int = 0
    source_non_yyyy_values: int = 0
    source_range_values: int = 0
    source_duplicate_rows: int = 0
    source_conflicts: int = 0
    source_count_drift_events: int = 0
    source_count_drift_rows: int = 0
    current_missing_or_corrupt: int = 0
    current_valid_different_skipped: int = 0
    unchanged_or_skipped: int = 0
    actual_typesense_updates: int = 0
    planned_typesense_updates: int = 0
    typesense_write_batches: int = 0
    unresolved_document_ids: int = 0
    pages_completed: int = 0
    partitions_completed: int = 0
    errors: int = 0
    source_values: Counter[str] = field(default_factory=Counter)
    range_examples: list[dict[str, str]] = field(default_factory=list)
    yyyy_examples: list[dict[str, str]] = field(default_factory=list)
    unresolved_examples: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_rows_scanned": self.source_rows_scanned,
            "source_rows_with_production_year": self.source_rows_with_production_year,
            "source_rows_empty_or_invalid": self.source_rows_empty_or_invalid,
            "source_non_yyyy_values": self.source_non_yyyy_values,
            "source_range_values": self.source_range_values,
            "source_duplicate_rows": self.source_duplicate_rows,
            "source_conflicts": self.source_conflicts,
            "source_count_drift_events": self.source_count_drift_events,
            "source_count_drift_rows": self.source_count_drift_rows,
            "current_missing_or_corrupt": self.current_missing_or_corrupt,
            "current_valid_different_skipped": self.current_valid_different_skipped,
            "unchanged_or_skipped": self.unchanged_or_skipped,
            "planned_typesense_updates": self.planned_typesense_updates,
            "actual_typesense_updates": self.actual_typesense_updates,
            "typesense_write_batches": self.typesense_write_batches,
            "unresolved_document_ids": self.unresolved_document_ids,
            "pages_completed": self.pages_completed,
            "partitions_completed": self.partitions_completed,
            "errors": self.errors,
            "source_values_top": [
                {"value": value, "count": count}
                for value, count in self.source_values.most_common(20)
            ],
            "range_examples": self.range_examples[:20],
            "yyyy_examples": self.yyyy_examples[:20],
            "unresolved_examples": self.unresolved_examples[:20],
            "error_messages": self.error_messages[-20:],
        }


class RepairState:
    """Separate repair checkpoint; active ingestion state is read-only."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS repair_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS repair_pages (
                source_key TEXT NOT NULL,
                partition_date TEXT NOT NULL,
                leaf_index INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                leaf_from TEXT NOT NULL,
                leaf_to TEXT NOT NULL,
                expected_count INTEGER NOT NULL,
                observation_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_key, partition_date, leaf_index, page_number)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS repair_partitions (
                source_key TEXT NOT NULL,
                partition_date TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_key, partition_date)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS repair_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                msc_requests INTEGER NOT NULL DEFAULT 0,
                msc_retries INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self.connection.commit()

    def set_meta(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT INTO repair_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )
        self.connection.commit()

    def get_meta(self, key: str) -> Any | None:
        row = self.connection.execute("SELECT value FROM repair_meta WHERE key=?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def start_run(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO repair_runs(started_at,status) VALUES(?,?)",
            (_utc_now(), "RUNNING"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, *, status: str, msc_requests: int, msc_retries: int, errors: int) -> None:
        self.connection.execute(
            "UPDATE repair_runs SET finished_at=?,status=?,msc_requests=?,msc_retries=?,errors=? WHERE run_id=?",
            (_utc_now(), status, msc_requests, msc_retries, errors, run_id),
        )
        self.connection.commit()

    def page_done(
        self,
        source_key: str,
        partition_date: str,
        leaf_index: int,
        page_number: int,
        leaf: SearchInterval,
    ) -> bool:
        row = self.connection.execute(
            """SELECT leaf_from,leaf_to FROM repair_pages
               WHERE source_key=? AND partition_date=? AND leaf_index=? AND page_number=?""",
            (source_key, partition_date, leaf_index, page_number),
        ).fetchone()
        return row is not None and row[0] == leaf.from_value and row[1] == leaf.to_value

    def mark_page(
        self,
        source_key: str,
        partition_date: str,
        leaf_index: int,
        page_number: int,
        leaf: SearchInterval,
        expected_count: int,
        observation: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            """INSERT INTO repair_pages
               (source_key,partition_date,leaf_index,page_number,leaf_from,leaf_to,expected_count,observation_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_key,partition_date,leaf_index,page_number) DO UPDATE SET
                 leaf_from=excluded.leaf_from, leaf_to=excluded.leaf_to,
                 expected_count=excluded.expected_count, observation_json=excluded.observation_json,
                 updated_at=excluded.updated_at""",
            (
                source_key, partition_date, leaf_index, page_number,
                leaf.from_value, leaf.to_value, expected_count,
                json.dumps(observation, ensure_ascii=False, sort_keys=True), _utc_now(),
            ),
        )
        self.connection.commit()

    def mark_partition(self, source_key: str, partition_date: str, status: str, error: str | None = None) -> None:
        self.connection.execute(
            """INSERT INTO repair_partitions(source_key,partition_date,status,error_message,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(source_key,partition_date) DO UPDATE SET
                 status=excluded.status,error_message=excluded.error_message,updated_at=excluded.updated_at""",
            (source_key, partition_date, status, error, _utc_now()),
        )
        self.connection.commit()

    def partition_done(self, source_key: str, partition_date: str) -> bool:
        row = self.connection.execute(
            "SELECT status FROM repair_partitions WHERE source_key=? AND partition_date=?",
            (source_key, partition_date),
        ).fetchone()
        return row is not None and row[0] == "COMPLETED"

    def aggregate_observations(self) -> RepairStats:
        stats = RepairStats()
        rows = self.connection.execute("SELECT observation_json FROM repair_pages").fetchall()
        for (raw,) in rows:
            observation = json.loads(raw)
            for name in (
                "source_rows_scanned", "source_rows_with_production_year", "source_rows_empty_or_invalid",
                "source_non_yyyy_values", "source_range_values", "source_duplicate_rows", "source_conflicts",
                "source_count_drift_events", "source_count_drift_rows",
                "current_missing_or_corrupt", "current_valid_different_skipped", "unchanged_or_skipped",
                "planned_typesense_updates", "actual_typesense_updates", "typesense_write_batches",
                "unresolved_document_ids",
            ):
                setattr(stats, name, getattr(stats, name) + int(observation.get(name, 0)))
            stats.pages_completed += 1
            stats.source_values.update(observation.get("source_values", {}))
            stats.range_examples.extend(observation.get("range_examples", []))
            stats.yyyy_examples.extend(observation.get("yyyy_examples", []))
            stats.unresolved_examples.extend(observation.get("unresolved_examples", []))
        stats.partitions_completed = int(self.connection.execute(
            "SELECT count(*) FROM repair_partitions WHERE status='COMPLETED'"
        ).fetchone()[0])
        failed = self.connection.execute(
            "SELECT error_message FROM repair_partitions WHERE status='FAILED' AND error_message IS NOT NULL ORDER BY updated_at"
        ).fetchall()
        stats.errors = len(failed)
        stats.error_messages = [str(row[0]) for row in failed]
        return stats

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "RepairState":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class CurrentYearIndex:
    """Streaming current active-generation projection keyed by exact document ID."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS current_year (id TEXT PRIMARY KEY, production_year)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.commit()

    def _meta(self, key: str) -> Any | None:
        row = self.connection.execute("SELECT value FROM index_meta WHERE key=?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def _set_meta(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT INTO index_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def ensure(
        self,
        client: TypesenseClient,
        collection: str,
        generation: str,
        expected_count: int,
        *,
        timeout_seconds: float,
        progress_every: int = 100_000,
    ) -> None:
        ready = self._meta("complete") is True
        if ready and self._meta("collection") == collection and self._meta("generation") == generation and self._meta("document_count") == expected_count:
            return
        self.connection.execute("DELETE FROM current_year")
        self._set_meta("complete", False)
        self._set_meta("collection", collection)
        self._set_meta("generation", generation)
        self._set_meta("document_count", expected_count)
        self.connection.commit()
        inserted = 0
        batch: list[tuple[str, Any]] = []
        for document in client.export_documents(
            collection, include_fields=("id", "production_year"), timeout_seconds=timeout_seconds
        ):
            document_id = document.get("id")
            if not isinstance(document_id, str) or not document_id:
                raise RepairError("Typesense export contained a document without a valid id")
            batch.append((document_id, document.get("production_year")))
            if len(batch) >= 10_000:
                self.connection.executemany("INSERT OR REPLACE INTO current_year(id,production_year) VALUES(?,?)", batch)
                self.connection.commit()
                inserted += len(batch)
                batch.clear()
                if progress_every and inserted % progress_every == 0:
                    LOGGER.info("production_year_index exported=%s", inserted)
        if batch:
            self.connection.executemany("INSERT OR REPLACE INTO current_year(id,production_year) VALUES(?,?)", batch)
            inserted += len(batch)
        actual = int(self.connection.execute("SELECT count(*) FROM current_year").fetchone()[0])
        if actual != expected_count:
            self.connection.rollback()
            raise RepairError(f"Typesense export count mismatch: {actual} != {expected_count}")
        self._set_meta("complete", True)
        self._set_meta("exported_at", _utc_now())
        self.connection.commit()
        LOGGER.info("production_year_index complete documents=%s", inserted)

    def get_many(self, ids: Sequence[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for offset in range(0, len(ids), 900):
            chunk = list(dict.fromkeys(ids[offset:offset + 900]))
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"SELECT id,production_year FROM current_year WHERE id IN ({placeholders})", chunk
            ).fetchall()
            result.update({str(row[0]): row[1] for row in rows})
        return result

    def apply_local(self, updates: Sequence[Mapping[str, str]]) -> None:
        self.connection.executemany(
            "UPDATE current_year SET production_year=? WHERE id=?",
            [(item["production_year"], item["id"]) for item in updates],
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CurrentYearIndex":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def load_goods_partitions(
    checkpoint_path: str | Path,
    generation: str,
    from_date: str,
    to_date: str,
) -> list[tuple[str, str, int]]:
    """Read only non-empty completed goods partitions from active state."""

    path = Path(checkpoint_path)
    if not path.is_file():
        raise RepairError(f"active checkpoint does not exist: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            """SELECT source_key,partition_date,coalesce(unique_uuid_count,0)
               FROM ingestion_checkpoint
               WHERE sink_target=? AND status='COMPLETED'
                 AND source_key IN (?,?) AND partition_date>=? AND partition_date<=?
                 AND coalesce(unique_uuid_count,0)>0
               ORDER BY partition_date,source_key""",
            (f"typesense:{generation}", *GOODS_SOURCE_KEYS, from_date, to_date),
        ).fetchall()
        return [(str(row[0]), str(row[1]), int(row[2])) for row in rows]
    finally:
        connection.close()


def group_goods_partitions(
    partitions: Sequence[tuple[str, str, int]],
    *,
    max_rows: int = 9500,
) -> list[tuple[str, str, SearchInterval, int]]:
    """Coalesce adjacent non-empty days into bounded sequential MSC windows."""

    if max_rows <= 0:
        raise ValueError("max_rows must be positive")
    grouped: list[tuple[str, str, SearchInterval, int]] = []
    by_source: dict[str, list[tuple[date, int]]] = {}
    for source_key, partition_date, count in partitions:
        by_source.setdefault(source_key, []).append((date.fromisoformat(partition_date), count))
    for source_key, entries in by_source.items():
        entries.sort()
        start: date | None = None
        end: date | None = None
        total = 0

        def flush() -> None:
            nonlocal start, end, total
            if start is None or end is None:
                return
            first = official_day_interval(start)
            last = official_day_interval(end)
            label = start.isoformat() if start == end else f"{start.isoformat()}..{end.isoformat()}"
            grouped.append((source_key, label, SearchInterval(first.from_value, last.to_value), total))
            start = end = None
            total = 0

        for current, count in entries:
            contiguous = end is not None and current == end + timedelta(days=1)
            if start is None:
                start = end = current
                total = count
                continue
            if not contiguous or total + count > max_rows:
                flush()
                start = end = current
                total = count
                continue
            end = current
            total += count
        flush()
    grouped.sort(key=lambda item: (item[2].from_value, item[0]))
    return grouped


def _page_content(response: Mapping[str, Any], page_number: int, page_size: int, expected_count: int) -> list[dict[str, Any]]:
    page = response.get("page")
    if not isinstance(page, Mapping):
        raise RepairError("MSC response missing page envelope")
    if page.get("currentPage") != page_number or page.get("pageSize") != page_size:
        raise RepairError(f"MSC page metadata mismatch at page {page_number}")
    if page.get("totalElements") != expected_count:
        raise RepairError(f"MSC page count changed expected={expected_count} actual={page.get('totalElements')}")
    content = page.get("content")
    if not isinstance(content, list) or not all(isinstance(item, dict) for item in content):
        raise RepairError("MSC page content is not an object array")
    required_pages = max(1, calculate_required_pages(expected_count, page_size, max_safe_results=9500, result_window=10000))
    if page.get("totalPages") not in ({0, 1} if not expected_count else {required_pages}):
        raise RepairError(f"MSC totalPages mismatch expected={required_pages} actual={page.get('totalPages')}")
    return content


def _observation_for_page(
    client: TypesenseClient,
    collection: str,
    index: CurrentYearIndex,
    source_key: str,
    partition_date: str,
    raw_records: Sequence[Mapping[str, Any]],
    seen_ids: set[str],
    seen_values: dict[str, str | None],
    *,
    dry_run: bool,
    batch_size: int,
    stats: RepairStats,
) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "source_rows_scanned": len(raw_records),
        "source_rows_with_production_year": 0,
        "source_rows_empty_or_invalid": 0,
        "source_non_yyyy_values": 0,
        "source_range_values": 0,
        "source_duplicate_rows": 0,
        "source_conflicts": 0,
        "source_count_drift_events": 0,
        "source_count_drift_rows": 0,
        "current_missing_or_corrupt": 0,
        "current_valid_different_skipped": 0,
        "unchanged_or_skipped": 0,
        "planned_typesense_updates": 0,
        "actual_typesense_updates": 0,
        "typesense_write_batches": 0,
        "unresolved_document_ids": 0,
        "source_values": Counter(),
        "range_examples": [],
        "yyyy_examples": [],
        "unresolved_examples": [],
    }
    candidates: list[dict[str, str]] = []
    candidate_ids: list[str] = []
    for raw in raw_records:
        stats.source_rows_scanned += 1
        source_id = raw.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise RepairError(f"source row in {source_key}/{partition_date} has no id")
        source_value = source_production_year(source_key, raw)
        if source_id in seen_ids:
            stats.source_duplicate_rows += 1
            observation["source_duplicate_rows"] += 1
            if seen_values[source_id] != source_value:
                stats.source_conflicts += 1
                observation["source_conflicts"] += 1
                raise RepairError(f"source UUID content conflict for {source_id}")
            if source_value is None:
                stats.source_rows_empty_or_invalid += 1
                observation["source_rows_empty_or_invalid"] += 1
            else:
                observation["source_rows_with_production_year"] += 1
                observation["source_values"][source_value] = observation["source_values"].get(source_value, 0) + 1
            continue
        seen_ids.add(source_id)
        seen_values[source_id] = source_value
        if source_value is None:
            stats.source_rows_empty_or_invalid += 1
            observation["source_rows_empty_or_invalid"] += 1
            continue
        observation["source_rows_with_production_year"] += 1
        observation["source_values"][source_value] = observation["source_values"].get(source_value, 0) + 1
        if not _YEAR_ONLY_RE.fullmatch(source_value):
            observation["source_non_yyyy_values"] += 1
            if "-" in source_value:
                observation["source_range_values"] += 1
            if len(observation["range_examples"]) < 5:
                observation["range_examples"].append({"id": source_id, "partition_date": partition_date, "value": source_value})
        elif len(observation["yyyy_examples"]) < 5:
            observation["yyyy_examples"].append({"id": source_id, "partition_date": partition_date, "value": source_value})
        candidate_ids.append(source_id)
        candidates.append({"id": source_id, "production_year": source_value})

    current = index.get_many(candidate_ids)
    updates: list[dict[str, str]] = []
    for candidate in candidates:
        source_id = candidate["id"]
        source_value = candidate["production_year"]
        if source_id not in current:
            stats.unresolved_document_ids += 1
            observation["unresolved_document_ids"] += 1
            if len(observation["unresolved_examples"]) < 5:
                observation["unresolved_examples"].append(source_id)
            continue
        reason, should_update = repair_decision(source_value, current[source_id])
        if reason == "current_missing_or_corrupt":
            stats.current_missing_or_corrupt += 1
            observation["current_missing_or_corrupt"] += 1
        elif reason == "current_valid_different":
            stats.current_valid_different_skipped += 1
            observation["current_valid_different_skipped"] += 1
        else:
            stats.unchanged_or_skipped += 1
            observation["unchanged_or_skipped"] += 1
        if should_update:
            updates.append(candidate)
    observation["planned_typesense_updates"] = len(updates)
    stats.planned_typesense_updates += len(updates)
    if dry_run:
        return observation
    for offset in range(0, len(updates), batch_size):
        batch = updates[offset:offset + batch_size]
        if any(set(item) != {"id", "production_year"} for item in batch):
            raise RepairError("repair attempted to send an unrelated field")
        result = client.import_documents(collection, batch, action="update")
        observation["typesense_write_batches"] += 1
        observation["actual_typesense_updates"] += result.accepted_count
        stats.typesense_write_batches += 1
        stats.actual_typesense_updates += result.accepted_count
        if result.rejected_count:
            raise RepairError(
                f"Typesense production_year update rejected={result.rejected_count}: {'; '.join(result.errors[:3])}"
            )
        index.apply_local(batch)
    return observation


def run_repair(
    *,
    serving_checkpoint: str | Path,
    generation: str,
    repair_state_path: str | Path,
    index_path: str | Path,
    from_date: str,
    to_date: str,
    dry_run: bool,
    max_partitions: int | None = None,
    batch_size: int = 500,
    msc_config: MSCConfig | None = None,
    typesense_config: TypesenseConfig | None = None,
    progress_every: int = 100_000,
) -> dict[str, Any]:
    if dry_run is False and generation != "serving_v1_20260910_raw_v2":
        raise RepairError("repair is pinned to the declared active generation")
    source_partitions = load_goods_partitions(serving_checkpoint, generation, from_date, to_date)
    partitions = group_goods_partitions(source_partitions, max_rows=9500)
    if max_partitions is not None:
        partitions = partitions[:max_partitions]
    if not partitions:
        raise RepairError("no non-empty completed goods partitions selected")
    ts_config = typesense_config or TypesenseConfig.from_env()
    client = TypesenseClient(ts_config)
    collection = physical_collection_name("goods", generation)
    collection_meta = client.get_collection(collection)
    if not collection_meta:
        raise RepairError(f"active goods collection is missing: {collection}")
    expected_documents = int(collection_meta.get("num_documents", 0))
    if expected_documents <= 0:
        raise RepairError("active goods collection has no documents")
    with RepairState(repair_state_path) as state, CurrentYearIndex(index_path) as index:
        state.set_meta("repair_version", REPAIR_VERSION)
        state.set_meta("generation", generation)
        state.set_meta("collection", collection)
        state.set_meta("dry_run", dry_run)
        state.set_meta("from_date", from_date)
        state.set_meta("to_date", to_date)
        run_id = state.start_run()
        msc = MSCClient(msc_config or MSCConfig())
        repair_errors = 0
        try:
            index.ensure(
                client, collection, generation, expected_documents,
                timeout_seconds=max(ts_config.timeout_seconds, 600), progress_every=progress_every,
            )
            config = msc.config
            local_stats = RepairStats()
            for partition_number, (source_key, partition_date, parent_interval, checkpoint_count) in enumerate(partitions, 1):
                if state.partition_done(source_key, partition_date):
                    continue
                LOGGER.info(
                    "production_year_repair partition=%s/%s source=%s date=%s checkpoint_rows=%s",
                    partition_number, len(partitions), source_key, partition_date, checkpoint_count,
                )
                partition_started = time.monotonic()
                before_requests = msc.stats.request_count
                seen_ids: set[str] = set()
                seen_values: dict[str, str | None] = {}
                partition_count_drifted = False
                try:
                    count_interval = lambda interval: msc.count_interval(get_contract(source_key), interval)
                    try:
                        plan = plan_partition(
                            parent_interval,
                            count_interval,
                            config=config,
                            # The active serving checkpoint contains the exact
                            # completed-row count for this source/day.  Reuse it
                            # as the root count; every fetched page still proves
                            # it via MSC's response aggregation.  Only oversized
                            # days need fresh child-count requests for splitting.
                            initial_count=checkpoint_count,
                        )
                    except PartitioningError as checkpoint_error:
                        # Historical MSC results can drift after ingestion.  If
                        # the checkpoint root no longer reconciles with fresh
                        # child counts, re-plan once from MSC's current parent
                        # count instead of failing a safe, resumable repair.
                        LOGGER.warning(
                            "production_year_repair stale_checkpoint_replan source=%s date=%s error=%s",
                            source_key, partition_date, checkpoint_error,
                        )
                        plan = plan_partition(parent_interval, count_interval, config=config)
                    for leaf_index, leaf in enumerate(plan.safe_leaves):
                        expected_count = int(leaf.expected_count or 0)
                        required_pages = max(1, calculate_required_pages(
                            expected_count, config.page_size,
                            max_safe_results=config.max_safe_results,
                            result_window=config.result_window,
                        ))
                        page_number = 0
                        while page_number < required_pages:
                            # A page checkpoint is retained for audit, but an
                            # interrupted partition is replayed from page 0.
                            # That keeps the cross-leaf UUID union proof intact
                            # without retaining millions of IDs in the state DB.
                            response = msc.fetch_page(get_contract(source_key), leaf, page_number)
                            if page_number == 0:
                                response_count = parse_search_count(response)
                                if response_count != expected_count:
                                    if response_count > config.max_safe_results:
                                        raise RepairError(
                                            "MSC aggregation drift made leaf unsafe "
                                            f"expected={expected_count} actual={response_count}"
                                        )
                                    local_stats.source_count_drift_events += 1
                                    local_stats.source_count_drift_rows += abs(response_count - expected_count)
                                    partition_count_drifted = True
                                    LOGGER.warning(
                                        "production_year_repair source_count_drift source=%s date=%s "
                                        "leaf=%s expected=%s actual=%s",
                                        source_key, partition_date, leaf_index, expected_count, response_count,
                                    )
                                    expected_count = response_count
                                    required_pages = max(1, calculate_required_pages(
                                        expected_count, config.page_size,
                                        max_safe_results=config.max_safe_results,
                                        result_window=config.result_window,
                                    ))
                            records = _page_content(response, page_number, config.page_size, expected_count)
                            observation = _observation_for_page(
                                client, collection, index, source_key, partition_date, records,
                                seen_ids, seen_values, dry_run=dry_run, batch_size=batch_size, stats=local_stats,
                            )
                            if page_number == 0 and response_count != int(leaf.expected_count or 0):
                                observation["source_count_drift_events"] = 1
                                observation["source_count_drift_rows"] = abs(
                                    response_count - int(leaf.expected_count or 0)
                                )
                            state.mark_page(source_key, partition_date, leaf_index, page_number, leaf, expected_count, observation)
                            LOGGER.info(
                                "production_year_repair page source=%s date=%s leaf=%s page=%s rows=%s updates=%s elapsed_seconds=%.3f",
                                source_key, partition_date, leaf_index, page_number,
                                len(records), observation["actual_typesense_updates"], time.monotonic() - partition_started,
                            )
                            page_number += 1
                    expected_union = plan.parent_interval.expected_count
                    if expected_union is None or len(seen_ids) != expected_union:
                        if not partition_count_drifted:
                            raise RepairError(f"source UUID union mismatch expected={expected_union} actual={len(seen_ids)}")
                        LOGGER.warning(
                            "production_year_repair source_union_drift source=%s date=%s expected=%s actual=%s",
                            source_key, partition_date, expected_union, len(seen_ids),
                        )
                    state.mark_partition(source_key, partition_date, "COMPLETED")
                    LOGGER.info(
                        "production_year_repair partition_completed source=%s date=%s rows=%s requests=%s elapsed_seconds=%.3f",
                        source_key, partition_date, len(seen_ids), msc.stats.request_count - before_requests,
                        time.monotonic() - partition_started,
                    )
                except Exception as exc:
                    repair_errors += 1
                    state.mark_partition(source_key, partition_date, "FAILED", str(exc))
                    LOGGER.error("production_year_repair partition_failed source=%s date=%s error=%s", source_key, partition_date, exc)
                    raise
            aggregate = state.aggregate_observations()
            state.finish_run(
                run_id, status="PASS" if repair_errors == 0 else "FAILED",
                msc_requests=msc.stats.request_count, msc_retries=msc.stats.retry_count, errors=repair_errors,
            )
            return {
                "repair_version": REPAIR_VERSION,
                "status": "PASS" if repair_errors == 0 else "FAILED",
                "dry_run": dry_run,
                "generation": generation,
                "collection": collection,
                "from_date": from_date,
                "to_date": to_date,
                "source_partitions_selected": len(source_partitions),
                "partitions_selected": len(partitions),
                "partitions_completed": aggregate.partitions_completed,
                "stats": aggregate.as_dict(),
                "msc": {
                    "requests": msc.stats.request_count,
                    "retries": msc.stats.retry_count,
                    "http_errors": msc.stats.http_error_count,
                    "elapsed_seconds": msc.stats.elapsed_seconds,
                },
                "typesense": {"writes": aggregate.actual_typesense_updates, "write_batches": aggregate.typesense_write_batches},
                "checkpoint": str(repair_state_path),
                "current_year_index": str(index_path),
            }
        except Exception:
            state.finish_run(
                run_id, status="FAILED", msc_requests=msc.stats.request_count,
                msc_retries=msc.stats.retry_count, errors=max(1, repair_errors),
            )
            raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_report(path: str | Path, report: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
