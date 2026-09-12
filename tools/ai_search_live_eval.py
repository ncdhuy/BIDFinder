"""Opt-in semantic evaluation for the real BIDFinder AI search planner."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import unicodedata
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from ai_search_planner import (  # noqa: E402
    AIPlannerError,
    AISearchPlan,
    OpenAIResponsesPlanner,
    create_search_plan,
    get_planner_settings,
    serialize_plan,
)


def _case(case_id: str, group: str, message: str, expectations: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": case_id, "group": group, "message": message, "expectations": expectations}


CASES: tuple[dict[str, Any], ...] = (
    _case(
        "goods_core_iol_recent",
        "goods",
        "Thủy tinh thể nhân tạo mềm, đơn tiêu, kéo dài tiêu điểm, màu vàng, 4 càng; Bệnh viện Nguyễn Trãi; 6 tháng gần nhất",
        {
            "required": [
                {"field": "item_name", "all": ["Thủy tinh thể nhân tạo", "vàng", "4 càng"]},
                {"field": "procuring_entity_name", "all": ["Nguyễn Trãi"]},
            ],
            "dates": [{"field": "decision_issued_at", "amount": 6, "unit": "months", "direction": "previous"}],
            "not_phrases": ["Thủy tinh thể nhân tạo mềm, đơn tiêu, kéo dài tiêu điểm, màu vàng, 4 càng"],
            "forbidden_fields": ["id", "data_group", "source_tab", "source_tab_label", "partition_date", "quantity", "winning_unit_price", "bidder_count"],
        },
    ),
    _case(
        "goods_exact_tbmt",
        "goods",
        "Mã TBMT IB2600498667",
        {"exact_identifiers": [{"field": "bid_invitation_code", "value": "IB2600498667"}]},
    ),
    _case(
        "goods_device_model_brand_hospital",
        "goods",
        "Máy theo dõi bệnh nhân IntelliVue MX450 Philips; Bệnh viện Chợ Rẫy",
        {
            "required": [
                {"fields": ["item_name"], "any": ["máy theo dõi", "bệnh nhân"]},
                {"fields": ["model_mark", "model"], "any": ["IntelliVue", "MX450"]},
                {"field": "brand", "all": ["Philips"]},
                {"field": "procuring_entity_name", "all": ["Chợ Rẫy"]},
            ],
            "not_phrases": ["Máy theo dõi bệnh nhân IntelliVue MX450 Philips"],
        },
    ),
    _case(
        "goods_categorical_attributes",
        "goods",
        "Gói thầu mua máy thở di động; đơn vị tính bộ; sản xuất năm 2025; xuất xứ Nhật Bản",
        {
            "required": [
                {"field": "item_name", "all": ["máy thở"]},
                {"field": "unit", "all": ["bộ"]},
                {"field": "production_year", "all": ["2025"]},
                {"field": "country_of_origin", "all": ["Nhật Bản"]},
            ]
        },
    ),
    _case(
        "goods_technical_model_manufacturer",
        "goods",
        "Máy siêu âm; model ACME-900; thông số IP65 220V; hãng Bosch",
        {
            "required": [
                {"field": "item_name", "all": ["Máy siêu âm"]},
                {"fields": ["model_mark", "model"], "all": ["ACME-900"]},
                {"field": "technical_specification", "all": ["IP65", "220V"]},
                {"field": "manufacturer", "all": ["Bosch"]},
            ]
        },
    ),
    _case(
        "goods_noise_numeric_metadata",
        "goods",
        "Thiết bị y tế; số lượng 25; giá 3.000.000; 2 nhà thầu; nguồn HANG_HOA",
        {
            "required": [{"field": "item_name", "all": ["Thiết bị y tế"]}],
            "forbidden_fields": ["quantity", "winning_unit_price", "bidder_count", "source_tab", "source_tab_label", "data_group"],
            "not_terms": ["3.000.000", "HANG_HOA"],
        },
    ),
    _case(
        "goods_selection_location",
        "goods",
        "Đấu thầu rộng rãi cho Bệnh viện Bạch Mai tại Hà Nội",
        {
            "required": [
                {"field": "selection_method", "any": ["đấu thầu rộng rãi", "rộng rãi"]},
                {"field": "procuring_entity_name", "all": ["Bạch Mai"]},
                {"field": "location", "all": ["Hà Nội"]},
            ]
        },
    ),
    _case(
        "goods_exact_identifiers",
        "goods",
        "Quyết định 184/QĐ-MN14; số lưu hành VN-12345; mã HS 9018.90",
        {
            "exact_identifiers": [
                {"field": "decision_number", "value": "184/QĐ-MN14"},
                {"field": "registration_or_import_permit_number", "value": "VN-12345"},
                {"field": "hs_code", "value": "9018.90"},
            ]
        },
    ),
    _case(
        "goods_explicit_result_date",
        "goods",
        "Găng tay y tế; kết quả lựa chọn nhà thầu đăng tải trong 3 tháng gần đây",
        {
            "required": [{"field": "item_name", "all": ["Găng tay y tế"]}],
            "dates": [{"field": "result_posted_at", "amount": 3, "unit": "months", "direction": "previous"}],
            "forbidden_date_fields": ["decision_issued_at"],
        },
    ),
    _case(
        "goods_generic_current_year",
        "goods",
        "Vật tư tiêu hao trong năm nay",
        {
            "required": [{"field": "item_name", "all": ["Vật tư tiêu hao"]}],
            "dates": [{"field": "decision_issued_at", "amount": 1, "unit": "years", "direction": "current"}],
        },
    ),
    _case(
        "medicine_salts_strength_bidder_location",
        "medicines",
        "Gói 2g thuốc chứa: Acid clavulanic (dưới dạng kali clavulanat & silicon dioxyd); Amoxicilin (dưới dạng amoxicilin trihydrat); 62,5mg + 500mg; CÔNG TY CỔ PHẦN DƯỢC HẬU GIANG; Hà Nội",
        {
            "required": [
                {"field": "strength", "all": ["62,5", "500"]},
                {"field": "winning_bidder_name", "all": ["Hậu Giang"]},
                {"field": "location", "all": ["Hà Nội"]},
            ],
            "concept_groups": [{
                "field": "active_ingredient_or_herbal_component",
                "groups": [{"alternatives_all": ["clavulanic", "clavulanat"]}, {"all": ["amoxicilin"]}],
            }],
            "not_terms": ["silicon dioxyd"],
            "not_phrases": ["Gói 2g thuốc chứa: Acid clavulanic (dưới dạng kali clavulanat & silicon dioxyd)"],
        },
    ),
    _case(
        "medicine_meropenem_form_route",
        "medicines",
        "Meropenem 1g lọ bột pha tiêm tĩnh mạch",
        {
            "required": [
                {"fields": ["medicine_name", "active_ingredient_or_herbal_component"], "all": ["Meropenem"]},
                {"field": "strength", "any": ["1g", "1 g"]},
                {"fields": ["dosage_form", "packaging"], "all": ["bột pha tiêm"]},
                {"fields": ["packaging", "dosage_form"], "any": ["lọ"]},
                {"field": "route_of_administration", "all": ["tĩnh mạch"]},
            ]
        },
    ),
    _case(
        "medicine_metformin_no_invention",
        "medicines",
        "Metformin XR 500 mg",
        {
            "required": [
                {"fields": ["medicine_name", "active_ingredient_or_herbal_component"], "all": ["Metformin"]},
                {"field": "strength", "any": ["500", "500 mg"]},
                {"fields": ["medicine_name", "dosage_form"], "all": ["XR"]},
            ],
            "not_terms": ["insulin", "glimepiride", "amoxicilin", "atorvastatin"],
        },
    ),
    _case(
        "medicine_mixed_english_permit",
        "medicines",
        "Amoxicillin 500mg viên nang cứng, uống; GĐKLH 893110140124; CÔNG TY TNHH ABC Pharma",
        {
            "required": [
                {"fields": ["medicine_name", "active_ingredient_or_herbal_component"], "all": ["Amoxicillin"]},
                {"field": "strength", "any": ["500mg", "500 mg"]},
                {"field": "dosage_form", "all": ["viên nang cứng"]},
                {"field": "route_of_administration", "all": ["uống"]},
                {"field": "manufacturer", "all": ["ABC Pharma"]},
            ],
            "exact_identifiers": [{"field": "marketing_authorization_or_import_permit", "value": "893110140124"}],
        },
    ),
    _case(
        "medicine_packaging_shelf_life_group",
        "medicines",
        "Thuốc Generic nhóm N2; đơn vị viên; hộp 3 vỉ x 10 viên; hạn dùng 36 tháng",
        {
            "required": [
                {"field": "medicine_group", "all": ["N2"]},
                {"field": "unit", "all": ["viên"]},
                {"field": "packaging", "all": ["3 vỉ", "10 viên"]},
                {"field": "shelf_life", "all": ["36 tháng"]},
            ]
        },
    ),
    _case(
        "medicine_country_manufacturer",
        "medicines",
        "Dược liệu cao khô gừng; sản xuất tại India; nhà sản xuất Himalaya",
        {
            "required": [
                {"fields": ["medicine_name", "active_ingredient_or_herbal_component"], "all": ["gừng"]},
                {"field": "production_country", "all": ["India"]},
                {"field": "manufacturer", "all": ["Himalaya"]},
            ]
        },
    ),
    _case(
        "medicine_hospital_location",
        "medicines",
        "Bệnh viện Chợ Rẫy cần thuốc Vancomycin; thành phố Hồ Chí Minh",
        {
            "required": [
                {"field": "medicine_name", "all": ["Vancomycin"]},
                {"field": "procuring_entity_name", "all": ["Chợ Rẫy"]},
                {"field": "location", "all": ["Hồ Chí Minh"]},
            ]
        },
    ),
    _case(
        "medicine_salt_alternative",
        "medicines",
        "Ceftriaxone (dưới dạng ceftriaxone sodium) 1 g",
        {
            "required": [
                {"field": "active_ingredient_or_herbal_component", "all": ["Ceftriaxone"]},
                {"field": "strength", "any": ["1 g", "1g"]},
            ],
            "not_terms": ["amoxicilin", "metformin"],
        },
    ),
    _case(
        "medicine_explicit_result_date",
        "medicines",
        "Insulin glargine; đăng tải KQLCNT 30 ngày gần đây",
        {
            "required": [{"fields": ["medicine_name", "active_ingredient_or_herbal_component"], "all": ["Insulin glargine"]}],
            "dates": [{"field": "result_posted_at", "amount": 30, "unit": "days", "direction": "previous"}],
            "forbidden_date_fields": ["decision_issued_at"],
        },
    ),
    _case(
        "medicine_exact_registration",
        "medicines",
        "Thuốc Apitim 5; số đăng ký 893110140124",
        {
            "required": [{"field": "medicine_name", "all": ["Apitim 5"]}],
            "exact_identifiers": [{"field": "marketing_authorization_or_import_permit", "value": "893110140124"}],
        },
    ),
    _case(
        "traditional_common_scientific_parts_processing",
        "traditional",
        "Đan sâm; Salvia miltiorrhiza; rễ; sao vàng",
        {
            "required": [
                {"field": "item_name", "all": ["Đan sâm"]},
                {"field": "scientific_name", "all": ["Salvia miltiorrhiza"]},
                {"field": "used_part", "all": ["rễ"]},
                {"field": "processing_method", "all": ["sao vàng"]},
            ]
        },
    ),
    _case(
        "traditional_material_processing_origin",
        "traditional",
        "Bạch linh (Poria); thân nấm; chế biến thái phiến, phơi khô; Việt Nam; gói 500g; Đông Dược Văn Hương",
        {
            "required": [
                {"fields": ["item_name"], "all": ["Bạch linh"]},
                {"field": "scientific_name", "all": ["Poria"]},
                {"field": "used_part", "all": ["thân nấm"]},
                {"field": "processing_method", "all": ["thái phiến", "phơi khô"]},
                {"fields": ["production_country", "origin"], "all": ["Việt Nam"]},
                {"field": "packaging", "all": ["500g"]},
                {"field": "manufacturer", "all": ["Đông Dược Văn Hương"]},
            ]
        },
    ),
    _case(
        "traditional_manufacturer_hospital_location",
        "traditional",
        "Dược liệu đan sâm; Công ty cổ phần Dược Traphaco; Bệnh viện Y học cổ truyền Trung ương; Hà Nội",
        {
            "required": [
                {"field": "item_name", "all": ["đan sâm"]},
                {"field": "manufacturer", "all": ["Traphaco"]},
                {"field": "procuring_entity_name", "all": ["Y học cổ truyền Trung ương"]},
                {"field": "location", "all": ["Hà Nội"]},
            ]
        },
    ),
    _case(
        "traditional_origin_processing",
        "traditional",
        "Nghệ vàng, Curcuma longa; nguồn gốc Lào Cai; sơ chế rửa, thái, sấy khô",
        {
            "required": [
                {"field": "item_name", "all": ["Nghệ vàng"]},
                {"field": "scientific_name", "all": ["Curcuma longa"]},
                {"field": "origin", "all": ["Lào Cai"]},
                {"field": "processing_method", "all": ["rửa", "thái", "sấy khô"]},
            ]
        },
    ),
    _case(
        "traditional_permit_group_unit",
        "traditional",
        "Dược liệu ba kích; số đăng ký 4979/BYT-YDCT; nhóm kỹ thuật N3; đơn vị kg",
        {
            "required": [
                {"field": "item_name", "all": ["ba kích"]},
                {"field": "technical_group", "all": ["N3"]},
                {"field": "unit", "all": ["kg"]},
            ],
            "exact_identifiers": [{"field": "registration_or_import_permit_number", "value": "4979/BYT-YDCT"}],
        },
    ),
    _case(
        "traditional_noisy_company_country",
        "traditional",
        "CÔNG TY TNHH Đông Dược Văn Hương cung cấp hoàng kỳ (Astragalus membranaceus), bộ phận rễ, nước sản xuất Việt Nam",
        {
            "required": [
                {"field": "item_name", "all": ["hoàng kỳ"]},
                {"field": "scientific_name", "all": ["Astragalus membranaceus"]},
                {"field": "used_part", "all": ["rễ"]},
                {"field": "manufacturer", "all": ["Đông Dược Văn Hương"]},
                {"field": "production_country", "all": ["Việt Nam"]},
            ]
        },
    ),
    _case(
        "traditional_location_numeric_noise",
        "traditional",
        "Dược liệu tại Quảng Trị; số lượng 20 kg; đơn giá 197.400",
        {
            "required": [{"field": "location", "all": ["Quảng Trị"]}],
            "forbidden_fields": ["quantity", "winning_unit_price"],
            "not_terms": ["197.400"],
        },
    ),
    _case(
        "traditional_explicit_result_date_location",
        "traditional",
        "Các vị thuốc cổ truyền đăng kết quả trong 30 ngày gần đây; tại Hà Nội",
        {
            "required": [{"field": "location", "all": ["Hà Nội"]}],
            "dates": [{"field": "result_posted_at", "amount": 30, "unit": "days", "direction": "previous"}],
            "forbidden_date_fields": ["decision_issued_at"],
        },
    ),
)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value)).casefold()
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = "".join(char if char.isalnum() else " " for char in text)
    return " ".join(text.split())


def _contains(actual: Any, expected: Any) -> bool:
    return _fold(expected) in _fold(actual)


def _plan_payload(plan: AISearchPlan | Mapping[str, Any]) -> Mapping[str, Any]:
    return serialize_plan(plan) if isinstance(plan, AISearchPlan) else plan


def _clauses_by_field(plan: AISearchPlan | Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {}
    for clause in _plan_payload(plan).get("clauses", []):
        if isinstance(clause, Mapping):
            result.setdefault(str(clause.get("field")), []).append(clause)
    return result


def _all_alternatives(plan: AISearchPlan | Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for clauses in _clauses_by_field(plan).values():
        for clause in clauses:
            for concept in clause.get("concepts", []):
                if isinstance(concept, Mapping):
                    terms.extend(str(term) for term in concept.get("alternatives", []))
    return terms


def _field_concepts(plan: AISearchPlan | Mapping[str, Any], fields: Sequence[str]) -> list[Mapping[str, Any]]:
    concepts: list[Mapping[str, Any]] = []
    for field in fields:
        for clause in _clauses_by_field(plan).get(field, []):
            concepts.extend(concept for concept in clause.get("concepts", []) if isinstance(concept, Mapping))
    return concepts


def evaluate_semantics(plan: AISearchPlan | Mapping[str, Any], expectations: Mapping[str, Any]) -> list[str]:
    """Return semantic failures without comparing complete planner JSON."""

    failures: list[str] = []
    payload = _plan_payload(plan)
    if payload.get("group") != expectations.get("group", payload.get("group")):
        failures.append(f"group={payload.get('group')!r}")

    by_field = _clauses_by_field(plan)
    for requirement in expectations.get("required", []):
        fields = tuple(requirement.get("fields", (requirement.get("field"),)))
        concepts = _field_concepts(plan, fields)
        terms = [term for concept in concepts for term in concept.get("alternatives", [])]
        for expected in requirement.get("all", []):
            if not any(_contains(term, expected) for term in terms):
                failures.append(f"missing {expected!r} in {','.join(fields)}")
        any_expected = requirement.get("any", [])
        if any_expected and not any(_contains(term, expected) for term in terms for expected in any_expected):
            failures.append(f"missing one of {any_expected!r} in {','.join(fields)}")

    for requirement in expectations.get("concept_groups", []):
        fields = tuple(requirement.get("fields", (requirement.get("field"),)))
        concepts = _field_concepts(plan, fields)
        used: set[int] = set()
        for group in requirement.get("groups", []):
            match_index = None
            for index, concept in enumerate(concepts):
                if index in used:
                    continue
                alternatives = concept.get("alternatives", [])
                if all(any(_contains(actual, expected) for actual in alternatives) for expected in group.get("alternatives_all", [])) and all(
                    any(_contains(actual, expected) for actual in alternatives) for expected in group.get("all", [])
                ):
                    match_index = index
                    break
            if match_index is None:
                failures.append(f"missing independent concept {group} in {','.join(fields)}")
            else:
                used.add(match_index)

    exact_identifiers = expectations.get("exact_identifiers", [])
    for requirement in exact_identifiers:
        found = False
        for clause in by_field.get(requirement["field"], []):
            for concept in clause.get("concepts", []):
                if concept.get("match") == "exact" and requirement["value"] in concept.get("alternatives", []):
                    found = True
        if not found:
            failures.append(f"identifier {requirement['field']} did not preserve exact value")

    clause_fields = set(by_field)
    for field in expectations.get("forbidden_fields", []):
        if field in clause_fields:
            failures.append(f"forbidden field {field}")

    dates = payload.get("date_constraints", [])
    for expected in expectations.get("dates", []):
        if not any(
            constraint.get("field") == expected["field"]
            and constraint.get("period", {}).get("amount") == expected["amount"]
            and constraint.get("period", {}).get("unit") == expected["unit"]
            and constraint.get("period", {}).get("direction") == expected["direction"]
            for constraint in dates
            if isinstance(constraint, Mapping)
        ):
            failures.append(f"missing date {expected}")

    for field in expectations.get("forbidden_date_fields", []):
        if any(constraint.get("field") == field for constraint in dates if isinstance(constraint, Mapping)):
            failures.append(f"wrong date field {field}")

    terms = _all_alternatives(plan)
    for expected in expectations.get("not_terms", []):
        if any(_contains(term, expected) for term in terms):
            failures.append(f"irrelevant term present {expected!r}")
    for phrase in expectations.get("not_phrases", []):
        if any(_contains(term, phrase) for term in terms):
            failures.append(f"verbose phrase present {phrase!r}")
    return failures


def live_eval_preflight(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if environ is None else environ
    enabled = values.get("BIDFINDER_AI_LIVE_EVAL", "").strip().lower() in {"1", "true", "yes", "on"}
    model = values.get("BIDFINDER_AI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
    if not enabled:
        return {"status": "SKIP", "reason": "live_eval_disabled", "model": model}
    if not values.get("OPENAI_API_KEY", "").strip():
        return {"status": "SKIP", "reason": "missing_api_key", "model": model}
    return {"status": "READY", "model": model}


async def run_cases(
    cases: Sequence[Mapping[str, Any]],
    provider_factory: Callable[[], Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    case_reports: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        case_started = time.perf_counter()
        returned_plan: Mapping[str, Any] | None = None
        failure_reasons: list[str] = []
        try:
            plan = await create_search_plan(case["group"], case["message"], provider=provider_factory())
            returned_plan = serialize_plan(plan)
            expectations = dict(case["expectations"])
            expectations.setdefault("group", case["group"])
            failure_reasons = evaluate_semantics(plan, expectations)
        except AIPlannerError as exc:
            failure_reasons = [f"{exc.category}: {exc}"]
        except Exception as exc:  # Keep report useful without dumping response bodies.
            failure_reasons = [f"unexpected_{type(exc).__name__}"]
        elapsed_ms = round((time.perf_counter() - case_started) * 1000, 2)
        result: dict[str, Any] = {
            "id": case["id"],
            "group": case["group"],
            "passed": not failure_reasons,
            "latency_ms": elapsed_ms,
        }
        if failure_reasons:
            result["failure_reason"] = failure_reasons
            if returned_plan is not None:
                result["returned_plan"] = returned_plan
        else:
            passed += 1
        case_reports.append(result)

    total = len(cases)
    return {
        "status": "PASS" if passed == total else "FAIL",
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "aggregate_latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "cases": case_reports,
    }


async def run_live_evaluation(
    *,
    cases: Sequence[Mapping[str, Any]] = CASES,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    preflight = live_eval_preflight(environ)
    if preflight["status"] == "SKIP":
        return {
            "status": "SKIP",
            "reason": preflight["reason"],
            "total_cases": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": None,
            "model": preflight["model"],
            "aggregate_latency_ms": 0.0,
            "cases": [],
        }

    settings = get_planner_settings()
    report = await run_cases(cases, lambda: OpenAIResponsesPlanner(settings))
    report["model"] = settings.model
    return report


def _print_report(report: Mapping[str, Any]) -> None:
    if report["status"] == "SKIP":
        print(f"SKIP: reason={report['reason']} model={report['model']}")
    else:
        print(
            f"{report['status']}: total={report['total_cases']} passed={report['passed']} "
            f"failed={report['failed']} pass_rate={report['pass_rate']:.2%} "
            f"model={report['model']} aggregate_latency_ms={report['aggregate_latency_ms']}"
        )
        for case in report["cases"]:
            if not case["passed"]:
                print(f"FAIL {case['id']}: {'; '.join(case['failure_reason'])}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="optional machine-readable JSON report path")
    args = parser.parse_args(argv)
    report = asyncio.run(run_live_evaluation())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_report(report)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
