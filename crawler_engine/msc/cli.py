"""Operator CLI for controlled MSC public-search validation/crawling."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import sys
from datetime import date
from pathlib import Path

from .checkpoint import CheckpointStore
from .backfill import (
    BackfillControlError,
    BackfillRunner,
    UUIDProvenanceStore,
    AuditedSink,
    atomic_write_json,
    build_manifest,
    capacity_preflight,
    estimate_capacity,
    historical_backfill_audit,
    load_fixture_samples,
    plan_summary,
    ordered_source_keys,
    require_full_run_authorization,
    source_population_preflight,
    run_search_benchmark,
    verify_manifest,
)
from .client import MSCClient
from .config import DEFAULT_CHECKPOINT_PATH, MSCConfig, TypesenseConfig
from .contracts import SOURCE_CONTRACTS
from .engine import EngineError, MSCIngestionEngine
from .models import IngestionStatus
from .sink import InMemorySink, JsonlValidationSink, TypesenseSink
from .typesense_client import TypesenseClient, TypesenseCollectionManager, TypesenseError
from .serving import (
    latest_closed_day,
    next_incremental_start,
    render_serving_report_markdown,
    run_incremental,
    run_prefix_extension,
)


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


def _write_or_print(payload: dict, output: Path | None) -> None:
    if output:
        atomic_write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


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
    validate.add_argument("--sink", choices=("memory", "jsonl", "typesense"), default=None)
    validate.add_argument("--generation", help="required physical Typesense generation when --sink typesense")
    validate.add_argument("--typesense-batch-size", type=int)
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
    crawl.add_argument("--sink", choices=("memory", "jsonl", "typesense"), default=None)
    crawl.add_argument("--generation", help="required physical Typesense generation when --sink typesense")
    crawl.add_argument("--typesense-batch-size", type=int)
    for command in (validate, crawl):
        command.add_argument("--timeout", type=float, default=30.0)
        command.add_argument("--request-delay", type=float, default=1.0)
        command.add_argument("--max-retries", type=int, default=3)
        command.add_argument("--page-size", type=int, default=1000)
    preflight = sub.add_parser("preflight", help="read one MSC aggregation count per source contract")
    preflight.add_argument("--from", dest="from_date", required=True, type=_day)
    preflight.add_argument("--to", dest="to_date", required=True, type=_day)
    preflight.add_argument("--output", type=Path)
    preflight.add_argument("--timeout", type=float, default=30.0)
    preflight.add_argument("--request-delay", type=float, default=1.0)
    preflight.add_argument("--max-retries", type=int, default=3)
    plan = sub.add_parser("capacity", help="estimate capacity from a manifest and bounded source fixtures")
    plan.add_argument("--plan", required=True, type=Path)
    plan.add_argument("--sample-dir", type=Path, default=None)
    plan.add_argument("--sample-limit", type=int, default=100)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--typesense-batch-size", type=int)
    backfill = sub.add_parser("backfill", help="run an explicit closed-range historical backfill")
    backfill.add_argument("--from", dest="from_date", required=True, type=_day)
    backfill.add_argument("--to", dest="to_date", required=True, type=_day)
    backfill.add_argument("--generation", required=True, help="physical generation only; aliases are never written")
    backfill.add_argument("--checkpoint", required=True, type=Path)
    backfill.add_argument("--sources", type=_sources, default=tuple(SOURCE_CONTRACTS))
    backfill.add_argument("--resume", action="store_true")
    backfill.add_argument("--force", action="store_true")
    backfill.add_argument("--plan-only", action="store_true")
    backfill.add_argument("--max-partitions", type=int)
    backfill.add_argument("--request-delay", type=float, default=1.0)
    backfill.add_argument("--timeout", type=float, default=30.0)
    backfill.add_argument("--max-retries", type=int, default=3)
    backfill.add_argument("--page-size", type=int, default=1000)
    backfill.add_argument("--typesense-batch-size", type=int, default=None)
    backfill.add_argument("--manifest", type=Path, default=None, help="explicit historical manifest path")
    backfill.add_argument("--report", type=Path, default=Path("backfill-report.json"))
    backfill.add_argument("--uuid-audit", type=Path, default=None)
    backfill.add_argument("--sample-dir", type=Path, default=None)
    backfill.add_argument("--acknowledge-readiness", action="store_true", help="required for any actual run")
    backfill.add_argument("--authorize-full-run", metavar="PHRASE", help="exact historical-write authorization phrase")
    incremental = sub.add_parser("incremental", help="sync a serving generation through closed MSC days")
    incremental.add_argument("--generation", required=True, help="serving physical generation; historical generation is rejected")
    incremental.add_argument("--checkpoint", required=True, type=Path)
    incremental.add_argument("--provenance", required=True, type=Path)
    incremental.add_argument("--from", dest="from_date", type=_day)
    incremental.add_argument("--to", dest="to_date", type=_day)
    incremental.add_argument("--latest-closed", action="store_true", help="use latest fully closed Vietnam day as --to")
    incremental.add_argument("--lookback", type=int, default=3, help="bounded recent closed-day revalidation window")
    incremental.add_argument("--resume", action="store_true", default=True)
    incremental.add_argument("--no-resume", dest="resume", action="store_false")
    incremental.add_argument("--force", action="store_true")
    incremental.add_argument("--max-partitions", type=int, required=True)
    incremental.add_argument("--request-delay", type=float, default=1.0)
    incremental.add_argument("--timeout", type=float, default=30.0)
    incremental.add_argument("--max-retries", type=int, default=3)
    incremental.add_argument("--page-size", type=int, default=1000)
    incremental.add_argument("--typesense-batch-size", type=int, default=None)
    incremental.add_argument("--report", type=Path, default=Path("incremental-serving-audit.json"))
    incremental.add_argument("--markdown", type=Path, default=None)
    incremental.add_argument("--base-manifest-fingerprint", required=True)
    prefix = sub.add_parser("prefix", help="extend serving data with one explicit source-floor prefix")
    prefix.add_argument("--generation", required=True, help="serving physical generation only")
    prefix.add_argument("--checkpoint", required=True, type=Path)
    prefix.add_argument("--provenance", required=True, type=Path)
    prefix.add_argument("--from", dest="from_date", required=True, type=_day)
    prefix.add_argument("--to", dest="to_date", required=True, type=_day)
    prefix.add_argument("--sources", required=True, type=_sources)
    prefix.add_argument("--resume", action="store_true", default=True)
    prefix.add_argument("--no-resume", dest="resume", action="store_false")
    prefix.add_argument("--force", action="store_true")
    prefix.add_argument("--max-partitions", type=int, required=True)
    prefix.add_argument("--request-delay", type=float, default=1.0)
    prefix.add_argument("--timeout", type=float, default=30.0)
    prefix.add_argument("--max-retries", type=int, default=3)
    prefix.add_argument("--page-size", type=int, default=1000)
    prefix.add_argument("--typesense-batch-size", type=int, default=None)
    prefix.add_argument("--manifest", type=Path, required=True)
    prefix.add_argument("--report", type=Path, required=True)
    prefix.add_argument("--markdown", type=Path, default=None)
    prefix.add_argument("--base-manifest-fingerprint", required=True)
    audit = sub.add_parser("backfill-audit", help="audit a completed physical generation without alias writes")
    audit.add_argument("--plan", required=True, type=Path)
    audit.add_argument("--checkpoint", required=True, type=Path)
    audit.add_argument("--uuid-audit", required=True, type=Path)
    audit.add_argument("--report", type=Path)
    audit.add_argument("--output", type=Path)
    benchmark = sub.add_parser("benchmark", help="run a bounded physical-generation search benchmark")
    benchmark.add_argument("--generation", required=True)
    benchmark.add_argument("--repeats", type=int, default=3)
    benchmark.add_argument("--output", type=Path)
    typesense = sub.add_parser("typesense", help="manage versioned Typesense collections and aliases")
    typesense_sub = typesense.add_subparsers(dest="typesense_operation", required=True)
    for operation in ("create-generation", "validate-generation", "activate-generation"):
        command = typesense_sub.add_parser(operation)
        command.add_argument("--generation", required=True)
    typesense_sub.add_parser("inspect", help="show known aliases and targets")
    rollback = typesense_sub.add_parser("rollback-alias", help="point one stable alias to a known generation")
    rollback.add_argument("--group", required=True, choices=tuple(("goods", "medicines", "traditional_medicine")))
    rollback.add_argument("--generation", required=True)
    return parser


def _msc_config(args: argparse.Namespace) -> MSCConfig:
    return MSCConfig(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        max_retries=args.max_retries,
        page_size=getattr(args, "page_size", 1000),
    )


def _run_preflight(args: argparse.Namespace) -> int:
    result = source_population_preflight(
        MSCClient(_msc_config(args)), args.from_date, args.to_date
    )
    _write_or_print(result, args.output)
    return 0


def _run_capacity(args: argparse.Namespace) -> int:
    manifest = json.loads(args.plan.read_text(encoding="utf-8"))
    verify_manifest(manifest)
    sample_dir = args.sample_dir or Path(__file__).resolve().parents[2] / "docs" / "msc-contracts"
    samples = load_fixture_samples(sample_dir, sample_limit=args.sample_limit, source_keys=manifest["sources"])
    estimate = estimate_capacity(
        manifest["source_totals"], samples,
        typesense_batch_size=args.typesense_batch_size or manifest["typesense_batch_size"],
    )
    _write_or_print(estimate, args.output)
    return 0


def _run_backfill(args: argparse.Namespace) -> int:
    if args.plan_only:
        if args.manifest is None:
            raise BackfillControlError("--plan-only requires an explicit --manifest path")
        config = _msc_config(args)
        preflight = source_population_preflight(MSCClient(config), args.from_date, args.to_date, args.sources)
        manifest = build_manifest(
            args.from_date, args.to_date, args.generation, preflight["source_totals"],
            page_size=args.page_size,
            typesense_batch_size=args.typesense_batch_size or 500,
            source_keys=args.sources,
        )
        atomic_write_json(args.manifest, manifest)
        with CheckpointStore(args.checkpoint) as checkpoints:
            result = {"manifest": manifest, "plan": plan_summary(manifest, checkpoints)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if not args.acknowledge_readiness:
        raise BackfillControlError("actual backfill requires --acknowledge-readiness; --plan-only is the safe default")
    require_full_run_authorization(args.authorize_full_run)
    if args.max_partitions is None:
        raise BackfillControlError("actual backfill requires explicit --max-partitions")
    if args.manifest is None:
        raise BackfillControlError("actual backfill requires an explicit --manifest path")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_manifest(manifest, generation=args.generation)
    expected_range = (manifest["source_range"]["from"], manifest["source_range"]["to"])
    if expected_range != (args.from_date, args.to_date) or tuple(manifest["sources"]) != tuple(ordered_source_keys(args.sources)):
        raise BackfillControlError("manifest range/source set does not match backfill arguments")
    config = _msc_config(args)
    if args.page_size != int(manifest["page_size"]):
        raise BackfillControlError("backfill --page-size must match the manifest")
    if config.max_safe_results != int(manifest["safe_msc_search_threshold"]):
        raise BackfillControlError("MSC safe search threshold does not match the manifest")
    typesense_config = TypesenseConfig.from_env()
    if args.typesense_batch_size is not None:
        if args.typesense_batch_size != int(manifest["typesense_batch_size"]):
            raise BackfillControlError("backfill --typesense-batch-size must match the manifest")
        typesense_config = replace(typesense_config, batch_size=args.typesense_batch_size)
    else:
        typesense_config = replace(typesense_config, batch_size=int(manifest["typesense_batch_size"]))
    typesense_client = TypesenseClient(typesense_config)
    sample_dir = args.sample_dir or Path(__file__).resolve().parents[2] / "docs" / "msc-contracts"
    estimate = estimate_capacity(
        manifest["source_totals"],
        load_fixture_samples(sample_dir, source_keys=manifest["sources"]),
        typesense_batch_size=manifest["typesense_batch_size"],
    )
    gate = capacity_preflight(estimate, typesense_client=typesense_client, local_path=args.checkpoint.parent)
    print(json.dumps({"capacity_preflight": gate}, ensure_ascii=False, sort_keys=True))
    if gate["decision"] == "FAIL":
        raise BackfillControlError("capacity preflight failed: available local disk is below estimated safety margin")
    uuid_path = args.uuid_audit or args.checkpoint.with_name(args.checkpoint.stem + ".uuid.sqlite3")
    with CheckpointStore(args.checkpoint) as checkpoints, UUIDProvenanceStore(uuid_path) as provenance:
        sink = AuditedSink(TypesenseSink(typesense_client, args.generation), provenance)
        engine = MSCIngestionEngine(MSCClient(config), checkpoints, sink, config)
        results = BackfillRunner(
            engine, checkpoints, manifest, report_path=args.report,
            resume=args.resume, force=args.force, max_partitions=args.max_partitions,
        ).run()
    print(json.dumps({"results": [result.as_dict() for result in results]}, ensure_ascii=False, sort_keys=True))
    return 0 if all(result.status == IngestionStatus.COMPLETED for result in results) else 1


def _run_incremental(args: argparse.Namespace) -> int:
    if args.latest_closed and args.to_date is not None:
        raise BackfillControlError("--latest-closed cannot be combined with --to")
    with CheckpointStore(args.checkpoint) as checkpoints:
        from_date = args.from_date or next_incremental_start(checkpoints, args.generation).isoformat()
    to_date = args.to_date or latest_closed_day().isoformat()
    config = _msc_config(args)
    ts_config = TypesenseConfig.from_env()
    if args.typesense_batch_size is not None:
        ts_config = replace(ts_config, batch_size=args.typesense_batch_size)
    report = run_incremental(
        generation=args.generation,
        from_date=from_date,
        to_date=to_date,
        checkpoint_path=args.checkpoint,
        provenance_path=args.provenance,
        report_path=args.report,
        base_manifest_fingerprint=args.base_manifest_fingerprint,
        lookback_days=args.lookback,
        force=args.force,
        resume=args.resume,
        max_partitions=args.max_partitions,
        msc_config=config,
        typesense_config=ts_config,
    )
    if args.markdown:
        args.markdown.write_text(render_serving_report_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 1


def _run_prefix(args: argparse.Namespace) -> int:
    config = _msc_config(args)
    ts_config = TypesenseConfig.from_env()
    if args.typesense_batch_size is not None:
        ts_config = replace(ts_config, batch_size=args.typesense_batch_size)
    report = run_prefix_extension(
        generation=args.generation,
        from_date=args.from_date,
        to_date=args.to_date,
        source_keys=args.sources,
        checkpoint_path=args.checkpoint,
        provenance_path=args.provenance,
        report_path=args.report,
        manifest_path=args.manifest,
        base_manifest_fingerprint=args.base_manifest_fingerprint,
        force=args.force,
        resume=args.resume,
        max_partitions=args.max_partitions,
        msc_config=config,
        typesense_config=ts_config,
    )
    if args.markdown:
        args.markdown.write_text(render_serving_report_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 1


def _run_audit(args: argparse.Namespace) -> int:
    manifest = json.loads(args.plan.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report else None
    with CheckpointStore(args.checkpoint) as checkpoints, UUIDProvenanceStore(args.uuid_audit) as provenance:
        client = TypesenseClient(TypesenseConfig.from_env())
        result = historical_backfill_audit(manifest, checkpoints, provenance, typesense_client=client, report=report)
    _write_or_print(result, args.output)
    return 0 if result["overall_status"] == "PASS" else 1


def _run_benchmark(args: argparse.Namespace) -> int:
    result = run_search_benchmark(TypesenseClient(TypesenseConfig.from_env()), args.generation, repeats=args.repeats)
    _write_or_print(result, args.output)
    return 0 if not result["errors"] else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.operation == "preflight":
            return _run_preflight(args)
        if args.operation == "capacity":
            return _run_capacity(args)
        if args.operation == "backfill":
            return _run_backfill(args)
        if args.operation == "incremental":
            return _run_incremental(args)
        if args.operation == "prefix":
            return _run_prefix(args)
        if args.operation == "backfill-audit":
            return _run_audit(args)
        if args.operation == "benchmark":
            return _run_benchmark(args)
        if args.operation == "typesense":
            manager = TypesenseCollectionManager(TypesenseClient(TypesenseConfig.from_env()))
            if args.typesense_operation == "create-generation":
                result = manager.create_generation(args.generation)
            elif args.typesense_operation == "validate-generation":
                result = manager.validate_generation(args.generation)
            elif args.typesense_operation == "activate-generation":
                result = manager.activate_generation(args.generation)
            elif args.typesense_operation == "rollback-alias":
                result = manager.rollback_alias(args.group, args.generation)
            else:
                result = manager.inspect()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        config = MSCConfig(
            timeout_seconds=args.timeout, request_delay_seconds=args.request_delay,
            max_retries=args.max_retries, page_size=args.page_size,
        )
        checkpoint_path = args.checkpoint if getattr(args, "checkpoint", None) else ":memory:"
        sink_name = args.sink
        if sink_name == "typesense":
            if not args.generation:
                raise ValueError("--generation is required when --sink typesense")
            typesense_config = TypesenseConfig.from_env()
            if args.typesense_batch_size is not None:
                typesense_config = replace(typesense_config, batch_size=args.typesense_batch_size)
            sink = TypesenseSink(TypesenseClient(typesense_config), args.generation)
        elif sink_name == "jsonl" or (sink_name is None and getattr(args, "output_dir", None) and not getattr(args, "dry_run", False)):
            sink = JsonlValidationSink(args.output_dir)
        else:
            sink = InMemorySink()
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
    except KeyboardInterrupt:
        print("msc_cli_interrupted", file=sys.stderr)
        return 130
    except (EngineError, TypesenseError, BackfillControlError, ValueError, OSError) as exc:
        print(f"msc_cli_error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
