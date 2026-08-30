"""Frozen Typesense V1 schemas and conservative search configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping

from .config import ENGINE_VERSION, SCHEMA_VERSION

LOGICAL_ALIASES = {
    "goods": "bidfinder_goods",
    "medicines": "bidfinder_medicines",
    "traditional_medicine": "bidfinder_traditional",
}
GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
INTERNAL_CANONICAL_FIELDS = frozenset({"source_key"})


def validate_generation_id(generation_id: str) -> str:
    if not isinstance(generation_id, str) or not GENERATION_RE.fullmatch(generation_id):
        raise ValueError("generation must contain 1-64 letters, numbers, '.', '_' or '-' and start alphanumeric")
    return generation_id


def physical_collection_name(logical_group: str, generation_id: str) -> str:
    if logical_group not in LOGICAL_ALIASES:
        raise ValueError(f"unknown logical group: {logical_group}")
    return f"{LOGICAL_ALIASES[logical_group]}_v1_{validate_generation_id(generation_id)}"


def _field(name: str, field_type: str = "string", *, optional: bool = True, facet: bool = False, sort: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "type": field_type, "optional": optional}
    if facet:
        result["facet"] = True
    if sort:
        result["sort"] = True
    return result


_COMMON_FIELDS = (
    _field("id", "string", optional=False),
    _field("data_group", "string", optional=False, facet=True),
    _field("source_tab", "string", optional=False, facet=True),
    _field("source_tab_label", "string", optional=False, facet=True),
    _field("partition_date", "string", optional=False, facet=True, sort=True),
)

_GROUP_FIELDS: Mapping[str, tuple[dict[str, Any], ...]] = {
    "goods": (
        _field("item_name"), _field("unit", facet=True), _field("quantity", "float", sort=True),
        _field("country_of_origin", facet=True), _field("hs_code"), _field("model_mark"),
        _field("brand"), _field("production_year", "int32", sort=True), _field("manufacturer"),
        _field("technical_specification"), _field("model"),
        _field("registration_or_import_permit_number"), _field("winning_unit_price", "float", sort=True),
        _field("winning_bidder_id", "string[]"), _field("winning_bidder_name", "string[]"),
        _field("bid_invitation_code"), _field("procuring_entity_id"), _field("procuring_entity_name"),
        _field("selection_method", facet=True), _field("result_posted_at"), _field("decision_number"),
        _field("decision_issued_at"), _field("bidder_count", "float", sort=True), _field("location"),
    ),
    "medicines": (
        _field("medicine_name"), _field("active_ingredient_or_herbal_component"), _field("strength"),
        _field("marketing_authorization_or_import_permit"), _field("route_of_administration", facet=True),
        _field("dosage_form", facet=True), _field("shelf_life"), _field("manufacturer"),
        _field("production_country", facet=True), _field("packaging"), _field("unit", facet=True),
        _field("quantity", "float", sort=True), _field("winning_unit_price", "float", sort=True),
        _field("winning_bidder_id", "string[]"), _field("winning_bidder_name", "string[]"),
        _field("medicine_group", facet=True), _field("bid_invitation_code"), _field("procuring_entity_id"),
        _field("procuring_entity_name"), _field("selection_method", facet=True), _field("result_posted_at"),
        _field("decision_number"), _field("decision_issued_at"), _field("bidder_count", "float", sort=True),
        _field("location"),
    ),
    "traditional_medicine": (
        _field("item_name"), _field("used_part"), _field("scientific_name"), _field("origin", facet=True),
        _field("processing_method"), _field("registration_or_import_permit_number"), _field("manufacturer"),
        _field("production_country", facet=True), _field("packaging"), _field("unit", facet=True),
        _field("quantity", "float", sort=True), _field("winning_unit_price", "float", sort=True),
        _field("winning_bidder_id", "string[]"), _field("winning_bidder_name", "string[]"),
        _field("technical_group", facet=True), _field("bid_invitation_code"), _field("procuring_entity_id"),
        _field("procuring_entity_name"), _field("selection_method", facet=True), _field("result_posted_at"),
        _field("decision_number"), _field("decision_issued_at"), _field("bidder_count", "float", sort=True),
        _field("location"),
    ),
}

_QUERY_BY = {
    "goods": (
        "item_name", "country_of_origin", "hs_code", "model_mark", "brand", "manufacturer",
        "technical_specification", "model", "registration_or_import_permit_number", "winning_bidder_name",
        "bid_invitation_code", "procuring_entity_name", "selection_method", "unit",
    ),
    "medicines": (
        "medicine_name", "active_ingredient_or_herbal_component", "strength",
        "marketing_authorization_or_import_permit", "route_of_administration", "dosage_form", "shelf_life",
        "manufacturer", "production_country", "packaging", "winning_bidder_name", "medicine_group",
        "bid_invitation_code", "procuring_entity_name", "selection_method", "unit",
    ),
    "traditional_medicine": (
        "item_name", "used_part", "scientific_name", "origin", "processing_method",
        "registration_or_import_permit_number", "manufacturer", "production_country", "packaging", "winning_bidder_name",
        "technical_group", "bid_invitation_code", "procuring_entity_name", "selection_method", "unit",
    ),
}


@dataclass(frozen=True)
class SearchConfig:
    logical_group: str
    alias: str
    query_by: tuple[str, ...]
    filter_fields: frozenset[str]
    sort_fields: frozenset[str]


def _search_config(group: str) -> SearchConfig:
    fields = {field["name"]: field for field in (*_COMMON_FIELDS, *_GROUP_FIELDS[group])}
    filter_fields = frozenset(
        name for name, field in fields.items()
        if field.get("facet") or field["type"] in {"float", "int32"}
    )
    sort_fields = frozenset(name for name, field in fields.items() if field.get("sort"))
    return SearchConfig(group, LOGICAL_ALIASES[group], _QUERY_BY[group], filter_fields, sort_fields)


SEARCH_CONFIGS = {group: _search_config(group) for group in LOGICAL_ALIASES}


def collection_schema(logical_group: str, generation_id: str) -> dict[str, Any]:
    if logical_group not in LOGICAL_ALIASES:
        raise ValueError(f"unknown logical group: {logical_group}")
    validate_generation_id(generation_id)
    return {
        "name": physical_collection_name(logical_group, generation_id),
        "fields": deepcopy([*_COMMON_FIELDS, *_GROUP_FIELDS[logical_group]]),
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "ingestion_engine_version": ENGINE_VERSION,
            "logical_group": logical_group,
            "generation_id": generation_id,
        },
    }


def schema_for_group(logical_group: str) -> dict[str, Any]:
    return collection_schema(logical_group, "validation")


def _matches_type(value: Any, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "string[]":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if field_type == "int32":
        return isinstance(value, int) and not isinstance(value, bool) and -(2**31) <= value < 2**31
    if field_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"unsupported Typesense field type: {field_type}")


def canonical_to_typesense_document(record: Mapping[str, Any], logical_group: str | None = None) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("canonical record must be an object")
    group = logical_group or record.get("data_group")
    if group not in LOGICAL_ALIASES:
        raise ValueError(f"unknown canonical data_group: {group}")
    schema = schema_for_group(group)
    fields = {field["name"]: field for field in schema["fields"]}
    extras = set(record) - set(fields) - INTERNAL_CANONICAL_FIELDS
    if extras:
        raise ValueError(f"canonical record contains fields outside frozen Typesense schema: {', '.join(sorted(extras))}")
    result: dict[str, Any] = {}
    errors: list[str] = []
    for name, field in fields.items():
        value = record.get(name)
        if value is None:
            if not field.get("optional", False):
                errors.append(f"{name} is required")
            continue
        if not _matches_type(value, field["type"]):
            errors.append(f"{name} expected {field['type']}, got {type(value).__name__}")
            continue
        result[name] = value
    if errors:
        raise ValueError("; ".join(errors))
    return result


def validate_canonical_record(record: Mapping[str, Any], logical_group: str | None = None) -> None:
    canonical_to_typesense_document(record, logical_group)


def schema_signature(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return comparison data while ignoring server-added default field flags."""

    return {
        "name": schema.get("name"),
        "fields": sorted([
            {
                "name": field.get("name"),
                "type": field.get("type"),
                "optional": bool(field.get("optional", False)),
                "facet": bool(field.get("facet", False)),
                "sort": bool(field.get("sort", False)),
            }
            for field in schema.get("fields", [])
        ], key=lambda item: item["name"]),
        "metadata": schema.get("metadata", {}),
    }
