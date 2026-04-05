import os
import psycopg2
from sqlalchemy import create_engine
import pandas as pd
import numpy as np
import argparse
from datetime import datetime
from schema_config import SCHEMAS 
from dotenv import load_dotenv
import time
import re
from dateutil.relativedelta import relativedelta
import shutil
from storage_adapter import ensure_local_file, is_r2_key, move_object, build_r2_key
import logging
import warnings

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl.styles.stylesheet",
)
warnings.filterwarnings(
    "ignore",
    message=r"Print area cannot be set to Defined name: .*",
    category=UserWarning,
    module="openpyxl.reader.workbook",
)
warnings.filterwarnings(
    "ignore",
    message=r"File contains an invalid specification for .*",
    category=UserWarning,
    module="openpyxl.reader.workbook",
)
warnings.filterwarnings(
    "ignore",
    message=r"Defined names for sheet index \d+ cannot be located",
    category=UserWarning,
    module="openpyxl.reader.workbook",
)

# =====================================================================
# CẤU HÌNH HỆ THỐNG & KẾT NỐI DATABASE
# =====================================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
ROOT_DATA_DIR = os.getenv("ROOT_DATA_DIR")
LOCAL_TEMP_ROOT = os.getenv("LOCAL_TEMP_ROOT")

if not DATABASE_URL:
    raise ValueError("❌ Thiếu biến môi trường DATABASE_URL trong file .env")
if not ROOT_DATA_DIR:
    raise ValueError("❌ Thiếu biến môi trường ROOT_DATA_DIR trong file .env")
if not LOCAL_TEMP_ROOT:
    raise ValueError("❌ Thiếu biến môi trường LOCAL_TEMP_ROOT trong file .env")

# SQLAlchemy yêu cầu giao thức 'postgresql://' thay vì 'postgres://'
SQLALCHEMY_URL = DATABASE_URL.replace("postgres://", "postgresql://")

TARGET_DATE = None

def get_db_connection():
    """Dùng cho các thao tác Execute/Delete thuần túy (nhanh, nhẹ)"""
    return psycopg2.connect(DATABASE_URL)

def get_engine():
    """Dùng riêng cho Pandas để Insert Chunking đa luồng vào DB"""
    return create_engine(SQLALCHEMY_URL)


def ensure_ignored_qd_table(cursor):
    return


def load_ignored_qd_map(cursor):
    ignored_map = {}
    cursor.execute("""
        SELECT ma_tbmt, so_qd
        FROM qd_relations
        WHERE relation_type = 'TYPO_ERROR'
    """)
    for tbmt, so_qd in cursor.fetchall():
        ignored_map.setdefault(tbmt, set()).add(so_qd)
    return ignored_map


def version_key(version_value):
    raw = str(version_value or "00").strip().replace("/", "-")
    parts = [p for p in raw.split("-") if p != ""]
    numbers = []

    for part in parts[:2]:
        try:
            numbers.append(int(part))
        except ValueError:
            digits = "".join(ch for ch in part if ch.isdigit())
            numbers.append(int(digits) if digits else 0)

    while len(numbers) < 2:
        numbers.append(0)

    return tuple(numbers[:2])

# =====================================================================
# TỪ KHÓA MAPPING & DATA CLEANING
# =====================================================================
KEYWORD_RULES = {
    "Tên hoạt chất": ["hoạt chất"],
    "Tên thuốc": ["tên thuốc"],
    "Nồng độ, hàm lượng": ["hàm lượng"],
    "Số đăng ký": ["số đăng ký"],
    "GĐKLH hoặc GPNK": ["gđklh", "gpnk"],
    "Đơn giá trúng thầu (VND)": ["đơn giá"],
    "Thành tiền (VND)": ["thành tiền"],
    "Nhà thầu trúng thầu": ["nhà thầu"],
    
    "Danh mục hàng hóa": ["tên hàng", "danh mục hàng"],
    "Tên phần/lô": ["tên phần", "tên lô"],
    "Mặt hàng dự thầu": ["mặt hàng dự thầu", "mặt hàng"],
    "Ký mã hiệu": ["ký mã", "mã hiệu"],
    "Tính năng kỹ thuật": ["tính năng", "kỹ thuật"],
    "Xuất xứ": ["xuất xứ", "nước sản xuất"],
    "Hãng sản xuất": ["hãng sản xuất"],
    "Năm sản xuất": ["năm sản xuất"]
}

