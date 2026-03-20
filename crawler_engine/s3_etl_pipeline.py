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

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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
    if not isinstance(s, str): return str(s)
    return s.lower()

def get_smart_column_mapping(df_columns: list, mapping_config: dict) -> dict:
    final_map = {}
    clean_mapping_config = {clean_col_str(k): v for k, v in mapping_config.items()}
    
    for col in df_columns:
        col_clean = clean_col_str(col)
        if col in mapping_config:
            final_map[col] = mapping_config[col]; continue
        if col_clean in clean_mapping_config:
            final_map[col] = clean_mapping_config[col_clean]; continue
            
        for target_col, keywords in KEYWORD_RULES.items():
            if any(kw in col_clean for kw in keywords):
                final_map[col] = target_col; break
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

    def is_goods_total_row(row: pd.Series) -> bool:
        patterns = [
            r"tổng cộng giá .* hàng hóa",
            r"tổng giá .* hàng hóa",
            r"tổng cộng .* phí.*lệ phí",
        ]
        for value in row.tolist():
            text = clean_text(value).lower()
            if not text:
                continue
            if any(re.search(pattern, text) for pattern in patterns):
                return True
        return False

    stt_col = next((c for c in df.columns if clean_col_str(c) == "stt"), None)
    vendor_col = next((c for c in df.columns if "nhà thầu" in clean_col_str(c)), None)
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
                df['so_qd_sanitized'] = qd_original 
                df['qd_display'] = u['so_qd']
                df['version_code'] = u['version']
                max_ver = max(max_ver, u['version'], key=version_key)
                all_dfs.append(df)
            except Exception as e:
                logger.error(f"Lỗi đọc file INDEPENDENT {u['file_path']}: {e}")
        
        return pd.concat(all_dfs, ignore_index=True) if all_dfs else None, qd_original, max_ver, files_to_archive

    # 2. ĐỌC QĐ BASE
    base = max(base_units, key=lambda x: version_key(x['version']))
    try:
        df_base = read_and_normalize_excel(base['file_path'], schema_name)
        base_rows = len(df_base)
        base_size = get_size_for_etl(base["file_path"])

    except Exception as e:
        logger.error(f"Lỗi đọc QĐ gốc {base['file_path']}: {e}")
        return None, None, None, []

    # 3. NHÁNH ƯU TIÊN 1: CÓ QUYẾT ĐỊNH THAY THẾ (REPLACEMENT) -> CÓ ARCHIVE
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
        df_final['so_qd_sanitized'] = qd_original
        df_final['qd_display'] = final_qd_display
        df_final['version_code'] = best_rep['version']
        
        return df_final, final_qd_display, best_rep['version'], files_to_archive

    # 4. NHÁNH 2: CHỈ CÓ QUYẾT ĐỊNH ĐIỀU CHỈNH (ADJUSTMENT) -> KHÔNG ARCHIVE
    enriched_adjs = []
    adj_units_sorted = sorted(adj_units, key=lambda x: version_key(x['version']))
    
    for a in adj_units_sorted:
        try:
            df_adj = read_and_normalize_excel(a['file_path'], schema_name)
            adj_size = get_size_for_etl(a["file_path"])

            enriched_adjs.append({'unit': a, 'df': df_adj, 'rows': len(df_adj), 'size': adj_size})
        except Exception:
            continue

    if not enriched_adjs:
        df_base['Mã TBMT'] = tbmt
        df_base['so_qd_sanitized'] = qd_original
        df_base['qd_display'] = f"QĐ gốc: {base['so_qd']}"
        df_base['version_code'] = base['version']
        return df_base, f"QĐ gốc: {base['so_qd']}", base['version'], []

    adj_raw_names = [a['unit']['so_qd'] for a in enriched_adjs]
    final_qd_display = f"QĐ gốc: {base['so_qd']}, QĐ điều chỉnh: {', '.join(adj_raw_names)}"
    
    last_adj = enriched_adjs[-1]
    is_replace = (last_adj['rows'] >= base_rows * 0.9) or (last_adj['size'] >= base_size * 0.9)

    if is_replace:
        logger.info(f"🔄 [REPLACE-ADJUSTMENT] {tbmt}: QĐ điều chỉnh ghi đè hoàn toàn QĐ gốc.")
        df_final = last_adj['df']
        df_final['Mã TBMT'] = tbmt
        df_final['so_qd_sanitized'] = qd_original 
        df_final['qd_display'] = final_qd_display
        df_final['version_code'] = last_adj['unit']['version']
        
        return df_final, final_qd_display, last_adj['unit']['version'], []

    else:
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
        df_final['so_qd_sanitized'] = qd_original
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
    df = df.copy()
    vendor_cols = [c for c in df.columns if isinstance(c, str) and "nhà thầu" in c.lower()]
    if not vendor_cols:
        return df
        
    vendor_col = vendor_cols[0]
    current_vendor = None
    rows = []

    for _, row in df.iterrows():
        vendor = row[vendor_col]
        other_cols = [c for c in row.index if c != vendor_col and "stt" not in str(c).lower()]
        other_values = row[other_cols]
        
        is_group_header = pd.notna(vendor) and str(vendor).strip() != "" and other_values.isna().all()
        
        if is_group_header:
            current_vendor = vendor
            continue 
            
        if pd.isna(vendor) and current_vendor is not None:
            row[vendor_col] = current_vendor
            
        if not row.isna().all():
            rows.append(row)

    if not rows:
        return df
        
    return pd.DataFrame(rows, columns=df.columns)

