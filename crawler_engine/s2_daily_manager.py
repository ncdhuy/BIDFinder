import os
import psycopg2
import pandas as pd
import shutil
from datetime import datetime
from schema_config import SCHEMAS 
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from storage_adapter import ensure_local_file, upload_file, build_r2_key, is_r2_key
import logging
import re

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =====================================================================
# CONFIGURATION
# =====================================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
ROOT_DATA_DIR = os.getenv("ROOT_DATA_DIR")
LOCAL_TEMP_ROOT = os.getenv("LOCAL_TEMP_ROOT")

if not DATABASE_URL:
    raise ValueError("Chưa cấu hình DATABASE_URL")
if not ROOT_DATA_DIR:
    raise ValueError("Chưa cấu hình ROOT_DATA_DIR")
if not LOCAL_TEMP_ROOT:
    raise ValueError("Chưa cấu hình LOCAL_TEMP_ROOT")

OCR_INPUT_DIR = os.path.join(ROOT_DATA_DIR, "ocr_workspace", "input_pdf")
OCR_OUTPUT_DIR = os.path.join(ROOT_DATA_DIR, "ocr_workspace", "output_excel")

SIZE_DROP_THRESHOLD = 0.5 
TARGET_DATE = None
SOURCE_DIR = None


# =====================================================================
# CORE HELPERS
# =====================================================================
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


def choose_largest_file(rows):
    if not rows:
        return None
    return max(rows, key=lambda row: get_file_size_any(row["file_path"]))


def select_comparable_asset(version_rows):
    excel_rows = [row for row in version_rows if row["file_type"] == "excel"]
    if excel_rows:
        chosen = choose_largest_file(excel_rows)
        return {
            "status": "OK",
            "category": "excel",
            "file_path": chosen["file_path"],
            "file_type": chosen["file_type"],
        }

    attachment_rows = [row for row in version_rows if row["file_type"] == "attachment"]
    non_pdf_attachments = [
        row for row in attachment_rows
        if os.path.splitext(str(row["file_path"] or ""))[1].lower() != ".pdf"
    ]
    if non_pdf_attachments:
        chosen = choose_largest_file(non_pdf_attachments)
        return {
            "status": "OK",
            "category": "attachment",
            "file_path": chosen["file_path"],
            "file_type": chosen["file_type"],
        }

    pdf_rows = [row for row in version_rows if row["file_type"] == "pdf"]
    pdf_attachments = [
        row for row in attachment_rows
        if os.path.splitext(str(row["file_path"] or ""))[1].lower() == ".pdf"
    ]

    if pdf_attachments and pdf_rows:
        return {
            "status": "AMBIGUOUS_PDF",
            "category": "pdf",
            "reason": "Cùng version tồn tại cả PDF quyết định và PDF dữ liệu",
        }

    if pdf_attachments:
        chosen = choose_largest_file(pdf_attachments)
        return {
            "status": "OK",
            "category": "pdf_attachment",
            "file_path": chosen["file_path"],
            "file_type": chosen["file_type"],
        }

    if pdf_rows:
        chosen = choose_largest_file(pdf_rows)
        return {
            "status": "OK",
            "category": "pdf",
            "file_path": chosen["file_path"],
            "file_type": chosen["file_type"],
        }

    return {
        "status": "NO_COMPARABLE_ASSET",
        "category": None,
        "reason": "Không có file phù hợp để so sánh dung lượng",
    }


def build_version_map(package_rows):
    version_map = {}
    for row in package_rows:
        version_map.setdefault(row["version"], []).append(row)
    return version_map


def resolve_latest_and_previous_versions(version_map):
    if len(version_map) < 2:
        return None, None

    sorted_versions = sorted(version_map.keys(), key=version_key, reverse=True)
    latest_ver = sorted_versions[0]
    previous_ver = sorted_versions[1]

    db_latest_versions = [
        ver for ver, rows in version_map.items()
        if any(row["is_latest"] == 1 for row in rows)
    ]
    if db_latest_versions:
        latest_ver = max(db_latest_versions, key=version_key)
        older_versions = [ver for ver in sorted_versions if ver != latest_ver]
        if not older_versions:
            return None, None
        previous_ver = older_versions[0]

    return latest_ver, previous_ver


def build_asset_mismatch_issue(tbmt, current_qd, previous_ver, latest_ver, previous_asset, latest_asset, priority="LOW"):
    return {
        "TBMT": tbmt,
        "So_qd": current_qd,
        "Version": latest_ver,
        "Priority": priority,
        "Issue": "Version Asset Mismatch",
        "Details": (
            f"Hai version dùng loại file khác nhau "
            f"(v{previous_ver}: {previous_asset['category']}, "
            f"v{latest_ver}: {latest_asset['category']}), chưa thể so sánh tin cậy."
        ),
        "Files": current_qd
    }


