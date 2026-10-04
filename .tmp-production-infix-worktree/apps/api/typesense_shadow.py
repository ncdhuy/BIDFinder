"""Phase 4A Typesense shadow-read adapter and parity primitives.

This module owns only procurement shadow reads. Postgres remains the response
authority; callers schedule these operations after the primary response has
been assembled.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import CancelledError as FutureCancelledError, ThreadPoolExecutor
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
import unicodedata
from typing import Any, Awaitable, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from typesense_display import (
    NormalizationError,
    normalize_bidder_count,
    normalize_location,
    normalize_year,
)
from typesense_contract import (
    PUBLIC_GROUPS,
    canonical_field_for,
    get_group_contract,
    normalize_group,
    public_group,
    resolve_serving_generation,
    source_selector,
)


logger = logging.getLogger("bidfinder.typesense_shadow")

# A dashboard query can scan every matching document. Share this limit across
# requests so repeated clicks cannot create an unbounded number of page pools.
_dashboard_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dashboard-analytics")

SHADOW_INFRA_ERROR = "SHADOW_INFRA_ERROR"
QUERY_CONTRACT_FAILURE = "QUERY_CONTRACT_FAILURE"
LEGACY_POPULATION_DIFFERENCE = "LEGACY_POPULATION_DIFFERENCE"
RANKING_DIFFERENCE = "RANKING_DIFFERENCE"
PERFORMANCE_OUTLIER = "PERFORMANCE_OUTLIER"
SHADOW_PARITY_MISMATCH = "SHADOW_PARITY_MISMATCH"
SHADOW_PARITY_NOT_COMPARABLE = "SHADOW_PARITY_NOT_COMPARABLE"
IDENTITY_NOT_COMPARABLE = "IDENTITY_NOT_COMPARABLE"
TYPESENSE_MAX_HITS_PER_PAGE = 250
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
    cross_group_search: bool = False
    cross_group_search_fields: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    structured_filters: Mapping[str, Any] = field(default_factory=dict)
    ranges: Mapping[str, Any] = field(default_factory=dict)
    date_ranges: Mapping[str, Any] = field(default_factory=dict)
    exact_identifiers: Mapping[str, Any] = field(default_factory=dict)
    sort: tuple[CanonicalSort, ...] = ()
    limit: int = 1000
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
            "cross_group_search": self.cross_group_search,
            "cross_group_search_fields": list(self.cross_group_search_fields),
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
    limit: int = 1000,
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
    cross_group_search: bool = False,
    cross_group_search_fields: Sequence[str] | None = None,
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
    normalized_cross_group_fields = tuple(dict.fromkeys(
        str(item).strip() for item in (cross_group_search_fields or ()) if str(item).strip()
    ))
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
        cross_group_search=bool(cross_group_search),
        cross_group_search_fields=normalized_cross_group_fields,
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


def _iso_date_range_clauses(start_value: Any, end_value: Any, field_name: str = "partition_date") -> tuple[str, ...]:
    """Build exact/prefix clauses for ISO date strings.

    Typesense range operators are numeric-oriented. The serving schema stores
    date fields as ISO ``YYYY-MM-DD`` strings (or ISO timestamp prefixes), so
    bounded ranges can be represented losslessly as exact dates plus complete
    month/year prefixes.
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
            clauses.append(_date_prefix_clause(field_name, f"{cursor.year}*", exact_partition=field_name == "partition_date"))
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
                clauses.append(_date_prefix_clause(field_name, f"{cursor.strftime('%Y-%m')}*", exact_partition=field_name == "partition_date"))
                cursor = next_month
                continue
        clauses.append(_date_prefix_clause(field_name, cursor.isoformat(), exact_partition=field_name == "partition_date"))
        cursor += timedelta(days=1)
    return tuple(clauses)


def _iso_date_range_filter(field_name: str, range_clauses: Sequence[str]) -> str:
    """Compact long ISO prefix ranges before Typesense's filter-op limit."""

    # Typesense counts every OR operand in ``filter_by``.  A list equality
    # filter accepts the same wildcard prefixes while counting as one field
    # operation, which keeps realistic date windows below the default limit.
    if len(range_clauses) <= 8:
        return "(" + " || ".join(range_clauses) + ")"

    prefixes: list[str] = []
    prefix = f"{field_name}:"
    for clause in range_clauses:
        if not clause.startswith(prefix):
            return "(" + " || ".join(range_clauses) + ")"
        value = clause[len(prefix):]
        if value.startswith("="):
            value = value[1:]
        if not value:
            return "(" + " || ".join(range_clauses) + ")"
        prefixes.append(value)
    return f"{field_name}:=[{','.join(prefixes)}]"


def _prefix_clause(field_name: str, value: Any, *, negate: bool = False) -> str:
    escaped = _escape_filter_value(value)
    operator = ":!" if negate else ":"
    if any(character.isspace() for character in escaped):
        return f"{field_name}{operator}`{escaped}`"
    return f"{field_name}{operator}{escaped}*"


def _exact_clause(field_name: str, value: Any) -> str:
    return f"{field_name}:=`{_escape_filter_value(value)}`"


def _raw_filter_values(value: Any) -> list[Any]:
    plain = _plain(value)
    if isinstance(plain, (list, tuple, set)):
        return list(plain)
    if isinstance(plain, Mapping):
        tokens = plain.get("tokens", [])
        if isinstance(tokens, list):
            return [item.get("value") if isinstance(item, Mapping) else item for item in tokens]
    return []


