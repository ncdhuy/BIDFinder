import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from crawler_engine.msc.backfill import (
    AuditedSink,
    BackfillControlError,
    BackfillRunner,
    UUIDConflictError,
    UUIDProvenanceStore,
    build_manifest,
    checkpoint_audit,
    estimate_capacity,
    field_index_classification,
    historical_backfill_audit,
    iter_parent_partitions,
    load_fixture_samples,
    plan_summary,
    source_population_preflight,
    verify_manifest,
)
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.cli import main
from crawler_engine.msc.config import ENGINE_VERSION, SCHEMA_VERSION
from crawler_engine.msc.contracts import SOURCE_CONTRACTS, get_contract
from crawler_engine.msc.typesense_schema import collection_schema, physical_collection_name
from crawler_engine.msc.models import (
    DriftDiagnostic,
    IngestionStatus,
    PartitionContext,
    PartitionResult,
    SearchInterval,
    SinkWriteResult,
)


class CountClient:
    def __init__(self, totals):
        self.totals = totals
        self.stats = SimpleNamespace(request_count=0)

    def count_interval(self, contract, interval):
        self.stats.request_count += 1
        return self.totals[contract.key]


class FakeSink:
    sink_target = "typesense:test-generation"


class FakeEngine:
    def __init__(self, checkpoints, fail_key=None):
        self.checkpoints = checkpoints
        self.sink = FakeSink()
        self.calls = []
        self.fail_key = fail_key

    def ingest_partition(self, source_key, partition_date, *, force=False, allow_open_day=False):
        self.calls.append((source_key, partition_date, force, allow_open_day))
        self.checkpoints.start(source_key, partition_date, force=force, sink_target=self.sink.sink_target)
        if self.fail_key == (source_key, partition_date):
            self.checkpoints.fail(source_key, partition_date, "MSC_CONTRACT_ERROR", "fixture failure", sink_target=self.sink.sink_target)
            return PartitionResult(source_key, partition_date, IngestionStatus.FAILED, error_code="MSC_CONTRACT_ERROR", error_message="fixture failure", sink_target=self.sink.sink_target)
        self.checkpoints.finish(
            source_key, partition_date, IngestionStatus.COMPLETED,
            sink_target=self.sink.sink_target, parent_pre_count=1,
            parent_post_count=1, normalized_count=1, sink_accepted_count=1,
        )
        return PartitionResult(source_key, partition_date, IngestionStatus.COMPLETED, parent_pre_count=1, parent_post_count=1, normalized_count=1, sink_accepted_count=1, sink_target=self.sink.sink_target)


class InterruptEngine(FakeEngine):
    def ingest_partition(self, source_key, partition_date, *, force=False, allow_open_day=False):
        self.calls.append((source_key, partition_date, force, allow_open_day))
        raise KeyboardInterrupt


class FakeUUIDStore:
    def __init__(self, groups):
        self.groups = groups

    def group_counts(self):
        return self.groups

    def total_count(self):
        return sum(self.groups.values())

    def conflict_count(self):
        return 0


class FakeTypesenseClient:
    def __init__(self, generation, counts):
        self.generation = generation
        self.counts = counts

    def health(self):
        return {"ok": True, "version": "30.2"}

    def get_collection(self, name):
        for group, count in self.counts.items():
            if name == physical_collection_name(group, self.generation):
                return {**collection_schema(group, self.generation), "num_documents": count}
        return None

    def document_count(self, collection):
        for group, count in self.counts.items():
            if collection == physical_collection_name(group, self.generation):
                return count
        raise AssertionError(collection)


