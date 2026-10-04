"""Run bounded empirical Typesense sizing against real MSC canonical records.

This runner is deliberately separate from the production CLI. It reuses the
production MSCIngestionEngine and TypesenseSink, but has a deterministic,
guarded sample plan and never activates aliases or touches Postgres.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawler_engine.msc.backfill import AuditedSink, UUIDProvenanceStore
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS, get_contract
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus, PartitionContext, PartitionResult, SinkWriteResult
from crawler_engine.msc.partitioning import official_day_interval
from crawler_engine.msc.sink import Sink, TypesenseSink
from crawler_engine.msc.typesense_client import TypesenseClient, TypesenseCollectionManager
from crawler_engine.msc.typesense_schema import (
    SEARCH_CONFIGS,
    canonical_to_typesense_document,
    physical_collection_name,
)
from crawler_engine.msc.sizing import (
    FULL_DATASET_DOCUMENTS,
    RAM_TARGET_UTILIZATION,
    SIZING_SAMPLE_MAXIMUM,
    SIZING_SAMPLE_MINIMUM,
    SIZING_SAMPLE_TARGET,
    capacity_decision,
    canonical_json,
    deterministic_sample_plan,
    empirical_projection,
    enforce_sample_maximum,
    growth_scenarios,
    indexed_field_names,
    serialize_report,
    subtract_baseline,
    write_report,
)

DEFAULT_GENERATION = f"size_{date.today().strftime('%Y%m%d')}_{os.getpid()}"
SOURCE_QUOTAS = {
    "goods_general": 390_000,
    "medical_devices": 35_000,
    "medicine_generic": 40_000,
    "medicine_originator": 5_000,
    "medicine_herbal": 10_000,
    "herbal_material": 10_000,
    "traditional_medicine": 10_000,
}

# The labels name the intended field coverage. Typesense still uses the frozen
# query_by list, exactly as production search does.
SEARCH_CASES = (
    {"category": "goods_item_name", "group": "goods", "target_field": "item_name", "query": "máy"},
    {"category": "goods_manufacturer", "group": "goods", "target_field": "manufacturer", "query": "công ty"},
    {"category": "goods_bidder", "group": "goods", "target_field": "winning_bidder_name", "query": "công ty"},
    {"category": "goods_tender_code", "group": "goods", "target_field": "bid_invitation_code", "query": "Gói thầu"},
    {"category": "goods_source_tab", "group": "goods", "target_field": "source_tab", "query": "*", "filter_by": "source_tab:=HANG_HOA"},
    {"category": "goods_price_filter", "group": "goods", "target_field": "winning_unit_price", "query": "*", "filter_by": "winning_unit_price:>0"},
    {"category": "goods_price_sort", "group": "goods", "target_field": "winning_unit_price", "query": "*", "sort_by": "winning_unit_price:desc"},
    {"category": "medicines_name", "group": "medicines", "target_field": "medicine_name", "query": "thuốc"},
    {"category": "medicines_active_ingredient", "group": "medicines", "target_field": "active_ingredient_or_herbal_component", "query": "acid"},
    {"category": "medicines_manufacturer", "group": "medicines", "target_field": "manufacturer", "query": "công ty"},
    {"category": "medicines_bidder_tender", "group": "medicines", "target_field": "winning_bidder_name,bid_invitation_code", "query": "công ty"},
    {"category": "traditional_item_name", "group": "traditional_medicine", "target_field": "item_name", "query": "dược liệu"},
    {"category": "traditional_scientific_name", "group": "traditional_medicine", "target_field": "scientific_name", "query": "cây"},
    {"category": "traditional_manufacturer_source", "group": "traditional_medicine", "target_field": "manufacturer,source_tab", "query": "công ty"},
    {"category": "traditional_bidder_tender", "group": "traditional_medicine", "target_field": "winning_bidder_name,bid_invitation_code", "query": "công ty"},
)


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 3)


def _command(command: Sequence[str], *, timeout: float = 60.0, check: bool = True) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}: {completed.stderr[-500:]}")
    return (completed.stdout or "").strip()


def _docker_exec(container: str, script: str) -> str:
    return _command(["rtk", "docker", "exec", container, "sh", "-c", script], timeout=30)


def _read_os_metrics(container: str) -> dict[str, Any]:
    script = (
        "awk '/VmRSS:/ {print \"rss_bytes=\" $2*1024}' /proc/1/status; "
        "awk '/MemAvailable:/ {print \"memory_available_bytes=\" $2*1024} "
        "/MemFree:/ {print \"memory_free_bytes=\" $2*1024}' /proc/meminfo; "
        "du -sb /data 2>/dev/null | awk '{print \"data_directory_bytes=\" $1}'; "
        "df -B1 /data | awk 'NR==2 {print \"disk_available_bytes=\" $4}'"
    )
    values: dict[str, Any] = {}
    for line in _docker_exec(container, script).splitlines():
        key, _, value = line.partition("=")
        if key and value.isdigit():
            values[key] = int(value)
    try:
        cpu = _command(["rtk", "docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", container], timeout=30)
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", cpu)
        if match:
            values["container_cpu_percent"] = float(match.group(1))
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        values["container_cpu_percent"] = None
    values["process"] = "Linux /proc/1 inside disposable Typesense container"
    return values


def _numeric_metrics(metrics: Mapping[str, Any]) -> dict[str, int | float]:
    return {key: value for key, value in metrics.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}


def _metric(metrics: Mapping[str, Any], *names: str) -> int | float | None:
    for name in names:
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _measurement(
    client: TypesenseClient,
    generation: str,
    container: str,
    label: str,
    *,
    settle_seconds: float,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if settle_seconds:
        time.sleep(settle_seconds)
    collection_counts = {
        group: client.document_count(physical_collection_name(group, generation))
        for group in SEARCH_CONFIGS
    }
    try:
        raw_metrics = client.metrics()
        metrics_error = None
    except Exception as exc:  # Metrics are optional; OS metrics remain authoritative.
        raw_metrics = {}
        metrics_error = f"{type(exc).__name__}: {exc}"
    os_metrics = _read_os_metrics(container)
    result: dict[str, Any] = {
        "label": label,
        "documents": sum(collection_counts.values()),
        "collection_document_counts": collection_counts,
        "typesense": {
            "metrics_error": metrics_error,
            "numeric_metrics": _numeric_metrics(raw_metrics),
            "memory_allocated_bytes": _metric(raw_metrics, "memory_allocated_bytes", "memory_allocated"),
            "memory_active_bytes": _metric(raw_metrics, "memory_active_bytes", "memory_active"),
            "system_memory_used_bytes": _metric(raw_metrics, "system_memory_used_bytes"),
            "system_memory_free_bytes": _metric(raw_metrics, "system_memory_free_bytes"),
            "cpu_active_percentage": _metric(raw_metrics, "system_cpu_active_percentage", "cpu_active_percentage"),
        },
        "os": os_metrics,
    }
    if baseline is not None:
        base_os = baseline["os"]
        for name, key in (
            ("dataset_process_rss_bytes", "rss_bytes"),
            ("dataset_data_directory_bytes", "data_directory_bytes"),
        ):
            if key in os_metrics and key in base_os:
                result[name] = round(subtract_baseline(os_metrics[key], base_os[key]))
            else:
                result[name] = None
        for name, key in (
            ("dataset_typesense_memory_allocated_bytes", "memory_allocated_bytes"),
            ("dataset_typesense_memory_active_bytes", "memory_active_bytes"),
        ):
            current = result["typesense"].get(key)
            previous = baseline["typesense"].get(key)
            result[name] = round(subtract_baseline(current, previous)) if current is not None and previous is not None else None
    return result


class SizingObservingSink:
    """Observe canonical records, then delegate unchanged to production sink."""

    def __init__(self, sink: Sink) -> None:
        self.sink = sink
        self.sink_target = getattr(sink, "sink_target", "unknown")
        self.canonical_bytes = 0
        self.indexed_bytes = 0
        self.document_counts: dict[str, int] = defaultdict(int)
        self.field_observation_counts: dict[str, int] = defaultdict(int)
        self.field_totals: dict[str, int] = defaultdict(int)
        self.field_observation_limit = 25_000

    def write_partition(self, context: PartitionContext, records: Sequence[Mapping[str, Any]]) -> SinkWriteResult:
        group = context.contract.data_group
        names = set(indexed_field_names(group))
        for record in records:
            document = canonical_to_typesense_document(record, group)
            self.canonical_bytes += len(canonical_json(record).encode("utf-8"))
            indexed = {key: value for key, value in document.items() if key in names}
            self.indexed_bytes += len(canonical_json(indexed).encode("utf-8"))
            self.document_counts[group] += 1
            if self.field_observation_counts[group] < self.field_observation_limit:
                self.field_observation_counts[group] += 1
                for name, value in indexed.items():
                    self.field_totals[f"{group}.{name}"] += len(canonical_json({name: value}).encode("utf-8"))
        return self.sink.write_partition(context, records)

    def field_report(self) -> list[dict[str, Any]]:
        total = sum(self.field_totals.values())
        counts = self.document_counts
        rows = []
        for key, value in sorted(self.field_totals.items(), key=lambda item: item[1], reverse=True):
            group, field = key.split(".", 1)
            rows.append({
                "logical_group": group,
                "field": field,
                "serialized_index_input_bytes": value,
                "percentage": value / total * 100 if total else 0.0,
                "average_bytes_per_group_document": value / self.field_observation_counts[group] if self.field_observation_counts[group] else 0.0,
                "observation_documents": self.field_observation_counts[group],
            })
        return rows


def _search_one(client: TypesenseClient, generation: str, case: Mapping[str, Any]) -> None:
    kwargs = {key: case[key] for key in ("filter_by", "sort_by") if key in case}
    client.search_group(case["group"], case["query"], collection=physical_collection_name(case["group"], generation), **kwargs)


def _run_search_benchmark(client: TypesenseClient, generation: str, milestone: str, repeats: int = 4) -> dict[str, Any]:
    # One warm-up per case and one multi-search warm-up keep cold startup out of timings.
    for case in SEARCH_CASES:
        try:
            _search_one(client, generation, case)
        except Exception:
            pass
    try:
        client.multi_search_all("thuốc", generation_id=generation, per_page=20)
    except Exception:
        pass
    cases = []
    for case in SEARCH_CASES:
        samples: list[float] = []
        errors: list[str] = []
        for _ in range(repeats):
            started = time.perf_counter()
            try:
                _search_one(client, generation, case)
                samples.append((time.perf_counter() - started) * 1000)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
        cases.append({
            **case,
            "milestone": milestone,
            "successful": len(samples),
            "errors": errors,
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "max_ms": round(max(samples), 3) if samples else None,
        })
    multi_samples: list[float] = []
    multi_errors: list[str] = []
    for _ in range(repeats):
        started = time.perf_counter()
        try:
            client.multi_search_all("thuốc", generation_id=generation, per_page=20)
            multi_samples.append((time.perf_counter() - started) * 1000)
        except Exception as exc:
            multi_errors.append(f"{type(exc).__name__}: {exc}")
    cases.append({
        "category": "multi_search_all",
        "group": "all",
        "target_field": "goods+medicines+traditional_medicine",
        "query": "thuốc",
        "milestone": milestone,
        "successful": len(multi_samples),
        "errors": multi_errors,
        "p50_ms": _percentile(multi_samples, 0.50),
        "p95_ms": _percentile(multi_samples, 0.95),
        "max_ms": round(max(multi_samples), 3) if multi_samples else None,
    })
    return {"milestone": milestone, "repeats": repeats, "cases": cases}


def _worker_queries(config: TypesenseConfig, generation: str) -> dict[str, Any]:
    client = TypesenseClient(config)
    samples: list[float] = []
    errors: list[str] = []
    for case in SEARCH_CASES:
        started = time.perf_counter()
        try:
            _search_one(client, generation, case)
            samples.append((time.perf_counter() - started) * 1000)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    started = time.perf_counter()
    try:
        client.multi_search_all("thuốc", generation_id=generation, per_page=20)
        samples.append((time.perf_counter() - started) * 1000)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    return {"samples": samples, "errors": errors}


def _run_concurrency_probe(config: TypesenseConfig, generation: str) -> list[dict[str, Any]]:
    results = []
    for concurrency in (1, 10, 25):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            workers = list(executor.map(lambda _: _worker_queries(config, generation), range(concurrency)))
        elapsed = time.perf_counter() - started
        samples = [sample for worker in workers for sample in worker["samples"]]
        errors = [error for worker in workers for error in worker["errors"]]
        requests = len(samples) + len(errors)
        results.append({
            "concurrent_clients": concurrency,
            "fixed_query_set_size": len(SEARCH_CASES) + 1,
            "requests": requests,
            "requests_per_second": round(requests / elapsed, 3) if elapsed else None,
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "max_ms": round(max(samples), 3) if samples else None,
            "errors": len(errors),
            "error_rate": len(errors) / requests if requests else 0.0,
        })
    return results


def _read_during_write(
    engine: MSCIngestionEngine,
    search_config: TypesenseConfig,
    generation: str,
    source_key: str,
    partition_date: str,
) -> tuple[dict[str, Any], Any]:
    stop = threading.Event()
    samples: list[float] = []
    errors: list[str] = []

    def search_loop() -> None:
        client = TypesenseClient(search_config)
        while not stop.is_set() and len(samples) + len(errors) < 80:
            started = time.perf_counter()
            try:
                _search_one(client, generation, SEARCH_CASES[0])
                samples.append((time.perf_counter() - started) * 1000)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=search_loop, name="typesense-sizing-read-probe", daemon=True)
    thread.start()
    started = time.perf_counter()
    result = engine.ingest_partition(source_key, partition_date)
    stop.set()
    thread.join(timeout=10)
    probe = {
        "source_key": source_key,
        "partition_date": partition_date,
        "import_documents": result.sink_accepted_count,
        "import_elapsed_seconds": result.sink_elapsed_seconds,
        "import_result_elapsed_seconds": result.elapsed_seconds,
        "wall_elapsed_seconds": round(time.perf_counter() - started, 3),
        "search_requests": len(samples) + len(errors),
        "search_p50_ms": _percentile(samples, 0.50),
        "search_p95_ms": _percentile(samples, 0.95),
        "search_max_ms": round(max(samples), 3) if samples else None,
        "search_errors": errors,
        "material_degradation_note": "Compare p95 with adjacent sequential milestone; this is observational, not an SLA.",
        "partition_status": result.status.value,
    }
    return probe, result


def _result_dict(result: PartitionResult) -> dict[str, Any]:
    if hasattr(result, "as_dict"):
        return result.as_dict()
    fields = (
        "source_key", "partition_date", "status", "parent_pre_count", "parent_post_count",
        "raw_fetched_count", "unique_source_count", "normalized_count", "sink_accepted_count",
        "leaf_count", "request_count", "retry_count", "elapsed_seconds", "drift", "error_code",
        "error_message", "skipped", "sink_target", "sink_attempted_count", "sink_batch_count",
        "sink_elapsed_seconds",
    )
    payload = {name: getattr(result, name, None) for name in fields}
    status = payload.get("status")
    payload["status"] = getattr(status, "value", status)
    drift = payload.get("drift")
    if hasattr(drift, "as_dict"):
        payload["drift"] = drift.as_dict()
    elif drift is not None and hasattr(drift, "__dict__"):
        payload["drift"] = dict(vars(drift))
    return payload


def _wait_for_document_counts(client: TypesenseClient, generation: str, expected: Mapping[str, int], timeout_seconds: float = 300.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        actual = {group: client.document_count(physical_collection_name(group, generation)) for group in SEARCH_CONFIGS}
        if actual == dict(expected):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Typesense document counts did not restore after restart: expected={dict(expected)} actual={actual}")
        time.sleep(2)


def _restart_and_measure(
    client: TypesenseClient,
    generation: str,
    container: str,
    settle_seconds: float,
    baseline: Mapping[str, Any],
    expected_counts: Mapping[str, int],
) -> dict[str, Any]:
    _command(["rtk", "docker", "stop", container], timeout=120)
    _command(["rtk", "docker", "start", container], timeout=120)
    _wait_for_health(client)
    _wait_for_document_counts(client, generation, expected_counts)
    measurement = _measurement(client, generation, container, "restart_steady_state", settle_seconds=settle_seconds, baseline=baseline)
    measurement["document_count_restore_verified"] = True
    measurement["expected_collection_document_counts"] = dict(expected_counts)
    return measurement


def _wait_for_health(client: TypesenseClient, timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if client.health().get("ok") is True:
                break
        except Exception:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Typesense did not become healthy after restart")
        time.sleep(1)


def _write_markdown(report: Mapping[str, Any], path: Path) -> None:
    def fmt(value: Any) -> str:
        if value is None:
            return "unavailable"
        if isinstance(value, float):
            return f"{value:,.3f}"
        return f"{value:,}" if isinstance(value, int) else str(value)

    lines = [
        "# Empirical Typesense sizing report",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Typesense: `{report.get('typesense_version')}`; generation: `{report.get('generation')}`",
        f"- Sample documents: **{sum(report.get('source_sample_counts', {}).values()):,}**; full dataset projection base: **{FULL_DATASET_DOCUMENTS:,}**",
        "- No full historical backfill; no application alias activation; no Neon/Postgres writes.",
        "",
        "## Sample composition",
        "",
        "| Source | Documents | Dates |",
        "| --- | ---: | --- |",
    ]
    for source in SOURCE_CONTRACTS:
        dates = report.get("source_sample_dates", {}).get(source, [])
        lines.append(f"| `{source}` | {fmt(report.get('source_sample_counts', {}).get(source, 0))} | {', '.join(dates)} |")
    lines += ["", "## Milestones", "", "| Milestone | Docs | RSS delta | Typesense active | Data-dir delta |", "| --- | ---: | ---: | ---: | ---: |"]
    for item in report.get("milestones", []):
        lines.append(f"| {item.get('label')} | {fmt(item.get('documents'))} | {fmt(item.get('dataset_process_rss_bytes'))} | {fmt(item.get('dataset_typesense_memory_active_bytes'))} | {fmt(item.get('dataset_data_directory_bytes'))} |")
    restart = report.get("restart_measurement")
    if restart:
        lines += ["", "## Restart", "", f"After graceful stop/start: `{restart.get('documents'):,}` documents; RSS delta `{fmt(restart.get('dataset_process_rss_bytes'))}`; data-dir delta `{fmt(restart.get('dataset_data_directory_bytes'))}`."]
    lines += ["", "## Projections", "", "| Metric | Largest-sample slope | Regression slope | Largest-sample full projection |", "| --- | ---: | ---: | ---: |"]
    for metric, projection in report.get("projections", {}).items():
        lines.append(f"| `{metric}` | {fmt(projection['largest_sample']['bytes_per_document'])} B/doc | {fmt(projection['regression']['bytes_per_document'])} B/doc | {fmt(round(projection['largest_sample']['projected_bytes']))} B |")
    capacity = report.get("capacity_decision")
    if capacity:
        lines += ["", f"32 GB/node decision: **{capacity.get('decision')}**; projected utilization `{capacity.get('projected_utilization', 0):.1%}` against 70% target."]
    disk_capacity = report.get("disk_capacity")
    if disk_capacity:
        lines += [f"Disk recommendation: **at least {disk_capacity.get('recommended_minimum_ssd_gb_per_node')} GB/node**; keep at least 50% free before creating another generation, warn below 35%, and block below 20%."]
    lines += ["", "## Growth", "", "| Scenario | Documents | RAM | Disk |", "| --- | ---: | ---: | ---: |"]
    for item in report.get("growth_scenarios", []):
        lines.append(f"| +{item['growth_fraction']:.0%} | {fmt(item['documents'])} | {fmt(item['projected_ram_bytes'])} B | {fmt(item['projected_disk_bytes'])} B |")
    lines += ["", "## Largest indexed fields", "", "| Group | Field | Bytes | Share |", "| --- | --- | ---: | ---: |"]
    for item in report.get("field_size_contributions", [])[:15]:
        lines.append(f"| `{item['logical_group']}` | `{item['field']}` | {fmt(item['serialized_index_input_bytes'])} | {item['percentage']:.2f}% |")
    imp = report.get("import", {})
    lines += ["", "## Import", "", f"Batch size `{imp.get('batch_size')}`; accepted `{fmt(imp.get('cumulative_accepted'))}`; rejected `{fmt(imp.get('cumulative_rejected'))}`; batches `{fmt(imp.get('cumulative_batches'))}`; Typesense import throughput `{fmt(report.get('backfill_projection', {}).get('observed_typesense_import_documents_per_second'))}` docs/s."]
    lines += ["", "## Search and concurrency", ""]
    for benchmark in report.get("search_benchmarks", []):
        lines.append(f"### {benchmark.get('milestone')}")
        lines.append("")
        lines.append("| Category | p50 ms | p95 ms | Max ms | Errors |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for case in benchmark.get("cases", []):
            lines.append(f"| `{case.get('category')}` | {fmt(case.get('p50_ms'))} | {fmt(case.get('p95_ms'))} | {fmt(case.get('max_ms'))} | {len(case.get('errors', []))} |")
        lines.append("")
    lines.append("| Concurrent clients | Requests/s | p50 ms | p95 ms | Error rate |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for item in report.get("concurrency", []):
        lines.append(f"| {item.get('concurrent_clients')} | {fmt(item.get('requests_per_second'))} | {fmt(item.get('p50_ms'))} | {fmt(item.get('p95_ms'))} | {item.get('error_rate', 0):.2%} |")
    if report.get("read_during_write"):
        lines += ["", "Read-during-write: " + json.dumps(report["read_during_write"], ensure_ascii=False, sort_keys=True)]
    lines += ["", "## Recommendation", "", "```json", json.dumps(report.get("production_recommendation", {}), ensure_ascii=False, indent=2, sort_keys=True), "```", "", "## Gate", "", "```json", json.dumps(report.get("gate", {}), ensure_ascii=False, indent=2, sort_keys=True), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_projection(report: Mapping[str, Any], metric: str) -> dict[str, Any] | None:
    points = [item for item in report["milestones"] if item.get(metric) is not None]
    return empirical_projection(points, FULL_DATASET_DOCUMENTS, metric=metric) if len(points) >= 2 else None


def run_experiment(args: argparse.Namespace) -> int:
    if not os.getenv("TYPESENSE_API_KEY"):
        raise RuntimeError("TYPESENSE_API_KEY must be set for disposable Typesense")
    generation = args.generation
    enforce_sample_maximum(0, args.maximum_documents)
    plan = deterministic_sample_plan(
        source_quotas=SOURCE_QUOTAS,
        target_documents=args.target_documents,
        maximum_documents=args.maximum_documents,
    )
    typesense_config = TypesenseConfig.from_env()
    if typesense_config.batch_size != 500:
        raise RuntimeError(f"sizing run requires existing default Typesense batch size 500, got {typesense_config.batch_size}")
    typesense_client = TypesenseClient(typesense_config)
    _wait_for_health(typesense_client, timeout_seconds=180.0)
    manager = TypesenseCollectionManager(typesense_client)
    manager.create_generation(generation)
    # No activate_generation call by design.

    report: dict[str, Any] = {
        "report_version": "typesense-sizing-report-v1",
        "status": "RUNNING",
        "typesense_version": "30.2",
        "runtime": {"container": container_name if (container_name := args.container_name) else None, "settle_seconds": args.settle_seconds},
        "sample_plan": plan,
        "generation": generation,
        "checkpoint_path": str(args.checkpoint),
        "uuid_audit_path": str(args.uuid_audit),
        "milestones": [],
        "restart_measurement": None,
        "partitions": [],
        "failed_partitions": [],
        "skipped_partitions": [],
        "source_sample_counts": {key: 0 for key in SOURCE_CONTRACTS},
        "source_sample_dates": {key: [] for key in SOURCE_CONTRACTS},
        "search_benchmarks": [],
        "concurrency": [],
        "read_during_write": None,
        "measurement_notes": {
            "typesense_metrics": "Raw numeric /metrics.json values retained when endpoint exposes them; null means unavailable.",
            "os_metrics": "Linux /proc, du, and df measured inside disposable Typesense container.",
            "ram_projection_metric": "dataset_process_rss_bytes, OS process RSS delta from 0-document baseline.",
            "disk_projection_metric": "dataset_data_directory_bytes, /data du delta from 0-document baseline.",
            "field_contribution_sample": "first 25,000 real canonical documents per logical group; document and indexed-byte totals cover full sample.",
            "sample_count_probe_delay_seconds": args.probe_delay,
        },
    }

    with CheckpointStore(args.checkpoint) as checkpoints, UUIDProvenanceStore(args.uuid_audit) as uuid_store:
        production_sink = TypesenseSink(typesense_client, generation, batch_size=500)
        observing_sink = SizingObservingSink(production_sink)
        audited_sink = AuditedSink(observing_sink, uuid_store)
        ingestion_client = MSCClient(MSCConfig(
                request_delay_seconds=args.request_delay,
                timeout_seconds=args.msc_timeout,
                max_retries=args.max_retries,
                page_size=1000,
            ))
        sample_count_client = MSCClient(MSCConfig(
                request_delay_seconds=args.probe_delay,
                timeout_seconds=args.msc_timeout,
                max_retries=args.max_retries,
                page_size=1000,
            ))
        engine = MSCIngestionEngine(
            ingestion_client,
            checkpoints,
            audited_sink,
        )
        baseline = _measurement(typesense_client, generation, args.container_name, "baseline_0", settle_seconds=args.settle_seconds)
        baseline["dataset_process_rss_bytes"] = 0
        baseline["dataset_data_directory_bytes"] = 0
        baseline["dataset_typesense_memory_allocated_bytes"] = 0 if baseline["typesense"]["memory_allocated_bytes"] is not None else None
        baseline["dataset_typesense_memory_active_bytes"] = 0 if baseline["typesense"]["memory_active_bytes"] is not None else None
        report["milestones"].append(baseline)
        write_report(args.output, report)

        selected = set()
        source_counts: dict[str, int] = defaultdict(int)
        date_candidates = []
        dates_by_year = plan["date_selection"]["dates_by_year"]
        for position in range(max(len(values) for values in dates_by_year.values())):
            for year in ("2023", "2024", "2025", "2026"):
                if position < len(dates_by_year[year]):
                    date_candidates.append((year, dates_by_year[year][position]))
        milestones = ((50_000, "50k"), (100_000, "100k"), (250_000, "250k"), (500_000, "500k"))
        search_milestones = {"100k", "250k"}
        read_write_done = False
        stop = False
        for source_key in SOURCE_CONTRACTS:
            for year, partition_date in date_candidates:
                if stop or source_counts[source_key] >= SOURCE_QUOTAS[source_key]:
                    break
                identity = (source_key, partition_date)
                if identity in selected:
                    continue
                selected.add(identity)
                interval = official_day_interval(partition_date)
                try:
                    predicted = sample_count_client.count_interval(get_contract(source_key), interval)
                except Exception as exc:
                    report["failed_partitions"].append({"source_key": source_key, "partition_date": partition_date, "stage": "sample_count", "error": f"{type(exc).__name__}: {exc}"})
                    stop = True
                    break
                if predicted <= 0:
                    continue
                current = sum(report["source_sample_counts"].values())
                if current + predicted > args.maximum_documents:
                    report["skipped_partitions"].append({"source_key": source_key, "partition_date": partition_date, "stage": "sample_maximum_guard", "predicted_documents": predicted})
                    continue
                try:
                    if not read_write_done and current >= SIZING_SAMPLE_MINIMUM:
                        read_write_probe, result = _read_during_write(engine, typesense_config, generation, source_key, partition_date)
                        report["read_during_write"] = read_write_probe
                        read_write_done = True
                    else:
                        result = None
                    if result is None:
                        result = engine.ingest_partition(source_key, partition_date)
                except Exception as exc:
                    report["failed_partitions"].append({"source_key": source_key, "partition_date": partition_date, "stage": "ingest", "error": f"{type(exc).__name__}: {exc}"})
                    stop = True
                    break
                result_dict = _result_dict(result)
                report["partitions"].append(result_dict)
                report["source_sample_counts"][source_key] += result.normalized_count
                report["source_sample_dates"][source_key].append(partition_date)
                source_counts[source_key] += result.normalized_count
                if result.status != IngestionStatus.COMPLETED or result.sink_accepted_count != result.normalized_count:
                    report["failed_partitions"].append({"source_key": source_key, "partition_date": partition_date, "stage": "invariant", "result": result_dict})
                    stop = True
                    break
                total = sum(report["source_sample_counts"].values())
                enforce_sample_maximum(total, args.maximum_documents)
                for threshold, label in milestones:
                    if label not in {m["label"] for m in report["milestones"]} and total >= threshold:
                        measurement = _measurement(typesense_client, generation, args.container_name, label, settle_seconds=args.settle_seconds, baseline=baseline)
                        report["milestones"].append(measurement)
                        if label in search_milestones:
                            report["search_benchmarks"].append(_run_search_benchmark(typesense_client, generation, label))
                        write_report(args.output, report)
                if total >= args.target_documents and all(report["source_sample_counts"][key] > 0 for key in SOURCE_CONTRACTS):
                    stop = True
                    break
            if stop:
                break

        largest = sum(report["source_sample_counts"].values())
        if largest >= SIZING_SAMPLE_MINIMUM and largest > 0:
            if not any(item["label"] == "largest_sample" for item in report["milestones"]):
                report["milestones"].append(_measurement(typesense_client, generation, args.container_name, "largest_sample", settle_seconds=args.settle_seconds, baseline=baseline))
            expected_counts = report["milestones"][-1]["collection_document_counts"]
            report["restart_measurement"] = _restart_and_measure(typesense_client, generation, args.container_name, args.settle_seconds, baseline, expected_counts)
            report["search_benchmarks"].append(_run_search_benchmark(typesense_client, generation, "largest_sample_restart"))
            report["concurrency"] = _run_concurrency_probe(typesense_config, generation)
        report["final_collection_counts"] = {
            group: typesense_client.document_count(physical_collection_name(group, generation))
            for group in SEARCH_CONFIGS
        }
        report["uuid_audit"] = {
            "expected_sampled_uuid_union": uuid_store.total_count(),
            "conflict_count": uuid_store.conflict_count(),
            "group_counts": uuid_store.group_counts(),
        }
        report["parity"] = {
            "expected_sampled_uuid_union": uuid_store.total_count(),
            "actual_typesense_total": sum(report["final_collection_counts"].values()),
            "groups": {
                group: {"expected": uuid_store.group_counts().get(group, 0), "actual": count, "pass": uuid_store.group_counts().get(group, 0) == count}
                for group, count in report["final_collection_counts"].items()
            },
        }
        report["import"] = {
            "batch_size": 500,
            "cumulative_batches": sum(item.get("sink_batch_count", 0) for item in report["partitions"]),
            "cumulative_attempted": sum(item.get("sink_attempted_count", 0) for item in report["partitions"]),
            "cumulative_accepted": sum(item.get("sink_accepted_count", 0) for item in report["partitions"]),
            "cumulative_rejected": sum(max(item.get("normalized_count", 0) - item.get("sink_accepted_count", 0), 0) for item in report["partitions"]),
            "cumulative_import_elapsed_seconds": round(sum(item.get("sink_elapsed_seconds", 0.0) for item in report["partitions"]), 3),
            "msc_requests": engine.client.stats.request_count,
            "msc_retries": engine.client.stats.retry_count,
            "msc_http_errors": engine.client.stats.http_error_count,
        }
        report["canonical_bytes"] = {
            "sample_total": observing_sink.canonical_bytes,
            "average_per_document": observing_sink.canonical_bytes / largest if largest else None,
        }
        report["field_size_contributions"] = observing_sink.field_report()
        report["projections"] = {}
        for metric in ("dataset_process_rss_bytes", "dataset_data_directory_bytes", "dataset_typesense_memory_active_bytes", "dataset_typesense_memory_allocated_bytes"):
            projection = _build_projection(report, metric)
            if projection:
                report["projections"][metric] = projection
        ram_projection = report["projections"].get("dataset_process_rss_bytes") or report["projections"].get("dataset_typesense_memory_active_bytes")
        disk_projection = report["projections"].get("dataset_data_directory_bytes")
        report["analytical_comparison"] = {
            "indexed_input_bytes_per_document": observing_sink.indexed_bytes / largest if largest else None,
            "projected_indexed_input_bytes": round(observing_sink.indexed_bytes / largest * FULL_DATASET_DOCUMENTS) if largest else None,
            "keyword_search_ram_2x_bytes": round(observing_sink.indexed_bytes / largest * FULL_DATASET_DOCUMENTS * 2) if largest else None,
            "keyword_search_ram_3x_bytes": round(observing_sink.indexed_bytes / largest * FULL_DATASET_DOCUMENTS * 3) if largest else None,
            "note": "Analytical comparison uses actual sampled canonical documents and frozen indexed/searchable field classification.",
        }
        if ram_projection and disk_projection:
            ram_largest_slope = ram_projection["largest_sample"]["bytes_per_document"]
            disk_largest_slope = disk_projection["largest_sample"]["bytes_per_document"]
            ram_full = ram_projection["largest_sample"]["projected_bytes"]
            disk_full = disk_projection["largest_sample"]["projected_bytes"]
            report["growth_scenarios"] = growth_scenarios(FULL_DATASET_DOCUMENTS, ram_largest_slope, disk_largest_slope)
            report["capacity_decision"] = capacity_decision(ram_full)
            report["disk_capacity"] = {
                "single_generation_projected_bytes": disk_full,
                "two_generation_bytes": disk_full * 2,
                "active_staging_rollback_snapshot_free_margin_bytes": round(disk_full * 3.5),
                "recommended_minimum_ssd_gb_per_node": max(200, math.ceil(disk_full * 3.5 / 100_000_000_000) * 100),
                "thresholds": {"do_not_create_new_generation_below_free_fraction": 0.50, "warning_free_fraction": 0.35, "critical_free_fraction": 0.20},
                "note": "Reserve active, staging, rollback, snapshot/free-space margin; never auto-delete rollback generation.",
            }
        else:
            report["growth_scenarios"] = []
            report["capacity_decision"] = None
            report["disk_capacity"] = None
        report["backfill_projection"] = {
            "full_dataset_documents": FULL_DATASET_DOCUMENTS,
            "observed_active_ingestion_documents": largest,
            "observed_msc_engine_requests": sum(item.get("request_count", 0) for item in report["partitions"]),
            "estimated_msc_requests_full_dataset": round(sum(item.get("request_count", 0) for item in report["partitions"]) / largest * FULL_DATASET_DOCUMENTS) if largest else None,
            "estimated_typesense_batches_full_dataset": math.ceil(FULL_DATASET_DOCUMENTS / 500),
            "observed_typesense_batches": report["import"]["cumulative_batches"],
            "observed_typesense_import_documents_per_second": round(largest / report["import"]["cumulative_import_elapsed_seconds"], 3) if report["import"]["cumulative_import_elapsed_seconds"] else None,
            "unavoidable_msc_request_pacing_seconds_at_one_second_delay": round(sum(item.get("request_count", 0) for item in report["partitions"]) / largest * FULL_DATASET_DOCUMENTS) if largest else None,
            "time_statement": "Order-of-magnitude only; excludes operational pauses, retries, and external MSC availability.",
            "recommendation": {"msc_request_delay_seconds": args.request_delay, "typesense_batch_size": 500, "additional_write_throttle": "add only if read-during-write p95 materially degrades or production backfill monitoring shows pressure"},
        }
        capacity = report.get("capacity_decision") or {}
        concurrency = report.get("concurrency") or []
        one_p95 = concurrency[0].get("p95_ms") if concurrency else None
        high_p95 = concurrency[-1].get("p95_ms") if concurrency else None
        recommended_vcpus = 8 if one_p95 is None or high_p95 is None or high_p95 > one_p95 * 2 else 4
        recommended_ram = 32 if capacity.get("approved") else "next available tier above 32"
        report["production_recommendation"] = {
            "cloud": {"preferred": "Typesense Cloud HA", "nodes": 3, "ram_gb_per_node": recommended_ram, "vcpus_per_node": recommended_vcpus, "disk": "provider allocation meeting disk_capacity minimum plus backup policy"},
            "self_hosted": {"typesense_version": "30.2", "nodes": 3, "ram_gb_per_node": recommended_ram, "vcpus_per_node": recommended_vcpus, "ssd": "at least disk_capacity recommended minimum per node"},
            "reasoning": "HA replacement, upgrades, backups, and reduced operations favor Typesense Cloud; self-hosted remains valid for cost/control.",
        }
        report["monitoring_thresholds"] = {
            "ram_warning": "sustained >70% of node RAM or empirical full-dataset headroom consumed",
            "ram_critical": "sustained >80%; scale before 90%",
            "disk_warning": "free <35%",
            "disk_critical": "free <20%; block new generation creation",
            "typesense_import_rejection": "any rejected document pages operator immediately; zero is required for PASS",
            "crawler_retry_rate": "warning >5% over bounded window; investigate before continuing",
            "search_latency": "warning when p95 doubles versus warm baseline; critical when sustained and errors appear",
        }
        source_ok = all(report["source_sample_counts"].get(key, 0) > 0 for key in SOURCE_CONTRACTS)
        year_ok = all(any(item["partition_date"].startswith(str(year)) for item in report["partitions"]) for year in (2023, 2024, 2025, 2026))
        measurement_ok = len(report["milestones"]) >= 4
        restart_ok = report["restart_measurement"] is not None and report["parity"]["actual_typesense_total"] == report["parity"]["expected_sampled_uuid_union"]
        no_rejects = report["import"]["cumulative_rejected"] == 0 and report["import"]["cumulative_accepted"] == largest
        report["gate"] = {
            "sample_minimum": largest >= SIZING_SAMPLE_MINIMUM,
            "preferred_target": largest >= SIZING_SAMPLE_TARGET,
            "all_seven_sources": source_ok,
            "multi_year": year_ok,
            "milestones": measurement_ok,
            "restart": restart_ok,
            "count_parity": report["parity"]["actual_typesense_total"] == largest and all(item["pass"] for item in report["parity"]["groups"].values()),
            "no_failed_partitions": not report["failed_partitions"],
            "zero_rejected": no_rejects,
            "bounded_search": bool(report["search_benchmarks"]),
            "concurrency": bool(report["concurrency"]),
            "projection": bool(ram_projection and disk_projection),
            "no_full_backfill": True,
            "no_alias_activation": True,
        }
        report["status"] = "PASS" if all(report["gate"].values()) else "PARTIAL"
        report["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_report(args.output, report)
        _write_markdown(report, args.markdown_output)

    print(json.dumps({"status": report["status"], "sample_documents": largest, "report": str(args.output), "generation": generation}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--generation", default=DEFAULT_GENERATION)
    parser.add_argument("--output", type=Path, default=ROOT / "typesense-sizing-report.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "typesense-sizing-report.md")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "crawler_engine" / ".msc_state" / "sizing-checkpoints.sqlite3")
    parser.add_argument("--uuid-audit", type=Path, default=ROOT / "crawler_engine" / ".msc_state" / "sizing-uuid-audit.sqlite3")
    parser.add_argument("--target-documents", type=int, default=SIZING_SAMPLE_TARGET)
    parser.add_argument("--maximum-documents", type=int, default=SIZING_SAMPLE_MAXIMUM)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--probe-delay", type=float, default=0.5)
    parser.add_argument("--msc-timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser


if __name__ == "__main__":
    raise SystemExit(run_experiment(build_parser().parse_args()))
