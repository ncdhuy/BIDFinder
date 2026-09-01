"""Local SQLite operational checkpoint store; never application/search data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ENGINE_VERSION, SCHEMA_VERSION
from .models import IngestionStatus

DEFAULT_SINK_TARGET = "validation-jsonl"


@dataclass(frozen=True)
class Checkpoint:
    source_key: str
    partition_date: str
    sink_target: str
    status: IngestionStatus
    attempt_count: int
    parent_pre_count: int | None
    parent_post_count: int | None
    raw_fetched_count: int | None
    unique_uuid_count: int | None
    normalized_count: int | None
    sink_accepted_count: int | None
    started_at: str | None
    completed_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    engine_version: str
    schema_version: str


class CheckpointStore:
    """Durable state keyed by source key, official date, and sink target."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self._connection.commit()

    def _create_table(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS ingestion_checkpoint (
                source_key TEXT NOT NULL,
                partition_date TEXT NOT NULL,
                sink_target TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','VALIDATED','COMPLETED','FAILED','QUARANTINED')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                parent_pre_count INTEGER,
                parent_post_count INTEGER,
                raw_fetched_count INTEGER,
                unique_uuid_count INTEGER,
                normalized_count INTEGER,
                sink_accepted_count INTEGER,
                started_at TEXT,
                completed_at TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                engine_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_key, partition_date, sink_target)
            )"""
        )

    def _migrate(self) -> None:
        """Migrate Phase 2 source/date rows without discarding their state."""

        table = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ingestion_checkpoint'"
        ).fetchone()
        if table is None:
            self._create_table()
            return
        info = self._connection.execute("PRAGMA table_info(ingestion_checkpoint)").fetchall()
        columns = {row["name"] for row in info}
        primary_key = {row["name"] for row in info if row["pk"]}
        if "sink_target" in columns and primary_key == {"source_key", "partition_date", "sink_target"}:
            return

        legacy_table = "ingestion_checkpoint_phase2_legacy"
        legacy_exists = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (legacy_table,)
        ).fetchone()
        if legacy_exists is not None:
            raise RuntimeError("checkpoint migration left an existing legacy table; inspect before retrying")
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(f"ALTER TABLE ingestion_checkpoint RENAME TO {legacy_table}")
            self._create_table()
            self._connection.execute(
                f"""INSERT INTO ingestion_checkpoint
                   (source_key, partition_date, sink_target, status, attempt_count,
                    parent_pre_count, parent_post_count, raw_fetched_count, unique_uuid_count,
                    normalized_count, sink_accepted_count, started_at, completed_at,
                    last_error_code, last_error_message, engine_version, schema_version, updated_at)
                   SELECT source_key, partition_date, ?, status, attempt_count,
                    parent_pre_count, parent_post_count, raw_fetched_count, unique_uuid_count,
                    normalized_count, sink_accepted_count, started_at, completed_at,
                    last_error_code, last_error_message, engine_version, schema_version, updated_at
                   FROM {legacy_table}""",
                (DEFAULT_SINK_TARGET,),
            )
            self._connection.execute(f"DROP TABLE {legacy_table}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "CheckpointStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get(self, source_key: str, partition_date: str, sink_target: str = DEFAULT_SINK_TARGET) -> Checkpoint | None:
        row = self._connection.execute(
            "SELECT * FROM ingestion_checkpoint WHERE source_key=? AND partition_date=? AND sink_target=?",
            (source_key, partition_date, sink_target),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            source_key=row["source_key"], partition_date=row["partition_date"], sink_target=row["sink_target"],
            status=IngestionStatus(row["status"]), attempt_count=row["attempt_count"],
            parent_pre_count=row["parent_pre_count"], parent_post_count=row["parent_post_count"],
            raw_fetched_count=row["raw_fetched_count"], unique_uuid_count=row["unique_uuid_count"],
            normalized_count=row["normalized_count"], sink_accepted_count=row["sink_accepted_count"],
            started_at=row["started_at"], completed_at=row["completed_at"],
            last_error_code=row["last_error_code"], last_error_message=row["last_error_message"],
            engine_version=row["engine_version"], schema_version=row["schema_version"],
        )

    def list(self, sink_target: str | None = None) -> tuple[Checkpoint, ...]:
        """Return checkpoint rows for read-only audit/reporting."""

        if sink_target is None:
            rows = self._connection.execute(
                "SELECT source_key, partition_date, sink_target FROM ingestion_checkpoint ORDER BY partition_date, source_key, sink_target"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT source_key, partition_date, sink_target FROM ingestion_checkpoint WHERE sink_target=? ORDER BY partition_date, source_key",
                (sink_target,),
            ).fetchall()
        result = []
        for row in rows:
            checkpoint = self.get(row["source_key"], row["partition_date"], row["sink_target"])
            if checkpoint is not None:
                result.append(checkpoint)
        return tuple(result)

    def status_counts(self, sink_target: str | None = None) -> dict[str, int]:
        counts = {status.value: 0 for status in IngestionStatus}
        for checkpoint in self.list(sink_target):
            counts[checkpoint.status.value] += 1
        return counts

    def ensure(self, source_key: str, partition_date: str, sink_target: str = DEFAULT_SINK_TARGET) -> Checkpoint:
        """Create visible PENDING state without claiming the partition."""

        now = self._now()
        self._connection.execute(
            """INSERT INTO ingestion_checkpoint
               (source_key, partition_date, sink_target, status, attempt_count, engine_version,
                schema_version, updated_at)
               VALUES (?, ?, ?, 'PENDING', 0, ?, ?, ?)
               ON CONFLICT(source_key, partition_date, sink_target) DO NOTHING""",
            (source_key, partition_date, sink_target, ENGINE_VERSION, SCHEMA_VERSION, now),
        )
        self._connection.commit()
        return self.get(source_key, partition_date, sink_target)  # type: ignore[return-value]

    def start(self, source_key: str, partition_date: str, *, force: bool = False, sink_target: str = DEFAULT_SINK_TARGET) -> Checkpoint:
        self.ensure(source_key, partition_date, sink_target)
        current = self.get(source_key, partition_date, sink_target)
        if current and current.status == IngestionStatus.COMPLETED and not force:
            raise ValueError("completed checkpoint requires force=True")
        attempt = (current.attempt_count if current else 0) + 1
        now = self._now()
        self._connection.execute(
            """INSERT INTO ingestion_checkpoint
               (source_key, partition_date, sink_target, status, attempt_count, started_at,
                completed_at, last_error_code, last_error_message, engine_version,
                schema_version, updated_at)
               VALUES (?, ?, ?, 'RUNNING', ?, ?, NULL, NULL, NULL, ?, ?, ?)
               ON CONFLICT(source_key, partition_date, sink_target) DO UPDATE SET
                status='RUNNING', attempt_count=excluded.attempt_count,
                started_at=excluded.started_at, completed_at=NULL,
                last_error_code=NULL, last_error_message=NULL,
                engine_version=excluded.engine_version, schema_version=excluded.schema_version,
                updated_at=excluded.updated_at""",
            (source_key, partition_date, sink_target, attempt, now, ENGINE_VERSION, SCHEMA_VERSION, now),
        )
        self._connection.commit()
        return self.get(source_key, partition_date, sink_target)  # type: ignore[return-value]

    def update_metrics(self, source_key: str, partition_date: str, sink_target: str = DEFAULT_SINK_TARGET, **metrics: Any) -> None:
        allowed = {
            "parent_pre_count", "parent_post_count", "raw_fetched_count", "unique_uuid_count",
            "normalized_count", "sink_accepted_count",
        }
        values = {key: value for key, value in metrics.items() if key in allowed}
        if not values:
            return
        assignments = ", ".join(f"{key}=?" for key in values)
        values["updated_at"] = self._now()
        self._connection.execute(
            f"UPDATE ingestion_checkpoint SET {assignments}, updated_at=? WHERE source_key=? AND partition_date=? AND sink_target=?",
            (*[values[key] for key in metrics if key in allowed], values["updated_at"], source_key, partition_date, sink_target),
        )
        self._connection.commit()

    def finish(self, source_key: str, partition_date: str, status: IngestionStatus, *, sink_target: str = DEFAULT_SINK_TARGET, **metrics: Any) -> Checkpoint:
        if status not in {IngestionStatus.VALIDATED, IngestionStatus.COMPLETED}:
            raise ValueError("finish requires VALIDATED or COMPLETED")
        current = self.get(source_key, partition_date, sink_target)
        if current is None or current.status != IngestionStatus.RUNNING:
            raise ValueError("only RUNNING checkpoints can finish")
        self.update_metrics(source_key, partition_date, sink_target, **metrics)
        now = self._now()
        self._connection.execute(
            "UPDATE ingestion_checkpoint SET status=?, completed_at=?, updated_at=? WHERE source_key=? AND partition_date=? AND sink_target=?",
            (status.value, now, now, source_key, partition_date, sink_target),
        )
        self._connection.commit()
        return self.get(source_key, partition_date, sink_target)  # type: ignore[return-value]

    def fail(self, source_key: str, partition_date: str, code: str, message: str, *, quarantine: bool = False, sink_target: str = DEFAULT_SINK_TARGET, **metrics: Any) -> Checkpoint:
        current = self.get(source_key, partition_date, sink_target)
        if current is None:
            raise ValueError("checkpoint must exist before failure is recorded")
        if current.status != IngestionStatus.RUNNING:
            raise ValueError("only RUNNING checkpoints can fail")
        self.update_metrics(source_key, partition_date, sink_target, **metrics)
        status = IngestionStatus.QUARANTINED if quarantine else IngestionStatus.FAILED
        now = self._now()
        self._connection.execute(
            "UPDATE ingestion_checkpoint SET status=?, last_error_code=?, last_error_message=?, updated_at=? WHERE source_key=? AND partition_date=? AND sink_target=?",
            (status.value, code, message[:2000], now, source_key, partition_date, sink_target),
        )
        self._connection.commit()
        return self.get(source_key, partition_date, sink_target)  # type: ignore[return-value]
