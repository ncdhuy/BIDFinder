"""Durable, full-record exception ledger for operational SQLite state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Mapping


def ensure_exception_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS exception_ledger (
            exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            logical_group TEXT NOT NULL,
            source_key TEXT,
            partition_date TEXT,
            page_number INTEGER,
            leaf_index INTEGER,
            category TEXT NOT NULL,
            reason TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_exception_ledger_operation ON exception_ledger(operation_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_exception_ledger_source ON exception_ledger(source_id)"
    )


def record_exception(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    source_id: str,
    logical_group: str,
    category: str,
    reason: str,
    source_key: str | None = None,
    partition_date: str | None = None,
    page_number: int | None = None,
    leaf_index: int | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    if not operation_id or not source_id or not logical_group or not category or not reason:
        raise ValueError("exception ledger requires operation_id, source_id, logical_group, category, and reason")
    ensure_exception_ledger(connection)
    connection.execute(
        """INSERT INTO exception_ledger
           (operation_id,source_id,logical_group,source_key,partition_date,page_number,leaf_index,
            category,reason,details_json,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(operation_id), str(source_id), logical_group, source_key, partition_date,
            page_number, leaf_index, category, reason[:4000],
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    connection.commit()


def exception_rows(connection: sqlite3.Connection, operation_id: str | None = None) -> list[dict[str, Any]]:
    ensure_exception_ledger(connection)
    if operation_id is None:
        rows = connection.execute("SELECT * FROM exception_ledger ORDER BY exception_id").fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM exception_ledger WHERE operation_id=? ORDER BY exception_id", (str(operation_id),)
        ).fetchall()
    columns = [column[0] for column in connection.execute("SELECT * FROM exception_ledger LIMIT 0").description]
    return [dict(zip(columns, row)) for row in rows]


def exception_count(connection: sqlite3.Connection, operation_id: str | None = None) -> int:
    ensure_exception_ledger(connection)
    if operation_id is None:
        row = connection.execute("SELECT count(*) FROM exception_ledger").fetchone()
    else:
        row = connection.execute(
            "SELECT count(*) FROM exception_ledger WHERE operation_id=?", (str(operation_id),)
        ).fetchone()
    return int(row[0])
