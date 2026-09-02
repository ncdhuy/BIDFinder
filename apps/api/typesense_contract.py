"""Authoritative Phase 4B search contract for the MSC Typesense collections.

The contract is derived from the frozen ingestion schema and source contracts.
It is intentionally backend-neutral so API and future UI code share one field
catalog without exposing Typesense query syntax.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from typing import Any, Mapping


try:
    from crawler_engine.msc.contracts import SOURCE_CONTRACTS
    from crawler_engine.msc.typesense_schema import (
        LOGICAL_ALIASES,
        SEARCH_CONFIGS,
        schema_for_group,
    )
except ModuleNotFoundError:  # ``uvicorn`` is documented from ``apps/api``.
    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from crawler_engine.msc.contracts import SOURCE_CONTRACTS
    from crawler_engine.msc.typesense_schema import (
        LOGICAL_ALIASES,
        SEARCH_CONFIGS,
        schema_for_group,
    )


PUBLIC_GROUPS = ("goods", "medicines", "traditional")
SCHEMA_GROUPS = {
    "goods": "goods",
    "medicines": "medicines",
    "traditional": "traditional_medicine",
    # Kept for Phase 4A callers and old shadow reports.
    "traditional_medicine": "traditional_medicine",
}

GROUP_LABELS = {
    "goods": "Hàng hóa",
    "medicines": "Thuốc",
    "traditional": "Dược liệu và vị thuốc cổ truyền",
}

FIELD_LABELS = {
    "id": "Mã bản ghi",
    "data_group": "Nhóm dữ liệu",
    "source_tab": "Mã nguồn MSC",
    "source_tab_label": "Loại nguồn",
    "partition_date": "Ngày phân vùng",
    "item_name": "Tên hàng hóa / dược liệu",
    "medicine_name": "Tên thuốc",
    "unit": "Đơn vị tính",
    "quantity": "Số lượng / khối lượng",
    "country_of_origin": "Xuất xứ",
    "hs_code": "Mã HS",
    "model_mark": "Ký mã hiệu",
    "brand": "Nhãn hiệu",
    "production_year": "Năm sản xuất",
    "manufacturer": "Hãng / cơ sở sản xuất",
    "technical_specification": "Cấu hình / tính năng kỹ thuật",
    "model": "Chủng loại",
    "registration_or_import_permit_number": "Số lưu hành / giấy phép nhập khẩu",
    "winning_unit_price": "Đơn giá trúng thầu (VND)",
    "winning_bidder_id": "Mã nhà thầu trúng thầu",
    "winning_bidder_name": "Nhà thầu trúng thầu",
    "bid_invitation_code": "Mã TBMT",
    "procuring_entity_id": "Mã chủ đầu tư",
    "procuring_entity_name": "Chủ đầu tư",
    "selection_method": "Hình thức lựa chọn nhà thầu",
    "result_posted_at": "Thời điểm đăng kết quả",
    "decision_number": "Số quyết định",
    "decision_issued_at": "Ngày ban hành quyết định",
    "bidder_count": "Số nhà thầu tham dự",
    "location": "Địa điểm",
    "active_ingredient_or_herbal_component": "Hoạt chất / thành phần dược liệu",
    "strength": "Nồng độ / hàm lượng",
    "marketing_authorization_or_import_permit": "GĐKLH hoặc GPNK",
    "route_of_administration": "Đường dùng",
    "dosage_form": "Dạng bào chế",
    "shelf_life": "Hạn dùng",
    "production_country": "Nước sản xuất",
    "packaging": "Quy cách đóng gói",
    "medicine_group": "Nhóm thuốc",
    "used_part": "Bộ phận dùng",
    "scientific_name": "Tên khoa học",
    "origin": "Nguồn gốc",
    "processing_method": "Phương pháp chế biến",
    "technical_group": "Nhóm tiêu chí kỹ thuật",
}

AUTOCOMPLETE_FIELDS = {
    "goods": ("item_name", "manufacturer", "winning_bidder_name", "bid_invitation_code", "procuring_entity_name"),
    "medicines": (
        "medicine_name", "active_ingredient_or_herbal_component", "manufacturer",
        "winning_bidder_name", "bid_invitation_code", "procuring_entity_name",
    ),
    "traditional": (
        "item_name", "scientific_name", "manufacturer", "winning_bidder_name",
        "bid_invitation_code", "procuring_entity_name",
    ),
}

IDENTIFIER_FIELDS = {
    "goods": ("id", "bid_invitation_code", "decision_number", "registration_or_import_permit_number", "winning_bidder_id", "procuring_entity_id"),
    "medicines": ("id", "bid_invitation_code", "decision_number", "marketing_authorization_or_import_permit", "winning_bidder_id", "procuring_entity_id"),
    "traditional": ("id", "bid_invitation_code", "decision_number", "registration_or_import_permit_number", "winning_bidder_id", "procuring_entity_id"),
}

FIELD_WEIGHTS = {
    "item_name": 10,
    "medicine_name": 10,
    "active_ingredient_or_herbal_component": 9,
    "bid_invitation_code": 8,
    "manufacturer": 5,
    "winning_bidder_name": 5,
    "procuring_entity_name": 4,
    "scientific_name": 9,
    "technical_specification": 6,
}

SAMPLE_VALUES = {
    "goods": {
        "id": "4a38103c-8b82-4e18-9dad-4b46b615916a",
        "data_group": "goods", "source_tab": "HANG_HOA",
        "source_tab_label": "Hàng hóa ngoài thuốc, thiết bị, vật tư y tế", "partition_date": "2026-09-01",
        "item_name": "Thực phẩm", "unit": "kg", "quantity": 1, "country_of_origin": "Việt Nam",
        "hs_code": "", "model": "", "registration_or_import_permit_number": "",
        "model_mark": "Thực phẩm", "brand": "Thực phẩm", "production_year": 2026,
        "manufacturer": "Việt Nam", "technical_specification": "Thực phẩm",
        "winning_unit_price": 61595022, "winning_bidder_id": ["vn0319058766"],
        "winning_bidder_name": ["CÔNG TY TNHH SCHOOL NUTRITION METAMILK VN"],
        "bid_invitation_code": "IB2600498667", "procuring_entity_id": "vn0304098773",
        "procuring_entity_name": "TRƯỜNG MẦM NON 14", "selection_method": "LCNT_DB",
        "result_posted_at": "2026-08-28T23:57:28", "decision_number": "184/QĐ-MN14",
        "decision_issued_at": "2026-08-25T23:59:59", "bidder_count": 1.7142857142857142,
        "location": "Thành phố Hồ Chí Minh, Phường Khánh Hội",
    },
    "medicines": {
        "id": "53ece56b-0d7d-4b19-a10e-341a3741f0e4",
        "data_group": "medicines", "source_tab": "THUOC_TAN_DUOC",
        "source_tab_label": "Gói thầu thuốc Generic", "partition_date": "2026-09-01",
        "medicine_name": "Apitim 5", "active_ingredient_or_herbal_component": "Amlodipin",
        "strength": "5mg", "marketing_authorization_or_import_permit": "893110140124",
        "route_of_administration": "Uống", "dosage_form": "Viên nang cứng", "shelf_life": "36 tháng",
        "unit": "Viên", "quantity": 65000, "manufacturer": "Công ty Cổ phần Dược Hậu Giang - Chi nhánh nhà máy dược phẩm DHG tại Hậu Giang",
        "production_country": "Việt Nam", "packaging": "Hộp 3 vỉ x 10 viên", "medicine_group": "N2",
        "winning_unit_price": 580, "winning_bidder_id": ["vn1800156801"],
        "winning_bidder_name": ["CÔNG TY CỔ PHẦN DƯỢC HẬU GIANG"], "bid_invitation_code": "IB2600498574",
        "procuring_entity_id": "vn3101155502", "procuring_entity_name": "TRẠM Y TẾ XÃ TRƯỜNG NINH",
        "selection_method": "CDT", "result_posted_at": "2026-08-28T21:56:06",
        "decision_number": "452/QĐ-TYT", "decision_issued_at": "2026-08-28T23:59:59",
        "location": "Tỉnh Quảng Trị, Xã Trường Ninh",
    },
    "traditional": {
        "id": "8d1a9094-9e9c-483e-a7b5-3535b9a8d7b0",
        "data_group": "traditional_medicine", "source_tab": "DUOC_LIEU",
        "source_tab_label": "Dược liệu", "partition_date": "2026-09-01",
        "item_name": "Bạch linh (Phục linh, Bạch phục linh)", "used_part": "Thân nấm",
        "scientific_name": "Poria", "origin": "B", "processing_method": "Quả thể nấm, thái, phơi khô hoặc sấy khô",
        "registration_or_import_permit_number": "4979/BYT-YDCT 122/YDCT-QLHN",
        "unit": "Kg", "quantity": 20,
        "manufacturer": "Công ty dược liệu", "production_country": "Việt Nam",
        "packaging": "Gói 1-5kg", "winning_unit_price": 197400,
        "winning_bidder_id": ["vn3100781627"], "winning_bidder_name": ["Công ty TNHH Đông Dược Văn Hương"],
        "technical_group": "N3", "bid_invitation_code": "IB2600477804",
        "procuring_entity_id": "vn3100488587", "procuring_entity_name": "Bệnh viện đa khoa khu vực Minh Hóa",
        "selection_method": "CDTRG", "result_posted_at": "2026-08-22T17:29:44",
        "decision_number": "885/QĐ-BV", "decision_issued_at": "2026-08-21T23:59:59",
        "bidder_count": 1.7419354838709677, "location": "Tỉnh Quảng Trị, Xã Minh Hóa",
    },
}


def normalize_group(group: str) -> str:
    try:
        return SCHEMA_GROUPS[str(group)]
    except KeyError as exc:
        raise ValueError(f"unknown logical group: {group}") from exc


def public_group(group: str) -> str:
    schema_group = normalize_group(group)
    return "traditional" if schema_group == "traditional_medicine" else schema_group


def _schema_fields(group: str) -> list[dict[str, Any]]:
    return list(schema_for_group(normalize_group(group))["fields"])


def _source_selector(group: str, source_key: str) -> dict[str, str]:
    contract = SOURCE_CONTRACTS[source_key]
    members = [item for item in SOURCE_CONTRACTS.values() if item.data_group == contract.data_group]
    same_tab = all(item.source_tab == contract.source_tab for item in members)
    return {
        "field": "source_tab" if not same_tab else "source_tab_label",
        "value": contract.source_tab if not same_tab else contract.source_tab_label,
    }


def _source_keys(group: str) -> list[str]:
    schema_group = normalize_group(group)
    return [key for key, item in SOURCE_CONTRACTS.items() if item.data_group == schema_group]


def _available_sources(group: str, canonical_name: str) -> list[str]:
    result: list[str] = []
    for source_key in _source_keys(group):
        source = SOURCE_CONTRACTS[source_key]
        if canonical_name in {"id", "data_group", "source_tab", "source_tab_label", "partition_date"}:
            result.append(source_key)
            continue
        if any(mapping.canonical_key == canonical_name and mapping.source_field in source.observed_source_fields for mapping in source.canonical_mapping):
            result.append(source_key)
    return result


def _raw_aliases(group: str, canonical_name: str) -> list[str]:
    aliases: set[str] = set()
    if canonical_name == "id":
        return ["id"]
    if canonical_name == "data_group":
        return ["data_group"]
    if canonical_name == "source_tab":
        return ["tab"]
    if canonical_name == "source_tab_label":
        return []
    if canonical_name == "partition_date":
        return ["partition_date"]
    for source_key in _source_keys(group):
        source = SOURCE_CONTRACTS[source_key]
        aliases.update(
            mapping.source_field
            for mapping in source.canonical_mapping
            if mapping.canonical_key == canonical_name
        )
    return sorted(aliases)


def _operators(field: Mapping[str, Any]) -> list[str]:
    name = field["name"]
    if field.get("sort") and name == "partition_date":
        return ["eq", "from", "to"]
    if field["type"] in {"float", "int32"}:
        return ["eq", "min", "max"]
    if field.get("facet"):
        return ["eq", "in"]
    return []


def build_search_contract() -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for group in PUBLIC_GROUPS:
        schema_group = normalize_group(group)
        schema = _schema_fields(group)
        query_by = tuple(SEARCH_CONFIGS[schema_group].query_by)
        filter_fields = set(SEARCH_CONFIGS[schema_group].filter_fields)
        sort_fields = set(SEARCH_CONFIGS[schema_group].sort_fields)
        fields: list[dict[str, Any]] = []
        for field in schema:
            name = field["name"]
            identifier = name in IDENTIFIER_FIELDS[group]
            autocomplete = name in AUTOCOMPLETE_FIELDS[group]
            fields.append({
                "name": name,
                "label": FIELD_LABELS.get(name, name),
                "type": field["type"],
                "raw_aliases": _raw_aliases(group, name),
                "source_types": _available_sources(group, name),
                "searchable": name in query_by,
                "filterable": name in filter_fields,
                "sortable": name in sort_fields,
                "facetable": bool(field.get("facet")),
                "autocomplete": autocomplete,
                "nullable": bool(field.get("optional", False)),
                "missing_behavior": "omitted; never coerced to zero or empty string",
                "example": SAMPLE_VALUES.get(group, {}).get(name),
                "example_source": "MSC contract fixture" if name in SAMPLE_VALUES.get(group, {}) else "not present in provided fixture sample",
                "api_exposure": "canonical",
                "ui_visibility": "detail" if name in {"id", "winning_bidder_id", "procuring_entity_id"} else "list_and_detail",
                "identifier": identifier,
                "exact_lookup": identifier,
                "allowed_operators": _operators(field),
            })
        weights = [FIELD_WEIGHTS.get(name, 2) for name in query_by]
        groups[group] = {
            "schema_group": schema_group,
            "collection_alias": LOGICAL_ALIASES[schema_group],
            "source_types": [
                {
                    "key": key,
                    "label": SOURCE_CONTRACTS[key].source_tab_label,
                    "selector": _source_selector(group, key),
                }
                for key in _source_keys(group)
            ],
            "full_text": {"fields": list(query_by), "weights": weights},
            "result_fields": [field["name"] for field in schema],
            "fields": fields,
            "filter_fields": sorted(name for name in filter_fields),
            "sort_fields": sorted(name for name in sort_fields),
            "autocomplete_fields": list(AUTOCOMPLETE_FIELDS[group]),
            "identifier_fields": list(IDENTIFIER_FIELDS[group]),
            "null_semantics": {
                "missing": "not indexed and does not match equality/range filters",
                "empty_string": "normalized as missing during ingestion where source value is blank",
                "empty_array": "not indexed; never treated as numeric zero",
                "zero": "legitimate numeric value and remains filterable/sortable",
            },
        }
    return {
        "contract_version": "typesense-search-contract-v1",
        "serving_generation": "serving_v1_20260901",
        "backend_independent": True,
        "groups": groups,
        "legacy_compatibility": {
            "scope": {"all": list(PUBLIC_GROUPS), "medicine": ["medicines"], "goods": ["goods"]},
            "traditional_legacy_key": "traditional_medicine",
            "query_preview": "/api/query-preview",
            "bulk_query": "/api/bulk-query",
        },
    }


SEARCH_CONTRACT = build_search_contract()


def get_search_contract() -> dict[str, Any]:
    return SEARCH_CONTRACT


def get_group_contract(group: str) -> dict[str, Any]:
    return SEARCH_CONTRACT["groups"][public_group(group)]


def canonical_field_for(group: str, name: str) -> str | None:
    if name in {field["name"] for field in get_group_contract(group)["fields"]}:
        return name
    legacy = {
        "drugName": "medicine_name", "activeIngredient": "active_ingredient_or_herbal_component",
        "concentration": "strength", "route": "route_of_administration", "dosageForm": "dosage_form",
        "specification": "packaging", "regNo": "marketing_authorization_or_import_permit",
        "country": "production_country", "winner": "winning_bidder_name", "investor": "procuring_entity_name",
        "approvalDecision": "decision_number", "selectionMethod": "selection_method", "place": "location",
        "goodsKeyword": "item_name", "lotName": "item_name", "goodsName": "item_name",
        "technicalSpec": "technical_specification", "bidItem": "technical_specification",
    }
    if public_group(group) in {"goods", "traditional"}:
        legacy.update({"drugName": "item_name", "country": "country_of_origin", "model": "model_mark"})
    return legacy.get(name)


def validate_contract_against_schema() -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, Any] = {}
    for group in PUBLIC_GROUPS:
        schema_group = normalize_group(group)
        fields = {field["name"]: field for field in _schema_fields(group)}
        contract = get_group_contract(group)
        names = {field["name"] for field in contract["fields"]}
        query_by = set(SEARCH_CONFIGS[schema_group].query_by)
        actual_filters = set(SEARCH_CONFIGS[schema_group].filter_fields)
        actual_sorts = set(SEARCH_CONFIGS[schema_group].sort_fields)
        for field in contract["fields"]:
            name = field["name"]
            if name not in fields:
                errors.append(f"{group}.{name}: absent from Typesense schema")
            if field["searchable"] != (name in query_by):
                errors.append(f"{group}.{name}: searchable drift")
            if field["filterable"] != (name in actual_filters):
                errors.append(f"{group}.{name}: filterable drift")
            if field["sortable"] != (name in actual_sorts):
                errors.append(f"{group}.{name}: sortable drift")
        for name in query_by | actual_filters | actual_sorts:
            if name not in names:
                errors.append(f"{group}.{name}: schema capability omitted from catalog")
        checks[group] = {
            "schema_fields": len(fields),
            "catalog_fields": len(names),
            "searchable": len(query_by),
            "filterable": len(actual_filters),
            "sortable": len(actual_sorts),
            "source_types": len(contract["source_types"]),
        }
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "groups": checks}


def source_selector(group: str, source_types: list[str] | tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    requested = tuple(source_types)
    allowed = {item["key"]: item["selector"] for item in get_group_contract(group)["source_types"]}
    unknown = sorted(set(requested) - set(allowed))
    if unknown:
        raise ValueError(f"unknown source type(s) for {public_group(group)}: {', '.join(unknown)}")
    if not requested:
        return "", ()
    fields = {allowed[key]["field"] for key in requested}
    if len(fields) != 1:
        raise ValueError("source types do not share one selector field")
    field_name = next(iter(fields))
    return field_name, tuple(allowed[key]["value"] for key in requested)


def contract_counts() -> dict[str, dict[str, int]]:
    return {
        group: {
            key: sum(1 for field in get_group_contract(group)["fields"] if field[key])
            for key in ("searchable", "filterable", "sortable", "autocomplete")
        }
        for group in PUBLIC_GROUPS
    }


VALID_BACKEND_MODES = frozenset({"postgres", "typesense", "controlled"})


@dataclass(frozen=True)
class ProcurementBackendConfig:
    """Centralized procurement read switch; Postgres remains rollback/fallback infrastructure."""

    mode: str = "typesense"
    controlled_typesense_enabled: bool = False
    fallback_enabled: bool = True
    fallback_timeout_seconds: float = 0.8

    @property
    def typesense_primary(self) -> bool:
        return self.mode == "typesense" or (self.mode == "controlled" and self.controlled_typesense_enabled)


def _env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    return default if not value else value in {"1", "true", "yes", "on"}


def get_procurement_backend_config() -> ProcurementBackendConfig:
    mode = os.getenv("BIDFINDER_PROCUREMENT_BACKEND", "typesense").strip().lower()
    if mode not in VALID_BACKEND_MODES:
        raise ValueError(f"BIDFINDER_PROCUREMENT_BACKEND must be one of: {', '.join(sorted(VALID_BACKEND_MODES))}")
    try:
        timeout = max(0.05, float(os.getenv("BIDFINDER_PROCUREMENT_FALLBACK_TIMEOUT_SECONDS", "0.8")))
    except ValueError:
        timeout = 0.8
    return ProcurementBackendConfig(
        mode=mode,
        controlled_typesense_enabled=_env_bool("BIDFINDER_CONTROLLED_TYPESENSE_ENABLED"),
        fallback_enabled=_env_bool("BIDFINDER_PROCUREMENT_FALLBACK_ENABLED", True),
        fallback_timeout_seconds=timeout,
    )