def build_ambiguous_pdf_issue(tbmt, current_qd, previous_ver, latest_ver):
    return {
        "TBMT": tbmt,
        "So_qd": current_qd,
        "Version": latest_ver,
        "Priority": "MEDIUM",
        "Issue": "Version Asset Ambiguous",
        "Details": (
            f"QĐ có nhiều version nhưng ít nhất một version chứa cả PDF quyết định "
            f"và PDF dữ liệu, cần kiểm tra tay (v{previous_ver} -> v{latest_ver})."
        ),
        "Files": current_qd
    }


def compare_version_assets(tbmt, current_qd, previous_ver, latest_ver, previous_asset, latest_asset):
    if latest_asset["status"] == "AMBIGUOUS_PDF" or previous_asset["status"] == "AMBIGUOUS_PDF":
        return build_ambiguous_pdf_issue(tbmt, current_qd, previous_ver, latest_ver)

    if latest_asset["status"] != "OK" or previous_asset["status"] != "OK":
        return None

    priority_rank = {
        "excel": 3,
        "attachment": 2,
        "pdf_attachment": 1,
        "pdf": 0,
    }

    latest_rank = priority_rank.get(latest_asset["category"], -1)
    previous_rank = priority_rank.get(previous_asset["category"], -1)

    compare_note = ""
    if latest_asset["category"] == previous_asset["category"]:
        compare_path_latest = latest_asset["file_path"]
        compare_path_previous = previous_asset["file_path"]
    else:
        common_rank = min(latest_rank, previous_rank)
        if common_rank < 0:
            return None

        if common_rank == 0:
            if latest_asset["category"] != "pdf" or previous_asset["category"] != "pdf":
                return build_asset_mismatch_issue(
                    tbmt, current_qd, previous_ver, latest_ver, previous_asset, latest_asset
                )
            compare_note = "So sánh trên PDF quyết định do không có file dữ liệu tốt hơn."
        else:
            return build_asset_mismatch_issue(
                tbmt, current_qd, previous_ver, latest_ver, previous_asset, latest_asset
            )

        compare_path_latest = latest_asset["file_path"]
        compare_path_previous = previous_asset["file_path"]

    latest_size = get_file_size_any(compare_path_latest)
    previous_size = get_file_size_any(compare_path_previous)

    triggered = False
    details_parts = []

    if previous_size > 0 and (latest_size / previous_size < SIZE_DROP_THRESHOLD):
        triggered = True
        details_parts.append(
            f"Dung lượng giảm từ v{previous_ver} ({previous_size//1024}KB) "
            f"xuống v{latest_ver} ({latest_size//1024}KB)"
        )

    if latest_asset["category"] == "excel" and previous_asset["category"] == "excel":
        latest_rows = get_excel_row_count_any(compare_path_latest)
        previous_rows = get_excel_row_count_any(compare_path_previous)

        if (
            latest_rows is not None and previous_rows is not None and previous_rows > 0
            and (latest_rows / previous_rows < SIZE_DROP_THRESHOLD)
        ):
            triggered = True
            details_parts.append(
                f"Số dòng dữ liệu giảm từ v{previous_ver} ({previous_rows} dòng) "
                f"xuống v{latest_ver} ({latest_rows} dòng)"
            )

    if not triggered:
        return None

    details = "QĐ có nhiều version, " + ". ".join(details_parts)
    if compare_note:
        details = f"{details}. {compare_note}"

    return {
        "TBMT": tbmt,
        "So_qd": current_qd,
        "Version": latest_ver,
        "Priority": "MEDIUM",
        "Issue": "Data Drop Warning",
        "Details": details,
        "Files": current_qd
    }


def get_db_connection():
    """Tạo kết nối PostgreSQL tới Neon DB"""
    if not DATABASE_URL:
        raise ValueError("Chưa cấu hình biến môi trường DATABASE_URL")
    return psycopg2.connect(DATABASE_URL)

def get_file_size_any(path_value, temp_subdir="daily_manager_size"):
    try:
        local_path = ensure_local_file(path_value, temp_subdir=temp_subdir)
        return os.path.getsize(local_path)
    except Exception:
        return 0


def get_excel_row_count_any(path_value, temp_subdir="daily_manager_excel_rows"):
    try:
        local_path = ensure_local_file(path_value, temp_subdir=temp_subdir)
        df_temp = pd.read_excel(local_path, header=None, nrows=15)
        header_idx = df_temp.notna().sum(axis=1).idxmax()
        df = pd.read_excel(local_path, header=header_idx)
        df = df.dropna(how="all")
        return len(df)
    except Exception:
        return None

def choose_best_file(file_list):
    priority = {
        ".xlsx": 1, ".xls": 2, ".docx": 3, ".doc": 4, ".rar": 5, ".zip": 6, ".xml": 7, ".pdf": 8  # Hạ cấp PDF xuống thấp nhất
    }
    def score(fname):
        ext = os.path.splitext(fname)[1].lower()
        p = priority.get(ext, 99)
        size = get_file_size_any(os.path.join(SOURCE_DIR, fname))
        return (p, -size, fname.lower())
    return sorted(file_list, key=score)[0] if file_list else None

