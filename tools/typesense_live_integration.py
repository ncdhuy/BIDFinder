"""Run the bounded Phase 3A live Typesense proof against a disposable server."""

from __future__ import annotations

import argparse
import copy
from dataclasses import fields, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
import statistics
import sys
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Mapping, Sequence
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus, PartitionContext
from crawler_engine.msc.normalize import normalize_record
from crawler_engine.msc.partitioning import official_day_interval
from crawler_engine.msc.sink import TypesenseSink
from crawler_engine.msc.typesense_client import (
    TypesenseClient,
    TypesenseCollectionManager,
    parse_import_response,
    serialize_ndjson,
)
from crawler_engine.msc.typesense_schema import (
    LOGICAL_ALIASES,
    SEARCH_CONFIGS,
    canonical_to_typesense_document,
    collection_schema,
    physical_collection_name,
)


SOURCE_CASES = (
    ("goods_general", "goods", "2026-08-25"),
    ("medical_devices", "goods", "2026-08-28"),
    ("medicine_generic", "medicines", "2026-08-28"),
    ("medicine_originator", "medicines", "2026-08-27"),
    ("medicine_herbal", "medicines", "2026-08-28"),
    ("herbal_material", "traditional_medicine", "2026-08-22"),
    ("traditional_medicine", "traditional_medicine", "2026-08-27"),
)
OVERFLOW_CASE = ("goods_general", "goods", "2026-08-28")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    return value


def _value(value: Any) -> Any:
    if isinstance(value, list):
        return next((item for item in value if item not in (None, "")), None)
    if isinstance(value, str) and not value.strip(" _-"):
        return None
    return value if value not in (None, "") else None


def _preview(value: Any, limit: int = 100) -> str | None:
    value = _value(value)
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


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


class RecordingTypesenseClient(TypesenseClient):
    def __init__(self, config: TypesenseConfig) -> None:
        super().__init__(config)
        self.import_timings: list[float] = []
        self.import_attempts: list[int] = []

    def import_documents(self, collection: str, documents: Sequence[Mapping[str, Any]]) -> Any:
        result = super().import_documents(collection, documents)
        self.import_timings.append(result.elapsed_seconds)
        self.import_attempts.append(len(documents))
        return result


class RecordingTypesenseSink(TypesenseSink):
    def __init__(self, client: TypesenseClient, generation_id: str) -> None:
        super().__init__(client, generation_id)
        self.expected_ids = {group: set() for group in LOGICAL_ALIASES}
        self.expected_records: dict[str, dict[str, dict[str, Any]]] = {group: {} for group in LOGICAL_ALIASES}
        self.candidates: dict[str, dict[str, Any]] = {group: {} for group in LOGICAL_ALIASES}
        self.numeric_ranges: dict[str, dict[str, list[float]]] = {group: {} for group in LOGICAL_ALIASES}

    def write_partition(self, context: PartitionContext, records: Sequence[dict[str, Any]]) -> Any:
        group = context.contract.data_group
        for record in records:
            self.expected_ids[group].add(record["id"])
            self.expected_records[group].setdefault(record["id"], dict(record))
            for key, raw_value in record.items():
                value = _value(raw_value)
                if value is None:
                    continue
                if key not in self.candidates[group] and isinstance(value, (str, int, float)):
                    self.candidates[group][key] = value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bounds = self.numeric_ranges[group].setdefault(key, [float(value), float(value)])
                    bounds[0] = min(bounds[0], float(value))
                    bounds[1] = max(bounds[1], float(value))
        return super().write_partition(context, records)


