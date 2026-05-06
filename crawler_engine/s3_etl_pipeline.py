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
from drug_group_parser import build_drug_group_filter_array
from web_winner_facts import (
    WebWinnerManualReviewRequired,
    apply_vendor_single_winner_fallback,
    clear_web_winner_fact_cache,
    prefetch_web_winner_facts,
)
import logging
import warnings
from schema_normalization_shared import (
    KEYWORD_RULES as SHARED_KEYWORD_RULES,
    build_schema_mapping_config as shared_build_schema_mapping_config,
    clean_col_str as shared_clean_col_str,
    clean_numeric_series as shared_clean_numeric_series,
    collapse_duplicate_columns as shared_collapse_duplicate_columns,
    count_excel_rows_with_detected_header,
    drop_header_legend_rows as shared_drop_header_legend_rows,
    drop_invalid_value_rows as shared_drop_invalid_value_rows,
    get_smart_column_mapping as shared_get_smart_column_mapping,
    load_excel_with_detected_header,
    normalize_header_lookup_key,
)

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
warnings.filterwarnings(
    "ignore",
    message=r"Cannot parse header or footer so it will be ignored",
    category=UserWarning,
    module="openpyxl.worksheet.header_footer",
)
warnings.filterwarnings(
    "ignore",
    message=r"Unknown extension is not supported and will be removed",
    category=UserWarning,
    module=r"openpyxl\.worksheet\._reader",
)
warnings.filterwarnings(
    "ignore",
    message=r"Conditional Formatting extension is not supported and will be removed",
    category=UserWarning,
    module=r"openpyxl\.worksheet\._reader",
)

# =====================================================================
# CẤU HÌNH HỆ THỐNG & KẾT NỐI DATABASE
# =====================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

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


def fetch_relation_peer_jobs(cursor, active_jobs: list[dict], ignored_qd_map: dict) -> list[dict]:
    """Bring cross-day relation peers into today's ETL cluster when their files are available."""
    seed_schema_map = {}
    for job in active_jobs:
        if job.get("relation_type") in ("INDEPENDENT", "CANCELLATION", "TYPO_ERROR"):
            continue
        tbmt = job.get("tbmt")
        qd_original = job.get("qd_original")
        schema_type = job.get("schema_type")
        if tbmt and qd_original and schema_type in SCHEMAS:
            seed_schema_map.setdefault((tbmt, qd_original), set()).add(schema_type)

    if not seed_schema_map:
        return []

    cursor.execute("""
        SELECT
            r.ma_tbmt,
            r.so_qd_original,
            r.so_qd,
            r.version,
            r.relation_type,
            p.file_path,
            pm.ten_goi_thau
        FROM qd_relations r
        LEFT JOIN LATERAL (
            SELECT p2.file_path
            FROM packages p2
            WHERE p2.ma_tbmt = r.ma_tbmt
              AND p2.so_qd = r.so_qd
              AND p2.version = r.version
              AND p2.file_type = 'excel'
              AND COALESCE(p2.status, '') <> 'ARCHIVED'
            ORDER BY p2.is_latest DESC, p2.crawled_at DESC NULLS LAST, p2.file_path
            LIMIT 1
        ) p ON TRUE
        LEFT JOIN package_metadata pm
          ON pm.ma_tbmt = r.ma_tbmt
         AND pm.so_qd = r.so_qd
         AND pm.version = r.version
        WHERE (r.ma_tbmt, r.so_qd_original) IN %s
          AND r.relation_type <> 'TYPO_ERROR'
    """, (tuple(seed_schema_map.keys()),))

    peer_jobs = []
    for tbmt, qd_original, so_qd, version, relation_type, file_path, ten_goi_thau in cursor.fetchall():
        if so_qd in ignored_qd_map.get(tbmt, set()):
            continue
        if relation_type != "CANCELLATION" and not file_path:
            logger.warning(
                f"⚠️ [RELATION-PEER-MISSING-FILE] {tbmt} / {so_qd} / v{version}: "
                "không tìm thấy Excel trong packages để đưa vào cluster ETL liên ngày."
            )
            continue
        for schema_type in seed_schema_map.get((tbmt, qd_original), set()):
            peer_jobs.append({
                "qd_original": qd_original,
                "tbmt": tbmt,
                "schema_type": schema_type,
                "manifest_id": None,
                "so_qd": so_qd,
                "version": version,
                "full_path": file_path,
                "relation_type": relation_type,
                "ten_goi_thau": ten_goi_thau,
                "relation_peer": True,
            })

    return peer_jobs


def expand_active_jobs_with_relation_peers(cursor, active_jobs: list[dict], ignored_qd_map: dict) -> list[dict]:
    peer_jobs = fetch_relation_peer_jobs(cursor, active_jobs, ignored_qd_map)
    if not peer_jobs:
        return active_jobs

    merged = {}
    for job in active_jobs + peer_jobs:
        key = (job["tbmt"], job["so_qd"], job["version"], job["schema_type"])
        if key not in merged or (merged[key].get("manifest_id") is None and job.get("manifest_id") is not None):
            merged[key] = job

    added_count = sum(1 for job in merged.values() if job.get("relation_peer") and job.get("manifest_id") is None)
    if added_count:
        logger.info(f"🔗 Đã bổ sung {added_count} relation peer liên ngày vào cluster ETL.")
    return list(merged.values())


def ensure_qd_display_columns(cursor):
    cursor.execute("ALTER TABLE processed_medicines ADD COLUMN IF NOT EXISTS qd_display TEXT")
    cursor.execute("ALTER TABLE processed_goods ADD COLUMN IF NOT EXISTS qd_display TEXT")


RELATION_REPLACEMENT_DELETE_SQL_TEMPLATE = """
WITH relation_clusters AS (
    SELECT
        base.ma_tbmt,
        base.so_qd_original,
        base.so_qd AS source_so_qd,
        base.version AS source_version,
        rep.so_qd AS replacement_so_qd,
        rep.version AS replacement_version
    FROM qd_relations base
    JOIN qd_relations rep
      ON rep.ma_tbmt = base.ma_tbmt
     AND rep.so_qd_original = base.so_qd_original
     AND rep.relation_type = 'REPLACEMENT'
    WHERE base.relation_type IN ('BASE', 'ADJUSTMENT')
),
rows_to_delete AS (
    SELECT DISTINCT p.id
    FROM {table_name} p
    JOIN relation_clusters rc
      ON p.ma_tbmt = rc.ma_tbmt
     AND p.so_qd = rc.source_so_qd
     AND p.version = rc.source_version
    WHERE EXISTS (
        SELECT 1
        FROM {table_name} target
        WHERE target.ma_tbmt = rc.ma_tbmt
          AND target.so_qd = rc.replacement_so_qd
          AND target.version = rc.replacement_version
    )
),
deleted AS (
    DELETE FROM {table_name} p
    USING rows_to_delete d
    WHERE p.id = d.id
    RETURNING p.id
)
SELECT COUNT(*) FROM deleted;
"""


RELATION_PASS_THROUGH_DELETE_SQL_TEMPLATE = """
WITH pass_through_units AS (
    SELECT ma_tbmt, so_qd, version
    FROM qd_relations
    WHERE relation_type IN ('CANCELLATION', 'TYPO_ERROR')
),
deleted AS (
    DELETE FROM {table_name} p
    USING pass_through_units u
    WHERE p.ma_tbmt = u.ma_tbmt
      AND p.so_qd = u.so_qd
      AND p.version = u.version
    RETURNING p.id
)
SELECT COUNT(*) FROM deleted;
"""


RELATION_ADJUSTMENT_DUPLICATE_DELETE_SQL_TEMPLATE = """
WITH relation_clusters AS (
    SELECT
        base.ma_tbmt,
        base.so_qd_original,
        base.so_qd AS base_so_qd,
        base.version AS base_version,
        rel.so_qd AS target_so_qd,
        rel.version AS target_version
    FROM qd_relations base
    JOIN qd_relations rel
      ON rel.ma_tbmt = base.ma_tbmt
     AND rel.so_qd_original = base.so_qd_original
     AND rel.relation_type = 'ADJUSTMENT'
    WHERE base.relation_type = 'BASE'
),
duplicate_base_rows AS (
    SELECT DISTINCT b.id
    FROM {table_name} b
    JOIN relation_clusters rc
      ON b.ma_tbmt = rc.ma_tbmt
     AND b.so_qd = rc.base_so_qd
     AND b.version = rc.base_version
    JOIN {table_name} t
      ON t.ma_tbmt = rc.ma_tbmt
     AND t.so_qd = rc.target_so_qd
     AND t.version = rc.target_version
     AND (
            (
                NULLIF(BTRIM(b.ma_phan_lo), '') IS NOT NULL
                AND NULLIF(BTRIM(t.ma_phan_lo), '') IS NOT NULL
                AND b.ma_phan_lo = t.ma_phan_lo
            )
            OR
            (
                (
                    NULLIF(BTRIM(b.ma_phan_lo), '') IS NULL
                    OR NULLIF(BTRIM(t.ma_phan_lo), '') IS NULL
                )
                AND {fallback_match}
            )
        )
),
deleted AS (
    DELETE FROM {table_name} p
    USING duplicate_base_rows d
    WHERE p.id = d.id
    RETURNING p.id
)
SELECT COUNT(*) FROM deleted;
"""


QD_DISPLAY_UPDATE_SQL_TEMPLATE = """
WITH cluster_summary AS (
    SELECT
        ma_tbmt,
        so_qd_original,
        MAX(so_qd) FILTER (WHERE relation_type = 'BASE') AS base_qd,
        STRING_AGG(so_qd, '; ' ORDER BY COALESCE(NULLIF(SUBSTRING(so_qd FROM '[0-9]+'), '')::NUMERIC, 0), so_qd)
            FILTER (WHERE relation_type = 'CANCELLATION') AS cancellation_qds,
        STRING_AGG(so_qd, ', ' ORDER BY COALESCE(NULLIF(SUBSTRING(so_qd FROM '[0-9]+'), '')::NUMERIC, 0), so_qd)
            FILTER (WHERE relation_type = 'ADJUSTMENT') AS adj_qds,
        STRING_AGG(so_qd, ', ' ORDER BY COALESCE(NULLIF(SUBSTRING(so_qd FROM '[0-9]+'), '')::NUMERIC, 0), so_qd)
            FILTER (WHERE relation_type = 'REPLACEMENT') AS rep_qds
    FROM qd_relations
    WHERE relation_type <> 'TYPO_ERROR'
    GROUP BY ma_tbmt, so_qd_original
),
display_map AS (
    SELECT
        r.ma_tbmt,
        r.so_qd,
        r.version,
        CASE
            WHEN COALESCE(cs.rep_qds, '') <> '' THEN
                CONCAT(
                    'QĐ gốc: ',
                    COALESCE(cs.base_qd, r.so_qd_original),
                    '; QĐ thay thế: ',
                    cs.rep_qds,
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            WHEN COALESCE(cs.adj_qds, '') <> '' THEN
                CONCAT(
                    'QĐ gốc: ',
                    COALESCE(cs.base_qd, r.so_qd_original),
                    '; QĐ điều chỉnh: ',
                    cs.adj_qds,
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            WHEN COALESCE(cs.base_qd, '') <> '' THEN
                CONCAT(
                    cs.base_qd,
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            WHEN COALESCE(cs.cancellation_qds, '') <> '' AND r.relation_type <> 'CANCELLATION' THEN
                CONCAT(r.so_qd, '; ', cs.cancellation_qds)
            ELSE r.so_qd
        END AS qd_display
    FROM qd_relations r
    JOIN cluster_summary cs
      ON cs.ma_tbmt = r.ma_tbmt
     AND cs.so_qd_original = r.so_qd_original
    WHERE r.relation_type <> 'TYPO_ERROR'
),
updated AS (
    UPDATE {table_name} p
    SET qd_display = dm.qd_display
    FROM display_map dm
    WHERE p.ma_tbmt = dm.ma_tbmt
      AND p.so_qd = dm.so_qd
      AND p.version = dm.version
      AND COALESCE(p.qd_display, '') IS DISTINCT FROM COALESCE(dm.qd_display, '')
    RETURNING p.id
)
SELECT COUNT(*) FROM updated;
"""


