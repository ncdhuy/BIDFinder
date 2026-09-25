"""Read-only coverage check for the history chart's Postgres rollup."""

import asyncio
from datetime import timedelta
from pathlib import Path
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import asyncpg  # noqa: E402
import server  # noqa: E402


async def main() -> None:
    generation = server.typesense_search_repository.config.serving_generation
    display_day, _, _ = server.get_update_snapshot()
    if not server.DATABASE_URL:
        print("DATABASE_URL is unavailable")
        return

    connection = await asyncpg.connect(
        server.DATABASE_URL,
        ssl=server.db_ssl_config,
        timeout=8,
        command_timeout=8,
    )
    try:
        async with connection.transaction(readonly=True):
            table = await connection.fetchval("SELECT to_regclass('daily_approval_summary')")
            if table is None:
                print("daily_approval_summary is missing")
                return
            print(f"Serving generation: {generation}; display day: {display_day}")
            for days in (30, 90, 180):
                start_day = display_day - timedelta(days=days - 1)
                started = perf_counter()
                row = await connection.fetchrow(
                    """
                    SELECT count(*)::int AS present,
                           min(data_date) AS first_day,
                           max(data_date) AS last_day
                    FROM daily_approval_summary
                    WHERE data_date BETWEEN $1 AND $2
                      AND serving_generation = $3
                    """,
                    start_day,
                    display_day,
                    generation,
                )
                elapsed_ms = (perf_counter() - started) * 1000
                print(
                    f"{days} days: {row['present']}/{days} present, "
                    f"first={row['first_day']}, last={row['last_day']}, "
                    f"query={elapsed_ms:.1f} ms"
                )
            generations = await connection.fetch(
                """
                SELECT serving_generation, count(*)::int AS rows, max(data_date) AS last_day
                FROM daily_approval_summary
                GROUP BY serving_generation
                ORDER BY last_day DESC
                LIMIT 5
                """
            )
            for row in generations:
                print(f"Stored generation: {row['serving_generation']}, rows={row['rows']}, last={row['last_day']}")
            dashboard_table = await connection.fetchval("SELECT to_regclass('daily_update_dashboard')")
            if dashboard_table is not None:
                dashboard_rows = await connection.fetch(
                    """
                    SELECT data_date, computed_at
                    FROM daily_update_dashboard
                    WHERE serving_generation = $1 AND data_date BETWEEN $2 AND $3
                    ORDER BY data_date
                    """,
                    generation,
                    display_day - timedelta(days=1),
                    display_day,
                )
                print("Dashboard summary dates:", ", ".join(str(row["data_date"]) for row in dashboard_rows))
                started = perf_counter()
                dashboard = await server.fetch_update_dashboard(connection, display_day)
                print(
                    f"Dashboard API read: {(perf_counter() - started) * 1000:.1f} ms, "
                    f"data_date={dashboard['data_date']}"
                )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
