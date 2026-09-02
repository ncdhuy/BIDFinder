from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crawler_engine.msc.backfill import UUIDProvenanceStore
from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.contracts import (
    SOURCE_CONTRACTS,
    SOURCE_COVERAGE_FLOORS,
    expected_coverage_partition_count,
    expected_source_partition_count,
)
from crawler_engine.msc.models import IngestionStatus, PartitionContext, SearchInterval
from crawler_engine.msc.serving import (
    EXPECTED_HISTORICAL_GROUP_COUNTS,
    HISTORICAL_GENERATION,
    bootstrap_checkpoint,
    bootstrap_provenance,
    build_serving_report,
    clone_generation,
    retire_historical_generation,
    incremental_window,
    live_generations,
    require_serving_generation,
    safe_retire_generation,
    validate_prefix_range,
)
from crawler_engine.msc.typesense_schema import LOGICAL_ALIASES, collection_schema, physical_collection_name


class FakeTypesense:
    def __init__(self, generations: tuple[str, ...] = (HISTORICAL_GENERATION, "local_canary_20260831_29ef44")) -> None:
        self.collections: dict[str, dict] = {}
        self.documents: dict[str, dict[str, dict]] = {}
        for generation in generations:
            for group in LOGICAL_ALIASES:
                name = physical_collection_name(group, generation)
                schema = collection_schema(group, generation)
                schema["num_documents"] = 2
                self.collections[name] = schema
                self.documents[name] = {"u1": {"id": "u1", "data_group": group}}
        self.deleted: list[str] = []

    def get_collection(self, name: str):
        return self.collections.get(name)

    def list_collections(self):
        return list(self.collections.values())

    def clone_collection(self, source, destination, *, copy_documents=True, metadata=None):
        source_schema = self.collections[source]
        cloned = {**source_schema, "name": destination, "metadata": dict(metadata or source_schema["metadata"])}
        self.collections[destination] = cloned
        self.documents[destination] = dict(self.documents[source])
        return cloned

    def document_count(self, name):
        return int(self.collections[name]["num_documents"])

    def get_document(self, collection, document_id):
        return self.documents.get(collection, {}).get(document_id)

    def search_group(self, *_args, **_kwargs):
        return {"found": 2}

    def get_alias(self, _alias):
        return None

    def health(self):
        return {"ok": True, "version": "30.2"}

    def delete_collection(self, name):
        self.deleted.append(name)
        self.collections.pop(name, None)
        self.documents.pop(name, None)
        return {"name": name}


def _context(source_key: str, day: str) -> PartitionContext:
    contract = SOURCE_CONTRACTS[source_key]
    return PartitionContext(
        source_key, day, contract, SearchInterval("a", "b"), 1, 1, 1, 1, 1, 1,
        sink_target=f"typesense:{HISTORICAL_GENERATION}",
    )


