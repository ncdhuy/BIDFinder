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
        payload = server_module.AISearchPreviewRequest(group=plan.group, message="test")
        preview = AsyncMock(side_effect=responses)
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "create_search_plan", new=AsyncMock(return_value=plan)), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(request, payload))
        return response, preview

    def test_message_mode_uses_shared_luna_rate_limit(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        request = object()
        payload = server_module.AISearchPreviewRequest(group="goods", message="máy thở")
        limiter = AsyncMock(return_value=None)
        with patch.object(server_module, "enforce_rate_limit", new=limiter), \
             patch.object(server_module, "create_search_plan", new=AsyncMock(return_value=plan)), \
             patch.object(server_module, "execute_query_preview", new=AsyncMock(return_value=preview_payload(1))):
            asyncio.run(server_module.create_ai_search_preview(request, payload))

        limiter.assert_awaited_once_with(
            request,
            "ai-search-luna",
            server_module.AI_SEARCH_LUNA_RATE_LIMIT_PER_MINUTE,
            include_user_agent=False,
        )

    def test_edited_plan_mode_keeps_existing_preview_rate_limit_bucket(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        request = object()
        payload = server_module.AISearchPreviewRequest(group="goods", plan=server_module.serialize_plan(plan))
        limiter = AsyncMock(return_value=None)
        with patch.object(server_module, "enforce_rate_limit", new=limiter), \
             patch.object(server_module, "execute_query_preview", new=AsyncMock(return_value=preview_payload(1))):
            asyncio.run(server_module.create_ai_search_preview(request, payload))

        limiter.assert_awaited_once_with(
            request,
            "ai-search-edited-plan",
            server_module.AI_SEARCH_PREVIEW_RATE_LIMIT_PER_MINUTE,
            include_user_agent=True,
        )

    def test_luna_limit_ignores_user_agent_rotation(self):
        from starlette.requests import Request

        def make_request(user_agent):
            return Request({
                "type": "http",
                "method": "POST",
                "path": "/api/ai/search-preview",
                "headers": [(b"user-agent", user_agent.encode("ascii"))],
                "client": ("198.51.100.10", 1234),
                "server": ("127.0.0.1", 8001),
                "scheme": "http",
            })

        async def exercise():
            async with server_module.rate_limit_lock:
                server_module.rate_limit_buckets.clear()
            first = await server_module.enforce_rate_limit(
                make_request("ua-one"), "ai-search-luna", 2, include_user_agent=False
            )
            second = await server_module.enforce_rate_limit(
                make_request("ua-two"), "ai-search-luna", 2, include_user_agent=False
            )
            third = await server_module.enforce_rate_limit(
                make_request("ua-three"), "ai-search-luna", 2, include_user_agent=False
            )
            return first, second, third

        first, second, third = asyncio.run(exercise())
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(429, third.status_code)

    def test_luna_quota_is_shared_across_planner_and_message_preview(self):
        plan = normalized_plan("goods", [clause("item_name", "mÃ¡y thá»Ÿ")])
        planner = AsyncMock(return_value=plan)
        preview = AsyncMock(return_value=preview_payload(1))

        def make_request(path, user_agent):
            from starlette.requests import Request

            return Request({
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"user-agent", user_agent.encode("ascii"))],
                "client": ("198.51.100.10", 1234),
                "server": ("127.0.0.1", 8001),
                "scheme": "http",
            })

        async def exercise():
            async with server_module.rate_limit_lock:
                server_module.rate_limit_buckets.clear()
            with patch.object(server_module, "AI_SEARCH_LUNA_RATE_LIMIT_PER_MINUTE", 2), \
                 patch.object(server_module, "create_search_plan", new=planner), \
                 patch.object(server_module, "_execute_ai_search_preview", new=preview):
                first = await server_module.create_ai_search_plan(
                    make_request("/api/ai/search-plan", "ua-a"),
                    server_module.AIPlanRequest(group="goods", message="mÃ¡y thá»Ÿ"),
                )
                second = await server_module.create_ai_search_preview(
                    make_request("/api/ai/search-preview", "ua-b"),
                    server_module.AISearchPreviewRequest(group="goods", message="mÃ¡y thá»Ÿ"),
                )
                third = await server_module.create_ai_search_preview(
                    make_request("/api/ai/search-preview", "ua-c"),
                    server_module.AISearchPreviewRequest(group="goods", message="mÃ¡y thá»Ÿ"),
                )
            return first, second, third

        first, second, third = asyncio.run(exercise())
        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(429, third.status_code)
        self.assertEqual(2, planner.await_count)

    def test_luna_quota_is_independent_per_client_ip(self):
        from starlette.requests import Request

        def make_request(client_ip):
            return Request({
                "type": "http",
                "method": "POST",
                "path": "/api/ai/search-plan",
                "headers": [(b"user-agent", b"same-ua")],
                "client": (client_ip, 1234),
                "server": ("127.0.0.1", 8001),
                "scheme": "http",
            })

        async def exercise():
            async with server_module.rate_limit_lock:
                server_module.rate_limit_buckets.clear()
            first = await server_module.enforce_rate_limit(
                make_request("198.51.100.10"), "ai-search-luna", 1, include_user_agent=False
            )
            second = await server_module.enforce_rate_limit(
                make_request("198.51.100.11"), "ai-search-luna", 1, include_user_agent=False
            )
            third = await server_module.enforce_rate_limit(
                make_request("198.51.100.10"), "ai-search-luna", 1, include_user_agent=False
            )
            return first, second, third

        first, second, third = asyncio.run(exercise())
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(429, third.status_code)

    def test_edited_plan_does_not_consume_luna_quota(self):
        plan = normalized_plan("goods", [clause("item_name", "mÃ¡y thá»Ÿ")])
        planner = AsyncMock(return_value=plan)
        preview = AsyncMock(return_value=preview_payload(1))

        def make_request(path, user_agent="test-ua"):
            from starlette.requests import Request

            return Request({
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"user-agent", user_agent.encode("ascii"))],
                "client": ("198.51.100.10", 1234),
                "server": ("127.0.0.1", 8001),
                "scheme": "http",
            })

        async def exercise():
            async with server_module.rate_limit_lock:
                server_module.rate_limit_buckets.clear()
            with patch.object(server_module, "AI_SEARCH_LUNA_RATE_LIMIT_PER_MINUTE", 1), \
                 patch.object(server_module, "AI_SEARCH_PREVIEW_RATE_LIMIT_PER_MINUTE", 1), \
                 patch.object(server_module, "create_search_plan", new=planner), \
                 patch.object(server_module, "execute_query_preview", new=preview):
                edited_payload = server_module.AISearchPreviewRequest(
                    group="goods",
                    plan=server_module.serialize_plan(plan),
                )
                edited = await server_module.create_ai_search_preview(
                    make_request("/api/ai/search-preview"), edited_payload
                )
                edited_limited = await server_module.create_ai_search_preview(
                    make_request("/api/ai/search-preview"), edited_payload
                )
                planner_response = await server_module.create_ai_search_plan(
                    make_request("/api/ai/search-plan", "rotated-ua"),
                    server_module.AIPlanRequest(group="goods", message="mÃ¡y thá»Ÿ"),
                )
            return edited, edited_limited, planner_response

        edited, edited_limited, planner_response = asyncio.run(exercise())
        self.assertEqual(200, edited.status_code)
        self.assertFalse(json.loads(edited.body)["meta"]["planner_invoked"])
        self.assertEqual(429, edited_limited.status_code)
        self.assertEqual(200, planner_response.status_code)
        planner.assert_awaited_once_with("goods", "mÃ¡y thá»Ÿ")
        preview.assert_awaited_once()

    def test_trusted_proxy_rate_limit_uses_forwarded_client_ip(self):
        from starlette.requests import Request

        def make_request(peer_ip, forwarded_ip):
            return Request({
                "type": "http",
                "method": "POST",
                "path": "/api/ai/search-plan",
                "headers": [
                    (b"user-agent", b"proxy-test"),
                    (b"x-forwarded-for", forwarded_ip.encode("ascii")),
                ],
                "client": (peer_ip, 1234),
                "server": ("127.0.0.1", 8001),
                "scheme": "http",
            })

        trusted_a = make_request("127.0.0.1", "203.0.113.20")
        trusted_b = make_request("127.0.0.1", "203.0.113.21")
        untrusted = make_request("198.51.100.10", "203.0.113.20")

        async def exercise():
            async with server_module.rate_limit_lock:
                server_module.rate_limit_buckets.clear()
            first = await server_module.enforce_rate_limit(
                trusted_a, "ai-search-luna", 1, include_user_agent=False
            )
            second = await server_module.enforce_rate_limit(
                trusted_b, "ai-search-luna", 1, include_user_agent=False
            )
            third = await server_module.enforce_rate_limit(
                trusted_a, "ai-search-luna", 1, include_user_agent=False
            )
            return first, second, third

        with patch.object(server_module, "TRUST_PROXY_HEADERS", True), patch.object(
            server_module,
            "TRUSTED_PROXY_IPS",
            {server_module.ipaddress.ip_address("127.0.0.1")},
        ):
            self.assertEqual("203.0.113.20", server_module.get_client_ip(trusted_a))
            self.assertEqual("198.51.100.10", server_module.get_client_ip(untrusted))
            first, second, third = asyncio.run(exercise())

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(429, third.status_code)

    def test_initial_message_mode_invokes_planner(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        planner = AsyncMock(return_value=plan)
        preview = AsyncMock(return_value=preview_payload(3))
        request = object()
        payload = server_module.AISearchPreviewRequest(group="goods", message="máy thở")
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "create_search_plan", new=planner), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(request, payload))

        planner.assert_awaited_once_with("goods", "máy thở")
        self.assertTrue(json.loads(response.body)["meta"]["planner_invoked"])

    def test_edited_plan_mode_skips_planner_and_preserves_grouped_concepts(self):
        plan = normalized_plan(
            "medicines",
            [{
                "field": "active_ingredient_or_herbal_component",
                "concepts": [
                    {"alternatives": ["clavulanic", "clavulanat"]},
                    {"alternatives": ["amoxicilin", "amoxicillin"]},
                ],
                "join": "AND",
            }],
        )
        planner = AsyncMock(side_effect=AssertionError("planner must not run in edited mode"))
        preview = AsyncMock(return_value=preview_payload(5))
        request = object()
        payload = server_module.AISearchPreviewRequest(group="medicines", plan=server_module.serialize_plan(plan))
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "create_search_plan", new=planner), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(request, payload))

        planner.assert_not_awaited()
        body = json.loads(response.body)
        self.assertFalse(body["meta"]["planner_invoked"])
        self.assertEqual([
            {"alternatives": ["clavulanic", "clavulanat"], "match": "text"},
            {"alternatives": ["amoxicilin", "amoxicillin"], "match": "text"},
        ], body["plan"]["clauses"][0]["concepts"])
        self.assertEqual([
            ["clavulanic", "clavulanat"],
            ["amoxicilin", "amoxicillin"],
        ], [group.alternatives for group in preview.await_args.args[1].filters.activeIngredient.groups])

    def test_preview_requires_exactly_one_mode(self):
        plan = normalized_plan("goods")
        request = object()
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)):
            both = asyncio.run(server_module.create_ai_search_preview(
                request,
                server_module.AISearchPreviewRequest(group="goods", message="máy thở", plan=server_module.serialize_plan(plan)),
            ))
            neither = asyncio.run(server_module.create_ai_search_preview(
                request,
                server_module.AISearchPreviewRequest(group="goods"),
            ))

        self.assertEqual(400, both.status_code)
        self.assertEqual(400, neither.status_code)

    def test_edited_plan_group_mismatch_fails_closed(self):
        plan = normalized_plan("goods", [clause("item_name", "máy thở")])
        preview = AsyncMock(return_value=preview_payload(5))
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(
                object(),
                server_module.AISearchPreviewRequest(group="medicines", plan=server_module.serialize_plan(plan)),
            ))

        self.assertEqual(422, response.status_code)
        preview.assert_not_awaited()

    def test_invalid_edited_plan_fails_closed(self):
        preview = AsyncMock(return_value=preview_payload(5))
        invalid = {
            "version": "1",
            "group": "goods",
            "clauses": [{"field": "not_a_contract_field", "concepts": [{"alternatives": ["x"]}], "join": "AND"}],
            "date_constraints": [],
            "warnings": [],
            "explanation": [],
        }
        with patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
             patch.object(server_module, "execute_query_preview", new=preview):
            response = asyncio.run(server_module.create_ai_search_preview(
                object(),
                server_module.AISearchPreviewRequest(group="goods", plan=invalid),
            ))

        self.assertEqual(422, response.status_code)
        preview.assert_not_awaited()

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