class ReadinessTest(unittest.TestCase):
    def _manifest(self, source_totals=None):
        totals = source_totals or {key: 1 for key in SOURCE_CONTRACTS}
        return build_manifest("2023-02-01", "2023-02-02", "test-generation", totals)

    def test_manifest_fingerprints_detect_contract_or_schema_drift(self):
        manifest = self._manifest()
        verify_manifest(manifest, generation="test-generation")
        changed = json.loads(json.dumps(manifest))
        changed["source_contract_fingerprints"]["goods_general"] = "changed"
        with self.assertRaises(BackfillControlError):
            verify_manifest(changed)

    def test_preflight_uses_one_aggregation_request_per_source(self):
        totals = {key: index + 1 for index, key in enumerate(SOURCE_CONTRACTS)}
        client = CountClient(totals)
        result = source_population_preflight(client, "2023-02-01", "2023-02-02")
        self.assertEqual(7, client.stats.request_count)
        self.assertFalse(result["records_paginated"])
        self.assertEqual(sum(totals.values()), result["overall_total"])

    def test_traversal_is_date_ascending_then_registry_order(self):
        result = list(iter_parent_partitions("2023-02-01", "2023-02-02", ("medical_devices", "goods_general")))
        self.assertEqual(
            [("goods_general", "2023-02-01"), ("medical_devices", "2023-02-01"),
             ("goods_general", "2023-02-02"), ("medical_devices", "2023-02-02")],
            result,
        )

    def test_plan_reports_remaining_and_batch_estimates(self):
        manifest = self._manifest({key: 1000 for key in SOURCE_CONTRACTS})
        with tempfile.TemporaryDirectory() as temp:
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                summary = plan_summary(manifest, store)
        self.assertEqual(14, summary["source_date_parent_partitions"])
        self.assertEqual(14, summary["remaining_partitions"])
        self.assertEqual(14, summary["estimated_typesense_batches"])

    def test_runner_resume_force_and_failure_stop(self):
        manifest = self._manifest({key: 1 for key in SOURCE_CONTRACTS})
        with tempfile.TemporaryDirectory() as temp:
            checkpoint_path = Path(temp) / "checkpoints.sqlite3"
            report_path = Path(temp) / "backfill-report.json"
            with CheckpointStore(checkpoint_path) as store:
                engine = FakeEngine(store, fail_key=("medical_devices", "2023-02-01"))
                results = BackfillRunner(engine, store, manifest, report_path=report_path, max_partitions=14).run()
                self.assertEqual([("goods_general", "2023-02-01", False, False), ("medical_devices", "2023-02-01", False, False)], engine.calls)
                self.assertEqual(IngestionStatus.FAILED, results[-1].status)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual("FAILED", report["state"])
                self.assertEqual(1, report["counts"]["failed"])
                with self.assertRaises(BackfillControlError):
                    BackfillRunner(engine, store, manifest, report_path=report_path, max_partitions=14).run()

                engine.fail_key = None
                results = BackfillRunner(engine, store, manifest, report_path=report_path, resume=True, max_partitions=14).run()
                self.assertEqual(IngestionStatus.COMPLETED, results[-1].status)
                engine.calls.clear()
                BackfillRunner(engine, store, manifest, report_path=report_path, resume=True, force=True, max_partitions=14).run()
                self.assertTrue(engine.calls)

    def test_resumed_skipped_partition_does_not_fire_recovery_callback(self):
        manifest = self._manifest({key: 1 for key in SOURCE_CONTRACTS})
        partitions = tuple(iter_parent_partitions(
            manifest["source_range"]["from"], manifest["source_range"]["to"], manifest["sources"]
        ))
        with tempfile.TemporaryDirectory() as temp:
            checkpoint_path = Path(temp) / "checkpoints.sqlite3"
            report_path = Path(temp) / "backfill-report.json"
            with CheckpointStore(checkpoint_path) as store:
                source_key, partition_date = partitions[0]
                store.start(source_key, partition_date, sink_target="typesense:test-generation")
                store.finish(
                    source_key,
                    partition_date,
                    IngestionStatus.COMPLETED,
                    sink_target="typesense:test-generation",
                    parent_pre_count=1,
                    parent_post_count=1,
                    normalized_count=1,
                    sink_accepted_count=1,
                )
                callbacks = []
                results = BackfillRunner(
                    FakeEngine(store),
                    store,
                    manifest,
                    report_path=report_path,
                    resume=True,
                    max_partitions=14,
                    on_partition_boundary=lambda result, _report: callbacks.append(result),
                ).run()

            self.assertTrue(results[0].skipped)
            self.assertEqual(13, len(callbacks))
            self.assertTrue(all(not result.skipped for result in callbacks))

    def test_capacity_arithmetic_and_field_review(self):
        samples = load_fixture_samples(sample_limit=1)
        totals = {key: 10 for key in SOURCE_CONTRACTS}
        estimate = estimate_capacity(totals, samples)
        self.assertEqual(1, estimate["overall"]["estimated_typesense_batches"])
        self.assertGreater(estimate["overall"]["projected_indexed_field_bytes"], 0)
        self.assertEqual("full-text searchable", field_index_classification("goods")["technical_specification"])
        self.assertEqual("display-only", field_index_classification("goods")["location"])

    def test_uuid_audit_distinguishes_same_and_conflicting_provenance(self):
        contract = get_contract("goods_general")
        context = PartitionContext(
            "goods_general", "2023-02-01", contract,
            SearchInterval("2023-02-01T00:00:00.000Z", "2023-02-01T23:59:59.999Z"),
            1, 1, 1, 1, 1, 1, DriftDiagnostic(()), "typesense:test-generation",
        )
        record = {"id": "uuid-1", "source_key": "goods_general", "data_group": "goods", "partition_date": "2023-02-01", "item_name": "x"}
        with tempfile.TemporaryDirectory() as temp:
            with UUIDProvenanceStore(Path(temp) / "uuids.sqlite3") as store:
                class Sink:
                    sink_target = "typesense:test-generation"
                    def write_partition(self, context, records):
                        return SinkWriteResult(len(records), len(records), 0, batch_count=1)
                audited = AuditedSink(Sink(), store)
                audited.write_partition(context, [record])
                audited.write_partition(context, [record])
                conflicting = dict(record, item_name="different")
                with self.assertRaises(UUIDConflictError):
                    audited.write_partition(context, [conflicting])
                self.assertEqual(1, store.total_count())
                self.assertEqual(1, store.conflict_count())

    def test_checkpoint_audit_reports_pending_failed_and_quarantined(self):
        manifest = self._manifest()
        with tempfile.TemporaryDirectory() as temp:
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                store.ensure("goods_general", "2023-02-01", "typesense:test-generation")
                store.start("goods_general", "2023-02-02", sink_target="typesense:test-generation")
                store.fail("goods_general", "2023-02-02", "SEARCH_WINDOW_OVERFLOW", "overflow", quarantine=True, sink_target="typesense:test-generation")
                result = checkpoint_audit(store, "2023-02-01", "2023-02-02", manifest["sources"], "typesense:test-generation")
        self.assertEqual(2, result["sources"]["medical_devices"]["pending"])
        self.assertEqual(1, result["sources"]["goods_general"]["quarantined"])

    def test_runner_requires_explicit_partition_cap(self):
        manifest = self._manifest()
        with tempfile.TemporaryDirectory() as temp:
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                with self.assertRaises(BackfillControlError):
                    BackfillRunner(FakeEngine(store), store, manifest, report_path=Path(temp) / "report.json").run()

    def test_cli_actual_run_requires_explicit_acknowledgement(self):
        self.assertEqual(
            2,
            main([
                "backfill", "--from", "2023-02-01", "--to", "2023-02-02",
                "--generation", "test-generation", "--checkpoint", "checkpoint.sqlite3",
                "--max-partitions", "14",
            ]),
        )

    def test_interrupt_writes_atomic_recoverable_report(self):
        manifest = self._manifest()
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                with self.assertRaises(KeyboardInterrupt):
                    BackfillRunner(InterruptEngine(store), store, manifest, report_path=report_path, max_partitions=14).run()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("INTERRUPTED", report["state"])
            self.assertFalse(list(Path(temp).glob(".report.json.*.tmp")))

    def test_historical_audit_checks_source_coverage_and_typesense_counts(self):
        manifest = self._manifest({key: 2 for key in SOURCE_CONTRACTS})
        expected_groups = {"goods": 4, "medicines": 6, "traditional_medicine": 4}
        with tempfile.TemporaryDirectory() as temp:
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                engine = FakeEngine(store)
                BackfillRunner(engine, store, manifest, report_path=Path(temp) / "report.json", max_partitions=14).run()
                audit = historical_backfill_audit(
                    manifest, store, FakeUUIDStore(expected_groups),
                    typesense_client=FakeTypesenseClient("test-generation", expected_groups),
                )
        self.assertEqual("PASS", audit["overall_status"])
        self.assertTrue(all(item["parity"] for item in audit["source_coverage_parity"].values()))
        self.assertTrue(all(audit["typesense_count_parity"].values()))

    def test_historical_audit_reports_coverage_mismatch(self):
        manifest = self._manifest({key: 2 for key in SOURCE_CONTRACTS})
        with tempfile.TemporaryDirectory() as temp:
            with CheckpointStore(Path(temp) / "checkpoints.sqlite3") as store:
                store.start("goods_general", "2023-02-01", sink_target="typesense:test-generation")
                store.finish("goods_general", "2023-02-01", IngestionStatus.COMPLETED, sink_target="typesense:test-generation", parent_pre_count=1, parent_post_count=1, normalized_count=1, sink_accepted_count=1)
                audit = historical_backfill_audit(
                    manifest, store, FakeUUIDStore({"goods": 1, "medicines": 0, "traditional_medicine": 0}),
                )
        self.assertEqual("FAIL", audit["overall_status"])
        self.assertFalse(audit["source_coverage_parity"]["goods_general"]["parity"])


if __name__ == "__main__":
    unittest.main()
