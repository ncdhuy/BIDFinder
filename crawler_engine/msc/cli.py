"""Operator CLI for controlled MSC public-search validation/crawling."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from .checkpoint import CheckpointStore
from .client import MSCClient
from .config import DEFAULT_CHECKPOINT_PATH, MSCConfig
from .contracts import SOURCE_CONTRACTS
from .engine import EngineError, MSCIngestionEngine
from .models import IngestionStatus
from .sink import InMemorySink, JsonlValidationSink


def _sources(value: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if values == ("all",):
        return tuple(SOURCE_CONTRACTS)
    unknown = sorted(set(values) - set(SOURCE_CONTRACTS))
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown source key(s): {', '.join(unknown)}")
    if not values:
        raise argparse.ArgumentTypeError("at least one source key is required")
    return values


def _single_source(value: str) -> tuple[str, ...]:
    return _sources(value)


def _day(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    validate = sub.add_parser("validate", help="validate one source/date partition")
    validate.add_argument("--source", required=True, type=_single_source)
    validate.add_argument("--date", required=True, type=_day)
    validate.add_argument("--output-dir", type=Path)
    validate.add_argument("--checkpoint", type=Path)
    validate.add_argument("--force", action="store_true")
    validate.add_argument("--allow-open-day", action="store_true")
    crawl = sub.add_parser("crawl", help="crawl explicit source/date range sequentially")
    crawl.add_argument("--from", dest="from_date", required=True, type=_day)
    crawl.add_argument("--to", dest="to_date", required=True, type=_day)
    crawl.add_argument("--sources", required=True, type=_sources)
    crawl.add_argument("--output-dir", type=Path)
    crawl.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT_PATH)
    crawl.add_argument("--force", action="store_true")
    crawl.add_argument("--allow-open-day", action="store_true")
    crawl.add_argument("--dry-run", action="store_true", help="use in-memory sink; do not write JSONL")
    crawl.add_argument("--max-partitions", type=int)
    for command in (validate, crawl):
        command.add_argument("--timeout", type=float, default=30.0)
        command.add_argument("--request-delay", type=float, default=1.0)
        command.add_argument("--max-retries", type=int, default=3)
        command.add_argument("--page-size", type=int, default=1000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = MSCConfig(
            timeout_seconds=args.timeout, request_delay_seconds=args.request_delay,
            max_retries=args.max_retries, page_size=args.page_size,
        )
        checkpoint_path = args.checkpoint if getattr(args, "checkpoint", None) else ":memory:"
        sink = InMemorySink()
        if getattr(args, "output_dir", None) and not getattr(args, "dry_run", False):
            sink = JsonlValidationSink(args.output_dir)
        with CheckpointStore(checkpoint_path) as checkpoints:
            engine = MSCIngestionEngine(MSCClient(config), checkpoints, sink, config)
            if args.operation == "validate":
                source_keys = args.source
                results = [
                    engine.ingest_partition(
                        source_key, args.date, force=args.force,
                        allow_open_day=args.allow_open_day,
                    )
                    for source_key in source_keys
                ]
            else:
                results = engine.crawl_range(
                    args.from_date, args.to_date, args.sources, force=args.force,
                    allow_open_day=args.allow_open_day, max_partitions=args.max_partitions,
                )
        for result in results:
            print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if all(result.status in {IngestionStatus.COMPLETED, IngestionStatus.VALIDATED} for result in results) else 1
    except (EngineError, ValueError, OSError) as exc:
        print(f"msc_cli_error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
