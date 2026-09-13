"""Durable daily AI usage accounting for the single-process API runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
import threading
from typing import Any


@dataclass(frozen=True)
class AIUsageSnapshot:
    used_units: float
    budget_units: float
    used_percent: int
    remaining_percent: int
    reset_at: str


def percentage_pair(used_units: float, budget_units: float) -> tuple[int, int]:
    if budget_units <= 0:
        return 100, 0
    used_percent = min(100, max(0, int(round(max(0.0, used_units) / budget_units * 100))))
    return used_percent, 100 - used_percent


class AIUsageStore:
    """SQLite ledger keyed by opaque identity and local Vietnam usage date."""

    # The API currently runs as one process. Multi-instance deployments should move
    # this ledger (and the Luna limiter) to a shared authority before scaling out.

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_daily_usage (
                identity_key TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                usage_units REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(identity_key, usage_date)
            )
            """
        )
        connection.commit()

    def get_units(self, identity_key: str, usage_date: str) -> float:
        with self._lock:
            connection = self._connect()
            try:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT usage_units FROM ai_daily_usage WHERE identity_key = ? AND usage_date = ?",
                    (identity_key, usage_date),
                ).fetchone()
            finally:
                connection.close()
        return float(row[0]) if row else 0.0

    def add_units(self, identity_key: str, usage_date: str, usage_units: float) -> float:
        increment = max(0.0, float(usage_units))
        if increment <= 0:
            return self.get_units(identity_key, usage_date)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            connection = self._connect()
            try:
                self._ensure_schema(connection)
                connection.execute(
                    """
                    INSERT INTO ai_daily_usage(identity_key, usage_date, usage_units, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(identity_key, usage_date) DO UPDATE SET
                        usage_units = ai_daily_usage.usage_units + excluded.usage_units,
                        updated_at = excluded.updated_at
                    """,
                    (identity_key, usage_date, increment, updated_at),
                )
                connection.commit()
                row = connection.execute(
                    "SELECT usage_units FROM ai_daily_usage WHERE identity_key = ? AND usage_date = ?",
                    (identity_key, usage_date),
                ).fetchone()
            finally:
                connection.close()
        return float(row[0]) if row else increment

    def snapshot(
        self,
        identity_key: str,
        usage_date: str,
        budget_units: float,
        reset_at: str,
    ) -> AIUsageSnapshot:
        used_units = self.get_units(identity_key, usage_date)
        used_percent, remaining_percent = percentage_pair(used_units, float(budget_units))
        return AIUsageSnapshot(
            used_units=used_units,
            budget_units=float(budget_units),
            used_percent=used_percent,
            remaining_percent=remaining_percent,
            reset_at=reset_at,
        )


def snapshot_payload(snapshot: AIUsageSnapshot, *, counted: bool) -> dict[str, Any]:
    return {
        "period": "daily",
        "used_percent": snapshot.used_percent,
        "remaining_percent": snapshot.remaining_percent,
        "reset_at": snapshot.reset_at,
        "counted": bool(counted),
    }
