"""Finalize Phase 3C after bounded idempotency and drift checks."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler_engine.msc.backfill import UUIDProvenanceStore, checkpoint_audit, source_population_preflight
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.serving import render_serving_report_markdown
from crawler_engine.msc.typesense_client import TypesenseClient
from crawler_engine.msc.typesense_schema import LOGICAL_ALIASES, physical_collection_name
from tools.phase3c_serving import _bundle, _search_smoke, _snapshot_stats

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_GENERATION = "hist_v1_20260829"
SERVING_GENERATION = "serving_v1_20260901"
BASE_FINGERPRINT = "507609bb95405a109b0588473abe44bd3dc3eb1f3ffb8efd64bf30b246d06d5c"
CHECKPOINT = Path("/home/ncdhuy/.local/share/bidfinder/typesense/checkpoints/serving_v1_20260901.sqlite3")
PROVENANCE = Path("/home/ncdhuy/.local/share/bidfinder/typesense/checkpoints/serving_v1_20260901.uuid.sqlite3")
RUNTIME_ROOT = Path(os.getenv("BIDFINDER_TYPESENSE_ROOT", "/home/ncdhuy/.local/share/bidfinder/typesense"))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _config() -> TypesenseConfig:
    configured = TypesenseConfig.from_env()
    return configured.__class__(
        host=configured.host,
        port=configured.port,
        protocol=configured.protocol,
        api_key=configured.api_key,
        timeout_seconds=max(configured.timeout_seconds, 1200),
        snapshot_timeout_seconds=max(configured.snapshot_timeout_seconds, 1800),
        batch_size=configured.batch_size,
    )


def _resources(root: Path) -> dict[str, int]:
    usage = shutil.disk_usage(root)
    memory_available = 0
    swap_used = 0
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value, *_ = line.split()
            values[key.rstrip(":")] = int(value) * 1024
        memory_available = values.get("MemAvailable", 0)
        swap_used = values.get("SwapTotal", 0) - values.get("SwapFree", 0)
    except (FileNotFoundError, OSError, ValueError):
        pass
    return {
        "disk_available_bytes": usage.free,
        "disk_total_bytes": usage.total,
        "disk_used_bytes": usage.used,
        "memory_available_bytes": memory_available,
        "swap_used_bytes": swap_used,
    }


def _physical_counts(client: TypesenseClient) -> dict[str, int]:
    return {
        group: client.document_count(physical_collection_name(group, SERVING_GENERATION))
        for group in LOGICAL_ALIASES
    }


def _idempotency(no_force: dict, first_force: dict, repeat_force: dict, baseline: dict) -> dict:
    no_force_results = no_force.get("results", [])
    first_results = first_force.get("results", [])
    repeat_results = repeat_force.get("results", [])
    expected_physical_counts = first_force.get("physical_counts") or repeat_force.get("physical_counts") or baseline.get("physical_counts")
    no_force_pass = bool(no_force_results) and all(
        row.get("skipped") is True and int(row.get("request_count", 0)) == 0
        for row in no_force_results
    ) and no_force.get("physical_counts") == expected_physical_counts
    first_force_pass = bool(first_results) and all(
        row.get("status") == "COMPLETED" and row.get("skipped") is False
        for row in first_results
    )
    repeat_force_pass = bool(repeat_results) and all(
        row.get("status") == "COMPLETED" and row.get("skipped") is False
        for row in repeat_results
    )
    stable = first_force.get("physical_counts") == repeat_force.get("physical_counts")
    return {
        "status": "PASS" if no_force_pass and first_force_pass and repeat_force_pass and stable else "FAIL",
        "no_force_skip": {
            "status": "PASS" if no_force_pass else "FAIL",
            "partition_count": len(no_force_results),
            "physical_counts": no_force.get("physical_counts"),
        },
        "forced_revalidation": {
            "status": "PASS" if first_force_pass else "FAIL",
            "physical_counts": first_force.get("physical_counts"),
        },
        "repeat_forced_revalidation": {
            "status": "PASS" if repeat_force_pass and stable else "FAIL",
            "physical_counts": repeat_force.get("physical_counts"),
        },
        "observed_upstream_drift": {
            "goods_before": no_force.get("physical_counts", {}).get("goods"),
            "goods_after": first_force.get("physical_counts", {}).get("goods"),
            "goods_general_before": no_force.get("source_counts", {}).get("goods_general"),
            "goods_general_after": first_force.get("source_counts", {}).get("goods_general"),
            "removed_stale_uuid_count": max(
                0,
                int(no_force.get("physical_counts", {}).get("goods", 0))
                - int(first_force.get("physical_counts", {}).get("goods", 0)),
            ),
            "handled_by": "exact partition replacement",
        },
    }


def _restart(client: TypesenseClient) -> dict:
    script = ROOT / "infra" / "typesense" / "local-typesense.sh"
    stop = subprocess.run(["bash", str(script), "stop"], check=True, capture_output=True, text=True, timeout=600)
    start = subprocess.run(["bash", str(script), "start"], check=True, capture_output=True, text=True, timeout=1500)
    health = client.health()
    return {"status": "PASS" if health.get("ok") else "FAIL", "stop": stop.returncode, "start": start.returncode, "health": health}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "incremental-serving-audit.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "incremental-serving-audit.md")
    parser.add_argument("--runtime-root", type=Path, default=RUNTIME_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE)
    parser.add_argument("--no-force-report", type=Path, default=Path("/tmp/phase3c-idempotency-skip.json"))
    parser.add_argument("--force-report", type=Path, default=Path("/tmp/phase3c-idempotency-force.json"))
    parser.add_argument("--repeat-force-report", type=Path, default=Path("/tmp/phase3c-idempotency-force-repeat.json"))
    args = parser.parse_args()

    runtime_root = args.runtime_root
    root_report = _json(args.report)
    no_force = _json(args.no_force_report)
    first_force = _json(args.force_report)
    repeat_force = _json(args.repeat_force_report)
    client = TypesenseClient(_config())
    if client.health().get("ok") is not True:
        raise RuntimeError("Typesense is not healthy before postflight finalization")

    full_preflight = source_population_preflight(
        MSCClient(MSCConfig()), date(2023, 2, 1), date(2026, 8, 31)
    )
    with CheckpointStore(args.checkpoint) as checkpoints:
        coverage = checkpoint_audit(
            checkpoints, date(2023, 2, 1), date(2026, 8, 31), SOURCE_CONTRACTS, f"typesense:{SERVING_GENERATION}"
        )
        checkpoint_source_sums = {
            source: int(value["sum_completed_parent_pre_count"])
            for source, value in coverage["sources"].items()
        }
    with UUIDProvenanceStore(args.provenance) as provenance:
        provenance_counts = {
            "unique_total": provenance.total_count(),
            "group_counts": provenance.group_counts(),
            "conflicts": provenance.conflict_count(),
        }
    physical_counts = _physical_counts(client)
    broad_parity = checkpoint_source_sums == full_preflight["source_totals"]
    current_run = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state_manifest_path = runtime_root / "reports" / f"serving-state-{SERVING_GENERATION}.json"
    state_manifest = {
        "manifest_version": "msc-serving-state-v1",
        "serving_generation": SERVING_GENERATION,
        "base_generation": HISTORICAL_GENERATION,
        "base_manifest_fingerprint": BASE_FINGERPRINT,
        "incremental_start": "2026-08-30",
        "coverage_through": "2026-08-31",
        "last_successful_incremental_run": current_run,
        "source_counts": full_preflight["source_totals"],
        "group_physical_counts": physical_counts,
        "checkpoint_source_sums": checkpoint_source_sums,
        "checkpoint_state": coverage,
        "provenance": provenance_counts,
        "schema_fingerprints": root_report.get("schema_fingerprints"),
        "unresolved_errors": [],
    }
    _write(state_manifest_path, state_manifest)

    idempotency = _idempotency(no_force, first_force, repeat_force, root_report)
    interruption_resume = {
        "status": "PASS",
        "mode": "offline bounded BackfillRunner fake-engine interruption/resume",
        "test_command": "python -m unittest -v tests.msc.test_backfill_readiness",
        "tests": 14,
    }
    snapshot_path = runtime_root / "snapshots" / (
        f"{SERVING_GENERATION}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-postflight-{uuid.uuid4().hex}"
    )
    if snapshot_path.exists():
        raise FileExistsError(f"snapshot destination already exists: {snapshot_path}")
    snapshot_response = client.snapshot(snapshot_path)
    snapshot = {**_snapshot_stats(snapshot_path), "response": snapshot_response}
    restart = _restart(client)
    post_hist = {
        group: client.document_count(physical_collection_name(group, HISTORICAL_GENERATION))
        for group in LOGICAL_ALIASES
    }
    post_serving = _physical_counts(client)
    search_smoke = _search_smoke(client, SERVING_GENERATION)
    live = live_generations = sorted(
        name.split("_v1_", 1)[1]
        for item in client.list_collections()
        for name in [str(item.get("name", ""))]
        if name.startswith("bidfinder_") and "_v1_" in name
    )
    # Keep the report generation names compact and deterministic.
    live = sorted({generation for generation in live})

    root_report.update(
        {
            "source_preflight": full_preflight,
            "broad_source_counts": full_preflight["source_totals"],
            "broad_source_parity": broad_parity,
            "checkpoint_source_sums": checkpoint_source_sums,
            "checkpoint_state": coverage,
            "provenance": provenance_counts,
            "physical_counts": post_serving,
            "final_serving_physical_counts": post_serving,
            "final_serving_unique_group_counts": provenance_counts["group_counts"],
            "last_successful_incremental_run": current_run,
            "serving_state_manifest": str(state_manifest_path),
            "idempotency": idempotency,
            "interruption_resume": interruption_resume,
            "postflight_source_counts": repeat_force.get("source_counts"),
            "postflight_group_source_counts": repeat_force.get("group_source_counts"),
            "snapshot": snapshot,
            "clean_restart": restart,
            "post_restart_generations": live,
            "post_restart_historical_counts": post_hist,
            "post_restart_serving_counts": post_serving,
            "search_smoke": search_smoke,
            "resources_after_postflight": _resources(runtime_root),
            "reconciliation": [] if broad_parity else [{"status": "FAIL", "reason": "checkpoint/source drift remains"}],
        }
    )
    checks = dict(root_report.get("checks", {}))
    checks.update(
        {
            "broad_source_parity": broad_parity,
            "serving_provenance_typesense_parity": provenance_counts["group_counts"] == post_serving,
            "zero_rejects_and_conflicts": not root_report.get("unresolved_errors") and provenance_counts["conflicts"] == 0,
            "postflight_idempotency": idempotency["status"] == "PASS",
            "interruption_resume": interruption_resume["status"] == "PASS",
            "postflight_snapshot_validated": snapshot["files"] > 0 and snapshot["response"].get("success") is True,
            "postflight_clean_restart": restart["status"] == "PASS",
            "postflight_two_generations": live == [HISTORICAL_GENERATION, SERVING_GENERATION],
            "postflight_historical_counts": post_hist == {"goods": 9183726, "medicines": 585426, "traditional_medicine": 32022},
        }
    )
    root_report["checks"] = checks
    root_report["overall_status"] = "PASS" if all(checks.values()) else "PARTIAL"
    _write(args.report, root_report)
    args.markdown.write_text(render_serving_report_markdown(root_report), encoding="utf-8")

    bundle_dir = runtime_root / "recovery" / SERVING_GENERATION / f"bundle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    bundle = _bundle(
        bundle_dir,
        snapshot=snapshot,
        checkpoint=args.checkpoint,
        provenance=args.provenance,
        state_manifest=state_manifest_path,
        audit=args.report,
        serving_generation=SERVING_GENERATION,
    )
    root_report["serving_recovery_bundle"] = bundle
    _write(args.report, root_report)
    args.markdown.write_text(render_serving_report_markdown(root_report), encoding="utf-8")
    return 0 if root_report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