def clean_col_str(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return re.sub(r"\s+", " ", s).strip().lower()


def is_vendor_group_column_name(col_name) -> bool:
    col_clean = clean_col_str(col_name)
    if "nhà thầu" not in col_clean:
        return False
    if col_clean.startswith("stt") or col_clean.startswith("số thứ tự"):
        return False
    if col_clean.startswith("mã"):
        return False
    return True

def get_smart_column_mapping(df_columns: list, mapping_config: dict) -> dict:
    final_map = {}
    clean_mapping_config = {clean_col_str(k): v for k, v in mapping_config.items()}
    best_target_choice = {}

    def register_candidate(source_col, target_col, priority):
        if not target_col:
            return
        candidate = (priority, len(str(source_col or "")))
        current = best_target_choice.get(target_col)
        if current is None or candidate > current[0]:
            best_target_choice[target_col] = (candidate, source_col)

    for col in df_columns:
        col_clean = clean_col_str(col)
        if col in mapping_config:
            register_candidate(col, mapping_config[col], 3)
            continue
        if col_clean in clean_mapping_config:
            register_candidate(col, clean_mapping_config[col_clean], 3)
            continue
            
        for target_col, keywords in KEYWORD_RULES.items():
            if any(kw in col_clean for kw in keywords):
                register_candidate(col, target_col, 1)
                break

    for target_col, (_, source_col) in best_target_choice.items():
        final_map[source_col] = target_col
    return final_map

def clean_numeric_series(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().replace(["nan", "None"], "")
    s = s.str.replace("\u00a0", " ", regex=False)
    s = s.str.replace(r"[^\d,.\-]", "", regex=True)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors='coerce')


def collapse_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not df.columns.duplicated().any():
        return df

    collapsed = pd.DataFrame(index=df.index)
    for col_name in df.columns.unique():
        same_name = df.loc[:, df.columns == col_name]
        if isinstance(same_name, pd.Series):
            collapsed[col_name] = same_name
            continue

        merged = same_name.iloc[:, 0]
        for idx in range(1, same_name.shape[1]):
            merged = merged.combine_first(same_name.iloc[:, idx])
        collapsed[col_name] = merged

    return collapsed


def collapse_sparse_goods_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df

    def is_blank(value) -> bool:
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value) -> str:
        return str(value).strip() if not pd.isna(value) else ""

    def stt_root(value) -> str:
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    def is_goods_total_row(row: pd.Series) -> bool:
        non_blank_count = sum(not is_blank(v) for v in row.tolist())
        sparse_threshold = max(4, int(len(row) * 0.35))
        is_sparse_row = non_blank_count <= sparse_threshold

        patterns = [
            r"tổng cộng giá .* hàng hóa",
            r"tổng giá .* hàng hóa",
            r"tổng cộng .* phí.*lệ phí",
        ]
        sparse_summary_patterns = [
            r"^tổng cộng\b",
            r"^thành tiền\b",
            r"^số tiền bằng chữ\b",
            r"^giá trị bằng chữ\b",
            r"^cộng\b",
        ]
        for value in row.tolist():
            text = clean_text(value).lower()
            if not text:
                continue
            if any(re.search(pattern, text) for pattern in patterns):
                return True
            if is_sparse_row and any(re.search(pattern, text) for pattern in sparse_summary_patterns):
                return True
        return False

    stt_col = next((c for c in df.columns if clean_col_str(c) == "stt"), None)
    vendor_col = next((c for c in df.columns if is_vendor_group_column_name(c)), None)
    name_col = next((
        c for c in df.columns
        if "tên hàng hóa" in clean_col_str(c) or "danh mục hàng hóa" in clean_col_str(c)
    ), None)
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)
    if not stt_col:
        return df

    total_mask = df.apply(is_goods_total_row, axis=1)
    df = df.loc[~total_mask].reset_index(drop=True)
    if df.empty:
        return df

    # Pattern nhóm: dòng đầu có STT + Nhà thầu + thành tiền tổng, các dòng sau chứa chi tiết hàng hóa.
    if vendor_col and name_col:
        expanded_rows = []
        group_header = None

        for _, row in df.iterrows():
            current = row.copy()
            has_stt = not is_blank(current.get(stt_col))
            has_vendor = not is_blank(current.get(vendor_col))
            has_name = not is_blank(current.get(name_col))

            is_group_header = has_stt and has_vendor and not has_name
            is_group_detail = group_header is not None and not has_stt and has_name

            if is_group_header:
                group_header = current
                continue

            if is_group_detail:
                for col in df.columns:
                    if col == amount_col:
                        continue
                    if is_blank(current.get(col)) and not is_blank(group_header.get(col)):
                        current[col] = group_header.get(col)
                expanded_rows.append(current)
                continue

            expanded_rows.append(current)
            group_header = None if has_stt else group_header

        df = pd.DataFrame(expanded_rows, columns=df.columns)
        if df.empty:
            return df

    merged_rows = []
    i = 0
    while i < len(df):
        current = df.iloc[i].copy()
        next_row = df.iloc[i + 1].copy() if i + 1 < len(df) else None

        should_merge = False
        if next_row is not None:
            current_has_stt = not is_blank(current.get(stt_col))
            next_has_stt = not is_blank(next_row.get(stt_col))
            same_amount = True
            if amount_col:
                cur_amount = clean_text(current.get(amount_col))
                nxt_amount = clean_text(next_row.get(amount_col))
                same_amount = (not cur_amount or not nxt_amount or cur_amount == nxt_amount)

            next_has_detail = sum(not is_blank(v) for v in next_row.tolist()) >= 4
            should_merge = current_has_stt and not next_has_stt and same_amount and next_has_detail

            if not should_merge and name_col:
                current_has_name = not is_blank(current.get(name_col))
                same_stt_group = (
                    current_has_stt and next_has_stt and
                    stt_root(current.get(stt_col)) != "" and
                    stt_root(current.get(stt_col)) == stt_root(next_row.get(stt_col))
                )
                sparse_current = sum(not is_blank(v) for v in current.tolist()) <= 5
                richer_next = sum(not is_blank(v) for v in next_row.tolist()) > sum(not is_blank(v) for v in current.tolist())
                should_merge = same_stt_group and current_has_name and sparse_current and richer_next

        if should_merge and next_row is not None:
            for col in df.columns:
                if is_blank(current.get(col)) and not is_blank(next_row.get(col)):
                    current[col] = next_row.get(col)
            merged_rows.append(current)
            i += 2
            continue

        merged_rows.append(current)
        i += 1

    return pd.DataFrame(merged_rows, columns=df.columns)

# =====================================================================
# HÀM BỔ TRỢ: MERGE DỮ LIỆU
# =====================================================================

def collapse_sparse_medicine_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df

    def is_blank(value) -> bool:
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value) -> str:
        return str(value).strip() if not pd.isna(value) else ""

    def stt_root(value) -> str:
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    def normalize_stt(value) -> str:
        text = clean_text(value)
        return re.sub(r"\.0+$", "", text)

    stt_col = next((c for c in df.columns if clean_col_str(c) == "stt"), None)
    vendor_col = next((c for c in df.columns if is_vendor_group_column_name(c)), None)
    name_col = next((c for c in df.columns if "tên thuốc" in clean_col_str(c)), None)
    if not stt_col or not vendor_col or not name_col:
        return df

    expanded_rows = []
    group_header = None
    group_root = None

    for _, row in df.iterrows():
        current = row.copy()
        current_stt = normalize_stt(current.get(stt_col))
        current_root = stt_root(current_stt)
        has_stt = bool(current_stt)
        has_vendor = not is_blank(current.get(vendor_col))
        has_name = not is_blank(current.get(name_col))

        is_group_header = has_stt and has_vendor and not has_name and current_stt == current_root
        is_group_detail = (
            group_header is not None
            and (
                (has_stt and bool(group_root) and current_root == group_root and current_stt != group_root)
                or (not has_stt and has_name)
            )
        )

        if is_group_header:
            group_header = current
            group_root = current_root
            continue

        if is_group_detail:
            for col in df.columns:
                if is_blank(current.get(col)) and not is_blank(group_header.get(col)):
                    current[col] = group_header.get(col)
            expanded_rows.append(current)
            continue

        expanded_rows.append(current)
        if has_stt and current_root != group_root:
            group_header = None
            group_root = None

    return pd.DataFrame(expanded_rows, columns=df.columns)

def detect_single_value_goods_group_header(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    name_col,
    amount_col,
) -> tuple[str, list] | None:
    if current is None or next_row is None:
        return None

    def is_blank(value) -> bool:
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value) -> str:
        return str(value).strip() if not pd.isna(value) else ""

    def is_numeric_like(text: str) -> bool:
        return bool(re.match(r"^[\d\s.,()+\-/%xX*=]+$", text))

    def stt_root(value) -> str:
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    def has_detail_signal(row: pd.Series) -> bool:
        if row is None:
            return False
        non_blank_count = sum(not is_blank(v) for v in row.tolist())
        has_name = bool(name_col and not is_blank(row.get(name_col)))
        has_price = any(
            "đơn giá" in clean_col_str(col) and not is_blank(row.get(col))
            for col in row.index
        )
        has_amount = any(
            "thành tiền" in clean_col_str(col) and not is_blank(row.get(col))
            for col in row.index
        )
        has_quantity = any(
            any(token in clean_col_str(col) for token in ("khối lượng", "số lượng"))
            and not is_blank(row.get(col))
            for col in row.index
        )
        return has_name or has_price or has_amount or has_quantity or non_blank_count >= 4

    texts = []
    source_cols = []
    for col in current.index:
        if col == stt_col or col == amount_col:
            continue
        text = clean_text(current.get(col))
        if not text or is_numeric_like(text):
            continue
        text_lower = text.lower()
        if text_lower.startswith(("tổng cộng", "thành tiền", "số tiền bằng chữ", "giá trị bằng chữ", "cộng")):
            continue
        texts.append(text)
        source_cols.append(col)

    if not texts:
        return None

    normalized_unique = {re.sub(r"\s+", " ", text).strip().lower() for text in texts}
    if len(normalized_unique) != 1:
        return None

    current_non_blank = sum(not is_blank(v) for v in current.tolist())
    next_non_blank = sum(not is_blank(v) for v in next_row.tolist())
    if next_non_blank <= current_non_blank or not has_detail_signal(next_row):
        return None

    current_stt = clean_text(current.get(stt_col)) if stt_col else ""
    next_stt = clean_text(next_row.get(stt_col)) if stt_col else ""

    same_group = False
    if current_stt:
        current_root = stt_root(current_stt)
        next_root = stt_root(next_stt)
        same_group = (
            (not next_stt)
            or (bool(current_root) and current_root == next_root and next_stt != current_stt)
        )
    else:
        same_group = (not next_stt) or has_detail_signal(next_row)

    if not same_group:
        return None

    return texts[0], source_cols


