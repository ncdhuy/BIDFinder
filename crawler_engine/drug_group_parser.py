import re
import unicodedata
from typing import Iterable

import pandas as pd


CANONICAL_DRUG_GROUPS = ("BDG", "N1", "N2", "N3", "N4", "N5")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def clean_drug_group_for_parse(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).replace("\u00a0", " ").replace("\r", " ").replace("\n", " ")
    text = unicodedata.normalize("NFC", text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _unique_in_canonical_order(values: Iterable[str]) -> list[str]:
    found = set(values)
    return [value for value in CANONICAL_DRUG_GROUPS if value in found]


def parse_drug_group_filter_values(raw_value) -> list[str]:
    """Return canonical filter values for nhom_thuoc.

    Empty or unrecognized values deliberately return [] so callers can decide
    whether to fall back to the raw value for storage.
    """
    text = clean_drug_group_for_parse(raw_value)
    if not text:
        return []

    ascii_text = _strip_accents(text)
    compact = re.sub(r"[\s/_\-.]+", "", ascii_text)
    values: list[str] = []

    bdg_patterns = (
        r"\bbdg\b",
        r"\bbgd\b",
        r"\bbd\b",
        r"\bg2\b",
        r"\bbiet\s*duoc\b",
        r"\bbiet\s*duoc\s*goc\b",
    )
    if any(re.search(pattern, ascii_text) for pattern in bdg_patterns):
        values.append("BDG")
    if compact in {"bdg", "bgd", "bd", "g2"}:
        values.append("BDG")

    for number in range(1, 6):
        n_value = f"N{number}"
        if re.search(rf"\bn\s*{number}\b", ascii_text):
            values.append(n_value)
        if re.search(rf"\bnhom\s*{number}\b", ascii_text):
            values.append(n_value)
        if re.search(rf"\bg1\s*(?:n\s*{number}|nhom\s*{number})\b", ascii_text):
            values.append(n_value)
        if re.search(rf"\bg1n{number}\b", compact):
            values.append(n_value)

    if re.fullmatch(r"\s*[1-5](?:\s*[,;/]\s*[1-5])*\s*", ascii_text):
        values.extend(f"N{number}" for number in re.findall(r"[1-5]", ascii_text))

    for match in re.finditer(r"\bnhom\s+([1-5](?:\s*[,;/]\s*[1-5])*)\b", ascii_text):
        values.extend(f"N{number}" for number in re.findall(r"[1-5]", match.group(1)))

    return _unique_in_canonical_order(values)


def build_drug_group_filter_array(raw_value) -> list[str]:
    canonical = parse_drug_group_filter_values(raw_value)
    if canonical:
        return canonical

    text = clean_drug_group_for_parse(raw_value)
    if not text:
        return [""]
    return [str(raw_value).replace("\u00a0", " ").strip()]
