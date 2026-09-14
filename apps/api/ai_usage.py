"""Durable daily AI usage accounting backed by the application PostgreSQL pool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import inspect
import math
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
    """PostgreSQL ledger keyed by opaque identity and local Vietnam usage date."""

    def __init__(self, pool_or_provider: Any):
        self._pool_or_provider = pool_or_provider

    async def _pool(self) -> Any:
        pool = self._pool_or_provider
        if callable(pool):
            pool = pool()
            if inspect.isawaitable(pool):
                pool = await pool
        return pool

    async def get_units(self, identity_key: str, usage_date: str) -> float:
        usage_day = date.fromisoformat(usage_date)
        pool = await self._pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                """
                SELECT usage_units
                FROM app_ai_daily_usage
                WHERE identity_key = $1 AND usage_date = $2
                """,
                identity_key,
                usage_day,
            )
        return float(value) if value is not None else 0.0

    async def add_units(self, identity_key: str, usage_date: str, usage_units: float) -> float:
        increment = float(usage_units)
        if not math.isfinite(increment):
            increment = 0.0
        increment = max(0.0, increment)
        if increment <= 0:
            return await self.get_units(identity_key, usage_date)

        usage_day = date.fromisoformat(usage_date)
        pool = await self._pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                """
                INSERT INTO app_ai_daily_usage (identity_key, usage_date, usage_units)
                VALUES ($1, $2, $3)
                ON CONFLICT (identity_key, usage_date)
                DO UPDATE SET
                    usage_units = app_ai_daily_usage.usage_units + EXCLUDED.usage_units,
                    updated_at = NOW()
                RETURNING usage_units
                """,
                identity_key,
                usage_day,
                increment,
            )
        return float(value)

    async def snapshot(
        self,
        identity_key: str,
        usage_date: str,
        budget_units: float,
        reset_at: str,
    ) -> AIUsageSnapshot:
        used_units = await self.get_units(identity_key, usage_date)
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