SUMMARY_ROW_PREFIXES = (
    "tổng cộng",
    "thành tiền",
    "số tiền bằng chữ",
    "giá trị bằng chữ",
    "cộng",
)


def _is_blank_cell(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def _clean_cell_text(value) -> str:
    return str(value).strip() if not pd.isna(value) else ""


def _normalize_stt_value(value) -> str:
    text = _clean_cell_text(value)
    return re.sub(r"\.0+$", "", text)


def _stt_root_value(value) -> str:
    text = _normalize_stt_value(value)
    if not text:
        return ""
    match = re.match(r"^(\d+)", text)
    return match.group(1) if match else text


def _is_top_level_stt(value) -> bool:
    text = _normalize_stt_value(value)
    return bool(text) and text == _stt_root_value(text)


def _is_numeric_like_text(text) -> bool:
    return bool(re.match(r"^[\d\s.,()+\-/%xX*=]+$", text))


def _matches_group_target(col_name, target_name) -> bool:
    col_clean = clean_col_str(col_name)
    target_clean = clean_col_str(target_name)
    if col_clean == target_clean:
        return True
    if target_clean == "nhà thầu trúng thầu":
        return is_vendor_group_column_name(col_name)
    return target_clean in col_clean


def get_group_row_engine_settings(df: pd.DataFrame, schema_type: str):
    stt_col = next((c for c in df.columns if clean_col_str(c) == "stt"), None)
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)

    if schema_type == "GOODS_STANDARD":
        detail_cols = [
            c for c in df.columns
            if any(token in clean_col_str(c) for token in ("tên hàng hóa", "danh mục hàng hóa", "tên thương mại"))
        ]
        group_targets = ["Nhà thầu trúng thầu"]
        auto_create_target = "Nhà thầu trúng thầu"
    else:
        detail_cols = [c for c in df.columns if "tên thuốc" in clean_col_str(c)]
        group_targets = ["Nhà thầu trúng thầu", "Nhóm thuốc"]
        auto_create_target = "Nhà thầu trúng thầu"

    existing_group_cols = [
        c for c in df.columns
        if any(_matches_group_target(c, target) for target in group_targets)
    ]

    return {
        "stt_col": stt_col,
        "amount_col": amount_col,
        "detail_cols": detail_cols,
        "group_targets": group_targets,
        "existing_group_cols": existing_group_cols,
        "auto_create_target": auto_create_target,
    }


def is_generic_summary_row(row: pd.Series, amount_col=None) -> bool:
    non_blank_count = sum(not _is_blank_cell(v) for v in row.tolist())
    sparse_threshold = max(4, int(len(row) * 0.35))
    is_sparse_row = non_blank_count <= sparse_threshold

    strong_patterns = [
        r"tổng cộng giá .* hàng hóa",
        r"tổng giá .* hàng hóa",
        r"tổng cộng .* phí.*lệ phí",
    ]

    for value in row.tolist():
        text = _clean_cell_text(value).lower()
        if not text:
            continue
        if any(re.search(pattern, text) for pattern in strong_patterns):
            return True
        if is_sparse_row and any(text.startswith(prefix) for prefix in SUMMARY_ROW_PREFIXES):
            return True
    return False


def has_detail_signal_generic(row: pd.Series, detail_cols: list, amount_col=None) -> bool:
    if row is None:
        return False
    non_blank_count = sum(not _is_blank_cell(v) for v in row.tolist())
    has_detail = any(not _is_blank_cell(row.get(col)) for col in detail_cols)
    has_price = any(
        "đơn giá" in clean_col_str(col) and not _is_blank_cell(row.get(col))
        for col in row.index
    )
    has_amount = any(
        "thành tiền" in clean_col_str(col) and not _is_blank_cell(row.get(col))
        for col in row.index
    )
    has_quantity = any(
        any(token in clean_col_str(col) for token in ("khối lượng", "số lượng"))
        and not _is_blank_cell(row.get(col))
        for col in row.index
    )
    return has_detail or has_price or has_amount or has_quantity or non_blank_count >= 4


def _belongs_same_group(current_stt, next_stt) -> bool:
    current_stt = _normalize_stt_value(current_stt)
    next_stt = _normalize_stt_value(next_stt)
    current_root = _stt_root_value(current_stt)
    if not current_stt:
        return not next_stt
    return (not next_stt) or (bool(current_root) and current_root == _stt_root_value(next_stt) and next_stt != current_stt)


def detect_true_group_header_generic(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    detail_cols,
    group_cols,
    amount_col=None,
):
    if current is None or next_row is None or not stt_col or not group_cols:
        return None

    current_stt = _normalize_stt_value(current.get(stt_col))
    if not _is_top_level_stt(current_stt):
        return None

    if any(not _is_blank_cell(current.get(col)) for col in detail_cols):
        return None

    source_group_cols = [col for col in group_cols if not _is_blank_cell(current.get(col))]
    if not source_group_cols:
        return None

    if not _belongs_same_group(current_stt, next_row.get(stt_col)) or not has_detail_signal_generic(next_row, detail_cols, amount_col):
        return None

    carry_values = {}
    for col in current.index:
        if col == amount_col:
            continue
        value = current.get(col)
        if not _is_blank_cell(value):
            carry_values[col] = value

    return {
        "root": _stt_root_value(current_stt),
        "carry_values": carry_values,
        "source_cols": source_group_cols,
    }


def detect_wrong_column_group_header_generic(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    detail_cols,
    group_cols,
    amount_col=None,
):
    if current is None or next_row is None or not stt_col:
        return None

    current_stt = _normalize_stt_value(current.get(stt_col))
    current_has_stt = bool(current_stt)
    if current_has_stt and not _is_top_level_stt(current_stt):
        return None

    if not _belongs_same_group(current_stt, next_row.get(stt_col)) or not has_detail_signal_generic(next_row, detail_cols, amount_col):
        next_stt = _normalize_stt_value(next_row.get(stt_col))
        if current_has_stt or not next_stt or not has_detail_signal_generic(next_row, detail_cols, amount_col):
            return None

    texts = []
    source_cols = []
    for col in current.index:
        if col == stt_col or col == amount_col:
            continue
        text = _clean_cell_text(current.get(col))
        if not text or _is_numeric_like_text(text):
            continue
        text_lower = text.lower()
        if any(text_lower.startswith(prefix) for prefix in SUMMARY_ROW_PREFIXES):
            continue
        texts.append(text)
        source_cols.append(col)

    if not texts:
        return None

    normalized_unique = {re.sub(r"\s+", " ", text).strip().lower() for text in texts}
    if len(normalized_unique) != 1:
        return None

    current_non_blank = sum(not _is_blank_cell(v) for v in current.tolist())
    sparse_threshold = max(3, min(5, int(len(current) * 0.25) or 3))
    if current_non_blank > sparse_threshold:
        return None

    if any(col in group_cols for col in source_cols):
        return None

    next_non_blank = sum(not _is_blank_cell(v) for v in next_row.tolist())
    if next_non_blank <= current_non_blank:
        return None

    return {
        "root": _stt_root_value(current_stt) if current_has_stt else None,
        "text": texts[0],
        "source_cols": source_cols,
    }


