from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from server import (  # noqa: E402
    AutocompleteRequest,
    BulkQueryRequest,
    FilterRequest,
    QueryPreviewRequest,
    QueryRequest,
    SortRule,
    build_count_meta,
    build_sort_order_parts,
)

from typesense_shadow import (  # noqa: E402
    IDENTITY_NOT_COMPARABLE,
    AutocompleteQuery,
    QUERY_CONTRACT_FAILURE,
    SHADOW_INFRA_ERROR,
    SHADOW_OK,
    SHADOW_PARITY_MISMATCH,
    SHADOW_PARITY_NOT_COMPARABLE,
    SEVERITY_P0,
    SEVERITY_P2,
    LEGACY_POPULATION_DIFFERENCE,
    RANKING_DIFFERENCE,
    PostgresSearchRepository,
    TypesenseSearchRepository,
    TypesenseShadowError,
    TypesenseSearchResult,
    TypesenseShadowConfig,
    build_bulk_canonical_query,
    build_canonical_query,
    compare_results,
    identity_collision_audit,
    physical_collection_name,
    report_summary,
    run_shadow_comparison,
    translate_typesense_query,
)


from typesense_contract import IDENTIFIER_FIELDS  # noqa: E402


UUID = "00000000-0000-4000-8000-000000000001"


class TestShadowPrimitives(unittest.TestCase):
    def test_existing_api_request_defaults_are_characterized(self):
        query = QueryRequest()
        preview = QueryPreviewRequest()
        bulk = BulkQueryRequest(scope="goods")
        autocomplete = AutocompleteRequest(field="manufacturer", keyword="máy")
        self.assertEqual(("all", "standard"), (query.scope, query.searchMode))
        self.assertIsNone(query.filters)
        self.assertEqual(("all", None), (preview.scope, preview.filters))
        self.assertEqual(("goods", "price", 3, 3), (bulk.scope, bulk.diversityMode, bulk.priceLimit, bulk.productLimit))
        self.assertEqual(("all", True, 10), (autocomplete.scope, autocomplete.excludeSelf, autocomplete.limit))

    def test_extended_request_models_carry_canonical_contract_without_typesense_syntax(self):
        query = QueryRequest(
            group="medicines", sourceTypes=["medicine_generic"], text="Apitim",
            searchFields=["medicine_name"], structuredFilters={"medicine_group": {"eq": "N2"}},
            ranges={"quantity": {"min": 1}}, dateRanges={"partition_date": {"from": "2026-01-01"}},
            exactIdentifiers={}, page=2,
        )
        preview = QueryPreviewRequest(group="traditional", sourceTypes=["herbal_material"], text="Bạch linh")
        bulk = BulkQueryRequest(
            scope="goods", group="goods", sourceTypes=["goods_general"], fields=["item_name"],
            rows=[{"item_name": "Thực phẩm", "group": "goods"}],
            filters={"country_of_origin": {"eq": "Việt Nam"}},
            sort=[SortRule(column="quantity", order="asc")], page=3,
        )
        self.assertEqual(("medicines", ["medicine_generic"], 2), (query.group, query.sourceTypes, query.page))
        self.assertEqual(("traditional", ["herbal_material"]), (preview.group, preview.sourceTypes))
        self.assertEqual(("goods", ["goods_general"], 3), (bulk.group, bulk.sourceTypes, bulk.page))

    def test_existing_sort_and_count_contracts_are_characterized(self):
        parts = build_sort_order_parts("medicine", [SortRule(column="unitPrice", order="asc")])
        self.assertEqual(1, len(parts))
        self.assertTrue(parts[0].endswith(" ASC"))
        self.assertEqual({"count": 3, "exact": False, "label": "3+", "summary": "hơn 3"}, build_count_meta(3, exact=False))

    def test_generation_resolver_is_physical_and_alias_free(self):
        self.assertEqual("bidfinder_goods_v1_serving_v1_20260901", physical_collection_name("goods", "serving_v1_20260901"))
        self.assertNotIn("bidfinder_goods?", physical_collection_name("goods", "serving_v1_20260901"))
        with self.assertRaises(ValueError):
            physical_collection_name("goods", "../alias")

    def test_canonical_query_preserves_api_semantics_and_privacy_fingerprint(self):
        query = build_canonical_query(
            "medicines",
            {"drugName": {"tokens": [{"value": "Paracetamol", "op": "OR"}]}},
            [{"column": "unitPrice", "order": "asc"}],
            limit=25,
            page=2,
        )
        self.assertEqual((25, 25, 2), (query.limit, query.offset, query.page))
        self.assertEqual("explicit_sort", query.query_class)
        self.assertNotIn("Paracetamol", query.fingerprint)

    def test_translation_covers_all_three_groups_and_current_token_ops(self):
        for group, field in (("goods", "manufacturer"), ("medicines", "activeIngredient"), ("traditional_medicine", "scientific_name")):
            filters = {field: {"tokens": [{"value": "Việt Nam", "op": "AND"}, {"value": "cấm", "op": "NOT"}]}}
            query = build_canonical_query(group, filters, limit=10)
            plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
            self.assertEqual(physical_collection_name(group, "serving_v1_20260901"), plan.collection)
            self.assertIn("filter_by", plan.params)
            self.assertIn(":!", plan.params["filter_by"])

    def test_translation_records_unsupported_legacy_filters_without_inventing_schema(self):
        query = build_canonical_query("goods", {"validity": "Còn hiệu lực"}, limit=10)
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual(("validity",), plan.unsupported_filters)
        self.assertNotIn("validity", plan.params.get("filter_by", ""))

    def test_bulk_translation_uses_canonical_fields(self):
        query = build_bulk_canonical_query("medicines", ["drugName", "manufacturer"], {"drugName": "Paracetamol", "manufacturer": "Dược"}, limit=3)
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertIn("medicine_name", plan.params["filter_by"])
        self.assertIn("manufacturer", plan.params["filter_by"])

    def test_translation_supports_all_advertised_exact_identifier_fields(self):
        for group, fields in IDENTIFIER_FIELDS.items():
            for field in fields:
                query = build_canonical_query(group, exact_identifiers={field: "known-value"}, query_mode="exact")
                plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
                self.assertNotIn(field, plan.unsupported_filters)
                self.assertEqual(field, plan.params["query_by"])
                self.assertEqual("known-value", plan.params["q"])

    def test_translation_uses_iso_prefixes_for_string_partition_date_ranges(self):
        query = build_canonical_query(
            "goods",
            date_ranges={"partition_date": {"from": "2022-01-01", "to": "2022-12-31"}},
        )

        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")

        self.assertIn("partition_date:=2022*", plan.params["filter_by"])
        self.assertNotIn("partition_date:>=", plan.params["filter_by"])
        self.assertNotIn("partition_date:<=", plan.params["filter_by"])


class TestAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_adapter_delegates_canonical_query_and_count_mode(self):
        calls = {}

        async def fetch_page(connection, query, *, exact_count_enabled=False):
            calls.update(connection=connection, query=query, exact_count_enabled=exact_count_enabled)
            return {"data": [], "count": 0, "count_exact": exact_count_enabled}

        query = build_canonical_query("goods", limit=7, page=2)
        result = await PostgresSearchRepository(fetch_page).search("connection", query, exact_count_enabled=True)
        self.assertEqual({"data": [], "count": 0, "count_exact": True}, result)
        self.assertEqual(("connection", query, True), (calls["connection"], calls["query"], calls["exact_count_enabled"]))

    async def test_adapter_uses_physical_generation_and_admin_key_stays_server_side(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"found": 1, "hits": [{"document": {"id": UUID, "item_name": "Máy"}}]}).encode()

        class Opener:
            def __init__(self):
                self.request = None

            def __call__(self, request, **kwargs):
                self.request = request
                return Response()

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        result = await repo.search(build_canonical_query("goods", limit=1))
        self.assertEqual(1, result.total)
        self.assertIn("bidfinder_goods_v1_serving_v1_20260901", opener.request.full_url)
        self.assertEqual("server-only", opener.request.headers["X-typesense-api-key"])

    async def test_exact_id_uses_document_endpoint_and_autocomplete_deduplicates_prefixes(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(self.payload, ensure_ascii=False).encode()

        class Opener:
            def __init__(self):
                self.urls = []

            def __call__(self, request, **kwargs):
                self.urls.append(request.full_url)
                if "/documents/" in request.full_url and "search" not in request.full_url:
                    return Response({"id": UUID, "item_name": "Máy"})
                return Response({"found": 2, "hits": [
                    {"document": {"manufacturer": "Nhà máy"}},
                    {"document": {"manufacturer": "Nhà máy"}},
                ]})

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        exact = await repo.exact_lookup(build_canonical_query("goods", exact_identifiers={"id": UUID}, query_mode="exact"))
        suggestions = await repo.suggest(AutocompleteQuery("goods", "manufacturer", "Nhà", limit=5))
        self.assertEqual((1, UUID), (exact.total, exact.hits[0]["id"]))
        self.assertEqual(("Nhà máy",), suggestions)
        self.assertIn("/documents/" + UUID, opener.urls[0])


class TestParity(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_normalization_compares_page_total_and_window(self):
        query = build_canonical_query("goods", limit=1, page=2)
        row = {"id": UUID, "item_name": "MÃ¡y"}
        metric = compare_results(
            query,
            {"data": [row], "count": 2, "count_exact": True},
            TypesenseSearchResult("goods", 2, (row,), 4.0, 2, 1),
        )
        self.assertEqual((2, 2, 0, 1.0), (metric.postgres_total, metric.typesense_total, metric.missing_from_typesense, metric.top_k_overlap))

    async def test_explicit_sort_difference_is_not_population_p0(self):
        query = build_canonical_query("goods", sort=[{"column": "unitPrice", "order": "asc"}], limit=2)
        first = {"id": UUID, "item_name": "A", "winning_unit_price": 1}
        second = {"id": "00000000-0000-4000-8000-000000000002", "item_name": "B", "winning_unit_price": 2}
        metric = compare_results(
            query,
            {"data": [first, second], "count": 2, "count_exact": True},
            TypesenseSearchResult("goods", 2, (second, first), 4.0, 1, 2),
        )
        self.assertEqual((RANKING_DIFFERENCE, None, False), (metric.error_classification, metric.severity, metric.explicit_sort_parity))

    async def test_full_text_set_difference_is_legacy_population_difference(self):
        query = build_canonical_query("goods", {"drugName": {"tokens": [{"value": "A", "op": "OR"}]}}, limit=2)
        first = {"id": UUID, "item_name": "A"}
        second = {"id": "00000000-0000-4000-8000-000000000002", "item_name": "B"}
        third = {"id": "00000000-0000-4000-8000-000000000003", "item_name": "C"}
        metric = compare_results(
            query,
            {"data": [first, second], "count": 2, "count_exact": True},
            TypesenseSearchResult("goods", 2, (first, third), 4.0, 1, 2),
        )
        self.assertEqual((LEGACY_POPULATION_DIFFERENCE, None), (metric.error_classification, metric.severity))

    async def test_shadow_disabled_does_not_call_repository(self):
        class Repo:
            async def search(self, query):
                raise AssertionError("disabled shadow must not call repository")

        config = TypesenseShadowConfig(enabled=False, sample_rate=0)
        metrics = await run_shadow_comparison([build_canonical_query("goods", limit=1)], {"goods": {"data": []}}, repository=Repo(), config=config)
        self.assertEqual((), metrics)

    async def test_shadow_failure_is_infrastructure_error_and_does_not_raise(self):
        class Repo:
            async def search(self, query):
                raise TimeoutError("bounded timeout")

        query = build_canonical_query("goods", limit=1)
        metrics = await run_shadow_comparison([query], {"goods": {"data": [{"id": UUID}], "count": 1}}, repository=Repo(), config=TypesenseShadowConfig(enabled=True, sample_rate=1, timeout_seconds=0.05))
        self.assertEqual(1, len(metrics))
        self.assertEqual(SHADOW_INFRA_ERROR, metrics[0].error_classification)

    async def test_shadow_contract_failure_is_not_misclassified_as_infrastructure(self):
        class Repo:
            async def search(self, query):
                raise TypesenseShadowError("unsupported field", QUERY_CONTRACT_FAILURE)

        query = build_canonical_query("goods", limit=1)
        metrics = await run_shadow_comparison([query], {"goods": {"data": []}}, repository=Repo(), config=TypesenseShadowConfig(enabled=True, sample_rate=1))
        self.assertEqual(QUERY_CONTRACT_FAILURE, metrics[0].error_classification)

    async def test_uuid_and_field_parity_are_exact_for_canonical_rows(self):
        query = build_canonical_query("goods", limit=1)
        row = {"id": UUID, "item_name": "Máy", "manufacturer": "Nhà máy", "winning_unit_price": 10}
        shadow = TypesenseSearchResult("goods", 1, (row,), 4.0, 1, 1)
        metric = compare_results(query, {"data": [row], "count": 1, "count_exact": True}, shadow, postgres_latency_ms=5)
        self.assertEqual(SHADOW_OK, metric.error_classification)
        self.assertEqual(1, metric.exact_uuid_intersection)
        self.assertEqual(0, metric.field_mismatch_count)
        self.assertEqual(1.0, metric.top_k_overlap)

    async def test_serial_postgres_identity_is_not_falsely_counted_as_uuid_mismatch(self):
        query = build_canonical_query("goods", limit=1)
        row = {"__row_id": 42, "Danh mục hàng hóa": "Máy"}
        shadow = TypesenseSearchResult("goods", 1, ({"id": UUID, "item_name": "Máy"},), 4.0, 1, 1)
        metric = compare_results(query, {"data": [row], "count": 1, "count_exact": True}, shadow)
        self.assertEqual(SHADOW_PARITY_NOT_COMPARABLE, metric.error_classification)
        self.assertIsNone(metric.missing_from_typesense)
        self.assertIsNone(metric.extra_in_typesense)

    async def test_fingerprint_bridge_compares_serial_postgres_to_typesense_uuid(self):
        query = build_canonical_query("goods", limit=1)
        primary = {
            "Mã TBMT": "TB-1",
            "Quyết định phê duyệt": "QD-1",
            "Version": "v1",
            "Mã phần/lô": "L-1",
            "Danh mục hàng hóa": "Máy bơm",
            "Đơn giá trúng thầu (VND)": 10,
        }
        shadow = {
            "id": UUID,
            "bid_invitation_code": "TB-1",
            "decision_number": "QD-1",
            "version": "v1",
            "item_name": "Máy bơm",
            "winning_unit_price": 10.0,
        }
        metric = compare_results(query, {"data": [primary], "count": 1, "count_exact": True}, TypesenseSearchResult("goods", 1, (shadow,), 4.0, 1, 1))
        self.assertEqual(SHADOW_OK, metric.error_classification)
        self.assertEqual("fingerprint", metric.identity_strategy)
        self.assertEqual(1, metric.exact_uuid_intersection)

    async def test_fingerprint_collision_uses_multiset_and_is_not_comparable(self):
        query = build_canonical_query("goods", limit=2)
        primary = {"Mã TBMT": "TB-1", "Mã phần/lô": "L-1", "Danh mục hàng hóa": "Máy"}
        shadow = {"id": UUID, "bid_invitation_code": "TB-1", "lot_code": "L-1", "item_name": "Máy"}
        metric = compare_results(
            query,
            {"data": [primary, dict(primary)], "count": 2, "count_exact": True},
            TypesenseSearchResult("goods", 2, (shadow, dict(shadow)), 4.0, 1, 2),
        )
        audit = identity_collision_audit([primary, dict(primary)], "goods")
        self.assertEqual(1, audit["duplicated_fingerprint_groups"])
        self.assertEqual(IDENTITY_NOT_COMPARABLE, metric.error_classification)
        self.assertEqual((0, 0, None), (metric.missing_from_typesense, metric.extra_in_typesense, metric.severity))

    async def test_report_summary_serializes_compact_metrics(self):
        query = build_canonical_query("goods", limit=1)
        row = {"id": UUID, "item_name": "Máy"}
        metric = compare_results(query, {"data": [row], "count": 1, "count_exact": True}, TypesenseSearchResult("goods", 1, (row,), 4.0, 1, 1))
        summary = report_summary([metric])
        self.assertEqual(1, summary["total_comparisons"])
        self.assertEqual(0, summary["p0_mismatches"])
        self.assertEqual(1, summary["by_query_class"]["filter_only"]["comparisons"])
        self.assertIsInstance(metric.to_dict(), dict)


if __name__ == "__main__":
    unittest.main()
