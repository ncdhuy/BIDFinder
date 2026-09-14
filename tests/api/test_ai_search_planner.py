from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "apps" / "api"))

from ai_search_planner import (  # noqa: E402
    AI_SEARCH_PLAN_JSON_SCHEMA,
    BIDFINDER_TIMEZONE,
    AIPlannerConfigurationError,
    AIPlannerProviderError,
    AIPlannerValidationError,
    AIRelativePeriod,
    OpenAIResponsesPlanner,
    PlannerSettings,
    allowed_fields_for_group,
    build_planner_system_prompt,
    create_search_plan,
    resolve_relative_period,
    serialize_plan,
    validate_ai_search_plan,
)
from typesense_contract import get_search_contract  # noqa: E402
from ai_usage import AIUsageSnapshot  # noqa: E402


def make_plan(group: str, clauses=None, dates=None, warnings=None, explanation=None):
    return {
        "version": "1",
        "group": group,
        "clauses": clauses or [],
        "date_constraints": dates or [],
        "warnings": warnings or [],
        "explanation": explanation or [],
    }


def clause(field: str, *terms: str):
    return {
        "field": field,
        "concepts": [
            {"alternatives": [term]}
            for term in terms
        ],
        "join": "AND",
    }


def relative_date(field: str, amount: int, unit: str, direction: str = "previous"):
    return {
        "field": field,
        "period": {
            "kind": "relative",
            "amount": amount,
            "unit": unit,
            "direction": direction,
        },
        "inclusive": True,
    }


class StubProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def create_plan(self, *, group: str, message: str):
        self.calls.append((group, message))
        return self.payload


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