def merge_pseudo_group_rows_generic(df: pd.DataFrame, stt_col, detail_cols, amount_col=None) -> pd.DataFrame:
    if df.empty or not stt_col:
        return df

    merged_rows = []
    i = 0
    primary_detail_col = detail_cols[0] if detail_cols else None

    while i < len(df):
        current = df.iloc[i].copy()
        next_row = df.iloc[i + 1].copy() if i + 1 < len(df) else None

        should_merge = False
        if next_row is not None:
            current_has_stt = not _is_blank_cell(current.get(stt_col))
            next_has_stt = not _is_blank_cell(next_row.get(stt_col))
            next_next_row = df.iloc[i + 2].copy() if i + 2 < len(df) else None
            same_amount = True
            if amount_col:
                cur_amount = _clean_cell_text(current.get(amount_col))
                nxt_amount = _clean_cell_text(next_row.get(amount_col))
                same_amount = (not cur_amount or not nxt_amount or cur_amount == nxt_amount)

            next_has_detail = has_detail_signal_generic(next_row, detail_cols, amount_col)
            next_is_group_header = detect_wrong_column_group_header_generic(
                current=next_row,
                next_row=next_next_row,
                stt_col=stt_col,
                detail_cols=detail_cols,
                group_cols=[],
                amount_col=amount_col,
            ) is not None
            should_merge = current_has_stt and not next_has_stt and same_amount and next_has_detail and not next_is_group_header

            if not should_merge and primary_detail_col:
                current_has_name = not _is_blank_cell(current.get(primary_detail_col))
                current_stt = _normalize_stt_value(current.get(stt_col))
                next_stt = _normalize_stt_value(next_row.get(stt_col))
                same_stt_group = (
                    current_has_stt and next_has_stt and
                    _stt_root_value(current_stt) != "" and
                    _stt_root_value(current_stt) == _stt_root_value(next_stt)
                )
                sparse_current = sum(not _is_blank_cell(v) for v in current.tolist()) <= 5
                richer_next = sum(not _is_blank_cell(v) for v in next_row.tolist()) > sum(not _is_blank_cell(v) for v in current.tolist())
                should_merge = same_stt_group and current_has_name and sparse_current and richer_next

        if should_merge and next_row is not None:
            for col in df.columns:
                next_value = next_row.get(col)
                current_value = current.get(col)
                if not _is_blank_cell(next_value):
                    current[col] = next_value
                elif _is_blank_cell(current_value):
                    current[col] = next_value
            merged_rows.append(current)
            i += 2
            continue

        merged_rows.append(current)
        i += 1

    return pd.DataFrame(merged_rows, columns=df.columns)


def normalize_grouped_rows_generic(df: pd.DataFrame, schema_type: str):
    if df is None or df.empty:
        return df

    working_df = df.copy()
    settings = get_group_row_engine_settings(working_df, schema_type)
    stt_col = settings["stt_col"]
    detail_cols = settings["detail_cols"]
    amount_col = settings["amount_col"]
    group_cols = list(settings["existing_group_cols"])
    auto_create_target = settings["auto_create_target"]

    if not stt_col or not detail_cols:
        return working_df

    total_mask = working_df.apply(lambda row: is_generic_summary_row(row, amount_col), axis=1)
    working_df = working_df.loc[~total_mask].reset_index(drop=True)
    if working_df.empty:
        return working_df

    current_context = None
    normalized_rows = []

    for idx, (_, row) in enumerate(working_df.iterrows()):
        current = row.copy()
        next_row = working_df.iloc[idx + 1] if idx + 1 < len(working_df) else None

        true_group = detect_true_group_header_generic(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            detail_cols=detail_cols,
            group_cols=group_cols,
            amount_col=amount_col,
        )
        if true_group:
            current_context = true_group
            continue

        wrong_group = detect_wrong_column_group_header_generic(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            detail_cols=detail_cols,
            group_cols=group_cols,
            amount_col=amount_col,
        )
        if wrong_group:
            if auto_create_target and auto_create_target not in working_df.columns:
                working_df[auto_create_target] = np.nan
                current[auto_create_target] = np.nan
                if auto_create_target not in group_cols:
                    group_cols.append(auto_create_target)
            if auto_create_target:
                current_context = {
                    "root": wrong_group["root"],
                    "carry_values": {auto_create_target: wrong_group["text"]},
                    "source_cols": wrong_group["source_cols"],
                }
                continue

        current_stt = _normalize_stt_value(current.get(stt_col))
        current_root = _stt_root_value(current_stt)
        if current_context:
            context_root = current_context["root"]
            if context_root:
                belongs_to_context = (
                    (bool(current_stt) and current_root == context_root and current_stt != context_root)
                    or (not current_stt and has_detail_signal_generic(current, detail_cols, amount_col))
                )
            else:
                belongs_to_context = has_detail_signal_generic(current, detail_cols, amount_col)
            if belongs_to_context:
                for col, value in current_context["carry_values"].items():
                    if col == amount_col:
                        continue
                    if _is_blank_cell(current.get(col)) and not _is_blank_cell(value):
                        current[col] = value
            elif context_root and current_stt and current_root and current_root != context_root:
                current_context = None

        if not all(_is_blank_cell(v) for v in current.tolist()):
            normalized_rows.append(current)

    normalized_df = pd.DataFrame(normalized_rows, columns=working_df.columns)
    return merge_pseudo_group_rows_generic(normalized_df, stt_col, detail_cols, amount_col)

def _norm_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().str.strip().replace({"nan": "", "none": ""})

def generate_row_hash(df: pd.DataFrame, schema_name: str) -> pd.Series:
    cfg = SCHEMAS[schema_name]
    pri = cfg.get("primary_merge_key", [])
    fb  = cfg.get("fallback_merge_key", [])
    df2 = df.copy()

    def build(keys, prefix):
        if not keys:
            return pd.Series([prefix] * len(df2), index=df2.index)
        cols = []
        for k in keys:
            if k in df2.columns:
                cols.append(_norm_series(df2[k]))
            else:
                cols.append(pd.Series([""] * len(df2), index=df2.index))
        out = cols[0]
        for c in cols[1:]:
            out = out + "||" + c
        return prefix + out

    pri_key = build(pri, "PRI_")
    fb_key  = build(fb, "FB_")

    if pri:
        mask = pd.Series(True, index=df2.index)
        for k in pri:
            if k in df2.columns:
                mask &= _norm_series(df2[k]).ne("")
            else:
                mask &= False
        return pri_key.where(mask, fb_key)
    else:
        return fb_key
    
def apply_numeric_cleaning(df: pd.DataFrame) -> pd.DataFrame:
    df = collapse_duplicate_columns(df)
    str_cols = df.select_dtypes(include=['object']).columns
    for c in str_cols:
        df[c] = df[c].astype(str).str.strip().str.lstrip('\'"')
        df[c] = df[c].replace(["nan", "None", "<NA>", "NaT"], np.nan)
        
    cols_num = ['Số lượng', 'Khối lượng', 'Đơn giá trúng thầu (VND)', 'Thành tiền (VND)']
    for c in cols_num:
        if c in df.columns: 
            df[c] = clean_numeric_series(df[c])
            
    if all(c in df.columns for c in ["Thành tiền (VND)", "Khối lượng", "Đơn giá trúng thầu (VND)"]):
        mask_missing = df["Thành tiền (VND)"].isna()
        mask_has_inputs = df["Khối lượng"].notna() & df["Đơn giá trúng thầu (VND)"].notna()
        df.loc[mask_missing & mask_has_inputs, "Thành tiền (VND)"] = df.loc[mask_missing & mask_has_inputs, "Khối lượng"] * df.loc[mask_missing & mask_has_inputs, "Đơn giá trúng thầu (VND)"]

    df = df.replace([np.inf, -np.inf], np.nan)
    return df

