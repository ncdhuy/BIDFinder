from __future__ import annotations

import asyncio
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import server as server_module  # noqa: E402
from server import (  # noqa: E402
    AutocompleteRequest,
    BulkQueryRequest,
    FilterRequest,
    PROCUREMENT_FALLBACK_EVENT,
    QueryPreviewRequest,
    QueryRequest,
    SortRule,
    build_count_meta,
    build_sort_order_parts,
    cap_standard_query_page,
    fetch_backend_page,
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


from typesense_contract import IDENTIFIER_FIELDS, ProcurementBackendConfig  # noqa: E402


UUID = "00000000-0000-4000-8000-000000000001"


class TestShadowPrimitives(unittest.TestCase):
    def test_existing_api_request_defaults_are_characterized(self):
        query = QueryRequest()
        preview = QueryPreviewRequest()
        bulk = BulkQueryRequest(scope="goods")
        autocomplete = AutocompleteRequest(field="manufacturer", keyword="máy")
        self.assertEqual(("all", "standard"), (query.scope, query.searchMode))
        self.assertIsNone(query.filters)
        self.assertEqual(50, query.limit)
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

    def test_standard_query_page_is_capped_at_1000_rows(self):
        self.assertEqual((1000, 5000), (server_module.DEFAULT_QUERY_LIMIT, server_module.MAX_QUERY_LIMIT))
        self.assertEqual(50, server_module.DEFAULT_QUERY_PAGE_SIZE)

        query = build_canonical_query("goods", limit=50, page=20, search_mode="standard")
        page = {"data": [{"id": str(index)} for index in range(50)], "has_more": True}
        capped = cap_standard_query_page(page, query)
        self.assertEqual((50, False), (len(capped["data"]), capped["has_more"]))

        query = build_canonical_query("goods", limit=50, page=21, search_mode="standard")
        capped = cap_standard_query_page(page, query)
        self.assertEqual((0, False), (len(capped["data"]), capped["has_more"]))

        full_query = build_canonical_query("goods", limit=5000, search_mode="full")
        self.assertEqual(5000, full_query.limit)

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

    def test_translation_uses_bounded_search_without_global_facet_plumbing(self):
        query = build_canonical_query(
            "goods",
            {"selectionMethod": ["Open"]},
            structured_filters={"production_year": {"eq": 2025}},
            limit=1000,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")

        filter_by = plan.params["filter_by"]
        self.assertIn("selection_method", filter_by)
        self.assertIn("production_year:=`2025`", filter_by)

        self.assertNotIn("facet_by", plan.params)
        self.assertNotIn("max_facet_values", plan.params)

    def test_bounded_page_preserves_ordered_working_set_and_local_page_slice(self):
        page = {
            "data": [{"id": str(index)} for index in range(123)],
            "count": 585449,
            "count_exact": False,
            "has_more": True,
        }

        page_two = server_module.page_bounded_working_set(
            page, page_number=2, page_size=50, working_set_limit=1000,
        )
        page_three = server_module.page_bounded_working_set(
            page, page_number=3, page_size=50, working_set_limit=1000,
        )

        self.assertEqual([str(index) for index in range(50, 100)], [row["id"] for row in page_two["data"]])
        self.assertEqual([str(index) for index in range(100, 123)], [row["id"] for row in page_three["data"]])
        self.assertEqual(123, page_two["working_set_count"])
        self.assertEqual(1000, page_two["working_set_limit"])
        self.assertEqual(585449, page_two["count"])
        self.assertTrue(page_two["has_more"])
        self.assertFalse(page_three["has_more"])
        self.assertTrue(page_two["working_set_truncated"])

        complete_page = {
            "data": [{"id": str(index)} for index in range(257)],
            "count": 257,
            "count_exact": True,
            "has_more": False,
        }
        complete = server_module.page_bounded_working_set(
            complete_page, page_number=1, page_size=50, working_set_limit=1000,
        )
        self.assertEqual(257, complete["working_set_count"])
        self.assertFalse(complete["working_set_truncated"])

    def test_translation_records_unsupported_legacy_filters_without_inventing_schema(self):
        query = build_canonical_query("goods", {"validity": "Còn hiệu lực"}, limit=10)
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual(("validity",), plan.unsupported_filters)
        self.assertNotIn("validity", plan.params.get("filter_by", ""))

    def test_translation_can_search_display_string_fields_selected_by_advanced_ui(self):
        query = build_canonical_query(
            "goods",
            text="QĐ-123",
            search_fields=["decision_number"],
            limit=10,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual("decision_number", plan.params["query_by"])
        self.assertEqual((), plan.unsupported_filters)

    def test_advanced_field_search_uses_prefix_without_unsupported_infix_index(self):
        query = build_canonical_query(
            "medicines",
            text="nefo",
            search_fields=["active_ingredient_or_herbal_component"],
            limit=50,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual("active_ingredient_or_herbal_component", plan.params["query_by"])
        self.assertEqual("true", plan.params["prefix"])
        self.assertNotIn("infix", plan.params)

    def test_legacy_advanced_token_filter_matches_value_prefix(self):
        query = build_canonical_query(
            "medicines",
            filters={"activeIngredient": {"tokens": [{"value": "nefo", "op": "OR"}]}},
            limit=50,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertIn("active_ingredient_or_herbal_component:nefo*", plan.params["filter_by"])
        self.assertNotIn("*nefo*", plan.params["filter_by"])

    def test_goods_keyword_filter_spans_all_four_shared_search_fields(self):
        query = build_canonical_query(
            "goods",
            filters={"goodsKeyword": {"tokens": [{"value": "vông", "op": "OR"}]}},
            limit=50,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        filter_by = plan.params["filter_by"]
        for field in ("item_name", "model_mark", "brand", "technical_specification"):
            self.assertIn(f"{field}:vông*", filter_by)

    def test_cross_group_phrase_search_ignores_fields_not_present_in_each_collection(self):
        fields = (
            "item_name", "model_mark", "brand", "technical_specification",
            "medicine_name", "active_ingredient_or_herbal_component",
        )
        for group, expected_query_by in {
            "goods": "item_name,model_mark,brand,technical_specification",
            "medicines": "medicine_name,active_ingredient_or_herbal_component",
            "traditional_medicine": "item_name",
        }.items():
            query = build_canonical_query(
                group,
                text='"nefopam medi"',
                search_fields=fields,
                cross_group_search=True,
                limit=50,
            )
            plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
            self.assertEqual(expected_query_by, plan.params["query_by"])
            self.assertEqual((), plan.unsupported_filters)

    def test_cross_group_product_keyword_uses_each_groups_product_name_fields(self):
        expected_fields = {
            "goods": ("item_name", "model_mark", "brand", "technical_specification"),
            "medicines": ("medicine_name", "active_ingredient_or_herbal_component"),
            "traditional_medicine": ("item_name",),
        }
        for group, fields in expected_fields.items():
            query = build_canonical_query(
                group,
                filters={"crossGroupProductKeyword": {"tokens": [{"value": "nefo", "op": "OR"}]}},
                limit=50,
            )
            filter_by = translate_typesense_query(
                query,
                serving_generation="serving_v1_20260901",
            ).params["filter_by"]
            for field in fields:
                self.assertIn(f"{field}:nefo*", filter_by)

    def test_cross_group_medicine_search_keeps_selected_medicine_field_scoped(self):
        query = build_canonical_query(
            "medicines",
            text='"Nefopam Medisol 20mg/2ml"',
            search_fields=(
                "item_name", "model_mark", "brand", "technical_specification",
                "medicine_name", "active_ingredient_or_herbal_component",
            ),
            filters={"crossGroupProductKeyword": {"tokens": [{"value": "Nefopam Medisol 20mg/2ml", "op": "OR"}]}},
            cross_group_search=True,
            cross_group_search_fields=("active_ingredient_or_herbal_component",),
            limit=50,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual("active_ingredient_or_herbal_component", plan.params["query_by"])
        self.assertIn("active_ingredient_or_herbal_component:", plan.params["filter_by"])
        self.assertNotIn("medicine_name:", plan.params["filter_by"])

    def test_cross_group_traditional_source_expands_to_both_medicine_product_fields(self):
        query = build_canonical_query(
            "medicines",
            text='"Bạch linh"',
            search_fields=("item_name", "medicine_name", "active_ingredient_or_herbal_component"),
            cross_group_search=True,
            cross_group_search_fields=("item_name",),
            limit=50,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual("medicine_name,active_ingredient_or_herbal_component", plan.params["query_by"])

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

    def test_translation_supports_source_timestamp_date_ranges(self):
        query = build_canonical_query(
            "medicines",
            date_ranges={"result_posted_at": {"from": "2025-01-01", "to": "2025-12-31"}},
        )

        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")

        self.assertIn("result_posted_at:2025*", plan.params["filter_by"])
        self.assertNotIn("result_posted_at:=2025*", plan.params["filter_by"])
        self.assertNotIn("**", plan.params["filter_by"])
        self.assertNotIn("result_posted_at", plan.unsupported_filters)

    def test_advanced_enum_filters_match_legacy_labels_and_current_codes(self):
        query = build_canonical_query(
            "medicines",
            {
                "selectionMethod": ["Đấu thầu rộng rãi"],
                "place": ["Tỉnh Thanh Hóa"],
                "drugGroup": ["N1"],
            },
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        filter_by = plan.params["filter_by"]

        self.assertIn("selection_method:=`DTRR`", filter_by)
        self.assertIn("selection_method:=`LCNT_DB`", filter_by)
        self.assertIn("location:`Thanh Hóa`", filter_by)
        self.assertIn("medicine_group:=`N1`", filter_by)
        self.assertIn("medicine_group:`Nhóm 1`", filter_by)

    def test_traditional_group_uses_the_same_legacy_group_aliases(self):
        query = build_canonical_query(
            "traditional_medicine",
            {"drugGroup": ["Nhóm 1"]},
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertIn("technical_group:=`N1`", plan.params["filter_by"])
        self.assertIn("technical_group:`Nhóm 1`", plan.params["filter_by"])

    def test_drug_group_includes_all_legacy_encoded_value_forms(self):
        expected_values = {
            "BDG": ("BDG", "BGD", "BD", "G2", "Biệt dược", "Biệt dược gốc", "Biet duoc", "Biet duoc goc"),
            "N1": ("N1", "N 1", "G1N1", "G1 N1", "G1 Nhóm 1", "G1 Nhom 1", "Nhóm 1", "Nhom 1"),
            "N2": ("N2", "N 2", "G1N2", "G1 N2", "G1 Nhóm 2", "G1 Nhom 2", "Nhóm 2", "Nhom 2"),
            "N3": ("N3", "N 3", "G1N3", "G1 N3", "G1 Nhóm 3", "G1 Nhom 3", "Nhóm 3", "Nhom 3"),
            "N4": ("N4", "N 4", "G1N4", "G1 N4", "G1 Nhóm 4", "G1 Nhom 4", "Nhóm 4", "Nhom 4"),
            "N5": ("N5", "N 5", "G1N5", "G1 N5", "G1 Nhóm 5", "G1 Nhom 5", "Nhóm 5", "Nhom 5"),
        }
        for group, field in (("medicines", "medicine_group"), ("traditional_medicine", "technical_group")):
            for canonical, values in expected_values.items():
                query = build_canonical_query(group, {"drugGroup": [canonical]})
                filter_by = translate_typesense_query(
                    query,
                    serving_generation="serving_v1_20260901",
                ).params["filter_by"]
                for value in values:
                    self.assertIn(f"{field}:=`{value}`", filter_by)


class TestAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_retries_one_transient_typesense_infrastructure_failure(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"found": 1, "hits": [{"document": {"id": UUID, "item_name": "Máy"}}]}).encode()

        class Opener:
            def __init__(self):
                self.calls = 0

            def __call__(self, request, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise HTTPError(request.full_url, 503, "service unavailable", {}, BytesIO())
                return Response()

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        result = await repo.search(build_canonical_query("goods", limit=1))

        self.assertEqual(1, result.total)
        self.assertEqual(2, opener.calls)

    async def test_adapter_retries_across_collection_startup_window(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"found": 1, "hits": [{"document": {"id": UUID, "item_name": "Máy"}}]}).encode()

        class Opener:
            def __init__(self):
                self.calls = 0

            def __call__(self, request, **kwargs):
                self.calls += 1
                if self.calls <= 2:
                    raise HTTPError(request.full_url, 503, "service unavailable", {}, BytesIO())
                return Response()

        opener = Opener()
        config = TypesenseShadowConfig(
            enabled=True,
            serving_generation="serving_v1_20260901",
            sample_rate=1,
            api_key="server-only",
            query_retry_seconds=2,
        )
        repo = TypesenseSearchRepository(config, opener=opener)
        result = await repo.search(build_canonical_query("goods", limit=1))

        self.assertEqual(1, result.total)
        self.assertEqual(3, opener.calls)

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

    async def test_update_count_uses_result_posted_at_prefix_and_zero_hit_page(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({"found": 17, "hits": []}).encode()

        class Opener:
            def __init__(self):
                self.request = None

            def __call__(self, request, **kwargs):
                self.request = request
                return Response()

        opener = Opener()
        config = TypesenseShadowConfig(api_key="server-only", serving_generation="serving_v1_20260901")
        repo = TypesenseSearchRepository(config, opener=opener)

        self.assertEqual(17, repo._request_update_count("goods", date(2026, 8, 28)))
        self.assertIn("result_posted_at%3A2026-08-28%2A", opener.request.full_url)
        self.assertIn("per_page=0", opener.request.full_url)

    async def test_adapter_returns_ordered_hits_without_global_facets(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                payload = {
                    "found": 128000,
                    "hits": [{"document": {"id": UUID, "unit": "Hộp"}}],
                    "facet_counts": [{"field_name": "unit", "counts": [{"value": "Hộp", "count": 32456}]}],
                }
                return json.dumps(payload, ensure_ascii=False).encode()

        class Opener:
            def __init__(self):
                self.request = None

            def __call__(self, request, **kwargs):
                self.request = request
                return Response()

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        result = await repo.search(build_canonical_query("goods", limit=50))
        api_page = result.to_api_page()

        self.assertEqual((128000, 1), (result.total, len(result.hits)))
        self.assertNotIn("Chai", [result.hits[0].get("unit")])
        self.assertNotIn("facets", api_page)
        self.assertNotIn("facets_available", api_page)
        self.assertNotIn("facet_by", opener.request.full_url)

    async def test_adapter_batches_large_limits_under_typesense_page_cap(self):
        class Response:
            def __init__(self, page, per_page):
                self.page = page
                self.per_page = per_page

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                start = (self.page - 1) * self.per_page
                hits = [{"document": {"id": f"{start + index:036d}", "item_name": "MÃ¡y"}} for index in range(self.per_page)]
                return json.dumps({"found": 5000, "hits": hits}).encode()

        class Opener:
            def __init__(self):
                self.requests = []

            def __call__(self, request, **kwargs):
                from urllib.parse import parse_qs, urlparse

                params = parse_qs(urlparse(request.full_url).query)
                page = int(params["page"][0])
                per_page = int(params["per_page"][0])
                self.requests.append((page, per_page))
                return Response(page, per_page)

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        result = await repo.search(build_canonical_query("goods", limit=5000))

        self.assertEqual((5000, 5000), (result.total, len(result.hits)))
        self.assertEqual(20, len(opener.requests))
        self.assertEqual({250}, {per_page for _, per_page in opener.requests})

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

    async def test_autocomplete_phrase_matches_inside_values_like_legacy_filter(self):
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
                self.url = None

            def __call__(self, request, **kwargs):
                self.url = request.full_url
                return Response({"found": 4, "hits": [
                    {"document": {"item_name": "Dung dịch hiệu chuẩn máy điện giải"}},
                    {"document": {"item_name": "Điện cực máy điện tim"}},
                    {"document": {"item_name": "máy điện xung"}},
                    {"document": {"item_name": "thiết bị điện; máy tính mini"}},
                ]})

        opener = Opener()
        config = TypesenseShadowConfig(enabled=True, serving_generation="serving_v1_20260901", sample_rate=1, api_key="server-only")
        repo = TypesenseSearchRepository(config, opener=opener)
        suggestions = await repo.suggest(AutocompleteQuery("goods", "item_name", "máy điện", limit=5))

        from urllib.parse import parse_qs, urlparse
        params = parse_qs(urlparse(opener.url).query)
        self.assertEqual((
            "Dung dịch hiệu chuẩn máy điện giải",
            "Điện cực máy điện tim",
            "máy điện xung",
        ), suggestions)
        self.assertEqual("máy điện", params["q"][0])
        self.assertEqual("true", params["prefix"][0])
        self.assertEqual("0", params["drop_tokens_threshold"][0])

        partial_suggestions = await repo.suggest(AutocompleteQuery("goods", "item_name", "\u006d\u00e1y \u0111i\u1ec7n t", limit=5))
        partial_params = parse_qs(urlparse(opener.url).query)
        self.assertEqual(("\u0110i\u1ec7n c\u1ef1c m\u00e1y \u0111i\u1ec7n tim",), partial_suggestions)
        self.assertEqual('"máy điện"', partial_params["q"][0])
        self.assertEqual("false", partial_params["prefix"][0])

        prefix_suggestions = await repo.suggest(AutocompleteQuery("goods", "item_name", "\u006d\u00e1y \u0111i\u1ec7n ti", limit=5))
        prefix_params = parse_qs(urlparse(opener.url).query)
        self.assertEqual(("\u0110i\u1ec7n c\u1ef1c m\u00e1y \u0111i\u1ec7n tim",), prefix_suggestions)
        self.assertEqual("\u006d\u00e1y \u0111i\u1ec7n ti", prefix_params["q"][0])
        self.assertEqual("true", prefix_params["prefix"][0])


class TestProcurementBackendSwitch(unittest.IsolatedAsyncioTestCase):
    async def test_infrastructure_failure_uses_postgres_fallback_and_records_event(self):
        class TypesenseOffline:
            async def search(self, query):
                raise TypesenseShadowError("Typesense unavailable", SHADOW_INFRA_ERROR)

        class PostgresFallback:
            def __init__(self):
                self.calls = 0

            async def search(self, connection, query, *, exact_count_enabled=False):
                self.calls += 1
                return {"data": [{"id": UUID}], "count": 1, "count_exact": True, "backend": "postgres"}

        fallback = PostgresFallback()
        query = build_canonical_query("goods", limit=1)
        with patch.object(server_module, "typesense_search_repository", TypesenseOffline()), \
             patch.object(server_module, "postgres_search_repository", fallback), \
             patch.object(server_module, "procurement_backend_config", return_value=ProcurementBackendConfig(mode="typesense", fallback_enabled=True, fallback_timeout_seconds=0.1)), \
             patch.object(server_module, "record_procurement_fallback") as record:
            page = await fetch_backend_page(None, query)

        self.assertEqual(1, fallback.calls)
        self.assertEqual(PROCUREMENT_FALLBACK_EVENT, page["backend_fallback"]["event"])
        record.assert_called_once_with("/api/query", "goods", "typesense_infrastructure")

    async def test_semantic_failure_never_falls_back(self):
        class TypesenseContractFailure:
            async def search(self, query):
                raise TypesenseShadowError("unsupported field", QUERY_CONTRACT_FAILURE)

        class PostgresMustNotRun:
            async def search(self, *args, **kwargs):
                raise AssertionError("semantic Typesense errors must not use Postgres fallback")

        query = build_canonical_query("goods", limit=1)
        with patch.object(server_module, "typesense_search_repository", TypesenseContractFailure()), \
             patch.object(server_module, "postgres_search_repository", PostgresMustNotRun()), \
             patch.object(server_module, "procurement_backend_config", return_value=ProcurementBackendConfig(mode="typesense", fallback_enabled=True)):
            with self.assertRaises(TypesenseShadowError) as context:
                await fetch_backend_page(None, query)

        self.assertEqual(QUERY_CONTRACT_FAILURE, context.exception.code)

    async def test_traditional_infrastructure_failure_does_not_use_goods_fallback(self):
        class TypesenseOffline:
            async def search(self, query):
                raise TypesenseShadowError("Typesense unavailable", SHADOW_INFRA_ERROR)

        class PostgresMustNotRun:
            async def search(self, connection, query, **kwargs):
                if server_module.normalize_group(query.group) != "traditional_medicine":
                    raise AssertionError("traditional fallback must not use the goods legacy scope")
                raise TypesenseShadowError("traditional legacy scope unavailable", QUERY_CONTRACT_FAILURE)

        query = build_canonical_query("traditional", limit=1)
        with patch.object(server_module, "typesense_search_repository", TypesenseOffline()), \
             patch.object(server_module, "postgres_search_repository", PostgresMustNotRun()), \
             patch.object(server_module, "procurement_backend_config", return_value=ProcurementBackendConfig(mode="typesense", fallback_enabled=True)):
            with self.assertRaises(server_module.HTTPException) as context:
                await fetch_backend_page(None, query)

        self.assertEqual(503, context.exception.status_code)
        self.assertIn("tạm thời không khả dụng", context.exception.detail)


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