# =====================================================================
# LOGIC NHẬN DIỆN VÀ MAP CỘT SCHEMA
# =====================================================================
def clean_col_str(s):
    if not isinstance(s, str): return str(s)
    return s.lower()


def collapse_sparse_goods_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    def is_goods_total_row(row):
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
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)
    if not stt_col:
        return df

    total_mask = df.apply(is_goods_total_row, axis=1)
    df = df.loc[~total_mask].reset_index(drop=True)
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

KEYWORD_RULES = {
    "Tên hoạt chất": ["hoạt chất"],
    "Tên thuốc": ["tên thuốc"],
    "Nồng độ, hàm lượng": ["nồng độ", "hàm lượng"],
    "Số đăng ký": ["số đăng ký"],
    "GĐKLH hoặc GPNK": ["gđklh", "gpnk"], 
    "Đơn giá trúng thầu (VND)": ["đơn giá"],
    "Thành tiền (VND)": ["thành tiền"],
    "Nhà thầu trúng thầu": ["nhà thầu trúng thầu"],
    
    "Tên hàng hóa": ["hàng hóa"],
    "Ký mã hiệu": ["ký mã", "mã hiệu"],
    "Tính năng kỹ thuật": ["tính năng", "kỹ thuật"],
    "Xuất xứ": ["xuất xứ", "nước sản xuất"],
    "Hãng sản xuất": ["hãng sản xuất"],
    "Năm sản xuất": ["năm sản xuất"]
}

def normalize_cols_for_check_smart(raw_cols, mapping):
    normalized_cols = set()
    clean_mapping = {clean_col_str(k): v for k, v in mapping.items()}
    for col in raw_cols:
        col_clean = clean_col_str(col)
        mapped_val = None
        if col in mapping: mapped_val = mapping[col]
        elif col_clean in clean_mapping: mapped_val = clean_mapping[col_clean]
        else:
            for target_col, keywords in KEYWORD_RULES.items():
                if any(kw in col_clean for kw in keywords):
                    mapped_val = target_col
                    break
        if mapped_val is not None: normalized_cols.add(mapped_val)
        else: normalized_cols.add(col) 
    return normalized_cols

def match_signature(current_cols, signature_list):
    signature = set(signature_list)
    if not signature: return False
    matched = signature.intersection(current_cols)
    return (len(matched) / len(signature)) >= 0.8

def identify_file_status_detailed(file_path, file_ext, tbmt, all_files_in_batch):
    ext = file_ext.lower()
    if ext in ['.xlsx', '.xls']:
        try:
            try:
                df_temp = pd.read_excel(file_path, header=None, nrows=15) 
                header_idx = df_temp.notna().sum(axis=1).idxmax()
                df_header = pd.read_excel(file_path, header=header_idx, nrows=0)
                df_check = pd.read_excel(file_path, header=header_idx, nrows=50) 
                current_cols = set(df_header.columns)
            except:
                return "MANUAL_FIX_REQUIRED", "Lỗi đọc file Excel (Corrupt/Password/Header rỗng)"

            def check_price_column_quality(df):
                target_col = None
                for col in df.columns:
                    col_clean = clean_col_str(col)
                    if "đơn giá" in col_clean and "trúng" in col_clean: target_col = col; break
                    elif "đơn giá" in col_clean and "dự" in col_clean: target_col = col; break
                if not target_col:
                    potential_cols = [c for c in df.columns if "đơn giá" in clean_col_str(c)]
                    if potential_cols: target_col = potential_cols[0]
                    else: return False, "Không tìm thấy cột 'Đơn giá'"
                s = df[target_col].astype(str).str.strip().replace("nan", "")
                s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
                s_num = pd.to_numeric(s, errors='coerce')
                total_rows = len(df)
                if total_rows == 0: return False, "File rỗng"
                na_ratio = s_num.isna().sum() / total_rows
                if na_ratio > 0.05: return False, f"Cột '{target_col}' chứa {na_ratio:.1%} NA"
                return True, "OK"
                
            def check_schema_compliance(schema_type):
                config = SCHEMAS[schema_type]
                working_df = df_check.copy()
                if schema_type == "GOODS_STANDARD":
                    working_df = collapse_sparse_goods_rows(working_df)

                norm_cols = normalize_cols_for_check_smart(set(working_df.columns), config["column_mapping"])
                signature = set(config["signature_columns"])
                matched_sig = signature.intersection(norm_cols)
                if not match_signature(norm_cols, config["signature_columns"]):
                    return False, f"Signature mismatch. Thiếu: {signature - matched_sig}."
                mandatory = set(config.get("mandatory_columns", []))
                missing_mandatory = mandatory - norm_cols
                if missing_mandatory: return False, f"Thiếu cột bắt buộc: {missing_mandatory}"
                total_cells = working_df.size
                if total_cells > 0:
                    null_cells = working_df.isna().sum().sum()
                    null_ratio = null_cells / total_cells
                    if null_ratio > 0.3:
                        return False, f"File quá rỗng (Tỷ lệ NULL: {null_ratio:.1%})"
                return check_price_column_quality(working_df)

            is_med, reason_med = check_schema_compliance("MEDICINE_STANDARD")
            if is_med: return "MEDICINE_STANDARD", "OK"
            is_goods, reason_goods = check_schema_compliance("GOODS_STANDARD")
            if is_goods: return "GOODS_STANDARD", "OK"
            return "MANUAL_FIX_REQUIRED", f"MED: {reason_med} | GOODS: {reason_goods}"
            
        except Exception as e: return "MANUAL_FIX_REQUIRED", f"Lỗi không xác định: {str(e)}"
    elif ext == '.pdf':
        better_formats = ('.xlsx', '.xls', '.doc', '.docx', '.rar', '.zip', '.7z', '.xml')
        if not any(f.lower().endswith(better_formats) for f in all_files_in_batch):
            return "OCR_REQUIRED", "PDF Only"
        return "IGNORE", "Đã có file nguồn khác"
    elif ext in ['.doc', '.docx', '.rar', '.zip', '.7z', '.xml']:
        return "MANUAL_FIX_REQUIRED", f"Định dạng {ext} cần chuyển sang Excel"
    return "IGNORE", "File rác"

