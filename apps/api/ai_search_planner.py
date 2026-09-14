"""Structured, backend-only natural-language search planning for BIDFinder."""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from typing import Any, Mapping, Protocol, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

try:
    from .typesense_contract import PUBLIC_GROUPS, get_search_contract
except ImportError:  # ``uvicorn`` is documented from ``apps/api``.
    from typesense_contract import PUBLIC_GROUPS, get_search_contract


PLANNER_VERSION = "v0.1.3"
PLAN_SCHEMA_VERSION = "1"
MAX_MESSAGE_LENGTH = 4000
MAX_CLAUSES = 24
MAX_CONCEPTS_PER_CLAUSE = 8
MAX_ALTERNATIVES_PER_CONCEPT = 8
MAX_TERM_LENGTH = 160
MAX_WARNING_LENGTH = 240
MAX_EXPLANATION_LENGTH = 240
MAX_DATE_CONSTRAINTS = 4
MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

try:
    BIDFINDER_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
except ZoneInfoNotFoundError:  # Windows may not ship the IANA database.
    BIDFINDER_TIMEZONE = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")


class _StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class AIPlanRequest(_StrictModel):
    group: Literal["goods", "medicines", "traditional"]
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)


class AISearchPreviewRequest(_StrictModel):
    group: Literal["goods", "medicines", "traditional"]
    message: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    plan: dict[str, Any] | None = None


class AIConcept(_StrictModel):
    alternatives: list[str] = Field(..., min_length=1, max_length=MAX_ALTERNATIVES_PER_CONCEPT)


class AINormalizedConcept(_StrictModel):
    alternatives: list[str] = Field(..., min_length=1, max_length=MAX_ALTERNATIVES_PER_CONCEPT)
    match: Literal["text", "exact"] = "text"


class AIClause(_StrictModel):
    field: str = Field(..., min_length=1, max_length=80)
    concepts: list[AINormalizedConcept] = Field(..., min_length=1, max_length=MAX_CONCEPTS_PER_CLAUSE)
    # Alternatives express OR inside one concept. AND is the only clause join,
    # so the intermediate representation never depends on Boolean precedence.
    join: Literal["AND"]


class AIRelativePeriod(_StrictModel):
    kind: Literal["relative"]
    amount: int = Field(..., ge=1, le=120)
    unit: Literal["days", "months", "years"]
    direction: Literal["previous", "current"]


class AIDateConstraint(_StrictModel):
    field: str = Field(..., min_length=1, max_length=80)
    period: AIRelativePeriod
    inclusive: bool


class AISearchPlan(_StrictModel):
    version: Literal["1"]
    group: Literal["goods", "medicines", "traditional"]
    clauses: list[AIClause] = Field(..., max_length=MAX_CLAUSES)
    date_constraints: list[AIDateConstraint] = Field(..., max_length=MAX_DATE_CONSTRAINTS)
    warnings: list[str] = Field(..., max_length=12)
    explanation: list[str] = Field(..., max_length=24)
    _provider_usage: dict[str, Any] | None = PrivateAttr(default=None)


def _safe_usage_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    return value


def _usage_number(usage: Mapping[str, Any], *names: str) -> int | float | None:
    for name in names:
        value = _safe_usage_number(usage.get(name))
        if value is not None:
            return value
    return None