class PlannerSchemaTest(unittest.TestCase):
    def test_allowed_fields_come_from_group_contract(self):
        self.assertIn("item_name", allowed_fields_for_group("goods"))
        self.assertIn("medicine_name", allowed_fields_for_group("medicines"))
        self.assertNotIn("medicine_name", allowed_fields_for_group("goods"))
        self.assertIn("scientific_name", allowed_fields_for_group("traditional"))
        self.assertIn("decision_issued_at", allowed_fields_for_group("goods"))
        self.assertNotIn("id", allowed_fields_for_group("goods"))
        self.assertNotIn("data_group", allowed_fields_for_group("goods"))
        self.assertNotIn("source_tab", allowed_fields_for_group("goods"))
        self.assertNotIn("partition_date", allowed_fields_for_group("goods"))
        self.assertNotIn("quantity", allowed_fields_for_group("goods"))
        self.assertNotIn("winning_unit_price", allowed_fields_for_group("goods"))
        self.assertNotIn("bidder_count", allowed_fields_for_group("goods"))

    def test_contract_exposes_ai_planner_roles(self):
        fields = {
            field["name"]: field
            for field in get_search_contract()["groups"]["goods"]["fields"]
        }
        self.assertEqual("text", fields["item_name"]["ai_planner_role"])
        self.assertTrue(fields["item_name"]["ai_planning"])
        self.assertEqual("date", fields["decision_issued_at"]["ai_planner_role"])
        self.assertFalse(fields["quantity"]["ai_planning"])
        self.assertIsNone(fields["id"]["ai_planner_role"])

    def test_provider_schema_does_not_expose_match(self):
        concept_schema = AI_SEARCH_PLAN_JSON_SCHEMA["properties"]["clauses"]["items"]["properties"]["concepts"]["items"]
        self.assertNotIn("match", concept_schema["properties"])
        self.assertNotIn("match", concept_schema["required"])

    def test_wrong_group_is_rejected(self):
        with self.assertRaisesRegex(AIPlannerValidationError, "invalid AI search plan"):
            validate_ai_search_plan(make_plan("medicines", [clause("medicine_name", "amoxicilin")]), requested_group="goods")

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(make_plan("goods", [clause("made_up_field", "value")]), requested_group="goods")
        self.assertEqual("unknown_field", context.exception.category)

    def test_malformed_boolean_structure_is_rejected(self):
        payload = make_plan("goods", [
            {"field": "item_name", "concepts": [{"alternatives": ["máy"]}], "join": "OR"}
        ])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(payload, requested_group="goods")
        self.assertEqual("boolean_structure", context.exception.category)

    def test_empty_terms_are_removed_but_empty_concepts_fail_closed(self):
        payload = make_plan("goods", [
            {"field": "item_name", "concepts": [{"alternatives": ["", " máy  "]}], "join": "AND"}
        ])
        plan = validate_ai_search_plan(payload, requested_group="goods")
        self.assertEqual(["máy"], plan.clauses[0].concepts[0].alternatives)

        empty = make_plan("goods", [clause("item_name", "")])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(empty, requested_group="goods")
        self.assertEqual("empty_concepts", context.exception.category)

    def test_redundant_route_wrappers_collapse_to_atomic_keyword(self):
        plan = validate_ai_search_plan(
            make_plan(
                "medicines",
                [clause("route_of_administration", "uống", "đường uống", "đường dùng uống", "thuốc uống")],
            ),
            requested_group="medicines",
        )
        self.assertEqual(["uống"], plan.clauses[0].concepts[0].alternatives)

        empty_route = make_plan("medicines", [clause("route_of_administration", "đường dùng")])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(empty_route, requested_group="medicines")
        self.assertEqual("empty_concepts", context.exception.category)

    def test_match_is_derived_from_contract_roles(self):
        identifier = validate_ai_search_plan(
            make_plan("goods", [clause("bid_invitation_code", "IB2600498667")]),
            requested_group="goods",
        )
        self.assertEqual("exact", identifier.clauses[0].concepts[0].match)

        text = validate_ai_search_plan(
            make_plan("goods", [clause("item_name", "máy")]),
            requested_group="goods",
        )
        self.assertEqual("text", text.clauses[0].concepts[0].match)

        categorical = validate_ai_search_plan(
            make_plan("goods", [clause("unit", "cái")]),
            requested_group="goods",
        )
        self.assertEqual("text", categorical.clauses[0].concepts[0].match)

    def test_provider_controlled_match_is_rejected(self):
        payload = make_plan("goods", [clause("item_name", "máy")])
        payload["clauses"][0]["concepts"][0]["match"] = "exact"
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(payload, requested_group="goods")
        self.assertEqual("concept_shape", context.exception.category)

    def test_date_constraints_are_structural_and_date_fields_are_validated(self):
        plan = validate_ai_search_plan(
            make_plan("goods", dates=[relative_date("result_posted_at", 6, "months")]),
            requested_group="goods",
        )
        self.assertEqual(6, plan.date_constraints[0].period.amount)
        self.assertEqual("months", plan.date_constraints[0].period.unit)

        invalid = make_plan("goods", dates=[relative_date("item_name", 6, "months")])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(invalid, requested_group="goods")
        self.assertEqual("invalid_date_field", context.exception.category)

        date_clause = make_plan("goods", [clause("result_posted_at", "recent")])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(date_clause, requested_group="goods")
        self.assertEqual("date_field_as_text", context.exception.category)

    def test_prompt_states_supported_date_field_policy(self):
        prompt = build_planner_system_prompt("goods")
        self.assertIn("decision_issued_at", prompt)
        self.assertIn("result_posted_at", prompt)
        self.assertIn("Generic recent-period language", prompt)
        self.assertIn("winning_bidder_name", prompt)
        self.assertIn("combination-product strengths", prompt)
        self.assertIn("contextual container wording", prompt)
        self.assertIn("ngày đăng tải KQLCNT", prompt)
        self.assertNotIn("partition_date", prompt)
        self.assertNotIn("quantity", prompt)

    def test_prompt_states_procurement_company_role_policy(self):
        prompt = build_planner_system_prompt("medicines")
        self.assertIn("Commercial companies or businesses", prompt)
        self.assertIn("without an explicit manufacturing", prompt)
        self.assertIn("Use manufacturer only for explicit cues", prompt)
        self.assertIn("hãng", prompt)
        self.assertIn("nhà sản xuất", prompt)

    def test_prompt_states_institution_role_hierarchy(self):
        prompt = build_planner_system_prompt("traditional")
        for cue in ("Bệnh viện", "Trung tâm y tế", "Trạm y tế", "Phòng khám", "Viện", "Trường", "Đại học", "Sở", "Ban quản lý"):
            with self.subTest(cue=cue):
                self.assertIn(cue, prompt)
        self.assertIn("default to procuring_entity_name", prompt)
        self.assertIn("Commercial companies or businesses", prompt)

        for cue, field in (
            ("Công ty", "winning_bidder_name"),
            ("nhà sản xuất", "manufacturer"),
            ("nhà thầu", "winning_bidder_name"),
            ("chủ đầu tư", "procuring_entity_name"),
        ):
            with self.subTest(cue=cue):
                self.assertIn(cue, prompt)
                self.assertIn(field, prompt)

    def test_prompt_preserves_supplied_medicine_salt_form(self):
        prompt = build_planner_system_prompt("medicines")
        self.assertIn("X (dưới dạng Y)", prompt)
        self.assertIn("same active-ingredient concept", prompt)
        self.assertIn("use X as the primary keyword", prompt)
        self.assertIn("Do not discard Y's identity", prompt)
        self.assertIn("never copy the full parenthetical phrase", prompt)

    def test_prompt_distinguishes_medicine_name_from_active_ingredient(self):
        prompt = build_planner_system_prompt("medicines")
        self.assertIn("medicine_name (Tên thuốc or product name)", prompt)
        self.assertIn("active_ingredient_or_herbal_component (Hoạt chất or thành phần dược liệu)", prompt)
        self.assertIn("a recognized generic or INN substance name such as paracetamol, amoxicillin, metformin, or meropenem belongs to active_ingredient_or_herbal_component", prompt)
        self.assertIn('"paracetamol 150mg thuốc đặt" maps paracetamol to active_ingredient_or_herbal_component', prompt)
        self.assertIn('"tên thuốc Panadol 500mg" maps Panadol to medicine_name', prompt)
        self.assertIn("Never put the same value in both fields", prompt)
        self.assertIn("If the value is genuinely ambiguous", prompt)
        self.assertIn("Write warnings and explanation entries in Vietnamese", prompt)

    def test_prompt_requires_precise_keywords_and_non_redundant_synonyms(self):
        prompt = build_planner_system_prompt("medicines")
        self.assertIn("Prefer precise keyword extraction", prompt)
        self.assertIn("genuine spelling, INN, salt, or chemical-name variant", prompt)
        self.assertIn("For route_of_administration, extract the atomic route keyword", prompt)
        self.assertIn('"nefopam thuốc uống, kết quả 3 tháng gần nhất" yields route_of_administration alternatives ["uống"] only', prompt)
        self.assertIn("two AND concepts in active_ingredient_or_herbal_component", prompt)
        self.assertIn("primary keywords amoxicilin and clavulanic", prompt)

    def test_bounds_and_extra_keys_are_rejected(self):
        too_many = make_plan("goods", [clause("item_name", *[str(i) for i in range(25)])])
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(too_many, requested_group="goods")
        self.assertEqual("concept_bounds", context.exception.category)

        extra = make_plan("goods")
        extra["raw_typesense_query"] = "item_name:=*"
        with self.assertRaises(AIPlannerValidationError) as context:
            validate_ai_search_plan(extra, requested_group="goods")
        self.assertEqual("top_level_keys", context.exception.category)

    def test_relative_period_resolution_is_python_side(self):
        start, end = resolve_relative_period(
            AIRelativePeriod(kind="relative", amount=30, unit="days", direction="previous"),
            now=date(2026, 9, 12),
        )
        self.assertEqual((date(2026, 8, 13), date(2026, 9, 12)), (start, end))
        start, end = resolve_relative_period(
            AIRelativePeriod(kind="relative", amount=1, unit="years", direction="current"),
            now=date(2026, 9, 12),
        )
        self.assertEqual((date(2026, 1, 1), date(2026, 12, 31)), (start, end))

        start, end = resolve_relative_period(
            AIRelativePeriod(kind="relative", amount=1, unit="months", direction="previous"),
            now=date(2024, 3, 31),
        )
        self.assertEqual((date(2024, 2, 29), date(2024, 3, 31)), (start, end))

        start, end = resolve_relative_period(
            AIRelativePeriod(kind="relative", amount=1, unit="years", direction="current"),
            now=date(2024, 12, 31),
        )
        self.assertEqual((date(2024, 1, 1), date(2024, 12, 31)), (start, end))

        start, end = resolve_relative_period(
            AIRelativePeriod(kind="relative", amount=1, unit="days", direction="previous"),
            now=datetime(2026, 9, 11, 17, tzinfo=timezone.utc),
        )
        self.assertEqual((date(2026, 9, 11), date(2026, 9, 12)), (start, end))
        self.assertEqual("Asia/Ho_Chi_Minh", getattr(BIDFINDER_TIMEZONE, "key", BIDFINDER_TIMEZONE.tzname(None)))


