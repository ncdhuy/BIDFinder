from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import server as server_module  # noqa: E402
from ai_search_planner import validate_ai_search_plan  # noqa: E402


def normalized_plan(group: str, clauses=None, dates=None):
    return validate_ai_search_plan({
        "version": "1",
        "group": group,
        "clauses": clauses or [],
        "date_constraints": dates or [],
        "warnings": [],
        "explanation": [],
    }, requested_group=group)


def clause(field: str, *terms: str):
    return {
        "field": field,
        "concepts": [{"alternatives": [term]} for term in terms],
        "join": "AND",
    }


def preview_payload(total: int):
    return server_module.JSONResponse(content={
        "success": True,
        "backend": "typesense",
        "total": total,
        "exact": True,
        "display": str(total),
        "summary": str(total),
    })


class AISearchPreviewEndpointTest(unittest.TestCase):
    def _run_endpoint(self, plan, responses):
        request = object()
        payload = server_module.AIPlanRequest(group=plan.group, message="test")
        preview = AsyncMock(side_effect=responses)
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "create_search_plan", new=AsyncMock(return_value=plan)), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(request, payload))
        return response, preview

    def test_existing_preview_endpoint_uses_shared_preview_execution(self):
        request = object()
        payload = server_module.QueryPreviewRequest(scope="goods", group="goods")
        execution = AsyncMock(return_value=preview_payload(4))
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "execute_query_preview", new=execution):
            response = asyncio.run(server_module.preview_query(request, payload))

        self.assertEqual(4, json.loads(response.body)["total"])
        execution.assert_awaited_once_with(request, payload)

    def test_positive_strict_preview_stops_without_relaxation(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        response, preview = self._run_endpoint(plan, [preview_payload(3)])
        body = json.loads(response.body)

        self.assertEqual(1, preview.call_count)
        self.assertEqual(0, body["optimization"]["selected_round"])
        self.assertEqual([{"round": 0, "kind": "strict", "preview_count": 3}], body["optimization"]["rounds"])
        self.assertEqual("ok", body["status"])

    def test_zero_strict_preview_runs_one_safe_broadening_round(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        response, preview = self._run_endpoint(plan, [preview_payload(0), preview_payload(2)])
        body = json.loads(response.body)

        self.assertEqual(2, preview.call_count)
        self.assertEqual(1, body["optimization"]["selected_round"])
        self.assertEqual("safe_broadening", body["optimization"]["rounds"][1]["kind"])
        self.assertEqual(2, body["optimization"]["rounds"][1]["preview_count"])
        self.assertEqual("matched_after_safe_broadening", body["optimization"]["outcome"])
        strict_payload = preview.await_args_list[0].args[1]
        broadened_payload = preview.await_args_list[1].args[1]
        self.assertEqual(strict_payload.text, broadened_payload.text)
        self.assertNotEqual(strict_payload.searchFields, broadened_payload.searchFields)

    def test_zero_strict_and_broadened_preview_returns_no_match(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        response, preview = self._run_endpoint(plan, [preview_payload(0), preview_payload(0)])
        body = json.loads(response.body)

        self.assertEqual(2, preview.call_count)
        self.assertEqual("no_match", body["status"])
        self.assertIsNone(body["optimization"]["selected_round"])

    def test_safe_broadening_preserves_hard_constraints(self):
        plan = normalized_plan(
            "goods",
            [clause("item_name", "máy thở"), clause("winning_bidder_name", "ABC")],
            [{
                "field": "decision_issued_at",
                "period": {"kind": "relative", "amount": 6, "unit": "months", "direction": "previous"},
                "inclusive": True,
            }],
        )
        _response, preview = self._run_endpoint(plan, [preview_payload(0), preview_payload(1)])

        strict_payload = preview.await_args_list[0].args[1]
        broadened_payload = preview.await_args_list[1].args[1]
        self.assertEqual(strict_payload.exactIdentifiers, broadened_payload.exactIdentifiers)
        self.assertEqual(strict_payload.dateRanges, broadened_payload.dateRanges)
        self.assertEqual(strict_payload.filters, broadened_payload.filters)
        self.assertEqual(strict_payload.text, broadened_payload.text)

    def test_non_goods_zero_preview_does_not_invent_broadening(self):
        plan = normalized_plan("medicines", [clause("medicine_name", "Meropenem")])
        response, preview = self._run_endpoint(plan, [preview_payload(0)])
        body = json.loads(response.body)

        self.assertEqual(1, preview.call_count)
        self.assertEqual("no_match", body["status"])
        self.assertEqual(1, len(body["optimization"]["rounds"]))


if __name__ == "__main__":
    unittest.main()
