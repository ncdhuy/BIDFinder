import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_shadow import (  # noqa: E402
    TypesenseSearchRepository,
    TypesenseShadowConfig,
    aggregate_dashboard_documents,
    build_canonical_query,
    build_dashboard_price_histogram,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class DashboardAnalyticsTest(unittest.TestCase):
    def test_aggregation_uses_unique_packages_and_package_based_product_counts(self):
        documents = {
            "medicines": [
                {
                    "id": "m1", "medicine_name": "Amox", "quantity": 2, "winning_unit_price": 10,
                    "bid_invitation_code": "PKG-1", "winning_bidder_id": ["B1"],
                    "procuring_entity_id": "I1", "procuring_entity_name": "Bệnh viện A",
                    "location": "Tỉnh Quảng Trị, Xã A", "result_posted_at": "2026-01-02",
                },
                {
                    "id": "m2", "medicine_name": "Amox", "quantity": 3, "winning_unit_price": 10,
                    "bid_invitation_code": "PKG-1", "winning_bidder_id": ["B1"],
                    "procuring_entity_id": "I1", "procuring_entity_name": "Bệnh viện A",
                    "location": "Tỉnh Quảng Trị, Xã A", "result_posted_at": "2026-01-02",
                },
                # Same document appears twice in a source response. It must not inflate totals.
                {
                    "id": "m2", "medicine_name": "Amox", "quantity": 3, "winning_unit_price": 10,
                    "bid_invitation_code": "PKG-1", "winning_bidder_id": ["B1"],
                    "procuring_entity_id": "I1", "procuring_entity_name": "Bệnh viện A",
                    "location": "Tỉnh Quảng Trị, Xã A", "result_posted_at": "2026-01-02",
                },
                {
                    "id": "m3", "medicine_name": "Amox", "quantity": 1, "winning_unit_price": 20,
                    "bid_invitation_code": "PKG-2", "winning_bidder_id": ["B2"],
                    "procuring_entity_id": "I2", "procuring_entity_name": "Bệnh viện B",
                    "location": "Tỉnh Hà Nội", "result_posted_at": "2026-02-03",
                },
            ],
            "goods": [
                {
                    "id": "g1", "item_name": "Găng tay", "quantity": 1, "winning_unit_price": 5,
                    "bid_invitation_code": "PKG-3", "winning_bidder_name": ["Nhà thầu C"],
                    "procuring_entity_name": "Bệnh viện B", "location": "Tỉnh Hà Nội",
                    "result_posted_at": "2026-02-03",
                },
            ],
        }

        result = aggregate_dashboard_documents(documents)

        self.assertEqual(75, result["summary"]["total_awarded_value"])
        self.assertEqual(3, result["summary"]["package_count"])
        self.assertEqual(3, result["summary"]["bidder_count"])
        self.assertEqual(2, result["summary"]["investor_count"])
        self.assertEqual({"Amox": 2}, {row["name"]: row["count"] for row in result["top_products"] if row["name"] == "Amox"})
        self.assertEqual(2, len(result["geography"]))
        self.assertEqual("day", result["timeline"]["grain"])
        self.assertEqual(["2026-01", "2026-02"], [point["period"] for point in result["timeline"]["series"]["month"]])
        self.assertEqual(["2026-Q1"], [point["period"] for point in result["timeline"]["series"]["quarter"]])
        self.assertEqual(75, result["timeline"]["series"]["year"][0]["total_awarded_value"])
        self.assertEqual(4, result["unit_price_distribution"]["count"])
        self.assertEqual("Bệnh viện A", result["top_investors"][0]["name"])

    def test_price_histogram_excludes_invalid_values_and_preserves_counts(self):
        histogram = build_dashboard_price_histogram([0, -1, None, "bad", 10, 20, 30, 1000, 2000, 3000])
        self.assertEqual(6, histogram["count"])
        self.assertLessEqual(len(histogram["bins"]), 12)
        self.assertEqual(10, histogram["stats"]["min"])
        self.assertEqual(3000, histogram["stats"]["max"])
        self.assertEqual(6, sum(item["count"] for item in histogram["bins"]))

    def test_request_all_pages_complete_match_universe_beyond_search_caps(self):
        calls = []

        def opener(request, timeout):
            del timeout
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            calls.append(page)
            start = (page - 1) * 250
            end = min(start + 250, 501)
            return _Response({
                "found": 501,
                "hits": [{"document": {"id": str(index)}} for index in range(start, end)],
            })

        repository = TypesenseSearchRepository(
            TypesenseShadowConfig(serving_generation="serving_v1", api_key="server-only"),
            opener=opener,
        )
        query = build_canonical_query("goods", limit=50)
        documents = repository._request_all(query, include_fields=("id", "item_name"))

        self.assertEqual(501, len(documents))
        self.assertEqual([1, 2, 3], calls)


if __name__ == "__main__":
    unittest.main()