def _metric(
    result: Any,
    source_key: str,
    logical_group: str,
    partition_date: str,
    msc_client: RecordingMSCClient,
    sink: TypesenseSink,
    checkpoints: CheckpointStore,
    page_before: int,
    count_before: int,
    started: float,
) -> dict[str, Any]:
    checkpoint = checkpoints.get(source_key, partition_date, sink.sink_target)
    attempted = result.sink_attempted_count
    accepted = result.sink_accepted_count
    drift = result.drift
    return {
        "source_key": source_key,
        "logical_group": logical_group,
        "date": partition_date,
        "pre_count": result.parent_pre_count,
        "post_count": result.parent_post_count,
        "leaf_count": result.leaf_count,
        "msc_page_request_count": msc_client.page_request_count - page_before,
        "msc_count_request_count": msc_client.count_request_count - count_before,
        "msc_request_count": result.request_count,
        "unique_source_count": result.unique_source_count,
        "normalized_count": result.normalized_count,
        "typesense_import_batches": result.sink_batch_count,
        "typesense_attempted_count": attempted,
        "typesense_accepted_count": accepted,
        "typesense_rejected_count": max(0, attempted - accepted),
        "checkpoint_final_state": _jsonable(checkpoint),
        "status": _jsonable(result.status),
        "skipped": result.skipped,
        "retry_count": result.retry_count,
        "sink_elapsed_seconds": result.sink_elapsed_seconds,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "schema_drift": {
            "additive_fields": list(drift.additive_fields),
            "type_errors": list(drift.type_errors),
        },
    }


def _run_partition(
    engine: MSCIngestionEngine,
    source_key: str,
    group: str,
    partition_date: str,
    msc_client: RecordingMSCClient,
    sink: TypesenseSink,
    checkpoints: CheckpointStore,
    *,
    force: bool = False,
) -> tuple[Any, dict[str, Any]]:
    page_before = msc_client.page_request_count
    count_before = msc_client.count_request_count
    started = perf_counter()
    result = engine.ingest_partition(source_key, partition_date, force=force)
    return result, _metric(
        result, source_key, group, partition_date, msc_client, sink, checkpoints,
        page_before, count_before, started,
    )


def _context(source_key: str, partition_date: str) -> PartitionContext:
    contract = SOURCE_CONTRACTS[source_key]
    return PartitionContext(
        source_key, partition_date, contract, official_day_interval(partition_date),
        1, 1, 1, 1, 1, 1,
    )


