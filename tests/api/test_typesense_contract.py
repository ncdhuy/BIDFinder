from __future__ import annotations

import os
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_contract import (
    PUBLIC_GROUPS,
    contract_counts,
    get_procurement_backend_config,
    get_search_contract,
    source_selector,
    validate_contract_against_schema,
)
from typesense_shadow import (
    LEGACY_POPULATION_DIFFERENCE,
    QUERY_CONTRACT_FAILURE,
    RANKING_DIFFERENCE,
    TypesenseSearchResult,
    build_canonical_query,
    translate_typesense_query,
)


class TypesenseContractTest(unittest.TestCase):
    def test_schema_metadata_agreement_and_three_groups(self):
        report = validate_contract_against_schema()
        self.assertEqual("PASS", report["status"])
        self.assertEqual(set(PUBLIC_GROUPS), set(get_search_contract()["groups"]))
        self.assertEqual({"goods": 2, "medicines": 3, "traditional": 2}, {
            group: len(contract["source_types"])
            for group, contract in get_search_contract()["groups"].items()
        })

    def test_checked_in_catalog_matches_runtime_contract_and_corpus_is_broad(self):
        artifact = json.loads((ROOT / "typesense-search-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(get_search_contract(), artifact)
        fields = {field["name"]: field for field in artifact["groups"]["goods"]["fields"]}
        self.assertEqual(["danhMucHangHoa", "tenThietBi"], fields["item_name"]["raw_aliases"])
        medicine_fields = {field["name"]: field for field in artifact["groups"]["medicines"]["fields"]}
        self.assertEqual(["tenThuoc"], medicine_fields["medicine_name"]["raw_aliases"])
        from tools.typesense_query_validation import corpus_summary
        summary = corpus_summary()
        self.assertEqual(212, summary["corpus_size"])
        self.assertEqual({"goods", "medicines", "traditional"}, set(summary["by_group"]))

    def test_field_capability_counts_are_complete(self):
        self.assertEqual({
            "goods": {"searchable": 14, "filterable": 11, "sortable": 5, "autocomplete": 5},
            "medicines": {"searchable": 16, "filterable": 13, "sortable": 4, "autocomplete": 6},
            "traditional": {"searchable": 15, "filterable": 12, "sortable": 4, "autocomplete": 6},
        }, contract_counts())

    def test_source_selector_preserves_all_seven_identities(self):
        field, values = source_selector("medicines", ["medicine_generic", "medicine_originator"])
        self.assertEqual("source_tab_label", field)
        self.assertEqual(2, len(values))
        self.assertNotEqual(values[0], values[1])
        field, values = source_selector("goods", ["goods_general", "medical_devices"])
        self.assertEqual(("source_tab", 2), (field, len(values)))
        field, values = source_selector("traditional", ["herbal_material", "traditional_medicine"])
        self.assertEqual(("source_tab", 2), (field, len(values)))

    def test_full_query_contract_maps_source_text_filters_ranges_and_page(self):
        query = build_canonical_query(
            "traditional",
            text="Bạch linh",
            search_fields=["item_name"],
            source_types=["herbal_material"],
            structured_filters={"unit": {"in": ["Kg", "g"]}},
            ranges={"quantity": {"min": 0, "max": 100}},
            date_ranges={"partition_date": {"from": "2025-01-01", "to": "2026-12-31"}},
            sort=[{"column": "quantity", "order": "asc"}],
            page=3,
            limit=25,
        )
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertEqual(50, query.offset)
        self.assertEqual(3, plan.params["page"])
        self.assertEqual(25, plan.params["per_page"])
        self.assertEqual("Bạch linh", plan.params["q"])
        self.assertEqual("item_name", plan.params["query_by"])
        self.assertIn("source_tab:=`DUOC_LIEU`", plan.params["filter_by"])
        self.assertIn("quantity:>=0", plan.params["filter_by"])
        self.assertIn("partition_date:=2025*", plan.params["filter_by"])
        self.assertIn("partition_date:=2026*", plan.params["filter_by"])
        self.assertTrue(plan.params["include_fields"])
        self.assertEqual((), plan.unsupported_filters)
        self.assertEqual((), plan.unsupported_sorts)

    def test_exact_identifier_and_filter_only_paths(self):
        exact = build_canonical_query("goods", exact_identifiers={"bid_invitation_code": "IB2600498667"}, query_mode="exact")
        plan = translate_typesense_query(exact, serving_generation="serving_v1_20260901")
        self.assertEqual("IB2600498667", plan.params["q"])
        self.assertEqual("bid_invitation_code", plan.params["query_by"])
        self.assertEqual(0, plan.params["num_typos"])
        self.assertEqual("false", plan.params["prefix"])

        zero = build_canonical_query("goods", structured_filters={"quantity": 0})
        zero_plan = translate_typesense_query(zero, serving_generation="serving_v1_20260901")
        self.assertIn("quantity:=0", zero_plan.params["filter_by"])
        filter_only = translate_typesense_query(build_canonical_query("goods"), serving_generation="serving_v1_20260901")
        self.assertEqual("*", filter_only.params["q"])
        self.assertEqual("item_name", filter_only.params["query_by"])
        self.assertEqual("partition_date:desc", filter_only.params["sort_by"])

    def test_non_filterable_null_operator_is_explicitly_rejected(self):
        query = build_canonical_query("goods", structured_filters={"manufacturer": {"eq": "Nhà máy"}, "quantity": {"missing": True}})
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        self.assertIn("manufacturer", plan.unsupported_filters)
        self.assertIn("quantity:null", plan.unsupported_filters)
        text_range = build_canonical_query("goods", structured_filters={"unit": {"min": "A"}})
        text_range_plan = translate_typesense_query(text_range, serving_generation="serving_v1_20260901")
        self.assertIn("unit:min", text_range_plan.unsupported_filters)

    def test_typesense_response_page_is_api_compatible_and_deterministic(self):
        page = TypesenseSearchResult("goods", 3, ({"id": "1", "item_name": "A"},), 4.0, 2, 1).to_api_page()
        self.assertEqual((3, True, 1, "typesense"), (page["count"], page["has_more"], page["displayed"], page["backend"]))

    def test_backend_defaults_to_typesense_with_postgres_fallback_and_supports_rollback(self):
        names = ["BIDFINDER_PROCUREMENT_BACKEND", "BIDFINDER_CONTROLLED_TYPESENSE_ENABLED", "BIDFINDER_PROCUREMENT_FALLBACK_ENABLED"]
        with patch.dict(os.environ, {}, clear=False):
            for name in names:
                os.environ.pop(name, None)
            config = get_procurement_backend_config()
        self.assertEqual("typesense", config.mode)
        self.assertTrue(config.typesense_primary)
        self.assertTrue(config.fallback_enabled)
        with patch.dict(os.environ, {
            "BIDFINDER_PROCUREMENT_BACKEND": "postgres",
            "BIDFINDER_PROCUREMENT_FALLBACK_ENABLED": "false",
        }):
            config = get_procurement_backend_config()
        self.assertEqual("postgres", config.mode)
        self.assertFalse(config.typesense_primary)
        self.assertFalse(config.fallback_enabled)
        with patch.dict(os.environ, {
            "BIDFINDER_PROCUREMENT_BACKEND": "controlled",
            "BIDFINDER_CONTROLLED_TYPESENSE_ENABLED": "true",
            "BIDFINDER_PROCUREMENT_FALLBACK_ENABLED": "true",
        }):
            config = get_procurement_backend_config()
        self.assertTrue(config.typesense_primary)
        self.assertTrue(config.fallback_enabled)

    def test_population_difference_is_not_p0_and_contract_failure_is_distinct(self):
        self.assertEqual("LEGACY_POPULATION_DIFFERENCE", LEGACY_POPULATION_DIFFERENCE)
        self.assertEqual("QUERY_CONTRACT_FAILURE", QUERY_CONTRACT_FAILURE)
        self.assertEqual("RANKING_DIFFERENCE", RANKING_DIFFERENCE)


if __name__ == "__main__":
    unittest.main()