def _fold(value: Any) -> str:
    import unicodedata
    text = str(value if value is not None else "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


_SELECTION_METHOD_ALIASES: dict[str, tuple[str, ...]] = {
    "dau thau rong rai": ("Đấu thầu rộng rãi", "DTRR", "LCNT_DB"),
    "dtrr": ("Đấu thầu rộng rãi", "DTRR", "LCNT_DB"),
    "lcnt_db": ("Đấu thầu rộng rãi", "DTRR", "LCNT_DB"),
    "dau thau han che": ("Đấu thầu hạn chế", "DTHC", "LCNT_HC"),
    "dthc": ("Đấu thầu hạn chế", "DTHC", "LCNT_HC"),
    "lcnt_hc": ("Đấu thầu hạn chế", "DTHC", "LCNT_HC"),
    "chi dinh thau": ("Chỉ định thầu", "CDT"),
    "cdt": ("Chỉ định thầu", "CDT"),
    "chao hang canh tranh": ("Chào hàng cạnh tranh", "CDTRG"),
    "cdtrg": ("Chào hàng cạnh tranh", "CDTRG"),
    "mua sam truc tiep": ("Mua sắm trực tiếp", "MSTT"),
    "mstt": ("Mua sắm trực tiếp", "MSTT"),
    "tu thuc hien": ("Tự thực hiện", "TTH"),
    "tth": ("Tự thực hiện", "TTH"),
}


def _selection_method_filter_values(value: Any) -> list[str]:
    expanded: list[str] = []
    for raw in _raw_filter_values(value):
        text = str(raw or "").strip()
        if not text:
            continue
        aliases = _SELECTION_METHOD_ALIASES.get(_fold(text), (text,))
        for alias in aliases:
            if alias not in expanded:
                expanded.append(alias)
    return expanded


def _location_filter_values(value: Any) -> list[str]:
    terms: list[str] = []
    for raw in _raw_filter_values(value):
        text = str(raw or "").strip()
        if not text:
            continue
        bare = re.sub(r"^(?:tỉnh|thành phố|tp\.?)\s+", "", text, flags=re.IGNORECASE).strip()
        for term in (bare, text):
            if term and term not in terms:
                terms.append(term)
    return terms


def _partial_clause(field_name: str, value: Any) -> str:
    return f"{field_name}:`{_escape_filter_value(value)}`"


def _partial_list_clause(field_name: str, values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    members = [_partial_clause(field_name, value) for value in values if str(value or "").strip()]
    return "(" + " || ".join(members) + ")" if members else None


def _date_prefix_clause(field_name: str, prefix: str, *, exact_partition: bool = False) -> str:
    if exact_partition:
        return f"{field_name}:={prefix}" if prefix.endswith("*") else f"{field_name}:=`{prefix}`"
    # Source timestamp fields are indexed strings, not facet fields. Use the
    # partial string operator so prefix filtering does not require ``:=``.
    return f"{field_name}:{prefix if prefix.endswith('*') else prefix + '*'}"


_DRUG_GROUP_LEGACY_VALUES: dict[str, tuple[str, ...]] = {
    # Keep the same value families as the legacy SQL matcher.  The source
    # columns are not guaranteed to contain only the new canonical codes.
    "BDG": (
        "BDG",
        "BGD",
        "BD",
        "G2",
        "Biệt dược",
        "Biệt dược gốc",
        "Biet duoc",
        "Biet duoc goc",
    ),
    "N1": (
        "N1",
        "N 1",
        "G1N1",
        "G1 N1",
        "G1 Nhóm 1",
        "G1 Nhom 1",
        "Nhóm 1",
        "Nhom 1",
    ),
    "N2": (
        "N2",
        "N 2",
        "G1N2",
        "G1 N2",
        "G1 Nhóm 2",
        "G1 Nhom 2",
        "Nhóm 2",
        "Nhom 2",
    ),
    "N3": (
        "N3",
        "N 3",
        "G1N3",
        "G1 N3",
        "G1 Nhóm 3",
        "G1 Nhom 3",
        "Nhóm 3",
        "Nhom 3",
    ),
    "N4": (
        "N4",
        "N 4",
        "G1N4",
        "G1 N4",
        "G1 Nhóm 4",
        "G1 Nhom 4",
        "Nhóm 4",
        "Nhom 4",
    ),
    "N5": (
        "N5",
        "N 5",
        "G1N5",
        "G1 N5",
        "G1 Nhóm 5",
        "G1 Nhom 5",
        "Nhóm 5",
        "Nhom 5",
    ),
    "UNKNOWN": (
        "UNKNOWN",
        "Không xác định",
        "Khong xac dinh",
        "Chưa xác định được",
        "Chua xac dinh duoc",
    ),
}

# Every user-facing/legacy spelling resolves to the complete legacy value
# family.  This is deliberately broader than the canonical UI labels: old
# rows contain packed forms such as G1N1 and G1 Nhóm 1.
_DRUG_GROUP_ALIASES: dict[str, tuple[str, ...]] = {}
for _canonical, _legacy_values in _DRUG_GROUP_LEGACY_VALUES.items():
    for _alias in (_canonical, *_legacy_values):
        _DRUG_GROUP_ALIASES[_fold(_alias)] = _legacy_values


def _drug_group_filter_values(value: Any) -> list[str]:
    expanded: list[str] = []
    for raw in _raw_filter_values(value):
        text = str(raw or "").strip()
        if not text:
            continue
        aliases = _DRUG_GROUP_ALIASES.get(_fold(text), (text,))
        for alias in aliases:
            if alias not in expanded:
                expanded.append(alias)
    return expanded


def _drug_group_clause(field_name: str, value: Any) -> str | None:
    values = _drug_group_filter_values(value)
    if not values:
        return None
    exact_members = [_exact_clause(field_name, item) for item in values]
    # The legacy matcher used substring matching (ILIKE ``%value%``).  Use
    # Typesense's partial string operator for every legacy spelling so packed
    # or comma-separated source values remain discoverable, not only values
    # that happen to contain whitespace.
    partial_members = [_partial_clause(field_name, item) for item in values]
    members = list(dict.fromkeys(exact_members + partial_members))
    return "(" + " || ".join(members) + ")"


def _token_clauses(fields: Sequence[str], token_filter: Any) -> str | None:
    plain = _plain(token_filter)
    tokens = plain.get("tokens", []) if isinstance(plain, Mapping) else []
    groups = plain.get("groups", []) if isinstance(plain, Mapping) else []
    and_parts: list[str] = []
    or_parts: list[str] = []
    not_parts: list[str] = []
    for item in tokens:
        if not isinstance(item, Mapping):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        positive = " || ".join(_prefix_clause(name, value) for name in fields)
        op = str(item.get("op", "OR")).upper()
        if op == "NOT":
            not_parts.append(" && ".join(_prefix_clause(name, value, negate=True) for name in fields))
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

    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            alternatives = []
            for raw_value in group.get("alternatives", []):
                value = str(raw_value or "").strip()
                if not value:
                    continue
                positive = " || ".join(_prefix_clause(name, value) for name in fields)
                if positive:
                    alternatives.append(positive)
            if alternatives:
                clauses.append(" || ".join(alternatives))

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
        "goodsKeyword": ("item_name", "model_mark", "brand", "technical_specification"),
        "crossGroupProductKeyword": ("item_name", "model_mark", "brand", "technical_specification"),
        "activeIngredient": ("item_name", "technical_specification"), "concentration": ("item_name", "technical_specification"),
        "route": ("item_name", "technical_specification"), "dosageForm": ("item_name", "technical_specification"),
        "specification": ("technical_specification",), "regNo": ("registration_or_import_permit_number",),
        "unit": ("unit",), "manufacturer": ("manufacturer",), "country": ("country_of_origin",),
        "selectionMethod": ("selection_method",), "place": ("location",), "drugGroup": ("item_name", "technical_specification"),
    },
    "medicines": {
        "investor": ("procuring_entity_name",), "approvalDecision": ("decision_number",),
        "winner": ("winning_bidder_name",), "drugName": ("medicine_name",),
        "crossGroupProductKeyword": ("medicine_name", "active_ingredient_or_herbal_component"),
        "activeIngredient": ("active_ingredient_or_herbal_component",), "concentration": ("strength",),
        "route": ("route_of_administration",), "dosageForm": ("dosage_form",), "specification": ("packaging",),
        "regNo": ("marketing_authorization_or_import_permit",), "unit": ("unit",), "manufacturer": ("manufacturer",),
        "country": ("production_country",), "selectionMethod": ("selection_method",), "place": ("location",),
        "drugGroup": ("medicine_group",),
    },
    "traditional_medicine": {
        "investor": ("procuring_entity_name",), "approvalDecision": ("decision_number",),
        "winner": ("winning_bidder_name",), "drugName": ("item_name",),
        "crossGroupProductKeyword": ("item_name",),
        "activeIngredient": ("scientific_name", "item_name"), "concentration": ("item_name",),
        "route": ("processing_method",), "dosageForm": ("processing_method",), "specification": ("packaging",),
        "regNo": ("registration_or_import_permit_number",), "unit": ("unit",), "manufacturer": ("manufacturer",),
        "country": ("production_country",), "selectionMethod": ("selection_method",), "place": ("location",),
        "drugGroup": ("technical_group",),
    },
}

CROSS_GROUP_GOODS_PRODUCT_FIELDS = (
    "item_name", "model_mark", "brand", "technical_specification"
)
CROSS_GROUP_MEDICINE_PRODUCT_FIELDS = (
    "medicine_name", "active_ingredient_or_herbal_component"
)


def _cross_group_product_fields(schema_group: str, source_fields: Sequence[str]) -> tuple[str, ...]:
    """Keep the selected field scoped locally while mapping equivalent products."""

    source = set(source_fields)
    if schema_group == "goods":
        return CROSS_GROUP_GOODS_PRODUCT_FIELDS
    if schema_group == "traditional_medicine":
        return ("item_name",)
    if schema_group == "medicines":
        if "item_name" in source:
            return CROSS_GROUP_MEDICINE_PRODUCT_FIELDS
        selected = tuple(field for field in CROSS_GROUP_MEDICINE_PRODUCT_FIELDS if field in source)
        return selected or CROSS_GROUP_MEDICINE_PRODUCT_FIELDS
    return ()

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


