from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from tools.ai_search_live_eval import (  # noqa: E402
    CASES,
    evaluate_semantics,
    live_eval_preflight,
    run_cases,
    run_live_evaluation,
)


def plan(group: str, clauses, dates=None):
    return {
        "version": "1",
        "group": group,
        "clauses": clauses,
        "date_constraints": dates or [],
        "warnings": [],
        "explanation": [],
    }


def text_clause(field: str, *terms: str):
    return {
        "field": field,
        "concepts": [{"alternatives": [term]} for term in terms],
        "join": "AND",
    }


class LiveSemanticEvaluatorTest(unittest.TestCase):
    def test_fixture_set_covers_requested_live_eval_size(self):
        self.assertGreaterEqual(len(CASES), 25)
        self.assertLessEqual(len(CASES), 30)

    def test_evaluator_accepts_semantically_matching_plan(self):
        case = next(case for case in CASES if case["id"] == "goods_core_iol_recent")
        returned = plan(
            "goods",
            [text_clause("item_name", "Thủy tinh thể nhân tạo", "vàng", "4 càng"), text_clause("procuring_entity_name", "Nguyễn Trãi")],
            [{
                "field": "decision_issued_at",
                "period": {"kind": "relative", "amount": 6, "unit": "months", "direction": "previous"},
                "inclusive": True,
            }],
        )
        self.assertEqual([], evaluate_semantics(returned, {**case["expectations"], "group": "goods"}))

    def test_evaluator_requires_or_alternatives_and_independent_and_concepts(self):
        case = next(case for case in CASES if case["id"] == "medicine_salts_strength_bidder_location")
        split = plan("medicines", [{
            "field": "active_ingredient_or_herbal_component",
            "concepts": [
                {"alternatives": ["clavulanic"]},
                {"alternatives": ["clavulanat"]},
                {"alternatives": ["amoxicilin"]},
            ],
            "join": "AND",
        }])
        failures = evaluate_semantics(split, case["expectations"])
        self.assertTrue(any("independent concept" in failure for failure in failures))

    def test_fake_provider_runs_through_planner_and_semantic_evaluator(self):
        case = {
            "id": "fake",
            "group": "goods",
            "message": "máy thở",
            "expectations": {"required": [{"field": "item_name", "all": ["máy thở"]}]},
        }

        class FakeProvider:
            async def create_plan(self, **_kwargs):
                return plan("goods", [text_clause("item_name", "Máy thở")])

        report = asyncio.run(run_cases([case], lambda: FakeProvider()))
        self.assertEqual("PASS", report["status"])
        self.assertEqual(1, report["passed"])
        self.assertGreaterEqual(report["average_latency_ms"], 0.0)
        self.assertEqual([], [item for item in report["cases"] if not item["passed"]])

    def test_validation_failure_reports_sanitized_raw_provider_plan(self):
        case = {
            "id": "invalid-provider-plan",
            "group": "goods",
            "message": "máy thở",
            "expectations": {},
        }
        raw = plan("goods", [text_clause("item_name", "máy thở")])
        raw["clauses"][0]["concepts"][0]["match"] = "exact"
        raw["headers"] = {"Authorization": "Bearer should-not-appear"}

        class FakeProvider:
            async def create_plan(self, **_kwargs):
                return raw

        report = asyncio.run(run_cases([case], lambda: FakeProvider()))
        failure = report["cases"][0]
        self.assertFalse(failure["passed"])
        self.assertIn("raw_provider_plan", failure)
        self.assertNotIn("returned_plan", failure)
        self.assertEqual("exact", failure["raw_provider_plan"]["clauses"][0]["concepts"][0]["match"])
        self.assertIn("headers", failure["raw_provider_plan"]["unexpected_keys"])
        self.assertNotIn("should-not-appear", json.dumps(report))

    def test_contextual_packaging_can_be_omitted_but_explicit_packaging_is_supported(self):
        core = next(case for case in CASES if case["id"] == "medicine_salts_strength_bidder_location")
        core_plan = plan("medicines", [
            {
                "field": "active_ingredient_or_herbal_component",
                "concepts": [
                    {"alternatives": ["clavulanic", "clavulanat"]},
                    {"alternatives": ["amoxicilin"]},
                ],
                "join": "AND",
            },
            text_clause("strength", "62,5", "500"),
            text_clause("winning_bidder_name", "Hậu Giang"),
            text_clause("location", "Hà Nội"),
        ])
        self.assertEqual([], evaluate_semantics(core_plan, core["expectations"]))

        explicit = next(case for case in CASES if case["id"] == "medicine_packaging_shelf_life_group")
        explicit_plan = plan("medicines", [
            text_clause("medicine_group", "N2"),
            text_clause("unit", "viên"),
            text_clause("packaging", "hộp 3 vỉ x 10 viên"),
            text_clause("shelf_life", "36 tháng"),
        ])
        self.assertEqual([], evaluate_semantics(explicit_plan, explicit["expectations"]))

    def test_meropenem_container_is_not_required(self):
        case = next(case for case in CASES if case["id"] == "medicine_meropenem_form_route")
        returned = plan("medicines", [
            text_clause("medicine_name", "Meropenem"),
            text_clause("strength", "1g"),
            text_clause("dosage_form", "bột pha tiêm"),
            text_clause("route_of_administration", "tĩnh mạch"),
        ])
        self.assertEqual([], evaluate_semantics(returned, case["expectations"]))

    def test_live_evaluation_skips_without_credentials(self):
        environment = {"BIDFINDER_AI_LIVE_EVAL": "1"}
        self.assertEqual({"status": "SKIP", "reason": "missing_api_key", "model": "gpt-5.6-luna"}, live_eval_preflight(environment))
        with patch.dict("os.environ", environment, clear=True):
            report = asyncio.run(run_live_evaluation(environ=environment))
        self.assertEqual("SKIP", report["status"])
        self.assertEqual("missing_api_key", report["reason"])
        self.assertEqual(0, report["total_cases"])
        self.assertIsNone(report["pass_rate"])


if __name__ == "__main__":
    unittest.main()
