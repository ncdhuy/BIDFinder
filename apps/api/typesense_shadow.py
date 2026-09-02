"""Phase 4A Typesense shadow-read adapter and parity primitives.

This module owns only procurement shadow reads. Postgres remains the response
authority; callers schedule these operations after the primary response has
been assembled.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Awaitable, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from typesense_contract import (
    PUBLIC_GROUPS,
    canonical_field_for,
    get_group_contract,
    normalize_group,
    public_group,
    source_selector,
)


logger = logging.getLogger("bidfinder.typesense_shadow")

SHADOW_INFRA_ERROR = "SHADOW_INFRA_ERROR"
QUERY_CONTRACT_FAILURE = "QUERY_CONTRACT_FAILURE"
LEGACY_POPULATION_DIFFERENCE = "LEGACY_POPULATION_DIFFERENCE"
RANKING_DIFFERENCE = "RANKING_DIFFERENCE"
PERFORMANCE_OUTLIER = "PERFORMANCE_OUTLIER"
SHADOW_PARITY_MISMATCH = "SHADOW_PARITY_MISMATCH"
SHADOW_PARITY_NOT_COMPARABLE = "SHADOW_PARITY_NOT_COMPARABLE"
IDENTITY_NOT_COMPARABLE = "IDENTITY_NOT_COMPARABLE"
SHADOW_OK = "SHADOW_OK"

SEVERITY_P0 = "P0"
SEVERITY_P1 = "P1"
SEVERITY_P2 = "P2"
SEVERITY_P3 = "P3"

LOGICAL_GROUPS = ("goods", "medicines", "traditional_medicine")
LOGICAL_ALIASES = {
    "goods": "bidfinder_goods",
    "medicines": "bidfinder_medicines",
    "traditional_medicine": "bidfinder_traditional",
}
GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

IDENTITY_FIELD_ALIASES = {
    "goods": (
        ("bid_invitation_code", ("bid_invitation_code", "ma tbmt")),
        ("decision_number", ("decision_number", "quyet dinh phe duyet")),
        ("item_name", ("item_name", "danh muc hang hoa", "ten hang hoa")),
        ("model_mark", ("model_mark", "ky ma hieu")),
        ("brand", ("brand", "nhan hieu")),
        ("manufacturer", ("manufacturer", "hang san xuat")),
        ("technical_specification", ("technical_specification", "tinh nang ky thuat")),
        ("unit", ("unit", "don vi tinh")),
        ("quantity", ("quantity", "khoi luong")),
        ("country_of_origin", ("country_of_origin", "xuat xu")),
        ("production_year", ("production_year", "nam san xuat")),
        ("winning_unit_price", ("winning_unit_price", "don gia trung thau (vnd)")),
        ("winning_bidder_name", ("winning_bidder_name", "nha thau trung thau")),
    ),
    "medicines": (
        ("bid_invitation_code", ("bid_invitation_code", "ma tbmt")),
        ("decision_number", ("decision_number", "quyet dinh phe duyet")),
        ("medicine_code", ("medicine_code", "ma thuoc")),
        ("medicine_name", ("medicine_name", "ten thuoc")),
        ("active_ingredient_or_herbal_component", ("active_ingredient_or_herbal_component", "ten hoat chat")),
        ("strength", ("strength", "nong do ham luong")),
        ("manufacturer", ("manufacturer", "co so san xuat", "hang san xuat")),
        ("unit", ("unit", "don vi tinh")),
        ("quantity", ("quantity", "so luong")),
        ("winning_unit_price", ("winning_unit_price", "don gia trung thau (vnd)")),
        ("winning_bidder_name", ("winning_bidder_name", "nha thau trung thau")),
        ("medicine_group", ("medicine_group", "nhom thuoc")),
        ("marketing_authorization_or_import_permit", ("marketing_authorization_or_import_permit", "gdklh hoac gp nk")),
    ),
    "traditional_medicine": (
        ("bid_invitation_code", ("bid_invitation_code", "ma tbmt")),
        ("decision_number", ("decision_number", "quyet dinh phe duyet")),
        ("item_name", ("item_name", "ten duoc lieu", "ten san pham")),
        ("scientific_name", ("scientific_name", "ten khoa hoc")),
        ("used_part", ("used_part", "bo phan dung")),
        ("processing_method", ("processing_method", "phuong phap che bien")),
        ("manufacturer", ("manufacturer", "co so san xuat", "hang san xuat")),
        ("unit", ("unit", "don vi tinh")),
        ("quantity", ("quantity", "so luong")),
        ("winning_unit_price", ("winning_unit_price", "don gia trung thau (vnd)")),
        ("winning_bidder_name", ("winning_bidder_name", "nha thau trung thau")),
        ("technical_group", ("technical_group", "nhom tckt")),
    ),
}

QUERY_BY = {
    group: tuple(get_group_contract(group)["full_text"]["fields"])
    for group in ("goods", "medicines", "traditional_medicine")
}
FILTER_FIELDS = {
    group: frozenset(get_group_contract(group)["filter_fields"])
    for group in ("goods", "medicines", "traditional_medicine")
}
SORT_FIELDS = {
    group: frozenset(get_group_contract(group)["sort_fields"])
    for group in ("goods", "medicines", "traditional_medicine")
}


def validate_generation_id(generation_id: str) -> str:
    if not isinstance(generation_id, str) or not GENERATION_RE.fullmatch(generation_id):
        raise ValueError("generation must contain 1-64 letters, numbers, '.', '_' or '-' and start alphanumeric")
    return generation_id


def physical_collection_name(logical_group: str, generation_id: str) -> str:
    if logical_group not in LOGICAL_ALIASES:
        raise ValueError(f"unknown logical group: {logical_group}")
    return f"{LOGICAL_ALIASES[logical_group]}_v1_{validate_generation_id(generation_id)}"


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class CanonicalSort:
    field: str
    order: str = "desc"


@dataclass(frozen=True)
class ProcurementQuery:
    """Backend-neutral representation of the complete Phase 4B query contract."""

    group: str
    source_types: tuple[str, ...] = ()
    text: str = ""
    search_fields: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    structured_filters: Mapping[str, Any] = field(default_factory=dict)
    ranges: Mapping[str, Any] = field(default_factory=dict)
    date_ranges: Mapping[str, Any] = field(default_factory=dict)
    exact_identifiers: Mapping[str, Any] = field(default_factory=dict)
    sort: tuple[CanonicalSort, ...] = ()
    limit: int = 200
    page: int = 1
    search_mode: str = "standard"
    endpoint: str = "/api/query"
    query_mode: str = "search"
    query_class: str = "filter_only"

    @property
    def offset(self) -> int:
        return max(0, (self.page - 1) * self.limit)

    @property
    def fingerprint(self) -> str:
        payload = {
            "group": self.group,
            "source_types": list(self.source_types),
            "search_fields": list(self.search_fields),
            "filters": _plain(self.filters),
            "structured_filters": _plain(self.structured_filters),
            "ranges": _plain(self.ranges),
            "date_ranges": _plain(self.date_ranges),
            "exact_identifiers": _plain(self.exact_identifiers),
            "sort": [asdict(item) for item in self.sort],
            "limit": self.limit,
            "page": self.page,
            "search_mode": self.search_mode,
            "endpoint": self.endpoint,
            "query_mode": self.query_mode,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class AutocompleteQuery:
    group: str
    field: str
    keyword: str
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 10
    source_types: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    endpoint: str = "/api/autocomplete"

    @property
    def fingerprint(self) -> str:
        payload = {
            "group": self.group,
            "field": self.field,
            "keyword": self.keyword,
            "filters": _plain(self.filters),
            "limit": self.limit,
            "source_types": list(self.source_types),
            "search_fields": list(self.search_fields),
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def classify_query(filters: Mapping[str, Any], sort: Sequence[CanonicalSort]) -> str:
    return _classify_query(filters, sort)


def _classify_query(
    filters: Mapping[str, Any],
    sort: Sequence[CanonicalSort],
    *,
    text: str = "",
    search_fields: Sequence[str] = (),
    structured_filters: Mapping[str, Any] | None = None,
    exact_identifiers: Mapping[str, Any] | None = None,
) -> str:
    if exact_identifiers:
        return "exact_identifier"
    names = set(filters)
    if sort:
        return "explicit_sort"
    if names & {
        "approvalDecision", "regNo", "maTbmt", "tenderCode",
        "bid_invitation_code", "decision_number",
        "registration_or_import_permit_number",
        "marketing_authorization_or_import_permit",
    }:
        return "exact_identifier"
    if text.strip() or search_fields:
        return "full_text_relevance"
    if structured_filters:
        return "filter_only"
    if any(filters.get(name) for name in names):
        return "full_text_relevance"
    return "filter_only"


def build_canonical_query(
    group: str,
    filters: Any = None,
    sort: Any = None,
    limit: int = 200,
    *,
    page: int = 1,
    search_mode: str = "standard",
    endpoint: str = "/api/query",
    source_types: Sequence[str] | None = None,
    text: str = "",
    search_fields: Sequence[str] | None = None,
    structured_filters: Mapping[str, Any] | None = None,
    ranges: Mapping[str, Any] | None = None,
    date_ranges: Mapping[str, Any] | None = None,
    exact_identifiers: Mapping[str, Any] | None = None,
    query_mode: str = "search",
) -> ProcurementQuery:
    normalized = normalize_group(group)
    plain_filters = _plain(filters) or {}
    if not isinstance(plain_filters, Mapping):
        plain_filters = {}
    canonical_sort: list[CanonicalSort] = []
    for rule in _plain(sort) or []:
        if not isinstance(rule, Mapping) or not rule.get("column"):
            continue
        order = str(rule.get("order", "desc")).lower()
        canonical_sort.append(CanonicalSort(str(rule["column"]), "asc" if order == "asc" else "desc"))
    safe_limit = max(1, int(limit or 1))
    safe_page = max(1, int(page or 1))
    normalized_text = str(text or "").strip()
    normalized_fields = tuple(str(item) for item in (search_fields or ()) if str(item).strip())
    plain_structured = _plain(structured_filters) or {}
    plain_ranges = _plain(ranges) or {}
    plain_date_ranges = _plain(date_ranges) or {}
    plain_exact = _plain(exact_identifiers) or {}
    normalized_source_types = tuple(str(item).strip() for item in (source_types or ()) if str(item).strip())
    return ProcurementQuery(
        group=normalized,
        source_types=normalized_source_types,
        text=normalized_text,
        search_fields=normalized_fields,
        filters=dict(plain_filters),
        structured_filters=dict(plain_structured) if isinstance(plain_structured, Mapping) else {},
        ranges=dict(plain_ranges) if isinstance(plain_ranges, Mapping) else {},
        date_ranges=dict(plain_date_ranges) if isinstance(plain_date_ranges, Mapping) else {},
        exact_identifiers=dict(plain_exact) if isinstance(plain_exact, Mapping) else {},
        sort=tuple(canonical_sort),
        limit=safe_limit,
        page=safe_page,
        search_mode=search_mode if search_mode in {"standard", "full"} else "standard",
        endpoint=endpoint,
        query_mode=query_mode if query_mode in {"search", "exact", "autocomplete"} else "search",
        query_class=_classify_query(
            plain_filters,
            canonical_sort,
            text=normalized_text,
            search_fields=normalized_fields,
            structured_filters=plain_structured if isinstance(plain_structured, Mapping) else {},
            exact_identifiers=plain_exact if isinstance(plain_exact, Mapping) else {},
        ),
    )


BULK_FIELD_MAP = {
    "goods": {
        "lotName": "item_name", "goodsName": "item_name", "technicalSpec": "technical_specification",
        "bidItem": "technical_specification", "model": "model_mark", "brand": "brand",
        "country": "country_of_origin", "manufacturer": "manufacturer", "unit": "unit",
    },
    "medicines": {
        "drugName": "medicine_name", "activeIngredient": "active_ingredient_or_herbal_component",
        "concentration": "strength", "route": "route_of_administration", "dosageForm": "dosage_form",
        "drugGroup": "medicine_group", "unit": "unit", "regNo": "marketing_authorization_or_import_permit",
        "specification": "packaging", "manufacturer": "manufacturer", "country": "production_country",
    },
    "traditional_medicine": {
        "drugName": "item_name", "goodsName": "item_name", "activeIngredient": "scientific_name",
        "concentration": "processing_method", "specification": "packaging", "manufacturer": "manufacturer",
        "country": "production_country", "unit": "unit", "lotName": "item_name",
    },
}


def build_bulk_canonical_query(
    group: str,
    selected_fields: Sequence[str],
    row_values: Mapping[str, Any],
    *,
    limit: int = 10,
    endpoint: str = "/api/bulk-query",
    source_types: Sequence[str] | None = None,
    sort: Any = None,
    page: int = 1,
) -> ProcurementQuery:
    normalized = normalize_group(group)
    if normalized not in BULK_FIELD_MAP:
        raise ValueError(f"bulk shadow does not support group: {group}")
    filters: dict[str, Any] = {}
    for field_name in selected_fields:
        canonical = BULK_FIELD_MAP[normalized].get(field_name) or canonical_field_for(normalized, field_name)
        value = str(row_values.get(field_name) or "").strip()
        if canonical and value:
            filters[canonical] = {"tokens": [{"value": value, "op": "OR"}]}
    return build_canonical_query(
        normalized,
        filters,
        sort,
        limit=max(1, int(limit)),
        page=page,
        endpoint=endpoint,
        source_types=source_types,
    )


@dataclass(frozen=True)
class TypesenseRequestPlan:
    collection: str
    params: Mapping[str, Any]
    unsupported_filters: tuple[str, ...] = ()
    unsupported_sorts: tuple[str, ...] = ()
    expected_differences: tuple[str, ...] = ()


def _escape_filter_value(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("\n", " ").strip()


def _iso_date_range_clauses(start_value: Any, end_value: Any) -> tuple[str, ...]:
    """Build exact/prefix clauses for the frozen string date field.

    Typesense range operators are numeric-oriented. The serving schema stores
    ``partition_date`` as ISO ``YYYY-MM-DD`` strings, so bounded ranges can be
    represented losslessly as exact dates plus complete month/year prefixes.
    """

    if start_value is None or end_value is None:
        return ()
    try:
        start = date.fromisoformat(str(start_value))
        end = date.fromisoformat(str(end_value))
    except ValueError:
        return ()
    if start > end:
        return ()

    clauses: list[str] = []
    cursor = start
    while cursor <= end:
        year_end = date(cursor.year, 12, 31)
        if cursor == date(cursor.year, 1, 1) and year_end <= end:
            clauses.append(f"partition_date:={cursor.year}*")
            cursor = year_end + timedelta(days=1)
            continue
        if cursor.day == 1:
            next_month = date(
                cursor.year + (cursor.month == 12),
                1 if cursor.month == 12 else cursor.month + 1,
                1,
            )
            month_end = next_month - timedelta(days=1)
            if month_end <= end:
                clauses.append(f"partition_date:={cursor.strftime('%Y-%m')}*")
                cursor = next_month
                continue
        clauses.append(f"partition_date:=`{cursor.isoformat()}`")
        cursor += timedelta(days=1)
    return tuple(clauses)


def _contains_clause(field_name: str, value: Any, *, negate: bool = False) -> str:
    escaped = _escape_filter_value(value)
    operator = ":!" if negate else ":"
    return f"{field_name}{operator}`*{escaped}*`"


def _exact_clause(field_name: str, value: Any) -> str:
    return f"{field_name}:=`{_escape_filter_value(value)}`"


def _token_clauses(fields: Sequence[str], token_filter: Any) -> str | None:
    plain = _plain(token_filter)
    tokens = plain.get("tokens", []) if isinstance(plain, Mapping) else []
    and_parts: list[str] = []
    or_parts: list[str] = []
    not_parts: list[str] = []
    for item in tokens:
        if not isinstance(item, Mapping):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        positive = " || ".join(_contains_clause(name, value) for name in fields)
        op = str(item.get("op", "OR")).upper()
        if op == "NOT":
            not_parts.append(" && ".join(_contains_clause(name, value, negate=True) for name in fields))
        elif op == "AND":
            and_parts.append(f"({positive})")
        else:
            or_parts.append(f"({positive})")
    clauses: list[str] = []
    if and_parts:
        clauses.append(" && ".join(and_parts))
    if or_parts:
        clauses.append(" || ".join(or_parts))
    clauses.extend(not_parts)
    return " && ".join(f"({item})" for item in clauses) if clauses else None


def _list_clause(field_name: str, values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    members = [_exact_clause(field_name, value) for value in values if str(value or "").strip()]
    return "(" + " || ".join(members) + ")" if members else None


def _typed_exact_clause(field_name: str, value: Any, field_type: str) -> str:
    escaped = _escape_filter_value(value)
    return f"{field_name}:={escaped}" if field_type in {"float", "int32"} else f"{field_name}:=`{escaped}`"


def _typed_list_clause(field_name: str, values: Any, field_type: str) -> str | None:
    if not isinstance(values, (list, tuple, set)):
        return None
    members = [
        _typed_exact_clause(field_name, value, field_type)
        for value in values
        if value is not None and str(value).strip()
    ]
    return "(" + " || ".join(members) + ")" if members else None


def _structured_filter_clauses(
    group: str,
    structured_filters: Mapping[str, Any],
    unsupported: list[str],
) -> list[str]:
    contract = get_group_contract(group)
    fields = {item["name"]: item for item in contract["fields"]}
    clauses: list[str] = []
    for name, raw in sorted(structured_filters.items()):
        field = fields.get(name)
        if field is None or not field["filterable"]:
            unsupported.append(name)
            continue
        if raw is None or raw == "":
            continue
        field_type = field["type"]
        if isinstance(raw, Mapping):
            operator = str(raw.get("operator", raw.get("op", ""))).lower()
            if operator and "value" in raw:
                raw = {operator: raw["value"]}
            if any(key in raw for key in ("missing", "is_null", "null")):
                unsupported.append(f"{name}:null")
                continue
            entries = raw.items()
        elif isinstance(raw, (list, tuple, set)):
            entries = (("in", raw),)
        else:
            entries = (("eq", raw),)
        field_clauses: list[str] = []
        for operator, value in entries:
            operator = str(operator).lower()
            if operator in {"eq", "equals"}:
                field_clauses.append(_typed_exact_clause(name, value, field_type))
            elif operator in {"in", "any"}:
                clause = _typed_list_clause(name, value, field_type)
                if clause:
                    field_clauses.append(clause)
            elif operator in {"min", "from", "gte", ">="}:
                if field_type not in {"float", "int32"} and name != "partition_date":
                    unsupported.append(f"{name}:{operator}")
                    continue
                field_clauses.append(f"{name}:>={_escape_filter_value(value)}")
            elif operator in {"max", "to", "lte", "<="}:
                if field_type not in {"float", "int32"} and name != "partition_date":
                    unsupported.append(f"{name}:{operator}")
                    continue
                field_clauses.append(f"{name}:<={_escape_filter_value(value)}")
            elif operator in {"neq", "not", "ne", "!="}:
                field_clauses.append(f"{name}:!={_escape_filter_value(value)}")
            else:
                unsupported.append(f"{name}:{operator}")
        if field_clauses:
            clauses.append(" && ".join(field_clauses))
    return clauses


FILTER_FIELD_MAP: dict[str, dict[str, tuple[str, ...]]] = {
    "goods": {
        "investor": ("procuring_entity_name",), "approvalDecision": ("decision_number",),
        "winner": ("winning_bidder_name",), "drugName": ("item_name", "model_mark", "brand", "technical_specification"),
        "activeIngredient": ("item_name", "technical_specification"), "concentration": ("item_name", "technical_specification"),
        "route": ("item_name", "technical_specification"), "dosageForm": ("item_name", "technical_specification"),
        "specification": ("technical_specification",), "regNo": ("registration_or_import_permit_number",),
        "unit": ("unit",), "manufacturer": ("manufacturer",), "country": ("country_of_origin",),
        "selectionMethod": ("selection_method",), "place": ("location",), "drugGroup": ("item_name", "technical_specification"),
    },
    "medicines": {
        "investor": ("procuring_entity_name",), "approvalDecision": ("decision_number",),
        "winner": ("winning_bidder_name",), "drugName": ("medicine_name",),
        "activeIngredient": ("active_ingredient_or_herbal_component",), "concentration": ("strength",),
        "route": ("route_of_administration",), "dosageForm": ("dosage_form",), "specification": ("packaging",),
        "regNo": ("marketing_authorization_or_import_permit",), "unit": ("unit",), "manufacturer": ("manufacturer",),
        "country": ("production_country",), "selectionMethod": ("selection_method",), "place": ("location",),
        "drugGroup": ("medicine_group",),
    },
    "traditional_medicine": {
        "investor": ("procuring_entity_name",), "approvalDecision": ("decision_number",),
        "winner": ("winning_bidder_name",), "drugName": ("item_name",),
        "activeIngredient": ("scientific_name", "item_name"), "concentration": ("item_name",),
        "route": ("processing_method",), "dosageForm": ("processing_method",), "specification": ("packaging",),
        "regNo": ("registration_or_import_permit_number",), "unit": ("unit",), "manufacturer": ("manufacturer",),
        "country": ("production_country",), "selectionMethod": ("selection_method",), "place": ("location",),
        "drugGroup": ("technical_group",),
    },
}

SORT_FIELD_MAP: dict[str, dict[str, str]] = {
    "goods": {
        "ma_tbmt": "bid_invitation_code", "approvalDate": "partition_date", "quantity": "quantity",
        "unitPrice": "winning_unit_price", "productionYear": "production_year", "bidderCount": "bidder_count",
    },
    "medicines": {
        "ma_tbmt": "bid_invitation_code", "approvalDate": "partition_date", "quantity": "quantity",
        "unitPrice": "winning_unit_price", "bidderCount": "bidder_count",
    },
    "traditional_medicine": {
        "ma_tbmt": "bid_invitation_code", "approvalDate": "partition_date", "quantity": "quantity",
        "unitPrice": "winning_unit_price", "bidderCount": "bidder_count",
    },
}


def translate_typesense_query(query: ProcurementQuery, *, serving_generation: str | None = None) -> TypesenseRequestPlan:
    schema_group = normalize_group(query.group)
    query_group = public_group(schema_group)
    clauses: list[str] = []
    unsupported: list[str] = []
    expected_differences: list[str] = []
    mapping = FILTER_FIELD_MAP[schema_group]

    if query.source_types:
        try:
            selector_field, selector_values = source_selector(query_group, query.source_types)
        except ValueError as exc:
            unsupported.append("source_types")
            expected_differences.append(str(exc))
        else:
            selector_clause = _list_clause(selector_field, list(selector_values))
            if selector_clause:
                clauses.append(selector_clause)

    clauses.extend(_structured_filter_clauses(query_group, query.structured_filters, unsupported))
    for name, raw_value in sorted(query.ranges.items()):
        field = get_group_contract(query_group).get("fields", [])
        field_info = next((item for item in field if item["name"] == name), None)
        if field_info is None or not field_info["filterable"] or field_info["type"] not in {"float", "int32"}:
            unsupported.append(name)
            continue
        if not isinstance(raw_value, Mapping):
            unsupported.append(name)
            continue
        for operator, value in ((">=", raw_value.get("min")), ("<=", raw_value.get("max"))):
            if value is not None:
                clauses.append(f"{name}:{operator}{_escape_filter_value(value)}")
    for name, raw_value in sorted(query.date_ranges.items()):
        if name != "partition_date":
            unsupported.append(name)
            continue
        if not isinstance(raw_value, Mapping):
            unsupported.append(name)
            continue
        range_clauses = _iso_date_range_clauses(raw_value.get("from"), raw_value.get("to"))
        if range_clauses:
            clauses.append("(" + " || ".join(range_clauses) + ")")
        else:
            for operator, value in ((">=", raw_value.get("from")), ("<=", raw_value.get("to"))):
                if value is not None:
                    clauses.append(f"partition_date:{operator}{_escape_filter_value(value)}")
        expected_differences.append("date range uses ingestion partition_date; source timestamps remain display-only strings")

    for name, raw_value in sorted(query.filters.items()):
        if raw_value is None or raw_value == "":
            continue
        if name in {"priceFrom", "priceTo", "quantityFrom", "quantityTo"}:
            field_name = "winning_unit_price" if name.startswith("price") else "quantity"
            operator = ">=" if name.endswith("From") else "<="
            clauses.append(f"{field_name}:{operator}{_escape_filter_value(raw_value)}")
            continue
        if name in {"dateFrom", "dateTo"}:
            value = _escape_filter_value(raw_value)
            operator = ">=" if name == "dateFrom" else "<="
            clauses.append(f"partition_date:{operator}{value}")
            expected_differences.append("date range uses ingestion partition_date; Postgres uses package approval date")
            continue
        if name == "validity":
            unsupported.append(name)
            continue
        fields = (name,) if (name in QUERY_BY[schema_group] or name in FILTER_FIELDS[schema_group]) and name not in mapping else mapping.get(name)
        if not fields:
            unsupported.append(name)
            continue
        if name in {"selectionMethod", "place"}:
            clause = _list_clause(fields[0], raw_value)
        elif name == "drugGroup" and schema_group == "medicines":
            plain = _plain(raw_value)
            values = plain if isinstance(plain, list) else (plain.get("tokens", []) if isinstance(plain, Mapping) else [])
            values = [item.get("value") if isinstance(item, Mapping) else item for item in values]
            clause = _list_clause(fields[0], values)
        else:
            clause = _token_clauses(fields, raw_value)
        if clause:
            clauses.append(clause)

    sort_parts: list[str] = []
    unsupported_sorts: list[str] = []
    for rule in query.sort:
        field_name = SORT_FIELD_MAP[schema_group].get(rule.field) or (rule.field if rule.field in SORT_FIELDS[schema_group] else None)
        if not field_name or field_name not in SORT_FIELDS[schema_group]:
            unsupported_sorts.append(rule.field)
            continue
        sort_parts.append(f"{field_name}:{rule.order}")
    # Typesense v30 treats ``id`` as an implicit document identifier and does
    # not allow it in ``sort_by``. Keep ordering inside the frozen live schema;
    # insertion order is Typesense's final tie-breaker.
    if not sort_parts:
        sort_parts = ["partition_date:desc"]
    if "approvalDate" in [rule.field for rule in query.sort]:
        expected_differences.append("approvalDate sort uses partition_date; Typesense schema has no package approval date")

    query_fields = list(QUERY_BY[schema_group])
    unsupported_search_fields: list[str] = []
    if query.search_fields:
        query_fields = []
        for name in query.search_fields:
            canonical = canonical_field_for(query_group, name) or name
            if canonical in QUERY_BY[schema_group]:
                query_fields.append(canonical)
            else:
                unsupported_search_fields.append(name)
        unsupported.extend(unsupported_search_fields)
        if not query_fields:
            query_fields = [QUERY_BY[schema_group][0]]

    exact_items = list(query.exact_identifiers.items())
    exact_field: str | None = None
    exact_value: Any = None
    if exact_items:
        if len(exact_items) != 1:
            unsupported.append("exact_identifiers")
        else:
            exact_field = canonical_field_for(query_group, exact_items[0][0]) or exact_items[0][0]
            exact_value = exact_items[0][1]
            if exact_value is None or not str(exact_value).strip():
                unsupported.append(exact_items[0][0])
            elif exact_field != "id":
                contract = get_group_contract(query_group)
                field_info = next((field for field in contract["fields"] if field["name"] == exact_field), None)
                if (
                    exact_field not in contract["identifier_fields"]
                    or field_info is None
                    or field_info["type"] not in {"string", "string[]"}
                ):
                    unsupported.append(exact_items[0][0])

    q = query.text or "*"
    if not query.text and not query.search_fields and not exact_items:
        # q=* does not need relevance across every indexed text field.
        query_fields = [QUERY_BY[schema_group][0]]
    if exact_field and exact_value is not None:
        q = str(exact_value)
        query_fields = [exact_field]
    weights = [1] if not (query.text or query.search_fields or exact_field) else [
        get_group_contract(query_group)["full_text"]["weights"][QUERY_BY[schema_group].index(field)]
        if field in QUERY_BY[schema_group] else 1
        for field in query_fields
    ]

    params: dict[str, Any] = {
        "q": q,
        "query_by": ",".join(query_fields),
        "query_by_weights": ",".join(str(weight) for weight in weights),
        "page": query.page,
        "per_page": query.limit,
        "sort_by": ",".join(sort_parts),
        "include_fields": ",".join(get_group_contract(query_group)["result_fields"]),
    }
    if exact_field:
        params.update({"num_typos": 0, "prefix": "false", "exhaustive_search": "true"})
    if clauses:
        params["filter_by"] = " && ".join(clauses)
    return TypesenseRequestPlan(
        collection=physical_collection_name(schema_group, serving_generation or get_shadow_config().serving_generation),
        params=params,
        unsupported_filters=tuple(unsupported),
        unsupported_sorts=tuple(unsupported_sorts),
        expected_differences=tuple(dict.fromkeys(expected_differences)),
    )


@dataclass(frozen=True)
class TypesenseShadowConfig:
    enabled: bool = False
    serving_generation: str = "serving_v1_20260901"
    sample_rate: float = 0.0
    timeout_seconds: float = 0.5
    host: str = "127.0.0.1"
    port: int = 8108
    protocol: str = "http"
    api_key: str = field(default="", repr=False)
    report_destination: str = ""
    debug_queries: bool = False

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> "TypesenseShadowConfig":
        raw_rate = os.getenv("BIDFINDER_TYPESENSE_SHADOW_SAMPLE_RATE", "0")
        try:
            rate = min(1.0, max(0.0, float(raw_rate)))
        except ValueError:
            rate = 0.0
        generation = os.getenv("BIDFINDER_TYPESENSE_SERVING_GENERATION", "serving_v1_20260901").strip()
        validate_generation_id(generation)
        try:
            timeout = max(0.05, float(os.getenv("BIDFINDER_TYPESENSE_SHADOW_TIMEOUT_SECONDS", "0.5")))
        except ValueError:
            timeout = 0.5
        try:
            port = int(os.getenv("BIDFINDER_TYPESENSE_PORT", "8108"))
        except ValueError:
            port = 8108
        host = os.getenv("BIDFINDER_TYPESENSE_HOST", os.getenv("TYPESENSE_HOST", "127.0.0.1"))
        protocol = os.getenv("BIDFINDER_TYPESENSE_PROTOCOL", os.getenv("TYPESENSE_PROTOCOL", "http")).lower()
        if protocol not in {"http", "https"} or not host or "://" in host or "/" in host:
            raise ValueError("invalid Typesense shadow endpoint configuration")
        return cls(
            enabled=_env_flag("BIDFINDER_TYPESENSE_SHADOW_ENABLED", False),
            serving_generation=generation,
            sample_rate=rate,
            timeout_seconds=timeout,
            host=host,
            port=max(1, min(65535, port)),
            protocol=protocol,
            api_key=os.getenv("BIDFINDER_TYPESENSE_API_KEY", os.getenv("TYPESENSE_API_KEY", "")),
            report_destination=os.getenv("BIDFINDER_TYPESENSE_SHADOW_REPORT_DESTINATION", "").strip(),
            debug_queries=_env_flag("BIDFINDER_TYPESENSE_SHADOW_DEBUG_QUERIES", False),
        )


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def get_shadow_config() -> TypesenseShadowConfig:
    return TypesenseShadowConfig.from_env()


@dataclass(frozen=True)
class TypesenseSearchResult:
    group: str
    total: int
    hits: tuple[Mapping[str, Any], ...]
    latency_ms: float
    page: int
    per_page: int

    def to_api_page(self) -> dict[str, Any]:
        visible = [dict(row) for row in self.hits]
        has_more = self.page * self.per_page < self.total
        return {
            "data": visible,
            "count": self.total,
            "count_exact": True,
            "count_label": str(self.total),
            "count_summary": str(self.total),
            "displayed": len(visible),
            "has_more": has_more,
            "approx_total": None,
            "page": self.page,
            "limit": self.per_page,
            "backend": "typesense",
            "typesense_latency_ms": round(self.latency_ms, 3),
        }


@dataclass(frozen=True)
class SuggestionMetric:
    endpoint: str
    query_class: str
    group: str
    query_fingerprint: str
    postgres_success: bool
    typesense_success: bool
    postgres_latency_ms: float | None
    typesense_latency_ms: float | None
    postgres_total: int | None
    typesense_total: int | None
    page_size: int
    exact_uuid_intersection: int | None
    missing_from_typesense: int | None
    extra_in_typesense: int | None
    top_k_overlap: float | None
    explicit_sort_parity: bool | None
    field_mismatch_count: int | None
    error_classification: str
    severity: str | None
    slow_outlier: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TypesenseShadowError(RuntimeError):
    def __init__(self, message: str, code: str = SHADOW_INFRA_ERROR):
        self.code = code
        super().__init__(message)


class SearchRepository(Protocol):
    async def search(self, query: ProcurementQuery) -> TypesenseSearchResult:
        ...


class PostgresSearchRepository:
    """Canonical seam for existing SQL reader; SQL stays in ``server.py``."""

    def __init__(self, fetch_page: Callable[..., Awaitable[Mapping[str, Any]]]):
        self._fetch_page = fetch_page

    async def search(self, connection: Any, query: ProcurementQuery, *, exact_count_enabled: bool = False) -> Mapping[str, Any]:
        return await self._fetch_page(connection, query, exact_count_enabled=exact_count_enabled)


class TypesenseSearchRepository:
    """Read-only app adapter. It only addresses versioned physical collections."""

    def __init__(self, config: TypesenseShadowConfig | None = None, *, opener: Callable[..., Any] | None = None):
        self.config = config or get_shadow_config()
        self._opener = opener or urlopen

    def _request(self, query: ProcurementQuery) -> TypesenseSearchResult:
        started = time.perf_counter()
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")
        plan = translate_typesense_query(query, serving_generation=self.config.serving_generation)
        if plan.unsupported_filters or plan.unsupported_sorts:
            unsupported = ", ".join((*plan.unsupported_filters, *plan.unsupported_sorts))
            raise TypesenseShadowError(f"unsupported search contract field(s): {unsupported}", QUERY_CONTRACT_FAILURE)
        params = urlencode(plan.params, doseq=True)
        url = f"{self.config.base_url}/collections/{quote(plan.collection, safe='')}/documents/search?{params}"
        request = Request(url, method="GET", headers={
            "Accept": "application/json",
            "X-TYPESENSE-API-KEY": self.config.api_key,
        })
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            code = SHADOW_INFRA_ERROR if exc.code in {408, 425, 429} or exc.code >= 500 else QUERY_CONTRACT_FAILURE
            raise TypesenseShadowError(f"Typesense HTTP {exc.code}", code=code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TypesenseShadowError(f"Typesense request failed: {type(exc).__name__}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TypesenseShadowError("Typesense returned invalid JSON") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("found"), int) or isinstance(payload.get("found"), bool) or payload["found"] < 0:
            raise TypesenseShadowError("Typesense returned malformed search metadata")
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            raise TypesenseShadowError("Typesense returned malformed hits")
        documents: list[Mapping[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, Mapping) or not isinstance(hit.get("document"), Mapping):
                raise TypesenseShadowError("Typesense returned malformed hit")
            document = dict(hit["document"])
            if not isinstance(document.get("id"), str) or not document["id"]:
                raise TypesenseShadowError("Typesense document has no identity")
            documents.append(document)
        return TypesenseSearchResult(
            group=public_group(query.group),
            total=int(payload["found"]),
            hits=tuple(documents),
            latency_ms=(time.perf_counter() - started) * 1000,
            page=query.page,
            per_page=query.limit,
        )

    async def search(self, query: ProcurementQuery) -> TypesenseSearchResult:
        return await asyncio.to_thread(self._request, query)

    def _exact_lookup(self, query: ProcurementQuery) -> TypesenseSearchResult:
        if len(query.exact_identifiers) != 1:
            raise TypesenseShadowError("exact lookup requires one identifier", QUERY_CONTRACT_FAILURE)
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")
        field_name, value = next(iter(query.exact_identifiers.items()))
        if value is None or not str(value).strip():
            raise TypesenseShadowError("exact lookup requires a non-empty identifier", QUERY_CONTRACT_FAILURE)
        canonical = canonical_field_for(public_group(query.group), field_name) or field_name
        if canonical == "id":
            started = time.perf_counter()
            plan = translate_typesense_query(query, serving_generation=self.config.serving_generation)
            if plan.unsupported_filters or plan.unsupported_sorts:
                unsupported = ", ".join((*plan.unsupported_filters, *plan.unsupported_sorts))
                raise TypesenseShadowError(f"unsupported search contract field(s): {unsupported}", QUERY_CONTRACT_FAILURE)
            url = f"{self.config.base_url}/collections/{quote(plan.collection, safe='')}/documents/{quote(str(value), safe='')}"
            request = Request(url, method="GET", headers={"Accept": "application/json", "X-TYPESENSE-API-KEY": self.config.api_key})
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    document = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 404:
                    return TypesenseSearchResult(public_group(query.group), 0, (), (time.perf_counter() - started) * 1000, query.page, query.limit)
                code = SHADOW_INFRA_ERROR if exc.code >= 500 else QUERY_CONTRACT_FAILURE
                raise TypesenseShadowError(f"Typesense HTTP {exc.code}", code=code) from exc
            except (URLError, TimeoutError, OSError) as exc:
                raise TypesenseShadowError(f"Typesense request failed: {type(exc).__name__}") from exc
            if not isinstance(document, Mapping) or not document.get("id"):
                raise TypesenseShadowError("Typesense exact document response is malformed")
            return TypesenseSearchResult(public_group(query.group), 1, (dict(document),), (time.perf_counter() - started) * 1000, query.page, query.limit)
        return self._request(query)

    async def exact_lookup(self, query: ProcurementQuery) -> TypesenseSearchResult:
        return await asyncio.to_thread(self._exact_lookup, query)

    def _suggest(self, query: AutocompleteQuery) -> tuple[str, ...]:
        started = time.perf_counter()
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")
        group = public_group(query.group)
        canonical = canonical_field_for(group, query.field) or query.field
        allowed = set(get_group_contract(group)["autocomplete_fields"])
        fields = tuple(query.search_fields) or ((canonical,) if canonical in allowed else ())
        if not fields:
            return ()
        plan = translate_typesense_query(
            build_canonical_query(
                group,
                query.filters,
                limit=query.limit,
                endpoint=query.endpoint,
                source_types=query.source_types,
            ),
            serving_generation=self.config.serving_generation,
        )
        params = dict(plan.params)
        params.update({
            "q": query.keyword or "*",
            "query_by": ",".join(fields),
            "query_by_weights": ",".join("1" for _ in fields),
            "per_page": query.limit,
            "include_fields": ",".join(fields),
            "prefix": "true",
            "num_typos": 0,
        })
        url = f"{self.config.base_url}/collections/{quote(plan.collection, safe='')}/documents/search?{urlencode(params)}"
        request = Request(url, method="GET", headers={"Accept": "application/json", "X-TYPESENSE-API-KEY": self.config.api_key})
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            code = SHADOW_INFRA_ERROR if exc.code in {408, 425, 429} or exc.code >= 500 else QUERY_CONTRACT_FAILURE
            raise TypesenseShadowError(f"Typesense HTTP {exc.code}", code=code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TypesenseShadowError(f"Typesense suggestion request failed: {type(exc).__name__}") from exc
        except Exception as exc:
            if isinstance(exc, TypesenseShadowError):
                raise
            raise TypesenseShadowError(f"Typesense suggestion request failed: {type(exc).__name__}") from exc
        hits = payload.get("hits", []) if isinstance(payload, Mapping) else None
        if not isinstance(hits, list):
            raise TypesenseShadowError("Typesense returned malformed suggestion hits")
        values: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            document = hit.get("document") if isinstance(hit, Mapping) else None
            if not isinstance(document, Mapping):
                continue
            for name in fields:
                value = document.get(name)
                members = value if isinstance(value, list) else [value]
                for member in members:
                    text = " ".join(str(member or "").split()).strip()
                    if text and text.casefold().startswith(query.keyword.casefold()) and text.casefold() not in seen:
                        seen.add(text.casefold())
                        values.append(text)
        _ = started
        return tuple(values[: query.limit])

    async def suggest(self, query: AutocompleteQuery) -> tuple[str, ...]:
        return await asyncio.to_thread(self._suggest, query)


@dataclass(frozen=True)
class ParityMetric:
    endpoint: str
    query_class: str
    group: str
    query_fingerprint: str
    postgres_success: bool
    typesense_success: bool
    postgres_latency_ms: float | None
    typesense_latency_ms: float | None
    postgres_total: int | None
    typesense_total: int | None
    page_size: int
    exact_uuid_intersection: int | None
    missing_from_typesense: int | None
    extra_in_typesense: int | None
    top_k_overlap: float | None
    explicit_sort_parity: bool | None
    field_mismatch_count: int | None
    error_classification: str
    severity: str | None
    identity_strategy: str = "unknown"
    identity_collision_groups: int = 0
    unsupported_filters: tuple[str, ...] = ()
    unsupported_sorts: tuple[str, ...] = ()
    expected_differences: tuple[str, ...] = ()
    slow_outlier: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["unsupported_filters"] = list(self.unsupported_filters)
        value["unsupported_sorts"] = list(self.unsupported_sorts)
        value["expected_differences"] = list(self.expected_differences)
        return value


def _authoritative_identity(record: Mapping[str, Any]) -> str | None:
    for key in ("id", "uuid", "source_uuid", "record_uuid", "document_id"):
        value = record.get(key)
        if isinstance(value, str) and UUID_RE.fullmatch(value):
            return value.lower()
    return None


def _normalized_identity_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        values = [_normalized_identity_value(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not value.is_integer():
            return format(value, ".15g")
        if isinstance(value, Decimal):
            normalized = format(value, "f").rstrip("0").rstrip(".")
            return normalized or "0"
        return str(int(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _fold(value)


def _identity_fingerprint(group: str, record: Mapping[str, Any]) -> str | None:
    aliases = IDENTITY_FIELD_ALIASES.get(group)
    if not aliases:
        return None
    folded = {_fold(key): value for key, value in record.items()}
    values: list[list[Any]] = []
    for name, names in aliases:
        value = next((folded[_fold(alias)] for alias in names if _fold(alias) in folded), None)
        values.append([name, _normalized_identity_value(value)])
    fields = dict(values)
    if not fields.get("bid_invitation_code"):
        return None
    anchors = {
        "goods": ("lot_code", "lot_name", "item_name", "model_mark"),
        "medicines": ("medicine_code", "medicine_name", "active_ingredient_or_herbal_component"),
        "traditional_medicine": ("item_name", "scientific_name"),
    }[group]
    if not any(fields.get(name) for name in anchors):
        return None
    payload = {"group": group, "fields": values}
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"fp:{digest}"


def _identity(record: Mapping[str, Any], group: str | None = None, *, strategy: str = "uuid") -> str | None:
    if strategy == "fingerprint" and group:
        return _identity_fingerprint(group, record)
    return _authoritative_identity(record)


def identity_collision_audit(records: Sequence[Mapping[str, Any]], group: str) -> dict[str, int]:
    identities = [_identity(record, group, strategy="fingerprint") for record in records]
    counts = Counter(identity for identity in identities if identity)
    duplicate_groups = sum(count > 1 for count in counts.values())
    return {
        "rows": len(records),
        "identity_rows": len([identity for identity in identities if identity]),
        "unique_fingerprints": len(counts),
        "duplicated_fingerprint_groups": duplicate_groups,
        "ambiguous_collision_groups": duplicate_groups,
    }


def _primary_rows(primary: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    if isinstance(primary, Mapping):
        rows = primary.get("data", [])
    else:
        rows = primary or []
    return tuple(row for row in rows if isinstance(row, Mapping))


FIELD_ALIASES = {
    "item_name": ("item_name", "ten hang hoa", "danh muc hang hoa", "ten thuoc"),
    "medicine_name": ("medicine_name", "ten thuoc"),
    "active_ingredient_or_herbal_component": ("active_ingredient_or_herbal_component", "ten hoat chat"),
    "strength": ("strength", "nong do ham luong"),
    "route_of_administration": ("route_of_administration", "duong dung"),
    "dosage_form": ("dosage_form", "dang bao che"),
    "packaging": ("packaging", "quy cach"),
    "unit": ("unit", "don vi tinh"),
    "manufacturer": ("manufacturer", "co so san xuat", "hang san xuat"),
    "production_country": ("production_country", "xuat xu"),
    "country_of_origin": ("country_of_origin", "xuat xu"),
    "winning_bidder_name": ("winning_bidder_name", "nha thau trung thau"),
    "procuring_entity_name": ("procuring_entity_name", "chu dau tu"),
    "selection_method": ("selection_method", "hinh thuc lcnt"),
    "location": ("location", "dia diem"),
    "decision_number": ("decision_number", "quyet dinh phe duyet"),
    "bid_invitation_code": ("bid_invitation_code", "ma tbmt"),
    "quantity": ("quantity", "so luong", "khoi luong"),
    "winning_unit_price": ("winning_unit_price", "don gia trung thau (vnd)"),
}


def _fold(value: Any) -> str:
    import unicodedata
    text = str(value if value is not None else "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


def _canonical_fields(group: str, row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    folded = {_fold(key): value for key, value in row.items()}
    for canonical, aliases in FIELD_ALIASES.items():
        if canonical == "item_name" and group == "medicines":
            continue
        if canonical == "medicine_name" and group != "medicines":
            continue
        for alias in aliases:
            if _fold(alias) in folded:
                result[canonical] = folded[_fold(alias)]
                break
    return result


def _values_equivalent(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if isinstance(left, list) or isinstance(right, list):
        left_values = {_fold(item) for item in (left if isinstance(left, list) else [left]) if item is not None}
        right_values = {_fold(item) for item in (right if isinstance(right, list) else [right]) if item is not None}
        return left_values == right_values
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        return float(left) == float(right)
    return _fold(left) == _fold(right)


def _field_mismatches(
    group: str,
    primary_rows: Sequence[Mapping[str, Any]],
    shadow_rows: Sequence[Mapping[str, Any]],
    *,
    strategy: str,
) -> int:
    primary_by_id = {
        _identity(row, group, strategy=strategy): row
        for row in primary_rows
        if _identity(row, group, strategy=strategy)
    }
    shadow_by_id = {
        _identity(row, group, strategy=strategy): row
        for row in shadow_rows
        if _identity(row, group, strategy=strategy)
    }
    mismatches = 0
    for record_id in primary_by_id.keys() & shadow_by_id.keys():
        left = _canonical_fields(group, primary_by_id[record_id])
        right = _canonical_fields(group, shadow_by_id[record_id])
        for name in left.keys() & right.keys():
            if not _values_equivalent(left[name], right[name]):
                mismatches += 1
    return mismatches


def _severity(query_class: str, *, set_mismatch: bool, count_mismatch: bool, field_mismatch: bool, sort_mismatch: bool, latency_ms: float | None) -> str | None:
    if field_mismatch:
        return SEVERITY_P0
    if latency_ms is not None and latency_ms > 500:
        return SEVERITY_P3
    return None


def compare_results(
    query: ProcurementQuery,
    primary: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    shadow: TypesenseSearchResult | None,
    *,
    postgres_latency_ms: float | None = None,
    error: str | None = None,
) -> ParityMetric:
    primary_rows = _primary_rows(primary)
    primary_total = int(primary.get("count", len(primary_rows))) if isinstance(primary, Mapping) and primary.get("count") is not None else len(primary_rows)
    shadow_rows = shadow.hits if shadow is not None else ()
    identity_strategy = "uuid" if primary_rows and all(_authoritative_identity(row) for row in primary_rows) else "fingerprint"
    primary_ids = [_identity(row, query.group, strategy=identity_strategy) for row in primary_rows]
    shadow_ids = [_identity(row, query.group, strategy=identity_strategy) for row in shadow_rows]
    identity_required = query.endpoint != "/api/query-preview" and bool(primary_rows)
    primary_comparable = not identity_required or all(value is not None for value in primary_ids)
    shadow_comparable = not identity_required or all(value is not None for value in shadow_ids)
    comparable = primary_comparable and shadow_comparable
    primary_counts = Counter(value for value in primary_ids if value) if comparable else Counter()
    shadow_counts = Counter(value for value in shadow_ids if value) if comparable else Counter()
    collision_groups = (
        sum(count > 1 for count in primary_counts.values()) + sum(count > 1 for count in shadow_counts.values())
        if comparable and identity_required else 0
    )
    if shadow is None:
        return ParityMetric(
            endpoint=query.endpoint, query_class=query.query_class, group=query.group,
            query_fingerprint=query.fingerprint, postgres_success=True, typesense_success=False,
            postgres_latency_ms=postgres_latency_ms, typesense_latency_ms=None, postgres_total=primary_total,
            typesense_total=None, page_size=query.limit, exact_uuid_intersection=None,
            missing_from_typesense=None, extra_in_typesense=None, top_k_overlap=None,
            explicit_sort_parity=None, field_mismatch_count=None, error_classification=SHADOW_INFRA_ERROR,
            severity=None, timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            slow_outlier=False,
            identity_strategy=identity_strategy,
            identity_collision_groups=collision_groups,
        )
    missing = sum(max(0, count - shadow_counts.get(identity, 0)) for identity, count in primary_counts.items()) if comparable else None
    extra = sum(max(0, count - primary_counts.get(identity, 0)) for identity, count in shadow_counts.items()) if comparable else None
    intersection = sum(min(count, shadow_counts.get(identity, 0)) for identity, count in primary_counts.items()) if comparable else None
    top_k = None
    if comparable:
        top_primary = [item for item in primary_ids[:10] if item]
        top_shadow = [item for item in shadow_ids[:10] if item]
        denominator = min(10, len(top_primary), len(top_shadow))
        top_k = (len(set(top_primary) & set(top_shadow)) / denominator) if denominator else (1.0 if not top_primary and not top_shadow else 0.0)
    sort_parity = None
    if query.sort and comparable:
        sort_parity = primary_ids[:query.limit] == shadow_ids[:query.limit]
    field_mismatch = _field_mismatches(query.group, primary_rows, shadow_rows, strategy=identity_strategy) if comparable and identity_required else 0
    count_mismatch = isinstance(primary, Mapping) and bool(primary.get("count_exact", True)) and primary_total != shadow.total
    set_mismatch = comparable and identity_required and bool(missing or extra)
    sort_mismatch = identity_required and sort_parity is False
    severity = None if not comparable or collision_groups else _severity(
        query.query_class,
        set_mismatch=set_mismatch,
        count_mismatch=count_mismatch,
        field_mismatch=bool(field_mismatch),
        sort_mismatch=sort_mismatch,
        latency_ms=shadow.latency_ms,
    )
    slow_outlier = shadow.latency_ms > 500
    if error:
        classification = SHADOW_INFRA_ERROR
    elif collision_groups:
        classification = IDENTITY_NOT_COMPARABLE
    elif not comparable:
        classification = SHADOW_PARITY_NOT_COMPARABLE
    elif field_mismatch:
        classification = QUERY_CONTRACT_FAILURE
    elif set_mismatch or count_mismatch:
        # Postgres is a sparse legacy subset. Population expansion is evidence,
        # not a correctness failure or cutover blocker.
        classification = LEGACY_POPULATION_DIFFERENCE
        severity = None
    elif sort_mismatch:
        classification = RANKING_DIFFERENCE
        severity = None
    elif slow_outlier:
        classification = PERFORMANCE_OUTLIER
        severity = SEVERITY_P3
    else:
        classification = SHADOW_OK
    return ParityMetric(
        endpoint=query.endpoint, query_class=query.query_class, group=query.group,
        query_fingerprint=query.fingerprint, postgres_success=True, typesense_success=True,
        postgres_latency_ms=postgres_latency_ms, typesense_latency_ms=shadow.latency_ms,
        postgres_total=primary_total, typesense_total=shadow.total, page_size=query.limit,
        exact_uuid_intersection=intersection, missing_from_typesense=missing, extra_in_typesense=extra,
        top_k_overlap=top_k, explicit_sort_parity=sort_parity, field_mismatch_count=field_mismatch,
        error_classification=classification, severity=severity, slow_outlier=slow_outlier,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        identity_strategy=identity_strategy,
        identity_collision_groups=collision_groups,
    )


def _write_metric(config: TypesenseShadowConfig, metric: ParityMetric) -> None:
    payload = metric.to_dict()
    if config.debug_queries:
        payload["debug"] = "query values intentionally omitted; use fingerprint for replay correlation"
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if config.report_destination:
        destination = Path(config.report_destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    logger.info("typesense_shadow %s", line)


def _classify_shadow_error(error: Exception) -> str:
    if isinstance(error, ValueError) or getattr(error, "code", "") == QUERY_CONTRACT_FAILURE:
        return QUERY_CONTRACT_FAILURE
    return SHADOW_INFRA_ERROR


async def run_shadow_comparison(
    queries: Sequence[ProcurementQuery],
    primary_results: Mapping[str, Mapping[str, Any] | Sequence[Mapping[str, Any]] | None],
    *,
    repository: SearchRepository | None = None,
    config: TypesenseShadowConfig | None = None,
    postgres_latencies_ms: Mapping[str, float] | None = None,
) -> tuple[ParityMetric, ...]:
    config = config or get_shadow_config()
    if not config.enabled or config.sample_rate <= 0 or random.random() > config.sample_rate:
        return ()
    repository = repository or TypesenseSearchRepository(config)
    postgres_latencies_ms = postgres_latencies_ms or {}

    async def one(query: ProcurementQuery) -> ParityMetric:
        plan = TypesenseRequestPlan(collection="", params={})
        try:
            plan = translate_typesense_query(query, serving_generation=config.serving_generation)
            shadow = await asyncio.wait_for(repository.search(query), timeout=config.timeout_seconds)
            metric = compare_results(query, primary_results.get(query.group), shadow, postgres_latency_ms=postgres_latencies_ms.get(query.group))
            metric = ParityMetric(**{**metric.to_dict(), "unsupported_filters": plan.unsupported_filters, "unsupported_sorts": plan.unsupported_sorts, "expected_differences": plan.expected_differences})
        except Exception as exc:
            metric = compare_results(query, primary_results.get(query.group), None, postgres_latency_ms=postgres_latencies_ms.get(query.group), error=str(exc))
            metric = ParityMetric(**{
                **metric.to_dict(),
                "error_classification": _classify_shadow_error(exc),
                "unsupported_filters": plan.unsupported_filters,
                "unsupported_sorts": plan.unsupported_sorts,
                "expected_differences": plan.expected_differences,
            })
        await asyncio.to_thread(_write_metric, config, metric)
        return metric

    return tuple(await asyncio.gather(*(one(query) for query in queries)))


async def run_shadow_autocomplete(
    queries: Sequence[AutocompleteQuery],
    primary_suggestions: Sequence[str],
    *,
    repository: TypesenseSearchRepository | None = None,
    config: TypesenseShadowConfig | None = None,
    postgres_latency_ms: float | None = None,
) -> tuple[SuggestionMetric, ...]:
    config = config or get_shadow_config()
    if not config.enabled or config.sample_rate <= 0 or random.random() > config.sample_rate:
        return ()
    repository = repository or TypesenseSearchRepository(config)
    primary_set = {str(item).strip().lower() for item in primary_suggestions if str(item).strip()}

    async def one(query: AutocompleteQuery) -> SuggestionMetric:
        started = time.perf_counter()
        try:
            suggestions = await asyncio.wait_for(repository.suggest(query), timeout=config.timeout_seconds)
            shadow_set = {item.strip().lower() for item in suggestions if item.strip()}
            overlap = len(primary_set & shadow_set) / min(10, len(primary_set), len(shadow_set)) if primary_set and shadow_set else (1.0 if not primary_set and not shadow_set else 0.0)
            metric = SuggestionMetric(
                endpoint=query.endpoint, query_class="autocomplete", group=query.group,
                query_fingerprint=query.fingerprint, postgres_success=True, typesense_success=True,
                postgres_latency_ms=postgres_latency_ms, typesense_latency_ms=(time.perf_counter() - started) * 1000,
                postgres_total=len(primary_suggestions), typesense_total=len(suggestions), page_size=query.limit,
                exact_uuid_intersection=None, missing_from_typesense=len(primary_set - shadow_set),
                extra_in_typesense=len(shadow_set - primary_set), top_k_overlap=overlap,
                explicit_sort_parity=None, field_mismatch_count=0, error_classification=SHADOW_OK,
                severity=None, slow_outlier=(time.perf_counter() - started) * 1000 > 500,
                timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            )
        except Exception as exc:
            metric = SuggestionMetric(
                endpoint=query.endpoint, query_class="autocomplete", group=query.group,
                query_fingerprint=query.fingerprint, postgres_success=True, typesense_success=False,
                postgres_latency_ms=postgres_latency_ms, typesense_latency_ms=None,
                postgres_total=len(primary_suggestions), typesense_total=None, page_size=query.limit,
                exact_uuid_intersection=None, missing_from_typesense=None, extra_in_typesense=None,
                top_k_overlap=None, explicit_sort_parity=None, field_mismatch_count=None,
                error_classification=_classify_shadow_error(exc), severity=None,
                timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            )
        await asyncio.to_thread(_write_metric, config, metric)  # type: ignore[arg-type]
        return metric

    return tuple(await asyncio.gather(*(one(query) for query in queries)))


_SHADOW_TASKS: set[asyncio.Task[Any]] = set()
_SHADOW_TASKS_LOCK = threading.Lock()


def schedule_shadow_comparison(*args: Any, **kwargs: Any) -> bool:
    """Queue comparison without extending API response latency."""

    config = kwargs.get("config") or get_shadow_config()
    if not config.enabled or config.sample_rate <= 0:
        return False
    try:
        task = asyncio.create_task(run_shadow_comparison(*args, **kwargs))
    except RuntimeError:
        return False
    with _SHADOW_TASKS_LOCK:
        _SHADOW_TASKS.add(task)
    task.add_done_callback(_discard_shadow_task)
    return True


def schedule_shadow_autocomplete(*args: Any, **kwargs: Any) -> bool:
    config = kwargs.get("config") or get_shadow_config()
    if not config.enabled or config.sample_rate <= 0:
        return False
    try:
        task = asyncio.create_task(run_shadow_autocomplete(*args, **kwargs))
    except RuntimeError:
        return False
    with _SHADOW_TASKS_LOCK:
        _SHADOW_TASKS.add(task)
    task.add_done_callback(_discard_shadow_task)
    return True


def _discard_shadow_task(task: asyncio.Task[Any]) -> None:
    with _SHADOW_TASKS_LOCK:
        _SHADOW_TASKS.discard(task)
    try:
        task.result()
    except Exception:
        logger.exception("typesense shadow task failed outside isolated comparison")


def report_summary(metrics: Iterable[ParityMetric]) -> dict[str, Any]:
    rows = list(metrics)
    by_class: dict[str, dict[str, Any]] = {}
    for metric in rows:
        bucket = by_class.setdefault(metric.query_class, {"comparisons": 0, "infra_errors": 0, "not_comparable": 0, "mismatches": 0, "population_differences": 0, "contract_failures": 0, "ranking_differences": 0, "performance_outliers": 0, "p0": 0, "p1": 0, "p2": 0, "p3": 0, "top_k_overlap": [], "postgres_latency_ms": [], "typesense_latency_ms": []})
        bucket["comparisons"] += 1
        if metric.error_classification == SHADOW_INFRA_ERROR:
            bucket["infra_errors"] += 1
        if metric.error_classification == SHADOW_PARITY_NOT_COMPARABLE:
            bucket["not_comparable"] += 1
        if metric.error_classification == SHADOW_PARITY_MISMATCH:
            bucket["mismatches"] += 1
        if metric.error_classification == LEGACY_POPULATION_DIFFERENCE:
            bucket["population_differences"] += 1
        if metric.error_classification == QUERY_CONTRACT_FAILURE:
            bucket["contract_failures"] += 1
        if metric.error_classification == RANKING_DIFFERENCE:
            bucket["ranking_differences"] += 1
        if metric.error_classification == PERFORMANCE_OUTLIER:
            bucket["performance_outliers"] += 1
        if metric.severity:
            bucket[metric.severity.lower()] += 1
        if metric.top_k_overlap is not None:
            bucket["top_k_overlap"].append(metric.top_k_overlap)
        if metric.postgres_latency_ms is not None:
            bucket["postgres_latency_ms"].append(metric.postgres_latency_ms)
        if metric.typesense_latency_ms is not None:
            bucket["typesense_latency_ms"].append(metric.typesense_latency_ms)
    for bucket in by_class.values():
        for name in ("top_k_overlap", "postgres_latency_ms", "typesense_latency_ms"):
            values = sorted(bucket[name])
            bucket[name] = {
                "count": len(values),
                "p50": values[(len(values) - 1) // 2] if values else None,
                "p95": values[min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))] if values else None,
            }
    return {
        "total_comparisons": len(rows),
        "infrastructure_errors": sum(item.error_classification == SHADOW_INFRA_ERROR for item in rows),
        "legacy_population_differences": sum(item.error_classification == LEGACY_POPULATION_DIFFERENCE for item in rows),
        "query_contract_failures": sum(item.error_classification == QUERY_CONTRACT_FAILURE for item in rows),
        "ranking_differences": sum(item.error_classification == RANKING_DIFFERENCE for item in rows),
        "performance_outliers": sum(item.error_classification == PERFORMANCE_OUTLIER for item in rows),
        "not_comparable": sum(item.error_classification == SHADOW_PARITY_NOT_COMPARABLE for item in rows),
        "identity_not_comparable": sum(item.error_classification == IDENTITY_NOT_COMPARABLE for item in rows),
        "identity_collision_groups": sum(item.identity_collision_groups for item in rows),
        "identity_strategies": dict(Counter(item.identity_strategy for item in rows)),
        "parity_mismatches": sum(item.error_classification == SHADOW_PARITY_MISMATCH for item in rows),
        "p0_mismatches": sum(item.severity == SEVERITY_P0 for item in rows),
        "p1_mismatches": sum(item.severity == SEVERITY_P1 for item in rows),
        "p2_differences": sum(item.severity == SEVERITY_P2 for item in rows),
        "p3_issues": sum(item.severity == SEVERITY_P3 for item in rows),
        "slow_typesense_queries": sum(item.slow_outlier for item in rows),
        "by_query_class": by_class,
    }
