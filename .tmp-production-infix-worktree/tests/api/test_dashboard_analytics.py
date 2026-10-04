import json
from concurrent.futures import CancelledError as FutureCancelledError
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

SERVER_SOURCE = (ROOT / "apps" / "api" / "server.py").read_text(encoding="utf-8")

from typesense_shadow import (  # noqa: E402
    TypesenseSearchRepository,
    TypesenseShadowConfig,
    aggregate_dashboard_documents,
    build_canonical_query,
    build_dashboard_selection_clauses,
    filter_dashboard_columns,
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
    def test_dashboard_uses_preview_access_without_separate_full_query_login_gate(self):
        route_start = SERVER_SOURCE.index('@app.post("/api/dashboard-analytics")')
        route_end = SERVER_SOURCE.index('\n\n@app.', route_start + 1)
        route_source = SERVER_SOURCE[route_start:route_end]

        self.assertIn('optional_db_connection(request, "preview")', route_source)
        self.assertIn('enforce_data_access_policy(conn, request, "preview")', route_source)
        self.assertNotIn('enforce_data_access_policy(conn, request, "full_query")', route_source)

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
        self.assertNotIn("requires_product_selection", result["bidder_price_band_analysis"])
        self.assertEqual(["B1", "B2", "Nhà thầu C"], [
            row["bidder_name"] for row in result["bidder_price_band_analysis"]["items"]
        ])
        selected_product = aggregate_dashboard_documents(documents, selected_product="Amox")
        bands = selected_product["bidder_price_band_analysis"]["items"]
        self.assertEqual([("B1", 50), ("B2", 20)], [
            (row["bidder_name"], row["corresponding_awarded_value"]) for row in bands
        ])
        selected_bidder = aggregate_dashboard_documents(documents, selected_bidder="B1")
        self.assertEqual(50, selected_bidder["summary"]["total_awarded_value"])
        self.assertEqual(1, selected_bidder["summary"]["package_count"])
        self.assertEqual(1, selected_bidder["summary"]["bidder_count"])
        self.assertEqual(["Bệnh viện A"], [row["name"] for row in selected_bidder["top_investors"]])
        self.assertEqual(["B1"], [
            row["bidder_name"] for row in selected_bidder["bidder_price_band_analysis"]["items"]
        ])
        self.assertNotIn("unit_price_distribution", selected_product)
        self.assertNotIn("bidder_unit_price_series", selected_product)
        self.assertEqual("Bệnh viện A", result["top_investors"][0]["name"])

    def test_request_all_pages_complete_match_universe_beyond_search_caps(self):
        calls = []
        remaining_pages = threading.Barrier(2, timeout=3)

        def opener(request, timeout):
            del timeout
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            calls.append(page)
            if page > 1:
                remaining_pages.wait()
            start = (page - 1) * 250
            end = min(start + 250, 1250)
            return _Response({
                "found": 1250,
                "hits": [{"document": {"id": str(index)}} for index in range(start, end)],
            })

        repository = TypesenseSearchRepository(
            TypesenseShadowConfig(serving_generation="serving_v1", api_key="server-only"),
            opener=opener,
        )
        query = build_canonical_query("goods", limit=50)
        documents = repository._request_all(query, include_fields=("id", "item_name"))

        self.assertEqual(1250, len(documents))
        self.assertCountEqual([1, 2, 3, 4, 5], calls)
        self.assertEqual([str(index) for index in range(1250)], [document["id"] for document in documents])

    def test_cancelled_dashboard_scan_stops_before_next_page_batch(self):
        stop = threading.Event()
        calls = []

        def opener(request, timeout):
            del timeout
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            calls.append(page)
            stop.set()
            return _Response({"found": 1250, "hits": [{"document": {"id": "0"}}]})

        repository = TypesenseSearchRepository(
            TypesenseShadowConfig(serving_generation="serving_v1", api_key="server-only"),
            opener=opener,
        )
        with self.assertRaises(FutureCancelledError):
            repository._request_all(build_canonical_query("goods", limit=50), stop_event=stop)
        self.assertEqual([1], calls)

    def test_dashboard_scan_limit_returns_match_count_without_reading_extra_pages(self):
        calls = []

        def opener(request, timeout):
            del timeout
            page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
            calls.append(page)
            start = (page - 1) * 250
            return _Response({
                "found": 1250,
                "hits": [{"document": {"id": str(index)}} for index in range(start, min(start + 250, 1250))],
            })

        repository = TypesenseSearchRepository(
            TypesenseShadowConfig(serving_generation="serving_v1", api_key="server-only"),
            opener=opener,
        )
        found, documents = repository._request_all(
            build_canonical_query("goods", limit=50), max_documents=1025, with_found=True,
        )
        self.assertEqual(1250, found)
        self.assertEqual(1025, len(documents))
        self.assertCountEqual([1, 2, 3, 4, 5], calls)

    def test_investor_cross_filter_matches_and_aggregates_case_variants(self):
        documents = [
            {
                "id": "a", "medicine_name": "Amox", "winning_unit_price": 100,
                "bid_invitation_code": "P1", "winning_bidder_id": ["B1"],
                "procuring_entity_id": "I1", "procuring_entity_name": "Bệnh viện An Tâm",
                "total_value": 100,
            },
            {
                "id": "b", "medicine_name": "Amox", "winning_unit_price": 100,
                "bid_invitation_code": "P2", "winning_bidder_id": ["B2"],
                "procuring_entity_id": "I2", "procuring_entity_name": "BỆNH VIỆN AN TÂM",
                "total_value": 200,
            },
        ]

        result = aggregate_dashboard_documents(
            {"medicines": documents},
            selected_investor="bệnh viện an tâm",
        )

        self.assertEqual(1, len(result["top_investors"]))
        self.assertEqual(2, result["top_investors"][0]["package_count"])
        self.assertEqual(300, result["top_investors"][0]["total_awarded_value"])
        self.assertEqual(300, result["summary"]["total_awarded_value"])
        self.assertEqual((), build_dashboard_selection_clauses("medicines", {"investor": "Bệnh viện An Tâm"}))

    def test_price_band_projection_keeps_product_and_unit_context(self):
        server_source = (ROOT / "apps" / "api" / "server.py").read_text(encoding="utf-8")
        route_start = server_source.index('@app.post("/api/dashboard-analytics")')
        route_end = server_source.index('\n\n@app.', route_start + 1)
        route_source = server_source[route_start:route_end]

        self.assertIn('"unit"', route_source)
        self.assertIn('build_dashboard_selection_clauses(query.group, selection)', route_source)
        self.assertIn('selected_bidder=selection.get("bidder")', route_source)
        self.assertIn('selected_investor=selection.get("investor")', route_source)

    def test_dashboard_column_filters_match_table_semantics_on_full_universe(self):
        documents = [
            {"id": str(index), "item_name": "A" if index % 2 else "B", "unit": "Hộp"}
            for index in range(1251)
        ]
        self.assertEqual([], filter_dashboard_columns("goods", documents, {"unit": []}))
        self.assertEqual(625, len(filter_dashboard_columns("goods", documents, {"item_name": ["a"]})))
        self.assertEqual(625, len(filter_dashboard_columns("goods", documents, {
            "item_name": {"text": {"operator": "beginsWith", "value": "a"}}
        })))


class DashboardLimitRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_limit_is_shared_across_groups_and_reported(self):
        import server

        calls = []

        class Repository:
            async def analytics_documents(self, query, **kwargs):
                limit = kwargs["max_documents"]
                calls.append((query.group, limit))
                return 100, [{"id": f"{query.group}-{index}"} for index in range(limit)]

        @asynccontextmanager
        async def connection(*_args):
            yield None

        request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
        with patch.object(server, "DASHBOARD_ANALYTICS_MAX_ROWS", 10), \
             patch.object(server, "typesense_search_repository", Repository()), \
             patch.object(server, "optional_db_connection", connection), \
             patch.object(server, "enforce_rate_limit", AsyncMock(return_value=None)), \
             patch.object(server, "enforce_data_access_policy", AsyncMock(return_value=None)), \
             patch.object(server, "procurement_backend_config", return_value=SimpleNamespace(typesense_primary=True)):
            response = await server.dashboard_analytics(request, server.DashboardAnalyticsRequest())

        body = json.loads(response.body)
        self.assertEqual(10, sum(limit for _, limit in calls))
        self.assertEqual([4, 3, 3], sorted((limit for _, limit in calls), reverse=True))
        self.assertEqual(10, body["scanned_documents"])
        self.assertEqual(10, body["scan_limit"])
        self.assertFalse(body["analytics_complete"])
        self.assertFalse(body["meta"]["complete"])


if __name__ == "__main__":
    unittest.main()