def translate_typesense_query(
    query: ProcurementQuery,
    *,
    serving_generation: str | None = None,
    additional_filter_clauses: Sequence[str] = (),
) -> TypesenseRequestPlan:
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
        if name not in {"partition_date", "result_posted_at", "decision_issued_at"}:
            unsupported.append(name)
            continue
        if not isinstance(raw_value, Mapping):
            unsupported.append(name)
            continue
        range_clauses = _iso_date_range_clauses(raw_value.get("from"), raw_value.get("to"), name)
        if range_clauses:
            clauses.append(_iso_date_range_filter(name, range_clauses))
        else:
            if name == "partition_date":
                for operator, value in ((">=", raw_value.get("from")), ("<=", raw_value.get("to"))):
                    if value is not None:
                        clauses.append(f"partition_date:{operator}{_escape_filter_value(value)}")
            else:
                unsupported.append(name)
                continue
        if name == "partition_date":
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
        if name == "crossGroupProductKeyword" and query.cross_group_search and query.cross_group_search_fields:
            fields = _cross_group_product_fields(schema_group, query.cross_group_search_fields) or fields
        if not fields:
            unsupported.append(name)
            continue
        if name == "selectionMethod":
            clause = _list_clause(fields[0], _selection_method_filter_values(raw_value))
        elif name == "place":
            clause = _partial_list_clause(fields[0], _location_filter_values(raw_value))
        elif name == "drugGroup" and schema_group in {"medicines", "traditional_medicine"}:
            clause = _drug_group_clause(fields[0], raw_value)
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

    requested_search_fields = query.search_fields
    if query.cross_group_search and query.cross_group_search_fields:
        scoped_fields = _cross_group_product_fields(schema_group, query.cross_group_search_fields)
        if scoped_fields:
            requested_search_fields = scoped_fields

    query_fields = list(QUERY_BY[schema_group])
    unsupported_search_fields: list[str] = []
    contract_fields = {
        field["name"]: field for field in get_group_contract(query_group).get("fields", [])
    }
    if requested_search_fields:
        query_fields = []
        for name in requested_search_fields:
            canonical = canonical_field_for(query_group, name) or name
            field_info = contract_fields.get(canonical)
            if field_info and field_info["type"] in {"string", "string[]"}:
                query_fields.append(canonical)
            else:
                unsupported_search_fields.append(name)
        if not query.cross_group_search:
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
    elif query.text or query.search_fields:
        # Keep ordinary search token-friendly: ``par`` must match values such
        # as ``paracetamol`` instead of only a standalone token. Advanced
        # Search sends multi-word field values as quoted phrases so a value
        # like ``máy điện`` cannot degrade into independent ``máy``/``điện``
        # matches. Typesense's phrase search is carried by q, not filter_by.
        has_exact_phrase = bool(re.search(r'"[^"\r\n]*\s+[^"\r\n]*"', query.text or ""))
        if has_exact_phrase:
            params.update({"prefix": "false", "num_typos": 0, "drop_tokens_threshold": 0})
        else:
            params.update({"prefix": "true", "num_typos": 0})
            # Typesense infix uses only the first query word, so apply it only
            # to one-token, explicitly scoped advanced searches.
            if requested_search_fields and not any(char.isspace() for char in (query.text or "").strip()):
                infix_fields = {
                    name for name, info in contract_fields.items() if info.get("infix_search")
                }
                infix_modes = ["always" if field in infix_fields else "off" for field in query_fields]
                if "always" in infix_modes:
                    params["infix"] = ",".join(infix_modes)
    clauses.extend(str(clause) for clause in additional_filter_clauses if str(clause).strip())
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
    serving_generation: str = ""
    sample_rate: float = 0.0
    timeout_seconds: float = 0.5
    host: str = "127.0.0.1"
    port: int = 8108
    protocol: str = "http"
    api_key: str = field(default="", repr=False)
    report_destination: str = ""
    debug_queries: bool = False
    query_retry_seconds: float = 15.0

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
        generation = resolve_serving_generation()
        try:
            timeout = max(0.05, float(os.getenv("BIDFINDER_TYPESENSE_SHADOW_TIMEOUT_SECONDS", "0.5")))
        except ValueError:
            timeout = 0.5
        try:
            port = int(os.getenv("BIDFINDER_TYPESENSE_PORT", "8108"))
        except ValueError:
            port = 8108
        try:
            query_retry_seconds = max(0.0, float(os.getenv("BIDFINDER_TYPESENSE_QUERY_RETRY_SECONDS", "15")))
        except ValueError:
            query_retry_seconds = 15.0
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
            query_retry_seconds=query_retry_seconds,
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
        visible = [_clean_result_document(row) for row in self.hits]
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


