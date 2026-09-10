"""Run the goods-only historical production_year repair."""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
import sys

from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.production_year_repair import (
    DEFAULT_HISTORICAL_THROUGH,
    REPAIR_VERSION,
    RepairError,
    run_repair,
    write_report,
)


def _day(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-checkpoint", required=True, type=Path)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--repair-state", required=True, type=Path)
    parser.add_argument("--current-index", required=True, type=Path)
    parser.add_argument("--from", dest="from_date", required=True, type=_day)
    parser.add_argument("--to", dest="to_date", type=_day, default=DEFAULT_HISTORICAL_THROUGH)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-partitions", type=int)
    parser.add_argument("--page-size", type=int, default=9500)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--progress-every", type=int, default=100_000)
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run == args.apply:
        raise SystemExit("choose exactly one of --dry-run or --apply")
    if args.batch_size <= 0 or args.page_size <= 0:
        raise SystemExit("page and batch sizes must be positive")
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    msc_config = MSCConfig(
        page_size=args.page_size,
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        max_retries=args.max_retries,
    )
    try:
        report = run_repair(
            serving_checkpoint=args.serving_checkpoint,
            generation=args.generation,
            repair_state_path=args.repair_state,
            index_path=args.current_index,
            from_date=args.from_date,
            to_date=args.to_date,
            dry_run=args.dry_run,
            max_partitions=args.max_partitions,
            batch_size=args.batch_size,
            msc_config=msc_config,
            typesense_config=TypesenseConfig.from_env(),
            progress_every=args.progress_every,
        )
        write_report(args.report, report)
        print(report)
        return 0
    except RepairError as exc:
        logging.getLogger(__name__).error("%s: %s", REPAIR_VERSION, exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
