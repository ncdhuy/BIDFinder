"""Backfill and refresh the daily approval-count serving rollup.

The rollup is derived from the active Typesense serving generation and stored
in Neon/Postgres.  It deliberately contains one row per calendar day so the
metadata endpoint can answer 30/90/180-day chart requests with a tiny indexed
range read instead of rescanning Typesense documents.

Examples:

    python -m crawler_engine.sync_daily_approval_summary \
        --from 2023-02-01 --to 2026-09-21 \
        --generation "$BIDFINDER_SERVING_GENERATION"

    python -m crawler_engine.sync_daily_approval_summary \
        --from 2026-09-18 --to 2026-09-21 \
        --generation "$BIDFINDER_SERVING_GENERATION"
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import asyncpg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - production installs python-dotenv
    load_dotenv = None


LOGICAL_GROUPS = ("goods", "medicines", "traditional_medicine")
LOGICAL_ALIASES = {
    "goods": "bidfinder_goods",
    "medicines": "bidfinder_medicines",
    "traditional_medicine": "bidfinder_traditional",
}
GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TYPESENSE_MAX_HITS_PER_PAGE = 250
DEFAULT_WORKERS = 24
DEFAULT_TIMEOUT_SECONDS = 30.0
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
ROLLUP_BASIS_SUFFIX = ":decision_date"

SUMMARY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS daily_approval_summary (
    data_date DATE PRIMARY KEY,
    approved_package_count INTEGER NOT NULL CHECK (approved_package_count >= 0),
    serving_generation TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

DASHBOARD_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS daily_update_dashboard (
    data_date DATE PRIMARY KEY,
    summary JSONB NOT NULL,
    serving_generation TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _load_environment() -> None:
    if load_dotenv is None:
        return
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / "apps" / "api" / ".env", override=False)
    load_dotenv(root / "crawler_engine" / ".env", override=False)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def _date_range(start_day: date, end_day: date) -> list[date]:
    if start_day > end_day:
        raise ValueError("--from must be on or before --to")
    return [
        start_day + timedelta(days=offset)
        for offset in range((end_day - start_day).days + 1)
    ]


def _resolve_generation(explicit: str | None) -> str:
    generation = (
        explicit
        or os.getenv("BIDFINDER_SERVING_GENERATION")
        or os.getenv("BIDFINDER_TYPESENSE_SERVING_GENERATION")
    )
    if not generation:
        report_path = os.getenv("BIDFINDER_SERVING_REPORT_PATH")
        if report_path:
            try:
                report = json.loads(Path(report_path).read_text(encoding="utf-8"))
                generation = str(report.get("serving_generation") or "").strip()
            except (OSError, ValueError, TypeError):
                generation = None
    if not generation or not GENERATION_RE.fullmatch(generation):
        raise ValueError(
            "serving generation is required; pass --generation or configure "
            "BIDFINDER_SERVING_GENERATION"
        )
    return generation


def _resolve_typesense_config() -> tuple[str, str, float]:
    host = os.getenv("BIDFINDER_TYPESENSE_HOST") or os.getenv("TYPESENSE_HOST", "127.0.0.1")
    protocol = (os.getenv("BIDFINDER_TYPESENSE_PROTOCOL") or os.getenv("TYPESENSE_PROTOCOL", "http")).lower()
    port_text = os.getenv("BIDFINDER_TYPESENSE_PORT") or os.getenv("TYPESENSE_PORT", "8108")
    api_key = os.getenv("BIDFINDER_TYPESENSE_API_KEY") or os.getenv("TYPESENSE_API_KEY", "")
    timeout_text = os.getenv("BIDFINDER_TYPESENSE_TIMEOUT_SECONDS") or os.getenv("TYPESENSE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))

    if not host or "://" in host or "/" in host:
        raise ValueError("Typesense host must be a hostname or IP address without a scheme")
    if protocol not in {"http", "https"}:
        raise ValueError("Typesense protocol must be http or https")
    if not api_key:
        raise ValueError("Typesense API key is not configured")
    try:
        port = int(port_text)
        timeout = float(timeout_text)
    except ValueError as exc:
        raise ValueError("Typesense port/timeout configuration is invalid") from exc
    if not 1 <= port <= 65535 or timeout <= 0:
        raise ValueError("Typesense port/timeout configuration is invalid")
    return f"{protocol}://{host}:{port}", api_key, timeout


def collect_dashboard_summaries(
    days: Iterable[date], *, generation: str, timeout_seconds: float,
) -> list[tuple[date, dict[str, Any]]]:
    """Materialize the two display days using the API's existing summary rules."""
    api_dir = Path(__file__).resolve().parents[1] / "apps" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from typesense_shadow import TypesenseSearchRepository, TypesenseShadowConfig

    base_url, api_key, _ = _resolve_typesense_config()
    endpoint = urlsplit(base_url)
    repository = TypesenseSearchRepository(TypesenseShadowConfig(
        serving_generation=generation,
        timeout_seconds=timeout_seconds,
        host=endpoint.hostname or "127.0.0.1",
        port=endpoint.port or 8108,
        protocol=endpoint.scheme,
        api_key=api_key,
    ))
    return [(day, repository._request_daily_summary(day)) for day in sorted(set(days))]


