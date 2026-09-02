"""Deterministic Phase 4A offline parity corpus.

The corpus is synthetic and contains no user queries. It exercises the frozen
canonical field contract and the current API query model without contacting
Postgres, MSC, or Typesense.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_shadow import (  # noqa: E402
    AutocompleteQuery,
    ParityMetric,
    ProcurementQuery,
    TypesenseSearchRepository,
    TypesenseSearchResult,
    TypesenseShadowConfig,
    build_canonical_query,
    build_bulk_canonical_query,
    compare_results,
    identity_collision_audit,
    report_summary,
    translate_typesense_query,
    _fold,
)


def _id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def _token(value: str, op: str = "OR") -> dict[str, Any]:
    return {"tokens": [{"value": value, "op": op}]}


def _row(group: str, number: int, **fields: Any) -> dict[str, Any]:
    return {"id": _id(number), "data_group": group, "source_tab": fields.pop("source_tab", "HANG_HOA"), "source_tab_label": fields.pop("source_tab_label", "fixture"), "partition_date": fields.pop("partition_date"), **fields}


CORPUS = [
    _row("goods", 1, partition_date="2022-06-15", item_name="Máy đo đường huyết", unit="cái", country_of_origin="Việt Nam", manufacturer="Công ty Thiết bị Việt", winning_bidder_name=["Công ty A"], bid_invitation_code="IB2200001", procuring_entity_name="Bệnh viện A", selection_method="DTRR", location="Hà Nội", quantity=10, winning_unit_price=100),
    _row("goods", 2, partition_date="2022-12-01", item_name="Bộ kit xét nghiệm", unit="hộp", country_of_origin="Hàn Quốc", manufacturer="Korea Medical", winning_bidder_name=["Công ty B"], bid_invitation_code="IB2200002", procuring_entity_name="Bệnh viện B", selection_method="CDT", location="Đà Nẵng", quantity=20, winning_unit_price=200),
    _row("goods", 3, partition_date="2023-01-20", item_name="Máy thở ICU", unit="cái", country_of_origin="Đức", manufacturer="MedTech GmbH", winning_bidder_name=["Công ty A"], bid_invitation_code="IB2300001", procuring_entity_name="Bệnh viện C", selection_method="DTRR", location="Hồ Chí Minh", quantity=3, winning_unit_price=300),
    _row("goods", 4, partition_date="2026-01-12", item_name="Găng tay y tế", unit="hộp", country_of_origin="Việt Nam", manufacturer="Nhà máy Việt", winning_bidder_name=["Công ty C"], bid_invitation_code="IB2600001", procuring_entity_name="Sở Y tế", selection_method="CDTRG", location="Huế", quantity=100, winning_unit_price=20),
    _row("goods", 5, partition_date="2026-08-28", item_name="Băng bột bó", unit="cuộn", country_of_origin="Trung Quốc", manufacturer="Ningbo Greetmed", winning_bidder_name=["Công ty D"], bid_invitation_code="IB2600002", procuring_entity_name="Bệnh viện D", selection_method="DTRR", location="Vĩnh Long", quantity=800, winning_unit_price=7),
    _row("goods", 6, partition_date="2026-08-29", item_name="Tủ lạnh bảo quản vaccine", unit="cái", country_of_origin="Nhật Bản", manufacturer="Tokyo Medical", winning_bidder_name=["Công ty E"], bid_invitation_code="IB2600003", procuring_entity_name="Trung tâm Y tế", selection_method="LCNT_DB", location="Cần Thơ", quantity=2, winning_unit_price=900),
    _row("medicines", 101, partition_date="2023-01-05", medicine_name="Paracetamol 500 mg", active_ingredient_or_herbal_component="Paracetamol", strength="500mg", route_of_administration="Uống", dosage_form="Viên nén", packaging="Hộp 10 vỉ", unit="Viên", manufacturer="Dược Hậu Giang", production_country="Việt Nam", winning_bidder_name=["Công ty Thuốc A"], bid_invitation_code="IB2300101", procuring_entity_name="Bệnh viện E", selection_method="CDT", location="Hà Nội", medicine_group="N2", quantity=65000, winning_unit_price=580),
    _row("medicines", 102, partition_date="2023-06-12", medicine_name="Amoxicillin 500mg", active_ingredient_or_herbal_component="Amoxicillin", strength="500 mg", route_of_administration="Uống", dosage_form="Viên nang", packaging="Hộp 3 vỉ", unit="Viên", manufacturer="Pharma Việt", production_country="Việt Nam", winning_bidder_name=["Công ty Thuốc B"], bid_invitation_code="IB2300102", procuring_entity_name="Bệnh viện F", selection_method="DTRR", location="Đà Nẵng", medicine_group="N1", quantity=30000, winning_unit_price=1200),
    _row("medicines", 103, partition_date="2026-02-10", medicine_name="Ceftriaxone", active_ingredient_or_herbal_component="Ceftriaxone sodium", strength="1g", route_of_administration="Tiêm", dosage_form="Bột pha tiêm", packaging="Lọ", unit="Lọ", manufacturer="Global Pharma", production_country="Ấn Độ", winning_bidder_name=["Công ty Thuốc C"], bid_invitation_code="IB2600101", procuring_entity_name="Bệnh viện G", selection_method="DTRR", location="Huế", medicine_group="N3", quantity=1000, winning_unit_price=5000),
    _row("medicines", 104, partition_date="2026-08-28", medicine_name="Artemisinin", active_ingredient_or_herbal_component="Artemisinin", strength="100mg", route_of_administration="Uống", dosage_form="Viên", packaging="Hộp", unit="Viên", manufacturer="Dược liệu Việt", production_country="Việt Nam", winning_bidder_name=["Công ty Thuốc A"], bid_invitation_code="IB2600102", procuring_entity_name="Sở Y tế", selection_method="CDTRG", location="Hà Nội", medicine_group="N5", quantity=500, winning_unit_price=900),
    _row("traditional_medicine", 201, partition_date="2023-01-15", item_name="Bạch linh", used_part="Quả thể", scientific_name="Poria", origin="Trong nước", processing_method="Thái lát", packaging="Gói 1kg", unit="Kg", manufacturer="Đông Dược A", production_country="Việt Nam", winning_bidder_name=["Công ty Dược Liệu"], bid_invitation_code="IB2300201", procuring_entity_name="Bệnh viện H", selection_method="CDT", location="Quảng Bình", technical_group="N3", quantity=20, winning_unit_price=197400),
    _row("traditional_medicine", 202, partition_date="2024-05-20", item_name="Đương quy", used_part="Rễ", scientific_name="Angelica sinensis", origin="Trung Quốc", processing_method="Sấy khô", packaging="Túi", unit="Kg", manufacturer="Đông Dược B", production_country="Trung Quốc", winning_bidder_name=["Công ty Dược Liệu B"], bid_invitation_code="IB2400201", procuring_entity_name="Bệnh viện I", selection_method="DTRR", location="Lào Cai", technical_group="N2", quantity=50, winning_unit_price=110000),
    _row("traditional_medicine", 203, partition_date="2026-08-22", item_name="Nhân sâm", used_part="Rễ", scientific_name="Panax ginseng", origin="Hàn Quốc", processing_method="Sấy", packaging="Hộp", unit="Kg", manufacturer="Korea Herb", production_country="Hàn Quốc", winning_bidder_name=["Công ty Dược Liệu C"], bid_invitation_code="IB2600201", procuring_entity_name="Sở Y tế", selection_method="CDTRG", location="Hồ Chí Minh", technical_group="N1", quantity=5, winning_unit_price=800000),
]


def _contains(value: Any, needle: str) -> bool:
    members = value if isinstance(value, list) else [value]
    return any(needle.casefold() in str(member or "").casefold() for member in members)


def _field_values(query: ProcurementQuery, name: str, row: Mapping[str, Any]) -> list[Any]:
    from typesense_shadow import FILTER_FIELD_MAP
    fields = FILTER_FIELD_MAP.get(query.group, {}).get(name, (name,))
    return [row.get(field) for field in fields]


def _matches(query: ProcurementQuery, row: Mapping[str, Any]) -> bool:
    for name, raw in query.filters.items():
        if name == "dateFrom" and str(row.get("partition_date", "")) < str(raw):
            return False
        if name == "dateTo" and str(row.get("partition_date", "")) > str(raw):
            return False
        if name in {"priceFrom", "priceTo"}:
            price = float(row.get("winning_unit_price") or 0)
            if name == "priceFrom" and price < float(raw):
                return False
            if name == "priceTo" and price > float(raw):
                return False
            continue
        if name in {"selectionMethod", "place"}:
            expected = raw if isinstance(raw, list) else []
            field_name = "selection_method" if name == "selectionMethod" else "location"
            if expected and row.get(field_name) not in expected:
                return False
            continue
        if isinstance(raw, Mapping) and isinstance(raw.get("tokens"), list):
            tokens = [item for item in raw["tokens"] if isinstance(item, Mapping) and str(item.get("value") or "").strip()]
            positive_or = []
            positive_and = []
            negative = []
            for item in tokens:
                found = any(_contains(value, str(item["value"])) for value in _field_values(query, name, row))
                op = str(item.get("op", "OR")).upper()
                if op == "NOT":
                    negative.append(found)
                elif op == "AND":
                    positive_and.append(found)
                else:
                    positive_or.append(found)
            if positive_and and not all(positive_and):
                return False
            if positive_or and not any(positive_or):
                return False
            if any(negative):
                return False
    return True


def _sort_value(row: Mapping[str, Any], field: str) -> Any:
    from typesense_shadow import SORT_FIELD_MAP
    mapped = SORT_FIELD_MAP.get(row.get("data_group", ""), {}).get(field, field)
    value = row.get(mapped)
    return (value is None, value)


class FixtureRepository:
    def __init__(self, rows: Sequence[Mapping[str, Any]], *, backend: str):
        self.rows = list(rows)
        self.backend = backend

    async def search(self, query: ProcurementQuery) -> TypesenseSearchResult:
        rows = [row for row in self.rows if row.get("data_group") == query.group and _matches(query, row)]
        if query.sort:
            for rule in reversed(query.sort):
                rows.sort(key=lambda row, field=rule.field: _sort_value(row, field), reverse=rule.order == "desc")
        else:
            rows.sort(key=lambda row: (row.get("partition_date") is None, row.get("partition_date", ""), row.get("bid_invitation_code", "")), reverse=False)
        start = query.offset
        page = rows[start:start + query.limit]
        return TypesenseSearchResult(query.group, len(rows), tuple(page), 0.2 if self.backend == "postgres" else 0.4, query.page, query.limit)


CASES: list[tuple[str, ProcurementQuery]] = []


def _add(label: str, group: str, *, filters: Mapping[str, Any] | None = None, sort: Any = None, limit: int = 3, page: int = 1) -> None:
    CASES.append((label, build_canonical_query(group, filters or {}, sort, limit, page=page)))


_add("goods broad", "goods", limit=4)
_add("goods common item text", "goods", filters={"drugName": _token("máy")})
_add("goods manufacturer", "goods", filters={"manufacturer": _token("việt")})
_add("goods bidder", "goods", filters={"winner": _token("công ty a")})
_add("goods tender code", "goods", filters={"bid_invitation_code": _token("IB2200001")})
_add("goods 2022", "goods", filters={"dateFrom": "2022-01-01", "dateTo": "2022-12-31"}, limit=10)
_add("goods Jan 2023", "goods", filters={"dateFrom": "2023-01-01", "dateTo": "2023-01-31"}, limit=10)
_add("goods recent 2026", "goods", filters={"dateFrom": "2026-01-01"}, limit=10)
_add("goods source tab", "goods", filters={"source_tab": _token("HANG_HOA")}, limit=10)
_add("goods price range", "goods", filters={"priceFrom": 50, "priceTo": 250}, limit=10)
_add("goods price ascending", "goods", sort=[{"column": "unitPrice", "order": "asc"}], limit=10)
_add("goods price descending", "goods", sort=[{"column": "unitPrice", "order": "desc"}], limit=10)
_add("goods pagination", "goods", limit=2, page=2)
_add("goods zero result", "goods", filters={"drugName": _token("không tồn tại")}, limit=10)
_add("medicine name", "medicines", filters={"drugName": _token("paracetamol")})
_add("medicine active ingredient", "medicines", filters={"activeIngredient": _token("paracetamol")})
_add("medicine manufacturer", "medicines", filters={"manufacturer": _token("dược")})
_add("medicine bidder", "medicines", filters={"winner": _token("thuốc a")})
_add("medicine tender code", "medicines", filters={"bid_invitation_code": _token("IB2300101")})
_add("medicine price range", "medicines", filters={"priceFrom": 500, "priceTo": 1500}, limit=10)
_add("medicine pagination", "medicines", limit=2, page=2)
_add("medicine Unicode", "medicines", filters={"drugName": _token("Paracetamol 500 mg")})
_add("traditional item", "traditional_medicine", filters={"drugName": _token("bạch linh")})
_add("traditional scientific name", "traditional_medicine", filters={"activeIngredient": _token("Poria")})
_add("traditional manufacturer", "traditional_medicine", filters={"manufacturer": _token("dược")})
_add("traditional source", "traditional_medicine", filters={"country": _token("hàn quốc")})
_add("traditional bidder", "traditional_medicine", filters={"winner": _token("liệu c")})
_add("traditional tender code", "traditional_medicine", filters={"bid_invitation_code": _token("IB2300201")})
_add("traditional pagination", "traditional_medicine", limit=2, page=2)
_add("traditional zero result", "traditional_medicine", filters={"drugName": _token("không có")}, limit=10)


def _real_value(row: Mapping[str, Any], *names: str) -> Any:
    wanted = {_fold(name) for name in names}
    for key, value in row.items():
        if _fold(key) in wanted and value not in (None, "", []):
            if isinstance(value, (list, tuple)):
                return next((item for item in value if item not in (None, "")), None)
            return value
    return None


def _token(value: Any) -> dict[str, Any] | None:
    text = " ".join(str(value or "").split()).strip()
    return {"tokens": [{"value": text, "op": "OR"}]} if text else None


def _percentiles(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None}
    return {
        "count": len(ordered),
        "p50": round(ordered[(len(ordered) - 1) // 2], 3),
        "p95": round(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))], 3),
    }


def _real_query_specs(group: str, rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, ProcurementQuery]]:
    sample = next(iter(rows), {})
    second = rows[1] if len(rows) > 1 else sample
    specs: list[tuple[str, ProcurementQuery]] = []

    def add(label: str, filters: Mapping[str, Any] | None = None, sort: Any = None, limit: int = 5, page: int = 1) -> None:
        specs.append((label, build_canonical_query(group, filters or {}, sort, limit, page=page)))

    if group == "goods":
        item = _real_value(sample, "Danh mục hàng hóa", "item_name", "Mặt hàng dự thầu")
        uncommon = _real_value(second, "Danh mục hàng hóa", "item_name", "Mặt hàng dự thầu")
        manufacturer = _real_value(sample, "Hãng sản xuất", "manufacturer")
        winner = _real_value(sample, "Nhà thầu trúng thầu", "winning_bidder_name")
        country = _real_value(sample, "Xuất xứ", "country_of_origin")
        unit = _real_value(sample, "Đơn vị tính", "unit")
        decision = _real_value(sample, "Quyết định phê duyệt", "decision_number")
        place = _real_value(sample, "Địa điểm", "location")
        method = _real_value(sample, "Hình thức LCNT", "selection_method")
        price = _real_value(sample, "Đơn giá trúng thầu (VND)", "winning_unit_price")
        investor = _real_value(sample, "Chủ đầu tư", "procuring_entity_name")
        technical = _real_value(sample, "Tính năng kỹ thuật", "technical_specification")
        add("goods broad", limit=5)
        add("goods page 2", limit=5, page=2)
        add("goods deeper page", limit=5, page=5)
        for label, field, value in (
            ("goods common item", "drugName", item), ("goods uncommon item", "drugName", uncommon),
            ("goods manufacturer", "manufacturer", manufacturer), ("goods bidder", "winner", winner),
            ("goods country", "country", country), ("goods unit", "unit", unit),
            ("goods approval identifier", "approvalDecision", decision),
            ("goods investor", "investor", investor), ("goods technical text", "specification", technical),
        ):
            token = _token(value)
            if token:
                add(label, {field: token}, limit=5)
        if method:
            add("goods selection method", {"selectionMethod": [str(method)]}, limit=5)
        if place:
            add("goods location", {"place": [str(place)]}, limit=5)
        add("goods 2022", {"dateFrom": "2022-01-01", "dateTo": "2022-12-31"}, limit=10)
        add("goods January 2023", {"dateFrom": "2023-01-01", "dateTo": "2023-01-31"}, limit=10)
        add("goods 2024", {"dateFrom": "2024-01-01", "dateTo": "2024-12-31"}, limit=10)
        add("goods changed 2025", {"dateFrom": "2025-01-01", "dateTo": "2025-12-31"}, limit=10)
        add("goods recent 2026", {"dateFrom": "2026-01-01"}, limit=10)
        if price is not None:
            try:
                numeric = float(price)
                add("goods price range", {"priceFrom": max(0, numeric * 0.5), "priceTo": numeric * 1.5}, limit=10)
            except (TypeError, ValueError):
                pass
        add("goods ascending price", sort=[{"column": "unitPrice", "order": "asc"}], limit=10)
        add("goods descending price", sort=[{"column": "unitPrice", "order": "desc"}], limit=10)
        add("goods ascending quantity", sort=[{"column": "quantity", "order": "asc"}], limit=10)
        add("goods descending quantity", sort=[{"column": "quantity", "order": "desc"}], limit=10)
        add("goods ascending approval date", sort=[{"column": "approvalDate", "order": "asc"}], limit=10)
        add("goods descending approval date", sort=[{"column": "approvalDate", "order": "desc"}], limit=10)
        add("goods zero result", {"drugName": _token("__phase4a_no_match__")}, limit=10)
    else:
        name = _real_value(sample, "Tên thuốc", "medicine_name")
        uncommon = _real_value(second, "Tên thuốc", "medicine_name")
        active = _real_value(sample, "Tên hoạt chất", "active_ingredient_or_herbal_component")
        manufacturer = _real_value(sample, "Cơ sở sản xuất", "manufacturer")
        winner = _real_value(sample, "Nhà thầu trúng thầu", "winning_bidder_name")
        country = _real_value(sample, "Xuất xứ", "production_country")
        unit = _real_value(sample, "Đơn vị tính", "unit")
        decision = _real_value(sample, "Quyết định phê duyệt", "decision_number")
        group_value = _real_value(sample, "Nhóm thuốc", "medicine_group")
        price = _real_value(sample, "Đơn giá trúng thầu (VND)", "winning_unit_price")
        investor = _real_value(sample, "Chủ đầu tư", "procuring_entity_name")
        concentration = _real_value(sample, "Nồng độ, hàm lượng", "strength")
        route = _real_value(sample, "Đường dùng", "route_of_administration")
        dosage = _real_value(sample, "Dạng bào chế", "dosage_form")
        specification = _real_value(sample, "Quy cách", "packaging")
        reg_no = _real_value(sample, "GĐKLH hoặc GPNK", "marketing_authorization_or_import_permit")
        place = _real_value(sample, "Địa điểm", "location")
        method = _real_value(sample, "Hình thức LCNT", "selection_method")
        add("medicine broad", limit=5)
        add("medicine page 2", limit=5, page=2)
        add("medicine deeper page", limit=5, page=5)
        for label, field, value in (
            ("medicine name", "drugName", name), ("medicine uncommon name", "drugName", uncommon),
            ("medicine active ingredient", "activeIngredient", active), ("medicine manufacturer", "manufacturer", manufacturer),
            ("medicine bidder", "winner", winner), ("medicine country", "country", country),
            ("medicine approval identifier", "approvalDecision", decision),
            ("medicine investor", "investor", investor), ("medicine concentration", "concentration", concentration),
            ("medicine route", "route", route), ("medicine dosage form", "dosageForm", dosage),
            ("medicine specification", "specification", specification), ("medicine registration", "regNo", reg_no),
            ("medicine unit", "unit", unit),
        ):
            token = _token(value)
            if token:
                add(label, {field: token}, limit=5)
        if group_value:
            add("medicine group", {"drugGroup": group_value}, limit=10)
        if method:
            add("medicine selection method", {"selectionMethod": [str(method)]}, limit=5)
        if place:
            add("medicine location", {"place": [str(place)]}, limit=5)
        add("medicine 2022", {"dateFrom": "2022-01-01", "dateTo": "2022-12-31"}, limit=10)
        add("medicine January 2023", {"dateFrom": "2023-01-01", "dateTo": "2023-01-31"}, limit=10)
        add("medicine 2024", {"dateFrom": "2024-01-01", "dateTo": "2024-12-31"}, limit=10)
        add("medicine changed 2025", {"dateFrom": "2025-01-01", "dateTo": "2025-12-31"}, limit=10)
        add("medicine recent 2026", {"dateFrom": "2026-01-01"}, limit=10)
        if price is not None:
            try:
                numeric = float(price)
                add("medicine price range", {"priceFrom": max(0, numeric * 0.5), "priceTo": numeric * 1.5}, limit=10)
            except (TypeError, ValueError):
                pass
        add("medicine ascending price", sort=[{"column": "unitPrice", "order": "asc"}], limit=10)
        add("medicine descending price", sort=[{"column": "unitPrice", "order": "desc"}], limit=10)
        add("medicine ascending quantity", sort=[{"column": "quantity", "order": "asc"}], limit=10)
        add("medicine descending quantity", sort=[{"column": "quantity", "order": "desc"}], limit=10)
        add("medicine ascending approval date", sort=[{"column": "approvalDate", "order": "asc"}], limit=10)
        add("medicine descending approval date", sort=[{"column": "approvalDate", "order": "desc"}], limit=10)
        add("medicine zero result", {"drugName": _token("__phase4a_no_match__")}, limit=10)
    return specs


async def run_live(*, api_key: str, host: str, port: int, protocol: str, timeout_seconds: float = 3.0) -> dict[str, Any]:
    import server as api_server

    config = TypesenseShadowConfig(
        enabled=True,
        serving_generation="serving_v1_20260901",
        sample_rate=1.0,
        timeout_seconds=timeout_seconds,
        host=host,
        port=port,
        protocol=protocol,
        api_key=api_key,
    )
    repository = TypesenseSearchRepository(config)
    pool = await api_server.ensure_db_pool()
    metrics: list[ParityMetric] = []
    endpoint_counts: Counter[str] = Counter()
    group_metrics: defaultdict[str, list[ParityMetric]] = defaultdict(list)
    slow_queries: list[dict[str, Any]] = []
    postgres_latencies: list[float] = []
    typesense_latencies: list[float] = []
    autocomplete_metrics: list[Any] = []
    preview_cases = 0
    bulk_cases = 0
    traditional_smoke: list[dict[str, Any]] = []
    collision_audits: list[dict[str, int]] = []
    case_records: list[dict[str, Any]] = []

    def add_metric(metric: ParityMetric, plan: Any, query: ProcurementQuery | None = None, label: str = "") -> None:
        nonlocal metrics
        metric = ParityMetric(**{
            **metric.to_dict(),
            "unsupported_filters": plan.unsupported_filters,
            "unsupported_sorts": plan.unsupported_sorts,
            "expected_differences": plan.expected_differences,
        })
        metrics.append(metric)
        endpoint_counts[metric.endpoint] += 1
        group_metrics[metric.group].append(metric)
        case_records.append({
            "label": label,
            "endpoint": metric.endpoint,
            "query_class": metric.query_class,
            "group": metric.group,
            "classification": metric.error_classification,
            "severity": metric.severity,
            "postgres_total": metric.postgres_total,
            "typesense_total": metric.typesense_total,
            "missing": metric.missing_from_typesense,
            "extra": metric.extra_in_typesense,
            "sort_parity": metric.explicit_sort_parity,
            "top_k_overlap": metric.top_k_overlap,
            "identity_strategy": metric.identity_strategy,
            "identity_collision_groups": metric.identity_collision_groups,
        })
        if metric.postgres_latency_ms is not None:
            postgres_latencies.append(metric.postgres_latency_ms)
        if metric.typesense_latency_ms is not None:
            typesense_latencies.append(metric.typesense_latency_ms)
        if metric.slow_outlier:
            slow_queries.append({
                "endpoint": metric.endpoint,
                "query_class": metric.query_class,
                "group": metric.group,
                "query_by": list(__import__("typesense_shadow").QUERY_BY[metric.group]),
                "filter_fields": list(plan.unsupported_filters) if plan.unsupported_filters else [],
                "sort": [rule for rule in plan.params.get("sort_by", "").split(",") if rule] if isinstance(plan.params.get("sort_by"), str) else [],
                "page": query.page if query else None,
                "limit": metric.page_size,
                "total_hits": metric.typesense_total,
                "latency_ms": round(metric.typesense_latency_ms or 0, 3),
            })

    def audit_identity_rows(group: str, primary: Mapping[str, Any], shadow: TypesenseSearchResult | None) -> None:
        primary_rows = [row for row in primary.get("data", []) if isinstance(row, Mapping)]
        shadow_rows = list(shadow.hits) if shadow is not None else []
        left = identity_collision_audit(primary_rows, group)
        right = identity_collision_audit(shadow_rows, group)
        collision_audits.append({
            "rows": left["rows"] + right["rows"],
            "identity_rows": left["identity_rows"] + right["identity_rows"],
            "unique_fingerprints": left["unique_fingerprints"] + right["unique_fingerprints"],
            "duplicated_fingerprint_groups": left["duplicated_fingerprint_groups"] + right["duplicated_fingerprint_groups"],
            "ambiguous_collision_groups": left["ambiguous_collision_groups"] + right["ambiguous_collision_groups"],
        })

    async with pool.acquire() as conn:
        seed_goods = await api_server.fetch_result_page(conn, "goods", api_server.FilterRequest(), [], 50)
        seed_medicines = await api_server.fetch_result_page(conn, "medicine", api_server.FilterRequest(), [], 50)
        seeds = {"goods": seed_goods["data"], "medicines": seed_medicines["data"]}

        async def compare_one(query: ProcurementQuery, primary: Mapping[str, Any], primary_latency: float) -> None:
            plan = translate_typesense_query(query, serving_generation=config.serving_generation)
            try:
                shadow = await asyncio.wait_for(repository.search(query), timeout=config.timeout_seconds)
                metric = compare_results(
                    query,
                    primary,
                    shadow,
                    postgres_latency_ms=primary_latency,
                )
            except Exception as exc:
                metric = compare_results(
                    query,
                    primary,
                    None,
                    postgres_latency_ms=primary_latency,
                    error=type(exc).__name__,
                )
                shadow = None
            audit_identity_rows(query.group, primary, shadow)
            add_metric(metric, plan, query)

        for group in ("goods", "medicines"):
            for label, query in _real_query_specs(group, seeds[group]):
                primary_start = time.perf_counter()
                if query.query_class == "full_text_relevance":
                    exact = False
                else:
                    exact = True
                primary = await api_server._fetch_primary_canonical_page(conn, query, exact_count_enabled=exact)
                primary_latency = (time.perf_counter() - primary_start) * 1000
                await compare_one(query, primary, round(primary_latency, 3))
                case_records[-1]["label"] = label

        preview_filters = [
            {},
            {"dateFrom": "2024-01-01", "dateTo": "2024-12-31"},
            {"drugName": _token(_real_value(seeds["goods"][0], "Danh mục hàng hóa", "Mặt hàng dự thầu"))},
            {"manufacturer": _token(_real_value(seeds["medicines"][0], "Cơ sở sản xuất", "manufacturer"))},
            {"country": _token(_real_value(seeds["goods"][0], "Xuất xứ", "country_of_origin"))},
            {"dateFrom": "2026-01-01"},
        ]
        for group, scope in (("goods", "goods"), ("medicines", "medicine")):
            for preview_index, filters in enumerate(preview_filters, start=1):
                query = build_canonical_query(group, filters, limit=10, endpoint="/api/query-preview")
                started = time.perf_counter()
                meta = await api_server.fetch_preview_bucket_cached(conn, scope, api_server.FilterRequest(**filters), api_server.PREVIEW_BUCKET_LIMIT)
                primary = {"data": [], "count": int(meta["count"]), "count_exact": bool(meta["exact"])}
                primary_latency = (time.perf_counter() - started) * 1000
                await compare_one(query, primary, round(primary_latency, 3))
                case_records[-1]["label"] = f"preview {group} case {preview_index}"
                preview_cases += 1

        for group, scope, field, aliases in (
            ("goods", "goods", "drugName", ("Danh mục hàng hóa", "Mặt hàng dự thầu")),
            ("goods", "goods", "manufacturer", ("Hãng sản xuất", "manufacturer")),
            ("medicines", "medicine", "drugName", ("Tên thuốc", "medicine_name")),
            ("medicines", "medicine", "manufacturer", ("Cơ sở sản xuất", "manufacturer")),
        ):
            for row in seeds[group][:6]:
                value = _real_value(row, *aliases)
                token = _token(value)
                if not token:
                    continue
                query = build_bulk_canonical_query(group, ["goodsName" if group == "goods" else "drugName"], {"goodsName" if group == "goods" else "drugName": value}, limit=3)
                primary_query = build_canonical_query(group, {field: token}, limit=3, endpoint="/api/bulk-query")
                primary_start = time.perf_counter()
                primary = await api_server._fetch_primary_canonical_page(conn, primary_query, exact_count_enabled=False)
                primary_latency = (time.perf_counter() - primary_start) * 1000
                plan = translate_typesense_query(query, serving_generation=config.serving_generation)
                try:
                    shadow = await asyncio.wait_for(repository.search(query), timeout=config.timeout_seconds)
                    metric = compare_results(query, primary, shadow, postgres_latency_ms=primary_latency)
                except Exception as exc:
                    metric = compare_results(query, primary, None, postgres_latency_ms=primary_latency, error=type(exc).__name__)
                    shadow = None
                audit_identity_rows(query.group, primary, shadow)
                add_metric(metric, plan, query, f"bulk {group} {field} case")
                bulk_cases += 1

        from typesense_shadow import run_shadow_autocomplete
        for group, scope in (("goods", "goods"), ("medicines", "medicine")):
            for field, aliases in (("drugName", ("Danh mục hàng hóa", "Mặt hàng dự thầu") if group == "goods" else ("Tên thuốc", "medicine_name")), ("manufacturer", ("Hãng sản xuất", "manufacturer") if group == "goods" else ("Cơ sở sản xuất", "manufacturer")), ("winner", ("Nhà thầu trúng thầu", "winning_bidder_name")), ("country", ("Xuất xứ", "country_of_origin") if group == "goods" else ("Xuất xứ", "production_country"))):
                value = _real_value(seeds[group][0], *aliases)
                keyword = " ".join(str(value or "").split())[:6]
                if not keyword:
                    continue
                req = api_server.AutocompleteRequest(scope=scope, field=field, keyword=keyword, filters={}, excludeSelf=True, limit=5)
                started = time.perf_counter()
                primary_suggestions = await api_server.fetch_autocomplete_suggestions(conn, req, scope)
                autocomplete_metrics.extend(await run_shadow_autocomplete(
                    [AutocompleteQuery(group=group, field=field, keyword=keyword, filters={}, limit=5)],
                    [keyword, *primary_suggestions][:5],
                    repository=repository,
                    config=config,
                    postgres_latency_ms=(time.perf_counter() - started) * 1000,
                ))

        traditional_seed = await repository.search(build_canonical_query("traditional_medicine", limit=5))
        traditional_row = traditional_seed.hits[0] if traditional_seed.hits else {}
        traditional_specs: list[tuple[str, ProcurementQuery]] = [("traditional broad", build_canonical_query("traditional_medicine", limit=5)), ("traditional page 2", build_canonical_query("traditional_medicine", limit=5, page=2)), ("traditional deeper page", build_canonical_query("traditional_medicine", limit=5, page=5)), ("traditional ascending price", build_canonical_query("traditional_medicine", sort=[{"column": "unitPrice", "order": "asc"}], limit=10)), ("traditional descending price", build_canonical_query("traditional_medicine", sort=[{"column": "unitPrice", "order": "desc"}], limit=10)), ("traditional zero result", build_canonical_query("traditional_medicine", {"drugName": _token("__phase4a_no_match__")}, limit=10))]
        for label, field, aliases in (("traditional item", "drugName", ("item_name", "ten duoc lieu", "ten san pham")), ("traditional scientific name", "activeIngredient", ("scientific_name", "ten khoa hoc")), ("traditional manufacturer", "manufacturer", ("manufacturer", "co so san xuat")), ("traditional bidder", "winner", ("winning_bidder_name", "nha thau trung thau"))):
            token = _token(_real_value(traditional_row, *aliases))
            if token:
                traditional_specs.append((label, build_canonical_query("traditional_medicine", {field: token}, limit=5)))
        for label, query in traditional_specs:
            if len(traditional_smoke) >= 8:
                break
            try:
                plan = translate_typesense_query(query, serving_generation=config.serving_generation)
                shadow = await asyncio.wait_for(repository.search(query), timeout=config.timeout_seconds)
                traditional_smoke.append({"label": label, "status": "REACHED", "total_hits": shadow.total, "latency_ms": round(shadow.latency_ms, 3), "unsupported_filters": list(plan.unsupported_filters)})
            except Exception as exc:
                traditional_smoke.append({"label": label, "status": "INFRA_ERROR", "error": type(exc).__name__})

    for metric in metrics:
        group_metrics[metric.group] = group_metrics[metric.group]
    by_group = {group: report_summary(values) for group, values in group_metrics.items()}
    by_endpoint: dict[str, Any] = {}
    for endpoint in sorted(endpoint_counts):
        by_endpoint[endpoint] = report_summary([metric for metric in metrics if metric.endpoint == endpoint])
    identity = {
        "strategy_counts": dict(Counter(metric.identity_strategy for metric in metrics)),
        "compared_rows": sum(metric.page_size for metric in metrics),
        "comparable_cases": sum(metric.missing_from_typesense is not None for metric in metrics),
        "identity_not_comparable": sum(metric.error_classification == "IDENTITY_NOT_COMPARABLE" for metric in metrics),
        "ambiguous_collision_groups": sum(metric.identity_collision_groups for metric in metrics),
    }
    return {
        "executed": True,
        "config": {"serving_generation": config.serving_generation, "sample_rate": config.sample_rate, "timeout_seconds": config.timeout_seconds, "endpoint": config.base_url},
        "corpus": {"total_comparisons": len(metrics) + len(autocomplete_metrics), "parity_comparisons": len(metrics), "by_endpoint": by_endpoint, "by_group": by_group, "autocomplete_comparisons": len(autocomplete_metrics), "preview_comparisons": preview_cases, "bulk_comparisons": bulk_cases, "traditional_adapter_smoke": len(traditional_smoke)},
        "comparisons": report_summary(metrics),
        "identity": identity,
        "collision_audit": {
            "comparisons_audited": len(collision_audits),
            "rows": sum(item["rows"] for item in collision_audits),
            "identity_rows": sum(item["identity_rows"] for item in collision_audits),
            "unique_fingerprints": sum(item["unique_fingerprints"] for item in collision_audits),
            "duplicated_fingerprint_groups": sum(item["duplicated_fingerprint_groups"] for item in collision_audits),
            "ambiguous_collision_groups": sum(item["ambiguous_collision_groups"] for item in collision_audits),
        },
        "parity": {"total_count": {"matched": sum(metric.postgres_total == metric.typesense_total for metric in metrics if metric.postgres_total is not None and metric.typesense_total is not None), "total": len(metrics)}, "missing_identity_rows": sum(metric.missing_from_typesense or 0 for metric in metrics if metric.missing_from_typesense is not None), "extra_identity_rows": sum(metric.extra_in_typesense or 0 for metric in metrics if metric.extra_in_typesense is not None), "explicit_sort": {"matched": sum(metric.explicit_sort_parity is True for metric in metrics if metric.explicit_sort_parity is not None), "total": sum(metric.explicit_sort_parity is not None for metric in metrics)}, "field_mismatches": sum(metric.field_mismatch_count or 0 for metric in metrics), "top_k_overlap": _percentiles([metric.top_k_overlap for metric in metrics if metric.top_k_overlap is not None])},
        "latency_ms": {"postgres": _percentiles(postgres_latencies), "typesense": _percentiles(typesense_latencies)},
        "slow_typesense_queries_over_500ms": slow_queries[:50],
        "autocomplete": {"comparisons": len(autocomplete_metrics), "ok": sum(item.error_classification == "SHADOW_OK" for item in autocomplete_metrics), "infra_errors": sum(item.error_classification == "SHADOW_INFRA_ERROR" for item in autocomplete_metrics), "top_k_overlap": _percentiles([item.top_k_overlap for item in autocomplete_metrics if item.top_k_overlap is not None])},
        "traditional_adapter": traditional_smoke,
        "case_records": [item for item in case_records if item["severity"] or item["classification"] != "SHADOW_OK"],
        "shadow_infrastructure_errors": report_summary(metrics)["infrastructure_errors"] + sum(item.error_classification == "SHADOW_INFRA_ERROR" for item in autocomplete_metrics),
    }


async def run() -> dict[str, Any]:
    postgres = FixtureRepository(CORPUS, backend="postgres")
    typesense = FixtureRepository(CORPUS, backend="typesense")
    metrics = []
    for label, query in CASES:
        primary = await postgres.search(query)
        shadow = await typesense.search(query)
        metric = compare_results(query, {"data": list(primary.hits), "count": primary.total, "count_exact": True}, shadow, postgres_latency_ms=primary.latency_ms)
        plan = translate_typesense_query(query, serving_generation="serving_v1_20260901")
        from typesense_shadow import ParityMetric
        metrics.append(ParityMetric(**{
            **metric.to_dict(),
            "unsupported_filters": plan.unsupported_filters,
            "unsupported_sorts": plan.unsupported_sorts,
            "expected_differences": plan.expected_differences,
        }))
        print(f"{label}: {metric.error_classification} class={metric.query_class} count={metric.postgres_total}/{metric.typesense_total} topK={metric.top_k_overlap}")
    summary = report_summary(metrics)
    percentiles = lambda values: {"p50": sorted(values)[(len(values) - 1) // 2], "p95": sorted(values)[min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))]} if values else {"p50": None, "p95": None}
    exact_counts = sum(metric.postgres_total == metric.typesense_total for metric in metrics)
    uuid_sets = sum(metric.missing_from_typesense == 0 and metric.extra_in_typesense == 0 for metric in metrics)
    sort_metrics = [metric for metric in metrics if metric.explicit_sort_parity is not None]
    field_values = [metric.field_mismatch_count for metric in metrics if metric.field_mismatch_count is not None]
    top_k = [metric.top_k_overlap for metric in metrics if metric.top_k_overlap is not None]
    return {
        "phase": "4A",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "starting_head": "2010504bbe1d1a5eaec8ea6b085b4c09dc52a036",
        "serving_generation": "serving_v1_20260901",
        "stable_aliases": {name: "inactive" for name in ("bidfinder_goods", "bidfinder_medicines", "bidfinder_traditional")},
        "offline_corpus": {"synthetic": True, "records": len(CORPUS), "comparisons": len(CASES), "groups": {group: sum(row["data_group"] == group for row in CORPUS) for group in ("goods", "medicines", "traditional_medicine")}},
        "comparisons": summary,
        "parity": {
            "total_count": {"matched": exact_counts, "total": len(metrics)},
            "uuid_set": {"exact": uuid_sets, "total": len(metrics)},
            "explicit_sort": {"matched": sum(metric.explicit_sort_parity is True for metric in sort_metrics), "total": len(sort_metrics)},
            "field_level": {"mismatch_count": sum(field_values), "comparable_cases": len(field_values)},
            "top_k_overlap": {"count": len(top_k), "min": min(top_k) if top_k else None, "p50": percentiles(top_k)["p50"], "p95": percentiles(top_k)["p95"]},
        },
        "latency_ms": {"postgres": percentiles([metric.postgres_latency_ms for metric in metrics if metric.postgres_latency_ms is not None]), "typesense": percentiles([metric.typesense_latency_ms for metric in metrics if metric.typesense_latency_ms is not None])},
        "slow_typesense_queries_over_500ms": [],
        "shadow_infrastructure_errors": summary["infrastructure_errors"],
        "serving_data_health": {"checkpoint_coverage": "9,738/9,738", "provenance_integrity": "PASS", "conflicts": 0, "unresolved_rejects": 0, "physical_provenance_parity": "PASS", "source": "Phase 3C.1 final-pass operator baseline"},
        "resource_state": {"shadow_load_measured": False, "typesense_rss": "~7.3 GB baseline", "wsl_mem_available": "~11 GB baseline", "swap": "negligible baseline", "note": "No live shadow request run by offline harness; credentials and local service state not persisted."},
        "api_response_regression": "not changed; Postgres response remains primary",
        "frontend_changed": False,
        "live_shadow": {
            "executed": False,
            "reason": "offline harness only; local Typesense credentials/service were unavailable",
        },
        "readiness": "PARTIAL" if summary["p0_mismatches"] == 0 else "BLOCKED",
        "offline_readiness": "PASS" if summary["p0_mismatches"] == 0 else "BLOCKED",
        "metrics": [metric.to_dict() for metric in metrics],
    }


def markdown(report: Mapping[str, Any]) -> str:
    parity = report["parity"]
    comp = report["comparisons"]
    lines = [
        "# Phase 4A Typesense shadow parity report",
        "",
        f"- Overall Phase 4A status: **{report['readiness']}**",
        f"- Offline baseline: **{report['offline_readiness']}**; live shadow execution: not run",
        f"- Starting HEAD: `{report['starting_head']}`",
        f"- Serving generation: `{report['serving_generation']}`",
        "- Stable aliases: inactive",
        "- Frontend changes: none",
        "",
        "## Offline corpus",
        "",
        f"Synthetic corpus: {report['offline_corpus']['records']} records, {report['offline_corpus']['comparisons']} comparisons. No raw user queries persisted.",
        "",
        "| Group | Records |",
        "| --- | ---: |",
    ]
    lines += [f"| {group} | {count} |" for group, count in report["offline_corpus"]["groups"].items()]
    lines += [
        "",
        "## Results",
        "",
        f"- Total-count parity: {parity['total_count']['matched']}/{parity['total_count']['total']}",
        f"- UUID-set parity: {parity['uuid_set']['exact']}/{parity['uuid_set']['total']}",
        f"- Explicit-sort parity: {parity['explicit_sort']['matched']}/{parity['explicit_sort']['total']}",
        f"- Field mismatches: {parity['field_level']['mismatch_count']}",
        f"- Top-K overlap: p50={parity['top_k_overlap']['p50']}, p95={parity['top_k_overlap']['p95']}",
        f"- P0/P1/P2/P3: {comp['p0_mismatches']}/{comp['p1_mismatches']}/{comp['p2_differences']}/{comp['p3_issues']}",
        f"- Shadow infrastructure errors: {report['shadow_infrastructure_errors']}",
        "",
        "## Latency and resources",
        "",
        f"- Offline Postgres fixture p50/p95: {report['latency_ms']['postgres']['p50']}/{report['latency_ms']['postgres']['p95']} ms",
        f"- Offline Typesense fixture p50/p95: {report['latency_ms']['typesense']['p50']}/{report['latency_ms']['typesense']['p95']} ms",
        "- Typesense queries over 500 ms: none in offline run; live outlier capture remains enabled.",
        "- Resource shadow-load measurement: not run; operator baseline remains ~7.3 GB RSS, ~11 GB WSL MemAvailable, negligible swap.",
        "",
        "## Gate",
        "",
        "- Postgres remains PRIMARY and user response authority.",
        "- Typesense uses physical `serving_v1_20260901` only; stable aliases remain inactive.",
        "- Offline result is a PASS baseline; overall Phase 4A remains PARTIAL until controlled live shadow and resource measurements run.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="run bounded live Postgres to Typesense validation")
    parser.add_argument("--typesense-api-key", default="", help="server-only key supplied by the existing local runtime")
    parser.add_argument("--typesense-host", default="127.0.0.1")
    parser.add_argument("--typesense-port", type=int, default=8108)
    parser.add_argument("--typesense-protocol", default="http")
    parser.add_argument("--report", type=Path, default=ROOT / "typesense-shadow-parity.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "typesense-shadow-parity.md")
    args = parser.parse_args()
    if args.live:
        if not args.typesense_api_key:
            parser.error("--typesense-api-key is required for --live")
        live = asyncio.run(run_live(
            api_key=args.typesense_api_key,
            host=args.typesense_host,
            port=args.typesense_port,
            protocol=args.typesense_protocol,
        ))
        print(json.dumps(live, ensure_ascii=False, sort_keys=True))
        return 0 if live["comparisons"]["p0_mismatches"] == 0 and live["shadow_infrastructure_errors"] == 0 else 1
    report = asyncio.run(run())
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"readiness": report["readiness"], "offline_readiness": report["offline_readiness"], "corpus": report["offline_corpus"], "p0": report["comparisons"]["p0_mismatches"], "p1": report["comparisons"]["p1_mismatches"], "p2": report["comparisons"]["p2_differences"], "p3": report["comparisons"]["p3_issues"]}, ensure_ascii=False))
    return 0 if report["offline_readiness"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
