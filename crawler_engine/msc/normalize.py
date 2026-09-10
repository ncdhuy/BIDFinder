"""Pure deterministic normalization from seven MSC sources to three groups."""

from __future__ import annotations

import re
import unicodedata
from math import isfinite
from typing import Any, Sequence

from .models import CanonicalRecord, RawRecord, SourceContract

_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"^(\d{4})(?:\s*[-–—]\s*(\d{4}))?$")
_LOCATION_PART_RE = re.compile(r"\s*[,;]\s*")
_PROVINCE_PREFIX_RE = re.compile(
    r"^(?:tỉnh|thành phố|tp\.?|city)\s+",
    re.IGNORECASE,
)
_LOCALITY_PREFIX_RE = re.compile(
    r"^(?:x\u00e3|ph\u01b0\u1eddng|th\u1ecb tr\u1ea5n|qu\u1eadn|huy\u1ec7n|th\u1ecb x\u00e3)\s+",
    re.IGNORECASE,
)
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


def normalize_bidder_count(value: Any) -> float | None:
    """Store numeric bidder counts as float without changing their value."""

    number = normalize_number(value)
    if number is None:
        return None
    if number < 0:
        raise NormalizationError("bidder count cannot be negative")
    return float(number)


def normalize_year(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"production year expected string, got {type(value).__name__}")
    value = normalize_text(value)
    if value is None:
        return None
    match = _YEAR_RE.fullmatch(value)
    if not match:
        return None
    start, end = match.groups()
    if end is None:
        return start
    if int(end) < int(start):
        return None
    return f"{start}-{end}"


def _normalize_location_text(value: str) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    entries: list[str] = []
    for entry in re.split(r"\s*;\s*", text):
        parts = [part for part in _LOCATION_PART_RE.split(entry) if part]
        if not parts:
            continue
        # Display local administrative units before the province/city. The
        # map still extracts the province independently, so display order does
        # not change map aggregation or merger resolution.
        province_index = next(
            (index for index, part in enumerate(parts) if _PROVINCE_PREFIX_RE.match(part)),
            None,
        )
        locality_after_province = province_index is not None and any(
            _LOCALITY_PREFIX_RE.match(part) for part in parts[province_index + 1:]
        )
        if locality_after_province:
            parts.append(parts.pop(province_index))
        entries.append(", ".join(parts))
    return "; ".join(entries) or None


def extract_location_province(value: Any) -> str | None:
    """Extract the source province/city while preserving its administrative label.

    This intentionally returns the source-era value (for example, ``Tỉnh
    Bình Dương``), so the merger map can distinguish legacy and current names
    instead of silently overwriting provenance.
    """

    normalized = _normalize_location_text(value) if isinstance(value, str) else normalize_location(value)
    if not normalized:
        return None
    for entry in normalized.split(";"):
        parts = [part.strip() for part in entry.split(",") if part.strip()]
        province = next((part for part in parts if _PROVINCE_PREFIX_RE.match(part)), None)
        if province:
            return province
        if parts:
            return parts[-1]
    return None


def normalize_location(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_location_text(value)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise NormalizationError("location expected object array or string")
    displays: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = _normalize_location_text(item)
            if text is not None:
                displays.append(text)
            continue
        if not isinstance(item, dict):
            raise NormalizationError("location entries expected objects or strings")
        components = []
        for name_keys, code_keys in (
            (("districtName", "wardName", "communeName"), ("districtCode", "wardCode", "communeCode")),
            (("provName", "provinceName", "cityName"), ("provCode", "provinceCode", "cityCode")),
        ):
            name_key = next((key for key in name_keys if item.get(key) is not None), name_keys[0])
            code_key = next((key for key in code_keys if item.get(key) is not None), code_keys[0])
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
        if canonical_key == "bidder_count":
            return normalize_bidder_count(value)
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