class GoldenPlannerSemanticTest(unittest.TestCase):
    def test_goods_golden_case(self):
        verbose_source = "Thủy tinh thể nhân tạo mềm, đơn tiêu, kéo dài tiêu điểm, màu vàng, 4 càng"
        plan = validate_ai_search_plan(
            make_plan(
                "goods",
                clauses=[
                    clause("item_name", "Thủy tinh thể nhân tạo", "vàng", "4 càng"),
                    clause("procuring_entity_name", "Nguyễn Trãi"),
                ],
                dates=[relative_date("result_posted_at", 6, "months")],
                explanation=["Tên và thuộc tính phân biệt vào item_name", "Bệnh viện vào procuring_entity_name"],
            ),
            requested_group="goods",
        )
        terms = [term for c in plan.clauses for concept in c.concepts for term in concept.alternatives]
        self.assertIn("Thủy tinh thể nhân tạo", terms)
        self.assertIn("vàng", terms)
        self.assertIn("4 càng", terms)
        self.assertNotIn(verbose_source, terms)
        self.assertEqual("Nguyễn Trãi", plan.clauses[1].concepts[0].alternatives[0])
        self.assertEqual((6, "months", "previous"), (
            plan.date_constraints[0].period.amount,
            plan.date_constraints[0].period.unit,
            plan.date_constraints[0].period.direction,
        ))

    def test_medicine_golden_case(self):
        plan = validate_ai_search_plan(
            make_plan(
                "medicines",
                clauses=[
                    {
                        "field": "active_ingredient_or_herbal_component",
                        "concepts": [
                            {"alternatives": ["clavulanic", "clavulanat"]},
                            {"alternatives": ["amoxicilin"]},
                        ],
                        "join": "AND",
                    },
                    clause("strength", "62,5", "500"),
                    clause("winning_bidder_name", "hậu giang"),
                    clause("location", "Hà Nội"),
                ],
                explanation=["Hoạt chất và dạng muối cùng một concept OR"],
            ),
            requested_group="medicines",
        )
        active = next(c for c in plan.clauses if c.field == "active_ingredient_or_herbal_component")
        self.assertEqual(["clavulanic", "clavulanat"], active.concepts[0].alternatives)
        self.assertEqual("amoxicilin", active.concepts[1].alternatives[0])
        strength = next(c for c in plan.clauses if c.field == "strength")
        self.assertEqual({"62,5", "500"}, {c.alternatives[0] for c in strength.concepts})
        self.assertNotIn("silicon dioxyd", json.dumps(serialize_plan(plan), ensure_ascii=False))
        self.assertEqual("hậu giang", next(c for c in plan.clauses if c.field == "winning_bidder_name").concepts[0].alternatives[0])
        self.assertEqual("Hà Nội", next(c for c in plan.clauses if c.field == "location").concepts[0].alternatives[0])

    def test_traditional_medicine_realistic_cases(self):
        cases = [
            ("herbal/common name", "item_name", "Đan sâm"),
            ("scientific name", "scientific_name", "Salvia miltiorrhiza"),
            ("used part", "used_part", "rễ"),
            ("processing method", "processing_method", "sao vàng"),
            ("manufacturer", "manufacturer", "Đông Dược Văn Hương"),
            ("hospital", "procuring_entity_name", "Bệnh viện đa khoa Minh Hóa"),
            ("location", "location", "Quảng Trị"),
            ("origin", "origin", "Lào Cai"),
            ("country", "production_country", "Việt Nam"),
            ("packaging", "packaging", "túi 500g"),
            ("technical group", "technical_group", "dược liệu chuẩn hóa"),
        ]
        for label, field, term in cases:
            with self.subTest(label=label):
                plan = validate_ai_search_plan(make_plan("traditional", [clause(field, term)]), requested_group="traditional")
                self.assertEqual(term, plan.clauses[0].concepts[0].alternatives[0])

    def test_additional_goods_and_medicine_cases(self):
        cases = [
            ("goods model and brand", "goods", [("model_mark", "ABC-220"), ("brand", "Philips")]),
            ("goods technical description", "goods", [("technical_specification", "IP65"), ("technical_specification", "220V")]),
            ("goods unit", "goods", [("unit", "cái")]),
            ("goods manufacturer", "goods", [("manufacturer", "Bosch")]),
            ("goods origin", "goods", [("country_of_origin", "Nhật Bản")]),
            ("goods HS code", "goods", [("hs_code", "9018.90")]),
            ("goods exact decision", "goods", [("decision_number", "184/QĐ-MN14")]),
            ("goods exact permit", "goods", [("registration_or_import_permit_number", "VN-12345")]),
            ("medicine dosage form", "medicines", [("dosage_form", "viên nang cứng")]),
            ("medicine route", "medicines", [("route_of_administration", "uống")]),
            ("medicine packaging", "medicines", [("packaging", "hộp 10 vỉ x 10 viên")]),
            ("medicine shelf life", "medicines", [("shelf_life", "36 tháng")]),
            ("medicine group", "medicines", [("medicine_group", "Generic")]),
            ("medicine mixed English", "medicines", [("medicine_name", "extended-release tablet"), ("strength", "500 mg")]),
            ("medicine permit exact", "medicines", [("marketing_authorization_or_import_permit", "893110140124")]),
            ("medicine production country", "medicines", [("production_country", "India")]),
            ("common selection method", "goods", [("selection_method", "đấu thầu rộng rãi")]),
            ("common bidder", "traditional", [("winning_bidder_name", "Công ty TNHH Đông Dược")]),
            ("common procuring entity", "medicines", [("procuring_entity_name", "Bệnh viện Nguyễn Trãi")]),
            ("same field from separate segments", "goods", [("item_name", "máy thở"), ("item_name", "di động")]),
            ("one source segment maps multiple fields", "medicines", [("medicine_name", "Amoxicilin"), ("strength", "500mg"), ("dosage_form", "viên"), ("route_of_administration", "uống")]),
            ("filler warning", "goods", []),
            ("diacritics", "traditional", [("scientific_name", "Cà gai leo")]),
        ]
        for label, group, fields in cases:
            with self.subTest(label=label):
                warnings = ["Không xác định được trường tìm kiếm"] if label == "filler warning" else []
                clauses = [clause(field, term) for field, term in fields]
                plan = validate_ai_search_plan(make_plan(group, clauses, warnings=warnings), requested_group=group)
                self.assertEqual(group, plan.group)
                self.assertEqual(len(fields), sum(len(c.concepts) for c in plan.clauses))