def resolve_local_for_etl(path_value: str) -> str:
    return ensure_local_file(path_value, temp_subdir="etl_input")

def get_size_for_etl(path_value: str) -> int:
    local_path = resolve_local_for_etl(path_value)
    return os.path.getsize(local_path)

def get_excel_row_count_for_etl(path_value: str) -> int | None:
    try:
        local_path = resolve_local_for_etl(path_value)
        df_temp = pd.read_excel(local_path, header=None, nrows=15)
        header_idx = df_temp.notna().sum(axis=1).idxmax()
        df = pd.read_excel(local_path, header=header_idx)
        df = df.dropna(how="all")
        return len(df)
    except Exception:
        return None

def read_and_normalize_excel(file_path: str, schema_name: str) -> pd.DataFrame:
    resolved_path = ensure_local_file(file_path, temp_subdir="etl_input")
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    df_temp = pd.read_excel(resolved_path, header=None, nrows=10)
    header_idx = df_temp.notna().sum(axis=1).idxmax()
    df = pd.read_excel(resolved_path, header=header_idx, dtype=str)

    return normalize_data(df, schema_name)


# =====================================================================
# MODULE: CLUSTER PROCESSING (XỬ LÝ CỤM QĐ)
# =====================================================================

def process_qd_cluster(tbmt: str, qd_original: str, units_in_cluster: list, schema_name: str):
    base_units = [u for u in units_in_cluster if u['relation_type'] == 'BASE']
    adj_units = [u for u in units_in_cluster if u['relation_type'] == 'ADJUSTMENT']
    rep_units = [u for u in units_in_cluster if u['relation_type'] == 'REPLACEMENT']
    indep_units = [u for u in units_in_cluster if u['relation_type'] == 'INDEPENDENT']

    files_to_archive = [] 

    # 1. TRƯỜNG HỢP KHÔNG CÓ CẤU HÌNH (INDEPENDENT)
    if indep_units or not base_units:
        all_dfs = []
        max_ver = "00"
        for u in units_in_cluster:
            try:
                df = read_and_normalize_excel(u['file_path'], schema_name)
                df['Mã TBMT'] = tbmt
                df['so_qd_sanitized'] = u['so_qd']
                df['qd_display'] = u['so_qd']
                df['version_code'] = u['version']
                max_ver = max(max_ver, u['version'], key=version_key)
                all_dfs.append(df)
            except Exception as e:
                logger.error(f"Lỗi đọc file INDEPENDENT {u['file_path']}: {e}")
        
        return pd.concat(all_dfs, ignore_index=True) if all_dfs else None, qd_original, max_ver, files_to_archive

    base = max(base_units, key=lambda x: version_key(x['version']))
    base_size = get_size_for_etl(base["file_path"])
    base_row_count_est = get_excel_row_count_for_etl(base["file_path"])

    # 2. NHÁNH ƯU TIÊN 1: CÓ QUYẾT ĐỊNH THAY THẾ (REPLACEMENT) -> CÓ ARCHIVE
    if rep_units:
        best_rep = max(rep_units, key=lambda x: version_key(x['version']))
        try:
            df_final = read_and_normalize_excel(best_rep['file_path'], schema_name)
        except Exception as e:
            logger.error(f"Lỗi đọc file REPLACEMENT {best_rep['file_path']}: {e}")
            return None, None, None, []

        final_qd_display = f"QĐ gốc: {base['so_qd']}, QĐ thay thế: {best_rep['so_qd']}"
        logger.info(f"🔄 [REPLACEMENT] {tbmt}: Đang dùng QĐ {best_rep['so_qd']} thay thế hoàn toàn cho {base['so_qd']}.")
        
        try:
            with get_db_connection() as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT file_path FROM packages 
                    WHERE ma_tbmt = %s AND so_qd = %s AND version = %s AND is_latest = 1
                """, (tbmt, base['so_qd'], base['version']))
                
                all_base_files = cur.fetchall()
                for (fp,) in all_base_files:
                    files_to_archive.append(fp)
        except Exception as e:
            logger.error(f"⚠️ Lỗi khi truy vấn lấy danh sách file Archive: {e}")
            for bu in base_units:
                files_to_archive.append(bu['file_path'])

        df_final['Mã TBMT'] = tbmt
        df_final['so_qd_sanitized'] = best_rep['so_qd']
        df_final['qd_display'] = final_qd_display
        df_final['version_code'] = best_rep['version']
        
        return df_final, final_qd_display, best_rep['version'], files_to_archive

    # 3. NHÁNH 2: CHỈ CÓ QUYẾT ĐỊNH ĐIỀU CHỈNH (ADJUSTMENT) -> KHÔNG ARCHIVE
    enriched_adjs = []
    adj_units_sorted = sorted(adj_units, key=lambda x: version_key(x['version']))
    
    for a in adj_units_sorted:
        try:
            df_adj = read_and_normalize_excel(a['file_path'], schema_name)
            adj_size = get_size_for_etl(a["file_path"])

            enriched_adjs.append({'unit': a, 'df': df_adj, 'rows': len(df_adj), 'size': adj_size})
        except Exception:
            continue

    if enriched_adjs:
        adj_raw_names = [a['unit']['so_qd'] for a in enriched_adjs]
        final_qd_display = f"QĐ gốc: {base['so_qd']}, QĐ điều chỉnh: {', '.join(adj_raw_names)}"
        last_adj = enriched_adjs[-1]

        if (
            (base_size > 0 and last_adj['size'] >= base_size * 0.9)
            or (
                base_row_count_est is not None
                and base_row_count_est > 0
                and last_adj['rows'] >= base_row_count_est * 0.9
            )
        ):
            logger.info(
                f"🔄 [REPLACE-ADJUSTMENT-SIZE] {tbmt}: QĐ điều chỉnh cuối "
                f"{last_adj['unit']['so_qd']} đủ lớn để ghi đè QĐ gốc mà không cần đọc BASE trước."
            )
            df_final = last_adj['df']
            df_final['Mã TBMT'] = tbmt
            df_final['so_qd_sanitized'] = last_adj['unit']['so_qd']
            df_final['qd_display'] = final_qd_display
            df_final['version_code'] = last_adj['unit']['version']
            return df_final, final_qd_display, last_adj['unit']['version'], []

    try:
        df_base = read_and_normalize_excel(base['file_path'], schema_name)
        base_rows = len(df_base)
    except Exception as e:
        logger.error(f"Lỗi đọc QĐ gốc {base['file_path']}: {e}")
        return None, None, None, []

    if not enriched_adjs:
        df_base['Mã TBMT'] = tbmt
        df_base['so_qd_sanitized'] = base['so_qd']
        df_base['qd_display'] = f"QĐ gốc: {base['so_qd']}"
        df_base['version_code'] = base['version']
        return df_base, f"QĐ gốc: {base['so_qd']}", base['version'], []

    last_adj = enriched_adjs[-1]
    is_replace = (last_adj['rows'] >= base_rows * 0.9) or (base_size > 0 and last_adj['size'] >= base_size * 0.9)

    if is_replace:
        logger.info(f"🔄 [REPLACE-ADJUSTMENT] {tbmt}: QĐ điều chỉnh ghi đè hoàn toàn QĐ gốc.")
        df_final = last_adj['df']
        df_final['Mã TBMT'] = tbmt
        df_final['so_qd_sanitized'] = last_adj['unit']['so_qd']
        df_final['qd_display'] = final_qd_display
        df_final['version_code'] = last_adj['unit']['version']
        
        return df_final, final_qd_display, last_adj['unit']['version'], []

    logger.info(f"🧩 [PATCH-ADJUSTMENT] {tbmt}: Đang vá {len(enriched_adjs)} QĐ điều chỉnh vào QĐ gốc...")
    df_base['_merge_key'] = generate_row_hash(df_base, schema_name)
    
    for adj in enriched_adjs:
        df_adj = adj['df']
        df_adj['_merge_key'] = generate_row_hash(df_adj, schema_name)
        
        adj_keys = set(df_adj['_merge_key'].dropna())
        adj_keys = {k for k in adj_keys if str(k).strip() not in ("FB_", "PRI_")}
        df_base = df_base[~df_base['_merge_key'].isin(adj_keys)]
        df_base = pd.concat([df_base, df_adj], ignore_index=True)
        
    df_final = df_base.drop(columns=['_merge_key'])
    df_final['Mã TBMT'] = tbmt
    df_final['so_qd_sanitized'] = last_adj['unit']['so_qd']
    df_final['qd_display'] = final_qd_display
    df_final['version_code'] = last_adj['unit']['version']
    
    return df_final, final_qd_display, last_adj['unit']['version'], []
    
# =====================================================================
# MODULE: DATABASE OPERATIONS
# =====================================================================

def cleanup_orphaned_data():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version
                    FROM packages 
                    WHERE is_latest = 0
                """)
                rows = cursor.fetchall()
                
                if not rows:
                    logger.info("🧹 Không có Unit rác/cũ nào cần dọn dẹp hôm nay.")
                    return
                    
                invalid_units_tuple = tuple(rows)
                logger.info(f"🧹 Đang dọn dẹp {len(rows)} Unit rác/cũ khỏi DB...")
                
                for schema_name, config in SCHEMAS.items():
                    if "table_name" in config:
                        table_name = config["table_name"]
                        db_map = config.get("db_mapping", {})
                        
                        db_tbmt = db_map.get('Mã TBMT', 'ma_tbmt')
                        db_qd = db_map.get('so_qd_sanitized', 'so_qd')
                        db_ver = db_map.get('version_code', 'version') # Giờ Map chuẩn cả 3
                        
                        cursor.execute(f"""
                            DELETE FROM {table_name} 
                            WHERE ({db_tbmt}, {db_qd}, {db_ver}) IN %s
                        """, (invalid_units_tuple,))

                cursor.execute("""
                    DELETE FROM daily_manifest 
                    WHERE (ma_tbmt, so_qd, version) IN %s
                """, (invalid_units_tuple,))
                
                conn.commit()
                logger.info("✅ Dọn dẹp data rác thành công.")
                
    except Exception as e:
        logger.error(f"⚠️ Lỗi khi dọn dẹp data cũ: {e}")