QD_DISPLAY_FALLBACK_SQL_TEMPLATE = """
WITH updated AS (
    UPDATE {table_name}
    SET qd_display = so_qd
    WHERE COALESCE(BTRIM(qd_display), '') = ''
      AND COALESCE(BTRIM(so_qd), '') <> ''
    RETURNING id
)
SELECT COUNT(*) FROM updated;
"""


ORPHAN_DUPLICATE_FLAGS_DELETE_SQL_TEMPLATE = """
WITH deleted AS (
    DELETE FROM processed_duplicate_flags f
    WHERE f.dataset_scope = %s
      AND NOT EXISTS (
          SELECT 1
          FROM {table_name} p
          WHERE p.id = f.processed_row_id
      )
    RETURNING f.id
)
SELECT COUNT(*) FROM deleted;
"""


def run_scalar(cursor, sql: str) -> int:
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def run_scalar_params(cursor, sql: str, params: tuple) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def reconcile_processed_relations() -> dict:
    stats = {}
    fallback_matches = {
        "processed_medicines": """
                LOWER(BTRIM(COALESCE(b.ten_thuoc, ''))) = LOWER(BTRIM(COALESCE(t.ten_thuoc, '')))
                AND COALESCE(b.so_luong, -1) = COALESCE(t.so_luong, -1)
                AND COALESCE(b.don_gia_trung_thau, -1) = COALESCE(t.don_gia_trung_thau, -1)
        """,
        "processed_goods": """
                LOWER(BTRIM(COALESCE(b.danh_muc_hang_hoa, ''))) = LOWER(BTRIM(COALESCE(t.danh_muc_hang_hoa, '')))
                AND COALESCE(b.khoi_luong, -1) = COALESCE(t.khoi_luong, -1)
                AND COALESCE(b.don_gia_trung_thau, -1) = COALESCE(t.don_gia_trung_thau, -1)
        """,
    }
    dataset_scopes = {
        "processed_medicines": "medicine",
        "processed_goods": "goods",
    }

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                ensure_qd_display_columns(cursor)
                for table_name, fallback_match in fallback_matches.items():
                    stats[f"{table_name}_pass_through_deleted"] = run_scalar(
                        cursor,
                        RELATION_PASS_THROUGH_DELETE_SQL_TEMPLATE.format(table_name=table_name),
                    )
                    stats[f"{table_name}_replacement_deleted"] = run_scalar(
                        cursor,
                        RELATION_REPLACEMENT_DELETE_SQL_TEMPLATE.format(table_name=table_name),
                    )
                    stats[f"{table_name}_adjustment_duplicates_deleted"] = run_scalar(
                        cursor,
                        RELATION_ADJUSTMENT_DUPLICATE_DELETE_SQL_TEMPLATE.format(
                            table_name=table_name,
                            fallback_match=fallback_match,
                        ),
                    )
                    stats[f"{table_name}_qd_display_updated"] = run_scalar(
                        cursor,
                        QD_DISPLAY_UPDATE_SQL_TEMPLATE.format(table_name=table_name),
                    )
                    stats[f"{table_name}_qd_display_fallback"] = run_scalar(
                        cursor,
                        QD_DISPLAY_FALLBACK_SQL_TEMPLATE.format(table_name=table_name),
                    )
                    stats[f"{table_name}_orphan_duplicate_flags_deleted"] = run_scalar_params(
                        cursor,
                        ORPHAN_DUPLICATE_FLAGS_DELETE_SQL_TEMPLATE.format(table_name=table_name),
                        (dataset_scopes[table_name],),
                    )
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi reconciliation qd_relations sau ETL: {e}")
        return stats

    changed = {key: value for key, value in stats.items() if value}
    if changed:
        logger.info(f"🧹 Reconcile qd_relations hoàn tất: {changed}")
    else:
        logger.info("🧹 Reconcile qd_relations hoàn tất: không có thay đổi.")
    return stats

# =====================================================================
# TỪ KHÓA MAPPING & DATA CLEANING
# =====================================================================
KEYWORD_RULES = SHARED_KEYWORD_RULES

def clean_col_str(s: str) -> str:
    return shared_clean_col_str(s)


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
    return shared_get_smart_column_mapping(df_columns, mapping_config)


def build_schema_mapping_config(config: dict) -> dict:
    return shared_build_schema_mapping_config(config)

def clean_numeric_series(series: pd.Series) -> pd.Series:
    return shared_clean_numeric_series(series)


def collapse_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    return shared_collapse_duplicate_columns(df)


def is_blank_cell(value) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str):
        return clean_col_str(value) in {"", "nan", "none", "<na>", "nat"}
    return False


def analyze_review_column_gaps(df: pd.DataFrame, schema_name: str) -> list[dict]:
    if df is None or df.empty:
        return []

    config = SCHEMAS[schema_name]
    review_cols = config.get("review_columns") or config.get("output_columns", [])
    gap_details = []
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)
    summary_like_mask = df.apply(lambda row: _is_summary_like_row_for_review(row, amount_col), axis=1)
    review_df = df.loc[~summary_like_mask].copy()
    total_rows = len(review_df.index)

    if total_rows == 0:
        return []

    for col in review_cols:
        blank_count = total_rows
        if col not in review_df.columns:
            gap_details.append({
                "column": col,
                "blank_count": total_rows,
                "total_rows": total_rows,
            })
            continue

        blank_mask = review_df[col].map(is_blank_cell)
        blank_count = int(blank_mask.sum())
        if blank_count > 0:
            gap_details.append({
                "column": col,
                "blank_count": blank_count,
                "total_rows": total_rows,
            })

    return gap_details


def log_pending_review_summary(flagged_units: list[dict], context_label: str, limit: int = 50):
    if not flagged_units:
        logger.info(f"✅ {context_label}: không có unit nào bị chuyển sang PENDING_ETL_REVIEW.")
        return

    logger.warning(
        f"📋 {context_label}: có {len(flagged_units)} unit bị chuyển sang PENDING_ETL_REVIEW."
    )

    for item in flagged_units[:limit]:
        gaps = item.get("column_gaps", [])
        cols_display = ", ".join(
            f"{gap['column']}({gap['blank_count']}/{gap['total_rows']})"
            for gap in gaps
        )
        issue_reason = str(item.get("issue_reason") or "").strip()
        if cols_display:
            detail_display = f"column_gaps = [{cols_display}]"
        elif issue_reason:
            detail_display = f"issue_reason = {issue_reason}"
        else:
            detail_display = "column_gaps = [N/A]"
        logger.warning(
            f"   - TBMT = {item.get('ma_tbmt')} | so_qd = {item.get('so_qd')} | "
            f"version = {item.get('version')} | schema = {item.get('schema_name')} | "
            f"{detail_display}"
        )

    remaining = len(flagged_units) - limit
    if remaining > 0:
        logger.warning(f"   ... và còn {remaining} unit khác.")


def is_bdg_package_title(package_title: str | None) -> bool:
    if not package_title:
        return False

    title_clean = clean_col_str(str(package_title))
    if "biệt dược gốc" in title_clean:
        return True
    return re.search(r"\bbdg\b", title_clean, flags=re.IGNORECASE) is not None


def apply_bdg_group_fill_rule(df: pd.DataFrame, package_title: str | None, schema_name: str) -> pd.DataFrame:
    if df is None or df.empty or schema_name != "MEDICINE_STANDARD":
        return df
    if not is_bdg_package_title(package_title):
        return df
    if "Nhóm thuốc" not in df.columns:
        return df

    df = df.copy()
    df["Nhóm thuốc"] = df["Nhóm thuốc"].astype("string")
    blank_mask = df["Nhóm thuốc"].map(is_blank_cell)
    filled_count = int(blank_mask.sum())
    if filled_count <= 0:
        return df

    df.loc[blank_mask, "Nhóm thuốc"] = "BDG"
    logger.info(
        f"🩹 [BDG-RULE] MEDICINE_STANDARD: điền 'BDG' cho {filled_count} dòng thiếu 'Nhóm thuốc' "
        f"vì tên gói thầu khớp biệt dược gốc."
    )
    return df


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
        if text_lower.startswith(("tổng cộng", "cộng tổng", "thành tiền", "số tiền bằng chữ", "giá trị bằng chữ", "cộng")):
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
    "tổng",
    "tổng cộng",
    "cộng tổng",
    "thành tiền",
    "số tiền bằng chữ",
    "giá trị bằng chữ",
    "cộng",
)

SUMMARY_ROW_EXACT_LABELS = (
    "cộng",
    "tổng",
    "cộng tổng",
)

SUMMARY_ROW_SUFFIX_LABELS = (
    "cộng tổng",
    "tổng cộng",
    "tổng giá",
    "tổng tiền",
    "tổng số",
    "thành tiền",
    "bằng tiền",
    "số tiền bằng chữ",
    "giá trị bằng chữ",
)


