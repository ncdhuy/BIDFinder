from __future__ import annotations

from datetime import date
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from crawler_engine.msc.backfill import (
    AuditedSink,
    UUIDProvenanceStore,
    build_manifest,
    reconcile_completed_prefix,
)
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.contracts import get_contract
from crawler_engine.msc.models import DriftDiagnostic, IngestionStatus, PartitionContext, SinkWriteResult
from crawler_engine.msc.partitioning import official_day_interval
from tools.phase3b_historical_backfill import (
    _current_observed_manifest,
    _manifest_deltas,
    _prepare_manifest_for_run,
    _sample_parity,
)


class CountOnlyClient:
    def __init__(self, counts: dict[str, int]):
        self.counts = counts
        self.requests = []

    def count_interval(self, contract, interval):
        first = date.fromisoformat(interval.from_value[:10])
        last = date.fromisoformat(interval.to_value[:10])
        self.requests.append((first.isoformat(), last.isoformat()))
        cursor = first
        total = 0
        while cursor <= last:
            total += self.counts.get(cursor.isoformat(), 0)
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return total


def _complete(store: CheckpointStore, partition_date: str, count: int) -> None:
    store.start("goods_general", partition_date, sink_target="typesense:test")
    store.finish(
        "goods_general",
        partition_date,
        IngestionStatus.COMPLETED,
        sink_target="typesense:test",
        parent_pre_count=count,
        parent_post_count=count,
        normalized_count=count,
        sink_accepted_count=count,
    )


class ReconciliationTest(unittest.TestCase):
    def test_clean_completed_prefix_is_pruned_at_root(self):
        with CheckpointStore() as store:
            for day, count in zip(("2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"), (2, 3, 4, 5)):
                _complete(store, day, count)
            client = CountOnlyClient({"2025-01-01": 2, "2025-01-02": 3, "2025-01-03": 4, "2025-01-04": 5})
            result = reconcile_completed_prefix(client, store, "goods_general", "2025-01-01", "2025-01-04", "typesense:test")
        self.assertEqual("CLEAN", result["status"])
        self.assertEqual(14, result["checkpoint_sum"])
        self.assertEqual(14, result["observed_count"])
        self.assertEqual(1, result["requests"])

    def test_only_changed_one_day_is_located_recursively(self):
        with CheckpointStore() as store:
            for day, count in zip(("2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"), (2, 3, 4, 5)):
                _complete(store, day, count)
            client = CountOnlyClient({"2025-01-01": 2, "2025-01-02": 1, "2025-01-03": 4, "2025-01-04": 5})
            result = reconcile_completed_prefix(client, store, "goods_general", "2025-01-01", "2025-01-04", "typesense:test")
        self.assertEqual("CHANGED", result["status"])
        self.assertEqual(5, result["requests"])
        self.assertEqual(
            [{"source_key": "goods_general", "partition_date": "2025-01-02", "previous_count": 3, "current_count": 1, "delta": -2}],
            result["changed_partitions"],
        )

    def test_partition_replacement_removes_exact_stale_uuid_and_updates_provenance(self):
        class FakeSink:
            sink_target = "typesense:test"

            def __init__(self):
                self.deleted = []

            def write_partition(self, context, records):
                return SinkWriteResult(len(records), len(records), 0)

            def delete_documents(self, context, document_ids):
                self.deleted.extend(document_ids)

        contract = get_contract("goods_general")
        context = PartitionContext("goods_general", "2025-01-01", contract, official_day_interval("2025-01-01"), 2, 2, 2, 2, 2, 1, sink_target="typesense:test")
        with UUIDProvenanceStore(":memory:") as provenance:
            audited = AuditedSink(FakeSink(), provenance)
            old = [{"id": "old", "value": "removed"}, {"id": "kept", "value": "before"}]
            provenance.begin_partition(context, old)
            provenance.commit()
            current = [{"id": "kept", "value": "after"}, {"id": "new", "value": "added"}]
            result = audited.replace_partition(context, current, {"old"})
            self.assertEqual(2, result.accepted_count)
            self.assertEqual({"kept", "new"}, provenance.partition_uuids("goods_general", "2025-01-01"))
            self.assertEqual(["old"], audited.sink.deleted)


