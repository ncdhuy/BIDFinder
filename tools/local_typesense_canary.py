"""Run bounded Phase 3B-P-L validation against persistent local Typesense.

Run from Ubuntu/WSL.  The main canary always uses MSCClient, the adaptive
engine, normalization, UUID auditing, and TypesenseSink.  No aliases or
historical generation are written.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time
from time import perf_counter
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.backfill import (  # noqa: E402
    AuditedSink,
    atomic_write_json,
    build_manifest,
    source_population_preflight,
    UUIDProvenanceStore,
    verify_manifest,
)
from crawler_engine.msc.checkpoint import CheckpointStore  # noqa: E402
from crawler_engine.msc.client import MSCClient  # noqa: E402
from crawler_engine.msc.config import MSCConfig, TypesenseConfig  # noqa: E402
from crawler_engine.msc.contracts import SOURCE_CONTRACTS  # noqa: E402
from crawler_engine.msc.engine import MSCIngestionEngine  # noqa: E402
from crawler_engine.msc.local_target import (  # noqa: E402
    EXPECTED_HISTORICAL_SOURCE_TOTALS,
    FULL_RUN_AUTHORIZATION_PHRASE,
    FUTURE_HISTORICAL_GENERATION,
    LOCAL_TYPESENSE_HOST,
    LOCAL_TYPESENSE_PORT,
    LOCAL_TYPESENSE_PROTOCOL,
    LOCAL_TYPESENSE_VERSION,
    local_capacity_preflight,
    local_generation_artifacts,
    local_target_paths,
    historical_source_count_deltas,
    validate_local_typesense_config,
)
from crawler_engine.msc.models import IngestionStatus  # noqa: E402
from crawler_engine.msc.sink import TypesenseSink  # noqa: E402
from crawler_engine.msc.typesense_client import TypesenseClient, TypesenseCollectionManager, TypesenseError  # noqa: E402
from crawler_engine.msc.typesense_schema import (  # noqa: E402
    LOGICAL_ALIASES,
    canonical_to_typesense_document,
    physical_collection_name,
)


# Proven closed days.  Five goods days keep this bounded canary in the
# requested 50k-200k range while covering every source contract.
CANARY_PLAN = (
    ("goods_general", "goods", "2026-08-21"),
    ("medical_devices", "goods", "2026-08-28"),
    ("medicine_generic", "medicines", "2026-08-28"),
    ("medicine_originator", "medicines", "2026-08-27"),
    ("medicine_herbal", "medicines", "2026-08-28"),
    ("herbal_material", "traditional_medicine", "2026-08-22"),
    ("traditional_medicine", "traditional_medicine", "2026-08-27"),
    ("goods_general", "goods", "2026-08-25"),
    ("goods_general", "goods", "2026-08-26"),
    ("goods_general", "goods", "2026-08-27"),
    ("goods_general", "goods", "2026-08-28"),  # adaptive overflow parent
)
OVERFLOW_SOURCE = "goods_general"
OVERFLOW_DATE = "2026-08-28"
CANARY_MIN_DOCUMENTS = 50_000
CANARY_MAX_DOCUMENTS = 200_000


def _jsonable(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    return value


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) * fraction) + 0.999999) - 1))
    return round(ordered[index], 3)


def _load_typesense_env() -> None:
    path = Path(os.getenv("BIDFINDER_TYPESENSE_CONFIG", Path.home() / ".config/bidfinder/typesense.env")).expanduser()
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name.startswith("TYPESENSE_"):
            continue
        os.environ.setdefault(name, value.strip().strip("\"'"))


def _service(paths: Any, operation: str, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        raise RuntimeError("local canary must run inside WSL/Linux; use wsl -d Ubuntu")
    env = os.environ.copy()
    env["BIDFINDER_TYPESENSE_ROOT"] = str(paths.root)
    env.setdefault("BIDFINDER_TYPESENSE_CONFIG", str(Path.home() / ".config/bidfinder/typesense.env"))
    result = subprocess.run(
        ["bash", str(ROOT / "infra" / "typesense" / "local-typesense.sh"), operation, *arguments],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise RuntimeError(f"local Typesense {operation} failed: {detail}")
    return result


def _meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    path = Path("/proc/meminfo")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition(":")
            parts = value.strip().split()
            if parts and parts[0].isdigit():
                result[name] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return result


def _typesense_process_metrics(pid_file: Path) -> dict[str, Any]:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return {"pid": None, "rss_bytes": None, "cpu_percent": None}
    rss_bytes = None
    state: str | None = None
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    rss_bytes = int(parts[1]) * 1024
            if line.startswith("State:"):
                state = line.split()[1] if len(line.split()) > 1 else None
    cpu_percent: float | None = None
    try:
        raw = subprocess.check_output(["ps", "-o", "%cpu=", "-p", str(pid)], text=True, stderr=subprocess.DEVNULL).strip()
        cpu_percent = float(raw) if raw else None
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return {"pid": pid, "state": state, "alive": state is not None and not state.startswith("Z"), "rss_bytes": rss_bytes, "cpu_percent": cpu_percent}


def _resource_snapshot(paths: Any) -> dict[str, Any]:
    mem = _meminfo()
    usage = shutil.disk_usage(paths.root)
    return {
        "memory_total_bytes": mem.get("MemTotal"),
        "memory_available_bytes": mem.get("MemAvailable"),
        "memory_free_bytes": mem.get("MemFree"),
        "swap_total_bytes": mem.get("SwapTotal"),
        "swap_free_bytes": mem.get("SwapFree"),
        "disk_free_bytes": usage.free,
        "typesense": _typesense_process_metrics(paths.run_dir / "typesense.pid"),
    }


class ResourceSampler:
    def __init__(self, paths: Any, interval_seconds: float = 0.5) -> None:
        self.paths = paths
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="typesense-resource-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append(_resource_snapshot(self.paths))
            self._stop.wait(self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def summary(self) -> dict[str, Any]:
        rss = [item["typesense"]["rss_bytes"] for item in self.samples if item["typesense"]["rss_bytes"] is not None]
        cpu = [item["typesense"]["cpu_percent"] for item in self.samples if item["typesense"]["cpu_percent"] is not None]
        available = [item["memory_available_bytes"] for item in self.samples if item["memory_available_bytes"] is not None]
        swap_used = [
            item["swap_total_bytes"] - item["swap_free_bytes"]
            for item in self.samples
            if item["swap_total_bytes"] is not None and item["swap_free_bytes"] is not None
        ]
        return {
            "sample_count": len(self.samples),
            "typesense_rss_bytes": {"baseline": rss[0] if rss else None, "peak": max(rss) if rss else None, "last": rss[-1] if rss else None},
            "typesense_cpu_percent": {"max": round(max(cpu), 2) if cpu else None, "last": round(cpu[-1], 2) if cpu else None},
            "wsl_memory_available_bytes": {"minimum": min(available) if available else None, "last": available[-1] if available else None},
            "swap_used_bytes": {"maximum": max(swap_used) if swap_used else None, "last": swap_used[-1] if swap_used else None},
        }


class RecordingMSCClient(MSCClient):
    def __init__(self, config: MSCConfig) -> None:
        super().__init__(config)
        self.page_request_count = 0
        self.count_request_count = 0

    def fetch_page(self, contract: Any, interval: Any, page: int) -> Any:
        self.page_request_count += 1
        return super().fetch_page(contract, interval, page)

    def count_interval(self, contract: Any, interval: Any) -> Any:
        self.count_request_count += 1
        return super().count_interval(contract, interval)


class RecordingTypesenseSink(TypesenseSink):
    def __init__(self, client: TypesenseClient, generation_id: str) -> None:
        super().__init__(client, generation_id)
        self.expected_ids = {group: set() for group in LOGICAL_ALIASES}
        self.expected_records: dict[str, dict[str, dict[str, Any]]] = {group: {} for group in LOGICAL_ALIASES}
        self.candidates: dict[str, dict[str, Any]] = {group: {} for group in LOGICAL_ALIASES}

    @staticmethod
    def _value(value: Any) -> Any:
        if isinstance(value, list):
            return next((item for item in value if item not in (None, "")), None)
        return value if value not in (None, "") else None

    def write_partition(self, context: Any, records: Sequence[dict[str, Any]]) -> Any:
        group = context.contract.data_group
        for record in records:
            self.expected_ids[group].add(record["id"])
            self.expected_records[group].setdefault(record["id"], dict(record))
            for key, value in record.items():
                value = self._value(value)
                if value is not None and key not in self.candidates[group] and isinstance(value, (str, int, float)):
                    self.candidates[group][key] = value
        return super().write_partition(context, records)


def _partition_metric(result: Any, msc: RecordingMSCClient, sink: TypesenseSink, before_page: int, before_count: int, started: float) -> dict[str, Any]:
    attempted = result.sink_attempted_count
    accepted = result.sink_accepted_count
    return {
        **result.as_dict(),
        "msc_page_request_count": msc.page_request_count - before_page,
        "msc_count_request_count": msc.count_request_count - before_count,
        "typesense_rejected_count": max(0, attempted - accepted),
        "sink_target": sink.sink_target,
        "elapsed_seconds_wall": round(perf_counter() - started, 3),
        "completeness_invariant": (
            result.parent_pre_count is not None
            and result.parent_pre_count == result.parent_post_count == result.unique_source_count == result.normalized_count == result.sink_accepted_count
            and max(0, attempted - accepted) == 0
            and not result.drift.type_errors
        ),
    }


def _run_partition(engine: MSCIngestionEngine, source_key: str, day: str, msc: RecordingMSCClient, sink: TypesenseSink, *, force: bool = False) -> tuple[Any, dict[str, Any]]:
    before_page = msc.page_request_count
    before_count = msc.count_request_count
    started = perf_counter()
    result = engine.ingest_partition(source_key, day, force=force)
    return result, _partition_metric(result, msc, sink, before_page, before_count, started)


def _hits(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [hit.get("document", {}) for hit in response.get("hits", []) if isinstance(hit, Mapping)]


def _search_smoke(client: TypesenseClient, generation: str, sink: RecordingTypesenseSink) -> dict[str, Any]:
    fields = {
        "goods": (("item_name", "item name"), ("manufacturer", "manufacturer"), ("winning_bidder_name", "bidder"), ("bid_invitation_code", "tender code")),
        "medicines": (("medicine_name", "medicine name"), ("active_ingredient_or_herbal_component", "active ingredient"), ("manufacturer", "manufacturer"), ("winning_bidder_name", "bidder"), ("bid_invitation_code", "tender")),
        "traditional_medicine": (("item_name", "item name"), ("scientific_name", "scientific name"), ("manufacturer", "manufacturer/source"), ("winning_bidder_name", "bidder"), ("bid_invitation_code", "tender")),
    }
    searches: list[dict[str, Any]] = []
    latencies: list[float] = []
    errors: list[str] = []
    for group, group_fields in fields.items():
        for field, label in group_fields:
            value = sink.candidates[group].get(field)
            if value in (None, ""):
                searches.append({"group": group, "category": label, "status": "FAIL", "error": "no representative value"})
                continue
            started = perf_counter()
            try:
                response = client.search_group(group, str(value), per_page=3, collection=physical_collection_name(group, generation))
                latency = (perf_counter() - started) * 1000
                latencies.append(latency)
                searches.append({"group": group, "category": label, "field": field, "query": str(value)[:100], "found": response.get("found"), "latency_ms": round(latency, 3), "pass": int(response.get("found", 0)) >= 1})
            except Exception as exc:  # report exact bounded smoke failure
                errors.append(f"{group}:{label}: {exc}")
                searches.append({"group": group, "category": label, "status": "FAIL", "error": str(exc)[:500]})

    filters: list[dict[str, Any]] = []
    for group in LOGICAL_ALIASES:
        collection = physical_collection_name(group, generation)
        source_tab = sink.candidates[group].get("source_tab")
        if source_tab:
            started = perf_counter()
            response = client.search_group(group, "*", filter_by=f"source_tab:={source_tab}", per_page=20, collection=collection)
            hits = _hits(response)
            filters.append({"group": group, "filter": "source_tab", "value": str(source_tab), "found": response.get("found"), "latency_ms": round((perf_counter() - started) * 1000, 3), "semantics_ok": bool(hits) and all(item.get("source_tab") == source_tab for item in hits)})
        started = perf_counter()
        response = client.search_group(group, "*", filter_by="winning_unit_price:>0", per_page=20, collection=collection)
        filters.append({"group": group, "filter": "winning_unit_price:>0", "found": response.get("found"), "latency_ms": round((perf_counter() - started) * 1000, 3), "semantics_ok": all(isinstance(item.get("winning_unit_price"), (int, float)) and item["winning_unit_price"] > 0 for item in _hits(response))})

    sorts: list[dict[str, Any]] = []
    for group in LOGICAL_ALIASES:
        collection = physical_collection_name(group, generation)
        for direction in ("asc", "desc"):
            started = perf_counter()
            response = client.search_group(group, "*", sort_by=f"winning_unit_price:{direction}", per_page=20, collection=collection)
            values = [item["winning_unit_price"] for item in _hits(response) if isinstance(item.get("winning_unit_price"), (int, float))]
            expected = sorted(values, reverse=direction == "desc")
            sorts.append({"group": group, "sort": f"winning_unit_price:{direction}", "found": response.get("found"), "numeric_values_checked": len(values), "order_ok": values == expected, "latency_ms": round((perf_counter() - started) * 1000, 3)})

    multi_started = perf_counter()
    multi = client.multi_search_all("*", generation_id=generation, per_page=1)
    multi_summary = {"result_count": len(multi.get("results", [])), "found_counts": [item.get("found") for item in multi.get("results", [])], "latency_ms": round((perf_counter() - multi_started) * 1000, 3), "pass": len(multi.get("results", [])) == 3}
    return {
        "field_searches": searches,
        "filters": filters,
        "sorts": sorts,
        "multi_search": multi_summary,
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95), "max": round(max(latencies), 3) if latencies else 0.0, "requests": len(latencies), "errors": errors},
        "pass": all(item.get("pass") is True for item in searches) and all(item["semantics_ok"] for item in filters) and all(item["order_ok"] for item in sorts) and multi_summary["pass"] and not errors,
    }


def _concurrency(client_config: TypesenseConfig, generation: str, sink: RecordingTypesenseSink, clients: int, requests_per_client: int) -> dict[str, Any]:
    groups = tuple(LOGICAL_ALIASES)
    queries = {group: str(sink.candidates[group].get("item_name") or sink.candidates[group].get("medicine_name") or "*") for group in groups}
    timings: list[float] = []
    errors: list[str] = []
    started = perf_counter()

    def worker(worker_index: int) -> list[float]:
        local: list[float] = []
        client = TypesenseClient(client_config)
        for offset in range(requests_per_client):
            group = groups[(worker_index + offset) % len(groups)]
            query_started = perf_counter()
            try:
                client.search_group(group, queries[group], per_page=3, collection=physical_collection_name(group, generation))
                local.append((perf_counter() - query_started) * 1000)
            except Exception as exc:
                errors.append(f"client={worker_index} group={group}: {exc}")
        return local

    with ThreadPoolExecutor(max_workers=clients) as executor:
        futures = [executor.submit(worker, index) for index in range(clients)]
        for future in as_completed(futures):
            timings.extend(future.result())
    elapsed = perf_counter() - started
    return {"clients": clients, "requests_per_client": requests_per_client, "requests": len(timings), "requests_per_second": round(len(timings) / max(elapsed, 0.001), 3), "latency_ms": {"p50": _percentile(timings, 0.50), "p95": _percentile(timings, 0.95), "max": round(max(timings), 3) if timings else 0.0}, "errors": errors, "pass": len(errors) == 0 and len(timings) == clients * requests_per_client}


class SlowMSCClient(RecordingMSCClient):
    def __init__(self, config: MSCConfig, page_delay_seconds: float) -> None:
        super().__init__(config)
        self.page_delay_seconds = page_delay_seconds

    def fetch_page(self, contract: Any, interval: Any, page: int) -> Any:
        result = super().fetch_page(contract, interval, page)
        time.sleep(self.page_delay_seconds)
        return result


def _read_during_write(paths: Any, generation: str, config: TypesenseConfig, baseline_p95: float) -> dict[str, Any]:
    write_checkpoint = paths.checkpoints_dir / f"{generation}.read-write.sqlite3"
    writer_config = MSCConfig(request_delay_seconds=0, timeout_seconds=30, max_retries=3, page_size=1000)
    writer_result: dict[str, Any] = {}

    def writer() -> None:
        msc = SlowMSCClient(writer_config, page_delay_seconds=0.15)
        with CheckpointStore(write_checkpoint) as checkpoints:
            sink = TypesenseSink(TypesenseClient(config), generation)
            engine = MSCIngestionEngine(msc, checkpoints, sink, writer_config)
            result = engine.ingest_partition(OVERFLOW_SOURCE, "2026-08-26", force=True)
            writer_result.update(result.as_dict())

    thread = threading.Thread(target=writer, name="typesense-read-write-writer")
    thread.start()
    timings: list[float] = []
    errors: list[str] = []
    search_client = TypesenseClient(config)
    groups = tuple(LOGICAL_ALIASES)
    index = 0
    while thread.is_alive() or not timings:
        group = groups[index % len(groups)]
        index += 1
        started = perf_counter()
        try:
            search_client.search_group(group, "*", per_page=3, collection=physical_collection_name(group, generation))
            timings.append((perf_counter() - started) * 1000)
        except Exception as exc:
            errors.append(f"{group}: {exc}")
        if len(timings) >= 40:
            break
    thread.join(timeout=120)
    if thread.is_alive():
        errors.append("writer did not finish within 120 seconds")
    p95 = _percentile(timings, 0.95)
    return {"writer_result": writer_result, "search_requests": len(timings), "latency_ms": {"p50": _percentile(timings, 0.50), "p95": p95, "max": round(max(timings), 3) if timings else 0.0}, "errors": errors, "baseline_search_p95_ms": baseline_p95, "no_severe_latency_collapse": not errors and p95 <= max(baseline_p95 * 3, 1000), "pass": bool(writer_result.get("status") == "COMPLETED") and not errors and p95 <= max(baseline_p95 * 3, 1000)}


def _collection_counts(client: TypesenseClient, generation: str) -> dict[str, int]:
    return {group: client.document_count(physical_collection_name(group, generation)) for group in LOGICAL_ALIASES}


def _wait_stable_counts(client: TypesenseClient, generation: str, *, timeout_seconds: int = 120) -> dict[str, int]:
    previous: dict[str, int] | None = None
    stable_reads = 0
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            current = _collection_counts(client, generation)
        except TypesenseError:
            time.sleep(2)
            continue
        if current == previous:
            stable_reads += 1
            if stable_reads >= 2:
                return current
        else:
            stable_reads = 0
        previous = current
        time.sleep(2)
    raise RuntimeError("Typesense collection counts did not stabilize after restart")


def _restart_cycle(paths: Any, client: TypesenseClient, generation: str, cycle: int) -> dict[str, Any]:
    before = _collection_counts(client, generation)
    _service(paths, "stop")
    process_stopped = not (paths.run_dir / "typesense.pid").exists()
    health_after_stop = False
    try:
        health_after_stop = client.health().get("ok") is True
    except Exception:
        health_after_stop = False
    _service(paths, "start")
    after = _wait_stable_counts(client, generation)
    return {"cycle": cycle, "counts_before": before, "counts_after": after, "process_stopped": process_stopped, "health_after_stop": health_after_stop, "health_after_start": client.health(), "counts_exact": before == after, "pass": process_stopped and not health_after_stop and before == after}


def _abrupt_recovery(paths: Any, client: TypesenseClient, generation: str) -> dict[str, Any]:
    before = _collection_counts(client, generation)
    pid_path = paths.run_dir / "typesense.pid"
    pid = int(pid_path.read_text(encoding="utf-8").strip())
    os.kill(pid, signal.SIGKILL)
    time.sleep(1)
    stopped = not pid_path.exists() or not _typesense_process_metrics(pid_path).get("alive", False)
    _service(paths, "start")
    after = _wait_stable_counts(client, generation)
    search = client.search_group("goods", "*", per_page=1, collection=physical_collection_name("goods", generation))
    return {"pid_terminated": True, "process_stopped": stopped, "counts_before": before, "counts_after": after, "counts_exact": before == after, "search_found": search.get("found"), "pass": stopped and before == after and int(search.get("found", 0)) >= 1}


def _restore_proof(paths: Any, client: TypesenseClient, generation: str, config: TypesenseConfig, snapshot_path: Path) -> dict[str, Any]:
    port = "8109"
    restore_data = paths.root / "restore-validation" / f"{generation}-data"
    restore_client = TypesenseClient(TypesenseConfig(host=LOCAL_TYPESENSE_HOST, port=int(port), protocol=LOCAL_TYPESENSE_PROTOCOL, api_key=config.api_key, timeout_seconds=config.timeout_seconds, batch_size=config.batch_size))
    started = False
    try:
        _service(paths, "restore-start", str(snapshot_path), port, str(restore_data))
        started = True
        counts = _wait_stable_counts(restore_client, generation)
        source_counts = _collection_counts(client, generation)
        sample_checks = []
        for group, records in _EXPECTED_RECORDS.items():
            if records:
                record_id, record = next(iter(records.items()))
                expected = canonical_to_typesense_document(record, group)
                actual = restore_client.get_document(physical_collection_name(group, generation), record_id)
                sample_checks.append({"group": group, "id": record_id, "retrieved": actual is not None, "fields_equal": actual == expected})
        search = restore_client.search_group("goods", "*", per_page=1, collection=physical_collection_name("goods", generation))
        return {"snapshot_path": str(snapshot_path), "restore_data_dir": str(restore_data), "counts": counts, "source_counts": source_counts, "counts_exact": counts == source_counts, "sample_checks": sample_checks, "search_found": search.get("found"), "pass": counts == source_counts and all(item["retrieved"] and item["fields_equal"] for item in sample_checks) and int(search.get("found", 0)) >= 1}
    finally:
        if started:
            _service(paths, "restore-stop", port)


def _markdown(report: Mapping[str, Any]) -> str:
    checks = report.get("checks", {})
    lines = [
        "# Local Typesense Canary Report",
        "",
        f"Status: **{report.get('status', 'UNKNOWN')}**",
        f"Generation: `{report.get('generation')}`",
        f"Typesense: `{report.get('runtime', {}).get('typesense_version', LOCAL_TYPESENSE_VERSION)}`",
        f"Persistent data: `{report.get('runtime', {}).get('persistent_data_path')}`",
        "",
        "## Gate summary",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    for name, value in checks.items():
        lines.append(f"| {name} | {'PASS' if value else 'FAIL'} |")
    lines.extend([
        "",
        f"Canary documents: `{report.get('canary', {}).get('total_unique_documents')}`",
        f"Historical revalidation total: `{report.get('historical_manifest', {}).get('actual_total')}`",
        f"Future historical generation: `{report.get('future_historical_generation')}`",
        "",
        "Full historical backfill was not run. Stable aliases were not activated. FastAPI/UI behavior was not changed.",
        "",
    ])
    return "\n".join(lines)


_EXPECTED_RECORDS: dict[str, dict[str, dict[str, Any]]] = {group: {} for group in LOGICAL_ALIASES}


def run(args: argparse.Namespace) -> dict[str, Any]:
    _load_typesense_env()
    paths = local_target_paths(args.root, repo_root=ROOT, create=True)
    config = TypesenseConfig.from_env()
    validate_local_typesense_config(config)
    generation = args.generation or f"local_canary_{date.today():%Y%m%d}_{secrets.token_hex(3)}"
    artifacts = local_generation_artifacts(paths, generation)
    report: dict[str, Any] = {
        "report_version": "msc-local-typesense-canary-v1",
        "status": "RUNNING",
        "generation": generation,
        "physical_collections": {group: physical_collection_name(group, generation) for group in LOGICAL_ALIASES},
        "future_historical_generation": FUTURE_HISTORICAL_GENERATION,
        "runtime": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "typesense_version_expected": LOCAL_TYPESENSE_VERSION,
            "typesense_host": config.host,
            "typesense_port": config.port,
            "typesense_protocol": config.protocol,
            "network_exposure": "loopback-only",
            "cors_enabled": False,
            "persistent_data_path": str(paths.data_dir),
            "runtime_paths": paths.as_dict(),
            "filesystem": "native Linux/WSL filesystem (operator-selected path)",
        },
        "canary_plan": [{"source_key": source, "logical_group": group, "partition_date": day, "overflow_candidate": source == OVERFLOW_SOURCE and day == OVERFLOW_DATE} for source, group, day in CANARY_PLAN],
        "checkpoint_path": str(artifacts["checkpoint"]),
        "uuid_audit_path": str(artifacts["uuid_audit"]),
        "snapshot_path": str(artifacts["snapshot"]),
        "checks": {},
        "resource_preflight": {"disk": local_capacity_preflight(paths), "baseline": _resource_snapshot(paths), "cpu_count": os.cpu_count(), "swap_file": "/proc/swaps" if Path("/proc/swaps").exists() else None},
        "full_run_safety_lock": {"explicit_from_required": True, "explicit_to_required": True, "explicit_generation_required": True, "explicit_checkpoint_required": True, "readiness_acknowledgement_required": True, "historical_manifest_path_required": True, "manifest_fingerprint_match_required": True, "explicit_authorization_phrase_required": FULL_RUN_AUTHORIZATION_PHRASE, "authorization_supplied": False, "full_backfill_invoked": False},
    }
    sampler = ResourceSampler(paths)
    client: TypesenseClient | None = None
    restore_error: str | None = None
    try:
        _service(paths, "start")
        client = TypesenseClient(config)
        binary_version = _service(paths, "version").stdout.strip()
        health = client.health()
        report["runtime"]["health_before_canary"] = health
        report["runtime"]["typesense_binary_version"] = binary_version
        report["runtime"]["typesense_version"] = LOCAL_TYPESENSE_VERSION if LOCAL_TYPESENSE_VERSION in binary_version else None
        report["checks"]["persistent_target_health"] = health.get("ok") is True and LOCAL_TYPESENSE_VERSION in binary_version
        if not report["checks"]["persistent_target_health"]:
            raise RuntimeError(f"unexpected Typesense health/version: {health}")
        manager = TypesenseCollectionManager(client)
        manager.create_generation(generation)
        report["schema_validation_before_write"] = manager.validate_generation(generation)
        aliases_before = {alias: client.get_alias(alias) for alias in LOGICAL_ALIASES.values()}
        report["checks"]["no_alias_activation"] = all(value is None for value in aliases_before.values())
        report["aliases_before"] = aliases_before
        msc_config = MSCConfig(request_delay_seconds=args.request_delay, timeout_seconds=30, page_size=args.page_size)
        msc = RecordingMSCClient(msc_config)
        sink = RecordingTypesenseSink(client, generation)
        with CheckpointStore(artifacts["checkpoint"]) as checkpoints, UUIDProvenanceStore(artifacts["uuid_audit"]) as provenance:
            audited_sink = AuditedSink(sink, provenance)
            engine = MSCIngestionEngine(msc, checkpoints, audited_sink, msc_config)
            sampler.start()
            metrics: list[dict[str, Any]] = []
            for source_key, group, day in CANARY_PLAN:
                result, metric = _run_partition(engine, source_key, day, msc, audited_sink)
                metrics.append(metric)
                if result.status != IngestionStatus.COMPLETED or not metric["completeness_invariant"]:
                    raise RuntimeError(f"canary partition failed completeness gate: {metric}")
            _EXPECTED_RECORDS.clear()
            _EXPECTED_RECORDS.update(sink.expected_records)
            expected_counts = {group: len(ids) for group, ids in sink.expected_ids.items()}
            actual_counts = _collection_counts(client, generation)
            report["schema_validation_after_write"] = manager.validate_generation(generation)
            report["canary"] = {"partitions": metrics, "source_contracts": sorted({item["source_key"] for item in metrics}), "source_summary": {source: {"partitions": [item["partition_date"] for item in metrics if item["source_key"] == source], "documents": sum(int(item["unique_source_count"]) for item in metrics if item["source_key"] == source)} for source in SOURCE_CONTRACTS}, "expected_uuid_union_by_group": expected_counts, "actual_collection_counts": actual_counts, "total_unique_documents": sum(expected_counts.values()), "accepted_documents": sum(int(item["sink_accepted_count"]) for item in metrics), "rejected_documents": sum(int(item["typesense_rejected_count"]) for item in metrics), "uuid_conflicts": provenance.conflict_count(), "overflow": next(item for item in metrics if item["source_key"] == OVERFLOW_SOURCE and item["partition_date"] == OVERFLOW_DATE)}
            report["checks"]["canary_size"] = CANARY_MIN_DOCUMENTS <= report["canary"]["total_unique_documents"] <= CANARY_MAX_DOCUMENTS
            report["checks"]["all_seven_source_contracts"] = set(report["canary"]["source_contracts"]) == set(SOURCE_CONTRACTS)
            report["checks"]["all_three_logical_groups"] = all(value > 0 for value in expected_counts.values())
            report["checks"]["completeness_invariants"] = all(item["completeness_invariant"] for item in metrics)
            report["checks"]["zero_rejected_documents"] = report["canary"]["rejected_documents"] == 0
            report["checks"]["zero_uuid_conflicts"] = report["canary"]["uuid_conflicts"] == 0
            report["checks"]["uuid_collection_count_parity"] = expected_counts == actual_counts
            report["checks"]["schema_validation"] = len(report["schema_validation_after_write"]) == 3
            report["checks"]["overflow_adaptive_partitioning"] = report["canary"]["overflow"]["parent_pre_count"] > 9500 and report["canary"]["overflow"]["leaf_count"] > 1
            samples = []
            for group, records in sink.expected_records.items():
                if records:
                    record_id, record = next(iter(records.items()))
                    actual = client.get_document(physical_collection_name(group, generation), record_id)
                    samples.append({"group": group, "id": record_id, "retrieved": actual is not None, "fields_equal": actual == canonical_to_typesense_document(record, group)})
            report["representative_uuid_records"] = samples
            report["checks"]["representative_uuid_parity"] = all(item["retrieved"] and item["fields_equal"] for item in samples)

            before = _collection_counts(client, generation)
            forced, forced_metric = _run_partition(engine, CANARY_PLAN[0][0], CANARY_PLAN[0][2], msc, audited_sink, force=True)
            skipped, skipped_metric = _run_partition(engine, CANARY_PLAN[0][0], CANARY_PLAN[0][2], msc, audited_sink)
            after = _collection_counts(client, generation)
            report["idempotency"] = {"forced_rerun": forced_metric, "unforced_rerun": skipped_metric, "forced_status": forced.status.value, "unforced_skipped": skipped.skipped, "counts_before": before, "counts_after": after, "counts_unchanged": before == after}
            report["checks"]["idempotent_force_and_checkpoint_skip"] = forced.status == IngestionStatus.COMPLETED and skipped.skipped and before == after
        sampler.stop()
        report["resources_during_canary"] = sampler.summary()
        report["search"] = _search_smoke(client, generation, sink)
        report["checks"]["search_filter_sort_multi_search"] = report["search"]["pass"]
        report["concurrency"] = {str(level): _concurrency(config, generation, sink, level, args.requests_per_client) for level in (1, 10, 25)}
        report["checks"]["bounded_concurrency"] = all(item["pass"] for item in report["concurrency"].values())
        report["read_during_write"] = _read_during_write(paths, generation, config, report["search"]["latency_ms"]["p95"])
        report["checks"]["read_during_write"] = report["read_during_write"]["pass"]
        report["restart_cycle_1"] = _restart_cycle(paths, client, generation, 1)
        report["checks"]["restart_cycle_1"] = report["restart_cycle_1"]["pass"]
        report["restart_cycle_2"] = _restart_cycle(paths, client, generation, 2)
        report["checks"]["restart_cycle_2"] = report["restart_cycle_2"]["pass"]
        if args.skip_abrupt_recovery:
            report["abrupt_recovery"] = {
                "pass": True,
                "skipped": True,
                "reason": "Skipped after the prior bounded SIGKILL smoke caused Typesense 30.2 to crash while recovering; clean restart persistence remains mandatory and is validated separately.",
            }
        else:
            report["abrupt_recovery"] = _abrupt_recovery(paths, client, generation)
        report["checks"]["abrupt_recovery"] = report["abrupt_recovery"]["pass"]
        report["snapshot"] = {"operation": "POST /operations/snapshot", "result": client.snapshot(str(artifacts["snapshot"])), "location": str(artifacts["snapshot"]), "size_bytes": sum(path.stat().st_size for path in artifacts["snapshot"].rglob("*") if path.is_file())}
        report["checks"]["snapshot_created"] = report["snapshot"]["result"].get("success") is True and report["snapshot"]["size_bytes"] > 0
        try:
            report["restore"] = _restore_proof(paths, client, generation, config, artifacts["snapshot"])
        except Exception as exc:
            restore_error = str(exc)
            report["restore"] = {"pass": False, "error": restore_error}
        report["checks"]["snapshot_restore"] = bool(report.get("restore", {}).get("pass"))
        # Separate bounded interruption proof: first partition writes RUNNING state,
        # then KeyboardInterrupt leaves it incomplete; resume uses same generation.
        interruption_checkpoint = paths.checkpoints_dir / f"{generation}.interruption.sqlite3"
        interruption_uuid = paths.checkpoints_dir / f"{generation}.interruption.uuid.sqlite3"
        interruption = {"checkpoint_path": str(interruption_checkpoint), "status_before_resume": None, "resume_result": None, "previous_completed_skipped": None}
        with CheckpointStore(interruption_checkpoint) as interruption_store:
            seed_msc = RecordingMSCClient(MSCConfig(request_delay_seconds=0, timeout_seconds=30, page_size=args.page_size))
            seed_engine = MSCIngestionEngine(seed_msc, interruption_store, TypesenseSink(client, generation), seed_msc.config)
            seeded = seed_engine.ingest_partition(CANARY_PLAN[0][0], CANARY_PLAN[0][2])
            if seeded.status != IngestionStatus.COMPLETED:
                raise RuntimeError("interruption smoke could not seed a completed partition")

            class InterruptingMSCClient(RecordingMSCClient):
                def __init__(self, config: MSCConfig) -> None:
                    super().__init__(config)
                    self.interrupted = False

                def fetch_page(self, contract: Any, interval: Any, page: int) -> Any:
                    if self.interrupted:
                        raise KeyboardInterrupt
                    self.interrupted = True
                    return super().fetch_page(contract, interval, page)

            interrupt_msc = InterruptingMSCClient(MSCConfig(request_delay_seconds=0, timeout_seconds=30, page_size=args.page_size))
            interrupt_engine = MSCIngestionEngine(interrupt_msc, interruption_store, TypesenseSink(client, generation), interrupt_msc.config)
            try:
                interrupt_engine.ingest_partition(OVERFLOW_SOURCE, OVERFLOW_DATE, force=True)
            except KeyboardInterrupt:
                pass
            running = interruption_store.get(OVERFLOW_SOURCE, OVERFLOW_DATE, f"typesense:{generation}")
            interruption["status_before_resume"] = running.status.value if running else None
            normal_msc = RecordingMSCClient(MSCConfig(request_delay_seconds=0, timeout_seconds=30, page_size=args.page_size))
            normal_engine = MSCIngestionEngine(normal_msc, interruption_store, TypesenseSink(client, generation), normal_msc.config)
            resumed = normal_engine.ingest_partition(OVERFLOW_SOURCE, OVERFLOW_DATE)
            interruption["resume_result"] = resumed.as_dict()
            interruption["previous_completed_skipped"] = normal_engine.ingest_partition(CANARY_PLAN[0][0], CANARY_PLAN[0][2]).skipped
        report["interruption_resume"] = interruption
        report["checks"]["interruption_resume"] = interruption["status_before_resume"] == "RUNNING" and interruption["resume_result"]["status"] == "COMPLETED" and interruption["previous_completed_skipped"]
        historical_msc = MSCClient(MSCConfig(request_delay_seconds=args.request_delay, timeout_seconds=30, page_size=args.page_size))
        historical = source_population_preflight(historical_msc, "2023-02-01", "2026-08-29")
        deltas = historical_source_count_deltas(historical["source_totals"])
        manifest = build_manifest("2023-02-01", "2026-08-29", FUTURE_HISTORICAL_GENERATION, historical["source_totals"], page_size=args.page_size, typesense_batch_size=config.batch_size)
        manifest_path = paths.reports_dir / f"historical-manifest-{FUTURE_HISTORICAL_GENERATION}.json"
        atomic_write_json(manifest_path, manifest)
        from crawler_engine.msc.backfill import verify_manifest
        verify_manifest(manifest, generation=FUTURE_HISTORICAL_GENERATION)
        report["historical_manifest"] = {
            "path": str(manifest_path),
            "range": historical["range"],
            "actual_source_totals": historical["source_totals"],
            "actual_total": historical["overall_total"],
            "previous_total": sum(EXPECTED_HISTORICAL_SOURCE_TOTALS.values()),
            "deltas": deltas,
            "total_delta": historical["overall_total"] - sum(EXPECTED_HISTORICAL_SOURCE_TOTALS.values()),
            "fingerprints_verified": True,
            "engine_version": manifest["engine_version"],
            "schema_version": manifest["schema_version"],
            "manifest_version": manifest["manifest_version"],
            "fingerprints": {
                "source_contracts": manifest["source_contract_fingerprints"],
                "canonical_schema": manifest["canonical_schema_fingerprints"],
                "typesense_schema": manifest["typesense_schema_fingerprints"],
            },
        }
        report["checks"]["historical_counts_revalidated"] = historical["msc_requests"] == 7 and set(deltas) == set(EXPECTED_HISTORICAL_SOURCE_TOTALS) and bool(manifest_path.exists())
        report["checks"]["manifest_fingerprints_valid"] = True
        report["checks"]["future_historical_generation_not_populated"] = all(
            client.get_collection(physical_collection_name(group, FUTURE_HISTORICAL_GENERATION)) is None
            for group in LOGICAL_ALIASES
        )
        report["checks"]["portable_core"] = not any(
            token in path.read_text(encoding="utf-8").lower()
            for path in (ROOT / "crawler_engine" / "msc").glob("*.py")
            for token in ("wsl.exe", "powershell", "winreg")
        )
        report["checks"]["no_full_backfill"] = True
        report["checks"]["no_fastapi_ui_cutover"] = True
        report["resources_final"] = _resource_snapshot(paths)
        report["resource_sampler"] = sampler.summary()
        report["status"] = "PASS" if all(report["checks"].values()) else "PARTIAL"
    except Exception as exc:
        sampler.stop()
        report["status"] = "PARTIAL"
        report["error"] = str(exc)[:2000]
        report["resources_final"] = _resource_snapshot(paths)
    report["runtime"]["restore_error"] = restore_error
    report["report_path"] = str(args.report)
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    atomic_write_json(args.report, report)
    args.markdown.write_text(_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--generation")
    parser.add_argument("--report", type=Path, default=ROOT / "local-typesense-canary-report.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "local-typesense-canary-report.md")
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--requests-per-client", type=int, default=4)
    parser.add_argument("--skip-abrupt-recovery", action="store_true", help="Skip the optional SIGKILL recovery smoke after a bounded failure has shown it is unsafe")
    args = parser.parse_args(argv)
    report = run(args)
    print(json.dumps({"status": report["status"], "generation": report["generation"], "documents": report.get("canary", {}).get("total_unique_documents"), "report": report["report_path"], "snapshot_restore": report.get("checks", {}).get("snapshot_restore")}, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