def mark_manifest_processed(ids_list: list):
    if not ids_list: return
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE daily_manifest SET status='PROCESSED' WHERE id IN %s", (tuple(ids_list),))
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi update status manifest: {e}")

def ensure_indexes(conn, table_name: str, index_columns: list):
    if not index_columns: return
    try:
        with conn.cursor() as cursor:
            for col in index_columns:
                idx_name = f"idx_{table_name}_{col}"
                cursor.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name}("{col}")')
            conn.commit()
        logger.info(f"   ⚡ Đã kiểm tra/tạo Index cho bảng '{table_name}'.")
    except Exception as e:
        logger.error(f"⚠️ Lỗi khi tạo Index cho bảng {table_name}: {e}")

import psycopg2.extras

def save_to_db(df: pd.DataFrame, schema_name: str) -> bool:
    if df.empty: 
        return False
        
    config = SCHEMAS[schema_name]
    table_name = config["table_name"]
    db_mapping = config["db_mapping"]
    index_columns = config.get("db_indexes", [])
    
    df_db = df.rename(columns=db_mapping)
    valid_cols = [c for c in df_db.columns if c in db_mapping.values()]
    df_db = df_db[valid_cols]
    
    if df_db.empty:
        return False

    columns = list(df_db.columns)
    values = [tuple(x) for x in df_db.to_numpy()]

    cols_str = ",".join(columns)
    unique_constraint = "uq_medicines" if table_name == "processed_medicines" else "uq_goods"
    
    insert_query = f"""
        INSERT INTO {table_name} ({cols_str}) 
        VALUES %s 
        ON CONFLICT ON CONSTRAINT {unique_constraint} 
        DO NOTHING;
    """

    engine = get_engine()
    conn = get_db_connection()
    try:
        db_tbmt = db_mapping.get('Mã TBMT', 'ma_tbmt')
        db_qd = db_mapping.get('so_qd_sanitized', 'so_qd')
        db_ver = db_mapping.get('version_code', 'version')
        
        unit_list = df[['Mã TBMT', 'so_qd_sanitized', 'version_code']].drop_duplicates().values.tolist()
        unit_tuple = tuple(tuple(x) for x in unit_list)
        
        with conn.cursor() as cursor:
            if unit_tuple:
                cursor.execute(f"""
                    DELETE FROM {table_name} 
                    WHERE ({db_tbmt}, {db_qd}, {db_ver}) IN %s
                """, (unit_tuple,))
            
            psycopg2.extras.execute_values(
                cursor, insert_query, values, template=None, page_size=1000
            )
            
        conn.commit()
        logger.info(f"✅ Ghi DB thành công (đã bỏ qua dòng trùng) vào bảng '{table_name}'.")
        
        ensure_indexes(conn, table_name, index_columns)
        return True
        
    except Exception as e:
        logger.error(f"❌ Lỗi ghi DB ({table_name}): {e}")
        conn.rollback()
        return False
    finally: 
        conn.close()
        engine.dispose()

# =====================================================================
# HÀM BỔ TRỢ: LÀM SẠCH METADATA
# =====================================================================

def clean_vnd_to_numeric(x):
    if pd.isna(x) or x is None: return None
    s = str(x).strip()
    if s == "" or s.lower() in ("nan", "none"): return None
    s = re.sub(r"(?i)\s*vnđ?|\s*vnd", "", s).strip()
    s = re.sub(r"[^\d]", "", s)
    return s if s else None

def extract_province(text):
    if pd.isna(text) or text is None: return None
    match = re.search(r'(TP\.|Tp\.|Thành phố|Tỉnh)\s*([A-Za-zÀ-ỹ\s]+?)(?=\s*[,;.\d]|$)', text)
    if match:
        prefix = match.group(1)
        province_name = match.group(2).strip()
        if prefix in ['TP.', 'Tp.']:
            prefix = 'Thành phố'
        result = f"{prefix} {province_name}"
        return result.replace(";", "").strip()
    return str(text).strip()

def parse_ddmmyyyy(d):
    if pd.isna(d) or d is None: return None
    s = str(d).strip()
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except:
        return None

def compute_end_date(ngay_phe_duyet_str, thoi_gian_str):
    start = parse_ddmmyyyy(ngay_phe_duyet_str)
    if not start: return None

    if pd.isna(thoi_gian_str) or thoi_gian_str is None:
        return None

    s_time = str(thoi_gian_str).lower().strip()
    m = re.search(r"(\d+)\s*(ngày|tháng)", s_time)
    if not m: return None

    val = int(m.group(1))
    unit = m.group(2)

    if unit == "ngày":
        end = start + pd.Timedelta(days=val)
    else:  
        end = start + relativedelta(months=val)

    if isinstance(end, pd.Timestamp):
        end = end.date()

    return end.strftime("%Y-%m-%d")

# =====================================================================
# HÀM CHÍNH: CẬP NHẬT TOÀN BỘ METADATA TRONG DB (AUTO-SYNC)
# =====================================================================