def _fetch_package_codes(
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    logical_group: str,
    day: date,
    generation: str,
) -> set[str]:
    collection = f"{LOGICAL_ALIASES[logical_group]}_v1_{generation}"
    package_codes: set[str] = set()
    page = 1
    per_page = TYPESENSE_MAX_HITS_PER_PAGE

    while True:
        params = {
            "q": "*",
            "query_by": "bid_invitation_code",
            "page": page,
            "per_page": per_page,
            "filter_by": f"decision_date:={day.isoformat()}",
            "include_fields": "bid_invitation_code",
        }
        request = Request(
            f"{base_url}/collections/{quote(collection, safe='')}/documents/search?{urlencode(params)}",
            method="GET",
            headers={"Accept": "application/json", "X-TYPESENSE-API-KEY": api_key},
        )
        try:
            with urlopen(request, timeout=max(timeout_seconds, 2.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Typesense HTTP {exc.code} for {logical_group}/{day.isoformat()}") from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Typesense request failed for {logical_group}/{day.isoformat()}") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("found"), int) or payload["found"] < 0:
            raise RuntimeError("Typesense returned malformed timeline metadata")
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            raise RuntimeError("Typesense returned malformed timeline hits")
        for hit in hits:
            if not isinstance(hit, dict) or not isinstance(hit.get("document"), dict):
                continue
            code = str(hit["document"].get("bid_invitation_code") or "").strip()
            if code:
                package_codes.add(code)

        found = int(payload["found"])
        if page * per_page >= found or len(hits) < per_page:
            return package_codes
        page += 1


