from typing import Iterable

import numpy as np
import pandas as pd

VENDOR_COLUMN = "Nhà thầu trúng thầu"

_WINNER_FACT_CACHE: dict[tuple[str, str, str], dict | None] = {}


class WebWinnerManualReviewRequired(ValueError):
    pass


def collapse_whitespace(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def is_blank_vendor_cell(value) -> bool:
    if pd.isna(value):
        return True
    text = collapse_whitespace(value)
    return text == "" or text.lower() in {"nan", "none", "null", "<na>", "nat"}


def normalize_vendor_name(value) -> str:
    return collapse_whitespace(value).casefold()


def _cache_key(tbmt, so_qd, version) -> tuple[str, str, str]:
    return (
        str(tbmt or "").strip(),
        str(so_qd or "").strip(),
        str(version or "00").strip() or "00",
    )


def clear_web_winner_fact_cache():
    _WINNER_FACT_CACHE.clear()


def _fact_from_row(row) -> dict:
    if row is None:
        return None

    if isinstance(row, dict):
        capture_status = row.get("capture_status")
        only_winner_name = row.get("only_winner_name")
    else:
        capture_status, only_winner_name = row

    return {
        "capture_status": collapse_whitespace(capture_status) or "UNKNOWN",
        "only_winner_name": only_winner_name,
    }


def prefetch_web_winner_facts(cursor, unit_keys: Iterable[tuple[str, str, str]]):
    normalized_keys = []
    seen_keys = set()
    for tbmt, so_qd, version in unit_keys or []:
        key = _cache_key(tbmt, so_qd, version)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized_keys.append(key)

    if not normalized_keys:
        return

    uncached_keys = [key for key in normalized_keys if key not in _WINNER_FACT_CACHE]
    if not uncached_keys:
        return

    unit_tuple = tuple(uncached_keys)
    try:
        cursor.execute("""
            SELECT ma_tbmt, so_qd, version, capture_status, only_winner_name
            FROM web_winner_facts
            WHERE (ma_tbmt, so_qd, version) IN %s
        """, (unit_tuple,))

        found_keys = set()
        for row in cursor.fetchall():
            key = _cache_key(row[0], row[1], row[2])
            _WINNER_FACT_CACHE[key] = _fact_from_row(row[3:])
            found_keys.add(key)

        for key in uncached_keys:
            if key not in found_keys:
                _WINNER_FACT_CACHE[key] = None
    except Exception:
        for key in uncached_keys:
            _WINNER_FACT_CACHE[key] = None


def get_web_winner_fact(cursor, tbmt, so_qd, version):
    key = _cache_key(tbmt, so_qd, version)
    if key in _WINNER_FACT_CACHE:
        return _WINNER_FACT_CACHE[key]

    if cursor is None:
        return None

    try:
        cursor.execute("""
            SELECT capture_status, only_winner_name
            FROM web_winner_facts
            WHERE ma_tbmt = %s AND so_qd = %s AND version = %s
        """, key)
        row = cursor.fetchone()
        fact = _fact_from_row(row)
    except Exception:
        fact = None
    _WINNER_FACT_CACHE[key] = fact
    return fact


def is_single_winner_fact(fact: dict | None) -> bool:
    if not fact:
        return False
    return (
        fact.get("capture_status") == "SINGLE_WINNER"
        and bool(collapse_whitespace(fact.get("only_winner_name")))
    )


def is_multi_winner_fact(fact: dict | None) -> bool:
    if not fact:
        return False
    return fact.get("capture_status") == "MULTI_WINNER"


def format_winner_fact_summary(fact: dict | None, max_names: int = 3) -> str:
    if not fact:
        return "không có winner fact từ web crawl"

    parts = [f"status={fact.get('capture_status')}"]
    winner_name = collapse_whitespace(fact.get("only_winner_name"))
    if winner_name:
        parts.append(f"winner={winner_name}")
    return " | ".join(parts)


def apply_vendor_single_winner_fallback(
    df: pd.DataFrame,
    tbmt,
    so_qd,
    version,
    cursor=None,
):
    if df is None or df.empty:
        return df, {"status": "NO_ACTION"}

    vendor_col = VENDOR_COLUMN
    if vendor_col not in df.columns:
        df = df.copy()
        df[vendor_col] = pd.Series(pd.NA, index=df.index, dtype="string")

    series = df[vendor_col]
    blank_mask = series.map(is_blank_vendor_cell)
    blank_count = int(blank_mask.sum())

    existing_values = []
    seen_values = set()
    for value in series[~blank_mask]:
        text = collapse_whitespace(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen_values:
            continue
        seen_values.add(key)
        existing_values.append(text)

    if blank_count == 0:
        return df, {
            "status": "NO_ACTION",
            "blank_count": 0,
            "existing_values": existing_values,
        }

    fact = get_web_winner_fact(cursor, tbmt, so_qd, version)

    if len(existing_values) > 1:
        return df, {
            "status": "MANUAL_REQUIRED",
            "blank_count": blank_count,
            "fact": fact,
            "reason": (
                f"Cột '{vendor_col}' còn {blank_count} dòng trống nhưng file đã có nhiều nhà thầu khác nhau: "
                + ", ".join(existing_values[:3])
            ),
        }

    if len(existing_values) == 1:
        existing_vendor = existing_values[0]
        if is_multi_winner_fact(fact):
            return df, {
                "status": "MANUAL_REQUIRED",
                "blank_count": blank_count,
                "fact": fact,
                "reason": (
                    f"Cột '{vendor_col}' còn {blank_count} dòng trống và web crawl cho thấy có nhiều nhà thầu trúng thầu. "
                    f"{format_winner_fact_summary(fact)}"
                ),
            }

        if is_single_winner_fact(fact):
            web_vendor = collapse_whitespace(fact.get("only_winner_name"))
            if normalize_vendor_name(existing_vendor) != normalize_vendor_name(web_vendor):
                return df, {
                    "status": "MANUAL_REQUIRED",
                    "blank_count": blank_count,
                    "fact": fact,
                    "reason": (
                        f"Mismatch giữa nhà thầu trong file ('{existing_vendor}') và web crawl ('{web_vendor}'). "
                        f"{format_winner_fact_summary(fact)}"
                    ),
                }

        df = df.copy()
        df[vendor_col] = df[vendor_col].astype("string")
        df.loc[blank_mask, vendor_col] = existing_vendor
        return df, {
            "status": "FILLED_FROM_EXISTING_VENDOR",
            "blank_count": blank_count,
            "winner_name": existing_vendor,
            "fact": fact,
        }

    if is_single_winner_fact(fact):
        winner_name = collapse_whitespace(fact.get("only_winner_name"))
        if not winner_name:
            return df, {"status": "UNRESOLVED", "blank_count": blank_count, "fact": fact}

        df = df.copy()
        df[vendor_col] = df[vendor_col].astype("string")
        df.loc[blank_mask, vendor_col] = winner_name
        return df, {
            "status": "FILLED_FROM_WEB_SINGLE_WINNER",
            "blank_count": blank_count,
            "winner_name": winner_name,
            "fact": fact,
        }

    if is_multi_winner_fact(fact):
        return df, {
            "status": "MANUAL_REQUIRED",
            "blank_count": blank_count,
            "fact": fact,
            "reason": (
                f"Web crawl xác định có nhiều nhà thầu trúng thầu nên không thể auto-fill '{vendor_col}'. "
                f"{format_winner_fact_summary(fact)}"
            ),
        }

    return df, {
        "status": "UNRESOLVED",
        "blank_count": blank_count,
        "fact": fact,
        "reason": format_winner_fact_summary(fact),
    }