def extract_provider_usage(response: Mapping[str, Any]) -> dict[str, int | float] | None:
    """Extract trustworthy token metadata without retaining provider response content."""
    usage = response.get("usage") if isinstance(response, Mapping) else None
    if not isinstance(usage, Mapping):
        return None

    input_tokens = _usage_number(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_number(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_number(usage, "total_tokens")
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
    cached_tokens = (
        _usage_number(input_details, "cached_tokens", "cache_read_input_tokens")
        if isinstance(input_details, Mapping)
        else None
    )

    extracted = {
        key: value
        for key, value in {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }.items()
        if value is not None
    }
    if not extracted:
        return None
    if input_tokens is not None and output_tokens is not None:
        return extracted
    if total_tokens is not None:
        return {"total_tokens": total_tokens}
    return None


def normalize_usage_units(
    usage: Mapping[str, Any] | None,
    *,
    input_weight: float = 1.0,
    cached_input_weight: float = 0.25,
    output_weight: float = 2.0,
) -> float | None:
    """Convert provider token metadata to model-independent weighted usage units."""
    if not isinstance(usage, Mapping):
        return None
    input_tokens = _safe_usage_number(usage.get("input_tokens"))
    cached_tokens = _safe_usage_number(usage.get("cached_input_tokens")) or 0
    output_tokens = _safe_usage_number(usage.get("output_tokens"))
    if input_tokens is not None and output_tokens is not None:
        cached = min(cached_tokens, input_tokens)
        non_cached_input = max(0, input_tokens - cached)
        return (
            float(non_cached_input) * float(input_weight)
            + float(cached) * float(cached_input_weight)
            + float(output_tokens) * float(output_weight)
        )
    total_tokens = _safe_usage_number(usage.get("total_tokens"))
    return float(total_tokens) if total_tokens is not None else None


class PlannerProvider(Protocol):
    async def create_plan(self, *, group: str, message: str) -> Mapping[str, Any]:
        ...


class AIPlannerError(Exception):
    def __init__(self, message: str, *, category: str):
        super().__init__(message)
        self.category = category


class AIPlannerInputError(AIPlannerError):
    pass


class AIPlannerConfigurationError(AIPlannerError):
    pass


class AIPlannerProviderError(AIPlannerError):
    pass


class AIPlannerValidationError(AIPlannerError):
    pass


@dataclass(frozen=True)
class PlannerSettings:
    enabled: bool
    api_key: str | None
    model: str
    timeout_seconds: float


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_planner_settings() -> PlannerSettings:
    raw_timeout = os.getenv("BIDFINDER_AI_TIMEOUT_SECONDS", "20").strip()
    try:
        timeout_seconds = min(120.0, max(1.0, float(raw_timeout)))
    except (TypeError, ValueError):
        timeout_seconds = 20.0
    return PlannerSettings(
        enabled=_env_flag("BIDFINDER_AI_ENABLED", True),
        api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        model=os.getenv("BIDFINDER_AI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna",
        timeout_seconds=timeout_seconds,
    )


def _model_validate(model_type, payload: Any):
    method = getattr(model_type, "model_validate", None)
    return method(payload) if method else model_type.parse_obj(payload)


def _model_dump(model: BaseModel) -> dict[str, Any]:
    method = getattr(model, "model_dump", None)
    return method() if method else model.dict()


def _contract_fields(group: str) -> list[dict[str, Any]]:
    if group not in PUBLIC_GROUPS:
        raise AIPlannerInputError("unknown planner group", category="invalid_group")
    try:
        fields = get_search_contract()["groups"][group]["fields"]
    except (KeyError, TypeError) as exc:
        raise AIPlannerValidationError("canonical field contract unavailable", category="canonical_contract") from exc
    if not isinstance(fields, list):
        raise AIPlannerValidationError("canonical field contract is malformed", category="canonical_contract")
    return [
        field
        for field in fields
        if isinstance(field, Mapping)
        and isinstance(field.get("name"), str)
        and field.get("ai_planning") is True
    ]


def allowed_fields_for_group(group: str) -> frozenset[str]:
    """Return canonical fields directly from the existing BIDFinder contract."""

    return frozenset(field["name"] for field in _contract_fields(group))


def _field_metadata(group: str) -> dict[str, dict[str, Any]]:
    return {field["name"]: field for field in _contract_fields(group)}


def _date_fields(group: str) -> frozenset[str]:
    return frozenset(
        field["name"]
        for field in _contract_fields(group)
        if field.get("ai_planner_role") == "date"
    )


def build_planner_system_prompt(group: str) -> str:
    fields = _contract_fields(group)
    field_lines = []
    for field in fields:
        flags = []
        role = field.get("ai_planner_role")
        if role:
            flags.append(role)
        if field.get("identifier") and role != "identifier":
            flags.append("identifier")
        if field.get("searchable"):
            flags.append("searchable")
        if field.get("filterable"):
            flags.append("filterable")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        field_lines.append(f'- {field["name"]}: {field.get("label", field["name"])}{suffix}')

    return f"""You are BIDFinder AI Search Planner {PLANNER_VERSION}.
The application selected dataset group is {group}. Treat that group as fixed. Never change, infer, or broaden it.
Return only one JSON object matching the supplied schema. Do not return Markdown, Typesense syntax, SQL, or reasoning.

Allowed canonical fields for this group come from the existing BIDFinder search contract:
{chr(10).join(field_lines)}

Planning policy:
1. Map each user fact to the correct canonical field.
2. Extract discriminative search terms. Do not copy verbose source descriptions as one phrase.
3. Use separate concepts with join AND when both concepts are independently required.
4. Put spelling, form, or synonym alternatives for the same concept in one alternatives array. Never use Boolean syntax inside a term.
5. Prefer recall when procurement wording varies, but do not invent unsupported facts or synonyms.
6. Preserve identifiers exactly, including Mã TBMT, registration numbers, model numbers, decision numbers, and HS codes. The backend derives exact identifier matching from the canonical field role.
7. Reduce low-value legal or company prefixes when searching company names. Keep the discriminative company name, such as Hậu Giang.
8. A semicolon is only a boundary hint. It is not a field separator.
9. For an organization or company without an explicit role, apply this entity-role hierarchy before any generic default.
9a. Healthcare or public institutions such as Bệnh viện, Trung tâm y tế, Trạm y tế, Phòng khám, Viện, Trường, Đại học, Sở, Ban quản lý, cơ quan, or đơn vị công default to procuring_entity_name.
9b. Commercial companies or businesses such as Công ty without an explicit manufacturing, bidder, supplier, buyer, or procuring cue default to winning_bidder_name.
10. Use manufacturer only for explicit cues such as hãng, hãng sản xuất, nhà sản xuất, cơ sở sản xuất, sản xuất bởi, manufacturer, or manufactured by.
10a. Explicit bidder or supplier cues such as nhà thầu, nhà thầu trúng thầu, đơn vị trúng thầu, cung cấp bởi, or nhà cung cấp in procurement context use winning_bidder_name.
10b. Explicit procuring or buyer cues such as chủ đầu tư, bên mời thầu, đơn vị mua, or đơn vị sử dụng use procuring_entity_name.
11. For medicine requests, distinguish active ingredient or salt/form, strength, dosage form, route, packaging, permit number, manufacturer, and location. Ignore irrelevant excipients unless user makes them a search requirement.
11a. When the user explicitly writes X (dưới dạng Y), keep supplied X and its salt or form Y as alternatives in the same active-ingredient concept. Do not discard Y or turn a representation of the same ingredient into an independent AND concept.
11b. For medicines, distinguish medicine_name (Tên thuốc or product name) from active_ingredient_or_herbal_component (Hoạt chất or thành phần dược liệu). Use the active-ingredient field only when the user explicitly identifies the value as an active ingredient, hoạt chất, thành phần, or salt/form. A standalone medicine-like name without that cue belongs to medicine_name; do not infer its chemical role from outside knowledge. For example, "paracetamol 150mg thuốc đặt" maps paracetamol to medicine_name, while "hoạt chất paracetamol" maps paracetamol to active_ingredient_or_herbal_component. Never put the same standalone value in both fields.
12. For combination-product strengths joined by +, /, or clearly separate dose components, put independently required strengths in separate concepts with AND. Do not make one complete strength string an alternative.
13. Treat contextual container wording such as Gói 2g thuốc chứa as narrative unless the user clearly requests packaging. Use packaging for explicit quy cách đóng gói, đóng gói, hộp 10 vỉ, chai 100ml, or clearly requested gói 2g.
14. For traditional medicine, distinguish common or herbal name, scientific name, used part, processing method, origin, packaging, manufacturer, and location.
15. Date-only fields may appear only in date_constraints, never as text clauses.
16. Generic recent-period language without an explicit date-field phrase defaults to decision_issued_at. This includes 6 tháng gần nhất, 30 ngày gần đây, and trong năm nay.
17. Explicit ngày đăng kết quả, ngày đăng tải KQLCNT, or đăng kết quả overrides the default and uses result_posted_at.
18. Explicit ngày quyết định or ngày ban hành quyết định uses decision_issued_at.
19. Represent periods structurally: previous 6 months means amount 6, unit months, direction previous; current year means amount 1, unit years, direction current. Never calculate calendar dates.
20. Keep explanation entries short field mappings only. Do not include chain-of-thought.
20a. Write warnings and explanation entries in Vietnamese.

The output must preserve this group and use only allowed fields. Empty terms are not useful. Add a warning when wording is ambiguous or unsupported.
"""


AI_SEARCH_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "enum": [PLAN_SCHEMA_VERSION]},
        "group": {"type": "string", "enum": list(PUBLIC_GROUPS)},
        "clauses": {
            "type": "array",
            "maxItems": MAX_CLAUSES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string", "maxLength": 80},
                    "concepts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_CONCEPTS_PER_CLAUSE,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "alternatives": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": MAX_ALTERNATIVES_PER_CONCEPT,
                                    "items": {"type": "string", "maxLength": MAX_TERM_LENGTH},
                                },
                            },
                            "required": ["alternatives"],
                        },
                    },
                    "join": {"type": "string", "enum": ["AND"]},
                },
                "required": ["field", "concepts", "join"],
            },
        },
        "date_constraints": {
            "type": "array",
            "maxItems": MAX_DATE_CONSTRAINTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string", "maxLength": 80},
                    "period": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kind": {"type": "string", "enum": ["relative"]},
                            "amount": {"type": "integer", "minimum": 1, "maximum": 120},
                            "unit": {"type": "string", "enum": ["days", "months", "years"]},
                            "direction": {"type": "string", "enum": ["previous", "current"]},
                        },
                        "required": ["kind", "amount", "unit", "direction"],
                    },
                    "inclusive": {"type": "boolean"},
                },
                "required": ["field", "period", "inclusive"],
            },
        },
        "warnings": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": MAX_WARNING_LENGTH},
        },
        "explanation": {
            "type": "array",
            "maxItems": 24,
            "items": {"type": "string", "maxLength": MAX_EXPLANATION_LENGTH},
        },
    },
    "required": ["version", "group", "clauses", "date_constraints", "warnings", "explanation"],
}