# =====================================================================
# DB OPERATIONS (CHUẨN HÓA CỘT ma_tbmt, so_qd, version)
# =====================================================================
def save_anomalies_to_db(report_list):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute("""
                    UPDATE scan_anomalies 
                    SET status = 'RESOLVED_AUTO' 
                    WHERE scan_date = %s AND status = 'PENDING'
                """, (TARGET_DATE,))
                
                if not report_list: return
                
                for item in report_list:
                    so_qd = item.get('So_qd', 'ALL')
                    version = item.get('Version', 'ALL')
                    c.execute("""
                        INSERT INTO scan_anomalies (scan_date, ma_tbmt, so_qd, version, issue_type, priority, details, files_involved, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                        ON CONFLICT (scan_date, ma_tbmt, so_qd, version, issue_type)
                        DO UPDATE SET 
                            priority = EXCLUDED.priority,
                            details = EXCLUDED.details,
                            files_involved = EXCLUDED.files_involved,
                            status = CASE 
                                WHEN scan_anomalies.status = 'IGNORED' THEN 'IGNORED' 
                                WHEN scan_anomalies.status = 'PROCESSED'
                                     AND COALESCE(scan_anomalies.details, '') = COALESCE(EXCLUDED.details, '')
                                     AND COALESCE(scan_anomalies.files_involved, '') = COALESCE(EXCLUDED.files_involved, '')
                                THEN 'PROCESSED'
                                ELSE 'PENDING' 
                            END
                    """, (TARGET_DATE, item['TBMT'], so_qd, version, item['Issue'], item['Priority'], item['Details'], item['Files']))
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi Database khi lưu Anomalies: {e}")

def derive_status(schema_type: str) -> str:
    if schema_type in ("MEDICINE_STANDARD", "GOODS_STANDARD"): return "READY"
    if schema_type == "OCR_REQUIRED": return "PENDING_OCR"
    if schema_type == "MANUAL_FIX_REQUIRED": return "PENDING_MANUAL"
    return "UNKNOWN"