def _clean_result_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the canonical display cleanup to legacy/current hit documents.

    The serving collection may still contain documents written with the
    previous numeric schema.  Cleaning at the API boundary keeps the current
    UI stable while new ingestion uses the canonical normalizer as well.
    """

    cleaned = dict(document)
    if cleaned.get("bidder_count") is not None:
        try:
            cleaned["bidder_count"] = normalize_bidder_count(cleaned["bidder_count"])
        except NormalizationError:
            cleaned.pop("bidder_count", None)

    if cleaned.get("production_year") is not None:
        raw_year = cleaned["production_year"]
        if isinstance(raw_year, bool):
            cleaned.pop("production_year", None)
        else:
            if isinstance(raw_year, (int, float)):
                raw_year = str(int(raw_year)) if float(raw_year).is_integer() else str(raw_year)
            if isinstance(raw_year, str):
                normalized_year = normalize_year(raw_year)
                if normalized_year is None:
                    cleaned.pop("production_year", None)
                else:
                    cleaned["production_year"] = normalized_year
            else:
                cleaned.pop("production_year", None)

    if cleaned.get("location") is not None:
        try:
            cleaned["location"] = normalize_location(cleaned["location"])
        except NormalizationError:
            cleaned.pop("location", None)
    return cleaned


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


def _analytics_decimal(value: Any, *, positive_only: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not parsed.is_finite() or (positive_only and parsed <= 0):
        return None
    return parsed


def _analytics_text(value: Any) -> str | None:
    if isinstance(value, (list, tuple, set)):
        value = next((item for item in value if str(item or "").strip()), None)
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _analytics_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [] if value is None else [value]


def _analytics_identity(value: Any) -> str | None:
    text = _analytics_text(value)
    if not text:
        return None
    folded = unicodedata.normalize("NFKD", text).casefold()
    return " ".join(folded.split())


def _analytics_add_label_count(counts: dict[str, int], label: str) -> None:
    counts[label] = counts.get(label, 0) + 1


def _analytics_most_common_label(counts: Mapping[str, int]) -> str | None:
    return min(counts, key=lambda label: (-counts[label], label.casefold(), label), default=None)


def _analytics_row_value(document: Mapping[str, Any]) -> Decimal:
    explicit_total = _analytics_decimal(document.get("total_value"), positive_only=True)
    if explicit_total is None:
        explicit_total = _analytics_decimal(document.get("winning_total_value"), positive_only=True)
    if explicit_total is not None:
        return explicit_total
    quantity = _analytics_decimal(document.get("quantity"), positive_only=True)
    unit_price = _analytics_decimal(document.get("winning_unit_price"), positive_only=True)
    return quantity * unit_price if quantity is not None and unit_price is not None else Decimal(0)


def _analytics_package_key(group: str, document: Mapping[str, Any]) -> str:
    package_code = _analytics_identity(document.get("bid_invitation_code"))
    if package_code:
        return f"package:{package_code}"
    decision = _analytics_identity(document.get("decision_number"))
    if decision:
        return f"{group}:decision:{decision}"
    return f"{group}:row:{_analytics_text(document.get('id')) or id(document)}"


def cluster_dashboard_price_levels(raw_prices: Iterable[Any]) -> list[list[Decimal]]:
    """Cluster nearby positive prices with a bounded, scale-relative tolerance."""
    prices = sorted({
        price for raw_price in raw_prices
        if (price := _analytics_decimal(raw_price, positive_only=True)) is not None
    })
    if len(prices) < 2:
        return [[price] for price in prices]

    gaps = sorted(right.ln() - left.ln() for left, right in zip(prices, prices[1:]))
    middle = len(gaps) // 2
    threshold = gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2
    threshold = max(Decimal("1.01").ln(), min(Decimal("1.05").ln(), threshold * Decimal("1.25")))
    max_span = Decimal("1.05")

    clusters: list[list[Decimal]] = [[prices[0]]]
    for price in prices[1:]:
        current = clusters[-1]
        close_enough = price.ln() - current[-1].ln() <= threshold
        bounded_span = price / current[0] <= max_span
        if close_enough and bounded_span:
            current.append(price)
        else:
            clusters.append([price])
    return clusters


def _dashboard_median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def build_dashboard_bidder_price_bands(
    observations: Sequence[Mapping[str, Any]],
    *,
    selected_product: Any = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Rank bidders by distinct wins in their most frequent comparable price band."""
    selected_product_key = _analytics_identity(selected_product)
    valid: list[dict[str, Any]] = []
    for observation in observations:
        price = _analytics_decimal(observation.get("unit_price"), positive_only=True)
        bidder_id_key = _analytics_identity(observation.get("bidder_key"))
        bidder_name = _analytics_text(observation.get("bidder_name")) or bidder_id_key
        bidder_key = _analytics_identity(bidder_name) or bidder_id_key
        if price is None or not bidder_key:
            continue
        product_key = _analytics_identity(observation.get("product_key") or observation.get("product"))
        if selected_product_key and product_key != selected_product_key:
            continue
        valid.append({
            **observation,
            "unit_price": price,
            "bidder_key": bidder_key,
            "product_key": product_key,
            "unit_key": _analytics_identity(observation.get("unit_key") or observation.get("unit")) or "",
            "package_key": str(observation.get("package_key") or observation.get("record_key") or ""),
            "record_key": str(observation.get("record_key") or observation.get("package_key") or ""),
            "awarded_value": _analytics_decimal(observation.get("awarded_value")) or Decimal(0),
            "bidder_name": bidder_name or bidder_key,
            "unit": _analytics_text(observation.get("unit")),
        })

    if selected_product_key:
        valid = [item for item in valid if item["product_key"] == selected_product_key]

    bidder_name_counts: dict[str, dict[str, int]] = {}
    for item in valid:
        counts = bidder_name_counts.setdefault(item["bidder_key"], {})
        _analytics_add_label_count(counts, item["bidder_name"])

    by_context_bidder: dict[tuple[str | None, str, str], list[dict[str, Any]]] = {}
    for item in valid:
        context = (item["product_key"], item["unit_key"], item["bidder_key"])
        by_context_bidder.setdefault(context, []).append(item)

    best_by_bidder: dict[str, dict[str, Any]] = {}
    for (product_key, unit_key, bidder_key), rows in by_context_bidder.items():
        unique_records: dict[str, dict[str, Any]] = {}
        for row in rows:
            unique_records.setdefault(row["record_key"], row)
        prices = [row["unit_price"] for row in unique_records.values()]
        bidder_name = _analytics_most_common_label(bidder_name_counts.get(bidder_key, {})) or bidder_key
        unit_counts: dict[str, int] = {}
        for row in unique_records.values():
            if row["unit"]:
                _analytics_add_label_count(unit_counts, row["unit"])
        unit = _analytics_most_common_label(unit_counts)
        records_by_price: dict[Decimal, list[dict[str, Any]]] = {}
        for row in unique_records.values():
            records_by_price.setdefault(row["unit_price"], []).append(row)

        for cluster in cluster_dashboard_price_levels(prices):
            package_prices: dict[str, set[Decimal]] = {}
            band_value = Decimal(0)
            packages: set[str] = set()
            for price in cluster:
                for row in records_by_price[price]:
                    package_key = row["package_key"]
                    packages.add(package_key)
                    package_prices.setdefault(package_key, set()).add(price)
                    band_value += row["awarded_value"]
            if not packages:
                continue
            package_observed_prices = [_dashboard_median(tuple(values)) for values in package_prices.values()]
            band = {
                "bidder_key": bidder_key,
                "bidder_name": bidder_name,
                "price_min": _analytics_number(cluster[0]),
                "price_max": _analytics_number(cluster[-1]),
                "median_price": _analytics_number(_dashboard_median(package_observed_prices)),
                "distinct_win_count": len(packages),
                "corresponding_awarded_value": _analytics_number(band_value),
                "unit": unit,
                "_product_key": product_key or "",
                "_unit_key": unit_key,
            }
            current = best_by_bidder.get(bidder_key)
            band_order = (
                -band["distinct_win_count"],
                -Decimal(str(band["corresponding_awarded_value"])),
                band["_product_key"], band["_unit_key"], Decimal(str(band["price_min"])),
            )
            if current is None or band_order < current["_order"]:
                band["_order"] = band_order
                best_by_bidder[bidder_key] = band

    ranked = sorted(
        best_by_bidder.values(),
        key=lambda band: (
            -band["distinct_win_count"],
            -Decimal(str(band["corresponding_awarded_value"])),
            band["bidder_name"].casefold(),
            band["bidder_key"],
        ),
    )[:max(0, limit)]
    for band in ranked:
        band.pop("_order", None)
        band.pop("_product_key", None)
        band.pop("_unit_key", None)
        band.pop("bidder_key", None)
    return {"items": ranked}


def _analytics_province(value: Any) -> str | None:
    try:
        normalized = normalize_location(value) or ""
    except (NormalizationError, TypeError, ValueError):
        normalized = _analytics_text(value) or ""
    parts = [part.strip() for part in re.split(r"[;,]", normalized) if part.strip()]
    province_prefix = re.compile(r"^(?:tỉnh|thành phố|tp\.?|city)\s+", re.IGNORECASE)
    for part in parts:
        if province_prefix.match(part):
            return province_prefix.sub("", part).strip() or None
    return parts[-1] if parts else None