class PlannerProviderTest(unittest.TestCase):
    def test_mocked_provider_success_and_group_is_forwarded(self):
        payload = make_plan("goods", [clause("item_name", "máy thở")])
        provider = StubProvider(payload)
        result = asyncio.run(create_search_plan("goods", "máy thở", provider=provider))
        self.assertEqual("goods", result.group)
        self.assertEqual([("goods", "máy thở")], provider.calls)

    def test_missing_configuration_fails_without_provider_call(self):
        environment = dict(os.environ)
        environment["BIDFINDER_AI_ENABLED"] = "true"
        environment.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(AIPlannerConfigurationError) as context:
                asyncio.run(create_search_plan("goods", "máy thở"))
        self.assertEqual("missing_api_key", context.exception.category)

    def test_provider_failure_and_invalid_output_fail_closed(self):
        class TimeoutProvider:
            async def create_plan(self, **_kwargs):
                raise AIPlannerProviderError("timeout", category="provider_transport")

        with self.assertRaises(AIPlannerProviderError):
            asyncio.run(create_search_plan("goods", "máy thở", provider=TimeoutProvider()))

        invalid = StubProvider(make_plan("medicines", [clause("medicine_name", "amoxicilin")]))
        with self.assertRaises(AIPlannerValidationError) as context:
            asyncio.run(create_search_plan("goods", "amoxicilin", provider=invalid))
        self.assertEqual("group_mismatch", context.exception.category)

        malformed = StubProvider({"version": "1", "group": "goods"})
        with self.assertRaises(AIPlannerValidationError) as context:
            asyncio.run(create_search_plan("goods", "máy thở", provider=malformed))
        self.assertEqual("top_level_keys", context.exception.category)

    def test_openai_adapter_uses_strict_structured_output(self):
        returned = make_plan("goods", [clause("item_name", "máy thở")])
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(returned, ensure_ascii=False)}]}]}
        settings = PlannerSettings(True, "test-key", "gpt-5.6-luna", 3.0)
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(response)

        with patch("ai_search_planner.urlopen", fake_urlopen):
            raw = asyncio.run(OpenAIResponsesPlanner(settings).create_plan(group="goods", message="máy thở"))
        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(returned, raw)
        self.assertEqual("gpt-5.6-luna", body["model"])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(AI_SEARCH_PLAN_JSON_SCHEMA, body["text"]["format"]["schema"])
        self.assertEqual(3.0, captured["timeout"])