def save_manifest_to_db(manifest_list):
    if not manifest_list: return
    
    unique_manifest = { (item["TBMT"], item.get("So_qd"), item.get("Version")): item for item in manifest_list }
    clean_list = list(unique_manifest.values())

    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                for item in clean_list:
                    status = derive_status(item["Schema_Type"])
                    c.execute("""
                        DELETE FROM daily_manifest
                        WHERE manifest_date = %s AND ma_tbmt = %s AND so_qd = %s AND version = %s
                    """, (TARGET_DATE, item["TBMT"], item.get("So_qd"), item.get("Version")))

                    c.execute("""
                        INSERT INTO daily_manifest
                        (manifest_date, ma_tbmt, so_qd, version, filename, schema_type, full_path, file_size_kb, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (TARGET_DATE, item["TBMT"], item.get("So_qd"), item.get("Version"),
                          item["Filename"], item["Schema_Type"], item["Full_Path"], item["Size_KB"], status))
        logger.info(f"✅ Đã upsert {len(clean_list)} record vào DB [table: daily_manifest].")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi Database khi save manifest: {e}")

def push_to_ocr_queue_direct(ocr_file_list):
    if not ocr_file_list: return
    count = 0
    try:
        with get_db_connection() as conn, conn.cursor() as c:
            for item in ocr_file_list:
                c.execute("""
                    INSERT INTO ocr_queue (ma_tbmt, so_qd, version, filename, file_path, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING')
                    ON CONFLICT ON CONSTRAINT uq_ocr DO NOTHING
                """, (item['TBMT'], item['So_qd'], item['Version'], item['Filename'], item['Full_Path']))
                if c.rowcount > 0: count += 1
        if count > 0: logger.info(f"⚡ Đã ghi nhận {count} file PDF cần OCR vào DB.")
    except psycopg2.Error as e:
        logger.error(f"Lỗi insert OCR Queue: {e}")

# =====================================================================
# MAIN TASKS
# =====================================================================

# ----------------- TASK 1: TÌM LỖI FILE RAW -----------------
def scan_anomalies():
    print(f"\n🔍 ĐANG QUÉT BẤT THƯỜNG TẠI: {SOURCE_DIR}")
    if not os.path.exists(SOURCE_DIR):
        print(f"❌ Không tìm thấy folder: {SOURCE_DIR}")
        return

    report_data = []
    files = [
        f for f in os.listdir(SOURCE_DIR)
        if not f.startswith('~$') and f.lower().endswith(('.xlsx', '.xls', '.pdf', '.doc', '.docx'))
    ]

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 0. Tải danh sách TBMT đã được cấu hình từ bảng qd_relations
                cursor.execute("SELECT DISTINCT ma_tbmt FROM qd_relations")
                configured_tbmts = {row[0] for row in cursor.fetchall()}

                # 1. Map QĐ từ bảng packages (cột: ma_tbmt, so_qd)
                cursor.execute("""
                    SELECT file_path, ma_tbmt, so_qd 
                    FROM packages 
                    WHERE file_path LIKE '%%' || %s || '%%'
                """, (TARGET_DATE,))
                db_files = cursor.fetchall()

                file_to_qd_map = {}
                for db_path, db_tbmt, db_qd in db_files:
                    base_name = os.path.basename(db_path)
                    core_name = os.path.splitext(base_name)[0]
                    file_to_qd_map[core_name] = (db_tbmt, db_qd)

                # 2. Phân nhóm
                tbmt_qd_map = {}

                for f in files:
                    core_f = os.path.splitext(f)[0]
                    if core_f in file_to_qd_map:
                        tbmt, qd_raw = file_to_qd_map[core_f]
                    else:
                        tbmt = f.split('_')[0] if '_' in f else "UNKNOWN_TBMT"
                        qd_raw = "UNKNOWN"
                        
                    tbmt_qd_map.setdefault(tbmt, set()).add(qd_raw)

                found_tbmts = tuple(tb for tb in tbmt_qd_map.keys() if tb and tb != "UNKNOWN_TBMT")
                if found_tbmts:
                    cursor.execute("""
                        SELECT DISTINCT ma_tbmt, so_qd
                        FROM packages
                        WHERE ma_tbmt IN %s AND is_latest = 1
                    """, (found_tbmts,))
                    for db_tbmt, db_qd in cursor.fetchall():
                        tbmt_qd_map.setdefault(db_tbmt, set()).add(db_qd)

                # 3. Ghi nhận lỗi
                for tbmt, qds in tbmt_qd_map.items():
                    if len(qds) > 1 and tbmt not in configured_tbmts:
                        report_data.append({
                            "TBMT": tbmt, "So_qd": "ALL", "Version": "ALL", "Priority": "HIGH", "Issue": "Multi-QD",
                            "Details": f"TBMT có {len(qds)} quyết định phê duyệt khác nhau", "Files": ", ".join(qds)
                        })

                for tbmt, qds in tbmt_qd_map.items():
                    for current_qd in qds:
                        if current_qd == "UNKNOWN":
                            continue

                        cursor.execute("""
                            SELECT version, file_path, file_type, is_latest
                            FROM packages 
                            WHERE ma_tbmt = %s AND so_qd = %s
                        """, (tbmt, current_qd))

                        package_rows = [
                            {
                                "version": row[0],
                                "file_path": row[1],
                                "file_type": row[2],
                                "is_latest": row[3],
                            }
                            for row in cursor.fetchall()
                        ]

                        version_map = build_version_map(package_rows)
                        latest_ver, previous_ver = resolve_latest_and_previous_versions(version_map)
                        if not latest_ver or not previous_ver:
                            continue

                        latest_asset = select_comparable_asset(version_map[latest_ver])
                        previous_asset = select_comparable_asset(version_map[previous_ver])
                        issue = compare_version_assets(
                            tbmt=tbmt,
                            current_qd=current_qd,
                            previous_ver=previous_ver,
                            latest_ver=latest_ver,
                            previous_asset=previous_asset,
                            latest_asset=latest_asset,
                        )
                        if issue:
                            report_data.append(issue)

                # 4. Lưu báo cáo lỗi
                save_anomalies_to_db(report_data)

                # 5. Thống kê
                cursor.execute("""
                    SELECT status, COUNT(*) 
                    FROM scan_anomalies 
                    WHERE scan_date = %s 
                    GROUP BY status
                """, (TARGET_DATE,))
                stats = dict(cursor.fetchall())
                pending_count = stats.get('PENDING', 0)
                resolved_count = stats.get('RESOLVED_AUTO', 0)
                processed_count = stats.get('PROCESSED', 0)

                if pending_count > 0:
                    print(f"\n⚠️ PHÁT HIỆN {pending_count} LỖI CẦN XỬ LÝ (PENDING).")
                    if resolved_count > 0: print(f" - Hệ thống đã tự khắc phục: {resolved_count} lỗi.")
                    if processed_count > 0: print(f" - Bạn đã xử lý thủ công trước đó: {processed_count} lỗi.")
                else:
                    print(f"\n✅ Tuyệt vời, không có/không còn lỗi PENDING nào cho ngày {TARGET_DATE}.")

    except Exception as e:
        print(f"❌ DB Error trong scan_anomalies: {e}")

# ----------------- TASK 2: ĐÁNH GIÁ, PHÂN LOẠI & CHỐT MANIFEST -----------------
def finalize_and_generate_manifest(batch_limit=None):
    print(f"\n🚀 ĐANG TẠO MANIFEST ({TARGET_DATE})")
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Purge Version Cũ (Cột: ma_tbmt, version)
                cursor.execute("""
                    DELETE FROM daily_manifest 
                    WHERE EXISTS (
                        SELECT 1 FROM packages p 
                        WHERE p.ma_tbmt = daily_manifest.ma_tbmt
                          AND p.so_qd = daily_manifest.so_qd
                          AND p.version = daily_manifest.version
                          AND p.is_latest = 0
                    )
                """)
                # 2. Dọn Ghost Files
                cursor.execute("SELECT id, full_path FROM daily_manifest WHERE manifest_date = %s", (TARGET_DATE,))
                ids_to_delete = [str(row[0]) for row in cursor.fetchall() if not os.path.exists(row[1])]
                if ids_to_delete:
                    cursor.execute(f"DELETE FROM daily_manifest WHERE id IN ({','.join(ids_to_delete)})")
                conn.commit()
    except Exception as e:
        logger.warning(f"Purge error: {e}")

    try:
        if not os.path.exists(SOURCE_DIR): return print(f"❌ Folder rỗng: {SOURCE_DIR}")
        all_physical_files = os.listdir(SOURCE_DIR)
        physical_map, found_tbmts = {}, set()
        for f in all_physical_files:
            if not f.startswith('~$') and f.endswith(('.xlsx', '.pdf', '.doc', '.docx')):
                tbmt_prefix = f.split('_')[0]
                physical_map.setdefault(tbmt_prefix, []).append(f)
                found_tbmts.add(tbmt_prefix)
        if not found_tbmts: return print("⚠️ Folder rỗng.")
    except Exception as e: return print(f"❌ Lỗi đọc folder: {e}")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version FROM daily_manifest
                    WHERE manifest_date = %s AND status IN ('READY', 'PROCESSED')
                """, (TARGET_DATE,))
                done_units = set(row for row in cursor.fetchall())

                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version, array_agg(file_path) AS file_paths
                    FROM packages 
                    WHERE ma_tbmt IN %s AND is_latest = 1
                    GROUP BY ma_tbmt, so_qd, version
                """, (tuple(found_tbmts),))
                
                db_rows = cursor.fetchall()
                if not db_rows: return print("⚠️ Không tìm thấy metadata trong DB.")

                manifest_data, processed_filenames, todo_count, all_pdfs_for_ocr = [], set(), 0, []

                for tbmt, qd_raw, version, file_paths in db_rows:
                    if (tbmt, qd_raw, version) in done_units: continue
                    todo_count += 1
                    if batch_limit and todo_count > batch_limit: break

                    candidates = physical_map.get(tbmt, [])
                    if not candidates: continue

                    matched_files = []
                    for fp in file_paths:
                        db_fname = os.path.basename(fp)
                        db_fname_no_ext = os.path.splitext(db_fname)[0]
                        for f in candidates:
                            if f not in matched_files and (f == db_fname or (len(db_fname_no_ext) > 5 and db_fname_no_ext in f)):
                                matched_files.append(f)

                    if not matched_files: continue

                    best_file = choose_best_file(matched_files)
                    if not best_file or best_file in processed_filenames: continue
                    processed_filenames.add(best_file)

                    full_path = os.path.join(SOURCE_DIR, best_file)
                    best_ext = os.path.splitext(best_file)[1].lower()

                    status, reason = identify_file_status_detailed(full_path, best_ext, tbmt, matched_files)

                    if status == "IGNORE": continue
                    if status == "MANUAL_FIX_REQUIRED":
                        print(f"🔴 CẦN SỬA TAY: {best_file}\n   => Lý do: {reason}")

                    if status == "OCR_REQUIRED":
                        for f in matched_files:
                            if f.lower().endswith('.pdf'):
                                all_pdfs_for_ocr.append({
                                    "TBMT": tbmt, "So_qd": qd_raw, "Version": version,
                                    "Filename": f, "Full_Path": os.path.join(SOURCE_DIR, f)
                                })
                                
                    manifest_data.append({
                        "TBMT": tbmt, "Filename": best_file, "Schema_Type": status,
                        "Full_Path": full_path, "Size_KB": round(os.path.getsize(full_path)/1024, 2),
                        "So_qd": qd_raw, "Version": version
                    })

                if todo_count == 0: return print(f"✅ Tất cả file đã đạt READY.")

                if manifest_data:
                    save_manifest_to_db(manifest_data)
                    if all_pdfs_for_ocr:
                        push_to_ocr_queue_direct(all_pdfs_for_ocr)
                        os.makedirs(OCR_INPUT_DIR, exist_ok=True)
                        os.makedirs(OCR_OUTPUT_DIR, exist_ok=True)
                        
                        copied_count = 0
                        for item in all_pdfs_for_ocr:
                            src = item['Full_Path']
                            dst = os.path.join(OCR_INPUT_DIR, item['Filename'])
                            if os.path.exists(src) and not os.path.exists(dst): 
                                shutil.copy2(src, dst)
                                copied_count += 1
                        print(f"✅ Đã export {copied_count} file sang OCR_INPUT.")

                    ready_count = len([x for x in manifest_data if x['Schema_Type'] in ['MEDICINE_STANDARD', 'GOODS_STANDARD']])
                    ocr_pkg_count = len([x for x in manifest_data if x['Schema_Type'] == 'OCR_REQUIRED'])
                    manual_count = len([x for x in manifest_data if x['Schema_Type'] == 'MANUAL_FIX_REQUIRED'])

                    print(f"✅ Đã bổ sung {len(manifest_data)} gói thầu (Unit) vào Manifest.")
                    print(f"   - Sẵn sàng ETL (READY): {ready_count} gói")
                    print(f"   - Cần OCR: {ocr_pkg_count} gói (Tổng cộng {len(all_pdfs_for_ocr)} file PDF)")
                    print(f"   - Cần sửa tay: {manual_count} gói")
                else:
                    print("⚠️ Không tạo được manifest mục nào.")

    except psycopg2.Error as e:
        logger.error(f"❌ DB Error finalize: {e}")

# ----------------- TASK 3: AUTO - IMPORT KẾT QUẢ TỪ OCR -----------------
def manage_ocr_workflow():
    print("\n--- OCR WORKFLOW SUPPORT ---")
    if not os.path.exists(OCR_OUTPUT_DIR): 
        return print("❌ Không có file output OCR.")

    files = [f for f in os.listdir(OCR_OUTPUT_DIR) if f.endswith('.xlsx') and not f.startswith('~$')]
    if not files: 
        return print("⚠️ Folder output trống.")

    print(f"📥 Đang import {len(files)} file Excel...")
    count = 0
    files_to_delete = []

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for f in files:
                    pdf_filename = os.path.splitext(f)[0] + ".pdf"
                    
                    cursor.execute("SELECT ma_tbmt, so_qd, version, file_path FROM ocr_queue WHERE filename=%s", (pdf_filename,))
                    row = cursor.fetchone()
                    
                    if row:
                        tbmt, so_qd, version, orig_path = row
                        
                        actual_dir = SOURCE_DIR
                        if orig_path and not is_r2_key(orig_path):
                            parent_dir = os.path.dirname(orig_path)
                            if parent_dir and os.path.exists(parent_dir):
                                actual_dir = parent_dir

                        src_excel = os.path.join(OCR_OUTPUT_DIR, f)
                        dst_excel = os.path.join(actual_dir, f)
                        shutil.copy2(src_excel, dst_excel)

                        ver_num = version
                        
                        cursor.execute("""
                            SELECT 1 FROM packages 
                            WHERE ma_tbmt = %s AND so_qd = %s AND version = %s AND file_type = 'excel'
                        """, (tbmt, so_qd, ver_num))
                        
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO packages (ma_tbmt, so_qd, version, file_path, file_type, is_latest, status, crawled_at)
                                VALUES (%s, %s, %s, %s, 'excel', 1, 'DONE', CURRENT_TIMESTAMP)
                            """, (tbmt, so_qd, ver_num, dst_excel))
                        else:
                            cursor.execute("""
                                UPDATE packages 
                                SET file_path = %s, is_latest = 1 
                                WHERE ma_tbmt = %s AND so_qd = %s AND version = %s AND file_type = 'excel'
                            """, (dst_excel, tbmt, so_qd, ver_num))

                        cursor.execute("UPDATE ocr_queue SET status='COMPLETED' WHERE ma_tbmt=%s AND so_qd=%s AND version=%s", 
                                       (tbmt, so_qd, version))
                        cursor.execute("DELETE FROM daily_manifest WHERE ma_tbmt=%s AND so_qd=%s AND version=%s AND schema_type='OCR_REQUIRED'", 
                                       (tbmt, so_qd, version))

                        pdf_src = os.path.join(OCR_INPUT_DIR, pdf_filename)
                        files_to_delete.append((src_excel, pdf_src))
                        count += 1
                        
                conn.commit()
        
        for src_excel, pdf_src in files_to_delete:
            if os.path.exists(src_excel): os.remove(src_excel)
            if os.path.exists(pdf_src): os.remove(pdf_src)
            
        print(f"\n✅ Đã import {count} file thành công vào hệ thống. DB 'packages' đã được cập nhật!")
        print("💡 Hãy chạy lại Task 1 (Scan Anomalies) và chỉnh sửa lỗi nếu có")
        print("💡 Sau đó chạy lại Task 2 (Finalize & Manifest) để đổi trạng thái thành READY.")

    except psycopg2.Error as e: 
        logger.error(f"❌ Lỗi OCR Import: {e}")