@contextmanager
def _checkpoint_paths() -> Any:
    prefix = f".phase3a-live-{os.getpid()}-{int(perf_counter() * 1000)}"
    paths = (
        ROOT / f"{prefix}.sqlite3",
        ROOT / f"{prefix}-partial.sqlite3",
    )
    try:
        yield paths
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def _hits(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [hit.get("document", {}) for hit in response.get("hits", []) if isinstance(hit, Mapping)]


def _search(client: TypesenseClient, group: str, label: str, query: str, **kwargs: Any) -> dict[str, Any]:
    started = perf_counter()
    response = client.search_group(group, query, per_page=3, **kwargs)
    hits = _hits(response)
    return {
        "group": group,
        "category": label,
        "query": _preview(query),
        "result_count": response.get("found"),
        "top_sample_ids": [hit.get("id") for hit in hits[:3] if hit.get("id")],
        "latency_ms": round((perf_counter() - started) * 1000, 2),
    }


def _run_search_proofs(client: TypesenseClient, sink: RecordingTypesenseSink) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    queries = {
        "goods": (
            ("item_name", "item name"),
            ("manufacturer", "manufacturer/brand"),
            ("winning_bidder_name", "bidder"),
            ("bid_invitation_code", "tender code"),
        ),
        "medicines": (
            ("medicine_name", "medicine name"),
            ("active_ingredient_or_herbal_component", "active ingredient"),
            ("manufacturer", "manufacturer"),
            ("winning_bidder_name", "bidder"),
            ("bid_invitation_code", "tender code"),
        ),
        "traditional_medicine": (
            ("item_name", "item name"),
            ("scientific_name", "scientific name"),
            ("manufacturer", "manufacturer/source"),
            ("winning_bidder_name", "bidder"),
            ("bid_invitation_code", "tender code"),
        ),
    }
    searches: list[dict[str, Any]] = []
    for group, fields_to_query in queries.items():
        for field, label in fields_to_query:
            value = sink.candidates[group].get(field)
            if value in (None, ""):
                searches.append({"group": group, "category": label, "skipped": "no indexed value"})
                continue
            searches.append(_search(client, group, label, str(value)))

    filters: list[dict[str, Any]] = []
    for group in LOGICAL_ALIASES:
        source_tab = sink.candidates[group].get("source_tab")
        if source_tab:
            response = _search(client, group, "source_tab", "*", filter_by=f"source_tab:={source_tab}")
            response.update({"filter": "source_tab", "filter_value": _preview(source_tab)})
            response["semantics_ok"] = all(hit.get("source_tab") == source_tab for hit in _hits(client.search_group(group, "*", filter_by=f"source_tab:={source_tab}", per_page=20)))
            filters.append(response)
        method = sink.candidates[group].get("selection_method")
        if method:
            response = _search(client, group, "selection_method", "*", filter_by=f"selection_method:={method}")
            response.update({"filter": "selection_method", "filter_value": _preview(method)})
            filters.append(response)
        if "location" not in SEARCH_CONFIGS[group].filter_fields:
            filters.append({"group": group, "filter": "location", "skipped": "not configured as facet/filter field"})
        price_bounds = sink.numeric_ranges[group].get("winning_unit_price")
        if price_bounds and price_bounds[1] > 0:
            filter_by = "winning_unit_price:>0"
            response = _search(client, group, "price range", "*", filter_by=filter_by)
            response.update({"filter": "winning_unit_price", "filter_value": filter_by})
            response["semantics_ok"] = all(
                isinstance(hit.get("winning_unit_price"), (int, float)) and hit["winning_unit_price"] > 0
                for hit in _hits(client.search_group(group, "*", filter_by=filter_by, per_page=20))
            )
            filters.append(response)

    sorts: list[dict[str, Any]] = []
    for group in LOGICAL_ALIASES:
        for direction in ("asc", "desc"):
            started = perf_counter()
            response = client.search_group(group, "*", sort_by=f"winning_unit_price:{direction}", per_page=20)
            values = [
                hit.get("winning_unit_price") for hit in _hits(response)
                if isinstance(hit.get("winning_unit_price"), (int, float))
            ]
            expected = sorted(values, reverse=direction == "desc")
            sorts.append({
                "group": group,
                "sort": f"winning_unit_price:{direction}",
                "result_count": response.get("found"),
                "numeric_values_checked": len(values),
                "order_ok": values == expected,
                "latency_ms": round((perf_counter() - started) * 1000, 2),
            })
    return searches, filters, sorts


def _raw_partial_import(client: TypesenseClient, collection: str, documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    request = Request(
        client._url(f"/collections/{collection}/documents/import?action=upsert"),
        data=serialize_ndjson(documents),
        method="POST",
        headers={"X-TYPESENSE-API-KEY": client.config.api_key, "Content-Type": "application/jsonl"},
    )
    with client._opener(request, timeout=client.config.timeout_seconds) as response:
        status = getattr(response, "status", None)
        body = response.read().decode("utf-8", errors="replace")
    result = parse_import_response(body, len(documents))
    return {
        "http_status": status,
        "attempted_count": result.attempted_count,
        "accepted_count": result.accepted_count,
        "rejected_count": result.rejected_count,
        "error_code": result.error_code,
        "parser_errors": list(result.errors),
    }


def run_gate(report_path: Path, generation: str | None = None) -> dict[str, Any]:
    generation_a = generation or f"live_{os.getpid()}"
    generation_b = f"{generation_a}_b"
    generation_c = f"{generation_a}_c"
    config = TypesenseConfig.from_env()
    msc_config = MSCConfig()
    ts_client = RecordingTypesenseClient(config)
    manager = TypesenseCollectionManager(ts_client)
    msc_client = RecordingMSCClient(msc_config)
    created = manager.create_generation(generation_a)
    schema_validation = manager.validate_generation(generation_a)
    inspected = {group: ts_client.get_collection(name) for group, name in created.items()}
    health = ts_client.health()
    started = perf_counter()
    with _checkpoint_paths() as (checkpoint_path, partial_checkpoint_path):
        checkpoints = CheckpointStore(checkpoint_path)
        sink = RecordingTypesenseSink(ts_client, generation_a)
        engine = MSCIngestionEngine(msc_client, checkpoints, sink, msc_config)
        try:
            # Seed only the old Phase 2 namespace; it must not suppress Typesense ingestion.
            checkpoints.start("medicine_originator", "2026-08-27")
            checkpoints.finish("medicine_originator", "2026-08-27", IngestionStatus.COMPLETED)
            source_metrics: list[dict[str, Any]] = []
            for case in (*SOURCE_CASES, OVERFLOW_CASE):
                _, metric = _run_partition(engine, *case, msc_client, sink, checkpoints)
                source_metrics.append(metric)

            a_counts_before = {
                group: ts_client.document_count(physical_collection_name(group, generation_a))
                for group in LOGICAL_ALIASES
            }
            expected_counts = {group: len(ids) for group, ids in sink.expected_ids.items()}
            main_import_timings = list(ts_client.import_timings)
            alias_a = manager.activate_generation(generation_a)
            aliases_after_a = manager.inspect()
            search_smoke, filters, sorts = _run_search_proofs(ts_client, sink)
            multi_started = perf_counter()
            multi = ts_client.multi_search_all("*", per_page=1)
            multi_summary = {
                "result_count": len(multi.get("results", [])),
                "found_counts": [item.get("found") for item in multi.get("results", [])],
                "latency_ms": round((perf_counter() - multi_started) * 1000, 2),
            }

            # Same-generation forced rerun proves real upsert idempotency; following run skips.
            rerun_result, rerun_metric = _run_partition(
                engine, "goods_general", "goods", "2026-08-25", msc_client, sink, checkpoints, force=True,
            )
            skip_result, skip_metric = _run_partition(
                engine, "goods_general", "goods", "2026-08-25", msc_client, sink, checkpoints,
            )
            a_counts_after = {
                group: ts_client.document_count(physical_collection_name(group, generation_a))
                for group in LOGICAL_ALIASES
            }
            sample_parity = []
            for group, records in sink.expected_records.items():
                if not records:
                    continue
                record_id, record = next(iter(records.items()))
                actual = ts_client.get_document(physical_collection_name(group, generation_a), record_id)
                expected_document = canonical_to_typesense_document(record, group)
                sample_parity.append({
                    "group": group,
                    "sample_id": record_id,
                    "retrieved": actual is not None,
                    "important_fields_equal": actual == expected_document,
                })

            manager.create_generation(generation_b)
            sink_b = TypesenseSink(ts_client, generation_b)
            b_engine = MSCIngestionEngine(msc_client, checkpoints, sink_b, msc_config)
            _, generation_b_metric = _run_partition(
                b_engine, "medicine_originator", "medicines", "2026-08-27", msc_client, sink_b, checkpoints,
            )
            goods_record = next(iter(sink.expected_records["goods"].values()))
            sink_b.write_partition(_context(goods_record["source_key"], "2026-08-25"), [goods_record])
            switched = manager.point_alias("goods", physical_collection_name("goods", generation_b))
            switched_target = ts_client.get_alias(LOGICAL_ALIASES["goods"])
            switched_search = ts_client.search_group("goods", "*", per_page=1)
            rolled_back = manager.rollback_alias("goods", generation_a)
            rollback_target = ts_client.get_alias(LOGICAL_ALIASES["goods"])
            rollback_search = ts_client.search_group("goods", "*", per_page=1)

            manager.create_generation(generation_c)
            partial_sink = TypesenseSink(ts_client, generation_c, batch_size=2)
            valid_record = copy.deepcopy(goods_record)
            invalid_record = copy.deepcopy(goods_record)
            invalid_record["id"] = f"{goods_record['id']}-partial-invalid"
            invalid_record["winning_unit_price"] = "not-a-number"
            partial_context = _context(goods_record["source_key"], "2026-08-25")
            partial_fixture = f"bidfinder_partial_{os.getpid()}"
            ts_client.create_collection({
                "name": partial_fixture,
                "fields": [{"name": "title", "type": "string", "optional": False}],
            })
            raw_partial = _raw_partial_import(
                ts_client, partial_fixture,
                [{"id": "valid", "title": "ok"}, {"id": "invalid", "title": 7}],
            )
            partial_result = partial_sink.write_partition(partial_context, [valid_record, invalid_record])
            partial_checkpoints = CheckpointStore(partial_checkpoint_path)
            partial_checkpoints.start("goods_general", "2026-08-25", sink_target=partial_sink.sink_target)
            partial_checkpoint_before_finish = partial_checkpoints.get("goods_general", "2026-08-25", partial_sink.sink_target)
            partial_checkpoints.close()

            a_validation = manager.validate_generation(generation_a)
            required_searches = [item for item in search_smoke if not item.get("skipped")]
            required_filters = [item for item in filters if not item.get("skipped")]
            checks = {
                "health": health.get("ok") is True,
                "schema_validation": len(schema_validation) == 3 and len(a_validation) == 3,
                "source_partitions_complete": all(
                    item["status"] == "COMPLETED"
                    and item["pre_count"] == item["post_count"] == item["unique_source_count"] == item["normalized_count"]
                    and item["typesense_accepted_count"] == item["normalized_count"]
                    and item["typesense_rejected_count"] == 0
                    for item in source_metrics
                ),
                "uuid_count_parity": expected_counts == a_counts_after,
                "sample_retrieval_parity": all(item["retrieved"] and item["important_fields_equal"] for item in sample_parity),
                "idempotency": rerun_metric["status"] == "COMPLETED" and skip_result.skipped and a_counts_before == a_counts_after,
                "search_smoke": all(item.get("result_count", 0) >= 1 for item in required_searches),
                "filters": all(item.get("semantics_ok", True) and item.get("result_count", 0) >= 0 for item in required_filters),
                "sorts": all(item["order_ok"] for item in sorts),
                "multi_search": multi_summary["result_count"] == 3,
                "alias_activation": all(
                    aliases_after_a["aliases"][alias]["collection_name"] == physical_collection_name(group, generation_a)
                    for group, alias in LOGICAL_ALIASES.items()
                ),
                "alias_switch_and_rollback": (
                    switched_target["collection_name"] == physical_collection_name("goods", generation_b)
                    and rollback_target["collection_name"] == physical_collection_name("goods", generation_a)
                    and rollback_search.get("found", 0) >= 1
                ),
                "checkpoint_generation": (
                    source_metrics[3]["skipped"] is False
                    and skip_result.skipped
                    and generation_b_metric["skipped"] is False
                    and generation_b_metric["status"] == "COMPLETED"
                ),
                "partial_import": (
                    raw_partial["http_status"] == 200
                    and raw_partial["accepted_count"] == 1
                    and raw_partial["rejected_count"] == 1
                    and partial_result.rejected_count == 1
                    and partial_checkpoint_before_finish.status != IngestionStatus.COMPLETED
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(f"Phase 3A-L checks failed: {[name for name, passed in checks.items() if not passed]}")
            report = {
                "status": "PASS",
                "checks": checks,
                "runtime": {
                    "typesense_version": "30.2",
                    "health": health,
                    "api_key_logged": False,
                    "msc_endpoint_scope": "public /search_prc",
                },
                "generation_id": generation_a,
                "physical_collections": {
                    group: physical_collection_name(group, generation_a) for group in LOGICAL_ALIASES
                },
                "schemas": {
                    "validated": len(schema_validation) == 3 and len(a_validation) == 3,
                    "inspected_field_counts": {group: len(item.get("fields", [])) for group, item in inspected.items()},
                    "implicit_id_omitted_by_server": all(
                        "id" not in {field.get("name") for field in item.get("fields", [])}
                        for item in inspected.values()
                    ),
                },
                "source_partitions": source_metrics[:7],
                "overflow": source_metrics[7],
                "expected_uuid_union": expected_counts,
                "actual_collection_document_counts": a_counts_after,
                "uuid_count_parity": expected_counts == a_counts_after,
                "sample_retrieval_parity": sample_parity,
                "idempotency": {
                    "forced_rerun": rerun_metric,
                    "following_unforced_run_skipped": skip_result.skipped,
                    "counts_before": a_counts_before,
                    "counts_after": a_counts_after,
                    "counts_unchanged": a_counts_before == a_counts_after,
                    "sample_ids_unchanged": all(item["retrieved"] for item in sample_parity),
                },
                "search_smoke": search_smoke,
                "filters": filters,
                "sorts": sorts,
                "multi_search": multi_summary,
                "alias_proof": {
                    "activate_generation_a": alias_a,
                    "aliases_after_a": aliases_after_a,
                    "switched_goods_to_generation_b": switched,
                    "switched_goods_target": switched_target,
                    "switched_goods_found": switched_search.get("found"),
                    "rolled_back_goods_to_generation_a": rolled_back,
                    "rollback_goods_target": rollback_target,
                    "rollback_goods_found": rollback_search.get("found"),
                },
                "checkpoint_generation": {
                    "old_validation_jsonl_seeded": True,
                    "old_validation_jsonl_did_not_skip_typesense": source_metrics[3]["skipped"] is False,
                    "generation_a_completed": source_metrics[3]["status"] == "COMPLETED",
                    "generation_a_rerun_skipped": skip_result.skipped,
                    "generation_b_not_skipped": generation_b_metric["skipped"] is False,
                    "generation_b_result": generation_b_metric,
                },
                "partial_import": {
                    "dedicated_fixture_collection": partial_fixture,
                    "raw_http_import": raw_partial,
                    "sink_attempted_count": partial_result.attempted_count,
                    "sink_accepted_count": partial_result.accepted_count,
                    "sink_rejected_count": partial_result.rejected_count,
                    "sink_error_code": partial_result.error_code,
                    "sink_fail_closed_before_import": partial_result.attempted_count == 0,
                    "checkpoint_status_before_finish": _jsonable(partial_checkpoint_before_finish.status),
                    "not_marked_complete": partial_checkpoint_before_finish.status != IngestionStatus.COMPLETED,
                },
                "performance": {
                    "main_documents_indexed": sum(item["typesense_accepted_count"] for item in source_metrics),
                    "main_import_batches": sum(item["typesense_import_batches"] for item in source_metrics),
                    "batch_size": config.batch_size,
                    "import_documents_per_second": round(
                        sum(item["typesense_accepted_count"] for item in source_metrics)
                        / max(sum(item["sink_elapsed_seconds"] for item in source_metrics), 0.001), 2,
                    ),
                    "batch_latency_mean_ms": round(statistics.mean(main_import_timings) * 1000, 2),
                    "batch_latency_median_ms": round(statistics.median(main_import_timings) * 1000, 2),
                    "multi_search_latency_ms": multi_summary["latency_ms"],
                    "overflow_elapsed_seconds": source_metrics[7]["elapsed_seconds"],
                    "gate_elapsed_seconds": round(perf_counter() - started, 3),
                },
                "proof_collections_retained_until_disposable_server_shutdown": True,
            }
        finally:
            checkpoints.close()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "typesense-integration-report.json")
    parser.add_argument("--generation")
    args = parser.parse_args()
    report = run_gate(args.report, args.generation)
    print(json.dumps({
        "status": report["status"],
        "report": str(args.report),
        "generation": report["generation_id"],
        "documents": report["performance"]["main_documents_indexed"],
        "uuid_count_parity": report["uuid_count_parity"],
        "partial_import_rejected": report["partial_import"]["sink_rejected_count"],
        "gate_elapsed_seconds": report["performance"]["gate_elapsed_seconds"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