def _raise_plan_error(category: str, message: str = "invalid AI search plan") -> None:
    raise AIPlannerValidationError(message, category=category)


def _clean_text_list(value: Any, *, max_length: int, category: str) -> list[str]:
    if not isinstance(value, list):
        _raise_plan_error(category)
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            _raise_plan_error(category)
        item = item.strip()
        if not item:
            continue
        if len(item) > max_length or any(ord(char) < 32 and char not in "\t\n\r" for char in item):
            _raise_plan_error(category)
        cleaned.append(item)
    return cleaned


def validate_ai_search_plan(payload: Mapping[str, Any] | AISearchPlan, *, requested_group: str | None = None) -> AISearchPlan:
    """Validate provider output and derive canonical match semantics."""

    normalized_input = isinstance(payload, AISearchPlan)
    raw = _model_dump(payload) if normalized_input else payload
    if not isinstance(raw, Mapping):
        _raise_plan_error("top_level_shape")

    required_keys = {"version", "group", "clauses", "date_constraints", "warnings", "explanation"}
    if set(raw) != required_keys:
        _raise_plan_error("top_level_keys")
    if requested_group is not None and requested_group not in PUBLIC_GROUPS:
        raise AIPlannerInputError("unknown planner group", category="invalid_group")
    if raw.get("group") != (requested_group or raw.get("group")):
        _raise_plan_error("group_mismatch")

    group = raw.get("group")
    if group not in PUBLIC_GROUPS:
        _raise_plan_error("invalid_group")
    allowed_fields = allowed_fields_for_group(group)
    metadata = _field_metadata(group)

    clauses = raw.get("clauses")
    if not isinstance(clauses, list) or len(clauses) > MAX_CLAUSES:
        _raise_plan_error("clause_bounds")
    cleaned_clauses = []
    for clause in clauses:
        if not isinstance(clause, Mapping):
            _raise_plan_error("clause_shape")
        if set(clause) != {"field", "concepts", "join"}:
            _raise_plan_error("clause_keys")
        field = clause.get("field")
        if not isinstance(field, str):
            _raise_plan_error("field_shape")
        field = field.strip()
        if field not in allowed_fields:
            _raise_plan_error("unknown_field")
        if metadata.get(field, {}).get("ai_planner_role") == "date":
            _raise_plan_error("date_field_as_text")
        if clause.get("join") != "AND":
            _raise_plan_error("boolean_structure")
        concepts = clause.get("concepts")
        if not isinstance(concepts, list) or not 1 <= len(concepts) <= MAX_CONCEPTS_PER_CLAUSE:
            _raise_plan_error("concept_bounds")

        cleaned_concepts = []
        for concept in concepts:
            expected_concept_keys = {"alternatives", "match"} if normalized_input else {"alternatives"}
            if not isinstance(concept, Mapping) or set(concept) != expected_concept_keys:
                _raise_plan_error("concept_shape")
            alternatives = _clean_text_list(
                concept.get("alternatives"),
                max_length=MAX_TERM_LENGTH,
                category="term_shape",
            )
            if not alternatives:
                continue
            if len(alternatives) > MAX_ALTERNATIVES_PER_CONCEPT:
                _raise_plan_error("alternative_bounds")
            field_metadata = metadata.get(field, {})
            match = "exact" if field_metadata.get("ai_planner_role") == "identifier" else "text"
            cleaned_concepts.append({"alternatives": alternatives, "match": match})
        if not cleaned_concepts:
            _raise_plan_error("empty_concepts")
        cleaned_clauses.append({"field": field, "concepts": cleaned_concepts, "join": "AND"})

    date_constraints = raw.get("date_constraints")
    if not isinstance(date_constraints, list) or len(date_constraints) > MAX_DATE_CONSTRAINTS:
        _raise_plan_error("date_bounds")
    cleaned_dates = []
    date_field_names = _date_fields(group)
    for constraint in date_constraints:
        if not isinstance(constraint, Mapping) or set(constraint) != {"field", "period", "inclusive"}:
            _raise_plan_error("date_shape")
        field = constraint.get("field")
        if not isinstance(field, str) or field.strip() not in date_field_names:
            _raise_plan_error("invalid_date_field")
        period = constraint.get("period")
        if not isinstance(period, Mapping) or set(period) != {"kind", "amount", "unit", "direction"}:
            _raise_plan_error("period_shape")
        if type(period.get("amount")) is not int or not 1 <= period["amount"] <= 120:
            _raise_plan_error("period_bounds")
        if period.get("kind") != "relative" or period.get("unit") not in {"days", "months", "years"} or period.get("direction") not in {"previous", "current"}:
            _raise_plan_error("period_value")
        if type(constraint.get("inclusive")) is not bool:
            _raise_plan_error("date_shape")
        cleaned_dates.append({
            "field": field.strip(),
            "period": {
                "kind": "relative",
                "amount": period["amount"],
                "unit": period["unit"],
                "direction": period["direction"],
            },
            "inclusive": constraint["inclusive"],
        })

    cleaned = {
        "version": raw.get("version"),
        "group": group,
        "clauses": cleaned_clauses,
        "date_constraints": cleaned_dates,
        "warnings": _clean_text_list(raw.get("warnings"), max_length=MAX_WARNING_LENGTH, category="warning_shape"),
        "explanation": _clean_text_list(raw.get("explanation"), max_length=MAX_EXPLANATION_LENGTH, category="explanation_shape"),
    }
    try:
        plan = _model_validate(AISearchPlan, cleaned)
    except ValidationError as exc:
        raise AIPlannerValidationError("invalid AI search plan schema", category="schema") from exc
    if plan.group != (requested_group or group):
        _raise_plan_error("group_mismatch")
    return plan