# ----------------- TASK 4: RE-VALIDATE (SỬA TAY FILE ERROR) -----------------
def revalidate_manual_fixes():
    print(f"\n🔧 ĐANG KIỂM TRA LẠI FILE SỬA TAY CỦA NGÀY {TARGET_DATE}...")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, ma_tbmt, filename FROM daily_manifest WHERE manifest_date = %s AND schema_type = 'MANUAL_FIX_REQUIRED'", (TARGET_DATE,))
                rows = cursor.fetchall()
                
                if not rows: return print(f"❌ Không có file cần sửa tay.")
                
                fixed_count, still_broken = 0, 0
                all_files_now = os.listdir(SOURCE_DIR)

                for r_id, tbmt, orig_filename in rows:
                    orig_name_no_ext = os.path.splitext(orig_filename)[0]
                    candidate_files = [f for f in all_files_now if orig_name_no_ext in f and f.endswith(('.xlsx', '.xls'))]
                    
                    if not candidate_files:
                        print(f"❌ {orig_filename}: Chưa có file Excel thay thế."); still_broken += 1; continue
                        
                    found_valid = False
                    for fname in candidate_files:
                        fpath = os.path.join(SOURCE_DIR, fname)
                        status, reason = identify_file_status_detailed(fpath, os.path.splitext(fname)[1], tbmt, [])
                        
                        if status in ['MEDICINE_STANDARD', 'GOODS_STANDARD']:
                            print(f"✅ ĐÃ SỬA XONG: {fname}")
                            cursor.execute("""
                                UPDATE daily_manifest 
                                SET schema_type = %s, status = 'READY', filename = %s, full_path = %s, file_size_kb = %s
                                WHERE id = %s
                            """, (status, fname, fpath, round(os.path.getsize(fpath)/1024, 2), r_id))
                            fixed_count += 1; found_valid = True; break 
                    
                    if not found_valid: print(f"❌ Vẫn chưa chuẩn: {orig_filename}"); still_broken += 1

                conn.commit()
                print(f"\n📊 KẾT QUẢ RE-VALIDATE: Đã sửa {fixed_count}, Còn lỗi {still_broken}")
    except psycopg2.Error as e: logger.error(f"❌ Lỗi Re-validate: {e}")

