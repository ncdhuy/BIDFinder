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
    def assert_distribution_is_complete(self, result):
        self.assertEqual(result["statistics"]["count"], sum(bin_item["count"] for bin_item in result["bins"]))
        self.assertTrue(all(bin_item["count"] > 0 for bin_item in result["bins"]))
        core_bins = [bin_item for bin_item in result["bins"] if bin_item["kind"] != "outside_core"]
        self.assertTrue(core_bins)
        self.assertGreaterEqual(result["core_interval"]["count"], result["statistics"]["count"] * 0.99)
        if result["mode"] == "histogram":
            self.assertTrue(all(bin_item["kind"] == "histogram" for bin_item in core_bins))
            self.assertTrue(all(
                left["max"] <= right["min"]
                for left, right in zip(core_bins, core_bins[1:])
            ))

    def test_normal_broad_distribution_uses_adaptive_log_histogram(self):
        prices = [
            1_000, 1_200, 1_500, 2_000, 2_500, 3_000, 4_000, 5_000, 7_000, 10_000,
            15_000, 20_000, 30_000, 50_000, 80_000, 120_000, 200_000, 300_000, 500_000, 800_000,
        ]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("histogram", result["mode"])
        self.assertGreaterEqual(len(result["bins"]), 5)
        self.assertLessEqual(len(result["bins"]), 8)
        self.assert_distribution_is_complete(result)
        widths = [bin_item["max"] / bin_item["min"] for bin_item in result["bins"]]
        self.assertGreater(max(widths), min(widths))

    def test_highly_right_skewed_distribution_keeps_extreme_value_outside_core(self):
        prices = [index * 1_000 for index in range(1, 101)] + [10**12]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("histogram", result["mode"])
        self.assertEqual(100, result["core_interval"]["count"])
        self.assertEqual(10**12, result["statistics"]["max"])
        self.assertEqual(1, result["bins"][-1]["count"])
        self.assertEqual("outside_core", result["bins"][-1]["kind"])
        self.assert_distribution_is_complete(result)

    def test_equal_quartiles_use_observed_point_mass_levels(self):
        prices = [1_300] * 10 + [1_800, 2_500, 5_000]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("point_mass", result["mode"])
        self.assertEqual(1_300, result["statistics"]["p25"])
        self.assertEqual(1_300, result["statistics"]["median"])
        self.assertEqual(1_300, result["statistics"]["p75"])
        self.assertEqual([1_300, 1_800, 2_500, 5_000], [bin_item["min"] for bin_item in result["bins"]])
        self.assert_distribution_is_complete(result)

    def test_dominant_exact_price_is_grouped_without_losing_other_levels(self):
        prices = [1_300] * 50 + [1_500, 1_600, 1_700, 2_000, 2_500, 3_000, 5_000]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("point_mass", result["mode"])
        self.assertEqual(50, result["bins"][0]["count"])
        self.assertEqual(1_300, result["bins"][0]["min"])
        self.assertTrue(all(bin_item["count"] > 0 for bin_item in result["bins"]))
        self.assert_distribution_is_complete(result)

    def test_point_mass_residual_price_levels_are_aggregated_as_other(self):
        prices = [1_300] * 30 + [1_400, 1_500, 1_600, 1_700, 1_800, 1_900, 2_000, 2_100, 2_200, 2_300]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("point_mass", result["mode"])
        self.assertEqual(6, len(result["bins"]))
        other = next(bin_item for bin_item in result["bins"] if bin_item["kind"] == "other")
        self.assertEqual(6, other["count"])
        self.assert_distribution_is_complete(result)

    def test_two_to_five_distinct_prices_render_only_observed_levels(self):
        for prices in ([100, 100, 200], [100, 100, 200, 300, 400, 500, 500]):
            with self.subTest(unique=len(set(prices))):
                result = build_dashboard_price_distribution(prices)
                self.assertEqual("point_mass", result["mode"])
                self.assertEqual(len(set(prices)), len(result["bins"]))
                self.assertEqual(sorted(set(prices)), [bin_item["min"] for bin_item in result["bins"]])
                self.assert_distribution_is_complete(result)

    def test_huge_max_does_not_stretch_core_and_raw_statistics_remain_exact(self):
        prices = [3_900] * 100 + [10**15]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual(3_900, result["core_interval"]["min"])
        self.assertEqual(3_900, result["core_interval"]["max"])
        self.assertEqual(10**15, result["statistics"]["max"])
        self.assertEqual((sum(prices) / len(prices)), result["statistics"]["mean"])
        self.assertEqual(10**15, result["bins"][-1]["outlier_max"])
        self.assert_distribution_is_complete(result)

    def test_many_outliers_are_preserved_in_one_outside_core_bucket(self):
        prices = [index * 1_000 for index in range(1, 1001)]
        prices.extend([1] * 6)
        prices.extend([10**12 + index for index in range(6)])
        result = build_dashboard_price_distribution(prices)

        outside = result["bins"][-1]
        self.assertEqual("outside_core", outside["kind"])
        self.assertGreaterEqual(outside["count"], 6)
        actual_outside = [
            price for price in prices
            if price < result["core_interval"]["min"] or price > result["core_interval"]["max"]
        ]
        self.assertEqual(min(actual_outside), outside["outlier_min"])
        self.assertEqual(max(actual_outside), outside["outlier_max"])
        self.assertEqual(10**12 + 5, outside["outlier_max"])
        self.assert_distribution_is_complete(result)

    def test_no_outliers_leaves_no_empty_outside_category(self):
        result = build_dashboard_price_distribution([index * 1_000 for index in range(1, 21)])

        self.assertFalse(any(bin_item["kind"] == "outside_core" for bin_item in result["bins"]))
        self.assert_distribution_is_complete(result)

    def test_empty_intermediate_histogram_ranges_are_merged(self):
        prices = [1_000, 1_100, 1_200, 1_300, 1_400, 1_500]
        prices += [100_000, 110_000, 120_000, 130_000, 140_000, 150_000]
        prices += [10_000_000, 11_000_000, 12_000_000, 13_000_000, 14_000_000, 15_000_000]
        result = build_dashboard_price_distribution(prices)

        self.assertEqual("histogram", result["mode"])
        self.assertEqual(3, len(result["bins"]))
        self.assertEqual([6, 6, 6], [bin_item["count"] for bin_item in result["bins"]])
        self.assert_distribution_is_complete(result)

    def test_invalid_and_empty_prices_are_excluded(self):
        result = build_dashboard_price_distribution([None, True, "invalid", "NaN", "Infinity", 0, -4, 12])
        self.assertEqual(1, result["statistics"]["count"])
        self.assertEqual(12, result["statistics"]["min"])
        self.assertEqual(12, result["statistics"]["max"])
        self.assertEqual(1, sum(bin_item["count"] for bin_item in result["bins"]))
        self.assertEqual({"mode": None, "core_interval": None, "statistics": None, "bins": []},
                         build_dashboard_price_distribution([None, 0, -1]))

    def test_statistics_keep_interpolated_quartiles_and_full_raw_range(self):
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
        self.assertEqual(3, sum(bin_item["count"] for bin_item in base["bins"]))
        self.assertEqual(2, sum(bin_item["count"] for bin_item in selected["bins"]))


if __name__ == "__main__":
    unittest.main()