class PlannerRateLimitTest(unittest.TestCase):
    @staticmethod
    def request():
        from starlette.requests import Request

        return Request({
            "type": "http",
            "method": "POST",
            "path": "/api/ai/search-plan",
            "headers": [(b"user-agent", b"planner-test")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8001),
            "scheme": "http",
        })

    def test_endpoint_returns_plan_without_executing_search(self):
        import server

        plan = validate_ai_search_plan(make_plan("goods", [clause("item_name", "máy thở")]), requested_group="goods")
        async def exercise():
            async with server.rate_limit_lock:
                server.rate_limit_buckets.clear()
            with patch("server.create_search_plan", new=AsyncMock(return_value=plan)), patch(
                "server.get_planner_settings",
                return_value=PlannerSettings(True, "test-key", "gpt-5.6-luna", 3.0),
            ), patch(
                "server._ai_usage_snapshot",
                new=AsyncMock(return_value=AIUsageSnapshot(0.0, 30000.0, 0, 100, "2026-09-14T00:00:00+07:00")),
            ):
                return await server.create_ai_search_plan(
                    self.request(),
                    server.AIPlanRequest(group="goods", message="máy thở"),
                )

        response = asyncio.run(exercise())
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(200, response.status_code)
        self.assertTrue(body["success"])
        self.assertEqual("goods", body["plan"]["group"])
        self.assertEqual("v0.1.4", body["meta"]["planner_version"])

    def test_luna_rate_limit_uses_ip_scoped_limiter(self):
        import server
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/search-plan",
            "headers": [(b"user-agent", b"planner-test")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8001),
            "scheme": "http",
        }
        request = Request(scope)

        async def exercise():
            async with server.rate_limit_lock:
                server.rate_limit_buckets.clear()
            first = await server.enforce_rate_limit(request, "ai-search-luna", 1, include_user_agent=False)
            second = await server.enforce_rate_limit(request, "ai-search-luna", 1, include_user_agent=False)
            return first, second

        first, second = asyncio.run(exercise())
        self.assertIsNone(first)
        self.assertEqual(429, second.status_code)


if __name__ == "__main__":
    unittest.main()
