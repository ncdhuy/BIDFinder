import json
import unittest

from crawler_engine.msc.backfill import load_fixture_samples
from crawler_engine.msc.sizing import (
    FULL_DATASET_DOCUMENTS,
    SIZING_SAMPLE_MAXIMUM,
    capacity_decision,
    bytes_per_document,
    deterministic_sample_plan,
    empirical_projection,
    enforce_sample_maximum,
    field_size_contributions,
    growth_scenarios,
    linear_slope,
    serialize_report,
    subtract_baseline,
)


class TypesenseSizingTest(unittest.TestCase):
    def test_baseline_and_bytes_per_document(self):
        self.assertEqual(subtract_baseline(150, 50), 100)
        self.assertEqual(bytes_per_document(1_050, 200, baseline_bytes=50, baseline_documents=0), 5)
        with self.assertRaises(ValueError):
            bytes_per_document(100, 0)

    def test_linear_slope_and_projection_methods(self):
        self.assertEqual(linear_slope(((0, 10), (10, 30), (20, 50)))["bytes_per_document"], 2)
        result = empirical_projection(
            (
                {"documents": 0, "ram": 100},
                {"documents": 50, "ram": 200},
                {"documents": 100, "ram": 300},
            ),
            200,
            metric="ram",
        )
        self.assertEqual(result["largest_sample"]["projected_bytes"], 400)
        self.assertEqual(result["regression"]["projected_bytes"], 400)

    def test_growth_scenarios(self):
        result = growth_scenarios(100, 2, 3)
        self.assertEqual([item["documents"] for item in result], [100, 120, 150])
        self.assertEqual(result[-1]["projected_ram_bytes"], 300)
        self.assertEqual(result[-1]["projected_disk_bytes"], 450)

    def test_capacity_decision_uses_seventy_percent_and_ignores_swap(self):
        passing = capacity_decision(22 * 1024**3)
        failing = capacity_decision(23 * 1024**3)
        self.assertEqual(passing["decision"], "PASS")
        self.assertEqual(failing["decision"], "FAIL")
        self.assertFalse(failing["swap_counted"])

    def test_deterministic_sample_plan_and_maximum_guard(self):
        quotas = {
            "goods_general": 390_000,
            "medical_devices": 35_000,
            "medicine_generic": 40_000,
            "medicine_originator": 5_000,
            "medicine_herbal": 10_000,
            "herbal_material": 10_000,
            "traditional_medicine": 10_000,
        }
        first = deterministic_sample_plan(source_quotas=quotas)
        second = deterministic_sample_plan(source_quotas=quotas)
        self.assertEqual(first, second)
        self.assertEqual(tuple(first["date_selection"]["dates_by_year"]), ("2023", "2024", "2025", "2026"))
        with self.assertRaises(ValueError):
            deterministic_sample_plan(source_quotas={"goods_general": SIZING_SAMPLE_MAXIMUM + 1})
        enforce_sample_maximum(SIZING_SAMPLE_MAXIMUM)
        with self.assertRaises(ValueError):
            enforce_sample_maximum(SIZING_SAMPLE_MAXIMUM + 1)

    def test_field_size_contributions_rank_index_input(self):
        samples = load_fixture_samples(sample_limit=1)
        result = field_size_contributions({"goods": samples["goods_general"]})
        self.assertTrue(result)
        self.assertGreaterEqual(result[0]["percentage"], result[-1]["percentage"])
        self.assertTrue(all(item["serialized_index_input_bytes"] > 0 for item in result))

    def test_report_serialization_is_valid_and_stable(self):
        payload = {"version": "test", "documents": FULL_DATASET_DOCUMENTS}
        serialized = serialize_report(payload)
        self.assertEqual(json.loads(serialized), payload)
        self.assertTrue(serialized.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