def validate_serialized_ai_search_plan(
    payload: Mapping[str, Any],
    *,
    requested_group: str | None = None,
) -> AISearchPlan:
    """Validate a serialized normalized plan supplied by the browser."""

    try:
        normalized = _model_validate(AISearchPlan, payload)
    except (TypeError, ValidationError) as exc:
        raise AIPlannerValidationError("invalid serialized AI search plan", category="schema") from exc
    return validate_ai_search_plan(normalized, requested_group=requested_group)


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def _today_in_bidfinder_timezone(now: date | datetime | None) -> date:
    if now is None:
        return datetime.now(BIDFINDER_TIMEZONE).date()
    if isinstance(now, datetime):
        if now.tzinfo is not None:
            return now.astimezone(BIDFINDER_TIMEZONE).date()
        return now.date()
    return now


def resolve_relative_period(period: AIRelativePeriod | Mapping[str, Any], *, now: date | datetime | None = None) -> tuple[date, date]:
    """Resolve structural periods in Python; planner output stays date-arithmetic free."""

    relative = period if isinstance(period, AIRelativePeriod) else _model_validate(AIRelativePeriod, period)
    today = _today_in_bidfinder_timezone(now)
    if relative.direction == "previous":
        if relative.unit == "days":
            start = today - timedelta(days=relative.amount)
        elif relative.unit == "months":
            start = _subtract_months(today, relative.amount)
        else:
            start = _subtract_months(today, relative.amount * 12)
        return start, today

    if relative.unit == "days":
        return today - timedelta(days=relative.amount - 1), today
    if relative.unit == "months":
        start = _subtract_months(today.replace(day=1), relative.amount - 1)
        return start, today
    return today.replace(year=today.year - relative.amount + 1, month=1, day=1), today.replace(month=12, day=31)


