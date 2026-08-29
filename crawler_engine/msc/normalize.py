"""Pure deterministic normalization from seven MSC sources to three groups."""

from __future__ import annotations

import re
import unicodedata
from math import isfinite
from typing import Any, Sequence

from .models import CanonicalRecord, RawRecord, SourceContract

_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"^\d{4}$")
_ARRAY_FIELDS = {"winning_bidder_id", "winning_bidder_name"}
_NUMBER_FIELDS = {
    "quantity", "winning_unit_price", "bidder_count",
}
_YEAR_FIELDS = {"production_year"}
_DATE_FIELDS = {"result_posted_at", "decision_issued_at"}
_LOCATION_FIELDS = {"location"}


class NormalizationError(ValueError):
    code = "NORMALIZATION_ERROR"


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"text field expected string, got {type(value).__name__}")
    value = unicodedata.normalize("NFC", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value or None


def normalize_array(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise NormalizationError(f"array field expected list, got {type(value).__name__}")
    result = []
    for member in value:
        text = normalize_text(member)
        if text is not None:
            result.append(text)
    return result or None


def normalize_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizationError(f"numeric field expected JSON number, got {type(value).__name__}")
    if isinstance(value, float) and not isfinite(value):
        raise NormalizationError("numeric field cannot be NaN or infinity")
    return value


def normalize_year(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"production year expected string, got {type(value).__name__}")
    value = value.strip()
    return int(value) if _YEAR_RE.fullmatch(value) else None


def normalize_location(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise NormalizationError("location expected object array")
    displays: list[str] = []
    for item in value:
        components = []
        for name_key, code_key in (("provName", "provCode"), ("districtName", "districtCode")):
            text = normalize_text(item.get(name_key)) or normalize_text(item.get(code_key))
            if text is not None:
                components.append(text)
        if components:
            displays.append(", ".join(components))
    return "; ".join(displays) or None


def _normalize_value(canonical_key: str, value: Any) -> Any:
    if canonical_key in _ARRAY_FIELDS:
        return normalize_array(value)
    if canonical_key in _NUMBER_FIELDS:
        return normalize_number(value)
    if canonical_key in _YEAR_FIELDS:
        return normalize_year(value)
    if canonical_key in _DATE_FIELDS:
        if value is None:
            return None
        if not isinstance(value, str):
            raise NormalizationError(f"date field expected string, got {type(value).__name__}")
        return value or None
    if canonical_key in _LOCATION_FIELDS:
        return normalize_location(value)
    return normalize_text(value)


def normalize_record(contract: SourceContract, raw: RawRecord, partition_date: str) -> CanonicalRecord:
    if not isinstance(raw, dict):
        raise NormalizationError("source record must be an object")
    source_id = raw.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise NormalizationError("source record requires non-empty string id")
    record: CanonicalRecord = {
        "id": source_id,
        "data_group": contract.data_group,
        "source_key": contract.key,
        "source_tab": contract.source_tab,
        "source_tab_label": contract.source_tab_label,
        "partition_date": partition_date,
    }
    for mapping in contract.canonical_mapping:
        record[mapping.canonical_key] = _normalize_value(mapping.canonical_key, raw.get(mapping.source_field))
    return record


def normalize_records(contract: SourceContract, records: Sequence[RawRecord], partition_date: str) -> tuple[CanonicalRecord, ...]:
    return tuple(normalize_record(contract, record, partition_date) for record in sorted(records, key=lambda item: item.get("id", "")))
