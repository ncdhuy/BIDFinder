from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_shadow import (  # noqa: E402
    aggregate_dashboard_documents,
    build_dashboard_price_distribution,
    build_dashboard_selection_clauses,
)


class DashboardPriceDistributionTest(unittest.TestCase):
    def test_histogram_bins_cover_all_valid_observations(self):
        result = build_dashboard_price_distribution([10, 20, 30, 40, 50, 60, 70, 80])

        self.assertGreater(len(result["bins"]), 1)
        self.assertLessEqual(len(result["bins"]), 16)
        self.assertEqual(8, sum(bucket["count"] for bucket in result["bins"]))
        self.assertEqual(10, result["bins"][0]["min"])
        self.assertEqual(80, result["bins"][-1]["max"])

    def test_statistics_use_interpolated_quartiles(self):
        result = build_dashboard_price_distribution([10, 20, 30, 40])

        self.assertEqual({
            "count": 4,
            "mean": 25,
            "median": 25,
            "p25": 17.5,
            "p75": 32.5,
            "iqr": 15,
            "min": 10,
            "max": 40,
        }, result["statistics"])

    def test_invalid_and_non_positive_prices_are_excluded(self):
        result = build_dashboard_price_distribution([None, True, "invalid", "NaN", "Infinity", 0, -4, 12])

        self.assertEqual(1, result["statistics"]["count"])
        self.assertEqual(12, result["statistics"]["min"])
        self.assertEqual(12, result["statistics"]["max"])
        self.assertEqual(1, result["bins"][0]["count"])

    def test_empty_distribution_has_no_stats_or_bins(self):
        self.assertEqual({"statistics": None, "bins": []}, build_dashboard_price_distribution([None, 0, -1]))

    def test_distribution_recomputes_for_dashboard_selection_universe(self):
        documents = [
            {"id": "a", "medicine_name": "Nefopam", "winning_unit_price": 10},
            {"id": "b", "medicine_name": "Nefopam", "winning_unit_price": 20},
            {"id": "c", "medicine_name": "Paracetamol", "winning_unit_price": 100},
        ]
        selection = {"product": "Nefopam", "province": "Hà Nội", "investor": "Bệnh viện A"}
        self.assertEqual(3, len(build_dashboard_selection_clauses("medicines", selection)))

        base = aggregate_dashboard_documents({"medicines": documents})["unit_price_distribution"]["statistics"]
        selected = aggregate_dashboard_documents({
            "medicines": [row for row in documents if row["medicine_name"] == selection["product"]]
        })["unit_price_distribution"]["statistics"]

        self.assertEqual(3, base["count"])
        self.assertEqual(2, selected["count"])
        self.assertEqual(15, selected["mean"])
        self.assertNotEqual(base["mean"], selected["mean"])


if __name__ == "__main__":
    unittest.main()