class ManifestLineageTest(unittest.TestCase):
    def test_observed_count_delta_does_not_change_contract_fingerprints(self):
        totals = {
            "goods_general": 10,
            "medical_devices": 20,
            "medicine_generic": 30,
            "medicine_originator": 40,
            "medicine_herbal": 50,
            "herbal_material": 60,
            "traditional_medicine": 70,
        }
        manifest = build_manifest("2025-01-01", "2025-01-02", "dev1", totals)
        observed = dict(manifest)
        observed["source_totals"] = {**totals, "goods_general": 8}
        observed["expected_overall_total"] = 278
        self.assertEqual(manifest["source_contract_fingerprints"], observed["source_contract_fingerprints"])
        self.assertEqual(manifest["canonical_schema_fingerprints"], observed["canonical_schema_fingerprints"])
        self.assertEqual(278, observed["expected_overall_total"])

    def test_manifest_lineage_records_delta_and_preserves_start_manifest(self):
        totals = {
            "goods_general": 10,
            "medical_devices": 20,
            "medicine_generic": 30,
            "medicine_originator": 40,
            "medicine_herbal": 50,
            "herbal_material": 60,
            "traditional_medicine": 70,
        }
        manifest = build_manifest("2025-01-01", "2025-01-02", "dev1", totals)
        fresh = {**totals, "goods_general": 8}
        observed = _current_observed_manifest(manifest, {"source_totals": fresh, "group_totals": {"goods": 8, "medicines": 140, "traditional_medicine": 70}, "overall_total": 278}, "2026-09-01T00:00:00+00:00")
        deltas = _manifest_deltas(manifest, fresh, "2026-09-01T00:00:00+00:00")
        self.assertEqual(10, deltas["goods_general"]["old_count"])
        self.assertEqual(8, deltas["goods_general"]["current_count"])
        self.assertEqual(-2, deltas["goods_general"]["delta"])
        self.assertEqual(278, observed["expected_overall_total"])
        self.assertEqual(10, manifest["source_totals"]["goods_general"])
        self.assertEqual(manifest["source_contract_fingerprints"], observed["source_contract_fingerprints"])

    def test_count_drift_is_allowed_only_for_resume(self):
        totals = {
            "goods_general": 10,
            "medical_devices": 20,
            "medicine_generic": 30,
            "medicine_originator": 40,
            "medicine_herbal": 50,
            "herbal_material": 60,
            "traditional_medicine": 70,
        }
        manifest = build_manifest("2025-01-01", "2025-01-02", "dev1", totals)
        fresh = {"source_totals": {**totals, "goods_general": 8}, "group_totals": {"goods": 8, "medicines": 140, "traditional_medicine": 70}, "overall_total": 278}
        with self.assertRaisesRegex(ValueError, "fresh MSC preflight differs"):
            _prepare_manifest_for_run(manifest, fresh, "2026-09-01T00:00:00+00:00", resume=False)
        observed, deltas, changed = _prepare_manifest_for_run(manifest, fresh, "2026-09-01T00:00:00+00:00", resume=True)
        self.assertEqual({"goods_general"}, set(changed))
        self.assertEqual(-2, deltas["goods_general"]["delta"])
        self.assertEqual(8, observed["source_totals"]["goods_general"])


class SampleParityTest(unittest.TestCase):
    def test_sample_parity_uses_drift_diagnostic_breaking_property(self):
        class FakeMSC:
            def count_interval(self, contract, interval):
                return 1

            def fetch_page(self, contract, interval, page):
                return {"page": {"content": [{"id": "sample"}]}}

        class FakeTypesense:
            def get_document(self, collection, document_id):
                return {"id": document_id}

        manifest = {
            "source_range": {"from": "2023-02-01", "to": "2026-08-29"},
            "sources": ["goods_general"],
            "generation": "hist_v1_20260829",
        }
        with patch("tools.phase3b_historical_backfill.validate_raw_records", return_value=DriftDiagnostic(())), patch(
            "tools.phase3b_historical_backfill.normalize_records", return_value=[{"id": "sample"}]
        ), patch(
            "tools.phase3b_historical_backfill.canonical_to_typesense_document",
            side_effect=lambda record, data_group: dict(record),
        ):
            result = _sample_parity(FakeMSC(), FakeTypesense(), manifest)

        self.assertEqual("PASS", result["status"])


class SQLiteBusyTimeoutTest(unittest.TestCase):
    def test_checkpoint_store_waits_for_transient_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = f"{temporary}/checkpoint.sqlite3"
            with CheckpointStore(path):
                pass

            blocker = sqlite3.connect(path, timeout=1.0)
            try:
                blocker.execute("BEGIN")
                blocker.execute("SELECT count(1) FROM ingestion_checkpoint").fetchone()
                result: dict[str, object] = {}

                def write_checkpoint() -> None:
                    try:
                        with CheckpointStore(path) as store:
                            result["checkpoint"] = store.start(
                                "goods_general",
                                "2026-01-01",
                                sink_target="typesense:test",
                            )
                    except BaseException as exc:  # pragma: no cover - assertion below reports it
                        result["error"] = exc

                worker = threading.Thread(target=write_checkpoint)
                worker.start()
                time.sleep(0.2)
                blocker.commit()
                worker.join(timeout=5.0)

                self.assertFalse(worker.is_alive())
                self.assertNotIn("error", result)
                self.assertEqual(result["checkpoint"].status, IngestionStatus.RUNNING)
            finally:
                blocker.close()

    def test_both_live_stores_configure_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = f"{temporary}/checkpoint.sqlite3"
            provenance_path = f"{temporary}/provenance.sqlite3"
            with CheckpointStore(checkpoint_path) as checkpoints:
                self.assertEqual(checkpoints._connection.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            with UUIDProvenanceStore(provenance_path) as provenance:
                self.assertEqual(provenance._connection.execute("PRAGMA busy_timeout").fetchone()[0], 30000)


if __name__ == "__main__":
    unittest.main()
