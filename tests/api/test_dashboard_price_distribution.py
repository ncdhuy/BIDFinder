from decimal import Decimal
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
        prices = [1_800, 3_900, 5_000, 10_000, 25_000, 50_000, 100_000, 200_000, 500_000, 1_059_376]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual(7, len(result["bins"]))
        self.assertEqual(len(prices), sum(bucket["count"] for bucket in result["bins"]))
        self.assertEqual(0, result["bins"][0]["min"])
        self.assertGreaterEqual(result["bins"][-1]["max"], 1_059_376)
        self.assertEqual(
            [bucket["max"] for bucket in result["bins"][:-1]],
            [bucket["min"] for bucket in result["bins"][1:]],
        )
        cut_points = [bucket["max"] for bucket in result["bins"][:-1]]
        for cut_point in cut_points:
            magnitude = Decimal(10) ** (Decimal(str(cut_point)).adjusted())
            self.assertIn(Decimal(str(cut_point)) / magnitude, {Decimal(1), Decimal(2), Decimal(5)})

    def test_extreme_outlier_does_not_stretch_core_price_ranges(self):
        result = build_dashboard_price_distribution([3_900] * 100 + [1_000_000_000_000])

        self.assertEqual(7, len(result["bins"]))
        self.assertEqual(1, result["bins"][-1]["count"])
        self.assertEqual(100, sum(bucket["count"] for bucket in result["bins"][:-1]))

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
        self.assertEqual(7, len(result["bins"]))
        self.assertEqual(1, sum(bucket["count"] for bucket in result["bins"]))

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

        base = aggregate_dashboard_documents({"medicines": documents})["unit_price_distribution"]
        selected = aggregate_dashboard_documents({
            "medicines": [row for row in documents if row["medicine_name"] == selection["product"]]
        })["unit_price_distribution"]

        self.assertEqual(3, base["statistics"]["count"])
        self.assertEqual(2, selected["statistics"]["count"])
        self.assertEqual(15, selected["statistics"]["mean"])
        self.assertNotEqual(base["statistics"]["mean"], selected["statistics"]["mean"])
        self.assertEqual(3, sum(bucket["count"] for bucket in base["bins"]))
        self.assertEqual(2, sum(bucket["count"] for bucket in selected["bins"]))


if __name__ == "__main__":
    unittest.main()
