"""Deterministic compilation of an AI search plan into BIDFinder's query contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import re
from typing import Any, Mapping

try:
    from .ai_search_planner import AISearchPlan, resolve_relative_period
    from .typesense_contract import get_search_contract, normalize_group
    from .typesense_shadow import (
        CROSS_GROUP_GOODS_PRODUCT_FIELDS,
        FILTER_FIELD_MAP,
    )
except ImportError:  # ``uvicorn`` is documented from ``apps/api``.
    from ai_search_planner import AISearchPlan, resolve_relative_period
    from typesense_contract import get_search_contract, normalize_group
    from typesense_shadow import CROSS_GROUP_GOODS_PRODUCT_FIELDS, FILTER_FIELD_MAP


class AIQueryCompilationError(ValueError):
    """A validated plan cannot be represented by the existing query contract."""

    def __init__(self, message: str, *, category: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class AICompiledQuery:
    """QueryPreviewRequest-compatible, backend-neutral request data."""

    group: str
    scope: str
    filters: Mapping[str, Any]
    text: str
    search_fields: tuple[str, ...]
    structured_filters: Mapping[str, Any]
    ranges: Mapping[str, Any]
    date_ranges: Mapping[str, Any]
    exact_identifiers: Mapping[str, Any]
    cross_group_search: bool = False
    cross_group_search_fields: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return only fields accepted by the existing preview request model."""

        return {
            "scope": self.scope,
            "group": self.group,
            "sourceTypes": [],
            "filters": copy.deepcopy(dict(self.filters)) or None,
            "text": self.text,
            "searchFields": list(self.search_fields),
            "structuredFilters": copy.deepcopy(dict(self.structured_filters)),
            "ranges": copy.deepcopy(dict(self.ranges)),
            "dateRanges": copy.deepcopy(dict(self.date_ranges)),
            "exactIdentifiers": copy.deepcopy(dict(self.exact_identifiers)),
            "crossGroupSearch": self.cross_group_search,
            "crossGroupSearchFields": list(self.cross_group_search_fields),
        }


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _contract_group(group: str) -> Mapping[str, Any]:
    contract = get_search_contract()["groups"]
    return contract[group]


def _planner_clauses(plan: AISearchPlan | Mapping[str, Any]) -> list[Any]:
    return list(_value(plan, "clauses", []) or [])


def _concepts(clause: Any) -> list[Any]:
    return list(_value(clause, "concepts", []) or [])


def _alternatives(concept: Any) -> list[str]:
    return [
        str(term).strip()
        for term in (_value(concept, "alternatives", []) or [])
        if str(term).strip()
    ]


def _terms(concepts: list[Any]) -> list[str]:
    result: list[str] = []
    for concept in concepts:
        result.extend(_alternatives(concept))
    return result


def _token_filter(concepts: list[Any]) -> dict[str, Any]:
    """Use the existing TokenFilter operators for concept OR and clause AND."""

    tokens: list[dict[str, str]] = []
    for concept in concepts:
        alternatives = _alternatives(concept)
        operation = "OR" if len(alternatives) > 1 else "AND"
        tokens.extend({"value": term, "op": operation} for term in alternatives)
    return {"tokens": tokens}


def _merge_tokens(filters: dict[str, Any], name: str, concepts: list[Any]) -> None:
    incoming = _token_filter(concepts)["tokens"]
    if not incoming:
        return
    existing = filters.get(name)
    if not isinstance(existing, Mapping):
        filters[name] = {"tokens": incoming}
        return
    filters[name] = {
        **dict(existing),
        "tokens": [*(existing.get("tokens") or []), *incoming],
    }


def _merge_values(target: dict[str, Any], name: str, values: list[str]) -> None:
    if not values:
        return
    existing = target.get(name)
    if isinstance(existing, list):
        target[name] = [*existing, *[value for value in values if value not in existing]]
    else:
        target[name] = list(dict.fromkeys(values))


def _merge_structured_values(target: dict[str, Any], name: str, values: list[str]) -> None:
    if not values:
        return
    existing = target.get(name)
    if isinstance(existing, Mapping) and "in" in existing:
        old_values = list(existing.get("in") or [])
        target[name] = {"in": [*old_values, *[value for value in values if value not in old_values]]}
    else:
        target[name] = {"in": list(dict.fromkeys(values))}


def _legacy_alias(schema_group: str, field: str) -> str | None:
    """Find an existing advanced-search alias from FILTER_FIELD_MAP."""

    mapping = FILTER_FIELD_MAP[schema_group]
    exact = next((name for name, fields in mapping.items() if tuple(fields) == (field,)), None)
    if exact:
        return exact
    return next((name for name, fields in mapping.items() if field in fields), None)


def _product_fields(group: str) -> tuple[str, ...]:
    contract = _contract_group(group)
    fields = {
        item["name"]
        for item in contract.get("fields", [])
        if item.get("searchable") and item.get("type") in {"string", "string[]"}
    }
    return tuple(field for field in CROSS_GROUP_GOODS_PRODUCT_FIELDS if field in fields)


def _quote_text_term(term: str) -> str:
    if re.search(r"\s", term):
        return '"' + term.replace('"', '\\"') + '"'
    return term


def _scope_for_group(group: str) -> str:
    return {"goods": "goods", "medicines": "medicine", "traditional": "traditional"}[group]