# =====================================================================
# MENU
# =====================================================================
if __name__ == "__main__":
    print("\n" + "="*50)
    print("      HỆ THỐNG QUẢN LÝ DỮ LIỆU MUASAMCONG")
    print("="*50)
    
    default_date = datetime.now().strftime("%Y%m%d")
    user_input = input(f"📅 Nhập ngày cần xử lý (YYYYMMDD) [Enter = {default_date}]: ").strip()
    TARGET_DATE = user_input if user_input else default_date
    SOURCE_DIR = os.path.join(ROOT_DATA_DIR, TARGET_DATE, "latest")
    
    print(f"\n🎯 Working Date : {TARGET_DATE}")
    
    try:
        get_db_connection().close()
        logger.info("✅ Đã kết nối thành công tới Neon PostgreSQL!")
    except Exception as e:
        logger.error(f"❌ KHÔNG THỂ KẾT NỐI DATABASE: {e}")
        exit(1)

    if not os.path.exists(SOURCE_DIR):
        print("⚠️ Cảnh báo: Thư mục dữ liệu của ngày này chưa tồn tại!")

    while True:
        print(f"\n--- DAILY MANAGER [{TARGET_DATE}] ---")
        print("1. Scan Anomalies (Tìm lỗi bất thường)")
        print("2. Finalize & Manifest (Kiểm duyệt & Chốt sổ Data)")
        print("3. Manage Manual OCR (Nhập kết quả xử lý từ ABBYY)")
        print("4. Re-validate Manual Fixes (Check lại file vừa sửa tay)")
        print("0. Thoát")
        
        c = input("👉 Chọn task (0-4): ").strip()
        if c == "0": break
        elif c == "1": scan_anomalies()
        elif c == "2": finalize_and_generate_manifest()
        elif c == "3": manage_ocr_workflow()
        elif c == "4": revalidate_manual_fixes()
        else: print("❌ Lựa chọn không hợp lệ!")
        
