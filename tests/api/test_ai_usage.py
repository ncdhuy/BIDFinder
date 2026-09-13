from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import server as server_module  # noqa: E402
from ai_search_planner import extract_provider_usage, normalize_usage_units, validate_ai_search_plan  # noqa: E402
from ai_usage import AIUsageStore  # noqa: E402


@contextmanager
def test_store():
    path = ROOT / f".tmp-ai-usage-{os.getpid()}.sqlite3"
    path.unlink(missing_ok=True)
    try:
        yield AIUsageStore(path)
    finally:
        path.unlink(missing_ok=True)


def make_request(path: str, cookie: str = "a" * 32):
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "GET" if path.endswith("/usage") else "POST",
        "path": path,
        "headers": [(b"cookie", f"bidfinder_ai_anon={cookie}".encode("ascii"))],
        "client": ("198.51.100.10", 1234),
        "server": ("127.0.0.1", 8001),
        "scheme": "http",
    })


class AIUsageTest(unittest.TestCase):
    def test_provider_usage_extraction_and_weighting(self):
        usage = extract_provider_usage({
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens": 30,
                "total_tokens": 130,
            }
        })
        self.assertEqual({
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "output_tokens": 30,
            "total_tokens": 130,
        }, usage)
        self.assertEqual(165.0, normalize_usage_units(usage))
        self.assertEqual({"total_tokens": 17}, extract_provider_usage({"usage": {"total_tokens": 17}}))
        self.assertIsNone(extract_provider_usage({"usage": {"input_tokens": 4}}))

    def test_sqlite_ledger_is_transactional_and_keyed_by_day(self):
        with test_store() as store:
            self.assertEqual(1.5, store.add_units("anon:hash", "2026-09-13", 1.5))
            self.assertEqual(4.0, store.add_units("anon:hash", "2026-09-13", 2.5))
            self.assertEqual(4.0, store.get_units("anon:hash", "2026-09-13"))
            self.assertEqual(0.0, store.get_units("anon:hash", "2026-09-14"))

    def test_message_preview_counts_provider_usage_and_usage_endpoint_reads_same_identity(self):
        plan = validate_ai_search_plan({
            "version": "1",
            "group": "goods",
            "clauses": [],
            "date_constraints": [],
            "warnings": [],
            "explanation": [],
        }, requested_group="goods")
        plan._provider_usage = {"input_tokens": 10, "output_tokens": 10}
        with test_store() as store:
            with patch.object(server_module, "ai_usage_store", store), \
                 patch.object(server_module, "AI_DAILY_USAGE_BUDGET_ANON", 100.0), \
                 patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
                 patch.object(server_module, "create_search_plan", new=AsyncMock(return_value=plan)), \
                 patch.object(server_module, "_execute_ai_search_preview", new=AsyncMock(return_value=server_module.JSONResponse(content={"success": True, "preview": {"total": 2}}))):
                response = asyncio.run(server_module.create_ai_search_preview(
                    make_request("/api/ai/search-preview"),
                    server_module.AISearchPreviewRequest(group="goods", message="test"),
                ))
                usage_response = asyncio.run(server_module.get_ai_usage(make_request("/api/ai/usage")))

        body = json.loads(response.body)
        usage_body = json.loads(usage_response.body)
        self.assertTrue(body["ai_usage"]["counted"])
        self.assertEqual(30, body["ai_usage"]["used_percent"])
        self.assertEqual(30, usage_body["ai_usage"]["used_percent"])
        self.assertFalse(usage_body["ai_usage"]["counted"])

    def test_exhausted_budget_rejects_before_provider(self):
        with test_store() as store:
            planner = AsyncMock()
            with patch.object(server_module, "ai_usage_store", store), \
                 patch.object(server_module, "AI_DAILY_USAGE_BUDGET_ANON", 0.0), \
                 patch.object(server_module, "enforce_rate_limit", new=AsyncMock(return_value=None)), \
                 patch.object(server_module, "create_search_plan", new=planner):
                response = asyncio.run(server_module.create_ai_search_plan(
                    make_request("/api/ai/search-plan"),
                    server_module.AIPlanRequest(group="goods", message="test"),
                ))

        body = json.loads(response.body)
        self.assertEqual(429, response.status_code)
        self.assertEqual("ai_daily_usage_exhausted", body["error"])
        self.assertEqual("\u0042\u1ea1n \u0111\u00e3 s\u1eed d\u1ee5ng h\u1ebft AI h\u00f4m nay. H\u1ea1n m\u1ee9c s\u1ebd \u0111\u01b0\u1ee3c \u0111\u1eb7t l\u1ea1i v\u00e0o ng\u00e0y mai.", body["message"])
        self.assertFalse(body["ai_usage"]["counted"])
        planner.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