def _is_blank_cell(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def _clean_cell_text(value) -> str:
    return str(value).strip() if not pd.isna(value) else ""


def _normalize_summary_text(value) -> str:
    text = _clean_cell_text(value).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :;,-")


def _extract_summary_label_base(text: str) -> str | None:
    normalized = _normalize_summary_text(text)
    if not normalized or _is_numeric_like_text(normalized):
        return None

    for label in sorted(SUMMARY_ROW_SUFFIX_LABELS, key=len, reverse=True):
        if normalized == label:
            return label
        if normalized.startswith(label + ":") or normalized.startswith(label + "-") or normalized.startswith(label + ";"):
            return label
        if normalized.startswith(label + " "):
            return label

    for label in SUMMARY_ROW_EXACT_LABELS:
        if normalized == label:
            return label
        if normalized.startswith(label + ":") or normalized.startswith(label + "-") or normalized.startswith(label + ";"):
            return label

    return None


def _is_summary_label_text(text: str) -> bool:
    return _extract_summary_label_base(text) is not None


def _is_summary_candidate_column(row: pd.Series, col_name, amount_col=None, max_label_col_idx: int = 5) -> bool:
    if row is None:
        return False
    col_clean = clean_col_str(col_name)
    if amount_col and col_clean == clean_col_str(amount_col):
        return True
    try:
        col_idx = list(row.index).index(col_name)
    except ValueError:
        return False
    return col_idx < max_label_col_idx


def _looks_like_amount_in_words_text(text: str) -> bool:
    normalized = _normalize_summary_text(text)
    if not normalized:
        return False
    if "đồng" not in normalized:
        return False
    if len(normalized) < 12:
        return False
    if _is_numeric_like_text(normalized):
        return False
    amount_words_markers = (
        "mươi", "trăm", "nghìn", "ngàn", "triệu", "tỷ", "chục",
        "linh", "lẻ", "mốt", "mươi", "mười",
    )
    return any(marker in normalized for marker in amount_words_markers)


def _is_summary_like_row_for_review(row: pd.Series, amount_col=None, max_non_blank: int = 4) -> bool:
    if row is None:
        return False

    populated_cells = [
        (col, _clean_cell_text(value))
        for col, value in row.items()
        if not _is_blank_cell(value)
    ]
    if not populated_cells or len(populated_cells) > max_non_blank:
        return False

    has_summary_label = False
    has_amount_value = False
    has_unit_price_value = False
    has_other_numeric_value = False
    numeric_value_count = 0

    for col, text in populated_cells:
        col_clean = clean_col_str(col)
        if _is_summary_label_text(text) and _is_summary_candidate_column(row, col, amount_col):
            has_summary_label = True
        if amount_col and col_clean == clean_col_str(amount_col) and _is_numeric_like_text(text):
            has_amount_value = True
            numeric_value_count += 1
            continue
        if "đơn giá" in col_clean and _is_numeric_like_text(text):
            has_unit_price_value = True
            numeric_value_count += 1
            continue
        if _is_numeric_like_text(text):
            has_other_numeric_value = True
            numeric_value_count += 1

    if not has_summary_label:
        return False
    if has_other_numeric_value:
        return False
    if has_amount_value:
        return True
    if has_unit_price_value and numeric_value_count == 1:
        return True
    return numeric_value_count == 0


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


def _extract_group_label_from_stt(value):
    text = _normalize_stt_value(value)
    if not text:
        return None

    match = re.match(r"^(\d+)\s*\.\s*(.+)$", text)
    if not match:
        return None

    label = re.sub(r"\s+", " ", match.group(2)).strip(" .:-")
    if not label or _is_numeric_like_text(label):
        return None

    if _is_summary_label_text(label):
        return None

    return {
        "root": match.group(1),
        "text": label,
    }


def _is_section_marker_stt(value) -> bool:
    text = _normalize_stt_value(value)
    if not text:
        return False
    text = text.strip(" .:-)")
    return bool(re.fullmatch(r"[ivxlcdm]+", text, flags=re.IGNORECASE))


def _extract_sparse_stt_text_label(value):
    text = _normalize_stt_value(value)
    if not text:
        return None
    if _is_section_marker_stt(text):
        return None
    if _is_numeric_like_text(text):
        return None

    label = re.sub(r"\s+", " ", text).strip(" .:-")
    if not label:
        return None

    if _is_summary_label_text(label):
        return None

    roman_match = re.match(r"^(?P<prefix>[ivxlcdm]+)\s*[\.\-:)]\s*(?P<label>.+)$", label, flags=re.IGNORECASE)
    if roman_match:
        inner_label = re.sub(r"\s+", " ", roman_match.group("label")).strip(" .:-")
        if inner_label and not _is_numeric_like_text(inner_label):
            return {
                "root": None,
                "text": inner_label,
            }

    if re.match(r"^[A-Za-zÀ-ỹ].+", label):
        return {
            "root": None,
            "text": label,
        }

    return None


def _matches_group_target(col_name, target_name) -> bool:
    col_clean = clean_col_str(col_name)
    target_clean = clean_col_str(target_name)
    if col_clean == target_clean:
        return True
    if normalize_header_lookup_key(col_name) == normalize_header_lookup_key(target_name):
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
        group_targets = ["Mã phần/lô", "Tên phần/lô", "Nhà thầu trúng thầu"]
        auto_create_target = "Nhà thầu trúng thầu"
        autofill_source_targets = ["Mã phần/lô", "Tên phần/lô", "Nhà thầu trúng thầu"]
    else:
        detail_cols = [c for c in df.columns if "tên thuốc" in clean_col_str(c)]
        group_targets = ["Mã phần/lô", "Nhà thầu trúng thầu", "Nhóm thuốc"]
        auto_create_target = "Nhà thầu trúng thầu"
        autofill_source_targets = ["Mã phần/lô", "Nhà thầu trúng thầu", "Nhóm thuốc"]

    existing_group_cols = [
        c for c in df.columns
        if any(_matches_group_target(c, target) for target in group_targets)
    ]
    autofill_source_cols = [
        c for c in df.columns
        if any(_matches_group_target(c, target) for target in autofill_source_targets)
    ]

    return {
        "stt_col": stt_col,
        "amount_col": amount_col,
        "detail_cols": detail_cols,
        "group_targets": group_targets,
        "existing_group_cols": existing_group_cols,
        "autofill_source_cols": autofill_source_cols,
        "auto_create_target": auto_create_target,
    }


def is_generic_summary_row(row: pd.Series, amount_col=None) -> bool:
    if row is None:
        return False

    non_blank_count = sum(not _is_blank_cell(v) for v in row.tolist())
    if non_blank_count == 0 or non_blank_count > 4:
        return False

    populated_cells = [
        (col, _clean_cell_text(value))
        for col, value in row.items()
        if not _is_blank_cell(value)
    ]
    if not populated_cells:
        return False

    non_numeric_text_cells = [
        (col, text)
        for col, text in populated_cells
        if text and not _is_numeric_like_text(text)
    ]
    if len(non_numeric_text_cells) == 1:
        text_col, text_value = non_numeric_text_cells[0]
        numeric_cols = [
            col for col, text in populated_cells
            if text and _is_numeric_like_text(text)
        ]
        has_amount_like_numeric = any(
            (amount_col and clean_col_str(col) == clean_col_str(amount_col))
            or ("đơn giá" in clean_col_str(col))
            or ("thành tiền" in clean_col_str(col))
            for col in numeric_cols
        )
        if _looks_like_amount_in_words_text(text_value) and has_amount_like_numeric:
            return True

    summary_label_cells = []
    other_text_cells = []
    for col, text in populated_cells:
        if not text:
            continue
        if _is_numeric_like_text(text):
            continue
        if _is_summary_label_text(text):
            if not _is_summary_candidate_column(row, col, amount_col):
                return False
            summary_label_cells.append((col, text))
            continue
        other_text_cells.append((col, text))

    if not summary_label_cells:
        return False

    non_label_text_cells = [
        (col, text)
        for col, text in other_text_cells
        if not (amount_col and clean_col_str(col) == clean_col_str(amount_col))
    ]
    if non_label_text_cells:
        summary_bases = {
            _extract_summary_label_base(text)
            for _, text in summary_label_cells
        }
        by_words_row = bool(summary_bases & {"số tiền bằng chữ", "giá trị bằng chữ", "bằng tiền"})
        if not by_words_row:
            return False

    return _is_summary_like_row_for_review(row, amount_col, max_non_blank=4)


def is_summary_continuation_row(row: pd.Series, prev_row: pd.Series | None, amount_col=None) -> bool:
    if prev_row is None or not is_generic_summary_row(prev_row, amount_col):
        return False

    populated_cells = [
        (col, _clean_cell_text(value))
        for col, value in row.items()
        if not _is_blank_cell(value)
    ]
    if not populated_cells or len(populated_cells) > 3:
        return False

    for col, text in populated_cells:
        if not _is_numeric_like_text(text):
            return False
        if amount_col and clean_col_str(col) == clean_col_str(amount_col):
            continue
        if "thành tiền" in clean_col_str(col) or "đơn giá" in clean_col_str(col):
            continue
    return True


def drop_summary_rows(df: pd.DataFrame, amount_col=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    keep_mask = []
    prev_row = None
    for _, row in df.iterrows():
        is_summary = is_generic_summary_row(row, amount_col) or is_summary_continuation_row(row, prev_row, amount_col)
        keep_mask.append(not is_summary)
        prev_row = row
    return df.loc[keep_mask].reset_index(drop=True)


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


def _is_sparse_group_candidate_row(current: pd.Series, amount_col=None) -> bool:
    if current is None:
        return False
    non_blank_count = sum(not _is_blank_cell(v) for v in current.tolist())
    if non_blank_count == 0 or non_blank_count > 3:
        return False
    return not is_generic_summary_row(current, amount_col)


def detect_true_group_header_generic(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    detail_cols,
    group_cols,
    amount_col=None,
):
    if current is None or next_row is None or not group_cols:
        return None

    current_stt = _normalize_stt_value(current.get(stt_col)) if stt_col else ""
    stt_group_label = _extract_group_label_from_stt(current.get(stt_col)) if stt_col else None
    if not stt_group_label and stt_col:
        stt_group_label = _extract_sparse_stt_text_label(current.get(stt_col))
    if current_stt and not _is_top_level_stt(current_stt) and not stt_group_label:
        return None

    if any(not _is_blank_cell(current.get(col)) for col in detail_cols):
        return None

    if not _is_sparse_group_candidate_row(current, amount_col):
        return None

    source_group_cols = [col for col in group_cols if not _is_blank_cell(current.get(col))]
    if not source_group_cols:
        return None

    if current_stt and not stt_group_label and stt_col and not _belongs_same_group(current_stt, next_row.get(stt_col)):
        return None

    autofill_context = _detect_shape_autofill_context(
        current=current,
        next_row=next_row,
        source_cols=source_group_cols,
        detail_cols=detail_cols,
        extra_allowed_cols=[
            stt_col,
            amount_col,
            *[col for col in current.index if "đơn giá" in clean_col_str(col)],
        ],
        amount_col=amount_col,
    )
    if not autofill_context:
        return None

    return {
        "root": None if stt_group_label or not current_stt or (stt_col and _is_section_marker_stt(current.get(stt_col))) else _stt_root_value(current_stt),
        "carry_values": autofill_context["carry_values"],
        "source_cols": autofill_context["source_cols"],
    }


def detect_wrong_column_group_header_generic(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    detail_cols,
    group_cols,
    amount_col=None,
):
    if current is None or next_row is None:
        return None

    current_stt = _normalize_stt_value(current.get(stt_col)) if stt_col else ""
    current_has_stt = bool(current_stt)
    stt_group_label = _extract_group_label_from_stt(current.get(stt_col)) if stt_col else None
    if not stt_group_label and stt_col:
        stt_group_label = _extract_sparse_stt_text_label(current.get(stt_col))
    if current_has_stt and not _is_top_level_stt(current_stt) and not stt_group_label:
        return None

    if not _is_sparse_group_candidate_row(current, amount_col):
        return None

    if not has_detail_signal_generic(next_row, detail_cols, amount_col):
        return None

    if (
        current_has_stt
        and not stt_group_label
        and stt_col
        and not _is_section_marker_stt(current.get(stt_col))
        and not _belongs_same_group(current_stt, next_row.get(stt_col))
    ):
        next_stt = _normalize_stt_value(next_row.get(stt_col))
        if current_has_stt or not next_stt:
            return None

    texts = []
    source_cols = []
    if stt_group_label:
        texts.append(stt_group_label["text"])
        source_cols.append(stt_col)

    for col in current.index:
        if col == stt_col or col == amount_col:
            continue
        text = _clean_cell_text(current.get(col))
        if not text or _is_numeric_like_text(text):
            continue
        if _is_summary_label_text(text):
            continue
        texts.append(text)
        source_cols.append(col)

    if not texts:
        return None

    normalized_unique = {re.sub(r"\s+", " ", text).strip().lower() for text in texts}
    if len(normalized_unique) != 1:
        return None

    next_non_blank = sum(not _is_blank_cell(v) for v in next_row.tolist())
    current_non_blank = sum(not _is_blank_cell(v) for v in current.tolist())
    if next_non_blank <= current_non_blank:
        return None

    return {
        "root": None if stt_group_label or (stt_col and _is_section_marker_stt(current.get(stt_col))) else (_stt_root_value(current_stt) if current_has_stt else None),
        "text": texts[0],
        "source_cols": source_cols,
    }


def merge_pseudo_group_rows_generic(df: pd.DataFrame, stt_col, detail_cols, amount_col=None) -> pd.DataFrame:
    if df.empty or not stt_col:
        return df

    def can_strictly_complement(current: pd.Series, next_row: pd.Series) -> bool:
        next_non_blank = []
        for col in df.columns:
            value = next_row.get(col)
            if _is_blank_cell(value):
                continue
            if col == stt_col:
                return False
            if amount_col and col == amount_col:
                # Same total amount often appears on split rows; do not use it
                # as a reason to merge, but also do not treat it as a conflict.
                continue
            current_value = current.get(col)
            if not _is_blank_cell(current_value):
                return False
            next_non_blank.append(col)
        return bool(next_non_blank)

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
            next_is_summary_like = is_generic_summary_row(next_row, amount_col) or _is_summary_like_row_for_review(next_row, amount_col)
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
            should_merge = (
                current_has_stt
                and not next_has_stt
                and same_amount
                and next_has_detail
                and not next_is_group_header
                and not next_is_summary_like
                and can_strictly_complement(current, next_row)
            )

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
                should_merge = (
                    same_stt_group
                    and current_has_name
                    and sparse_current
                    and richer_next
                    and not next_is_summary_like
                    and can_strictly_complement(current, next_row)
                )

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


def detect_autofill_group_header_row(
    current: pd.Series,
    next_row: pd.Series | None,
    stt_col,
    detail_cols,
    source_cols,
    amount_col=None,
):
    extra_allowed_cols = []
    if stt_col:
        extra_allowed_cols.append(stt_col)
    extra_allowed_cols.extend([
        col for col in current.index
        if "đơn giá" in clean_col_str(col)
    ])
    if amount_col:
        extra_allowed_cols.append(amount_col)
    return _detect_shape_autofill_context(
        current=current,
        next_row=next_row,
        source_cols=source_cols,
        detail_cols=detail_cols,
        extra_allowed_cols=extra_allowed_cols,
        amount_col=amount_col,
    )


def _detect_shape_autofill_context(
    current: pd.Series,
    next_row: pd.Series | None,
    source_cols: list[str],
    detail_cols: list[str],
    extra_allowed_cols: list[str] | None = None,
    amount_col=None,
):
    if current is None or next_row is None or not source_cols:
        return None
    if is_generic_summary_row(current, amount_col):
        return None
    if not has_detail_signal_generic(next_row, detail_cols, amount_col):
        return None
    if any(not _is_blank_cell(current.get(col)) for col in detail_cols):
        return None

    carry_values = {
        col: current.get(col)
        for col in source_cols
        if col in current.index and not _is_blank_cell(current.get(col))
    }
    if not carry_values:
        return None

    allowed_cols = {col for col in source_cols if col in current.index}
    for col in extra_allowed_cols or []:
        if col in current.index:
            allowed_cols.add(col)

    current_populated = [col for col, value in current.items() if not _is_blank_cell(value)]
    if not current_populated:
        return None
    if any(col not in allowed_cols for col in current_populated):
        return None

    if any(not _is_blank_cell(next_row.get(col)) for col in carry_values):
        return None

    next_populated = [col for col, value in next_row.items() if not _is_blank_cell(value)]
    if len(next_populated) <= len(current_populated):
        return None

    complement_cols = [col for col in next_populated if col not in carry_values]
    if not complement_cols:
        return None

    return {
        "root": None,
        "carry_values": carry_values,
        "source_cols": list(carry_values.keys()),
    }


def normalize_grouped_rows_generic(df: pd.DataFrame, schema_type: str):
    if df is None or df.empty:
        return df

    working_df = df.copy()
    settings = get_group_row_engine_settings(working_df, schema_type)
    stt_col = settings["stt_col"]
    detail_cols = settings["detail_cols"]
    amount_col = settings["amount_col"]
    group_cols = list(settings["existing_group_cols"])
    autofill_source_cols = list(settings["autofill_source_cols"])
    auto_create_target = settings["auto_create_target"]

    if not stt_col or not detail_cols:
        return working_df

    total_mask = []
    prev_row = None
    for _, row in working_df.iterrows():
        is_total_row = is_generic_summary_row(row, amount_col) or is_summary_continuation_row(row, prev_row, amount_col)
        total_mask.append(is_total_row)
        prev_row = row
    total_mask = pd.Series(total_mask, index=working_df.index)
    working_df = working_df.loc[~total_mask].reset_index(drop=True)
    if working_df.empty:
        return working_df

    current_context = None
    normalized_rows = []

    for idx, (_, row) in enumerate(working_df.iterrows()):
        current = row.copy()
        next_row = working_df.iloc[idx + 1] if idx + 1 < len(working_df) else None

        autofill_group = detect_autofill_group_header_row(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            detail_cols=detail_cols,
            source_cols=autofill_source_cols,
            amount_col=amount_col,
        )
        if autofill_group:
            current_context = autofill_group
            continue

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
    
def apply_numeric_cleaning(df: pd.DataFrame, schema_name: str | None = None) -> pd.DataFrame:
    df = collapse_duplicate_columns(df)
    str_cols = df.select_dtypes(include=['object']).columns
    for c in str_cols:
        normalized = df[c].astype("string").str.strip().str.lstrip('\'"')
        df[c] = normalized.mask(normalized.isin(["nan", "None", "<NA>", "NaT"]), pd.NA)
        
    cols_num = ['Số lượng', 'Khối lượng', 'Đơn giá trúng thầu (VND)', 'Thành tiền (VND)']
    for c in cols_num:
        if c in df.columns: 
            df[c] = clean_numeric_series(df[c])

    amount_col = "Thành tiền (VND)"
    price_col = "Đơn giá trúng thầu (VND)"
    quantity_col = "Khối lượng"
    if schema_name == "MEDICINE_STANDARD":
        quantity_col = "Số lượng"

    if quantity_col in df.columns and price_col in df.columns:
        if amount_col not in df.columns:
            df[amount_col] = np.nan
        mask_missing = df[amount_col].isna()
        mask_has_inputs = df[quantity_col].notna() & df[price_col].notna()
        df.loc[mask_missing & mask_has_inputs, amount_col] = (
            df.loc[mask_missing & mask_has_inputs, quantity_col]
            * df.loc[mask_missing & mask_has_inputs, price_col]
        )

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
        return count_excel_rows_with_detected_header(local_path)
    except Exception:
        return None

def read_and_normalize_excel(file_path: str, schema_name: str, tbmt=None, so_qd=None, version=None) -> pd.DataFrame:
    resolved_path = ensure_local_file(file_path, temp_subdir="etl_input")
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    df = load_excel_with_detected_header(
        resolved_path,
        dtype=str,
    )

    return normalize_data(df, schema_name, tbmt=tbmt, so_qd=so_qd, version=version)


# =====================================================================
# MODULE: CLUSTER PROCESSING (XỬ LÝ CỤM QĐ)
# =====================================================================

def process_qd_cluster(tbmt: str, qd_original: str, units_in_cluster: list, schema_name: str):
    base_units = [u for u in units_in_cluster if u['relation_type'] == 'BASE']
    adj_units = [u for u in units_in_cluster if u['relation_type'] == 'ADJUSTMENT']
    rep_units = [u for u in units_in_cluster if u['relation_type'] == 'REPLACEMENT']
    indep_units = [u for u in units_in_cluster if u['relation_type'] == 'INDEPENDENT']
    cancellation_units = [u for u in units_in_cluster if u['relation_type'] == 'CANCELLATION']

    files_to_archive = [] 

    def qd_number_sort_key(qd_value):
        match = re.search(r"\d+", str(qd_value or ""))
        return (int(match.group(0)) if match else 0, str(qd_value or ""))

    def ordered_qds(values):
        ordered = []
        for qd in sorted(values or [], key=qd_number_sort_key):
            qd_text = str(qd or "").strip()
            if qd_text and qd_text not in ordered:
                ordered.append(qd_text)
        return ordered

    def join_qds(values, separator=", "):
        return separator.join(ordered_qds(values))

    def build_qd_display(main_qd: str | None, cancellation_qds: list[str] | None = None) -> str:
        ordered = []
        if main_qd:
            ordered.append(str(main_qd).strip())
        for qd in ordered_qds(cancellation_qds):
            qd_text = str(qd or "").strip()
            if qd_text and qd_text not in ordered:
                ordered.append(qd_text)
        return "; ".join(ordered)

    def build_relation_qd_display(base_qd: str | None, relation_label: str, relation_qds: list[str],
                                  cancellation_qds: list[str] | None = None) -> str:
        parts = [f"QĐ gốc: {str(base_qd or qd_original).strip()}"]
        relation_text = join_qds(relation_qds)
        if relation_text:
            parts.append(f"{relation_label}: {relation_text}")
        cancellation_text = join_qds(cancellation_qds, separator="; ")
        if cancellation_text:
            parts.append(cancellation_text)
        return "; ".join(parts)

    cancellation_qds = ordered_qds([u["so_qd"] for u in cancellation_units])

    # 1. TRƯỜNG HỢP KHÔNG CÓ CẤU HÌNH (INDEPENDENT)
    if indep_units or not base_units:
        all_dfs = []
        max_ver = "00"
        processable_units = [
            u for u in units_in_cluster
            if u.get("relation_type") != "CANCELLATION"
        ]
        for u in processable_units:
            try:
                df = read_and_normalize_excel(
                    u['file_path'],
                    schema_name,
                    tbmt=tbmt,
                    so_qd=u['so_qd'],
                    version=u['version'],
                )
                df['Mã TBMT'] = tbmt
                df['so_qd_sanitized'] = u['so_qd']
                df['qd_display'] = build_qd_display(u['so_qd'], cancellation_qds)
                df['version_code'] = u['version']
                max_ver = max(max_ver, u['version'], key=version_key)
                all_dfs.append(df)
            except WebWinnerManualReviewRequired:
                raise
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
            df_final = read_and_normalize_excel(
                best_rep['file_path'],
                schema_name,
                tbmt=tbmt,
                so_qd=best_rep['so_qd'],
                version=best_rep['version'],
            )
        except WebWinnerManualReviewRequired:
            raise
        except Exception as e:
            logger.error(f"Lỗi đọc file REPLACEMENT {best_rep['file_path']}: {e}")
            return None, None, None, []

        final_qd_display = build_relation_qd_display(
            base['so_qd'],
            "QĐ thay thế",
            [u["so_qd"] for u in rep_units],
            cancellation_qds,
        )
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
            df_adj = read_and_normalize_excel(
                a['file_path'],
                schema_name,
                tbmt=tbmt,
                so_qd=a['so_qd'],
                version=a['version'],
            )
            adj_size = get_size_for_etl(a["file_path"])

            enriched_adjs.append({'unit': a, 'df': df_adj, 'rows': len(df_adj), 'size': adj_size})
        except WebWinnerManualReviewRequired:
            raise
        except Exception:
            continue

    if enriched_adjs:
        adj_raw_names = [a['unit']['so_qd'] for a in enriched_adjs]
        final_qd_display = build_relation_qd_display(
            base['so_qd'],
            "QĐ điều chỉnh",
            adj_raw_names,
            cancellation_qds,
        )
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
        df_base = read_and_normalize_excel(
            base['file_path'],
            schema_name,
            tbmt=tbmt,
            so_qd=base['so_qd'],
            version=base['version'],
        )
        base_rows = len(df_base)
    except WebWinnerManualReviewRequired:
        raise
    except Exception as e:
        logger.error(f"Lỗi đọc QĐ gốc {base['file_path']}: {e}")
        return None, None, None, []

    if not enriched_adjs:
        df_base['Mã TBMT'] = tbmt
        df_base['so_qd_sanitized'] = base['so_qd']
        df_base['qd_display'] = build_qd_display(base['so_qd'], cancellation_qds)
        df_base['version_code'] = base['version']
        return df_base, build_qd_display(base['so_qd'], cancellation_qds), base['version'], []

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
                    DELETE FROM processed_duplicate_flags
                    WHERE (ma_tbmt, so_qd, version) IN %s
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
                cursor.execute(
                    "UPDATE daily_manifest SET status='PROCESSED' WHERE id IN %s AND status IS DISTINCT FROM 'PROCESSED'",
                    (tuple(ids_list),)
                )
                cursor.execute("""
                    DELETE FROM manifest_issues
                    WHERE issue_date = %s
                      AND (ma_tbmt, so_qd, version) IN (
                          SELECT ma_tbmt, so_qd, version
                          FROM daily_manifest
                          WHERE id IN %s
                      )
                """, (TARGET_DATE, tuple(ids_list)))
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi update status manifest: {e}")


def mark_manifest_pending_review(ids_list: list):
    if not ids_list:
        return
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE daily_manifest SET status='PENDING_ETL_REVIEW' WHERE id IN %s AND status IS DISTINCT FROM 'PENDING_ETL_REVIEW'",
                    (tuple(ids_list),)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi update status manifest sang PENDING_ETL_REVIEW: {e}")


def save_manifest_issue_records(issue_records: list[dict]):
    if not issue_records:
        return

    unique_records = {
        (item["ma_tbmt"], item["so_qd"], item["version"], item["issue_type"]): item
        for item in issue_records
    }

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for item in unique_records.values():
                    cursor.execute("""
                        INSERT INTO manifest_issues
                        (issue_date, ma_tbmt, so_qd, version, filename, issue_type, issue_reason, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT ON CONSTRAINT uq_manifest_issues
                        DO UPDATE SET
                            filename = EXCLUDED.filename,
                            issue_reason = EXCLUDED.issue_reason,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE manifest_issues.filename IS DISTINCT FROM EXCLUDED.filename
                           OR manifest_issues.issue_reason IS DISTINCT FROM EXCLUDED.issue_reason
                    """, (
                        item.get("issue_date") or TARGET_DATE,
                        item["ma_tbmt"],
                        item["so_qd"],
                        item["version"],
                        item.get("filename"),
                        item["issue_type"],
                        item["issue_reason"],
                    ))
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi lưu manifest issue từ ETL: {e}")


def delete_processed_units(schema_name: str, units: list[dict]):
    if not units:
        return

    config = SCHEMAS[schema_name]
    table_name = config["table_name"]
    dataset_scope = "medicine" if table_name == "processed_medicines" else "goods"
    db_mapping = config["db_mapping"]
    db_tbmt = db_mapping.get('Mã TBMT', 'ma_tbmt')
    db_qd = db_mapping.get('so_qd_sanitized', 'so_qd')
    db_ver = db_mapping.get('version_code', 'version')
    unit_tuple = tuple(
        (unit["tbmt"], unit["so_qd"], unit["version"])
        for unit in units
        if unit.get("tbmt") and unit.get("so_qd") and unit.get("version")
    )

    if not unit_tuple:
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM processed_duplicate_flags
                    WHERE dataset_scope = %s
                      AND (ma_tbmt, so_qd, version) IN %s
                """, (dataset_scope, unit_tuple))
                cursor.execute(f"""
                    DELETE FROM {table_name}
                    WHERE ({db_tbmt}, {db_qd}, {db_ver}) IN %s
                """, (unit_tuple,))
            conn.commit()
    except Exception as e:
        logger.error(f"⚠️ Lỗi xóa dữ liệu processed cũ ở {table_name}: {e}")


def refresh_duplicate_flags(cursor, table_name: str, unit_tuple):
    if not unit_tuple:
        return

    dataset_scope = "medicine" if table_name == "processed_medicines" else "goods"
    cursor.execute("""
        DELETE FROM processed_duplicate_flags
        WHERE dataset_scope = %s
          AND (ma_tbmt, so_qd, version) IN %s
    """, (dataset_scope, unit_tuple))

    if dataset_scope == "medicine":
        duplicate_key_sql = """
            md5(CONCAT_WS(
                '||',
                COALESCE(p.ma_tbmt, ''),
                COALESCE(p.so_qd, ''),
                COALESCE(p.version, ''),
                COALESCE(p.ma_phan_lo, ''),
                COALESCE(p.ma_thuoc, ''),
                COALESCE(p.ten_thuoc, ''),
                COALESCE(p.ten_hoat_chat, ''),
                COALESCE(p.nong_do_ham_luong, ''),
                COALESCE(p.duong_dung, ''),
                COALESCE(p.dang_bao_che, ''),
                COALESCE(p.quy_cach, ''),
                COALESCE(p.nhom_thuoc, ''),
                COALESCE(p.so_dk_gpnk, ''),
                COALESCE(p.so_luong::text, ''),
                COALESCE(p.don_gia_trung_thau::text, '')
            ))
        """
        partition_sql = """
            PARTITION BY
                p.ma_tbmt, p.so_qd, p.version,
                COALESCE(p.ma_phan_lo, ''),
                COALESCE(p.ma_thuoc, ''),
                COALESCE(p.ten_thuoc, ''),
                COALESCE(p.ten_hoat_chat, ''),
                COALESCE(p.nong_do_ham_luong, ''),
                COALESCE(p.duong_dung, ''),
                COALESCE(p.dang_bao_che, ''),
                COALESCE(p.quy_cach, ''),
                COALESCE(p.nhom_thuoc, ''),
                COALESCE(p.so_dk_gpnk, ''),
                COALESCE(p.so_luong::text, ''),
                COALESCE(p.don_gia_trung_thau::text, '')
        """
    else:
        duplicate_key_sql = """
            md5(CONCAT_WS(
                '||',
                COALESCE(p.ma_tbmt, ''),
                COALESCE(p.so_qd, ''),
                COALESCE(p.version, ''),
                COALESCE(p.ma_phan_lo, ''),
                COALESCE(p.danh_muc_hang_hoa, ''),
                COALESCE(p.nha_thau_trung_thau, ''),
                COALESCE(p.khoi_luong::text, ''),
                COALESCE(p.don_gia_trung_thau::text, ''),
                COALESCE(p.ky_ma_hieu_hash, ''),
                COALESCE(p.nhan_hieu_hash, ''),
                COALESCE(p.tinh_nang_ky_thuat_hash, '')
            ))
        """
        partition_sql = """
            PARTITION BY
                p.ma_tbmt, p.so_qd, p.version,
                COALESCE(p.ma_phan_lo, ''),
                COALESCE(p.danh_muc_hang_hoa, ''),
                COALESCE(p.nha_thau_trung_thau, ''),
                COALESCE(p.khoi_luong::text, ''),
                COALESCE(p.don_gia_trung_thau::text, ''),
                COALESCE(p.ky_ma_hieu_hash, ''),
                COALESCE(p.nhan_hieu_hash, ''),
                COALESCE(p.tinh_nang_ky_thuat_hash, '')
        """

    cursor.execute(f"""
        INSERT INTO processed_duplicate_flags (
            dataset_scope, processed_row_id, ma_tbmt, so_qd, version, duplicate_key, duplicate_count
        )
        SELECT
            %s,
            flagged.id,
            flagged.ma_tbmt,
            flagged.so_qd,
            flagged.version,
            flagged.duplicate_key,
            flagged.duplicate_count
        FROM (
            SELECT
                p.id,
                p.ma_tbmt,
                p.so_qd,
                p.version,
                {duplicate_key_sql} AS duplicate_key,
                COUNT(*) OVER (
                    {partition_sql}
                ) AS duplicate_count
            FROM {table_name} p
            WHERE (p.ma_tbmt, p.so_qd, p.version) IN %s
        ) flagged
        WHERE flagged.duplicate_count > 1
    """, (dataset_scope, unit_tuple))


def build_blank_count_sql_expr(column_name: str) -> str:
    return (
        f"SUM(CASE WHEN COALESCE(NULLIF(LOWER(BTRIM(p.\"{column_name}\"::text)), 'nan'), '') = '' "
        f"THEN 1 ELSE 0 END) AS \"blank__{column_name}\""
    )


def audit_processed_units_for_empty_review_columns(manifest_date: str | None = None):
    started_at = time.time()
    scope_label = manifest_date or "ALL_DATES"
    logger.info(f"🔎 BẮT ĐẦU AUDIT HỒI TỐ CỘT REVIEW RỖNG [PHẠM VI: {scope_label}]")

    total_units_scanned = 0
    total_units_flagged = 0
    flagged_summary = []

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            for schema_name, config in SCHEMAS.items():
                review_cols = config.get("review_columns", [])
                if not review_cols:
                    continue

                table_name = config["table_name"]
                db_mapping = config["db_mapping"]
                db_tbmt = db_mapping.get("Mã TBMT", "ma_tbmt")
                db_qd = db_mapping.get("so_qd_sanitized", "so_qd")
                db_ver = db_mapping.get("version_code", "version")

                count_exprs = ",\n                       ".join(
                    [ 'COUNT(p.*) AS total_rows' ] + [
                        build_blank_count_sql_expr(db_mapping[col])
                        for col in review_cols
                        if col in db_mapping
                    ]
                )
                if not count_exprs:
                    continue

                where_clause = "WHERE m.status = 'PROCESSED' AND m.schema_type = %s"
                params = [schema_name]
                if manifest_date:
                    where_clause += " AND m.manifest_date = %s"
                    params.append(manifest_date)

                cursor.execute(f"""
                    SELECT m.id,
                           m.manifest_date,
                           m.ma_tbmt,
                           m.so_qd,
                           m.version,
                           m.filename,
                           {count_exprs}
                    FROM daily_manifest m
                    LEFT JOIN {table_name} p
                      ON p.{db_tbmt} = m.ma_tbmt
                     AND p.{db_qd} = m.so_qd
                     AND p.{db_ver} = m.version
                    {where_clause}
                    GROUP BY m.id, m.manifest_date, m.ma_tbmt, m.so_qd, m.version, m.filename
                    ORDER BY m.manifest_date, m.ma_tbmt, m.so_qd, m.version
                """, tuple(params))

                rows = cursor.fetchall()
                if not rows:
                    logger.info(f"ℹ️ Audit {schema_name}: không có unit PROCESSED trong phạm vi {scope_label}.")
                    continue

                total_units_scanned += len(rows)
                flagged_ids = []
                delete_units = []
                issue_records = []

                for row in rows:
                    manifest_id, issue_date, tbmt, so_qd, version, filename, *counts = row
                    total_rows = int(counts[0] or 0)
                    gap_counts = counts[1:]
                    column_gaps = [
                        {
                            "column": review_col,
                            "blank_count": int(blank_count or 0),
                            "total_rows": total_rows,
                        }
                        for review_col, blank_count in zip(review_cols, gap_counts)
                        if int(blank_count or 0) > 0
                    ]
                    if not column_gaps:
                        continue

                    flagged_ids.append(manifest_id)
                    delete_units.append({
                        "tbmt": tbmt,
                        "so_qd": so_qd,
                        "version": version,
                    })
                    issue_records.append({
                        "issue_date": issue_date,
                        "ma_tbmt": tbmt,
                        "so_qd": so_qd,
                        "version": version,
                        "filename": filename,
                        "issue_type": "ETL_REVIEW_COLUMN_GAPS",
                        "issue_reason": "Các cột review có dòng trống sau ETL: " + ", ".join(
                            f"{gap['column']} ({gap['blank_count']}/{gap['total_rows']})"
                            for gap in column_gaps
                        ),
                    })
                    flagged_summary.append({
                        "ma_tbmt": tbmt,
                        "so_qd": so_qd,
                        "version": version,
                        "schema_name": schema_name,
                        "column_gaps": column_gaps,
                    })

                if not flagged_ids:
                    logger.info(f"✅ Audit {schema_name}: không phát hiện unit nào thiếu cột review trong phạm vi {scope_label}.")
                    continue

                delete_processed_units(schema_name, delete_units)
                cursor.execute(
                    "UPDATE daily_manifest SET status='PENDING_ETL_REVIEW' WHERE id IN %s AND status IS DISTINCT FROM 'PENDING_ETL_REVIEW'",
                    (tuple(flagged_ids),)
                )
                conn.commit()
                save_manifest_issue_records(issue_records)

                total_units_flagged += len(flagged_ids)
                logger.warning(
                    f"⚠️ Audit {schema_name}: phát hiện {len(flagged_ids)} unit cần review lại trong phạm vi {scope_label}."
                )

    elapsed = round(time.time() - started_at, 2)
    logger.info(
        f"🏁 HOÀN TẤT AUDIT HỒI TỐ: đã quét {total_units_scanned} unit, "
        f"đánh dấu {total_units_flagged} unit cần review. Thời gian: {elapsed}s."
    )
    log_pending_review_summary(flagged_summary, f"TỔNG KẾT AUDIT HỒI TỐ [{scope_label}]")

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

def save_to_db(df: pd.DataFrame, schema_name: str, delete_units: list[dict] | None = None) -> bool:
    if df.empty: 
        return False
        
    config = SCHEMAS[schema_name]
    table_name = config["table_name"]
    db_mapping = config["db_mapping"]
    index_columns = config.get("db_indexes", [])
    
    df_db = df.rename(columns=db_mapping)
    valid_cols = [c for c in df_db.columns if c in db_mapping.values()]
    df_db = df_db[valid_cols]

    if table_name == "processed_medicines":
        df_db["nhom_thuoc_filter"] = df_db.get("nhom_thuoc", pd.Series([None] * len(df_db))).map(
            build_drug_group_filter_array
        )
    
    if df_db.empty:
        return False

    df_db = df_db.astype(object).where(pd.notna(df_db), None)
    columns = list(df_db.columns)
    values = [tuple(x) for x in df_db.to_numpy()]

    cols_str = ",".join(columns)
    insert_query = f"""
        INSERT INTO {table_name} ({cols_str}) 
        VALUES %s;
    """

    engine = get_engine()
    conn = get_db_connection()
    try:
        db_tbmt = db_mapping.get('Mã TBMT', 'ma_tbmt')
        db_qd = db_mapping.get('so_qd_sanitized', 'so_qd')
        db_ver = db_mapping.get('version_code', 'version')
        
        if delete_units:
            unit_list = [
                [item.get("tbmt"), item.get("so_qd"), item.get("version")]
                for item in delete_units
                if item.get("tbmt") and item.get("so_qd") and item.get("version")
            ]
        else:
            unit_list = df[['Mã TBMT', 'so_qd_sanitized', 'version_code']].drop_duplicates().values.tolist()
        unit_tuple = tuple(dict.fromkeys(tuple(x) for x in unit_list))
        
        with conn.cursor() as cursor:
            if unit_tuple:
                dataset_scope = "medicine" if table_name == "processed_medicines" else "goods"
                cursor.execute("""
                    DELETE FROM processed_duplicate_flags
                    WHERE dataset_scope = %s
                      AND (ma_tbmt, so_qd, version) IN %s
                """, (dataset_scope, unit_tuple))
                cursor.execute(f"""
                    DELETE FROM {table_name} 
                    WHERE ({db_tbmt}, {db_qd}, {db_ver}) IN %s
                """, (unit_tuple,))
            
            psycopg2.extras.execute_values(
                cursor, insert_query, values, template=None, page_size=1000
            )
            if unit_tuple:
                refresh_duplicate_flags(cursor, table_name, unit_tuple)
            
        conn.commit()
        logger.info(f"✅ Ghi DB thành công vào bảng '{table_name}' và cập nhật duplicate flags.")
        
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
                    ALTER TABLE package_metadata
                    ADD COLUMN IF NOT EXISTS ngay_phe_duyet_date DATE;
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
                    ngay_phe_duyet_date = parse_ddmmyyyy(ngay_pd_raw)
                    ngay_het_hl_calc = compute_end_date(ngay_pd_raw, tg_thuc_hien_raw)
                    
                    tinh_trang = "KHÔNG XÁC ĐỊNH"
                    if ngay_het_hl_calc:
                        end_dt = datetime.strptime(ngay_het_hl_calc, "%Y-%m-%d").date()
                        tinh_trang = "CÒN HIỆU LỰC" if end_dt >= today_date else "HẾT HIỆU LỰC"

                    cursor.execute("""
                        UPDATE package_metadata
                        SET 
                            gia_goi_thau = %s,
                            ngay_phe_duyet_date = %s::DATE,
                            ngay_het_hieu_luc = %s::DATE,
                            tinh_trang_hieu_luc = %s,
                            dia_diem = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE ma_tbmt = %s AND so_qd = %s AND version = %s
                          AND (
                              gia_goi_thau IS DISTINCT FROM %s
                              OR ngay_phe_duyet_date IS DISTINCT FROM %s::DATE
                              OR ngay_het_hieu_luc IS DISTINCT FROM %s::DATE
                              OR tinh_trang_hieu_luc IS DISTINCT FROM %s
                              OR dia_diem IS DISTINCT FROM %s
                          )
                    """, (
                        gia_clean, 
                        ngay_phe_duyet_date,
                        ngay_het_hl_calc, 
                        tinh_trang, 
                        dia_diem_clean,
                        ma_tbmt, so_qd, version,
                        gia_clean,
                        ngay_phe_duyet_date,
                        ngay_het_hl_calc,
                        tinh_trang,
                        dia_diem_clean
                    ))
                    updated_count += cursor.rowcount
            
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
        df[vendor_col] = pd.Series(pd.NA, index=df.index, dtype="string")

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


def drop_invalid_value_rows(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    return shared_drop_invalid_value_rows(df, schema_name)


VENDOR_GROUP_HEADER_IGNORE_PATTERNS = (
    r"^nhóm\b",
    r"^thuốc\b",
    r"^generic\b",
    r"^biệt dược\b",
    r"^bdg\b",
    r"^gói\b",
    r"^phần\b",
    r"^lô\b",
    r"^tổng cộng\b",
    r"^tổng số\b",
    r"^cộng gộp\b",
    r"^cộng dồn\b",
    r"^cộng lũy kế\b",
    r"^cộng hòa xã hội chủ nghĩa việt nam\b",
    r"^độc lập\s*[-–]\s*tự do\s*[-–]\s*hạnh phúc\b",
    r"^ghi chú\b",
    r"^ghi chu\b",
)


def _is_vendor_group_stt_token(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r"\s+", "", str(text)).strip()
    normalized = re.sub(r"\.0+$", "", normalized)
    return bool(
        re.fullmatch(r"\d+[.)]?", normalized)
        or re.fullmatch(r"[IVXLCDM]+[.)]?", normalized, flags=re.IGNORECASE)
    )


def _strip_vendor_group_prefix(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.sub(r"^\d+\s*[.)]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+\s+", "", cleaned)
    cleaned = re.sub(r"^[IVXLCDM]+\s*[.)]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[IVXLCDM]+\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .:-")


def _is_vendor_group_header_text(text: str) -> bool:
    cleaned = _strip_vendor_group_prefix(text)
    if not cleaned:
        return False
    if _is_numeric_like_text(cleaned) or _is_vendor_group_stt_token(cleaned):
        return False

    lowered = clean_col_str(cleaned)
    if any(re.search(pattern, lowered) for pattern in VENDOR_GROUP_HEADER_IGNORE_PATTERNS):
        return False
    return True


def _get_vendor_group_candidate_columns(df: pd.DataFrame, max_scan_cols: int = 7) -> list[str]:
    excluded_exact = {
        "nhà thầu trúng thầu",
        "số lượng",
        "khối lượng",
        "đơn giá trúng thầu (vnd)",
        "thành tiền (vnd)",
    }
    candidate_cols = []
    for col in list(df.columns)[:max_scan_cols]:
        col_clean = clean_col_str(col)
        if col_clean in excluded_exact:
            continue
        if "đơn giá" in col_clean or "thành tiền" in col_clean:
            continue
        candidate_cols.append(col)
    return candidate_cols


def detect_vendor_group_header_row(
    current: pd.Series,
    next_row: pd.Series | None,
    candidate_cols: list[str],
    detail_cols: list[str],
    amount_col=None,
):
    if current is None or next_row is None or not candidate_cols:
        return None
    if is_generic_summary_row(current, amount_col):
        return None
    if has_detail_signal_generic(current, detail_cols, amount_col):
        return None
    if not has_detail_signal_generic(next_row, detail_cols, amount_col):
        return None

    populated = []
    for col in candidate_cols:
        value = current.get(col)
        if _is_blank_cell(value):
            continue
        text = _clean_cell_text(value)
        if not text:
            continue
        populated.append((col, text))

    if not populated or len(populated) > 2:
        return None

    stt_cells = [(col, text) for col, text in populated if _is_vendor_group_stt_token(text)]
    text_cells = [(col, text) for col, text in populated if not _is_vendor_group_stt_token(text)]

    if len(text_cells) != 1:
        return None
    if len(populated) == 2 and len(stt_cells) != 1:
        return None

    vendor_text = _strip_vendor_group_prefix(text_cells[0][1])
    if not _is_vendor_group_header_text(vendor_text):
        return None

    return {
        "vendor_name": vendor_text,
        "source_cols": [col for col, _ in populated],
    }


def _looks_like_vendor_autocomplete_header(
    current: pd.Series,
    next_row: pd.Series | None,
    source_cols: list[str],
    detail_cols: list[str],
    amount_col=None,
) -> bool:
    if current is None or next_row is None or not source_cols:
        return False
    if is_generic_summary_row(current, amount_col):
        return False
    if has_detail_signal_generic(current, detail_cols, amount_col):
        return False
    if not has_detail_signal_generic(next_row, detail_cols, amount_col):
        return False

    populated = []
    for col in source_cols:
        value = current.get(col)
        if _is_blank_cell(value):
            continue
        text = _clean_cell_text(value)
        if not text:
            continue
        populated.append((col, text))

    if len(populated) != 1:
        return False

    _, only_text = populated[0]
    return _is_vendor_group_header_text(only_text)


def fill_vendor_from_sparse_group_headers(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    if df is None or df.empty or schema_name not in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        return df

    if schema_name == "GOODS_STANDARD":
        detail_cols = [c for c in df.columns if clean_col_str(c) in {"danh mục hàng hóa", "tên hàng hóa", "tên thương mại"}]
    else:
        detail_cols = [c for c in df.columns if clean_col_str(c) == "tên thuốc"]
    if not detail_cols:
        return df

    vendor_col = "Nhà thầu trúng thầu"
    working_df = df.copy()
    if vendor_col not in working_df.columns:
        working_df[vendor_col] = pd.Series(pd.NA, index=working_df.index, dtype="string")
    else:
        working_df[vendor_col] = working_df[vendor_col].astype("string")

    amount_col = next((c for c in working_df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    candidate_cols = _get_vendor_group_candidate_columns(working_df)
    if not candidate_cols:
        return working_df

    normalized_rows = []
    current_vendor = None

    for idx, (_, row) in enumerate(working_df.iterrows()):
        current = row.copy()
        next_row = working_df.iloc[idx + 1] if idx + 1 < len(working_df) else None

        header_info = detect_vendor_group_header_row(
            current=current,
            next_row=next_row,
            candidate_cols=candidate_cols,
            detail_cols=detail_cols,
            amount_col=amount_col,
        )
        if header_info:
            current_vendor = header_info["vendor_name"]
            continue

        if is_generic_summary_row(current, amount_col):
            current_vendor = None
            if not all(_is_blank_cell(v) for v in current.tolist()):
                normalized_rows.append(current)
            continue

        if has_detail_signal_generic(current, detail_cols, amount_col):
            if current_vendor and _is_blank_cell(current.get(vendor_col)):
                current[vendor_col] = current_vendor
        elif not all(_is_blank_cell(v) for v in current.tolist()):
            current_vendor = None

        if not all(_is_blank_cell(v) for v in current.tolist()):
            normalized_rows.append(current)

    if not normalized_rows:
        return working_df

    return pd.DataFrame(normalized_rows, columns=working_df.columns)


def _get_non_blank_vendor_signal_columns(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []

    signal_cols = []
    for col in df.columns:
        if not is_vendor_group_column_name(col):
            continue
        series = df[col].astype("string")
        if bool((~series.fillna("").str.strip().eq("")).any()):
            signal_cols.append(col)
    return signal_cols


def _format_vendor_autofill_ambiguous_reason(
    *,
    vendor_signal_cols: list[str],
    vendor_col: str,
    blank_count: int | None = None,
    source_cols: list[str] | None = None,
) -> str:
    signal_cols_preview = ", ".join(vendor_signal_cols[:3]) or vendor_col
    parts = [
        "[VENDOR_AUTOFILL_AMBIGUOUS]",
        f"Phát hiện pattern autocomplete '{vendor_col}' nhưng file đã có sẵn dữ liệu vendor thật ở cột {signal_cols_preview}.",
    ]

    if blank_count is not None:
        parts.append(f"Cột '{vendor_col}' hiện còn {int(blank_count)} dòng trống.")

    if source_cols:
        source_cols_preview = ", ".join(source_cols[:3])
        parts.append(f"Header nghi ngờ nằm ở cột {source_cols_preview}, không phải cột vendor.")

    parts.append(
        f"Không auto-fill '{vendor_col}' vì đây có thể là group header khác "
        f"(ví dụ Nhóm thuốc / nhóm hàng), cần kiểm tra thủ công."
    )
    return " ".join(parts)


def detect_non_vendor_group_header_manual_reason(df: pd.DataFrame, schema_name: str) -> str | None:
    if df is None or df.empty or schema_name not in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        return None

    settings = get_group_row_engine_settings(df, schema_name)
    stt_col = settings["stt_col"]
    detail_cols = list(settings["detail_cols"])
    amount_col = settings["amount_col"]
    group_cols = list(settings["existing_group_cols"])
    auto_create_target = settings["auto_create_target"]
    vendor_signal_cols = _get_non_blank_vendor_signal_columns(df)

    if auto_create_target != "Nhà thầu trúng thầu" or not stt_col or not detail_cols or not vendor_signal_cols:
        return None

    for idx in range(len(df) - 1):
        current = df.iloc[idx]
        next_row = df.iloc[idx + 1]
        wrong_group = detect_wrong_column_group_header_generic(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            detail_cols=detail_cols,
            group_cols=group_cols,
            amount_col=amount_col,
        )
        if not wrong_group:
            continue
        if any(is_vendor_group_column_name(col) for col in wrong_group["source_cols"]):
            continue

        blank_count = None
        if auto_create_target in df.columns:
            target_series = df[auto_create_target].astype("string")
            blank_count = int(target_series.fillna("").str.strip().eq("").sum())
        return _format_vendor_autofill_ambiguous_reason(
            vendor_signal_cols=vendor_signal_cols,
            vendor_col=auto_create_target,
            blank_count=blank_count,
            source_cols=wrong_group["source_cols"],
        )

    return None


def detect_sparse_vendor_autocomplete_manual_reason(df: pd.DataFrame, schema_name: str) -> str | None:
    if df is None or df.empty or schema_name not in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        return None

    vendor_col = "Nhà thầu trúng thầu"
    vendor_signal_cols = _get_non_blank_vendor_signal_columns(df)
    if not vendor_signal_cols:
        return None

    if vendor_col in df.columns:
        vendor_series = df[vendor_col].astype("string")
    else:
        vendor_series = pd.Series(pd.NA, index=df.index, dtype="string")
    non_blank_mask = ~vendor_series.fillna("").str.strip().eq("")

    blank_mask = vendor_series.fillna("").str.strip().eq("")
    if not bool(blank_mask.any()):
        return None

    if schema_name == "GOODS_STANDARD":
        detail_cols = [c for c in df.columns if clean_col_str(c) in {"danh mục hàng hóa", "tên hàng hóa", "tên thương mại"}]
    else:
        detail_cols = [c for c in df.columns if clean_col_str(c) == "tên thuốc"]
    if not detail_cols:
        return None

    amount_col = next((c for c in df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    candidate_cols = _get_vendor_group_candidate_columns(df)
    if not candidate_cols:
        return None

    for idx in range(len(df) - 1):
        current = df.iloc[idx]
        next_row = df.iloc[idx + 1]
        header_info = detect_vendor_group_header_row(
            current=current,
            next_row=next_row,
            candidate_cols=candidate_cols,
            detail_cols=detail_cols,
            amount_col=amount_col,
        )
        if header_info:
            return _format_vendor_autofill_ambiguous_reason(
                vendor_signal_cols=vendor_signal_cols,
                vendor_col=vendor_col,
                blank_count=int(blank_mask.sum()),
                source_cols=header_info.get("source_cols"),
            )

    return None


def autofill_group_header_values(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    if df is None or df.empty or schema_name not in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        return df

    if schema_name == "GOODS_STANDARD":
        detail_cols = [c for c in df.columns if clean_col_str(c) in {"danh mục hàng hóa", "tên hàng hóa", "tên thương mại"}]
        source_cols = [c for c in ("Mã phần/lô", "Tên phần/lô", "Nhà thầu trúng thầu") if c in df.columns]
    else:
        detail_cols = [c for c in df.columns if clean_col_str(c) == "tên thuốc"]
        source_cols = [c for c in ("Mã phần/lô", "Nhà thầu trúng thầu", "Nhóm thuốc") if c in df.columns]

    if not detail_cols or not source_cols:
        return df

    working_df = df.copy()
    amount_col = next((c for c in working_df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    stt_col = next((c for c in working_df.columns if clean_col_str(c) == "stt"), None)

    normalized_rows = []
    current_context = None

    for idx, (_, row) in enumerate(working_df.iterrows()):
        current = row.copy()
        next_row = working_df.iloc[idx + 1] if idx + 1 < len(working_df) else None
        extra_allowed_cols = [stt_col, amount_col]
        extra_allowed_cols.extend(
            col for col in working_df.columns
            if "đơn giá" in clean_col_str(col)
        )

        header_context = _detect_shape_autofill_context(
            current=current,
            next_row=next_row,
            source_cols=source_cols,
            detail_cols=detail_cols,
            extra_allowed_cols=extra_allowed_cols,
            amount_col=amount_col,
        )
        if header_context:
            current_context = header_context["carry_values"]
            continue

        if is_generic_summary_row(current, amount_col):
            current_context = None
            if not all(_is_blank_cell(v) for v in current.tolist()):
                normalized_rows.append(current)
            continue

        if current_context and has_detail_signal_generic(current, detail_cols, amount_col):
            for col, value in current_context.items():
                if _is_blank_cell(current.get(col)) and not _is_blank_cell(value):
                    current[col] = value
        elif not all(_is_blank_cell(v) for v in current.tolist()) and not has_detail_signal_generic(current, detail_cols, amount_col):
            current_context = None

        if not all(_is_blank_cell(v) for v in current.tolist()):
            normalized_rows.append(current)

    if not normalized_rows:
        return working_df
    return pd.DataFrame(normalized_rows, columns=working_df.columns)

def normalize_data(df: pd.DataFrame, schema_name: str, tbmt=None, so_qd=None, version=None) -> pd.DataFrame:
    config = SCHEMAS[schema_name]
    target_cols = config["output_columns"]
    mapping_config = build_schema_mapping_config(config)
    mandatory_cols = config.get("mandatory_columns", [])

    group_header_manual_reason = detect_non_vendor_group_header_manual_reason(df, schema_name)
    if group_header_manual_reason:
        raise WebWinnerManualReviewRequired(group_header_manual_reason)
    
    if schema_name in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        df = normalize_grouped_rows_generic(df, schema_name)
    if schema_name == "GOODS_STANDARD":
        df = apply_goods_trade_name_fallback(df)
        
    actual_mapping = get_smart_column_mapping(df.columns, mapping_config)
    df = df.rename(columns=actual_mapping)
    df = collapse_duplicate_columns(df)
    df = shared_drop_header_legend_rows(df)
    post_map_amount_col = next((c for c in df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    df = drop_summary_rows(df, post_map_amount_col)
    df = autofill_group_header_values(df, schema_name)
    sparse_vendor_manual_reason = detect_sparse_vendor_autocomplete_manual_reason(df, schema_name)
    if sparse_vendor_manual_reason:
        raise WebWinnerManualReviewRequired(sparse_vendor_manual_reason)
    df = fill_vendor_from_sparse_group_headers(df, schema_name)
    post_fill_amount_col = next((c for c in df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    df = drop_summary_rows(df, post_fill_amount_col)
    if schema_name in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        df = drop_invalid_value_rows(df, schema_name)
    if df.empty:
        raise ValueError("File rỗng sau chuẩn hóa")
    df, vendor_action = apply_vendor_single_winner_fallback(
        df,
        tbmt=tbmt,
        so_qd=so_qd,
        version=version,
        cursor=None,
    )
    if vendor_action.get("status") == "MANUAL_REQUIRED":
        raise WebWinnerManualReviewRequired(vendor_action["reason"])
    if vendor_action.get("status") == "FILLED_FROM_WEB_SINGLE_WINNER":
        logger.info(
            f"🩹 [WEB-WINNER-FILL] ETL {tbmt} / {so_qd} / v{version}: "
            f"điền '{vendor_action.get('winner_name')}' cho {vendor_action.get('blank_count', 0)} dòng thiếu "
            f"'Nhà thầu trúng thầu'."
        )
    
    missing = [col for col in mandatory_cols if col not in df.columns]
    if missing:
        logger.debug(f"Cột hiện có trong file: {list(df.columns)}")
        raise ValueError(f"Thiếu cột bắt buộc: {missing}")

    drop_cols = [k for k, v in mapping_config.items() if v is None and k in df.columns]
    df = df.drop(columns=drop_cols, errors='ignore')
    
    for col in target_cols:
        if col not in df.columns: df[col] = np.nan
            
    meta_cols = ['Mã TBMT', 'so_qd_sanitized', 'qd_display', 'version_code']
    ordered_cols = [c for c in meta_cols if c in df.columns] + target_cols

    return df[ordered_cols]

def process_pipeline():
    start_time = time.time()
    logger.info(f"🚀 BẮT ĐẦU ETL PIPELINE [DỮ LIỆU NGÀY: {TARGET_DATE}]")
    print("="*60)
    clear_web_winner_fact_cache()
    
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
                   COALESCE(r.relation_type, 'INDEPENDENT') as relation_type,
                   pm.ten_goi_thau
            FROM daily_manifest m
            LEFT JOIN qd_relations r 
              ON m.ma_tbmt = r.ma_tbmt AND m.so_qd = r.so_qd AND m.version = r.version
            LEFT JOIN package_metadata pm
              ON m.ma_tbmt = pm.ma_tbmt AND m.so_qd = pm.so_qd AND m.version = pm.version
            WHERE m.manifest_date = %s AND m.status IN ('READY', 'PENDING_ETL_REVIEW')
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
                "ten_goi_thau": row[8],
            }
            for row in c.fetchall()
            if row[4] not in ignored_qd_map.get(row[1], set())
        ]
        active_jobs = expand_active_jobs_with_relation_peers(c, active_jobs, ignored_qd_map)
        prefetch_web_winner_facts(
            c,
            [(job["tbmt"], job["so_qd"], job["version"]) for job in active_jobs]
        )

    if not active_jobs:
        logger.info(f"ℹ️ Không có dữ liệu 'READY' trong ngày {TARGET_DATE}.")
        reconcile_processed_relations()
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
        if m_id is not None:
            manifest_id_map.setdefault(key, []).append(m_id)
        cluster_units_map.setdefault(key, []).append({
            "so_qd": job["so_qd"],
            "version": job["version"],
            "file_path": job["full_path"],
            "relation_type": job["relation_type"],
            "manifest_id": job["manifest_id"],
            "filename": os.path.basename(str(job["full_path"] or "")),
            "ten_goi_thau": job.get("ten_goi_thau"),
        })

    total_inserted_clusters = 0
    flagged_summary = []

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

            processable_units = [
                unit for unit in units_in_cluster
                if unit.get("relation_type") != "CANCELLATION"
            ]
            if not processable_units:
                ids = manifest_id_map.get((tbmt, qd_original, schema_name), [])
                try:
                    if ids:
                        c.execute(
                            "UPDATE daily_manifest SET status='PROCESSED' WHERE id IN %s AND status IS DISTINCT FROM 'PROCESSED'",
                            (tuple(ids),)
                        )
                        conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(
                        f"⚠️ Không cập nhật được manifest cancellation-only sang PROCESSED cho {tbmt} / {qd_original}: {e}"
                    )
                logger.info(
                    f"ℹ️ ETL bỏ qua {tbmt} / {qd_original}: cụm chỉ gồm QĐ CANCELLATION, không có unit cần tạo dataframe."
                )
                continue

            try:
                df_final, qd_display, cluster_ver, files_to_archive = process_qd_cluster(tbmt, qd_original, units_in_cluster, schema_name)
            except WebWinnerManualReviewRequired as e:
                ids = manifest_id_map.get((tbmt, qd_original, schema_name), [])
                issue_reason = str(e)
                if ids:
                    mark_manifest_pending_review(ids)
                save_manifest_issue_records([
                    {
                        "ma_tbmt": tbmt,
                        "so_qd": unit["so_qd"],
                        "version": unit["version"],
                        "filename": unit.get("filename"),
                        "issue_type": "WEB_WINNER_MANUAL_REQUIRED",
                        "issue_reason": issue_reason,
                    }
                    for unit in units_in_cluster
                    if unit.get("manifest_id") is not None
                ])
                for unit in units_in_cluster:
                    flagged_summary.append({
                        "ma_tbmt": tbmt,
                        "so_qd": unit["so_qd"],
                        "version": unit["version"],
                        "schema_name": schema_name,
                        "column_gaps": [],
                        "issue_reason": issue_reason,
                    })
                logger.warning(
                    f"⚠️ [PENDING_ETL_REVIEW] {tbmt} / {qd_original} / {schema_name}: {issue_reason}"
                )
                continue
            if df_final is None or df_final.empty:
                logger.warning(f"⚠️ ETL bỏ qua {tbmt} / {qd_original}: không tạo được dataframe hợp lệ từ cụm QĐ.")
                continue

            package_title = next(
                (unit.get("ten_goi_thau") for unit in units_in_cluster if unit.get("ten_goi_thau")),
                None
            )
            df_final = apply_numeric_cleaning(df_final, schema_name)
            df_final = apply_bdg_group_fill_rule(df_final, package_title, schema_name)
            column_gaps = analyze_review_column_gaps(df_final, schema_name)
            if column_gaps:
                issue_reason = (
                    "Các cột review có dòng trống sau ETL: "
                    + ", ".join(
                        f"{gap['column']} ({gap['blank_count']}/{gap['total_rows']})"
                        for gap in column_gaps
                    )
                )
                ids = manifest_id_map.get((tbmt, qd_original, schema_name), [])
                delete_processed_units(schema_name, [
                    {
                        "tbmt": tbmt,
                        "so_qd": unit["so_qd"],
                        "version": unit["version"],
                    }
                    for unit in units_in_cluster
                ])
                if ids:
                    mark_manifest_pending_review(ids)
                save_manifest_issue_records([
                    {
                        "ma_tbmt": tbmt,
                        "so_qd": unit["so_qd"],
                        "version": unit["version"],
                        "filename": unit.get("filename"),
                        "issue_type": "ETL_REVIEW_COLUMN_GAPS",
                        "issue_reason": issue_reason,
                    }
                    for unit in units_in_cluster
                    if unit.get("manifest_id") is not None
                ])
                for unit in units_in_cluster:
                    flagged_summary.append({
                        "ma_tbmt": tbmt,
                        "so_qd": unit["so_qd"],
                        "version": unit["version"],
                        "schema_name": schema_name,
                        "column_gaps": column_gaps,
                    })
                logger.warning(
                    f"⚠️ [PENDING_ETL_REVIEW] {tbmt} / {qd_original} / {schema_name}: {issue_reason}"
                )
                continue
            
            if '_merge_key' in df_final.columns:
                df_final = df_final.drop(columns=['_merge_key'])

            delete_units = [
                {
                    "tbmt": tbmt,
                    "so_qd": unit["so_qd"],
                    "version": unit["version"],
                }
                for unit in units_in_cluster
            ]
            success = save_to_db(df_final, schema_name, delete_units=delete_units)
            
            if success:
                ids = manifest_id_map.get((tbmt, qd_original, schema_name), [])
                if ids:
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

    reconcile_processed_relations()
    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"🎉 HOÀN TẤT ETL: Xử lý thành công {total_inserted_clusters} Cụm QĐ. Tổng thời gian: {elapsed_time}s.")
    log_pending_review_summary(flagged_summary, f"TỔNG KẾT ETL [{TARGET_DATE}]")

# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("            ETL PIPELINE BÓC TÁCH DỮ LIỆU MUASAMCONG")
    print("="*60)

    parser = argparse.ArgumentParser(description="Chạy Pipeline ETL cho MuaSamCong.")
    parser.add_argument(
        '-m', '--mode',
        choices=['etl', 'audit-retro'],
        default='etl',
        help="Chế độ chạy: 'etl' để xử lý dữ liệu mới, 'audit-retro' để rà dữ liệu đã PROCESSED."
    )
    parser.add_argument('-d', '--date', type=str, help="Ngày cần chạy ETL/audit (Định dạng YYYYMMDD).")
    args = parser.parse_args()

    default_date = datetime.now().strftime("%Y%m%d")

    try:
        get_db_connection().close()
        logger.info("✅ Đã kết nối thành công tới PostgreSQL!")
    except Exception as e:
        logger.error(f"❌ KHÔNG THỂ KHỞI CHẠY PIPELINE: {e}")
        raise SystemExit(1)

    cli_mode_provided = any(arg in ("-m", "--mode") for arg in os.sys.argv[1:])

    if cli_mode_provided:
        if args.mode == 'etl':
            if args.date:
                TARGET_DATE = args.date
            else:
                user_input = input(f"📅 Nhập ngày cần xử lý ETL (YYYYMMDD) [Enter = Hôm nay {default_date}]: ").strip()
                TARGET_DATE = user_input if user_input else default_date
            process_pipeline()
        else:
            TARGET_DATE = args.date or default_date
            audit_processed_units_for_empty_review_columns(args.date)
    else:
        while True:
            print("\n--- ETL PIPELINE TASKS ---")
            print("1. Chạy ETL theo ngày")
            print("2. Audit hồi tố các unit đã PROCESSED")
            print("0. Thoát")

            choice = input("👉 Chọn task (0-2): ").strip()
            if choice == "0":
                break
            elif choice == "1":
                user_input = input(
                    f"📅 Nhập ngày cần ETL (YYYYMMDD) [Enter = Hôm nay {default_date}]: "
                ).strip()
                TARGET_DATE = user_input if user_input else default_date
                process_pipeline()
            elif choice == "2":
                user_input = input(
                    "📅 Nhập ngày manifest cần audit (YYYYMMDD) [Enter = audit toàn bộ]: "
                ).strip()
                TARGET_DATE = user_input if user_input else default_date
                audit_processed_units_for_empty_review_columns(user_input or None)
            else:
                print("❌ Lựa chọn không hợp lệ!")