def _structured_output_text(response: Mapping[str, Any]) -> str:
    top_level_text = response.get("output_text")
    if isinstance(top_level_text, str) and top_level_text.strip():
        return top_level_text
    for item in response.get("output", []):
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []):
            if not isinstance(content, Mapping):
                continue
            if content.get("type") == "refusal":
                raise AIPlannerProviderError("model refused planner request", category="provider_refusal")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise AIPlannerProviderError("structured output missing", category="provider_output")


class OpenAIResponsesPlanner:
    """Small stdlib adapter. Tests can replace this provider without API access."""

    def __init__(self, settings: PlannerSettings):
        self.settings = settings
        self.last_usage: dict[str, int | float] | None = None

    async def create_plan(self, *, group: str, message: str) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._create_plan_sync, group=group, message=message)

    def _create_plan_sync(self, *, group: str, message: str) -> Mapping[str, Any]:
        payload = {
            "model": self.settings.model,
            "store": False,
            "max_output_tokens": 2000,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": build_planner_system_prompt(group)}]},
                {"role": "user", "content": [{"type": "input_text", "text": message}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "bidfinder_ai_search_plan",
                    "strict": True,
                    "schema": AI_SEARCH_PLAN_JSON_SCHEMA,
                }
            },
        }
        request = URLRequest(
            OPENAI_RESPONSES_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                response_body = response.read(MAX_PROVIDER_RESPONSE_BYTES)
        except HTTPError as exc:
            raise AIPlannerProviderError("OpenAI provider returned an HTTP error", category="provider_http") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise AIPlannerProviderError("OpenAI provider request failed", category="provider_transport") from exc

        try:
            response_payload = json.loads(response_body.decode("utf-8"))
            self.last_usage = extract_provider_usage(response_payload)
            structured_text = _structured_output_text(response_payload)
            parsed = json.loads(structured_text)
        except AIPlannerProviderError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise AIPlannerProviderError("OpenAI provider returned malformed JSON", category="provider_output") from exc
        if not isinstance(parsed, Mapping):
            raise AIPlannerProviderError("OpenAI provider returned a non-object plan", category="provider_output")
        return parsed


def _validate_request(group: str, message: str) -> str:
    if group not in PUBLIC_GROUPS:
        raise AIPlannerInputError("unknown planner group", category="invalid_group")
    if not isinstance(message, str):
        raise AIPlannerInputError("planner message must be text", category="invalid_message")
    cleaned = message.strip()
    if not cleaned:
        raise AIPlannerInputError("planner message is empty", category="empty_message")
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise AIPlannerInputError("planner message is too long", category="message_too_long")
    return cleaned


async def create_search_plan(group: str, message: str, *, provider: PlannerProvider | None = None) -> AISearchPlan:
    cleaned_message = _validate_request(group, message)
    settings = get_planner_settings()
    if provider is None:
        if not settings.enabled:
            raise AIPlannerConfigurationError("AI planner is disabled", category="disabled")
        if not settings.api_key:
            raise AIPlannerConfigurationError("OpenAI API key is not configured", category="missing_api_key")
        provider = OpenAIResponsesPlanner(settings)
    try:
        raw_plan = await provider.create_plan(group=group, message=cleaned_message)
    except AIPlannerProviderError as exc:
        exc.provider_usage = getattr(provider, "last_usage", None)
        raise
    try:
        plan = validate_ai_search_plan(raw_plan, requested_group=group)
    except AIPlannerValidationError as exc:
        exc.provider_usage = getattr(provider, "last_usage", None)
        raise
    plan._provider_usage = getattr(provider, "last_usage", None)
    return plan


def serialize_plan(plan: AISearchPlan) -> dict[str, Any]:
    return _model_dump(plan)