def normalize_data(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    config = SCHEMAS[schema_name]
    target_cols = config["output_columns"]
    mapping_config = config.get("column_mapping", {})
    mandatory_cols = config.get("mandatory_columns", [])
    
    if schema_name == "GOODS_STANDARD":
        df = collapse_sparse_goods_rows(df)
        df = fix_vendor_group_header(df)
        
    actual_mapping = get_smart_column_mapping(df.columns, mapping_config)
    df = df.rename(columns=actual_mapping)
    df = collapse_duplicate_columns(df)
    
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
            SELECT DISTINCT COALESCE(r.so_qd_original, m.so_qd) as qd_original, m.ma_tbmt, m.schema_type, m.id as manifest_id
            FROM daily_manifest m
            LEFT JOIN qd_relations r 
              ON m.ma_tbmt = r.ma_tbmt AND m.so_qd = r.so_qd AND m.version = r.version
            WHERE m.manifest_date = %s AND m.status = 'READY'
        """, (TARGET_DATE,))
        active_jobs = [
            row for row in c.fetchall()
            if row[0] not in ignored_qd_map.get(row[1], set())
        ]

    if not active_jobs:
        logger.info(f"ℹ️ Không có dữ liệu 'READY' trong ngày {TARGET_DATE}.")
        return

    clusters = {}
    manifest_id_map = {}
    for qd_original, tbmt, schema_type, m_id in active_jobs:
        if schema_type not in SCHEMAS: continue
        key = (tbmt, qd_original, schema_type)
        clusters[key] = True
        manifest_id_map.setdefault(key, []).append(m_id)

    total_inserted_clusters = 0

    with get_db_connection() as conn, conn.cursor() as c:
        ignored_qd_map = load_ignored_qd_map(c)
        for (tbmt, qd_original, schema_name) in clusters.keys():
            c.execute("""
                SELECT p.so_qd, p.version, p.file_path, 
                       COALESCE(r.relation_type, 'INDEPENDENT') as relation_type
                FROM packages p
                LEFT JOIN qd_relations r 
                  ON p.ma_tbmt = r.ma_tbmt AND p.so_qd = r.so_qd AND p.version = r.version
                WHERE p.ma_tbmt = %s AND p.is_latest = 1 
                  AND COALESCE(r.so_qd_original, p.so_qd) = %s AND p.file_type = 'excel'
            """, (tbmt, qd_original))
            
            units_in_cluster = [
                {'so_qd': r[0], 'version': r[1], 'file_path': r[2], 'relation_type': r[3]}
                for r in c.fetchall()
                if r[0] not in ignored_qd_map.get(tbmt, set())
                and not os.path.basename(str(r[2] or "")).startswith("~$")
            ]
            
            if not units_in_cluster:
                logger.warning(f"⚠️ ETL bỏ qua {tbmt} / {qd_original}: không tìm thấy file Excel latest trong packages.")
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

            if 'qd_display' in df_final.columns:
                df_final['so_qd_sanitized'] = df_final['qd_display']

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