def sync_and_clean_all_metadata():
    logger.info("🔄 Đang quét và đồng bộ lại toàn bộ bảng package_metadata...")
    
    today_date = datetime.now().date()
    updated_count = 0

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    ALTER TABLE package_metadata 
                    ADD COLUMN IF NOT EXISTS tinh_trang_hieu_luc TEXT;
                """)
                
                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version, 
                           gia_goi_thau, ngay_phe_duyet, thoi_gian_thuc_hien, dia_diem, ngay_het_hieu_luc
                    FROM package_metadata
                    WHERE EXISTS (
                        SELECT 1
                        FROM daily_manifest m
                        WHERE m.manifest_date = %s
                          AND m.ma_tbmt = package_metadata.ma_tbmt
                          AND m.so_qd = package_metadata.so_qd
                          AND m.version = package_metadata.version
                    )
                """, (TARGET_DATE,))
                rows = cursor.fetchall()
                
                for row in rows:
                    ma_tbmt, so_qd, version, gia_raw, ngay_pd_raw, tg_thuc_hien_raw, dia_diem_raw, ngay_het_hl_db = row
                    
                    gia_clean = clean_vnd_to_numeric(gia_raw)
                    dia_diem_clean = extract_province(dia_diem_raw)
                    ngay_het_hl_calc = compute_end_date(ngay_pd_raw, tg_thuc_hien_raw)
                    
                    tinh_trang = "KHÔNG XÁC ĐỊNH"
                    if ngay_het_hl_calc:
                        end_dt = datetime.strptime(ngay_het_hl_calc, "%Y-%m-%d").date()
                        tinh_trang = "CÒN HIỆU LỰC" if end_dt >= today_date else "HẾT HIỆU LỰC"

                    cursor.execute("""
                        UPDATE package_metadata
                        SET 
                            gia_goi_thau = %s,
                            ngay_het_hieu_luc = %s::DATE,
                            tinh_trang_hieu_luc = %s,
                            dia_diem = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE ma_tbmt = %s AND so_qd = %s AND version = %s
                    """, (
                        gia_clean, 
                        ngay_het_hl_calc, 
                        tinh_trang, 
                        dia_diem_clean,
                        ma_tbmt, so_qd, version
                    ))
                    updated_count += 1
            
            conn.commit()
            logger.info(f"✨ Đã đồng bộ trạng thái Hiệu lực & Clean xong {updated_count} dòng Metadata.")

    except Exception as e:
        logger.error(f"⚠️ Lỗi trong quá trình Sync Metadata: {e}")

# =====================================================================
# MODULE: ETL PIPELINE ORCHESTRATION
# =====================================================================

def fix_vendor_group_header(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    df = df.copy()

    def is_blank(value) -> bool:
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value) -> str:
        return str(value).strip() if not pd.isna(value) else ""

    stt_col = next((c for c in df.columns if isinstance(c, str) and c.lower().strip() == "stt"), None)
    vendor_col = next((c for c in df.columns if is_vendor_group_column_name(c)), None)
    name_col = next((
        c for c in df.columns
        if isinstance(c, str) and any(token in c.lower() for token in ("tên hàng hóa", "danh mục hàng hóa", "tên thương mại"))
    ), None)
    amount_col = next((c for c in df.columns if isinstance(c, str) and "thành tiền" in c.lower()), None)
    goods_like = bool(name_col or amount_col or any(isinstance(c, str) and "đơn giá" in c.lower() for c in df.columns))

    if vendor_col:
        return df
    if not goods_like:
        return df

    vendor_col = "Nhà thầu trúng thầu"
    if vendor_col not in df.columns:
        df[vendor_col] = np.nan

    current_vendor = None
    current_group_root = None
    rows = []

    def stt_root(value) -> str:
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    for idx, (_, row) in enumerate(df.iterrows()):
        current = row.copy()
        next_row = df.iloc[idx + 1] if idx + 1 < len(df) else None
        detected_vendor_info = detect_single_value_goods_group_header(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            name_col=name_col,
            amount_col=amount_col,
        )
        if detected_vendor_info:
            detected_vendor, _ = detected_vendor_info
            current_vendor = detected_vendor
            current_group_root = stt_root(current.get(stt_col))
            continue

        current_root = stt_root(current.get(stt_col))
        if current_group_root and current_root and current_root != current_group_root:
            current_vendor = None
            current_group_root = None

        if current_vendor and is_blank(current.get(vendor_col)):
            current[vendor_col] = current_vendor

        if not current.isna().all():
            rows.append(current)

    if not rows:
        return df

    return pd.DataFrame(rows, columns=df.columns)


