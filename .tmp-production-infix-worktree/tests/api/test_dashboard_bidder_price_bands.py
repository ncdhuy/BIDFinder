from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_shadow import (  # noqa: E402
    aggregate_dashboard_documents,
    build_dashboard_bidder_price_bands,
    cluster_dashboard_price_levels,
)


def make_row(
    row_id,
    *,
    bidder="bidder-a",
    bidder_name=None,
    product="Sản phẩm A",
    unit="viên",
    price=1_000,
    package=None,
    value=100,
):
    return {
        "id": row_id,
        "medicine_name": product,
        "unit": unit,
        "winning_unit_price": price,
        "winning_bidder_id": [bidder],
        "winning_bidder_name": [bidder_name or bidder],
        "bid_invitation_code": package or f"PKG-{row_id}",
        "total_value": value,
    }


class DashboardBidderPriceBandsTest(unittest.TestCase):
    def test_close_observed_prices_form_one_adaptive_band(self):
        prices = [980, 981, 990, 999, 1_000, 1_005]
        self.assertEqual([prices], cluster_dashboard_price_levels(prices))

    def test_separated_price_levels_remain_separate(self):
        self.assertEqual([[1_000], [1_100], [10_000]], cluster_dashboard_price_levels([1_000, 1_100, 10_000]))

    def test_relative_clustering_is_scale_independent(self):
        from decimal import Decimal

        prices = [Decimal("0.98"), Decimal("0.981"), Decimal("0.99"), Decimal("0.999"), Decimal("1.005")]
        low_scale = cluster_dashboard_price_levels(prices)
        high_scale = cluster_dashboard_price_levels([price * Decimal("1e9") for price in prices])
        self.assertEqual([len(cluster) for cluster in low_scale], [len(cluster) for cluster in high_scale])
        self.assertEqual([5], [len(cluster) for cluster in low_scale])

    def test_chaining_cannot_create_a_band_wider_than_five_percent(self):
        clusters = cluster_dashboard_price_levels([1_000, 1_010, 1_020, 1_030, 1_040, 1_050, 1_060, 1_070])
        self.assertTrue(all(cluster[-1] / cluster[0] <= 1.05 for cluster in clusters))
        self.assertGreater(len(clusters), 1)

    def test_identical_prices_are_collapsed_before_clustering(self):
        self.assertEqual([[1_000], [2_000]], cluster_dashboard_price_levels([1_000, 1_000, 1_000, 2_000]))

    def test_invalid_prices_are_excluded(self):
        self.assertEqual([[1_000]], cluster_dashboard_price_levels([None, 0, -1, "NaN", "bad", 1_000]))

    def test_distinct_win_count_and_band_value_use_existing_package_semantics(self):
        first = make_row("r1", package="P1", price=980, value=100)
        rows = [
            first,
            dict(first),  # repeated document ID must not inflate either count or value
            make_row("r2", package="P1", price=981, value=50),
            make_row("r3", package="P2", price=990, value=200),
        ]
        result = aggregate_dashboard_documents({"medicines": rows}, selected_product="Sản phẩm A")
        band = result["bidder_price_band_analysis"]["items"][0]
        self.assertEqual(2, band["distinct_win_count"])
        self.assertEqual(350, band["corresponding_awarded_value"])
        self.assertEqual(980, band["price_min"])
        self.assertEqual(990, band["price_max"])
        self.assertEqual(985.25, band["median_price"])

    def test_best_band_is_selected_by_distinct_wins_not_all_bidder_money(self):
        rows = [
            make_row("a1", price=980, package="A1", value=10),
            make_row("a2", price=990, package="A2", value=10),
            make_row("a3", price=20_000, package="A3", value=1),
            make_row("a4", price=20_500, package="A4", value=1),
            make_row("a5", price=21_000, package="A5", value=1),
        ]
        result = aggregate_dashboard_documents({"medicines": rows}, selected_product="Sản phẩm A")
        band = result["bidder_price_band_analysis"]["items"][0]
        self.assertEqual(3, band["distinct_win_count"])
        self.assertEqual(3, band["corresponding_awarded_value"])
        self.assertEqual(20_000, band["price_min"])

    def test_case_variant_bidder_names_with_different_ids_are_one_cross_filter_row(self):
        rows = [
            make_row("upper", bidder="vendor-1", bidder_name="CÔNG TY CỔ PHẦN DƯỢC A", package="P1", price=980, value=100),
            make_row("mixed", bidder="vendor-2", bidder_name="Công ty cổ phần dược a", package="P2", price=1_005, value=200),
        ]

        result = aggregate_dashboard_documents(
            {"medicines": rows},
            selected_bidder="Công ty cổ phần Dược A",
        )
        items = result["bidder_price_band_analysis"]["items"]

        self.assertEqual(1, len(items))
        self.assertEqual(2, items[0]["distinct_win_count"])
        self.assertEqual(300, items[0]["corresponding_awarded_value"])
        self.assertEqual(980, items[0]["price_min"])
        self.assertEqual(1_005, items[0]["price_max"])

    def test_top_five_rank_by_band_win_count_then_value_then_name(self):
        rows = []
        for bidder, count, value in [
            ("Zulu", 3, 10),
            ("Bravo", 4, 1),
            ("Alpha", 3, 10),
            ("Charlie", 2, 1),
            ("Delta", 1, 1),
            ("Echo", 1, 1),
        ]:
            for index in range(count):
                rows.append(make_row(
                    f"{bidder}-{index}", bidder=bidder, bidder_name=bidder,
                    package=f"{bidder}-P{index}", price=1_000, value=value,
                ))
        items = aggregate_dashboard_documents({"medicines": rows}, selected_product="Sản phẩm A")["bidder_price_band_analysis"]["items"]
        self.assertEqual(["Bravo", "Alpha", "Zulu", "Charlie", "Delta"], [item["bidder_name"] for item in items])
        self.assertEqual([4, 3, 3, 2, 1], [item["distinct_win_count"] for item in items])

    def test_corresponding_band_value_breaks_equal_win_count_ties(self):
        rows = [
            make_row("low-1", bidder="Alpha", bidder_name="Alpha", package="A1", value=1),
            make_row("low-2", bidder="Alpha", bidder_name="Alpha", package="A2", value=1),
            make_row("high-1", bidder="Zulu", bidder_name="Zulu", package="Z1", value=500),
            make_row("high-2", bidder="Zulu", bidder_name="Zulu", package="Z2", value=500),
        ]
        items = aggregate_dashboard_documents({"medicines": rows}, selected_product="Sản phẩm A")["bidder_price_band_analysis"]["items"]
        self.assertEqual(["Zulu", "Alpha"], [item["bidder_name"] for item in items])

    def test_incompatible_units_stay_separate_without_requiring_product_selection(self):
        rows = [
            make_row("tablet", unit="viên", price=1_000, value=100),
            make_row("box", unit="hộp", price=1_001, value=900),
        ]
        mixed = aggregate_dashboard_documents({"medicines": rows})["bidder_price_band_analysis"]
        self.assertNotIn("requires_product_selection", mixed)
        self.assertEqual(1, len(mixed["items"]))
        self.assertEqual(1, mixed["items"][0]["distinct_win_count"])
        self.assertEqual(1_001, mixed["items"][0]["price_min"])
        self.assertEqual(900, mixed["items"][0]["corresponding_awarded_value"])
        self.assertEqual("hộp", mixed["items"][0]["unit"])

    def test_mixed_products_show_best_band_and_selected_product_still_filters(self):
        rows = [make_row("a", product="Sản phẩm A"), make_row("b", product="Sản phẩm B", price=2_000)]
        mixed = aggregate_dashboard_documents({"medicines": rows})["bidder_price_band_analysis"]
        self.assertNotIn("requires_product_selection", mixed)
        self.assertEqual(1, len(mixed["items"]))
        self.assertEqual(1_000, mixed["items"][0]["price_min"])
        selected = aggregate_dashboard_documents({"medicines": rows}, selected_product="Sản phẩm B")["bidder_price_band_analysis"]
        self.assertEqual(1, len(selected["items"]))
        self.assertEqual(2_000, selected["items"][0]["price_min"])

    def test_helper_deduplicates_record_identity_and_ranks_tied_bidders_stably(self):
        observations = []
        for key, name, package, value in [
            ("z", "Zulu", "Z1", 50),
            ("z", "Zulu", "Z2", 50),
            ("a", "Alpha", "A1", 50),
            ("a", "Alpha", "A2", 50),
        ]:
            observations.append({
                "bidder_key": key, "bidder_name": name, "product": "Sản phẩm A", "unit": "viên",
                "unit_price": 1_000, "package_key": package, "record_key": package, "awarded_value": value,
            })
        observations.append(dict(observations[0]))
        result = build_dashboard_bidder_price_bands(observations)
        self.assertEqual(["Alpha", "Zulu"], [item["bidder_name"] for item in result["items"]])
        self.assertEqual([2, 2], [item["distinct_win_count"] for item in result["items"]])


if __name__ == "__main__":
    unittest.main()