class TestPhase3CServing(unittest.TestCase):
    def test_source_specific_coverage_registry_and_total(self):
        self.assertEqual(date(2022, 1, 1), SOURCE_COVERAGE_FLOORS["goods_general"])
        self.assertTrue(all(
            SOURCE_COVERAGE_FLOORS[key] == date(2023, 1, 1)
            for key in SOURCE_CONTRACTS
            if key != "goods_general"
        ))
        self.assertEqual(9738, expected_coverage_partition_count("2026-08-31"))
        self.assertEqual(0, expected_source_partition_count("medical_devices", "2022-12-31"))
        self.assertEqual(31, expected_source_partition_count("medicine_generic", "2023-01-31"))

    def test_prefix_range_guard_uses_one_registered_floor_and_boundary(self):
        self.assertEqual(
            ("goods_general",),
            validate_prefix_range(("goods_general",), "2022-01-01", "2023-01-31")[0],
        )
        self.assertEqual(
            set(SOURCE_CONTRACTS) - {"goods_general"},
            set(validate_prefix_range(
                tuple(key for key in SOURCE_CONTRACTS if key != "goods_general"),
                "2023-01-01", "2023-01-31",
            )[0]),
        )
        for args in (
            (("goods_general",), "2023-01-01", "2023-01-31"),
            (("goods_general", "medical_devices"), "2022-01-01", "2023-01-31"),
            (("goods_general",), "2022-01-01", "2023-02-01"),
        ):
            with self.assertRaises(ValueError):
                validate_prefix_range(*args)

    def test_serving_generation_guard_and_immutable_historical_guard(self):
        self.assertEqual("serving_v1_20260901", require_serving_generation("serving_v1_20260901"))
        for generation in (HISTORICAL_GENERATION, "local_canary_20260831_29ef44"):
            with self.assertRaises(ValueError):
                require_serving_generation(generation)

    def test_closed_day_boundary_and_bounded_lookback(self):
        with patch("crawler_engine.msc.serving.operational_today", return_value=date(2026, 9, 1)):
            requested, effective, end = incremental_window("2026-08-31", "2026-08-31", lookback_days=3)
            self.assertEqual((date(2026, 8, 31), date(2026, 8, 30), date(2026, 8, 31)), (requested, effective, end))
            with self.assertRaises(ValueError):
                incremental_window("2026-08-30", "2026-09-01")
            with self.assertRaises(ValueError):
                incremental_window("2026-08-29", "2026-08-30")

    def test_checkpoint_and_provenance_bootstrap_are_copies_with_remapped_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_checkpoint = root / "hist.sqlite3"
            serving_checkpoint = root / "serving.sqlite3"
            with CheckpointStore(source_checkpoint) as store:
                for source_key in SOURCE_CONTRACTS:
                    store.start(source_key, "2026-08-29", sink_target=f"typesense:{HISTORICAL_GENERATION}")
                    store.finish(
                        source_key, "2026-08-29", IngestionStatus.COMPLETED,
                        sink_target=f"typesense:{HISTORICAL_GENERATION}",
                        parent_pre_count=1, parent_post_count=1, raw_fetched_count=1,
                        unique_uuid_count=1, normalized_count=1, sink_accepted_count=1,
                    )
                self.assertEqual(7, len(store.list(f"typesense:{HISTORICAL_GENERATION}")))
            result = bootstrap_checkpoint(
                source_checkpoint, serving_checkpoint,
                serving_generation="serving_v1_20260901",
            )
            self.assertEqual(7, result["rows_remapped"])
            with CheckpointStore(serving_checkpoint) as store:
                self.assertEqual(7, len(store.list("typesense:serving_v1_20260901")))
                self.assertEqual(0, len(store.list(f"typesense:{HISTORICAL_GENERATION}")))

            source_provenance = root / "hist.uuid.sqlite3"
            serving_provenance = root / "serving.uuid.sqlite3"
            with UUIDProvenanceStore(source_provenance) as store:
                store.begin_partition(_context("goods_general", "2026-08-29"), [{"id": "u1"}])
                store.commit()
            result = bootstrap_provenance(source_provenance, serving_provenance, serving_generation="serving_v1_20260901")
            self.assertEqual(1, result["total"])
            self.assertEqual(0, result["conflicts"])

    def test_clone_parity_and_two_generation_retirement(self):
        with tempfile.TemporaryDirectory() as directory:
            provenance = Path(directory) / "provenance.sqlite3"
            with UUIDProvenanceStore(provenance) as store:
                store.begin_partition(_context("goods_general", "2026-08-29"), [{"id": "u1"}])
                store.commit()
            client = FakeTypesense()
            clone = clone_generation(
                client, HISTORICAL_GENERATION, "serving_v1_20260901",
                provenance_path=provenance, base_manifest_fingerprint="fingerprint",
            )
            self.assertTrue(all(item["parity"] for item in clone["groups"].values()))
            self.assertEqual(9, len(client.collections))
            retired = safe_retire_generation(client, "local_canary_20260831_29ef44")
            self.assertEqual(3, retired["deleted"])
            self.assertEqual((HISTORICAL_GENERATION, "serving_v1_20260901"), live_generations(client))

    def test_serving_report_serialization_and_expected_base_counts(self):
        report = build_serving_report(
            serving_generation="serving_v1_20260901",
            base_manifest_fingerprint="fingerprint",
            requested_range={"from": "2026-08-30", "to": "2026-08-31"},
            effective_range={"from": "2026-08-30", "to": "2026-08-31"},
            source_counts={"goods_general": 2},
            checkpoint_state={"completed_parent_partitions": 7},
            provenance_counts={"unique_total": 2},
            physical_counts=EXPECTED_HISTORICAL_GROUP_COUNTS,
            last_successful_run="2026-09-01T00:00:00+00:00",
        )
        encoded = json.dumps(report, sort_keys=True)
        self.assertIn("serving_v1_20260901", encoded)
        self.assertEqual(HISTORICAL_GENERATION, report["base_generation"])
        self.assertEqual(set(LOGICAL_ALIASES), set(report["physical_counts"]))

    def test_historical_retirement_guard_preserves_offline_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / "historical-final"
            serving = root / "serving-final"
            (historical / "typesense-snapshot" / "state").mkdir(parents=True)
            serving.mkdir()
            (historical / "bundle.json").write_text("{}", encoding="utf-8")
            (serving / "bundle.json").write_text("{}", encoding="utf-8")
            client = FakeTypesense((HISTORICAL_GENERATION, "serving_v1_20260901"))
            with self.assertRaises(ValueError):
                retire_historical_generation(
                    client,
                    historical_bundle=historical,
                    serving_bundle=serving,
                    serving_generation="serving_v1_20260901",
                )
            self.assertTrue(historical.is_dir())
            self.assertEqual([], client.deleted)

    def test_one_live_generation_inventory(self):
        client = FakeTypesense(("serving_v1_20260901",))
        self.assertEqual(("serving_v1_20260901",), live_generations(client))


if __name__ == "__main__":
    unittest.main()
