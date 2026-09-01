"""Execute Phase 3C local serving bootstrap, catch-up, snapshot, and restart."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from typing import Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler_engine.msc.backfill import (
    UUIDProvenanceStore,
    checkpoint_audit,
    historical_backfill_audit,
    reconcile_completed_prefix,
    source_population_preflight,
)
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.engine import operational_today
from crawler_engine.msc.serving import (
    EXPECTED_HISTORICAL_GROUP_COUNTS,
    HISTORICAL_END,
    HISTORICAL_GENERATION,
    bootstrap_checkpoint,
    bootstrap_provenance,
    build_serving_report,
    clone_generation,
    incremental_window,
    latest_closed_day,
    live_generations,
    render_serving_report_markdown,
    safe_retire_generation,
)
from crawler_engine.msc.typesense_client import TypesenseClient
from crawler_engine.msc.typesense_schema import LOGICAL_ALIASES, physical_collection_name

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ROOT = Path(os.getenv("BIDFINDER_TYPESENSE_ROOT", "/home/ncdhuy/.local/share/bidfinder/typesense"))


class CapacityBlocked(RuntimeError):
    pass


def _json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _integrity(path: str | Path) -> str:
    connection = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def _samples(client: TypesenseClient, provenance_path: str | Path, generation: str) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {group: {} for group in LOGICAL_ALIASES}
    connection = sqlite3.connect(f"file:{Path(provenance_path)}?mode=ro", uri=True)
    try:
        for group in LOGICAL_ALIASES:
            rows = connection.execute(
                "SELECT uuid FROM uuid_provenance WHERE data_group=? ORDER BY uuid LIMIT 2", (group,)
            ).fetchall()
            for row in rows:
                record_id = str(row[0])
                document = client.get_document(physical_collection_name(group, generation), record_id)
                if document is not None:
                    result[group][record_id] = document
    finally:
        connection.close()
    return result


def _resources(path: str | Path) -> dict[str, int | None]:
    usage = shutil.disk_usage(path)
    result: dict[str, int | None] = {
        "disk_total_bytes": usage.total,
        "disk_used_bytes": usage.total - usage.free,
        "disk_available_bytes": usage.free,
        "memory_available_bytes": None,
        "swap_used_bytes": None,
    }
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"MemAvailable", "SwapFree", "SwapTotal"}:
                values[key] = int(value.strip().split()[0]) * 1024
        result["memory_available_bytes"] = values.get("MemAvailable")
        if "SwapTotal" in values and "SwapFree" in values:
            result["swap_used_bytes"] = values["SwapTotal"] - values["SwapFree"]
    return result


def _snapshot_stats(path: Path) -> dict[str, int | str]:
    if not path.is_dir():
        raise RuntimeError(f"Typesense snapshot directory missing: {path}")
    files = 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            total += item.stat().st_size
    if not files:
        raise RuntimeError(f"Typesense snapshot directory is empty: {path}")
    return {"path": str(path), "files": files, "bytes": total}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _search_smoke(client: TypesenseClient, generation: str) -> dict:
    cases = (
        ("goods search", "goods", "*", {}, {}),
        ("medicines search", "medicines", "amlodipin", {}, {}),
        ("traditional search", "traditional_medicine", "*", {}, {}),
        ("filter", "goods", "*", {"filter_by": "source_tab:HANG_HOA"}, {}),
        ("sort", "goods", "*", {"sort_by": "winning_unit_price:desc"}, {}),
    )
    rows = []
    for category, group, query, options, _ in cases:
        started = time.perf_counter()
        response = client.search_group(
            group, query, per_page=1, collection=physical_collection_name(group, generation), **options
        )
        rows.append({
            "category": category,
            "parameters": {"group": group, "q": query, **options},
            "result_count": response.get("found"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        })
    started = time.perf_counter()
    multi = client.multi_search_all("*", per_page=1, generation_id=generation)
    multi_latency = round((time.perf_counter() - started) * 1000, 3)
    multi_results = multi.get("results", [])
    rows.append({
        "category": "multi-search",
        "parameters": {"q": "*", "generation": generation},
        "result_count": [item.get("found") for item in multi_results],
        "latency_ms": multi_latency,
    })
    return {"cases": rows, "outliers_over_500ms": [row for row in rows if row["latency_ms"] > 500]}


def _bundle(
    directory: Path,
    *,
    snapshot: Mapping[str, object],
    checkpoint: Path,
    provenance: Path,
    state_manifest: Path,
    audit: Path,
    serving_generation: str,
) -> dict:
    if directory.exists():
        raise FileExistsError(f"recovery bundle destination already exists: {directory}")
    directory.mkdir(parents=True)
    files = {}
    for name, source in (
        ("checkpoint.sqlite3", checkpoint),
        ("uuid-provenance.sqlite3", provenance),
        ("serving-state-manifest.json", state_manifest),
        ("incremental-serving-audit.json", audit),
    ):
        target = directory / name
        shutil.copy2(source, target)
        files[name] = {"bytes": target.stat().st_size, "sha256": _sha256(target)}
    bundle = {
        "bundle_version": "msc-phase3c-serving-v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "serving_generation": serving_generation,
        "base_generation": HISTORICAL_GENERATION,
        "typesense_snapshot": dict(snapshot),
        "files": files,
        "sqlite_integrity": {"checkpoint": _integrity(directory / "checkpoint.sqlite3"), "provenance": _integrity(directory / "uuid-provenance.sqlite3")},
        "status": "VALIDATED",
    }
    (directory / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation")
    parser.add_argument("--historical-manifest", type=Path, default=DEFAULT_RUNTIME_ROOT / "reports" / "historical-manifest-hist_v1_20260829.final.json")
    parser.add_argument("--historical-checkpoint", type=Path, default=DEFAULT_RUNTIME_ROOT / "checkpoints" / "hist_v1_20260829.sqlite3")
    parser.add_argument("--historical-provenance", type=Path, default=DEFAULT_RUNTIME_ROOT / "checkpoints" / "hist_v1_20260829.uuid.sqlite3")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--report", type=Path, default=ROOT / "incremental-serving-audit.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "incremental-serving-audit.md")
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--lookback", type=int, default=0)
    parser.add_argument("--catchup-to", type=str)
    parser.add_argument("--skip-restart", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    audit_source = _json(ROOT / "historical-backfill-audit.json")
    if audit_source.get("final_status") != "PASS" or audit_source.get("generation") != HISTORICAL_GENERATION:
        raise RuntimeError("Phase 3B historical audit is not a final PASS for the expected generation")
    base_fingerprint = str(audit_source["manifest_lineage"]["final_observed"]["fingerprint"])
    serving_generation = args.generation or f"serving_v1_{operational_today().strftime('%Y%m%d')}"
    ts_config = TypesenseConfig.from_env()
    # Server-side clone can block while a full collection is copied.
    ts_config = ts_config.__class__(
        host=ts_config.host,
        port=ts_config.port,
        protocol=ts_config.protocol,
        api_key=ts_config.api_key,
        timeout_seconds=max(ts_config.timeout_seconds, 1800.0),
        snapshot_timeout_seconds=ts_config.snapshot_timeout_seconds,
        batch_size=ts_config.batch_size,
    )
    client = TypesenseClient(ts_config)
    health = client.health()
    if health.get("ok") is not True:
        raise RuntimeError(f"Typesense health failed: {health}")
    manifest = _json(args.historical_manifest)
    if manifest.get("generation") != HISTORICAL_GENERATION:
        raise RuntimeError("historical manifest generation mismatch")
    with CheckpointStore(args.historical_checkpoint) as checkpoints, UUIDProvenanceStore(args.historical_provenance) as provenance:
        historical_audit = historical_backfill_audit(manifest, checkpoints, provenance, typesense_client=client)
        if historical_audit["overall_status"] != "PASS":
            raise RuntimeError("historical generation validation failed")
        historical_samples = _samples(client, args.historical_provenance, HISTORICAL_GENERATION)
        historical_state = {
            "checkpoint_integrity": _integrity(args.historical_checkpoint),
            "provenance_integrity": _integrity(args.historical_provenance),
            "checkpoint_status": checkpoints.status_counts(f"typesense:{HISTORICAL_GENERATION}"),
            "provenance_total": provenance.total_count(),
            "provenance_groups": provenance.group_counts(),
            "conflicts": provenance.conflict_count(),
            "audit": historical_audit,
        }
    hist_counts = {
        group: client.document_count(physical_collection_name(group, HISTORICAL_GENERATION))
        for group in LOGICAL_ALIASES
    }
    if hist_counts != EXPECTED_HISTORICAL_GROUP_COUNTS:
        raise RuntimeError(f"historical physical counts failed: {hist_counts}")
    canary_report = _json(ROOT / "local-typesense-canary-report.json")
    recovery = audit_source.get("final_recovery_bundle", {})
    if recovery.get("status") != "VALIDATED" or canary_report.get("aliases_before") != {
        "bidfinder_goods": None, "bidfinder_medicines": None, "bidfinder_traditional": None
    }:
        raise RuntimeError("canary or Phase 3B recovery evidence is not safe for retirement")
    if set(live_generations(client)) != {HISTORICAL_GENERATION, "local_canary_20260831_29ef44"}:
        raise RuntimeError(f"unexpected live generations before retirement: {live_generations(client)}")
    aliases_before = {
        alias: client.get_alias(alias)
        for alias in LOGICAL_ALIASES.values()
    }
    if any(value is not None for value in aliases_before.values()):
        raise RuntimeError(f"stable aliases must be inactive before Phase 3C: {aliases_before}")
    retirement = safe_retire_generation(client, "local_canary_20260831_29ef44")
    if live_generations(client) != (HISTORICAL_GENERATION,):
        raise RuntimeError(f"canary retirement left unexpected generations: {live_generations(client)}")
    resources_before = _resources(args.runtime_root / "data")
    if resources_before["memory_available_bytes"] is not None and resources_before["memory_available_bytes"] < 4 * 1024**3:
        raise CapacityBlocked("less than 4 GiB memory available before full serving clone")
    clone = clone_generation(
        client,
        HISTORICAL_GENERATION,
        serving_generation,
        provenance_path=args.historical_provenance,
        base_manifest_fingerprint=base_fingerprint,
    )
    resources_after_clone = _resources(args.runtime_root / "data")
    if resources_after_clone["memory_available_bytes"] is not None and resources_after_clone["memory_available_bytes"] < 4 * 1024**3:
        raise CapacityBlocked("less than 4 GiB memory available after full serving clone")
    if set(live_generations(client)) != {HISTORICAL_GENERATION, serving_generation}:
        raise RuntimeError(f"serving clone created unexpected generations: {live_generations(client)}")
    serving_checkpoint = args.runtime_root / "checkpoints" / f"{serving_generation}.sqlite3"
    serving_provenance = args.runtime_root / "checkpoints" / f"{serving_generation}.uuid.sqlite3"
    checkpoint_bootstrap = bootstrap_checkpoint(
        args.historical_checkpoint, serving_checkpoint, serving_generation=serving_generation
    )
    provenance_bootstrap = bootstrap_provenance(
        args.historical_provenance, serving_provenance, serving_generation=serving_generation
    )
    clone_parity = clone
    if not all(item["parity"] for item in clone_parity["groups"].values()):
        raise RuntimeError("historical to serving clone parity failed")
    catchup_to = date.fromisoformat(args.catchup_to) if args.catchup_to else latest_closed_day()
    if catchup_to < date(2026, 8, 30):
        raise RuntimeError(f"no closed day available after historical freeze: {catchup_to}")
    msc_config = MSCConfig(
        page_size=args.page_size,
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        max_retries=args.max_retries,
    )
    # First Phase 3C catch-up is intentionally frozen at the first new day.
    incremental = __import__("crawler_engine.msc.serving", fromlist=["run_incremental"]).run_incremental(
        generation=serving_generation,
        from_date="2026-08-30",
        to_date=catchup_to,
        checkpoint_path=serving_checkpoint,
        provenance_path=serving_provenance,
        report_path=args.report,
        base_manifest_fingerprint=base_fingerprint,
        lookback_days=args.lookback,
        max_partitions=((catchup_to - date(2026, 8, 30)).days + 1) * len(SOURCE_CONTRACTS),
        msc_config=msc_config,
        typesense_config=ts_config,
    )
    full_preflight = source_population_preflight(
        MSCClient(msc_config), date(2023, 2, 1), catchup_to
    )
    with CheckpointStore(serving_checkpoint) as serving_store, UUIDProvenanceStore(serving_provenance) as serving_provenance_store:
        full_coverage = checkpoint_audit(
            serving_store, date(2023, 2, 1), catchup_to, SOURCE_CONTRACTS, f"typesense:{serving_generation}"
        )
        checkpoint_source_sums = {
            source: int(value["sum_completed_parent_pre_count"])
            for source, value in full_coverage["sources"].items()
        }
        reconciliation = []
        if checkpoint_source_sums != full_preflight["source_totals"]:
            for source in SOURCE_CONTRACTS:
                reconciliation.append(reconcile_completed_prefix(
                    MSCClient(msc_config), serving_store, source,
                    date(2023, 2, 1), catchup_to, f"typesense:{serving_generation}"
                ))
        provenance_counts = {
            "unique_total": serving_provenance_store.total_count(),
            "group_counts": serving_provenance_store.group_counts(),
            "conflicts": serving_provenance_store.conflict_count(),
        }
    serving_counts = {
        group: client.document_count(physical_collection_name(group, serving_generation))
        for group in LOGICAL_ALIASES
    }
    search_smoke = _search_smoke(client, serving_generation)
    serving_state_manifest = args.runtime_root / "reports" / f"serving-state-{serving_generation}.json"
    serving_state_manifest.parent.mkdir(parents=True, exist_ok=True)
    state_manifest = {
        "manifest_version": "msc-serving-state-v1",
        "serving_generation": serving_generation,
        "base_generation": HISTORICAL_GENERATION,
        "base_manifest_fingerprint": base_fingerprint,
        "incremental_start": "2026-08-30",
        "coverage_through": catchup_to.isoformat(),
        "last_successful_incremental_run": incremental.get("last_successful_incremental_run"),
        "source_counts": full_preflight["source_totals"],
        "group_physical_counts": serving_counts,
        "checkpoint_source_sums": checkpoint_source_sums,
        "checkpoint_state": full_coverage,
        "provenance": provenance_counts,
        "schema_fingerprints": incremental.get("schema_fingerprints"),
        "unresolved_errors": incremental.get("unresolved_errors", []),
    }
    serving_state_manifest.write_text(json.dumps(state_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    snapshot_path = args.runtime_root / "snapshots" / f"{serving_generation}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    if snapshot_path.exists():
        raise FileExistsError(f"snapshot destination already exists: {snapshot_path}")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_result = client.snapshot(snapshot_path)
    snapshot = {**_snapshot_stats(snapshot_path), "response": snapshot_result}
    clean_restart = {"skipped": True}
    if not args.skip_restart:
        script = ROOT / "infra" / "typesense" / "local-typesense.sh"
        stop = subprocess.run(["bash", str(script), "stop"], text=True, capture_output=True, check=True, timeout=600)
        start = subprocess.run(["bash", str(script), "start"], text=True, capture_output=True, check=True, timeout=1800)
        clean_restart = {"status": "PASS", "stop": stop.stdout.strip(), "start": start.stdout.strip(), "health": client.health()}
    if client.health().get("ok") is not True:
        raise RuntimeError("Typesense health failed after clean restart")
    post_hist_counts = {
        group: client.document_count(physical_collection_name(group, HISTORICAL_GENERATION))
        for group in LOGICAL_ALIASES
    }
    post_serving_counts = {
        group: client.document_count(physical_collection_name(group, serving_generation))
        for group in LOGICAL_ALIASES
    }
    post_samples = _samples(client, args.historical_provenance, HISTORICAL_GENERATION)
    historical_immutable = post_hist_counts == EXPECTED_HISTORICAL_GROUP_COUNTS and post_samples == historical_samples
    checks = {
        "historical_unchanged": historical_immutable,
        "canary_retired": live_generations(client) == (HISTORICAL_GENERATION, serving_generation),
        "one_serving_generation": live_generations(client).count(serving_generation) == 1,
        "clone_count_and_sample_parity": all(item["parity"] for item in clone_parity["groups"].values()),
        "checkpoint_bootstrap": checkpoint_bootstrap["rows_remapped"] == 9142,
        "provenance_bootstrap": provenance_bootstrap["total"] == 9_801_174 and provenance_bootstrap["conflicts"] == 0,
        "catchup_starts_after_freeze": incremental["incremental_start"] == "2026-08-30",
        "all_seven_sources": len(SOURCE_CONTRACTS) == 7,
        "broad_source_parity": checkpoint_source_sums == full_preflight["source_totals"] and not reconciliation,
        "serving_provenance_typesense_parity": serving_counts == provenance_counts["group_counts"],
        "zero_rejects_and_conflicts": not incremental.get("unresolved_errors") and provenance_counts["conflicts"] == 0,
        "snapshot_validated": snapshot["files"] > 0,
        "clean_restart": not args.skip_restart and clean_restart.get("status") == "PASS",
        "two_generations": live_generations(client) == (HISTORICAL_GENERATION, serving_generation),
        "aliases_inactive": all(client.get_alias(alias) is None for alias in LOGICAL_ALIASES.values()),
    }
    final_report = dict(incremental)
    final_report.update({
        "overall_status": "PASS" if all(checks.values()) else "PARTIAL",
        "historical_base_validation": historical_state,
        "canary_retirement": retirement,
        "serving_generation": serving_generation,
        "clone": clone,
        "clone_parity": clone_parity,
        "operational_state_bootstrap": {"checkpoint": checkpoint_bootstrap, "provenance": provenance_bootstrap},
        "execution_time_latest_closed_day": catchup_to.isoformat(),
        "broad_source_counts": full_preflight["source_totals"],
        "checkpoint_source_sums": checkpoint_source_sums,
        "broad_source_parity": checkpoint_source_sums == full_preflight["source_totals"] and not reconciliation,
        "reconciliation": reconciliation,
        "final_serving_unique_group_counts": provenance_counts["group_counts"],
        "final_serving_physical_counts": serving_counts,
        "unresolved_rejected_docs": incremental.get("unresolved_errors", []),
        "uuid_conflicts": provenance_counts["conflicts"],
        "search_smoke": search_smoke,
        "snapshot": snapshot,
        "clean_restart": clean_restart,
        "post_restart_generations": live_generations(client),
        "post_restart_historical_counts": post_hist_counts,
        "post_restart_serving_counts": post_serving_counts,
        "historical_immutability": historical_immutable,
        "resources_before_clone": resources_before,
        "resources_after_clone": resources_after_clone,
        "serving_state_manifest": str(serving_state_manifest),
        "checks": checks,
    })
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(final_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_serving_report_markdown(final_report), encoding="utf-8")
    bundle = _bundle(
        args.runtime_root / "recovery" / serving_generation / f"bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        snapshot=snapshot,
        checkpoint=Path(serving_checkpoint),
        provenance=Path(serving_provenance),
        state_manifest=serving_state_manifest,
        audit=args.report,
        serving_generation=serving_generation,
    )
    final_report["serving_recovery_bundle"] = bundle
    args.report.write_text(json.dumps(final_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_serving_report_markdown(final_report), encoding="utf-8")
    return 0 if final_report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
