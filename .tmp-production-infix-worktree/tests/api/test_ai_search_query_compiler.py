from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from ai_search_planner import validate_ai_search_plan  # noqa: E402
from ai_search_query_compiler import (  # noqa: E402
    AIQueryCompilationError,
    compile_ai_search_plan,
    safe_broaden_ai_query,
)
from typesense_shadow import build_canonical_query, translate_typesense_query  # noqa: E402


def raw_plan(group: str, clauses=None, dates=None):
    return validate_ai_search_plan({
        "version": "1",
        "group": group,
        "clauses": clauses or [],
        "date_constraints": dates or [],
        "warnings": [],
        "explanation": [],
    }, requested_group=group)


def clause(field: str, *concepts: tuple[str, ...] | str):
    return {
        "field": field,
        "concepts": [
            {"alternatives": list(concept) if isinstance(concept, tuple) else [concept]}
            for concept in concepts
        ],
        "join": "AND",
    }


def date_constraint(field: str, amount: int, unit: str, direction: str = "previous"):
    return {
        "field": field,
        "period": {"kind": "relative", "amount": amount, "unit": unit, "direction": direction},
        "inclusive": True,
    }


class AIQueryCompilerTest(unittest.TestCase):
    def test_identifier_uses_existing_exact_identifiers_and_preserves_value(self):
        compiled = compile_ai_search_plan(raw_plan(
            "goods",
            [clause("bid_invitation_code", "IB2600498667")],
        ))

        self.assertEqual("IB2600498667", compiled.exact_identifiers["bid_invitation_code"])
        self.assertEqual({}, dict(compiled.filters))
        self.assertEqual("IB2600498667", compiled.to_payload()["exactIdentifiers"]["bid_invitation_code"])

    def test_date_compiles_to_concrete_local_date_range(self):
        frozen_now = datetime(2026, 3, 31, 23, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        compiled = compile_ai_search_plan(raw_plan(
            "goods",
            dates=[date_constraint("decision_issued_at", 6, "months")],
        ), now=frozen_now)

        self.assertEqual(
            {"from": "2025-09-30", "to": "2026-03-31"},
            compiled.date_ranges["decision_issued_at"],
        )

    def test_boolean_concepts_reuse_legacy_and_or_token_filter_semantics(self):
        compiled = compile_ai_search_plan(raw_plan(
            "medicines",
            [
                clause(
                    "active_ingredient_or_herbal_component",
                    ("clavulanic", "clavulanat"),
                    ("amoxicilin", "amoxicillin"),
                ),
                clause("strength", "62,5", "500"),
            ],
        ))
        self.assertEqual(
            [
                {"alternatives": ["clavulanic", "clavulanat"]},
                {"alternatives": ["amoxicilin", "amoxicillin"]},
            ],
            compiled.filters["activeIngredient"]["groups"],
        )
        self.assertNotIn("tokens", compiled.filters["activeIngredient"])
        self.assertEqual(
            [
                {"alternatives": ["62,5"]},
                {"alternatives": ["500"]},
            ],
            compiled.filters["concentration"]["groups"],
        )
        translated = translate_typesense_query(
            build_canonical_query("medicines", compiled.filters, limit=50),
            serving_generation="serving_v1_20260901",
        )
        filter_by = translated.params["filter_by"]

        active_group_expression = (
            "(active_ingredient_or_herbal_component:clavulanic* || "
            "active_ingredient_or_herbal_component:clavulanat*) && "
            "(active_ingredient_or_herbal_component:amoxicilin* || "
            "active_ingredient_or_herbal_component:amoxicillin*)"
        )
        self.assertIn(active_group_expression, filter_by)
        self.assertIn("strength:62,5*", filter_by)
        self.assertIn("strength:500*", filter_by)
        self.assertNotIn(
            "active_ingredient_or_herbal_component:clavulanic* || "
            "active_ingredient_or_herbal_component:clavulanat* || "
            "active_ingredient_or_herbal_component:amoxicilin*",
            filter_by,
        )

    def test_company_and_location_reuse_existing_filters(self):
        compiled = compile_ai_search_plan(raw_plan(
            "medicines",
            [
                clause("winning_bidder_name", "Hậu Giang"),
                clause("location", "Hà Nội"),
            ],
        ))

        self.assertIn("Hậu Giang", compiled.filters["winner"]["groups"][0]["alternatives"])
        self.assertEqual(["Hà Nội"], compiled.filters["place"])

    def test_goods_product_terms_use_current_field_scope_and_can_broaden_safely(self):
        compiled = compile_ai_search_plan(raw_plan(
            "goods",
            [
                clause("item_name", "Thủy tinh thể nhân tạo"),
                clause("technical_specification", "màu vàng", "4 càng"),
            ],
        ))

        self.assertEqual(("item_name", "technical_specification"), compiled.search_fields)
        self.assertIn('"Thủy tinh thể nhân tạo"', compiled.text)
        self.assertIn('"màu vàng"', compiled.text)
        self.assertIn('"4 càng"', compiled.text)

        broadened = safe_broaden_ai_query(compiled)
        self.assertIsNotNone(broadened)
        broad_query, changes = broadened
        self.assertEqual(("item_name", "model_mark", "brand", "technical_specification"), broad_query.search_fields)
        self.assertEqual("goods_product_field_expansion", changes["kind"])
        self.assertEqual(compiled.text, broad_query.text)

    def test_categorical_and_date_constraints_coexist_without_raw_backend_syntax(self):
        compiled = compile_ai_search_plan(raw_plan(
            "goods",
            [
                clause("selection_method", "Đấu thầu rộng rãi"),
                clause("production_year", "2025"),
            ],
            [date_constraint("decision_issued_at", 1, "years", "current")],
        ))
        payload = compiled.to_payload()

        self.assertEqual(["Đấu thầu rộng rãi"], payload["filters"]["selectionMethod"])
        self.assertEqual({"in": ["2025"]}, payload["structuredFilters"]["production_year"])
        self.assertIn("decision_issued_at", payload["dateRanges"])
        self.assertNotIn("filter_by", payload)
        self.assertNotIn("sql", repr(payload).lower())

    def test_group_is_fixed_and_date_fields_are_not_text_clauses(self):
        compiled = compile_ai_search_plan(raw_plan("traditional", [clause("item_name", "Đan sâm")]))
        self.assertEqual(("traditional", "traditional"), (compiled.group, compiled.scope))

        with self.assertRaisesRegex(AIQueryCompilationError, "date field"):
            compile_ai_search_plan({
                "group": "goods",
                "clauses": [clause("decision_issued_at", "2026")],
                "date_constraints": [],
            })

    def test_unaliased_text_field_keeps_binding_when_used_alone(self):
        compiled = compile_ai_search_plan(raw_plan(
            "traditional",
            [clause("used_part", "rễ")],
        ))
        self.assertEqual(("used_part",), compiled.search_fields)
        self.assertEqual("rễ", compiled.text)

    def test_unaliased_text_fields_fail_closed_instead_of_merging_bindings(self):
        with self.assertRaises(AIQueryCompilationError) as context:
            compile_ai_search_plan(raw_plan(
                "traditional",
                [clause("used_part", "rễ"), clause("origin", "Lào Cai")],
            ))
        self.assertEqual("text_field_binding_unsupported", context.exception.category)

    def test_unaliased_text_alternatives_fail_closed_instead_of_flattening_or(self):
        with self.assertRaises(AIQueryCompilationError) as context:
            compile_ai_search_plan(raw_plan(
                "traditional",
                [clause("used_part", ("rễ", "lá"))],
            ))
        self.assertEqual("text_fallback_boolean_unsupported", context.exception.category)

    def test_empty_strict_product_query_has_at_most_one_safe_broadening_round(self):
        compiled = compile_ai_search_plan(raw_plan("goods", [clause("item_name", "máy thở")]))
        broadened = safe_broaden_ai_query(compiled)
        self.assertIsNotNone(broadened)
        self.assertIsNone(safe_broaden_ai_query(broadened[0]))


if __name__ == "__main__":
    unittest.main()