def collect_daily_counts(
    start_day: date,
    end_day: date,
    *,
    generation: str,
    workers: int = DEFAULT_WORKERS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[tuple[date, int]]:
    """Count distinct tender codes across groups, retaining zero days."""
    return collect_selected_daily_counts(
        _date_range(start_day, end_day),
        generation=generation,
        workers=workers,
        timeout_seconds=timeout_seconds,
    )


def collect_selected_daily_counts(
    days: Iterable[date],
    *,
    generation: str,
    workers: int = DEFAULT_WORKERS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[tuple[date, int]]:
    """Scan only the dates that changed or have no rollup row."""
    days = sorted(set(days))
    if not days:
        return []
    base_url, api_key, configured_timeout = _resolve_typesense_config()
    timeout_seconds = timeout_seconds or configured_timeout
    tasks = [(group, day) for group in LOGICAL_GROUPS for day in days]
    codes_by_day: dict[date, set[str]] = {day: set() for day in days}
    group_results_by_day: dict[date, int] = {day: 0 for day in days}
    counts_by_day: dict[date, int] = {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _fetch_package_codes,
                base_url,
                api_key,
                timeout_seconds,
                group,
                day,
                generation,
            ): (group, day)
            for group, day in tasks
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            _, day = futures.pop(future)
            codes_by_day[day].update(future.result())
            group_results_by_day[day] += 1
            if group_results_by_day[day] == len(LOGICAL_GROUPS):
                counts_by_day[day] = len(codes_by_day[day])
                del codes_by_day[day]
            if completed == len(tasks) or completed % 100 == 0:
                print(f"Scanned {completed}/{len(tasks)} serving partitions", flush=True)

    return [(day, counts_by_day.get(day, 0)) for day in days]


def _changed_days_from_report(path: Path | None, generation: str) -> set[date]:
    if path is None:
        return set()
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") == "SKIPPED":
        return set()
    if report.get("overall_status") != "PASS" or report.get("serving_generation") != generation:
        raise ValueError("incremental report does not match the successful serving generation")
    days = {
        _parse_date(str(value).rsplit(":", 1)[-1])
        for value in report.get("changed_partitions", [])
    }
    days.update(
        _parse_date(str(result["partition_date"]))
        for result in report.get("results", [])
        if not result.get("skipped") and result.get("partition_date")
    )
    return days


async def plan_refresh_days(
    start_day: date,
    end_day: date,
    *,
    generation: str,
    repair_history_days: int,
    changed_days: Iterable[date] = (),
) -> list[date]:
    """Refresh every displayed decision day, regardless of crawl partition dates."""
    repair_start = end_day - timedelta(days=repair_history_days - 1)
    # A changed crawl partition can contain decisions issued on different days.
    # Recompute the displayed history so those days cannot retain stale counts.
    selected = set(_date_range(start_day, end_day)) | set(_date_range(repair_start, end_day))
    return sorted(day for day in selected if day <= end_day)


async def write_daily_counts(
    rows: Iterable[tuple[date, int]],
    *,
    generation: str,
    dashboard_rows: Iterable[tuple[date, dict[str, Any]]] = (),
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")

    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(SUMMARY_TABLE_DDL)
        await connection.execute(DASHBOARD_TABLE_DDL)
        async with connection.transaction():
            await connection.executemany(
                """
                INSERT INTO daily_approval_summary (
                    data_date, approved_package_count, serving_generation, computed_at
                )
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (data_date) DO UPDATE SET
                    approved_package_count = EXCLUDED.approved_package_count,
                    serving_generation = EXCLUDED.serving_generation,
                    computed_at = EXCLUDED.computed_at
                """,
                ((data_day, count, generation + ROLLUP_BASIS_SUFFIX) for data_day, count in rows),
            )
            await connection.executemany(
                """
                INSERT INTO daily_update_dashboard (
                    data_date, summary, serving_generation, computed_at
                )
                VALUES ($1, $2::jsonb, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (data_date) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    serving_generation = EXCLUDED.serving_generation,
                    computed_at = EXCLUDED.computed_at
                """,
                ((day, json.dumps(summary, ensure_ascii=False), generation + ROLLUP_BASIS_SUFFIX) for day, summary in dashboard_rows),
            )
    finally:
        await connection.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start_day", required=True, type=_parse_date)
    parser.add_argument("--to", dest="end_day", required=True, type=_parse_date)
    parser.add_argument("--generation")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--incremental-report", type=Path, help="successful incremental output for changed partition dates")
    parser.add_argument("--repair-history-days", type=int, default=180, help="check this many recent chart days for missing rows")
    parser.add_argument("--dashboard-history-days", type=int, default=2, help="materialize this many latest KPI days")
    parser.add_argument("--dry-run", action="store_true", help="scan Typesense without writing Neon")
    return parser


def main() -> None:
    _load_environment()
    args = _build_parser().parse_args()
    if args.workers <= 0 or args.timeout <= 0 or args.repair_history_days <= 0 or args.dashboard_history_days <= 0:
        raise SystemExit("--workers, --timeout and history-day values must be positive")

    generation = _resolve_generation(args.generation)
    changed_days = _changed_days_from_report(args.incremental_report, generation)
    days = asyncio.run(plan_refresh_days(
        args.start_day, args.end_day,
        generation=generation,
        repair_history_days=args.repair_history_days,
        changed_days=changed_days,
    ))
    dashboard_days = [day for day in days if day >= args.end_day - timedelta(days=args.dashboard_history_days - 1)]
    dashboard_rows = collect_dashboard_summaries(
        dashboard_days, generation=generation, timeout_seconds=args.timeout,
    )
    dashboard_day_set = set(dashboard_days)
    rows = collect_selected_daily_counts(
        (day for day in days if day not in dashboard_day_set),
        generation=generation,
        workers=args.workers,
        timeout_seconds=args.timeout,
    )
    rows.extend((day, int(summary["approved_package_count"])) for day, summary in dashboard_rows)
    rows.sort(key=lambda row: row[0])
    total = len(rows)
    nonzero = sum(1 for _, count in rows if count)
    print(f"Computed {total} daily rows ({nonzero} non-zero) for {generation}", flush=True)
    if args.dry_run:
        return
    asyncio.run(write_daily_counts(rows, generation=generation, dashboard_rows=dashboard_rows))
    print("Wrote daily approval summary to Neon", flush=True)


if __name__ == "__main__":
    main()