def apply_goods_trade_name_fallback(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    normalized_goods_name_cols = {"danh mục hàng hóa", "tên hàng hóa"}
    has_goods_name = any(clean_col_str(col) in normalized_goods_name_cols for col in df.columns)
    if has_goods_name:
        return df

    trade_col = next((col for col in df.columns if clean_col_str(col) == "tên thương mại"), None)
    if not trade_col:
        return df

    df = df.copy()
    df = df.rename(columns={trade_col: "Danh mục hàng hóa"})
    return df


def drop_invalid_goods_value_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    price_col = "Đơn giá trúng thầu (VND)"
    amount_col = "Thành tiền (VND)"
    quantity_col = "Khối lượng"

    if price_col not in df.columns and amount_col not in df.columns:
        return df

    df = df.copy()

    if quantity_col in df.columns:
        df[quantity_col] = clean_numeric_series(df[quantity_col])
    if price_col in df.columns:
        df[price_col] = clean_numeric_series(df[price_col])
    if amount_col in df.columns:
        df[amount_col] = clean_numeric_series(df[amount_col])

    if all(col in df.columns for col in [quantity_col, price_col, amount_col]):
        mask_missing = df[amount_col].isna()
        mask_has_inputs = df[quantity_col].notna() & df[price_col].notna()
        df.loc[mask_missing & mask_has_inputs, amount_col] = (
            df.loc[mask_missing & mask_has_inputs, quantity_col]
            * df.loc[mask_missing & mask_has_inputs, price_col]
        )

    price_series = df[price_col] if price_col in df.columns else pd.Series([np.nan] * len(df), index=df.index)
    amount_series = df[amount_col] if amount_col in df.columns else pd.Series([np.nan] * len(df), index=df.index)

    invalid_mask = (price_series.isna() & amount_series.isna())
    invalid_mask |= amount_series.notna() & (amount_series <= 0)

    return df.loc[~invalid_mask].copy()

def normalize_data(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    config = SCHEMAS[schema_name]
    target_cols = config["output_columns"]
    mapping_config = config.get("column_mapping", {})
    mandatory_cols = config.get("mandatory_columns", [])
    
    if schema_name in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        df = normalize_grouped_rows_generic(df, schema_name)
    if schema_name == "GOODS_STANDARD":
        df = apply_goods_trade_name_fallback(df)
        
    actual_mapping = get_smart_column_mapping(df.columns, mapping_config)
    df = df.rename(columns=actual_mapping)
    df = collapse_duplicate_columns(df)
    if schema_name == "GOODS_STANDARD":
        df = drop_invalid_goods_value_rows(df)
    
    missing = [col for col in mandatory_cols if col not in df.columns]
    if missing:
        logger.debug(f"Cột hiện có trong file: {list(df.columns)}")
        raise ValueError(f"Thiếu cột bắt buộc: {missing}")

    drop_cols = [k for k, v in mapping_config.items() if v is None and k in df.columns]
    df = df.drop(columns=drop_cols, errors='ignore')
    
    for col in target_cols:
        if col not in df.columns: df[col] = np.nan
            
    meta_cols = ['Mã TBMT', 'version_code', 'so_qd_sanitized']
    ordered_cols = [c for c in meta_cols if c in df.columns] + target_cols
    
    return df[ordered_cols]

def process_pipeline():
    start_time = time.time()
    logger.info(f"🚀 BẮT ĐẦU ETL PIPELINE [DỮ LIỆU NGÀY: {TARGET_DATE}]")
    print("="*60)
    
    sync_and_clean_all_metadata()
    cleanup_orphaned_data()
    
    with get_db_connection() as conn, conn.cursor() as c:
        ignored_qd_map = load_ignored_qd_map(c)
        # Lấy file READY để ETL, dùng COALESCE(so_qd_original, so_qd) vì bảng relations đã đổi tên cột
        c.execute("""
            SELECT COALESCE(r.so_qd_original, m.so_qd) as qd_original,
                   m.ma_tbmt,
                   m.schema_type,
                   m.id as manifest_id,
                   m.so_qd,
                   m.version,
                   m.full_path,
                   COALESCE(r.relation_type, 'INDEPENDENT') as relation_type
            FROM daily_manifest m
            LEFT JOIN qd_relations r 
              ON m.ma_tbmt = r.ma_tbmt AND m.so_qd = r.so_qd AND m.version = r.version
            WHERE m.manifest_date = %s AND m.status = 'READY'
              AND NOT EXISTS (
                  SELECT 1
                  FROM scan_anomalies a
                  WHERE a.scan_date = %s
                    AND a.status = 'PENDING'
                    AND a.ma_tbmt = m.ma_tbmt
                    AND (a.so_qd = 'ALL' OR a.so_qd = m.so_qd)
                    AND (a.version = 'ALL' OR a.version = m.version)
              )
        """, (TARGET_DATE, TARGET_DATE))
        active_jobs = [
            {
                "qd_original": row[0],
                "tbmt": row[1],
                "schema_type": row[2],
                "manifest_id": row[3],
                "so_qd": row[4],
                "version": row[5],
                "full_path": row[6],
                "relation_type": row[7],
            }
            for row in c.fetchall()
            if row[0] not in ignored_qd_map.get(row[1], set())
        ]

    if not active_jobs:
        logger.info(f"ℹ️ Không có dữ liệu 'READY' trong ngày {TARGET_DATE}.")
        return

    clusters = {}
    manifest_id_map = {}
    cluster_units_map = {}
    for job in active_jobs:
        qd_original = job["qd_original"]
        tbmt = job["tbmt"]
        schema_type = job["schema_type"]
        m_id = job["manifest_id"]
        if schema_type not in SCHEMAS: continue
        key = (tbmt, qd_original, schema_type)
        clusters[key] = True
        manifest_id_map.setdefault(key, []).append(m_id)
        cluster_units_map.setdefault(key, []).append({
            "so_qd": job["so_qd"],
            "version": job["version"],
            "file_path": job["full_path"],
            "relation_type": job["relation_type"],
        })

    total_inserted_clusters = 0

    with get_db_connection() as conn, conn.cursor() as c:
        for (tbmt, qd_original, schema_name) in clusters.keys():
            units_in_cluster = [
                unit
                for unit in cluster_units_map.get((tbmt, qd_original, schema_name), [])
                if not os.path.basename(str(unit["file_path"] or "")).startswith("~$")
            ]
            
            if not units_in_cluster:
                logger.warning(f"⚠️ ETL bỏ qua {tbmt} / {qd_original}: không tìm thấy unit READY hợp lệ trong manifest.")
                continue

            df_final, qd_display, cluster_ver, files_to_archive = process_qd_cluster(tbmt, qd_original, units_in_cluster, schema_name)
            if df_final is None or df_final.empty:
                logger.warning(f"⚠️ ETL bỏ qua {tbmt} / {qd_original}: không tạo được dataframe hợp lệ từ cụm QĐ.")
                continue
                
            df_final = apply_numeric_cleaning(df_final)
            
            df_final["_dedup_hash"] = generate_row_hash(df_final, schema_name)
            
            hash_str = df_final["_dedup_hash"].astype(str)
            valid_hash_mask = (hash_str.str.len() > 5) & (~hash_str.str.contains("Không có dữ liệu|nan|None", case=False, na=False))
            
            df_valid = df_final[valid_hash_mask].drop_duplicates(subset=["_dedup_hash"], keep='last')
            df_invalid = df_final[~valid_hash_mask]
            
            df_final = pd.concat([df_valid, df_invalid], ignore_index=True)
            df_final = df_final.drop(columns=["_dedup_hash"])
            if '_merge_key' in df_final.columns:
                df_final = df_final.drop(columns=['_merge_key'])

            success = save_to_db(df_final, schema_name)
            
            if success:
                ids = manifest_id_map[(tbmt, qd_original, schema_name)]
                mark_manifest_processed(ids)
                total_inserted_clusters += 1
            
                for fpath in files_to_archive:
                    try:
                        if is_r2_key(fpath):
                            filename = os.path.basename(fpath)
                            parts = fpath.replace("\\", "/").split("/")
                            if "latest" in parts:
                                idx = parts.index("latest")
                                new_key = "/".join(parts[:idx] + ["archive"] + parts[idx+1:])
                            else:
                                new_key = fpath
                            if new_key != fpath:
                                move_object(fpath, new_key)
                                c.execute("""
                                    UPDATE packages
                                    SET is_latest = 0, file_path = %s
                                    WHERE file_path = %s
                                """, (new_key, fpath))
                                conn.commit()
                        else:
                            if os.path.exists(fpath):
                                current_latest_dir = os.path.dirname(fpath)
                                current_day_dir = os.path.dirname(current_latest_dir)
                                correct_archive_dir = os.path.join(current_day_dir, "archive")
                                os.makedirs(correct_archive_dir, exist_ok=True)
                                new_path = os.path.join(correct_archive_dir, os.path.basename(fpath))
                                shutil.move(fpath, new_path)
                                c.execute("""
                                    UPDATE packages
                                    SET is_latest = 0, file_path = %s
                                    WHERE file_path = %s
                                """, (new_path, fpath))
                                conn.commit()
                    except Exception as e:
                        logger.warning(f"Không thể archive file {fpath}: {e}")
            else:
                logger.warning(f"⚠️ ETL không ghi được DB cho {tbmt} / {qd_original} ({schema_name}). Manifest sẽ giữ trạng thái READY.")

    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"🎉 HOÀN TẤT ETL: Xử lý thành công {total_inserted_clusters} Cụm QĐ. Tổng thời gian: {elapsed_time}s.")

# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("            ETL PIPELINE BÓC TÁCH DỮ LIỆU MUASAMCONG")
    print("="*60)

    parser = argparse.ArgumentParser(description="Chạy Pipeline ETL cho MuaSamCong.")
    parser.add_argument('-d', '--date', type=str, help="Ngày cần chạy ETL (Định dạng YYYYMMDD).")
    args = parser.parse_args()

    default_date = datetime.now().strftime("%Y%m%d")

    if args.date:
        TARGET_DATE = args.date
    else:
        user_input = input(f"📅 Nhập ngày cần xử lý (YYYYMMDD) [Enter = Hôm nay {default_date}]: ").strip()
        TARGET_DATE = user_input if user_input else default_date

    try:
        get_db_connection().close()
        process_pipeline()
    except Exception as e:
        logger.error(f"❌ KHÔNG THỂ KHỞI CHẠY PIPELINE: {e}")