def compile_ai_search_plan(
    plan: AISearchPlan | Mapping[str, Any],
    *,
    now: Any = None,
) -> AICompiledQuery:
    """Compile a validated plan without inference, provider calls, or backend syntax."""

    group = str(_value(plan, "group", ""))
    if group not in {"goods", "medicines", "traditional"}:
        raise AIQueryCompilationError("unsupported planner group", category="invalid_group")

    schema_group = normalize_group(group)
    contract = _contract_group(group)
    metadata = {item["name"]: item for item in contract.get("fields", [])}
    filters: dict[str, Any] = {}
    structured_filters: dict[str, Any] = {}
    text_terms: list[str] = []
    search_fields: list[str] = []
    date_ranges: dict[str, Any] = {}
    exact_identifiers: dict[str, Any] = {}
    product_fields = _product_fields(group) if group == "goods" else ()

    clauses = _planner_clauses(plan)
    identifier_clauses = [
        clause
        for clause in clauses
        if _value(metadata.get(str(_value(clause, "field", ""))), "ai_planner_role") == "identifier"
    ]
    if len(identifier_clauses) > 1:
        raise AIQueryCompilationError(
            "existing exactIdentifiers mechanism supports one identifier per query",
            category="multiple_exact_identifiers",
        )
    has_identifier = bool(identifier_clauses)

    for clause in clauses:
        field = str(_value(clause, "field", "")).strip()
        info = metadata.get(field)
        if info is None:
            raise AIQueryCompilationError(f"unsupported planner field: {field}", category="unknown_field")
        role = info.get("ai_planner_role")
        concepts = _concepts(clause)
        if not concepts:
            raise AIQueryCompilationError(f"empty concepts for {field}", category="empty_concepts")

        if role == "date":
            raise AIQueryCompilationError(f"date field cannot be a text clause: {field}", category="date_field_as_text")

        if role == "identifier":
            values = _terms(concepts)
            if len(values) != 1:
                raise AIQueryCompilationError(
                    f"exact identifier must have one value: {field}",
                    category="identifier_alternatives",
                )
            exact_identifiers[field] = values[0]
            continue

        if group == "goods" and field in product_fields:
            if has_identifier or any(len(_alternatives(concept)) > 1 for concept in concepts):
                family_alias = next(
                    (
                        name
                        for name, mapped_fields in FILTER_FIELD_MAP[schema_group].items()
                        if tuple(mapped_fields) == product_fields and "goodsKeyword" in name
                    ),
                    None,
                )
                if family_alias is None:
                    raise AIQueryCompilationError("goods product family is unavailable", category="unsupported_product_search")
                _merge_tokens(filters, family_alias, concepts)
            else:
                if not info.get("searchable") or info.get("type") not in {"string", "string[]"}:
                    raise AIQueryCompilationError(f"field is not text searchable: {field}", category="unsupported_text_field")
                if field not in search_fields:
                    search_fields.append(field)
                text_terms.extend(_quote_text_term(term) for term in _terms(concepts))
            continue

        alias = _legacy_alias(schema_group, field)
        if alias == "place":
            _merge_values(filters, alias, _terms(concepts))
            continue
        if role == "categorical":
            if not info.get("filterable"):
                raise AIQueryCompilationError(
                    f"categorical field has no existing filter capability: {field}",
                    category="unsupported_categorical_field",
                )
            values = _terms(concepts)
            if alias == "selectionMethod" or alias == "place" or alias == "drugGroup":
                _merge_values(filters, alias, values)
            elif alias:
                _merge_tokens(filters, alias, concepts)
            else:
                _merge_structured_values(structured_filters, field, values)
            continue

        if alias:
            _merge_tokens(filters, alias, concepts)
            continue

        if has_identifier:
            raise AIQueryCompilationError(
                f"existing exactIdentifiers query cannot retain text field: {field}",
                category="identifier_text_combination_unsupported",
            )
        if not info.get("searchable") or info.get("type") not in {"string", "string[]"}:
            raise AIQueryCompilationError(f"field is not text searchable: {field}", category="unsupported_text_field")
        if field not in search_fields:
            search_fields.append(field)
        text_terms.extend(_quote_text_term(term) for term in _terms(concepts))

    for constraint in list(_value(plan, "date_constraints", []) or []):
        field = str(_value(constraint, "field", "")).strip()
        info = metadata.get(field)
        if info is None or info.get("ai_planner_role") != "date":
            raise AIQueryCompilationError(f"unsupported date field: {field}", category="invalid_date_field")
        if field in date_ranges:
            raise AIQueryCompilationError(f"duplicate date field: {field}", category="duplicate_date_field")
        start, end = resolve_relative_period(_value(constraint, "period"), now=now)
        date_ranges[field] = {"from": start.isoformat(), "to": end.isoformat()}

    return AICompiledQuery(
        group=group,
        scope=_scope_for_group(group),
        filters=filters,
        text=" ".join(text_terms),
        search_fields=tuple(search_fields),
        structured_filters=structured_filters,
        ranges={},
        date_ranges=date_ranges,
        exact_identifiers=exact_identifiers,
    )


def safe_broaden_ai_query(query: AICompiledQuery) -> tuple[AICompiledQuery, dict[str, Any]] | None:
    """Expand only the established goods product field family, retaining every term."""

    if query.group != "goods" or not query.text or not query.search_fields or query.exact_identifiers:
        return None
    family = _product_fields(query.group)
    current = tuple(query.search_fields)
    if not set(current).issubset(set(family)) or set(current) == set(family):
        return None
    broadened = replace(query, search_fields=family)
    return broadened, {
        "kind": "goods_product_field_expansion",
        "from": list(current),
        "to": list(family),
        "preserves_terms": True,
    }


# Short alias for callers that prefer the task wording.
compile_ai_plan = compile_ai_search_plan
