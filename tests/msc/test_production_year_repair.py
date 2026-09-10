import tempfile
import unittest
from pathlib import Path

from crawler_engine.msc.models import SearchInterval
from crawler_engine.msc.production_year_repair import (
    CurrentYearIndex,
    RepairState,
    _observation_for_page,
    current_year_is_missing_or_corrupt,
    group_goods_partitions,
    repair_decision,
    source_production_year,
)
from crawler_engine.msc.typesense_client import ImportResult


class FakeTypesense:
    def __init__(self):
        self.calls = []

    def import_documents(self, collection, documents, *, action):
        self.calls.append((collection, [dict(item) for item in documents], action))
        return ImportResult(len(documents), len(documents), 0)


class ProductionYearRepairTests(unittest.TestCase):
    def test_source_year_and_range_are_preserved_by_current_contract(self):
        self.assertEqual("2024", source_production_year("goods_general", {"id": "a", "namSanXuat": "2024"}))
        self.assertEqual("2024-2025", source_production_year("goods_general", {"id": "b", "namSanXuat": "2024-2025"}))

    def test_empty_source_value_is_skipped(self):
        self.assertIsNone(source_production_year("goods_general", {"id": "a", "namSanXuat": None}))
        self.assertIsNone(source_production_year("goods_general", {"id": "b", "namSanXuat": ""}))

    def test_valid_current_value_is_not_replaced_when_source_differs(self):
        self.assertFalse(current_year_is_missing_or_corrupt("2024"))
        self.assertEqual(("current_valid_different", False), repair_decision("2024-2025", "2024"))
        self.assertEqual(("already_correct", False), repair_decision("2024-2025", "2024-2025"))

    def test_missing_or_corrupt_value_produces_only_production_year_patch(self):
        self.assertTrue(current_year_is_missing_or_corrupt(None))
        self.assertTrue(current_year_is_missing_or_corrupt("0"))
        self.assertTrue(current_year_is_missing_or_corrupt("not-a-year"))
        with tempfile.TemporaryDirectory() as temporary:
            index_path = Path(temporary) / "current.sqlite3"
            with CurrentYearIndex(index_path) as index:
                index.connection.execute("INSERT INTO current_year(id,production_year) VALUES(?,?)", ("a", None))
                index.connection.commit()
                fake = FakeTypesense()
                stats = __import__(
                    "crawler_engine.msc.production_year_repair",
                    fromlist=["RepairStats"],
                ).RepairStats()
                observation = _observation_for_page(
                    fake, "goods", index, "goods_general", "2024-01-01",
                    [{"id": "a", "namSanXuat": "2024-2025"}], set(), {},
                    dry_run=False, batch_size=500, stats=stats,
                )
                self.assertEqual(1, observation["actual_typesense_updates"])
                self.assertEqual([("goods", [{"id": "a", "production_year": "2024-2025"}], "update")], fake.calls)
                self.assertEqual({"id", "production_year"}, set(fake.calls[0][1][0]))

    def test_checkpoint_resume_and_idempotent_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "repair.sqlite3"
            leaf = SearchInterval("2024-01-01T00:00:00.000Z", "2024-01-01T00:00:01.000Z", expected_count=1)
            with RepairState(state_path) as state:
                state.mark_page("goods_general", "2024-01-01", 0, 0, leaf, 1, {"source_rows_scanned": 1})
                self.assertTrue(state.page_done("goods_general", "2024-01-01", 0, 0, leaf))
                self.assertFalse(state.page_done("goods_general", "2024-01-01", 1, 0, leaf))
            index_path = Path(temporary) / "current.sqlite3"
            with CurrentYearIndex(index_path) as index:
                index.connection.execute("INSERT INTO current_year(id,production_year) VALUES(?,?)", ("a", None))
                index.connection.commit()
                fake = FakeTypesense()
                from crawler_engine.msc.production_year_repair import RepairStats

                first = _observation_for_page(
                    fake, "goods", index, "goods_general", "2024-01-01",
                    [{"id": "a", "namSanXuat": "2024"}], set(), {},
                    dry_run=False, batch_size=500, stats=RepairStats(),
                )
                second = _observation_for_page(
                    fake, "goods", index, "goods_general", "2024-01-01",
                    [{"id": "a", "namSanXuat": "2024"}], set(), {},
                    dry_run=False, batch_size=500, stats=RepairStats(),
                )
                self.assertEqual(1, first["actual_typesense_updates"])
                self.assertEqual(0, second["actual_typesense_updates"])
                self.assertEqual(1, len(fake.calls))

    def test_adjacent_source_days_are_coalesced_with_a_bounded_count(self):
        groups = group_goods_partitions([
            ("goods_general", "2024-01-01", 4_000),
            ("goods_general", "2024-01-02", 4_000),
            ("goods_general", "2024-01-03", 4_000),
            ("goods_general", "2024-01-05", 1_000),
        ], max_rows=9_500)
        self.assertEqual(3, len(groups))
        self.assertEqual("2024-01-01..2024-01-02", groups[0][1])
        self.assertEqual(8_000, groups[0][3])
        self.assertEqual("2024-01-03", groups[1][1])
        self.assertEqual("2024-01-05", groups[2][1])


if __name__ == "__main__":
    unittest.main()
