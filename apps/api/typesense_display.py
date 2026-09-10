"""Display normalization for Typesense-served documents.

This module belongs to the API boundary. It must stay independent from the
crawler/ingestion runtime because Typesense is the serving data source.
"""

from __future__ import annotations

import re
import unicodedata
from math import isfinite
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"^(\d{4})(?:\s*[-\u2013\u2014]\s*(\d{4}))?$")
_LOCATION_PART_RE = re.compile(r"\s*[,;]\s*")
_PROVINCE_PREFIX_RE = re.compile(
    r"^(?:t\u1ec9nh|th\u00e0nh ph\u1ed1|tp\.?|city)\s+",
    re.IGNORECASE,
)
_LOCALITY_PREFIX_RE = re.compile(
    r"^(?:x\u00e3|ph\u01b0\u1eddng|th\u1ecb tr\u1ea5n|qu\u1eadn|huy\u1ec7n|th\u1ecb x\u00e3)\s+",
    re.IGNORECASE,
)


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


def normalize_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizationError(f"numeric field expected JSON number, got {type(value).__name__}")
    if isinstance(value, float) and not isfinite(value):
        raise NormalizationError("numeric field cannot be NaN or infinity")
    return value


def normalize_bidder_count(value: Any) -> int | float | None:
    number = normalize_number(value)
    if number is None:
        return None
    if number < 0:
        raise NormalizationError("bidder count cannot be negative")
    return number


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
