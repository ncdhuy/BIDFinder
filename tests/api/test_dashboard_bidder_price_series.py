from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_shadow import (  # noqa: E402
    aggregate_dashboard_documents,
    build_dashboard_bidder_price_series,
    build_dashboard_selection_clauses,
)


def _row(row_id, bidder_id, bidder_name, unit_price, total_value, package):
    return {
        "id": row_id,
        "total_value": total_value,
        "winning_unit_price": unit_price,
        "winning_bidder_id": [bidder_id],
        "winning_bidder_name": [bidder_name],
        "bid_invitation_code": package,
    }


class DashboardBidderPriceSeriesTest(unittest.TestCase):
    def test_top_five_bidders_aggregate_exact_prices_in_ascending_order(self):
        documents = {
            "medicines": [
                _row("a1", "b1", "Alpha", 100, 200, "P1"),
                _row("a2", "b1", "Alpha", 100, 100, "P2"),
                _row("a3", "b1", "Alpha", 50, 50, "P1"),
                _row("b1", "b2", "Beta", 200, 250, "P3"),
                _row("c1", "b3", "Gamma", 300, 200, "P4"),
                _row("d1", "b4", "Delta", 400, 150, "P5"),
                _row("e1", "b5", "Epsilon", 500, 120, "P6"),
                _row("f1", "b6", "Zeta", 600, 80, "P7"),
            ],
        }

        result = aggregate_dashboard_documents(documents)
        series = result["bidder_unit_price_series"]

        self.assertEqual(["Alpha", "Beta", "Gamma", "Delta", "Epsilon"], [item["name"] for item in series])
        self.assertEqual([50, 100], [point["unit_price"] for point in series[0]["points"]])
        self.assertEqual([50, 300], [point["total_awarded_value"] for point in series[0]["points"]])
        self.assertEqual(2, series[0]["points"][1]["occurrence_count"])
        self.assertEqual(2, series[0]["points"][1]["package_count"])
        self.assertNotIn("unit_price_distribution", result)

    def test_invalid_or_non_positive_unit_prices_are_excluded(self):
        result = aggregate_dashboard_documents({
            "goods": [
                _row("valid", "b1", "Alpha", 10, 100, "P1"),
                _row("zero", "b1", "Alpha", 0, 100, "P2"),
                _row("negative", "b1", "Alpha", -5, 100, "P3"),
                _row("invalid", "b1", "Alpha", "not-a-price", 100, "P4"),
                _row("missing", "b1", "Alpha", None, 100, "P5"),
            ],
        })

        points = result["bidder_unit_price_series"][0]["points"]
        self.assertEqual([10], [point["unit_price"] for point in points])
        self.assertEqual(100, points[0]["total_awarded_value"])

    def test_helper_limits_ranked_series_to_five(self):
        totals = {f"b{index}": Decimal(10 - index) for index in range(7)}
        names = {f"b{index}": f"Bidder {index}" for index in range(7)}
        prices = {key: {Decimal("1"): {"value": value, "occurrence_count": 1, "packages": {key}}} for key, value in totals.items()}

        series = build_dashboard_bidder_price_series(totals, names, prices)

        self.assertEqual(5, len(series))
        self.assertEqual(["Bidder 0", "Bidder 1", "Bidder 2", "Bidder 3", "Bidder 4"], [item["name"] for item in series])

    def test_dashboard_exploration_dimensions_remain_composable(self):
        clauses = build_dashboard_selection_clauses("medicines", {
            "product": "Nefopam",
            "province": "Hà Nội",
            "investor": "Bệnh viện A",
        })

        self.assertEqual(3, len(clauses))
        self.assertTrue(any("Nefopam" in clause for clause in clauses))
        self.assertTrue(any("Hà Nội" in clause for clause in clauses))
        self.assertTrue(any("Bệnh viện A" in clause for clause in clauses))


if __name__ == "__main__":
    unittest.main()
