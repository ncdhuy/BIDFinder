from __future__ import annotations

import asyncio
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
        "concepts": [{"alternatives": [term], "match": "text"} for term in terms],
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
                {"alternatives": ["clavulanic"], "match": "text"},
                {"alternatives": ["clavulanat"], "match": "text"},
                {"alternatives": ["amoxicilin"], "match": "text"},
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
        self.assertEqual([], [item for item in report["cases"] if not item["passed"]])

    def test_live_evaluation_skips_without_credentials(self):
        environment = {"BIDFINDER_AI_LIVE_EVAL": "1"}
        self.assertEqual({"status": "SKIP", "reason": "missing_api_key", "model": "gpt-5.6-luna"}, live_eval_preflight(environment))
        with patch.dict("os.environ", environment, clear=True):
            report = asyncio.run(run_live_evaluation(environ=environment))
        self.assertEqual("SKIP", report["status"])
        self.assertEqual("missing_api_key", report["reason"])
        self.assertEqual(0, report["total_cases"])


if __name__ == "__main__":
    unittest.main()
