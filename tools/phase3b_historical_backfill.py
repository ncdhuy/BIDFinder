"""Run the authorized Phase 3B historical backfill and its data-plane gates.

This is an operational coordinator only. Retrieval, adaptive partitioning,
normalization, checkpointing, and Typesense writes remain owned by the
existing MSC ingestion engine and :class:`BackfillRunner`.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler_engine.msc.backfill import (
    BackfillControlError,
    BackfillRunner,
    AuditedSink,
    UUIDProvenanceStore,
    atomic_write_json,
    checkpoint_audit,
    fingerprint,
    historical_backfill_audit,
    reconcile_completed_prefix,
    require_full_run_authorization,
    source_population_preflight,
    verify_manifest,
)
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import get_contract
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus
from crawler_engine.msc.normalize import normalize_records
from crawler_engine.msc.partitioning import official_day_interval
from crawler_engine.msc.sink import TypesenseSink
from crawler_engine.msc.typesense_client import TypesenseClient, TypesenseError
from crawler_engine.msc.typesense_schema import (
    LOGICAL_ALIASES,
    canonical_to_typesense_document,
    physical_collection_name,
)
from crawler_engine.msc.validation import validate_raw_records


HISTORICAL_START = "2023-02-01"
HISTORICAL_END = "2026-08-29"
HISTORICAL_GENERATION = "hist_v1_20260829"
AUTHORITATIVE_SOURCE_TOTALS = {
    "goods_general": 8_219_247,
    "medical_devices": 964_685,
    "medicine_generic": 494_698,
    "medicine_originator": 55_239,
    "medicine_herbal": 35_489,
    "herbal_material": 9_554,
    "traditional_medicine": 22_468,
}
RECOVERY_MILESTONE_DOCUMENTS = 1_000_000
CRITICAL_MEM_AVAILABLE_BYTES = 2 * 1024**3
CRITICAL_FREE_FRACTION = 0.20
WARNING_FREE_FRACTION = 0.35


@contextmanager
def graceful_interrupts():
    """Turn operator stop signals into the runner's durable interruption path."""

    def stop(signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt(f"INTERRUPTED by signal {signum}")

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _default_root() -> Path:
    return Path(os.environ.get("BIDFINDER_TYPESENSE_ROOT", Path.home() / ".local/share/bidfinder/typesense"))


def _proc_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            parts = raw.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    except OSError:
        pass
    return values


def _typesense_rss_bytes(data_dir: Path) -> int | None:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return None
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if "typesense-server" not in command or f"--data-dir={data_dir}" not in command:
                continue
            for line in (entry / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
        except (OSError, ValueError):
            continue
    return None


def resource_snapshot(typesense_root: str | Path) -> dict[str, Any]:
    root = Path(typesense_root)
    mem = _proc_meminfo()
    usage = shutil.disk_usage(root)
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    return {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": mem.get("MemTotal"),
        "memory_available_bytes": mem.get("MemAvailable"),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(swap_total - swap_free, 0),
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "disk_free_fraction": round(usage.free / usage.total, 6) if usage.total else 0.0,
        "typesense_rss_bytes": _typesense_rss_bytes(root / "data"),
    }


class ResourceSafetyGuard:
    """Record bounded host samples and stop safely before resource exhaustion."""

    def __init__(self, typesense_root: str | Path) -> None:
        self.typesense_root = Path(typesense_root)
        self._swap_growth_streak = 0
        self._previous_swap_used: int | None = None
        self.sample_count = 0

    def check(self, report: Any) -> dict[str, Any]:
        sample = resource_snapshot(self.typesense_root)
        self.sample_count += 1
        monitoring = report.data["resource_monitoring"]
        monitoring["last"] = sample
        monitoring["sample_count"] = self.sample_count
        if self.sample_count <= 10 or self.sample_count % 25 == 0:
            monitoring["samples"] = (monitoring.get("samples", []) + [sample])[-10:]
        report.write()

        available = sample.get("memory_available_bytes")
        if available is not None and available < CRITICAL_MEM_AVAILABLE_BYTES:
            raise KeyboardInterrupt("RESOURCE_SAFETY: MemAvailable below 2 GiB")
        if sample["disk_free_fraction"] < CRITICAL_FREE_FRACTION:
            raise KeyboardInterrupt("RESOURCE_SAFETY: Typesense disk free below 20%")
        swap_used = int(sample["swap_used_bytes"])
        if self._previous_swap_used is not None and swap_used > self._previous_swap_used:
            self._swap_growth_streak += 1
        else:
            self._swap_growth_streak = 0
        self._previous_swap_used = swap_used
        if self._swap_growth_streak >= 3:
            raise KeyboardInterrupt("RESOURCE_SAFETY: swap usage increased across three samples")
        sample["disk_warning"] = sample["disk_free_fraction"] < WARNING_FREE_FRACTION
        return sample


def _sqlite_integrity(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


class RecoveryBundleManager:
    """Create and validate coherent Typesense/checkpoint/provenance bundles."""

    def __init__(
        self,
        client: TypesenseClient,
        manifest: Mapping[str, Any],
        provenance: UUIDProvenanceStore,
        *,
        checkpoint_path: str | Path,
        uuid_path: str | Path,
        report_path: str | Path,
        manifest_path: str | Path,
        recovery_dir: str | Path,
    ) -> None:
        self.client = client
        self.manifest = dict(manifest)
        self.provenance = provenance
        self.checkpoint_path = Path(checkpoint_path)
        self.uuid_path = Path(uuid_path)
        self.report_path = Path(report_path)
        self.manifest_path = Path(manifest_path)
        self.recovery_dir = Path(recovery_dir)
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        self.last_milestone_accepted = 0
        self.created: list[dict[str, Any]] = []

    def _counts(self) -> dict[str, int]:
        return {
            group: self.client.document_count(physical_collection_name(group, self.manifest["generation"]))
            for group in LOGICAL_ALIASES
        }

    def create(self, label: str, report: Any, *, final: bool = False) -> dict[str, Any]:
        boundary = report.data.get("last_completed_partition")
        if label != "initial" and not boundary:
            raise RuntimeError("recovery bundle requires a completed parent-partition boundary")
        indices = []
        for bundle in self.recovery_dir.glob("bundle-*"):
            match = re.match(r"^bundle-(\d+)-", bundle.name)
            if match:
                indices.append(int(match.group(1)))
        next_index = max(indices, default=-1) + 1
        name = f"bundle-{next_index:05d}-{label}"
        temporary = self.recovery_dir / f".{name}.tmp"
        target = self.recovery_dir / name
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        snapshot = temporary / "typesense-snapshot"
        snapshot.mkdir()
        self.client.snapshot(snapshot)
        if not any(snapshot.iterdir()):
            raise RuntimeError("Typesense snapshot is empty")
        shutil.copy2(self.checkpoint_path, temporary / "checkpoint.sqlite3")
        shutil.copy2(self.uuid_path, temporary / "uuid-provenance.sqlite3")
        shutil.copy2(self.report_path, temporary / "backfill-report.json")
        shutil.copy2(self.manifest_path, temporary / "manifest.json")
        counts = self._counts()
        metadata = {
            "bundle_version": "msc-phase3b-recovery-v1",
            "label": label,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generation": self.manifest["generation"],
            "manifest_fingerprint": fingerprint(self.manifest),
            "last_completed_partition": boundary,
            "accepted_document_counts": counts,
            "uuid_audit_total": self.provenance.total_count(),
            "uuid_conflict_count": self.provenance.conflict_count(),
            "final": final,
        }
        atomic_write_json(temporary / "bundle.json", metadata)
        self._validate(temporary, metadata)
        temporary.replace(target)
        metadata["path"] = str(target)
        self.created.append(metadata)
        if not final:
            self._prune()
        return metadata

    def maybe_create(self, result: Any, report: Any) -> dict[str, Any] | None:
        if getattr(result, "skipped", False):
            return None
        accepted = int(report.data["counts"].get("records_accepted", 0))
        if accepted - self.last_milestone_accepted < RECOVERY_MILESTONE_DOCUMENTS:
            return None
        self.last_milestone_accepted = accepted
        return self.create(f"milestone-{accepted}", report)

    def _validate(self, directory: Path, metadata: Mapping[str, Any]) -> None:
        for name in ("checkpoint.sqlite3", "uuid-provenance.sqlite3", "backfill-report.json", "manifest.json"):
            if not (directory / name).is_file():
                raise RuntimeError(f"recovery bundle missing {name}")
        if _sqlite_integrity(directory / "checkpoint.sqlite3") != "ok":
            raise RuntimeError("checkpoint recovery copy failed integrity check")
        if _sqlite_integrity(directory / "uuid-provenance.sqlite3") != "ok":
            raise RuntimeError("UUID provenance recovery copy failed integrity check")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        verify_manifest(manifest, generation=self.manifest["generation"])
        if fingerprint(manifest) != metadata["manifest_fingerprint"]:
            raise RuntimeError("recovery manifest fingerprint mismatch")
        report = json.loads((directory / "backfill-report.json").read_text(encoding="utf-8"))
        if report.get("generation") != self.manifest["generation"]:
            raise RuntimeError("recovery report generation mismatch")
        if self._counts() != metadata["accepted_document_counts"]:
            raise RuntimeError("recovery Typesense counts changed during validation")

    def _prune(self) -> None:
        bundles = sorted((p for p in self.recovery_dir.glob("bundle-*") if p.is_dir()), key=lambda p: p.name)
        keep = set(bundles[-2:])
        keep.update(p for p in bundles if p.name.endswith("-final"))
        for bundle in bundles:
            if bundle not in keep:
                shutil.rmtree(bundle)


def _reconcile_coverage(
    engine: MSCIngestionEngine,
    runner: BackfillRunner,
    manifest: Mapping[str, Any],
    store: CheckpointStore,
    provenance: UUIDProvenanceStore,
    manifest_deltas: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "SKIPPED_NO_SOURCE_DRIFT" if not manifest_deltas else "PASS",
        "sources": {},
        "changed_partitions": [],
        "requests": 0,
    }
    sink_target = f"typesense:{manifest['generation']}"
    for source_key in manifest["sources"]:
        if source_key not in manifest_deltas:
            continue
        prefix = reconcile_completed_prefix(
            engine.client,
            store,
            source_key,
            manifest["source_range"]["from"],
            manifest["source_range"]["to"],
            sink_target,
        )
        result["sources"][source_key] = prefix
        result["requests"] += int(prefix["requests"])
        for changed in prefix["changed_partitions"]:
            source_date = (changed["source_key"], changed["partition_date"])
            old_uuids = provenance.partition_uuids(*source_date)
            partition_result = engine.ingest_partition(
                changed["source_key"],
                changed["partition_date"],
                force=True,
                allow_open_day=False,
                replace_existing=True,
            )
            if partition_result.status != IngestionStatus.COMPLETED:
                result["status"] = "FAILED"
                raise BackfillControlError(
                    f"completed partition reconciliation failed for {source_date[0]}:{source_date[1]}"
                )
            new_uuids = provenance.partition_uuids(*source_date)
            reconciliation = {
                **changed,
                "added_uuid_count": len(new_uuids - old_uuids),
                "removed_uuid_count": len(old_uuids - new_uuids),
                "result": partition_result.as_dict(),
            }
            result["changed_partitions"].append(reconciliation)
            runner.report.data.setdefault("reconciled_completed_partitions", []).append(reconciliation)
            runner.report.write()

        if prefix["changed_partitions"]:
            verified = reconcile_completed_prefix(
                engine.client,
                store,
                source_key,
                manifest["source_range"]["from"],
                manifest["source_range"]["to"],
                sink_target,
            )
            result["requests"] += int(verified["requests"])
            result["sources"][source_key]["post_reconciliation"] = verified
            if verified["changed_partitions"]:
                result["status"] = "FAILED"
                raise BackfillControlError(
                    f"completed prefix remained unstable for {source_key} after exact partition reconciliation"
                )
    return result


def _sample_parity(msc: MSCClient, typesense: TypesenseClient, manifest: Mapping[str, Any]) -> dict[str, Any]:
    start = date.fromisoformat(manifest["source_range"]["from"])
    end = date.fromisoformat(manifest["source_range"]["to"])
    dates = (start, start + (end - start) // 2, end)
    samples: list[dict[str, Any]] = []
    for source_key in manifest["sources"]:
        contract = get_contract(source_key)
        found = 0
        for sample_date in dates:
            parent = official_day_interval(sample_date)
            count = msc.count_interval(contract, parent)
            if count <= 0:
                continue
            response = msc.fetch_page(contract, parent, 0)
            page = response.get("page", {})
            records = page.get("content", []) if isinstance(page, dict) else []
            drift = validate_raw_records(contract, records)
            if not records or drift.breaking:
                samples.append({"source_key": source_key, "date": sample_date.isoformat(), "pass": False, "reason": "sample contract failure"})
                continue
            canonical = normalize_records(contract, records[:1], sample_date.isoformat())[0]
            expected = canonical_to_typesense_document(canonical, contract.data_group)
            actual = typesense.get_document(physical_collection_name(contract.data_group, manifest["generation"]), canonical["id"])
            equal = actual == expected
            samples.append({"source_key": source_key, "date": sample_date.isoformat(), "uuid": canonical["id"], "retrieved": actual is not None, "fields_equal": equal, "pass": equal})
            found += 1
        if found == 0:
            samples.append({"source_key": source_key, "pass": False, "reason": "no deterministic sample date had records"})
    return {"status": "PASS" if samples and all(item["pass"] for item in samples) else "FAIL", "seed": 20230830, "samples": samples}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return round(sorted(values)[max(0, min(len(values) - 1, int(len(values) * fraction + 0.9999) - 1))], 3)


def _concurrency_benchmark(config: TypesenseConfig, generation: str) -> list[dict[str, Any]]:
    collection = physical_collection_name("goods", generation)

    def one() -> tuple[float, str | None]:
        client = TypesenseClient(config)
        started = time.perf_counter()
        try:
            client.search_group("goods", "*", collection=collection, per_page=20)
            return (time.perf_counter() - started) * 1000, None
        except Exception as exc:  # benchmark reports errors; it never changes data
            return (time.perf_counter() - started) * 1000, str(exc)

    results: list[dict[str, Any]] = []
    for level in (1, 10, 25):
        started = time.perf_counter()
        samples: list[float] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=level) as pool:
            for future in as_completed([pool.submit(one) for _ in range(level)]):
                latency, error = future.result()
                samples.append(latency)
                if error:
                    errors.append(error)
        elapsed = time.perf_counter() - started
        results.append({"clients": level, "requests": len(samples), "requests_per_second": round(len(samples) / elapsed, 3) if elapsed else 0.0, "p50_ms": _percentile(samples, 0.50), "p95_ms": _percentile(samples, 0.95), "max_ms": round(max(samples), 3) if samples else 0.0, "errors": errors})
    return results


def _markdown(audit: Mapping[str, Any]) -> str:
    counts = audit.get("counts", {})
    lines = [
        "# Phase 3B historical backfill audit",
        "",
        f"- Status: `{audit.get('overall_status')}`",
        f"- Generation: `{audit.get('generation')}`",
        f"- Range: `{audit.get('range', {}).get('from')}` to `{audit.get('range', {}).get('to')}`",
        f"- Manifest fingerprint: `{audit.get('manifest_fingerprint')}`",
        "",
        "## Counts",
        "",
        f"- Parent partitions: `{counts.get('parent_partitions_total')}`; completed `{counts.get('completed')}`; skipped `{counts.get('skipped')}`; failed `{counts.get('failed')}`; quarantined `{counts.get('quarantined')}`.",
        f"- Normalized: `{counts.get('normalized_documents')}`; Typesense attempted `{counts.get('typesense_attempted')}`; accepted `{counts.get('records_accepted')}`; rejected `{counts.get('typesense_rejected')}`.",
        "",
        "## Source coverage",
        "",
        "| Source | Broad count | Checkpoint sum | Parity |",
        "| --- | ---: | ---: | --- |",
    ]
    for source, item in audit.get("source_coverage", {}).items():
        lines.append(f"| `{source}` | {item.get('broad_range_count')} | {item.get('sum_completed_parent_source_counts')} | `{item.get('parity')}` |")
    lines += [
        "",
        f"- UUID conflicts: `{audit.get('uuid_conflict_count')}`; recovery bundles: `{len(audit.get('recovery_bundles', []))}`.",
        f"- Sample parity: `{audit.get('sample_parity', {}).get('status')}`; search benchmark errors: `{len(audit.get('search_benchmark', {}).get('errors', []))}`.",
        f"- Clean restart: `{audit.get('clean_restart', {}).get('pass')}`.",
        "",
        "Aliases remain inactive. FastAPI/frontend remain unchanged.",
    ]
    return "\n".join(lines) + "\n"


def _manifest_deltas(
    authorized: Mapping[str, Any],
    current_source_totals: Mapping[str, int],
    observed_at: str,
) -> dict[str, dict[str, Any]]:
    return {
        source_key: {
            "old_count": int(authorized["source_totals"][source_key]),
            "current_count": int(current_source_totals[source_key]),
            "delta": int(current_source_totals[source_key]) - int(authorized["source_totals"][source_key]),
            "observed_at": observed_at,
            "affected": int(current_source_totals[source_key]) != int(authorized["source_totals"][source_key]),
        }
        for source_key in authorized["sources"]
    }


def _current_observed_manifest(
    authorized: Mapping[str, Any],
    fresh: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    observed = dict(authorized)
    observed["source_totals"] = dict(fresh["source_totals"])
    observed["group_totals"] = dict(fresh["group_totals"])
    observed["expected_overall_total"] = int(fresh["overall_total"])
    observed["manifest_role"] = "current_observed"
    observed["observed_at"] = observed_at
    observed["authorized_manifest_fingerprint"] = fingerprint(authorized)
    return observed


def _prepare_manifest_for_run(
    authorized: Mapping[str, Any],
    fresh: Mapping[str, Any],
    observed_at: str,
    *,
    resume: bool,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    deltas = _manifest_deltas(authorized, fresh["source_totals"], observed_at)
    changed = {key: value for key, value in deltas.items() if value["affected"]}
    if changed and not resume:
        raise BackfillControlError(f"fresh MSC preflight differs from frozen manifest: {changed}")
    return _current_observed_manifest(authorized, fresh, observed_at), deltas, changed


def _quarantine_stale_milestone(recovery_dir: Path) -> dict[str, Any]:
    stale = recovery_dir / ".bundle-00002-milestone-6025055.tmp"
    if not stale.exists():
        return {"status": "ABSENT", "path": str(stale)}
    target = recovery_dir / "quarantine-bundle-00002-milestone-6025055.tmp"
    if target.exists():
        raise BackfillControlError(f"stale recovery quarantine target already exists: {target}")
    stale.replace(target)
    return {
        "status": "QUARANTINED",
        "path": str(target),
        "source": str(stale),
        "reason": "incomplete snapshot-only directory; no coherent DB/report/manifest metadata",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--uuid-audit", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--audit-markdown", type=Path, required=True)
    parser.add_argument("--max-partitions", type=int, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--acknowledge-readiness", action="store_true")
    parser.add_argument("--authorize-full-run", required=True)
    parser.add_argument("--typesense-root", type=Path, default=_default_root())
    return parser


def run(args: argparse.Namespace) -> int:
    if (args.from_date, args.to_date, args.generation) != (HISTORICAL_START, HISTORICAL_END, HISTORICAL_GENERATION):
        raise BackfillControlError("Phase 3B requires the exact frozen historical range and generation")
    if not args.acknowledge_readiness:
        raise BackfillControlError("Phase 3B requires --acknowledge-readiness")
    require_full_run_authorization(args.authorize_full_run)
    authorized_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_manifest(authorized_manifest, generation=args.generation)
    if authorized_manifest["source_range"]["from"] != args.from_date or authorized_manifest["source_range"]["to"] != args.to_date:
        raise BackfillControlError("manifest range does not match explicit Phase 3B range")
    if authorized_manifest["source_totals"] != AUTHORITATIVE_SOURCE_TOTALS:
        raise BackfillControlError("manifest source totals do not match the frozen Phase 3B authorization")

    msc_config = MSCConfig(request_delay_seconds=1.0, timeout_seconds=30.0, max_retries=3, page_size=int(authorized_manifest["page_size"]))
    msc = MSCClient(msc_config)
    fresh = source_population_preflight(msc, args.from_date, args.to_date, authorized_manifest["sources"])
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest, manifest_deltas, changed_manifest_deltas = _prepare_manifest_for_run(
        authorized_manifest,
        fresh,
        observed_at,
        resume=args.resume,
    )
    if not args.resume and fresh["source_totals"] != AUTHORITATIVE_SOURCE_TOTALS:
        raise BackfillControlError("fresh MSC preflight does not match the frozen Phase 3B authorization")
    observed_manifest_path = args.manifest.with_name(f"{args.manifest.stem}.observed.json")
    atomic_write_json(observed_manifest_path, manifest)
    manifest_lineage = {
        "authorized_start": {
            "path": str(args.manifest),
            "fingerprint": fingerprint(authorized_manifest),
            "source_totals": dict(authorized_manifest["source_totals"]),
            "expected_overall_total": int(authorized_manifest["expected_overall_total"]),
        },
        "current_observed": {
            "path": str(observed_manifest_path),
            "fingerprint": fingerprint(manifest),
            "source_totals": dict(manifest["source_totals"]),
            "expected_overall_total": int(manifest["expected_overall_total"]),
            "observed_at": observed_at,
        },
        "source_deltas": manifest_deltas,
    }

    typesense_config = TypesenseConfig.from_env()
    typesense_config = typesense_config.__class__(**{**typesense_config.__dict__, "batch_size": int(manifest["typesense_batch_size"])})
    typesense = TypesenseClient(typesense_config)
    health = typesense.health()
    if health.get("version") not in (None, "30.2"):
        raise BackfillControlError(f"unsupported Typesense version: {health.get('version')}")
    aliases = {name: (typesense.get_alias(name) or {}).get("collection_name") for name in LOGICAL_ALIASES}
    if any(aliases.values()):
        raise BackfillControlError("stable aliases must remain inactive")
    expected_collections = {physical_collection_name(group, args.generation) for group in LOGICAL_ALIASES}
    for name in expected_collections:
        if typesense.get_collection(name) is None:
            raise BackfillControlError(f"historical collection missing: {name}")
    physical = json.loads(typesense._request_raw("GET", "/collections?per_page=250").decode("utf-8"))
    live_generations = {item.get("metadata", {}).get("generation_id") for item in physical if item.get("name", "").startswith("bidfinder_") and item.get("metadata", {}).get("generation_id")}
    if len(live_generations) > 2 or args.generation not in live_generations:
        raise BackfillControlError(f"live generation envelope failed: {sorted(live_generations)}")

    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with CheckpointStore(args.checkpoint) as checkpoints, UUIDProvenanceStore(args.uuid_audit) as provenance:
        sink = AuditedSink(TypesenseSink(typesense, args.generation), provenance)
        engine = MSCIngestionEngine(msc, checkpoints, sink, msc_config)
        guard = ResourceSafetyGuard(args.typesense_root)
        stale_milestone = _quarantine_stale_milestone(args.recovery_dir)
        bundles = RecoveryBundleManager(typesense, manifest, provenance, checkpoint_path=args.checkpoint, uuid_path=args.uuid_audit, report_path=args.report, manifest_path=observed_manifest_path, recovery_dir=args.recovery_dir)
        initial_counts = bundles._counts()
        if not args.resume and any(initial_counts.values()):
            raise BackfillControlError(f"non-resume run requires empty historical generation: {initial_counts}")
        runner = BackfillRunner(engine, checkpoints, manifest, report_path=args.report, resume=args.resume, force=args.force, max_partitions=args.max_partitions, on_before_partition=lambda _s, _d, report: guard.check(report), on_partition_boundary=lambda result, report: bundles.maybe_create(result, report))
        runner.report.data["manifest_lineage"] = manifest_lineage
        runner.report.data["stale_recovery_milestone"] = stale_milestone
        initial_resource = guard.check(runner.report)
        runner.report.data["resource_monitoring"]["initial"] = initial_resource
        runner.report.write()
        if not args.resume and not list(args.recovery_dir.glob("bundle-*")):
            runner.report.write()
            bundles.create("initial", runner.report)
        interrupted_or_failed: str | None = None
        coverage: dict[str, Any] = {"status": "NOT_RUN", "sources": {}, "changed_partitions": [], "requests": 0}
        with graceful_interrupts():
            try:
                if args.resume:
                    coverage = _reconcile_coverage(engine, runner, manifest, checkpoints, provenance, changed_manifest_deltas)
                    runner.report.data["coverage_reconciliation"] = coverage
                    runner.report.write()
                runner.run()
            except KeyboardInterrupt as exc:
                interrupted_or_failed = str(exc) or "INTERRUPTED"
            except Exception as exc:
                interrupted_or_failed = str(exc)

        if interrupted_or_failed is not None and coverage["status"] == "NOT_RUN":
            coverage = {"status": "SKIPPED", "sources": {}, "changed_partitions": [], "requests": 0}
        report_data = json.loads(args.report.read_text(encoding="utf-8"))
        base_audit = historical_backfill_audit(manifest, checkpoints, provenance, typesense_client=typesense, report=report_data)
        base_audit["manifest_fingerprint"] = fingerprint(manifest)
        base_audit["manifest"] = manifest
        base_audit["authorized_manifest"] = authorized_manifest
        base_audit["manifest_lineage"] = manifest_lineage
        base_audit["manifest_deltas"] = manifest_deltas
        base_audit["fresh_preflight"] = fresh
        base_audit["stale_recovery_milestone"] = stale_milestone
        base_audit["coverage_reconciliation"] = coverage
        base_audit["counts"] = report_data.get("counts", {})
        base_audit["source_coverage"] = base_audit.get("source_coverage_parity", {})
        base_audit["schema_drift"] = report_data.get("schema_drift", {})
        base_audit["uuid_conflicts"] = provenance.conflict_count()
        base_audit["recovery_bundles"] = list(bundles.created)
        base_audit["interrupted_or_failed"] = interrupted_or_failed
        run_counts = base_audit["counts"]
        expected_documents = int(manifest["expected_overall_total"])
        base_audit["data_plane_gate"] = {
            "normalized_documents": int(run_counts.get("normalized_documents", 0)),
            "typesense_attempted": int(run_counts.get("typesense_attempted", 0)),
            "typesense_rejected": int(run_counts.get("typesense_rejected", 0)),
            "records_accepted": int(run_counts.get("records_accepted", 0)),
            "expected_documents": expected_documents,
            "pass": (
                int(run_counts.get("normalized_documents", 0)) == expected_documents
                and int(run_counts.get("typesense_attempted", 0)) == expected_documents
                and int(run_counts.get("typesense_rejected", 0)) == 0
                and int(run_counts.get("records_accepted", 0)) == expected_documents
            ),
        }

        if interrupted_or_failed is None and coverage["status"] == "PASS":
            base_audit["sample_parity"] = _sample_parity(msc, typesense, manifest)
            from crawler_engine.msc.backfill import run_search_benchmark
            base_audit["search_benchmark"] = run_search_benchmark(typesense, args.generation, repeats=3)
            base_audit["concurrency"] = _concurrency_benchmark(typesense_config, args.generation)
            base_audit["resources_final_before_restart"] = resource_snapshot(args.typesense_root)
            audit_gates_pass = base_audit["overall_status"] == "PASS" and base_audit["data_plane_gate"]["pass"] and base_audit["sample_parity"]["status"] == "PASS" and not base_audit["search_benchmark"]["errors"] and all(not item["errors"] for item in base_audit["concurrency"])
            if audit_gates_pass:
                final_bundle = bundles.create("final", runner.report, final=True)
                base_audit["final_recovery_bundle"] = final_bundle
                subprocess.run(["bash", "infra/typesense/local-typesense.sh", "restart"], check=True)
                restarted = TypesenseClient(TypesenseConfig.from_env())
                restart_counts = {group: restarted.document_count(physical_collection_name(group, args.generation)) for group in LOGICAL_ALIASES}
                restart_search = restarted.search_group("goods", "*", collection=physical_collection_name("goods", args.generation), per_page=1)
                base_audit["clean_restart"] = {"pass": restarted.health().get("ok") is True and all(value == base_audit["group_expected_unique_counts"][group] for group, value in restart_counts.items()) and int(restart_search.get("found", 0)) >= 1, "counts": restart_counts, "search_found": restart_search.get("found")}
                base_audit["resources_final"] = resource_snapshot(args.typesense_root)
            else:
                base_audit["clean_restart"] = {"pass": False, "skipped": True}
        else:
            base_audit["sample_parity"] = {"status": "SKIPPED"}
            base_audit["search_benchmark"] = {"errors": [], "status": "SKIPPED"}
            base_audit["concurrency"] = []
            base_audit["clean_restart"] = {"pass": False, "skipped": True}
        base_audit["overall_status"] = "PASS" if base_audit.get("overall_status") == "PASS" and base_audit.get("data_plane_gate", {}).get("pass") and base_audit.get("coverage_reconciliation", {}).get("status") == "PASS" and base_audit.get("sample_parity", {}).get("status") == "PASS" and not base_audit.get("search_benchmark", {}).get("errors") and all(not item.get("errors") for item in base_audit.get("concurrency", [])) and base_audit.get("clean_restart", {}).get("pass") else "PARTIAL"
        atomic_write_json(args.audit_json, base_audit)
        args.audit_markdown.write_text(_markdown(base_audit), encoding="utf-8")
        return 0 if base_audit["overall_status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return run(_parser().parse_args(argv))
    except (BackfillControlError, TypesenseError, OSError, ValueError) as exc:
        print(f"Phase 3B BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
