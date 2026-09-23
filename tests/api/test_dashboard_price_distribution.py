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
        self.assertEqual(result["display_cutoff"], result["bins"][-2]["max"])
        self.assertEqual(result["display_cutoff"], result["bins"][-1]["min"])
        self.assertTrue(result["bins"][-1]["overflow"])
        self.assertEqual(
            [bucket["max"] for bucket in result["bins"][:-1]],
            [bucket["min"] for bucket in result["bins"][1:]],
        )
        outliers = [price for price in prices if price > result["display_cutoff"]]
        self.assertEqual(min(outliers), result["bins"][-1]["outlier_min"])
        self.assertEqual(max(outliers), result["bins"][-1]["outlier_max"])

    def test_broad_distribution_uses_robust_cutoff_and_rounded_core_ranges(self):
        result = build_dashboard_price_distribution([1_000, 2_000, 3_000, 5_000, 10_000, 20_000, 1_000_000_000_000])

        # The raw Q3 + 3×IQR fence is 52,500; P99 caps it before the remote maximum.
        self.assertLessEqual(result["display_cutoff"], 52_500)
        self.assertGreater(result["display_cutoff"], 20_000)
        self.assertEqual(result["display_cutoff"], result["bins"][-2]["max"])
        self.assertEqual(1, result["bins"][-1]["count"])
        self.assertEqual(6, sum(bucket["count"] for bucket in result["bins"][:-1]))

    def test_zero_iqr_mode_builds_bins_around_dense_price_region_and_keeps_raw_stats(self):
        prices = [1_300] * 886 + [2_000_000, 10_000_000, 894_600_000]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual(0, result["statistics"]["iqr"])
        self.assertEqual(894_600_000, result["statistics"]["max"])
        self.assertAlmostEqual(sum(prices) / len(prices), result["statistics"]["mean"])
        self.assertEqual([1_000, 1_200, 1_400, 2_000, 5_000, 20_000], [bucket["max"] for bucket in result["bins"][:6]])
        self.assertEqual(886, result["bins"][2]["count"])
        self.assertEqual(3, result["bins"][-1]["count"])
        self.assertEqual(2_000_000, result["bins"][-1]["outlier_min"])
        self.assertEqual(894_600_000, result["bins"][-1]["outlier_max"])

    def test_dominant_exact_price_mode_uses_mode_aware_core_even_with_nonzero_iqr(self):
        result = build_dashboard_price_distribution([1_300] * 6 + [1_400, 1_600, 2_000, 3_000, 10_000])

        self.assertGreater(result["statistics"]["iqr"], 0)
        self.assertEqual(6, result["bins"][2]["count"])
        self.assertEqual(20_000, result["display_cutoff"])

    def test_dominant_narrow_price_region_uses_local_core_bins(self):
        prices = [1_200, 1_250, 1_300, 1_350, 1_400] * 2 + [5_000, 10_000]
        result = build_dashboard_price_distribution(prices)

        self.assertGreater(result["statistics"]["iqr"], 0)
        self.assertEqual([1_000, 1_200, 1_400, 2_000, 5_000, 20_000], [bucket["max"] for bucket in result["bins"][:6]])
        self.assertEqual(10, sum(bucket["count"] for bucket in result["bins"][1:4]))

    def test_extreme_outlier_does_not_stretch_core_price_ranges(self):
        result = build_dashboard_price_distribution([3_900] * 100 + [1_000_000_000_000])

        self.assertEqual(7, len(result["bins"]))
        self.assertEqual(100_000, result["display_cutoff"])
        self.assertEqual([3_000, 3_800, 4_000, 5_000, 20_000, 100_000], [bucket["max"] for bucket in result["bins"][:6]])
        self.assertTrue(result["bins"][-1]["overflow"])
        self.assertEqual(1, result["bins"][-1]["count"])
        self.assertEqual(1_000_000_000_000, result["bins"][-1]["outlier_min"])
        self.assertEqual(100, sum(bucket["count"] for bucket in result["bins"][:-1]))

    def test_normal_distribution_remains_six_core_bins_plus_overflow(self):
        prices = list(range(1_000, 31_000, 1_000))
        result = build_dashboard_price_distribution(prices)

        self.assertEqual(7, len(result["bins"]))
        self.assertEqual(len(prices), sum(bucket["count"] for bucket in result["bins"]))
        self.assertEqual(6, len(result["bins"][:-1]))
        self.assertTrue(result["bins"][-1]["overflow"])
        self.assertLess(result["display_cutoff"], max(prices))

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