def build_dashboard_selection_clauses(group: str, selection: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Translate temporary dashboard selections into safe server-side filters."""
    selection = selection or {}
    schema_group = normalize_group(group)
    product_field = {"goods": "item_name", "medicines": "medicine_name", "traditional_medicine": "item_name"}[schema_group]
    clauses: list[str] = []
    product = _analytics_text(selection.get("product"))
    province = _analytics_text(selection.get("province"))
    if product:
        clauses.append(_exact_clause(product_field, product))
    if province:
        clauses.append(_partial_clause("location", province))
    return tuple(clauses)


def build_dashboard_column_filter_clauses(group: str, column_filters: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Apply table-scoped filters to analytics when they are part of UI state."""
    if not isinstance(column_filters, Mapping):
        return ()
    public = public_group(group)
    contract = {field["name"]: field for field in get_group_contract(public).get("fields", [])}
    clauses: list[str] = []
    for raw_name, raw_rule in column_filters.items():
        field_name = canonical_field_for(public, raw_name) or str(raw_name)
        field_info = contract.get(field_name)
        if not field_info or not field_info.get("filterable"):
            raise TypesenseShadowError(
                f"dashboard cannot apply table filter field: {raw_name}",
                QUERY_CONTRACT_FAILURE,
            )
        values = raw_rule if isinstance(raw_rule, list) else raw_rule.get("values") if isinstance(raw_rule, Mapping) else None
        if values:
            typed_clause = _typed_list_clause(field_name, values, field_info["type"])
            if typed_clause:
                clauses.append(typed_clause)
        text_rule = raw_rule.get("text") if isinstance(raw_rule, Mapping) and "text" in raw_rule else (
            raw_rule if isinstance(raw_rule, Mapping) and raw_rule.get("operator") else None
        )
        if not isinstance(text_rule, Mapping):
            continue
        def text_clause(rule: Mapping[str, Any]) -> str | None:
            operator = str(rule.get("operator") or "equals")
            value = str(rule.get("value") or "").strip()
            if not value:
                return None
            escaped = _escape_filter_value(value)
            if operator == "equals":
                return _typed_exact_clause(field_name, value, field_info["type"])
            if operator == "notEquals":
                return f"{field_name}:!={escaped}"
            if operator == "beginsWith":
                return f"{field_name}:{escaped}*"
            if operator == "endsWith":
                return f"{field_name}:*{escaped}"
            if operator == "contains":
                return f"{field_name}:*{escaped}*"
            if operator == "notContains":
                return f"{field_name}:!*{escaped}*"
            raise TypesenseShadowError(
                f"dashboard cannot apply table filter operator: {operator}",
                QUERY_CONTRACT_FAILURE,
            )

        text_clauses = [text_clause(text_rule)]
        if text_rule.get("custom") and str(text_rule.get("secondValue") or "").strip():
            text_clauses.append(text_clause({
                "operator": text_rule.get("secondOperator") or "equals",
                "value": text_rule.get("secondValue"),
            }))
        text_clauses = [item for item in text_clauses if item]
        if len(text_clauses) > 1 and text_rule.get("logic") == "or":
            clauses.append("(" + " || ".join(text_clauses) + ")")
        else:
            clauses.extend(text_clauses)
    return tuple(clauses)


def filter_dashboard_columns(
    group: str,
    documents: Sequence[Mapping[str, Any]],
    column_filters: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    """Apply the table's bounded-set filters to the complete dashboard universe."""
    if not column_filters:
        return list(documents)
    public = public_group(group)
    contract = {field["name"] for field in get_group_contract(public).get("fields", [])}

    def normalize(value: Any) -> str:
        return "" if value is None else str(value).strip().lower()

    def condition(operator: str, query: Any):
        pattern = re.escape(normalize(query)).replace(r"\*", ".*").replace(r"\?", ".")
        source = {
            "equals": f"^{pattern}$", "notEquals": f"^{pattern}$",
            "beginsWith": f"^{pattern}", "endsWith": f"{pattern}$",
            "contains": pattern, "notContains": pattern,
        }.get(operator)
        if source is None:
            raise TypesenseShadowError(f"dashboard cannot apply table filter operator: {operator}", QUERY_CONTRACT_FAILURE)
        return re.compile(source), operator in {"notEquals", "notContains"}

    rules = []
    for raw_name, raw_rule in column_filters.items():
        field_name = canonical_field_for(public, raw_name) or str(raw_name)
        if field_name not in contract:
            raise TypesenseShadowError(f"dashboard cannot apply table filter field: {raw_name}", QUERY_CONTRACT_FAILURE)
        values = raw_rule if isinstance(raw_rule, list) else raw_rule.get("values") if isinstance(raw_rule, Mapping) else None
        text_rule = raw_rule.get("text") if isinstance(raw_rule, Mapping) and "text" in raw_rule else (
            raw_rule if isinstance(raw_rule, Mapping) and raw_rule.get("operator") else None
        )
        first = condition(str(text_rule.get("operator") or "equals"), text_rule.get("value") or "") if isinstance(text_rule, Mapping) else None
        second = condition(str(text_rule.get("secondOperator") or "equals"), text_rule.get("secondValue")) if (
            isinstance(text_rule, Mapping) and text_rule.get("custom") and str(text_rule.get("secondValue") or "").strip()
        ) else None
        rules.append((field_name, {normalize(item) for item in values} if isinstance(values, list) else None, first, second, text_rule.get("logic") if isinstance(text_rule, Mapping) else None))

    def text_matches(value: str, compiled: tuple[Any, bool]) -> bool:
        pattern, negate = compiled
        matched = pattern.search(value) is not None
        return not matched if negate else matched

    def rule_matches(document: Mapping[str, Any], rule: tuple[Any, Any, Any, Any, Any]) -> bool:
        field_name, values, first, second, logic = rule
        raw_values = document.get(field_name)
        candidates = [normalize(value) for value in raw_values] if isinstance(raw_values, list) else [normalize(raw_values)]
        if values is not None and not any(value in values for value in candidates):
            return False
        if first is None:
            return True
        first_match = any(text_matches(value, first) for value in candidates)
        if second is None:
            return first_match
        second_match = any(text_matches(value, second) for value in candidates)
        return first_match or second_match if logic == "or" else first_match and second_match

    return [document for document in documents if all(rule_matches(document, rule) for rule in rules)]


def _analytics_date(value: Any) -> date | None:
    text = _analytics_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%d/%m/%Y").date()
        except ValueError:
            return None


def _analytics_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)




def aggregate_dashboard_documents(
    documents_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    selected_product: Any = None,
    selected_bidder: Any = None,
    selected_investor: Any = None,
) -> dict[str, Any]:
    """Aggregate the dashboard scan window, never a paginated UI page."""
    selected_bidder_key = _analytics_identity(selected_bidder)
    if selected_bidder_key:
        # Bidder fields are not Typesense-filterable; filter the already-fetched full projection.
        documents_by_group = {
            group: [
                document for document in documents
                if any(
                    _analytics_identity(value) == selected_bidder_key
                    for field in ("winning_bidder_name", "winning_bidder_id")
                    for value in _analytics_values(document.get(field))
                )
            ]
            for group, documents in documents_by_group.items()
        }

    selected_investor_key = _analytics_identity(selected_investor)
    if selected_investor_key:
        # Match normalized display names after retrieval so capitalization variants
        # of the same procuring entity remain in the same cross-filter result.
        documents_by_group = {
            group: [
                document for document in documents
                if any(
                    _analytics_identity(value) == selected_investor_key
                    for value in _analytics_values(document.get("procuring_entity_name"))
                )
            ]
            for group, documents in documents_by_group.items()
        }

    product_fields = {"goods": "item_name", "medicines": "medicine_name", "traditional_medicine": "item_name"}
    packages: dict[str, dict[str, Any]] = {}
    products: dict[str, dict[str, Any]] = {}
    investors: dict[str, dict[str, Any]] = {}
    provinces: dict[str, dict[str, Any]] = {}
    bidders: set[str] = set()
    bidder_price_observations: list[dict[str, Any]] = []
    dated_values: list[tuple[date, Decimal]] = []
    seen_documents: set[tuple[str, str]] = set()
    matched_observations = 0

    for group, documents in documents_by_group.items():
        product_field = product_fields.get(group, "item_name")
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            document_id = _analytics_text(document.get("id"))
            if document_id and (group, document_id) in seen_documents:
                continue
            if document_id:
                seen_documents.add((group, document_id))
            matched_observations += 1
            package_key = _analytics_package_key(group, document)
            package = packages.setdefault(package_key, {"value": Decimal(0), "investor_key": None})
            row_value = _analytics_row_value(document)
            package["value"] += row_value

            product_name = _analytics_text(document.get(product_field))
            if product_name:
                product_key = _analytics_identity(product_name)
                entry = products.setdefault(product_key, {"name": product_name, "labels": {}, "packages": set(), "group": public_group(group)})
                _analytics_add_label_count(entry["labels"], product_name)
                entry["name"] = _analytics_most_common_label(entry["labels"]) or product_name
                entry["packages"].add(package_key)

            bidder_identity_values = _analytics_values(document.get("winning_bidder_id")) or _analytics_values(document.get("winning_bidder_name"))
            bidder_display_values = _analytics_values(document.get("winning_bidder_name")) or bidder_identity_values
            valid_unit_price = _analytics_decimal(document.get("winning_unit_price"), positive_only=True)
            unit_name = _analytics_text(document.get("unit"))
            for index, raw_bidder in enumerate(bidder_identity_values):
                bidder_key = _analytics_identity(raw_bidder)
                if not bidder_key:
                    continue
                bidder_label = _analytics_text(bidder_display_values[index] if index < len(bidder_display_values) else raw_bidder) or bidder_key
                bidders.add(bidder_key)
                if valid_unit_price is None:
                    continue
                bidder_price_observations.append({
                    "bidder_key": bidder_key,
                    "bidder_name": bidder_label,
                    "product_key": _analytics_identity(product_name),
                    "product": product_name,
                    "unit_key": _analytics_identity(unit_name),
                    "unit": unit_name,
                    "unit_price": valid_unit_price,
                    "awarded_value": row_value,
                    "package_key": package_key,
                    "record_key": f"{group}:{document_id}" if document_id else f"{group}:object:{id(document)}",
                })

            investor_name = _analytics_text(document.get("procuring_entity_name"))
            investor_id = _analytics_identity(document.get("procuring_entity_id"))
            # Name is the stable display contract across collections; use ID only
            # when a source row has no investor name at all.
            investor_key = _analytics_identity(investor_name) or investor_id
            if investor_key:
                package["investor_key"] = package["investor_key"] or investor_key
                investor = investors.setdefault(investor_key, {"name": investor_name or investor_key, "labels": {}, "packages": set()})
                _analytics_add_label_count(investor["labels"], investor_name or investor_key)
                investor["name"] = _analytics_most_common_label(investor["labels"]) or investor_key
                investor["packages"].add(package_key)

            province = _analytics_province(document.get("location"))
            if province and row_value > 0:
                entry = provinces.setdefault(province, {"name": province, "value": Decimal(0), "packages": set()})
                entry["value"] += row_value
                entry["packages"].add(package_key)

            if row_value > 0:
                result_date = _analytics_date(document.get("decision_issued_at"))
                if result_date:
                    dated_values.append((result_date, row_value))

    total_value = sum((package["value"] for package in packages.values()), Decimal(0))
    top_investors = []
    for key, investor in investors.items():
        total = sum((packages[package_key]["value"] for package_key in investor["packages"]), Decimal(0))
        top_investors.append({"name": investor["name"], "package_count": len(investor["packages"]), "total_awarded_value": _analytics_number(total), "key": key})
    top_investors.sort(key=lambda item: (-float(item["total_awarded_value"]), item["name"].casefold()))

    product_rows = [
        {"name": entry["name"], "count": len(entry["packages"]), "group": entry["group"]}
        for entry in products.values()
    ]
    product_rows.sort(key=lambda item: (-item["count"], item["name"].casefold()))

    geography = [
        {"province": entry["name"], "total_awarded_value": _analytics_number(entry["value"]), "package_count": len(entry["packages"])}
        for entry in provinces.values()
    ]
    geography.sort(key=lambda item: (-float(item["total_awarded_value"]), item["province"].casefold()))

    timeline = {"grain": None, "points": [], "series": {"month": [], "quarter": [], "year": []}}
    if dated_values:
        first, last = min(item[0] for item in dated_values), max(item[0] for item in dated_values)
        span_days = (last - first).days
        grain = "day" if span_days <= 90 else "month" if span_days <= 730 else "quarter" if span_days <= 1825 else "year"
        buckets_by_grain: dict[str, dict[str, Decimal]] = {key: {} for key in ("day", "month", "quarter", "year")}
        for current_date, value in dated_values:
            periods = {
                "day": current_date.isoformat(),
                "month": current_date.strftime("%Y-%m"),
                "quarter": f"{current_date.year}-Q{((current_date.month - 1) // 3) + 1}",
                "year": str(current_date.year),
            }
            for bucket_grain, period in periods.items():
                buckets = buckets_by_grain[bucket_grain]
                buckets[period] = buckets.get(period, Decimal(0)) + value
        series = {
            bucket_grain: [
                {"period": period, "total_awarded_value": _analytics_number(value)}
                for period, value in sorted(buckets.items())
            ]
            for bucket_grain, buckets in buckets_by_grain.items()
        }
        timeline = {
            "grain": grain,
            "points": series[grain],
            "series": {key: series[key] for key in ("month", "quarter", "year")},
        }

    return {
        "summary": {
            "total_awarded_value": _analytics_number(total_value),
            "package_count": len(packages),
            "bidder_count": len(bidders),
            "investor_count": len(investors),
        },
        "geography": geography,
        "top_products": product_rows[:10],
        "timeline": timeline,
        "bidder_price_band_analysis": build_dashboard_bidder_price_bands(
            bidder_price_observations,
            selected_product=selected_product,
        ),
        "top_investors": top_investors[:5],
        "meta": {"complete": True, "matched_observations": matched_observations, "groups": sorted(public_group(group) for group in documents_by_group)},
    }


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
        window_start = max(0, (query.page - 1) * query.limit)
        typesense_page = window_start // TYPESENSE_MAX_HITS_PER_PAGE + 1
        skip_in_page = window_start % TYPESENSE_MAX_HITS_PER_PAGE
        documents: list[Mapping[str, Any]] = []
        total: int | None = None

        while len(documents) < query.limit:
            batch_limit = min(
                TYPESENSE_MAX_HITS_PER_PAGE,
                skip_in_page + query.limit - len(documents),
            )
            request_params = dict(plan.params)
            request_params.update({"page": typesense_page, "per_page": batch_limit})
            params = urlencode(request_params, doseq=True)
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
            if total is None:
                total = int(payload["found"])
            hits = payload.get("hits", [])
            if not isinstance(hits, list):
                raise TypesenseShadowError("Typesense returned malformed hits")
            batch_documents: list[Mapping[str, Any]] = []
            for hit in hits:
                if not isinstance(hit, Mapping) or not isinstance(hit.get("document"), Mapping):
                    raise TypesenseShadowError("Typesense returned malformed hit")
                document = dict(hit["document"])
                if not isinstance(document.get("id"), str) or not document["id"]:
                    raise TypesenseShadowError("Typesense document has no identity")
                batch_documents.append(document)
            documents.extend(batch_documents[skip_in_page:skip_in_page + query.limit - len(documents)])
            if len(documents) >= query.limit or window_start + len(documents) >= total or len(batch_documents) < batch_limit:
                break
            typesense_page += 1
            skip_in_page = 0
        return TypesenseSearchResult(
            group=public_group(query.group),
            total=int(total or 0),
            hits=tuple(documents),
            latency_ms=(time.perf_counter() - started) * 1000,
            page=query.page,
            per_page=query.limit,
        )

    def _request_all(
        self,
        query: ProcurementQuery,
        *,
        additional_filter_clauses: Sequence[str] = (),
        include_fields: Sequence[str] = (),
        stop_event: threading.Event | None = None,
        max_documents: int | None = None,
        with_found: bool = False,
    ) -> list[Mapping[str, Any]] | tuple[int, list[Mapping[str, Any]]]:
        """Fetch a bounded analytics window and retain the full match count."""
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")
        plan = translate_typesense_query(
            query,
            serving_generation=self.config.serving_generation,
            additional_filter_clauses=additional_filter_clauses,
        )
        if plan.unsupported_filters or plan.unsupported_sorts:
            unsupported = ", ".join((*plan.unsupported_filters, *plan.unsupported_sorts))
            raise TypesenseShadowError(f"unsupported search contract field(s): {unsupported}", QUERY_CONTRACT_FAILURE)

        request_params = dict(plan.params)
        if include_fields:
            request_params["include_fields"] = ",".join(dict.fromkeys(include_fields))
        per_page = TYPESENSE_MAX_HITS_PER_PAGE

        def fetch_page(page: int) -> tuple[int, list[Mapping[str, Any]]]:
            if stop_event is not None and stop_event.is_set():
                raise FutureCancelledError()
            page_params = {**request_params, "page": page, "per_page": per_page}
            url = f"{self.config.base_url}/collections/{quote(plan.collection, safe='')}/documents/search?{urlencode(page_params, doseq=True)}"
            request = Request(url, method="GET", headers={
                "Accept": "application/json",
                "X-TYPESENSE-API-KEY": self.config.api_key,
            })
            try:
                with self._opener(request, timeout=max(self.config.timeout_seconds, 2.0)) as response:
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
            if not isinstance(payload, Mapping) or not isinstance(payload.get("found"), int) or payload["found"] < 0:
                raise TypesenseShadowError("Typesense returned malformed analytics metadata")
            hits = payload.get("hits", [])
            if not isinstance(hits, list):
                raise TypesenseShadowError("Typesense returned malformed analytics hits")
            page_documents: list[Mapping[str, Any]] = []
            for hit in hits:
                if not isinstance(hit, Mapping) or not isinstance(hit.get("document"), Mapping):
                    raise TypesenseShadowError("Typesense returned malformed analytics hit")
                document = dict(hit["document"])
                if not isinstance(document.get("id"), str) or not document["id"]:
                    raise TypesenseShadowError("Typesense analytics document has no identity")
                page_documents.append(document)
            return int(payload["found"]), page_documents

        found, documents = fetch_page(1)
        target = found if max_documents is None else min(found, max(0, max_documents))
        documents = documents[:target]
        last_page = (target + per_page - 1) // per_page
        if not documents or last_page <= 1:
            return (found, documents) if with_found else documents

        # The first response reveals the total. Fetch the remaining bounded pages
        # concurrently while map() keeps document ordering deterministic.
        with ThreadPoolExecutor(max_workers=min(4, last_page - 1)) as executor:
            for first_page in range(2, last_page + 1, 4):
                if stop_event is not None and stop_event.is_set():
                    raise FutureCancelledError()
                for _page_found, page_documents in executor.map(
                    fetch_page, range(first_page, min(first_page + 4, last_page + 1))
                ):
                    documents.extend(page_documents[:max(0, target - len(documents))])
        return (found, documents) if with_found else documents

    async def analytics_documents(
        self,
        query: ProcurementQuery,
        *,
        additional_filter_clauses: Sequence[str] = (),
        include_fields: Sequence[str] = (),
        max_documents: int | None = None,
        with_found: bool = False,
    ) -> list[Mapping[str, Any]] | tuple[int, list[Mapping[str, Any]]]:
        from functools import partial

        stop_event = threading.Event()
        try:
            return await asyncio.get_running_loop().run_in_executor(
                _dashboard_executor,
                partial(
                    self._request_all,
                    query,
                    additional_filter_clauses=additional_filter_clauses,
                    include_fields=include_fields,
                    stop_event=stop_event,
                    max_documents=max_documents,
                    with_found=with_found,
                ),
            )
        except asyncio.CancelledError:
            stop_event.set()
            raise

    async def search(self, query: ProcurementQuery) -> TypesenseSearchResult:
        try:
            return await asyncio.to_thread(self._request, query)
        except TypesenseShadowError as exc:
            # Typesense is a local runtime dependency and can return 5xx or
            # timeout errors while its serving collections are loading. Keep
            # retrying only that infrastructure class for a bounded window;
            # contract errors must still fail immediately and never fall into
            # the incomplete legacy Postgres path.
            retryable = (
                exc.code == SHADOW_INFRA_ERROR
                and (
                    str(exc).startswith("Typesense HTTP ")
                    or str(exc).startswith("Typesense request failed")
                )
            )
            if not retryable:
                raise
            deadline = time.monotonic() + self.config.query_retry_seconds
            delay = 0.25
            last_exc = exc
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise last_exc
                await asyncio.sleep(min(delay, remaining))
                try:
                    return await asyncio.to_thread(self._request, query)
                except TypesenseShadowError as retry_exc:
                    retryable = (
                        retry_exc.code == SHADOW_INFRA_ERROR
                        and (
                            str(retry_exc).startswith("Typesense HTTP ")
                            or str(retry_exc).startswith("Typesense request failed")
                        )
                    )
                    if not retryable:
                        raise
                    last_exc = retry_exc
                    delay = min(delay * 2, 2.0)

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

    def _request_update_package_codes(self, logical_group: str, day: date) -> set[str]:
        """Return unique tender codes for one serving partition day."""
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")

        collection = physical_collection_name(logical_group, self.config.serving_generation)
        package_codes: set[str] = set()
        page = 1
        per_page = TYPESENSE_MAX_HITS_PER_PAGE
        while True:
            params = {
                "q": "*",
                "query_by": "bid_invitation_code",
                "page": page,
                "per_page": per_page,
                "filter_by": f"decision_date:={day.isoformat()}",
                "include_fields": "bid_invitation_code",
            }
            url = f"{self.config.base_url}/collections/{quote(collection, safe='')}/documents/search?{urlencode(params)}"
            request = Request(url, method="GET", headers={
                "Accept": "application/json",
                "X-TYPESENSE-API-KEY": self.config.api_key,
            })
            try:
                with self._opener(request, timeout=max(self.config.timeout_seconds, 2.0)) as response:
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
            if not isinstance(payload, Mapping) or not isinstance(payload.get("found"), int) or payload["found"] < 0:
                raise TypesenseShadowError("Typesense returned malformed update timeline count")
            hits = payload.get("hits", [])
            if not isinstance(hits, list):
                raise TypesenseShadowError("Typesense returned malformed update timeline hits")
            for hit in hits:
                if not isinstance(hit, Mapping) or not isinstance(hit.get("document"), Mapping):
                    continue
                package_code = str(hit["document"].get("bid_invitation_code") or "").strip()
                if package_code:
                    package_codes.add(package_code)
            found = int(payload["found"])
            if page * per_page >= found or len(hits) < per_page:
                break
            page += 1
        return package_codes

    def _request_update_timeline(
        self,
        *,
        today: date | None = None,
        start_day: date | None = None,
    ) -> list[dict[str, Any]]:
        end_date = today or date.today()
        start_date = start_day or (end_date - timedelta(days=365))
        if start_date > end_date:
            start_date = end_date
        days = [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        ]
        tasks = [(logical_group, day) for logical_group in LOGICAL_GROUPS for day in days]
        with ThreadPoolExecutor(max_workers=24) as executor:
            codes_by_group = list(executor.map(lambda task: self._request_update_package_codes(*task), tasks))
        # A tender can have many product rows and can appear in more than one
        # serving group; merge codes before counting so the result is packages.
        by_day: dict[str, set[str]] = {}
        for (_, day), package_codes in zip(tasks, codes_by_group):
            by_day.setdefault(day.isoformat(), set()).update(package_codes)
        return [
            {"date": day, "count": len(package_codes)}
            for day, package_codes in sorted(by_day.items())
            if package_codes
        ]

    async def update_timeline(
        self,
        *,
        today: date | None = None,
        start_day: date | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._request_update_timeline, today=today, start_day=start_day)

    @staticmethod
    def _daily_value_number(value: Any) -> Decimal | None:
        """Parse a Typesense numeric field without allowing malformed rows through."""
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = Decimal(str(value).strip().replace(",", ""))
        except (ArithmeticError, TypeError, ValueError):
            return None
        if not parsed.is_finite() or parsed <= 0:
            return None
        return parsed

    def _request_daily_group_summary(self, logical_group: str, day: date) -> dict[str, Any]:
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")

        schema_group = logical_group
        query_by = {
            "goods": "item_name",
            "medicines": "medicine_name",
            "traditional_medicine": "item_name",
        }[schema_group]
        name_field = query_by
        collection = physical_collection_name(schema_group, self.config.serving_generation)
        include_fields = ",".join((
            "id", "quantity", "winning_unit_price", name_field,
            "procuring_entity_name", "bid_invitation_code", "source_tab",
        ))
        best: dict[str, Any] | None = None
        fallback_best: dict[str, Any] | None = None
        packages: dict[str, dict[str, Any]] = {}
        fallback_packages: dict[str, dict[str, Any]] = {}
        package_codes: set[str] = set()
        has_primary_data = False
        page = 1
        per_page = TYPESENSE_MAX_HITS_PER_PAGE

        while True:
            filter_parts = [f"decision_date:={day.isoformat()}"]
            params = {
                "q": "*",
                "query_by": query_by,
                "page": page,
                "per_page": per_page,
                "filter_by": " && ".join(filter_parts),
                "include_fields": include_fields,
            }
            url = f"{self.config.base_url}/collections/{quote(collection, safe='')}/documents/search?{urlencode(params)}"
            request = Request(url, method="GET", headers={
                "Accept": "application/json",
                "X-TYPESENSE-API-KEY": self.config.api_key,
            })
            try:
                with self._opener(request, timeout=max(self.config.timeout_seconds, 2.0)) as response:
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
            if not isinstance(payload, Mapping) or not isinstance(payload.get("found"), int) or payload["found"] < 0:
                raise TypesenseShadowError("Typesense returned malformed daily value metadata")
            hits = payload.get("hits", [])
            if not isinstance(hits, list):
                raise TypesenseShadowError("Typesense returned malformed daily value hits")

            for hit in hits:
                if not isinstance(hit, Mapping) or not isinstance(hit.get("document"), Mapping):
                    continue
                document = hit["document"]
                owner = document.get("procuring_entity_name")
                if isinstance(owner, (list, tuple)):
                    owner = ", ".join(str(item).strip() for item in owner if str(item).strip())
                owner = str(owner or "").strip() or None
                item_name = str(document.get(name_field) or "").strip() or None
                package_code = str(document.get("bid_invitation_code") or "").strip() or None
                if package_code:
                    package_codes.add(package_code)

                source_tab = str(document.get("source_tab") or "").strip()
                if logical_group == "goods" and source_tab not in {"THIET_BI_VAT_TU_Y_TE", "HANG_HOA"}:
                    continue
                is_general_goods = logical_group == "goods" and source_tab == "HANG_HOA"
                if not is_general_goods:
                    has_primary_data = True
                target_packages = fallback_packages if is_general_goods else packages

                if package_code:
                    target_packages.setdefault(package_code, {
                        "_value": Decimal(0),
                        "value": 0,
                        "name": None,
                        "owner": owner,
                        "bid_invitation_code": package_code,
                        "date": day.isoformat(),
                    })
                unit_price = self._daily_value_number(document.get("winning_unit_price"))
                quantity = self._daily_value_number(document.get("quantity"))
                if unit_price is None:
                    continue
                if package_code and quantity is not None:
                    value = quantity * unit_price
                    package = target_packages[package_code]
                    package["_value"] += value
                    package["value"] = (
                        int(package["_value"])
                        if package["_value"] == package["_value"].to_integral_value()
                        else float(package["_value"])
                    )
                    if not package.get("owner") and owner:
                        package["owner"] = owner
                current_best = fallback_best if is_general_goods else best
                if current_best is not None and unit_price <= current_best["_value"]:
                    continue
                candidate = {
                    "value": int(unit_price) if unit_price == unit_price.to_integral_value() else float(unit_price),
                    "_value": unit_price,
                    "name": item_name,
                    "owner": owner,
                    "bid_invitation_code": package_code,
                    "group": logical_group,
                    "date": day.isoformat(),
                }
                if is_general_goods:
                    fallback_best = candidate
                else:
                    best = candidate

            found = int(payload["found"])
            if page * per_page >= found or len(hits) < per_page:
                break
            page += 1

        for candidate in (best, fallback_best):
            if candidate is not None:
                candidate.pop("_value", None)
        for package in (*packages.values(), *fallback_packages.values()):
            package.pop("_value", None)
        return {
            "highest_item": best,
            "packages": packages,
            "fallback_highest_item": fallback_best,
            "fallback_packages": fallback_packages,
            "package_codes": package_codes,
            "has_primary_data": has_primary_data,
        }

    def _request_daily_summary(self, day: date) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=len(LOGICAL_GROUPS)) as executor:
            summaries = list(executor.map(lambda group: self._request_daily_group_summary(group, day), LOGICAL_GROUPS))

        packages: dict[str, dict[str, Any]] = {}
        package_codes: set[str] = set()
        candidates = []
        has_primary_data = any(summary.get("has_primary_data") for summary in summaries)
        item_key = "highest_item" if has_primary_data else "fallback_highest_item"
        packages_key = "packages" if has_primary_data else "fallback_packages"
        for summary in summaries:
            package_codes.update(summary.get("package_codes", set()))
            candidate = summary.get(item_key)
            if candidate is not None:
                candidates.append(candidate)
            for code, source_package in summary.get(packages_key, {}).items():
                if code not in packages:
                    packages[code] = dict(source_package)
                    continue
                package = packages[code]
                package["value"] = float(package.get("value") or 0) + float(source_package.get("value") or 0)
                if float(package["value"]).is_integer():
                    package["value"] = int(package["value"])
                if not package.get("owner") and source_package.get("owner"):
                    package["owner"] = source_package["owner"]

        highest_package = max(
            (package for package in packages.values() if float(package.get("value") or 0) > 0),
            key=lambda package: Decimal(str(package["value"])),
            default=None,
        )

        return {
            "approved_package_count": len(package_codes),
            "primary_data_available": has_primary_data,
            "highest_package": highest_package,
            "highest_goods": max(
                candidates,
                key=lambda candidate: Decimal(str(candidate["value"])),
                default=None,
            ),
        }

    async def daily_summary(self, day: date) -> dict[str, Any]:
        return await asyncio.to_thread(self._request_daily_summary, day)

    async def daily_highest_item(self, day: date) -> dict[str, Any] | None:
        return (await self.daily_summary(day)).get("highest_goods")

    def _suggest(self, query: AutocompleteQuery) -> tuple[str, ...]:
        started = time.perf_counter()
        if not self.config.api_key:
            raise TypesenseShadowError("Typesense shadow API key is not configured")
        group = public_group(query.group)
        canonical = canonical_field_for(group, query.field) or query.field
        contract_fields = {
            field["name"]: field
            for field in get_group_contract(group).get("fields", [])
        }
        allowed = set(get_group_contract(group)["autocomplete_fields"])
        requested_fields = tuple(query.search_fields)
        fields = (
            tuple(field for field in requested_fields if field in contract_fields and contract_fields[field]["type"] in {"string", "string[]"})
            if requested_fields
            else ((canonical,) if canonical in allowed else ())
        )
        if not fields:
            return ()
        plan = translate_typesense_query(
            build_canonical_query(
                group,
                query.filters,
                limit=query.limit,
                endpoint=query.endpoint,
                source_types=query.source_types,
                query_mode="autocomplete",
            ),
            serving_generation=self.config.serving_generation,
        )
        params = dict(plan.params)
        keyword = " ".join(str(query.keyword or "").split())
        is_phrase = " " in keyword
        candidate_keyword = keyword
        candidate_is_phrase = False
        if is_phrase and len(keyword.rsplit(" ", 1)[-1]) == 1:
            # Typesense can be too selective for a one-character final
            # prefix. Search the completed preceding phrase, then apply the
            # full type-ahead phrase check below.
            candidate_keyword = keyword.rsplit(" ", 1)[0]
            candidate_is_phrase = True
        escaped_candidate = candidate_keyword.replace("\\", "\\\\").replace('"', '\\"')
        params.update({
            # Autocomplete deliberately searches a broad candidate set. The
            # adapter enforces the contiguous phrase below, which also allows
            # Typesense to expand a partial final token ("máy điện t").
            "q": f'"{escaped_candidate}"' if candidate_is_phrase else (candidate_keyword or "*"),
            "query_by": ",".join(fields),
            "query_by_weights": ",".join("1" for _ in fields),
            "per_page": min(100, max(query.limit * 10, 20)),
            "include_fields": ",".join(fields),
            "prefix": "false" if candidate_is_phrase else "true",
            "num_typos": 0,
        })
        if len(keyword) >= 3 and not is_phrase:
            # Preserve prefix suggestions and also search inside words on
            # fields whose collection schema has an infix index.
            infix_modes = [
                "always" if contract_fields.get(field, {}).get("infix_search") else "off"
                for field in fields
            ]
            if "always" in infix_modes:
                params["infix"] = ",".join(infix_modes)
        if is_phrase or candidate_is_phrase:
            params["drop_tokens_threshold"] = 0
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
                    if text and keyword.casefold() in text.casefold() and text.casefold() not in seen:
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
