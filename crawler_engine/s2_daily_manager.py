import os
import psycopg2
import pandas as pd
import numpy as np
import shutil
import json
from datetime import datetime, timedelta, timezone
from schema_config import SCHEMAS 
from dotenv import load_dotenv
from psycopg2.extras import execute_values, Json
from storage_adapter import ensure_local_file, upload_file, build_r2_key, is_r2_key, delete_object
import logging
import re
import warnings

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
LOCAL_TZ = timezone(timedelta(hours=7))

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

HUMAN_WORKSPACE_ROOT = os.path.join(ROOT_DATA_DIR, "human_workspace")

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


def sanitize_task_key_component(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text or "UNKNOWN"


def build_human_task_key(tbmt: str, so_qd: str, version: str) -> str:
    return "__".join([
        sanitize_task_key_component(tbmt),
        sanitize_task_key_component(so_qd),
        f"v{sanitize_task_key_component(version or '00')}",
    ])


def get_human_workspace_base(task_type: str, work_date: str | None = None) -> str:
    date_value = work_date or TARGET_DATE or datetime.now().strftime("%Y%m%d")
    return os.path.join(HUMAN_WORKSPACE_ROOT, date_value, task_type.lower())


def get_human_source_dir(task_type: str, work_date: str | None = None) -> str:
    return os.path.join(get_human_workspace_base(task_type, work_date), "source")


def get_human_result_dir(task_type: str, work_date: str | None = None) -> str:
    return os.path.join(get_human_workspace_base(task_type, work_date), "result")


def get_human_meta_dir(task_type: str, work_date: str | None = None) -> str:
    return os.path.join(get_human_workspace_base(task_type, work_date), "_meta")


def get_human_tasks_sheet_path(task_type: str, work_date: str | None = None) -> str:
    return os.path.join(get_human_workspace_base(task_type, work_date), "tasks.xlsx")


def ensure_human_workspace_dirs(task_type: str, work_date: str | None = None):
    source_dir = get_human_source_dir(task_type, work_date)
    result_dir = get_human_result_dir(task_type, work_date)
    meta_dir = get_human_meta_dir(task_type, work_date)
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)
    return source_dir, result_dir, meta_dir


def build_expected_result_filename(source_filename: str, force_excel: bool = False) -> str:
    base_name = os.path.basename(str(source_filename or ""))
    stem, ext = os.path.splitext(base_name)
    ext = ext.lower()
    if not force_excel and ext in (".xlsx", ".xls"):
        return base_name
    return f"{stem}.xlsx"


def copy_file_to_workspace(src_path: str, dst_path: str):
    if not src_path or not os.path.exists(src_path):
        return False
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    if os.path.exists(dst_path):
        try:
            if os.path.getsize(src_path) == os.path.getsize(dst_path):
                return True
        except OSError:
            pass
    shutil.copy2(src_path, dst_path)
    return True


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


def normalize_docx_cell_text(text, keep_newlines=False):
    if text is None:
        return ""
    text = str(text).replace("\r", "\n")
    if keep_newlines:
        parts = [" ".join(part.split()) for part in text.split("\n")]
        return "\n".join(part for part in parts if part).strip()
    return " ".join(text.replace("\n", " ").split()).strip()


def trim_docx_row_values(values):
    trimmed = list(values or [])
    while trimmed and not normalize_docx_cell_text(trimmed[-1], keep_newlines=False):
        trimmed.pop()
    return trimmed


def is_docx_numbering_row(values):
    non_empty = [str(v).strip() for v in values if str(v).strip()]
    if not non_empty:
        return False

    numbered = 0
    for value in non_empty:
        if (
            re.match(r"^\(\d+\)(=.*)?$", value)
            or re.match(r"^\(\d+\)$", value)
            or re.match(r"^\d+(\.\d+)?$", value)
            or re.match(r"^[\d\s().=xX*/+\-]+$", value)
        ):
            numbered += 1
    return numbered / len(non_empty) >= 0.7


def score_docx_header_row(values):
    normalized = [
        normalize_docx_cell_text(v, keep_newlines=False).lower()
        for v in trim_docx_row_values(values)
    ]
    non_empty = [v for v in normalized if v]
    if len(non_empty) < 3:
        return float("-inf")

    header_keywords = (
        "stt", "tên thuốc", "tên hàng hóa", "danh mục hàng hóa", "tên thương mại",
        "nhà thầu", "đơn vị tính", "số lượng", "khối lượng", "đơn giá", "thành tiền",
        "nồng độ", "hàm lượng", "đường dùng", "dạng bào chế", "quy cách", "số đăng ký",
        "ký mã hiệu", "nhãn hiệu", "hãng sản xuất", "xuất xứ", "tính năng kỹ thuật",
        "cấu hình", "mã phần", "tên phần", "hoạt chất"
    )

    keyword_hits = sum(
        1 for value in non_empty
        if any(keyword in value for keyword in header_keywords)
    )
    unique_count = len(set(non_empty))
    repeated_penalty = 8 if unique_count == 1 else 0
    numbering_penalty = 6 if is_docx_numbering_row(non_empty) else 0
    return keyword_hits * 10 + unique_count - repeated_penalty - numbering_penalty


def choose_docx_header_index(rows):
    if not rows:
        return 0

    best_idx = 0
    best_score = float("-inf")
    for idx, row in enumerate(rows[: min(len(rows), 12)]):
        score = score_docx_header_row(row)
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score > float("-inf"):
        return best_idx

    return 0


def make_docx_headers_unique(header_values, width):
    padded = list(header_values[:width]) + [""] * max(0, width - len(header_values))
    result = []
    seen = {}

    for idx, value in enumerate(padded, start=1):
        base = normalize_docx_cell_text(value, keep_newlines=False) or f"Unnamed_{idx}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")

    return result


def convert_docx_table_to_excel(docx_path):
    try:
        from docx import Document
    except ImportError:
        logger.warning("⚠️ Thiếu thư viện python-docx, chưa thể auto-convert file Word.")
        return None

    xlsx_path = os.path.splitext(docx_path)[0] + ".xlsx"
    if os.path.exists(xlsx_path) and os.path.getmtime(xlsx_path) >= os.path.getmtime(docx_path):
        return xlsx_path

    doc = Document(docx_path)
    if not doc.tables:
        return None

    target_table = max(
        doc.tables,
        key=lambda t: sum(
            1 for row in t.rows for cell in row.cells if normalize_docx_cell_text(cell.text)
        )
    )

    rows = []
    for row in target_table.rows:
        values = trim_docx_row_values([cell.text for cell in row.cells])
        if any(normalize_docx_cell_text(v) for v in values):
            rows.append(values)

    if len(rows) < 2:
        return None

    header_idx = choose_docx_header_index(rows)
    header = [normalize_docx_cell_text(v, keep_newlines=False) for v in rows[header_idx]]
    data_rows = rows[header_idx + 1:]
    while data_rows and is_docx_numbering_row([
        normalize_docx_cell_text(v, keep_newlines=False) for v in data_rows[0]
    ]):
        data_rows = data_rows[1:]

    cleaned_rows = []
    for row in data_rows:
        normalized = [normalize_docx_cell_text(v, keep_newlines=True) for v in trim_docx_row_values(row)]
        if any(normalized):
            cleaned_rows.append(normalized)

    if not cleaned_rows:
        return None

    width = max(
        len(header),
        max((len(row) for row in cleaned_rows), default=0)
    )
    header = make_docx_headers_unique(header, width)
    normalized_rows = [
        list(row[:width]) + [""] * max(0, width - len(row))
        for row in cleaned_rows
    ]

    df = pd.DataFrame(normalized_rows, columns=header)
    df.to_excel(xlsx_path, index=False)
    return xlsx_path


def convert_legacy_doc_to_docx(doc_path):
    docx_path = os.path.splitext(doc_path)[0] + ".docx"
    if os.path.exists(docx_path) and os.path.getmtime(docx_path) >= os.path.getmtime(doc_path):
        return docx_path

    try:
        import win32com.client  # type: ignore
    except ImportError:
        logger.warning("⚠️ Thiếu win32com/pywin32, chưa thể auto-convert file .doc.")
        return None

    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(os.path.abspath(doc_path), ReadOnly=True)
        document.SaveAs(os.path.abspath(docx_path), FileFormat=16)
        return docx_path if os.path.exists(docx_path) else None
    except Exception as e:
        logger.warning(f"⚠️ Không thể convert .doc sang .docx {os.path.basename(doc_path)}: {e}")
        return None
    finally:
        try:
            if document is not None:
                document.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass


def convert_word_file_to_excel(word_path):
    ext = os.path.splitext(word_path)[1].lower()
    if ext == ".docx":
        return convert_docx_table_to_excel(word_path)
    if ext == ".doc":
        docx_path = convert_legacy_doc_to_docx(word_path)
        if docx_path:
            return convert_docx_table_to_excel(docx_path)
    return None


def auto_convert_docx_files_in_source():
    if not SOURCE_DIR or not os.path.exists(SOURCE_DIR):
        return []

    converted = []
    for fname in os.listdir(SOURCE_DIR):
        if fname.startswith("~$") or not fname.lower().endswith((".docx", ".doc")):
            continue
        full_path = os.path.join(SOURCE_DIR, fname)
        try:
            xlsx_path = os.path.splitext(full_path)[0] + ".xlsx"
            already_ready = os.path.exists(xlsx_path) and os.path.getmtime(xlsx_path) >= os.path.getmtime(full_path)
            converted_path = convert_word_file_to_excel(full_path)
            if converted_path and not already_ready:
                converted.append((fname, os.path.basename(converted_path)))
        except Exception as e:
            logger.warning(f"⚠️ Không thể auto-convert Word {fname}: {e}")
    return converted


def get_excel_sheet_names_any(path_value, temp_subdir="daily_manager_sheet_names"):
    try:
        local_path = ensure_local_file(path_value, temp_subdir=temp_subdir)
        with pd.ExcelFile(local_path) as workbook:
            return list(workbook.sheet_names or [])
    except Exception:
        return []

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


def build_qd_filename_tokens(qd_raw):
    qd_text = str(qd_raw or "").strip()
    if not qd_text or qd_text.upper() == "UNKNOWN":
        return set()

    qd_number = qd_text.split("/", 1)[0].strip()
    tokens = {
        qd_text.lower(),
        qd_text.replace("/", "_").lower(),
        qd_text.replace("/", "-").lower(),
    }
    if qd_number:
        tokens.add(qd_number.lower())
    return {token for token in tokens if token}


def sanitize_filename_like_crawler(text):
    if not text:
        return ""
    text = str(text)
    for ch in r'\/:*?"<>|':
        text = text.replace(ch, "_")
    return text.strip()


def extract_qd_number(text):
    match = re.search(r"(\d+)", str(text or ""))
    return match.group(1) if match else ""


def parse_unit_from_filename(filename):
    base_name = os.path.basename(str(filename or ""))
    core_name = os.path.splitext(base_name)[0]

    tbmt_match = re.search(r"(IB\d{10})", core_name, flags=re.IGNORECASE)
    version_match = re.search(r"_v(\d{2})_", core_name, flags=re.IGNORECASE)
    qd_match = re.search(r"_(\d+)_QĐ-([^_]+)", core_name, flags=re.IGNORECASE)
    plain_qd_match = re.search(r"_v\d{2}_(\d+)(?:_|$)", core_name, flags=re.IGNORECASE)

    tbmt = tbmt_match.group(1).upper() if tbmt_match else (base_name.split("_")[0] if "_" in base_name else "UNKNOWN_TBMT")
    version = version_match.group(1) if version_match else "00"

    if qd_match:
        qd_number = qd_match.group(1).strip()
        qd_suffix = qd_match.group(2).strip()
        so_qd = f"{qd_number}/QĐ-{qd_suffix}"
    elif plain_qd_match:
        so_qd = plain_qd_match.group(1).strip()
    else:
        so_qd = "UNKNOWN"

    return tbmt, so_qd, version


def resolve_qd_from_candidates(filename, tbmt, version, qd_guess, qd_candidates):
    if not qd_candidates:
        return qd_guess

    if qd_guess in qd_candidates:
        return qd_guess

    core_name = os.path.splitext(os.path.basename(str(filename or "")))[0]
    prefix = f"{tbmt}_v{version}_"
    remainder = core_name[len(prefix):] if core_name.lower().startswith(prefix.lower()) else core_name

    candidate_infos = []
    for qd in qd_candidates:
        sanitized_qd = sanitize_filename_like_crawler(qd)
        candidate_infos.append((qd, sanitized_qd, extract_qd_number(qd)))

    for qd, sanitized_qd, _ in sorted(candidate_infos, key=lambda item: len(item[1]), reverse=True):
        if not sanitized_qd:
            continue
        if remainder == sanitized_qd or remainder.startswith(sanitized_qd + "_"):
            return qd

    qd_number = extract_qd_number(qd_guess)
    if not qd_number:
        qd_number_patterns = [
            r"_v\d{2}_(\d+)(?:_|$)",
            r"(?:^|_)(?:qđ|qd)[ _-]*(?:số[ _-]*)?(\d+)",
            r"(?:^|_)(\d+)(?:_|$)",
        ]
        for pattern in qd_number_patterns:
            match = re.search(pattern, core_name, flags=re.IGNORECASE)
            if match:
                qd_number = match.group(1)
                break

    if qd_number:
        matched_candidates = [qd for qd, _, num in candidate_infos if num == qd_number]
        if len(matched_candidates) == 1:
            return matched_candidates[0]

    return qd_guess


def infer_manual_file_type(filename):
    ext = os.path.splitext(str(filename or ""))[1].lower()

    if ext in (".xlsx", ".xls"):
        return "excel"

    if ext == ".pdf":
        return "pdf"

    return None


def build_unit_file_context(unit_row, physical_map):
    tbmt = unit_row["tbmt"]
    qd_raw = unit_row["so_qd"]
    version = unit_row["version"]
    file_paths = unit_row.get("file_paths") or []

    candidates = physical_map.get(tbmt, [])
    if not candidates:
        return None

    matched_files = find_matched_files_for_unit(candidates, file_paths, tbmt, qd_raw, version)
    if not matched_files:
        return None

    best_file = choose_best_file(matched_files)
    if not best_file:
        return None

    full_path = os.path.join(SOURCE_DIR, best_file)
    ext = os.path.splitext(best_file)[1].lower()

    try:
        size_bytes = os.path.getsize(full_path)
    except OSError:
        size_bytes = get_file_size_any(full_path)

    return {
        "matched_files": matched_files,
        "best_file": best_file,
        "full_path": full_path,
        "ext": ext,
        "size_bytes": size_bytes,
        "row_count": None,
    }


def ensure_ctx_row_count(ctx):
    if not ctx:
        return None
    if ctx.get("ext") not in (".xlsx", ".xls"):
        return None
    if ctx.get("row_count") is None:
        ctx["row_count"] = get_excel_row_count_any(ctx.get("full_path"))
    return ctx.get("row_count")


def should_prefer_adjustment_over_base(base_ctx, adjustment_ctx):
    if not base_ctx or not adjustment_ctx:
        return False

    if base_ctx["ext"] not in (".xlsx", ".xls") or adjustment_ctx["ext"] not in (".xlsx", ".xls"):
        return False

    base_size = base_ctx.get("size_bytes") or 0
    adj_size = adjustment_ctx.get("size_bytes") or 0
    if base_size > 0 and adj_size >= base_size * 0.9:
        return True

    base_rows = ensure_ctx_row_count(base_ctx)
    adj_rows = ensure_ctx_row_count(adjustment_ctx)
    if base_rows and adj_rows and base_rows > 0 and adj_rows >= base_rows * 0.9:
        return True

    return False


def build_relation_superseded_units(unit_rows, physical_map):
    if not unit_rows:
        return {}

    clusters = {}
    for unit in unit_rows:
        cluster_key = (unit["tbmt"], unit["qd_original"])
        clusters.setdefault(cluster_key, []).append(unit)

    file_context_cache = {}
    superseded_map = {}

    def unit_key(unit):
        return (unit["tbmt"], unit["so_qd"], unit["version"])

    def get_ctx(unit):
        key = unit_key(unit)
        if key not in file_context_cache:
            file_context_cache[key] = build_unit_file_context(unit, physical_map)
        return file_context_cache[key]

    for cluster_units in clusters.values():
        base_units = [u for u in cluster_units if u["relation_type"] == "BASE"]
        adj_units = [u for u in cluster_units if u["relation_type"] == "ADJUSTMENT"]
        rep_units = [u for u in cluster_units if u["relation_type"] == "REPLACEMENT"]
        indep_units = [u for u in cluster_units if u["relation_type"] == "INDEPENDENT"]

        if indep_units or not base_units:
            continue

        if rep_units:
            best_rep = max(rep_units, key=lambda x: version_key(x["version"]))
            if not get_ctx(best_rep):
                continue
            best_rep_key = unit_key(best_rep)
            for unit in cluster_units:
                key = unit_key(unit)
                if key == best_rep_key:
                    continue
                superseded_map[key] = (
                    f"Được thay thế bởi QĐ {best_rep['so_qd']} / v{best_rep['version']} "
                    f"(relation_type = REPLACEMENT)"
                )
            continue

        if not adj_units:
            continue

        base = max(base_units, key=lambda x: version_key(x["version"]))
        adj_units_sorted = sorted(adj_units, key=lambda x: version_key(x["version"]))
        last_adj = adj_units_sorted[-1]

        if should_prefer_adjustment_over_base(get_ctx(base), get_ctx(last_adj)):
            last_adj_key = unit_key(last_adj)
            for unit in base_units + adj_units_sorted[:-1]:
                key = unit_key(unit)
                if key == last_adj_key:
                    continue
                superseded_map[key] = (
                    f"Được ưu tiên bỏ qua vì QĐ điều chỉnh cuối {last_adj['so_qd']} / v{last_adj['version']} "
                    f"đủ lớn để thay thế dữ liệu chính"
                )

    return superseded_map


def find_matched_files_for_unit(candidates, file_paths, tbmt, qd_raw, version):
    matched_files = []

    for fp in file_paths:
        db_fname = os.path.basename(fp)
        db_fname_no_ext = os.path.splitext(db_fname)[0]
        for f in candidates:
            if f not in matched_files and (f == db_fname or (len(db_fname_no_ext) > 5 and db_fname_no_ext in f)):
                matched_files.append(f)

    tbmt_token = str(tbmt or "").strip().lower()
    version_token = f"v{str(version or '').strip()}".lower()
    qd_tokens = build_qd_filename_tokens(qd_raw)

    for f in candidates:
        f_lower = f.lower()
        if tbmt_token and tbmt_token not in f_lower:
            continue
        if version_token and version_token not in f_lower:
            continue
        if qd_tokens and not any(token in f_lower for token in qd_tokens):
            continue
        if f not in matched_files:
            matched_files.append(f)

    return matched_files


def upsert_manual_file_to_packages(tbmt, qd_raw, version, full_path, file_type):
    if file_type not in ("excel", "pdf"):
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 1 FROM packages
                WHERE ma_tbmt = %s AND so_qd = %s AND version = %s AND file_type = %s
            """, (tbmt, qd_raw, version, file_type))

            if cursor.fetchone():
                cursor.execute("""
                    UPDATE packages
                    SET file_path = %s, is_latest = 1, status = 'DONE', crawled_at = CURRENT_TIMESTAMP
                    WHERE ma_tbmt = %s AND so_qd = %s AND version = %s AND file_type = %s
                """, (full_path, tbmt, qd_raw, version, file_type))
            else:
                cursor.execute("""
                    INSERT INTO packages (ma_tbmt, so_qd, version, file_path, file_type, is_latest, status, crawled_at, num_cols)
                    VALUES (%s, %s, %s, %s, %s, 1, 'DONE', CURRENT_TIMESTAMP, 0)
                """, (tbmt, qd_raw, version, full_path, file_type))

            conn.commit()


def sync_manual_files_in_latest(all_physical_files, found_tbmts):
    if not all_physical_files or not found_tbmts:
        return

    synced_count = 0

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version, file_path, file_type
                    FROM packages
                    WHERE ma_tbmt IN %s
                """, (tuple(found_tbmts),))
                package_rows = cursor.fetchall()
                existing_units = {(row[0], row[1], row[2]) for row in package_rows}
                existing_paths = {str(row[3]).lower() for row in package_rows if row[3]}
                existing_basename_pairs = {
                    (os.path.basename(str(row[3])).lower(), str(row[4]).lower())
                    for row in package_rows
                    if row[3] and row[4]
                }

                units_by_tbmt_ver = {}
                for tbmt, so_qd, version in existing_units:
                    units_by_tbmt_ver.setdefault((tbmt, version), set()).add(so_qd)

        for fname in all_physical_files:
            if fname.startswith('~$'):
                continue
            full_path = os.path.join(SOURCE_DIR, fname)
            file_type = infer_manual_file_type(fname)
            if not file_type:
                continue
            if full_path.lower() in existing_paths:
                continue
            if (fname.lower(), file_type.lower()) in existing_basename_pairs:
                continue

            tbmt, qd_raw, version = parse_unit_from_filename(fname)
            if not tbmt or tbmt == "UNKNOWN_TBMT" or tbmt not in found_tbmts:
                continue

            qd_candidates = units_by_tbmt_ver.get((tbmt, version), set())
            qd_raw = resolve_qd_from_candidates(fname, tbmt, version, qd_raw, qd_candidates)

            if qd_raw == "UNKNOWN":
                continue

            if (tbmt, qd_raw, version) not in existing_units:
                continue

            upsert_manual_file_to_packages(tbmt, qd_raw, version, full_path, file_type)
            synced_count += 1

        if synced_count:
            logger.info(f"⚡ Đã đồng bộ {synced_count} file thêm tay trong latest vào packages.")
    except psycopg2.Error as e:
        logger.warning(f"⚠️ Không thể đồng bộ file thêm tay vào packages: {e}")

# =====================================================================
# LOGIC NHẬN DIỆN VÀ MAP CỘT SCHEMA
# =====================================================================
def clean_col_str(s):
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


def collapse_sparse_goods_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    def stt_root(value):
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    def is_goods_total_row(row):
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


def collapse_sparse_medicine_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    def stt_root(value):
        text = clean_text(value)
        if not text:
            return ""
        match = re.match(r"^(\d+)", text)
        return match.group(1) if match else text

    def normalize_stt(value):
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

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    def is_numeric_like(text):
        return bool(re.match(r"^[\d\s.,()+\-/%xX*=]+$", text))

    def stt_root(value):
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


def normalize_goods_vendor_group_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    df = df.copy()

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    vendor_col = next((c for c in df.columns if is_vendor_group_column_name(c)), None)
    name_col = next((
        c for c in df.columns
        if any(token in clean_col_str(c) for token in ("tên hàng hóa", "danh mục hàng hóa", "tên thương mại"))
    ), None)
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)
    goods_like = bool(name_col or amount_col or any("đơn giá" in clean_col_str(c) for c in df.columns))

    if vendor_col:
        return df
    if not goods_like:
        return df

    vendor_col = "Nhà thầu trúng thầu"
    if vendor_col not in df.columns:
        df[vendor_col] = np.nan

    current_vendor = None
    current_group_root = None
    normalized_rows = []

    def stt_root(value):
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
            stt_col=next((c for c in df.columns if clean_col_str(c) == "stt"), None),
            name_col=name_col,
            amount_col=amount_col,
        )
        if detected_vendor_info:
            detected_vendor, _ = detected_vendor_info
            current_vendor = detected_vendor
            current_stt = clean_text(current.get(next((c for c in df.columns if clean_col_str(c) == "stt"), None)))
            current_group_root = stt_root(current_stt)
            continue

        current_stt = clean_text(current.get(next((c for c in df.columns if clean_col_str(c) == "stt"), None)))
        current_root = stt_root(current_stt)
        if current_group_root and current_root and current_root != current_group_root:
            current_vendor = None
            current_group_root = None

        if current_vendor and is_blank(current.get(vendor_col)):
            current[vendor_col] = current_vendor

        if not all(is_blank(v) for v in current.tolist()):
            normalized_rows.append(current)

    if not normalized_rows:
        return df

    return pd.DataFrame(normalized_rows, columns=df.columns)


def has_goods_group_header_with_vendor_column(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False

    def is_blank(value):
        return pd.isna(value) or str(value).strip() == ""

    def clean_text(value):
        return str(value).strip() if not pd.isna(value) else ""

    stt_col = next((c for c in df.columns if clean_col_str(c) == "stt"), None)
    vendor_col = next((c for c in df.columns if is_vendor_group_column_name(c)), None)
    name_col = next((
        c for c in df.columns
        if any(token in clean_col_str(c) for token in ("tên hàng hóa", "danh mục hàng hóa", "tên thương mại", "tên mời thầu"))
    ), None)
    amount_col = next((c for c in df.columns if "thành tiền" in clean_col_str(c)), None)

    if not stt_col or not vendor_col or not name_col:
        return False

    for i in range(len(df) - 1):
        current = df.iloc[i]
        next_row = df.iloc[i + 1]
        detected = detect_single_value_goods_group_header(
            current=current,
            next_row=next_row,
            stt_col=stt_col,
            name_col=name_col,
            amount_col=amount_col,
        )
        if detected:
            _, source_cols = detected
            if any(is_vendor_group_column_name(col) for col in source_cols):
                continue
            return True

    return False


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


def normalize_grouped_rows_generic(df: pd.DataFrame, schema_type: str, detect_conflicts: bool = False):
    if df is None or df.empty:
        return df, None

    working_df = df.copy()
    settings = get_group_row_engine_settings(working_df, schema_type)
    stt_col = settings["stt_col"]
    detail_cols = settings["detail_cols"]
    amount_col = settings["amount_col"]
    group_cols = list(settings["existing_group_cols"])
    auto_create_target = settings["auto_create_target"]

    if not stt_col or not detail_cols:
        return working_df, None

    total_mask = working_df.apply(lambda row: is_generic_summary_row(row, amount_col), axis=1)
    working_df = working_df.loc[~total_mask].reset_index(drop=True)
    if working_df.empty:
        return working_df, None

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
            if detect_conflicts and group_cols:
                group_label = ", ".join(str(col) for col in group_cols[:2])
                return working_df, f"Có group header nằm sai cột dù đã có cột {group_label}, cần kiểm tra tay"

            if auto_create_target and auto_create_target not in working_df.columns:
                working_df[auto_create_target] = np.nan
                current[auto_create_target] = np.nan
                if next_row is not None and auto_create_target not in next_row.index:
                    next_row = next_row.reindex(working_df.columns)
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
        belongs_to_context = False
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
    normalized_df = merge_pseudo_group_rows_generic(normalized_df, stt_col, detail_cols, amount_col)
    return normalized_df, None

KEYWORD_RULES = {
    "Tên hoạt chất": ["hoạt chất"],
    "Tên thuốc": ["tên thuốc"],
    "Nồng độ, hàm lượng": ["nồng độ", "hàm lượng"],
    "Số đăng ký": ["số đăng ký"],
    "GĐKLH hoặc GPNK": ["gđklh", "gpnk"], 
    "Đơn giá trúng thầu (VND)": ["đơn giá"],
    "Thành tiền (VND)": ["thành tiền"],
    "Nhà thầu trúng thầu": ["nhà thầu trúng thầu"],
    
    "Danh mục hàng hóa": ["hàng hóa", "danh mục hàng"],
    "Tên phần/lô": ["tên phần", "tên lô"],
    "Mặt hàng dự thầu": ["mặt hàng dự thầu", "mặt hàng"],
    "Ký mã hiệu": ["ký mã", "mã hiệu"],
    "Tính năng kỹ thuật": ["tính năng", "kỹ thuật"],
    "Xuất xứ": ["xuất xứ", "nước sản xuất"],
    "Hãng sản xuất": ["hãng sản xuất"],
    "Năm sản xuất": ["năm sản xuất"]
}

def get_smart_column_mapping(df_columns, mapping_config):
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


def clean_numeric_series_loose(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().replace(["nan", "None", "<NA>", "NaT"], "")
    s = s.str.replace("\u00a0", " ", regex=False)
    s = s.str.replace(r"[^\d,.\-]", "", regex=True)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


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
        df[quantity_col] = clean_numeric_series_loose(df[quantity_col])
    if price_col in df.columns:
        df[price_col] = clean_numeric_series_loose(df[price_col])
    if amount_col in df.columns:
        df[amount_col] = clean_numeric_series_loose(df[amount_col])

    if all(col in df.columns for col in [quantity_col, price_col, amount_col]):
        mask_missing_amount = df[amount_col].isna()
        mask_has_inputs = df[quantity_col].notna() & df[price_col].notna()
        df.loc[mask_missing_amount & mask_has_inputs, amount_col] = (
            df.loc[mask_missing_amount & mask_has_inputs, quantity_col]
            * df.loc[mask_missing_amount & mask_has_inputs, price_col]
        )

    price_series = df[price_col] if price_col in df.columns else pd.Series([pd.NA] * len(df), index=df.index)
    amount_series = df[amount_col] if amount_col in df.columns else pd.Series([pd.NA] * len(df), index=df.index)

    invalid_mask = (price_series.isna() & amount_series.isna())
    invalid_mask |= amount_series.notna() & (amount_series <= 0)

    return df.loc[~invalid_mask].copy()

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

            def check_price_column_quality(df, schema_type):
                target_col = None

                if schema_type == "GOODS_STANDARD":
                    preferred_goods_cols = [
                        "Đơn giá trúng thầu (VND)",
                        "Đơn giá bao gồm thuế, phí, lệ phí liên quan đến nhập khẩu",
                        "Đơn giá dự thầu (đã bao gồm thuế, phí, lệ phí (nếu có))",
                    ]
                    for preferred in preferred_goods_cols:
                        if preferred in df.columns:
                            target_col = preferred
                            break

                if not target_col:
                    for col in df.columns:
                        col_clean = clean_col_str(col)
                        if "đơn giá" in col_clean and "trúng" in col_clean:
                            target_col = col
                            break
                        elif "đơn giá" in col_clean and "bao gồm" in col_clean:
                            target_col = col
                            break
                        elif "đơn giá" in col_clean and "dự" in col_clean:
                            target_col = col
                            break

                if not target_col:
                    potential_cols = [c for c in df.columns if "đơn giá" in clean_col_str(c)]
                    if potential_cols:
                        target_col = potential_cols[0]
                    else:
                        return False, "Không tìm thấy cột 'Đơn giá'"
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
                if schema_type == "MEDICINE_STANDARD":
                    working_df, group_conflict = normalize_grouped_rows_generic(working_df, "MEDICINE_STANDARD")
                    if group_conflict:
                        return False, group_conflict
                if schema_type == "GOODS_STANDARD":
                    working_df, group_conflict = normalize_grouped_rows_generic(working_df, "GOODS_STANDARD", detect_conflicts=True)
                    if group_conflict:
                        return False, group_conflict
                    working_df = apply_goods_trade_name_fallback(working_df)
                actual_mapping = {
                    source_col: target_col
                    for source_col, target_col in get_smart_column_mapping(
                        list(working_df.columns), config["column_mapping"]
                    ).items()
                }
                working_df = working_df.rename(columns=actual_mapping)
                working_df = collapse_duplicate_columns(working_df)
                if schema_type == "GOODS_STANDARD":
                    working_df = drop_invalid_goods_value_rows(working_df)

                norm_cols = set(working_df.columns)
                signature = set(config["signature_columns"])
                matched_sig = signature.intersection(norm_cols)
                if not match_signature(norm_cols, config["signature_columns"]):
                    return False, f"Signature mismatch. Thiếu: {signature - matched_sig}."
                mandatory = set(config.get("mandatory_columns", []))
                missing_mandatory = mandatory - norm_cols
                if missing_mandatory: return False, f"Thiếu cột bắt buộc: {missing_mandatory}"
                density_cols = [col for col in mandatory if col in working_df.columns]
                total_cells = working_df[density_cols].size if density_cols else 0
                if total_cells > 0:
                    null_cells = working_df[density_cols].isna().sum().sum()
                    null_ratio = null_cells / total_cells
                    if null_ratio > 0.3:
                        return False, f"File quá rỗng (Tỷ lệ NULL: {null_ratio:.1%})"
                return check_price_column_quality(working_df, schema_type)

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


def build_pending_anomaly_map(cursor, target_tbmts):
    anomaly_map = {}
    if not target_tbmts:
        return anomaly_map

    cursor.execute("""
        SELECT ma_tbmt, so_qd, version, issue_type, details
        FROM scan_anomalies
        WHERE scan_date = %s
          AND status = 'PENDING'
          AND ma_tbmt IN %s
    """, (TARGET_DATE, tuple(target_tbmts)))

    for tbmt, so_qd, version, issue_type, details in cursor.fetchall():
        anomaly_map.setdefault(tbmt, []).append({
            "so_qd": so_qd,
            "version": version,
            "issue_type": issue_type,
            "details": details,
        })
    return anomaly_map


def get_pending_anomaly_for_unit(tbmt, so_qd, version, anomaly_map):
    for item in anomaly_map.get(tbmt, []):
        qd_match = item["so_qd"] == "ALL" or item["so_qd"] == so_qd
        version_match = item["version"] == "ALL" or item["version"] == version
        if qd_match and version_match:
            return item
    return None


def build_pending_temp_abort_map(cursor, target_tbmts):
    temp_abort_map = {}
    if not target_tbmts:
        return temp_abort_map

    cursor.execute("""
        SELECT aborts.ma_tbmt,
               aborts.last_abort_at,
               aborts.reason,
               latest_done.last_success_at
        FROM (
            SELECT DISTINCT ON (ma_tbmt)
                   ma_tbmt,
                   created_at AS last_abort_at,
                   reason
            FROM scan_logs
            WHERE action_type = 'TEMP_ABORT'
              AND ma_tbmt IN %s
            ORDER BY ma_tbmt, created_at DESC
        ) aborts
        LEFT JOIN (
            SELECT ma_tbmt, MAX(crawled_at) AS last_success_at
            FROM packages
            WHERE ma_tbmt IN %s
              AND status = 'DONE'
            GROUP BY ma_tbmt
        ) latest_done
          ON latest_done.ma_tbmt = aborts.ma_tbmt
    """, (tuple(target_tbmts), tuple(target_tbmts)))

    for tbmt, last_abort_at, reason, last_success_at in cursor.fetchall():
        if last_abort_at and (not last_success_at or last_abort_at > last_success_at):
            temp_abort_map[tbmt] = {
                "reason": reason or "TBMT đã TEMP_ABORT ở lần crawl gần nhất",
                "last_abort_at": last_abort_at,
            }
    return temp_abort_map

def derive_status(schema_type: str) -> str:
    if schema_type in ("MEDICINE_STANDARD", "GOODS_STANDARD"): return "READY"
    if schema_type == "OCR_REQUIRED": return "PENDING_OCR"
    if schema_type == "MANUAL_FIX_REQUIRED": return "PENDING_MANUAL"
    return "UNKNOWN"


def save_manifest_issues(issue_list):
    if not issue_list:
        return

    unique_issues = {
        (item["TBMT"], item.get("So_qd"), item.get("Version"), item["Issue_Type"]): item
        for item in issue_list
    }
    clean_list = list(unique_issues.values())

    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                for item in clean_list:
                    c.execute("""
                        INSERT INTO manifest_issues
                        (issue_date, ma_tbmt, so_qd, version, filename, issue_type, issue_reason, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT ON CONSTRAINT uq_manifest_issues
                        DO UPDATE SET
                            filename = EXCLUDED.filename,
                            issue_reason = EXCLUDED.issue_reason,
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        TARGET_DATE,
                        item["TBMT"],
                        item.get("So_qd"),
                        item.get("Version"),
                        item.get("Filename"),
                        item["Issue_Type"],
                        item.get("Issue_Reason")
                    ))
        logger.info(f"⚡ Đã upsert {len(clean_list)} record vào DB [table: manifest_issues].")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi Database khi save manifest issues: {e}")


def delete_related_physical_files(target_tbmts, tracked_paths, tracked_dirs=None):
    deleted_paths = []
    failed_paths = []
    seen_paths = set()
    tracked_dirs = tracked_dirs or []

    for path_value in tracked_paths:
        if not path_value or path_value in seen_paths:
            continue
        seen_paths.add(path_value)
        try:
            if is_r2_key(path_value):
                delete_object(path_value)
                deleted_paths.append(path_value)
            elif os.path.exists(path_value):
                os.remove(path_value)
                deleted_paths.append(path_value)
        except Exception as e:
            failed_paths.append((path_value, str(e)))

    normalized_targets = tuple(sorted(target_tbmts))
    if normalized_targets and os.path.exists(ROOT_DATA_DIR):
        for root, _, files in os.walk(ROOT_DATA_DIR):
            normalized_root = root.replace("\\", "/").lower()
            if "/latest" not in normalized_root and "/archive" not in normalized_root:
                continue
            for fname in files:
                if not any(fname.startswith(tbmt) for tbmt in normalized_targets):
                    continue
                full_path = os.path.join(root, fname)
                if full_path in seen_paths:
                    continue
                try:
                    os.remove(full_path)
                    deleted_paths.append(full_path)
                    seen_paths.add(full_path)
                except Exception as e:
                    failed_paths.append((full_path, str(e)))

    for dir_path in tracked_dirs:
        if not dir_path:
            continue
        try:
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
                deleted_paths.append(dir_path)
        except Exception as e:
            failed_paths.append((dir_path, str(e)))

    return deleted_paths, failed_paths


def parse_tbmt_inputs(ma_tbmt):
    if not ma_tbmt:
        return []
    if isinstance(ma_tbmt, (list, tuple, set)):
        raw_values = [str(item or "").strip() for item in ma_tbmt]
    else:
        raw_values = re.split(r"[\s,;]+", str(ma_tbmt or "").strip())

    ordered = []
    seen = set()
    for value in raw_values:
        clean_value = str(value or "").strip()
        if not clean_value or clean_value in seen:
            continue
        seen.add(clean_value)
        ordered.append(clean_value)
    return ordered


def normalize_crawl_date_input(value):
    raw = re.sub(r"\D", "", str(value or "").strip())
    if not raw:
        return None
    datetime.strptime(raw, "%Y%m%d")
    return raw


def crawl_date_to_sql(value):
    crawl_date = normalize_crawl_date_input(value)
    if not crawl_date:
        return None
    return datetime.strptime(crawl_date, "%Y%m%d").strftime("%Y-%m-%d")


def to_local_naive_timestamp(value):
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return value


def fetch_latest_run_snapshot(cursor):
    cursor.execute("""
        SELECT id, start_time, end_time, boxes_selected
        FROM run_sessions
        WHERE start_time IS NOT NULL
        ORDER BY start_time DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    if not row or not row[1]:
        return None
    start_time = to_local_naive_timestamp(row[1])
    end_time = to_local_naive_timestamp(row[2]) or datetime.now()
    return {
        "run_id": row[0],
        "start_time": start_time,
        "end_time": end_time,
        "boxes_selected": row[3] or 0,
        "crawl_date": start_time.strftime("%Y%m%d"),
        "crawl_date_sql": start_time.strftime("%Y-%m-%d"),
    }


def collect_crawl_batch_context(cursor, mode, crawl_date=None):
    tracked_paths = set()
    tracked_dirs = []
    summary = {}
    unit_keys = set()
    tbmt_set = set()
    scan_log_ids = []
    run_ids = []

    if mode == "latest_run":
        run_info = fetch_latest_run_snapshot(cursor)
        if not run_info:
            return None

        cursor.execute("""
            SELECT DISTINCT ma_tbmt, so_qd, version
            FROM packages
            WHERE crawled_at >= %s AND crawled_at <= %s
        """, (run_info["start_time"], run_info["end_time"]))
        unit_keys.update(tuple(row) for row in cursor.fetchall() if row[0] and row[1] and row[2])

        cursor.execute("""
            SELECT id, ma_tbmt
            FROM scan_logs
            WHERE run_id = %s
        """, (run_info["run_id"],))
        for log_id, tbmt in cursor.fetchall():
            scan_log_ids.append(log_id)
            if tbmt:
                tbmt_set.add(tbmt)

        run_ids.append(run_info["run_id"])
        date_info = run_info
    else:
        crawl_date = normalize_crawl_date_input(crawl_date)
        if not crawl_date:
            raise ValueError("Ngày crawl không hợp lệ. Vui lòng dùng định dạng YYYYMMDD.")
        crawl_date_sql = crawl_date_to_sql(crawl_date)

        cursor.execute("""
            SELECT DISTINCT ma_tbmt, so_qd, version
            FROM packages
            WHERE crawled_at::date = %s::date
        """, (crawl_date_sql,))
        unit_keys.update(tuple(row) for row in cursor.fetchall() if row[0] and row[1] and row[2])

        cursor.execute("""
            SELECT id, ma_tbmt
            FROM scan_logs
            WHERE created_at::date = %s::date
        """, (crawl_date_sql,))
        for log_id, tbmt in cursor.fetchall():
            scan_log_ids.append(log_id)
            if tbmt:
                tbmt_set.add(tbmt)

        cursor.execute("""
            SELECT id
            FROM run_sessions
            WHERE start_time::date = %s::date
        """, (crawl_date_sql,))
        run_ids.extend(row[0] for row in cursor.fetchall())

        date_info = {
            "crawl_date": crawl_date,
            "crawl_date_sql": crawl_date_sql,
        }
        tracked_dirs.extend([
            os.path.join(ROOT_DATA_DIR, crawl_date),
            os.path.join(HUMAN_WORKSPACE_ROOT, crawl_date),
        ])

    tbmt_set.update(unit[0] for unit in unit_keys if unit[0])
    unit_tuple = tuple(sorted(unit_keys))
    tbmt_tuple = tuple(sorted(tbmt_set))

    if unit_tuple:
        cursor.execute("""
            SELECT file_path
            FROM packages
            WHERE (ma_tbmt, so_qd, version) IN %s
        """, (unit_tuple,))
        tracked_paths.update(row[0] for row in cursor.fetchall() if row[0])

        cursor.execute("""
            SELECT full_path
            FROM daily_manifest
            WHERE manifest_date = %s
              AND (ma_tbmt, so_qd, version) IN %s
        """, (date_info["crawl_date"], unit_tuple))
        tracked_paths.update(row[0] for row in cursor.fetchall() if row[0])

        cursor.execute("""
            SELECT work_date, task_type, ma_tbmt, so_qd, version, source_files_json, expected_output_filename, result_filename
            FROM human_task_queue
            WHERE work_date = %s
              AND (ma_tbmt, so_qd, version) IN %s
        """, (date_info["crawl_date"], unit_tuple))
        for work_date, task_type, row_tbmt, row_so_qd, row_version, source_files_json, expected_output_filename, result_filename in cursor.fetchall():
            tracked_paths.update(
                build_human_task_artifact_paths(
                    task_type=task_type,
                    work_date=work_date,
                    tbmt=row_tbmt,
                    so_qd=row_so_qd,
                    version=row_version,
                    source_files=parse_source_files_json(source_files_json),
                    expected_output_filename=expected_output_filename,
                    result_filename=result_filename,
                )
            )

        table_queries = {
            "packages": "SELECT COUNT(*) FROM packages WHERE (ma_tbmt, so_qd, version) IN %s",
            "package_metadata": "SELECT COUNT(*) FROM package_metadata WHERE (ma_tbmt, so_qd, version) IN %s",
            "qd_relations": "SELECT COUNT(*) FROM qd_relations WHERE (ma_tbmt, so_qd, version) IN %s",
            "processed_medicines": "SELECT COUNT(*) FROM processed_medicines WHERE (ma_tbmt, so_qd, version) IN %s",
            "processed_goods": "SELECT COUNT(*) FROM processed_goods WHERE (ma_tbmt, so_qd, version) IN %s",
        }
        for table_name, sql_query in table_queries.items():
            cursor.execute(sql_query, (unit_tuple,))
            summary[table_name] = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*)
            FROM daily_manifest
            WHERE manifest_date = %s
              AND (ma_tbmt, so_qd, version) IN %s
        """, (date_info["crawl_date"], unit_tuple))
        summary["daily_manifest"] = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*)
            FROM human_task_queue
            WHERE work_date = %s
              AND (ma_tbmt, so_qd, version) IN %s
        """, (date_info["crawl_date"], unit_tuple))
        summary["human_task_queue"] = cursor.fetchone()[0]
    else:
        for table_name in [
            "packages", "package_metadata", "qd_relations", "processed_medicines",
            "processed_goods", "daily_manifest", "human_task_queue"
        ]:
            summary[table_name] = 0

    if tbmt_tuple:
        cursor.execute("""
            SELECT COUNT(*)
            FROM scan_anomalies
            WHERE scan_date = %s
              AND ma_tbmt IN %s
        """, (date_info["crawl_date"], tbmt_tuple))
        summary["scan_anomalies"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM manifest_issues
            WHERE issue_date = %s
              AND ma_tbmt IN %s
        """, (date_info["crawl_date"], tbmt_tuple))
        summary["manifest_issues"] = cursor.fetchone()[0]
    else:
        summary["scan_anomalies"] = 0
        summary["manifest_issues"] = 0

    summary["scan_logs"] = len(scan_log_ids)
    summary["run_sessions"] = len(run_ids)

    return {
        "mode": mode,
        "date_info": date_info,
        "unit_keys": unit_keys,
        "tbmts": tbmt_set,
        "scan_log_ids": scan_log_ids,
        "run_ids": run_ids,
        "tracked_paths": tracked_paths,
        "tracked_dirs": tracked_dirs,
        "summary": summary,
    }


def resolve_target_tbmts(cursor, ma_tbmt=None, package_phrase=None, investor_phrase=None, contractor_phrase=None):
    input_tbmts = parse_tbmt_inputs(ma_tbmt)
    package_phrase = (package_phrase or "").strip().lower()
    investor_phrase = (investor_phrase or "").strip().lower()
    contractor_phrase = (contractor_phrase or "").strip().lower()

    target_tbmts = set(input_tbmts)

    if package_phrase or investor_phrase:
        clauses = []
        params = []
        if package_phrase:
            clauses.append("LOWER(COALESCE(ten_goi_thau, '')) LIKE %s")
            params.append(f"%{package_phrase}%")
        if investor_phrase:
            clauses.append("LOWER(COALESCE(chu_dau_tu, '')) LIKE %s")
            params.append(f"%{investor_phrase}%")
        if clauses:
            cursor.execute(
                f"SELECT DISTINCT ma_tbmt FROM package_metadata WHERE {' OR '.join(clauses)}",
                tuple(params)
            )
            target_tbmts.update(row[0] for row in cursor.fetchall() if row[0])

    if contractor_phrase:
        like_value = f"%{contractor_phrase}%"
        cursor.execute("""
            SELECT DISTINCT ma_tbmt
            FROM processed_medicines
            WHERE LOWER(COALESCE(nha_thau_trung_thau, '')) LIKE %s
            UNION
            SELECT DISTINCT ma_tbmt
            FROM processed_goods
            WHERE LOWER(COALESCE(nha_thau_trung_thau, '')) LIKE %s
        """, (like_value, like_value))
        target_tbmts.update(row[0] for row in cursor.fetchall() if row[0])

    return target_tbmts


def fetch_tbmt_metadata_snapshot(cursor, tbmt_tuple):
    if not tbmt_tuple:
        return {}
    cursor.execute("""
        SELECT ma_tbmt,
               MAX(COALESCE(ten_goi_thau, '')) AS ten_goi_thau,
               MAX(COALESCE(chu_dau_tu, '')) AS chu_dau_tu
        FROM package_metadata
        WHERE ma_tbmt IN %s
        GROUP BY ma_tbmt
    """, (tbmt_tuple,))
    return {
        row[0]: {
            "ten_goi_thau": row[1],
            "chu_dau_tu": row[2],
        }
        for row in cursor.fetchall()
    }


def collect_related_cleanup_context(cursor, tbmt_tuple, keep_filtered_skip_logs=False):
    summary = {}
    tracked_paths = set()

    path_sources = [
        ("packages", "file_path"),
        ("daily_manifest", "full_path"),
    ]
    for table_name, col_name in path_sources:
        cursor.execute(f"SELECT {col_name} FROM {table_name} WHERE ma_tbmt IN %s", (tbmt_tuple,))
        tracked_paths.update(row[0] for row in cursor.fetchall() if row[0])

    cursor.execute("""
        SELECT work_date, task_type, ma_tbmt, so_qd, version, source_files_json, expected_output_filename, result_filename
        FROM human_task_queue
        WHERE ma_tbmt IN %s
    """, (tbmt_tuple,))
    for work_date, task_type, row_tbmt, row_so_qd, row_version, source_files_json, expected_output_filename, result_filename in cursor.fetchall():
        source_files = parse_source_files_json(source_files_json)
        for fname in source_files:
            tracked_paths.add(os.path.join(get_human_source_dir(task_type, work_date), os.path.basename(fname)))
        if expected_output_filename:
            tracked_paths.add(os.path.join(get_human_result_dir(task_type, work_date), expected_output_filename))
        if result_filename:
            tracked_paths.add(os.path.join(get_human_result_dir(task_type, work_date), result_filename))
        tracked_paths.add(
            os.path.join(
                get_human_meta_dir(task_type, work_date),
                f"{build_human_task_key(row_tbmt, row_so_qd, row_version)}.json"
            )
        )

    delete_targets = [
        ("processed_medicines", "ma_tbmt"),
        ("processed_goods", "ma_tbmt"),
        ("daily_manifest", "ma_tbmt"),
        ("human_task_queue", "ma_tbmt"),
        ("scan_anomalies", "ma_tbmt"),
        ("packages", "ma_tbmt"),
        ("package_metadata", "ma_tbmt"),
        ("qd_relations", "ma_tbmt"),
    ]
    if keep_filtered_skip_logs:
        delete_targets.append(("scan_logs", "ma_tbmt", "filtered_preserve"))
    else:
        delete_targets.append(("scan_logs", "ma_tbmt", "all"))

    for target in delete_targets:
        table_name = target[0]
        key_col = target[1]
        mode = target[2] if len(target) > 2 else "all"
        if table_name == "scan_logs" and mode == "filtered_preserve":
            cursor.execute("""
                SELECT COUNT(*)
                FROM scan_logs
                WHERE ma_tbmt IN %s
                  AND COALESCE(action_type, '') <> 'FILTERED_SKIP'
            """, (tbmt_tuple,))
        else:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {key_col} IN %s", (tbmt_tuple,))
        summary[table_name] = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM scan_logs
        WHERE ma_tbmt IN %s
          AND action_type = 'FILTERED_SKIP'
    """, (tbmt_tuple,))
    summary["scan_logs_filtered_skip_kept"] = cursor.fetchone()[0]

    return tracked_paths, summary, delete_targets


def execute_related_cleanup(cursor, tbmt_tuple, delete_targets):
    for target in delete_targets:
        table_name = target[0]
        key_col = target[1]
        mode = target[2] if len(target) > 2 else "all"
        if table_name == "scan_logs" and mode == "filtered_preserve":
            cursor.execute("""
                DELETE FROM scan_logs
                WHERE ma_tbmt IN %s
                  AND COALESCE(action_type, '') <> 'FILTERED_SKIP'
            """, (tbmt_tuple,))
        else:
            cursor.execute(f"DELETE FROM {table_name} WHERE {key_col} IN %s", (tbmt_tuple,))


def purge_related_records(ma_tbmt=None, package_phrase=None, investor_phrase=None, contractor_phrase=None, dry_run=False):
    package_phrase = (package_phrase or "").strip().lower()
    investor_phrase = (investor_phrase or "").strip().lower()
    contractor_phrase = (contractor_phrase or "").strip().lower()

    if not any([parse_tbmt_inputs(ma_tbmt), package_phrase, investor_phrase, contractor_phrase]):
        print("❌ Cần cung cấp ít nhất 1 điều kiện xóa.")
        return

    target_tbmts = set()
    summary = {}
    tracked_paths = set()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                target_tbmts = resolve_target_tbmts(
                    cursor,
                    ma_tbmt=ma_tbmt,
                    package_phrase=package_phrase,
                    investor_phrase=investor_phrase,
                    contractor_phrase=contractor_phrase
                )

                if not target_tbmts:
                    print("⚠️ Không tìm thấy gói thầu nào phù hợp điều kiện xóa.")
                    return

                tbmt_tuple = tuple(sorted(target_tbmts))
                print(f"🧹 {'Xem trước' if dry_run else 'Sẽ xóa'} dữ liệu liên quan của {len(tbmt_tuple)} TBMT.")
                print("   - Danh sách TBMT:", ", ".join(tbmt_tuple))
                tracked_paths, summary, delete_targets = collect_related_cleanup_context(cursor, tbmt_tuple)

                print("📋 Số dòng liên quan theo bảng:")
                for table_name, row_count in summary.items():
                    if row_count:
                        print(f"   - {table_name}: {row_count} dòng")

                print(f"📁 File vật lý/path tracking tìm thấy: {len(tracked_paths)}")

                if dry_run:
                    conn.rollback()
                    print("ℹ️ Dry-run: chưa xóa DB hay file vật lý.")
                    return

                execute_related_cleanup(cursor, tbmt_tuple, delete_targets)

                conn.commit()

        deleted_paths, failed_paths = delete_related_physical_files(target_tbmts, tracked_paths)
        refresh_human_tasks_sheet("OCR", TARGET_DATE)
        refresh_human_tasks_sheet("MANUAL", TARGET_DATE)

        print("✅ Đã xóa xong dữ liệu liên quan.")
        print(f"   - File vật lý đã xóa: {len(deleted_paths)}")
        if failed_paths:
            print(f"   - File vật lý lỗi khi xóa: {len(failed_paths)}")
            for path_value, reason in failed_paths[:10]:
                print(f"     * {path_value} -> {reason}")

    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi purge dữ liệu: {e}")


def purge_crawl_batch(mode="latest_run", crawl_date=None, dry_run=False):
    mode = (mode or "latest_run").strip().lower()
    if mode not in {"latest_run", "date"}:
        print("❌ Mode không hợp lệ. Chỉ hỗ trợ 'latest_run' hoặc 'date'.")
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                context = collect_crawl_batch_context(cursor, mode=mode, crawl_date=crawl_date)
                if not context:
                    print("⚠️ Không tìm thấy run_session gần nhất để xóa.")
                    return

                date_info = context["date_info"]
                unit_keys = context["unit_keys"]
                tbmt_set = context["tbmts"]
                scan_log_ids = context["scan_log_ids"]
                run_ids = context["run_ids"]
                tracked_paths = context["tracked_paths"]
                tracked_dirs = context["tracked_dirs"]
                summary = context["summary"]

                if mode == "latest_run":
                    print(f"🧹 {'Xem trước' if dry_run else 'Sẽ xóa'} dữ liệu thuộc lần crawl gần nhất.")
                    print(
                        f"   - Run session #{date_info['run_id']} | "
                        f"Bắt đầu: {date_info['start_time']} | Kết thúc: {date_info['end_time']}"
                    )
                    print(f"   - Ngày crawl: {date_info['crawl_date']}")
                else:
                    print(f"🧹 {'Xem trước' if dry_run else 'Sẽ xóa'} dữ liệu thuộc ngày crawl {date_info['crawl_date']}.")

                print(f"   - Số unit (TBMT/QĐ/version): {len(unit_keys)}")
                print(f"   - Số TBMT liên quan: {len(tbmt_set)}")
                print("📋 Số dòng sẽ xóa theo bảng:")
                for table_name, row_count in summary.items():
                    if row_count:
                        print(f"   - {table_name}: {row_count} dòng")

                print(f"📁 File/path tracking sẽ xóa: {len(tracked_paths)}")
                if tracked_dirs:
                    print(f"📁 Thư mục sẽ xóa: {len(tracked_dirs)}")
                    for dir_path in tracked_dirs:
                        print(f"   - {dir_path}")

                if dry_run:
                    conn.rollback()
                    print("ℹ️ Dry-run: chưa xóa DB, file vật lý hay thư mục.")
                    return

                unit_tuple = tuple(sorted(unit_keys))
                if unit_tuple:
                    table_deletes = [
                        ("processed_medicines", "(ma_tbmt, so_qd, version) IN %s"),
                        ("processed_goods", "(ma_tbmt, so_qd, version) IN %s"),
                        ("packages", "(ma_tbmt, so_qd, version) IN %s"),
                        ("package_metadata", "(ma_tbmt, so_qd, version) IN %s"),
                        ("qd_relations", "(ma_tbmt, so_qd, version) IN %s"),
                    ]
                    for table_name, where_clause in table_deletes:
                        cursor.execute(f"DELETE FROM {table_name} WHERE {where_clause}", (unit_tuple,))
                    cursor.execute("""
                        DELETE FROM daily_manifest
                        WHERE manifest_date = %s
                          AND (ma_tbmt, so_qd, version) IN %s
                    """, (date_info["crawl_date"], unit_tuple))
                    cursor.execute("""
                        DELETE FROM human_task_queue
                        WHERE work_date = %s
                          AND (ma_tbmt, so_qd, version) IN %s
                    """, (date_info["crawl_date"], unit_tuple))

                tbmt_tuple = tuple(sorted(tbmt_set))
                if tbmt_tuple:
                    cursor.execute("""
                        DELETE FROM scan_anomalies
                        WHERE scan_date = %s AND ma_tbmt IN %s
                    """, (date_info["crawl_date"], tbmt_tuple))
                    cursor.execute("""
                        DELETE FROM manifest_issues
                        WHERE issue_date = %s AND ma_tbmt IN %s
                    """, (date_info["crawl_date"], tbmt_tuple))

                if scan_log_ids:
                    cursor.execute("DELETE FROM scan_logs WHERE id IN %s", (tuple(scan_log_ids),))
                if run_ids:
                    cursor.execute("DELETE FROM run_sessions WHERE id IN %s", (tuple(run_ids),))

                conn.commit()

        deleted_paths, failed_paths = delete_related_physical_files(tbmt_set, tracked_paths, tracked_dirs=tracked_dirs)
        if mode == "latest_run":
            refresh_human_tasks_sheet("OCR", date_info["crawl_date"])
            refresh_human_tasks_sheet("MANUAL", date_info["crawl_date"])

        print("✅ Đã xóa xong dữ liệu thuộc crawl batch.")
        print(f"   - File/thư mục vật lý đã xóa: {len(deleted_paths)}")
        if failed_paths:
            print(f"   - File/thư mục lỗi khi xóa: {len(failed_paths)}")
            for path_value, reason in failed_paths[:10]:
                print(f"     * {path_value} -> {reason}")

    except ValueError as e:
        print(f"❌ {e}")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi purge crawl batch: {e}")


def mark_filtered_skip_records(ma_tbmt=None, package_phrase=None, investor_phrase=None, contractor_phrase=None, dry_run=False):
    package_phrase = (package_phrase or "").strip().lower()
    investor_phrase = (investor_phrase or "").strip().lower()
    contractor_phrase = (contractor_phrase or "").strip().lower()

    if not any([parse_tbmt_inputs(ma_tbmt), package_phrase, investor_phrase, contractor_phrase]):
        print("❌ Cần cung cấp ít nhất 1 điều kiện để gán FILTERED_SKIP.")
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                target_tbmts = resolve_target_tbmts(
                    cursor,
                    ma_tbmt=ma_tbmt,
                    package_phrase=package_phrase,
                    investor_phrase=investor_phrase,
                    contractor_phrase=contractor_phrase
                )

                if not target_tbmts:
                    print("⚠️ Không tìm thấy gói thầu nào phù hợp điều kiện gán FILTERED_SKIP.")
                    return

                tbmt_tuple = tuple(sorted(target_tbmts))
                metadata_snapshot = fetch_tbmt_metadata_snapshot(cursor, tbmt_tuple)
                cursor.execute("""
                    SELECT DISTINCT ma_tbmt
                    FROM scan_logs
                    WHERE ma_tbmt IN %s
                      AND action_type = 'FILTERED_SKIP'
                """, (tbmt_tuple,))
                existing_skips = {row[0] for row in cursor.fetchall() if row[0]}
                new_skips = [tbmt for tbmt in tbmt_tuple if tbmt not in existing_skips]
                tracked_paths, summary, delete_targets = collect_related_cleanup_context(
                    cursor,
                    tbmt_tuple,
                    keep_filtered_skip_logs=True
                )

                print(f"🚩 {'Xem trước' if dry_run else 'Sẽ gán'} FILTERED_SKIP cho {len(tbmt_tuple)} TBMT.")
                print(f"   - TBMT mới sẽ gán skip: {len(new_skips)}")
                print(f"   - TBMT đã có FILTERED_SKIP từ trước: {len(existing_skips)}")
                print("📋 Số dòng sẽ dọn khỏi các bảng liên quan:")
                for table_name, row_count in summary.items():
                    if row_count:
                        print(f"   - {table_name}: {row_count} dòng")
                print(f"📁 File vật lý/path tracking sẽ xóa: {len(tracked_paths)}")

                preview_limit = 20
                print("📋 Danh sách preview:")
                for tbmt in tbmt_tuple[:preview_limit]:
                    meta = metadata_snapshot.get(tbmt, {})
                    status_label = "MỚI" if tbmt in new_skips else "ĐÃ CÓ"
                    title = meta.get("ten_goi_thau") or "[Chưa có tên gói thầu]"
                    print(f"   - [{status_label}] {tbmt}: {title}")
                if len(tbmt_tuple) > preview_limit:
                    print(f"   - ... và thêm {len(tbmt_tuple) - preview_limit} TBMT khác")

                if dry_run:
                    conn.rollback()
                    print("ℹ️ Dry-run: chưa ghi FILTERED_SKIP hay xóa dữ liệu/file vật lý.")
                    return

                inserted_count = 0
                for tbmt in new_skips:
                    meta = metadata_snapshot.get(tbmt, {})
                    title = (meta.get("ten_goi_thau") or "").strip()
                    investor = (meta.get("chu_dau_tu") or "").strip()
                    reason_parts = []
                    if title:
                        reason_parts.append(title)
                    if investor:
                        reason_parts.append(f"Chủ đầu tư: {investor}")
                    reason = " | ".join(reason_parts) if reason_parts else f"Manual FILTERED_SKIP via daily_manager [{TARGET_DATE}]"
                    cursor.execute("""
                        INSERT INTO scan_logs (run_id, ma_tbmt, so_qd, version, action_type, reason, created_at)
                        VALUES (0, %s, 'N/A', 'N/A', 'FILTERED_SKIP', %s, CURRENT_TIMESTAMP)
                    """, (tbmt, reason))
                    inserted_count += 1

                execute_related_cleanup(cursor, tbmt_tuple, delete_targets)
                conn.commit()
                deleted_paths, failed_paths = delete_related_physical_files(target_tbmts, tracked_paths)
                refresh_human_tasks_sheet("OCR", TARGET_DATE)
                refresh_human_tasks_sheet("MANUAL", TARGET_DATE)
                print("✅ Đã ghi FILTERED_SKIP vào scan_logs.")
                print(f"   - TBMT mới được gán skip: {inserted_count}")
                print(f"   - TBMT đã có skip từ trước: {len(existing_skips)}")
                print(f"   - File vật lý đã xóa: {len(deleted_paths)}")
                if failed_paths:
                    print(f"   - File vật lý lỗi khi xóa: {len(failed_paths)}")
                    for path_value, reason in failed_paths[:10]:
                        print(f"     * {path_value} -> {reason}")
                print("ℹ️ Các TBMT này giờ được coi là filtered skip vĩnh viễn: crawler sẽ bỏ qua, còn dữ liệu liên quan đã được dọn sạch.")

    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi gán FILTERED_SKIP: {e}")


def ignore_qd_unit(ma_tbmt, so_qd, version, correct_qd, note=None, dry_run=False):
    ma_tbmt = (ma_tbmt or "").strip()
    so_qd = (so_qd or "").strip()
    version = (version or "").strip() or "00"
    correct_qd = (correct_qd or "").strip()
    note = (note or "").strip()
    if not ma_tbmt or not so_qd or not correct_qd:
        print("❌ Cần nhập đủ Mã TBMT, Số QĐ typo và Số QĐ đúng.")
        return

    tracked_paths = set()
    summary = {}

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO qd_relations (ma_tbmt, so_qd, version, so_qd_original, relation_type, note)
                    VALUES (%s, %s, %s, %s, 'TYPO_ERROR', %s)
                    ON CONFLICT (ma_tbmt, so_qd, version)
                    DO UPDATE SET
                        so_qd_original = EXCLUDED.so_qd_original,
                        relation_type = 'TYPO_ERROR',
                        note = EXCLUDED.note,
                        updated_at = NOW()
                """, (ma_tbmt, so_qd, version, correct_qd, note or "Typo QĐ from source"))

                path_sources = [
                    ("packages", "file_path"),
                    ("daily_manifest", "full_path"),
                ]
                for table_name, col_name in path_sources:
                    cursor.execute(
                        f"SELECT {col_name} FROM {table_name} WHERE ma_tbmt = %s AND so_qd = %s",
                        (ma_tbmt, so_qd)
                    )
                    tracked_paths.update(row[0] for row in cursor.fetchall() if row[0])
                cursor.execute("""
                    SELECT work_date, task_type, ma_tbmt, so_qd, version, source_files_json, expected_output_filename, result_filename
                    FROM human_task_queue
                    WHERE ma_tbmt = %s AND so_qd = %s
                """, (ma_tbmt, so_qd))
                for work_date, task_type, row_tbmt, row_so_qd, row_version, source_files_json, expected_output_filename, result_filename in cursor.fetchall():
                    source_files = parse_source_files_json(source_files_json)
                    for fname in source_files:
                        tracked_paths.add(os.path.join(get_human_source_dir(task_type, work_date), os.path.basename(fname)))
                    if expected_output_filename:
                        tracked_paths.add(os.path.join(get_human_result_dir(task_type, work_date), expected_output_filename))
                    if result_filename:
                        tracked_paths.add(os.path.join(get_human_result_dir(task_type, work_date), result_filename))
                    tracked_paths.add(
                        os.path.join(
                            get_human_meta_dir(task_type, work_date),
                            f"{build_human_task_key(row_tbmt, row_so_qd, row_version)}.json"
                        )
                    )

                delete_specs = [
                    ("processed_medicines", "ma_tbmt = %s AND so_qd = %s"),
                    ("processed_goods", "ma_tbmt = %s AND so_qd = %s"),
                    ("daily_manifest", "ma_tbmt = %s AND so_qd = %s"),
                    ("human_task_queue", "ma_tbmt = %s AND so_qd = %s"),
                    ("scan_anomalies", "ma_tbmt = %s AND (so_qd = %s OR files_involved ILIKE %s)"),
                    ("scan_logs", "ma_tbmt = %s AND so_qd = %s"),
                    ("packages", "ma_tbmt = %s AND so_qd = %s"),
                    ("package_metadata", "ma_tbmt = %s AND so_qd = %s"),
                    ("qd_relations", "ma_tbmt = %s AND so_qd = %s"),
                ]

                for table_name, where_clause in delete_specs:
                    if table_name == "scan_anomalies":
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}",
                            (ma_tbmt, so_qd, f"%{so_qd}%")
                        )
                    else:
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}",
                            (ma_tbmt, so_qd)
                        )
                    summary[table_name] = cursor.fetchone()[0]

                print(f"🚫 {'Xem trước' if dry_run else 'Sẽ bỏ qua'} QĐ typo {so_qd} của {ma_tbmt} -> QĐ đúng {correct_qd}.")
                for table_name, row_count in summary.items():
                    if row_count:
                        print(f"   - {table_name}: {row_count} dòng")
                print(f"   - File/path liên quan: {len(tracked_paths)}")

                if dry_run:
                    conn.rollback()
                    print("ℹ️ Dry-run: chưa xóa dữ liệu.")
                    return

                for table_name, where_clause in delete_specs:
                    if table_name == "scan_anomalies":
                        cursor.execute(
                            f"DELETE FROM {table_name} WHERE {where_clause}",
                            (ma_tbmt, so_qd, f"%{so_qd}%")
                        )
                    else:
                        cursor.execute(
                            f"DELETE FROM {table_name} WHERE {where_clause}",
                            (ma_tbmt, so_qd)
                        )

                conn.commit()

        deleted_paths, failed_paths = delete_related_physical_files({ma_tbmt}, tracked_paths)
        refresh_human_tasks_sheet("OCR", TARGET_DATE)
        refresh_human_tasks_sheet("MANUAL", TARGET_DATE)
        print(f"✅ Đã đánh dấu TYPO_ERROR và bỏ qua QĐ {so_qd} của {ma_tbmt}. File vật lý đã xóa: {len(deleted_paths)}")
        if failed_paths:
            print(f"⚠️ Có {len(failed_paths)} file/path không xóa được.")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi ignore QĐ typo: {e}")

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
                        ON CONFLICT ON CONSTRAINT uq_manifest
                        DO UPDATE SET
                            ma_tbmt = EXCLUDED.ma_tbmt,
                            so_qd = EXCLUDED.so_qd,
                            version = EXCLUDED.version,
                            schema_type = EXCLUDED.schema_type,
                            full_path = EXCLUDED.full_path,
                            file_size_kb = EXCLUDED.file_size_kb,
                            status = EXCLUDED.status
                    """, (TARGET_DATE, item["TBMT"], item.get("So_qd"), item.get("Version"),
                          item["Filename"], item["Schema_Type"], item["Full_Path"], item["Size_KB"], status))
        logger.info(f"✅ Đã upsert {len(clean_list)} record vào DB [table: daily_manifest].")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi Database khi save manifest: {e}")

def parse_source_files_json(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            pass
        return [value]
    return []


def refresh_human_tasks_sheet(task_type: str, work_date: str | None = None):
    work_date = work_date or TARGET_DATE
    if not work_date:
        return

    source_dir, result_dir, _ = ensure_human_workspace_dirs(task_type, work_date)
    sheet_path = get_human_tasks_sheet_path(task_type, work_date)

    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute("""
                SELECT ma_tbmt, so_qd, version, source_filename, source_files_json,
                       expected_output_filename, issue_reason, status, validation_message,
                       result_filename, updated_at
                FROM human_task_queue
                WHERE work_date = %s AND task_type = %s
                ORDER BY status, ma_tbmt, so_qd, version
            """, (work_date, task_type))
            rows = cursor.fetchall()
    except psycopg2.Error as e:
        logger.error(f"❌ Không thể refresh tasks.xlsx cho {task_type}: {e}")
        return

    records = []
    for row in rows:
        source_files = parse_source_files_json(row[4])
        records.append({
            "Mã TBMT": row[0],
            "Số QĐ": row[1],
            "Version": row[2],
            "File nguồn chính": row[3],
            "Tất cả file nguồn": "\n".join(source_files),
            "Tên file kết quả cần nộp": row[5],
            "Lý do / Hướng xử lý": row[6],
            "Trạng thái": row[7],
            "Lỗi validate": row[8],
            "File kết quả đã nhận": row[9],
            "Workspace source": source_dir,
            "Workspace result": result_dir,
            "Cập nhật lúc": row[10],
        })

    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=[
            "Mã TBMT", "Số QĐ", "Version", "File nguồn chính", "Tất cả file nguồn",
            "Tên file kết quả cần nộp", "Lý do / Hướng xử lý", "Trạng thái",
            "Lỗi validate", "File kết quả đã nhận", "Workspace source",
            "Workspace result", "Cập nhật lúc"
        ])
    df.to_excel(sheet_path, index=False)


def export_human_tasks(task_type: str, task_list: list):
    if not task_list:
        return 0

    source_dir, result_dir, meta_dir = ensure_human_workspace_dirs(task_type)
    unique_tasks = {
        (item["TBMT"], item["So_qd"], item["Version"]): item
        for item in task_list
    }
    exported_count = 0

    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            for item in unique_tasks.values():
                task_key = build_human_task_key(item["TBMT"], item["So_qd"], item["Version"])
                source_files = [f for f in item.get("Source_Files", []) if f]
                source_files = list(dict.fromkeys(source_files))

                for fname in source_files:
                    src = os.path.join(SOURCE_DIR, fname)
                    dst = os.path.join(source_dir, os.path.basename(fname))
                    copy_file_to_workspace(src, dst)

                meta_payload = {
                    "task_key": task_key,
                    "work_date": TARGET_DATE,
                    "task_type": task_type,
                    "ma_tbmt": item["TBMT"],
                    "so_qd": item["So_qd"],
                    "version": item["Version"],
                    "source_filename": item["Source_Filename"],
                    "expected_output_filename": item["Expected_Output_Filename"],
                    "issue_reason": item["Issue_Reason"],
                    "source_files": source_files,
                }
                meta_path = os.path.join(meta_dir, f"{task_key}.json")
                with open(meta_path, "w", encoding="utf-8") as fh:
                    json.dump(meta_payload, fh, ensure_ascii=False, indent=2)

                source_main_path = os.path.join(SOURCE_DIR, item["Source_Filename"])
                cursor.execute("""
                    INSERT INTO human_task_queue (
                        work_date, task_type, ma_tbmt, so_qd, version,
                        source_filename, source_path, source_files_json,
                        workspace_source_dir, workspace_result_dir,
                        expected_output_filename, issue_reason, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'EXPORTED')
                    ON CONFLICT ON CONSTRAINT uq_human_task
                    DO UPDATE SET
                        source_filename = EXCLUDED.source_filename,
                        source_path = EXCLUDED.source_path,
                        source_files_json = EXCLUDED.source_files_json,
                        workspace_source_dir = EXCLUDED.workspace_source_dir,
                        workspace_result_dir = EXCLUDED.workspace_result_dir,
                        expected_output_filename = EXCLUDED.expected_output_filename,
                        issue_reason = EXCLUDED.issue_reason,
                        status = CASE
                            WHEN human_task_queue.status = 'COMPLETED' THEN human_task_queue.status
                            ELSE 'EXPORTED'
                        END,
                        validation_message = CASE
                            WHEN human_task_queue.status = 'COMPLETED' THEN human_task_queue.validation_message
                            ELSE NULL
                        END,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    TARGET_DATE,
                    task_type,
                    item["TBMT"],
                    item["So_qd"],
                    item["Version"],
                    item["Source_Filename"],
                    source_main_path,
                    Json(source_files),
                    source_dir,
                    result_dir,
                    item["Expected_Output_Filename"],
                    item["Issue_Reason"],
                ))
                exported_count += 1

            conn.commit()
        refresh_human_tasks_sheet(task_type)
        logger.info(f"⚡ Đã export {exported_count} task {task_type} vào human_workspace.")
        return exported_count
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi export {task_type} vào human workspace: {e}")
        return 0


def find_result_file_for_task(result_dir: str, expected_output_filename: str):
    exact_path = os.path.join(result_dir, expected_output_filename)
    if os.path.exists(exact_path):
        return exact_path

    stem, _ = os.path.splitext(expected_output_filename)
    candidate_exts = [".xlsx", ".xls"]
    for ext in candidate_exts:
        candidate = os.path.join(result_dir, stem + ext)
        if os.path.exists(candidate):
            return candidate

    return None


def build_human_task_artifact_paths(task_type: str, work_date: str, tbmt: str, so_qd: str, version: str,
                                    source_files=None, expected_output_filename=None, result_filename=None):
    source_files = source_files or []
    paths = set()

    for fname in source_files:
        if fname:
            paths.add(os.path.join(get_human_source_dir(task_type, work_date), os.path.basename(fname)))

    if expected_output_filename:
        paths.add(os.path.join(get_human_result_dir(task_type, work_date), expected_output_filename))
    if result_filename:
        paths.add(os.path.join(get_human_result_dir(task_type, work_date), result_filename))

    paths.add(
        os.path.join(
            get_human_meta_dir(task_type, work_date),
            f"{build_human_task_key(tbmt, so_qd, version)}.json"
        )
    )
    return paths


def cleanup_human_workspace_artifacts(paths):
    deleted_paths = []
    failed_paths = []
    seen_paths = set()

    for path_value in paths:
        if not path_value or path_value in seen_paths:
            continue
        seen_paths.add(path_value)
        try:
            if os.path.exists(path_value):
                os.remove(path_value)
                deleted_paths.append(path_value)
        except Exception as e:
            failed_paths.append((path_value, str(e)))

    return deleted_paths, failed_paths


def upsert_ready_manifest_record(cursor, tbmt, so_qd, version, filename, full_path, schema_type):
    file_size_kb = round(os.path.getsize(full_path) / 1024, 2)
    cursor.execute("""
        DELETE FROM daily_manifest
        WHERE manifest_date = %s AND ma_tbmt = %s AND so_qd = %s AND version = %s
    """, (TARGET_DATE, tbmt, so_qd, version))
    cursor.execute("""
        INSERT INTO daily_manifest
        (manifest_date, ma_tbmt, so_qd, version, filename, schema_type, full_path, file_size_kb, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'READY')
        ON CONFLICT ON CONSTRAINT uq_manifest
        DO UPDATE SET
            schema_type = EXCLUDED.schema_type,
            full_path = EXCLUDED.full_path,
            file_size_kb = EXCLUDED.file_size_kb,
            status = 'READY'
    """, (TARGET_DATE, tbmt, so_qd, version, filename, schema_type, full_path, file_size_kb))


def import_human_results(task_type: str):
    task_type = task_type.upper()
    print(f"\n📥 ĐANG NHẬP KẾT QUẢ {task_type} TỪ HUMAN WORKSPACE [{TARGET_DATE}]...")

    source_dir, result_dir, _ = ensure_human_workspace_dirs(task_type)
    if not os.path.exists(result_dir):
        return print("❌ Không có thư mục result.")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, ma_tbmt, so_qd, version, source_filename, source_files_json,
                           expected_output_filename, issue_reason, status
                    FROM human_task_queue
                    WHERE work_date = %s AND task_type = %s
                      AND status IN ('EXPORTED', 'INVALID_OUTPUT', 'IN_PROGRESS', 'PENDING_EXPORT')
                    ORDER BY ma_tbmt, so_qd, version
                """, (TARGET_DATE, task_type))
                rows = cursor.fetchall()

                if not rows:
                    return print(f"❌ Không có task {task_type} nào đang chờ nhập.")

                imported_count = 0
                invalid_count = 0
                cleanup_paths = set()

                for row in rows:
                    task_id, tbmt, so_qd, version, source_filename, source_files_json, expected_output_filename, _, _ = row
                    source_files = parse_source_files_json(source_files_json)
                    result_path = find_result_file_for_task(result_dir, expected_output_filename)

                    if not result_path:
                        continue

                    result_filename = os.path.basename(result_path)
                    status, reason = identify_file_status_detailed(
                        result_path,
                        os.path.splitext(result_filename)[1],
                        tbmt,
                        source_files + [result_filename],
                    )

                    cursor.execute("""
                        UPDATE human_task_queue
                        SET import_attempts = import_attempts + 1,
                            result_filename = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (result_filename, task_id))

                    if status not in ['MEDICINE_STANDARD', 'GOODS_STANDARD']:
                        invalid_count += 1
                        cursor.execute("""
                            UPDATE human_task_queue
                            SET status = 'INVALID_OUTPUT',
                                validation_message = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (reason, task_id))
                        print(f"❌ {task_type} chưa đạt: {result_filename}\n   => {reason}")
                        continue

                    dest_filename = expected_output_filename
                    dest_path = os.path.join(SOURCE_DIR, dest_filename)
                    shutil.copy2(result_path, dest_path)
                    upsert_manual_file_to_packages(tbmt, so_qd, version, dest_path, "excel")
                    upsert_ready_manifest_record(cursor, tbmt, so_qd, version, dest_filename, dest_path, status)
                    cursor.execute("""
                        UPDATE human_task_queue
                        SET status = 'COMPLETED',
                            validation_message = 'OK',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (task_id,))
                    cleanup_paths.update(
                        build_human_task_artifact_paths(
                            task_type=task_type,
                            work_date=TARGET_DATE,
                            tbmt=tbmt,
                            so_qd=so_qd,
                            version=version,
                            source_files=source_files,
                            expected_output_filename=expected_output_filename,
                            result_filename=result_filename,
                        )
                    )
                    imported_count += 1
                    print(f"✅ ĐÃ NHẬP {task_type}: {dest_filename} -> {status}")

                conn.commit()

        deleted_artifacts, failed_cleanup = cleanup_human_workspace_artifacts(cleanup_paths)
        refresh_human_tasks_sheet(task_type)
        print(f"\n📊 KẾT QUẢ NHẬP {task_type}: Thành công {imported_count}, Lỗi validate {invalid_count}")
        print("💡 File chỉ được copy về latest khi đã validate pass.")
        if imported_count:
            print(f"🧹 Workspace đã dọn: {len(deleted_artifacts)} file")
            if failed_cleanup:
                print(f"⚠️ Workspace có {len(failed_cleanup)} file chưa xóa được.")
                for path_value, reason in failed_cleanup[:10]:
                    print(f"   - {path_value} -> {reason}")
    except psycopg2.Error as e:
        logger.error(f"❌ Lỗi import {task_type} từ human workspace: {e}")

# =====================================================================
# MAIN TASKS
# =====================================================================

# ----------------- TASK 1: TÌM LỖI FILE RAW -----------------
def scan_anomalies():
    print(f"\n🔍 ĐANG QUÉT BẤT THƯỜNG TẠI: {SOURCE_DIR}")
    if not os.path.exists(SOURCE_DIR):
        print(f"❌ Không tìm thấy folder: {SOURCE_DIR}")
        return

    converted_docx = auto_convert_docx_files_in_source()
    if converted_docx:
        logger.info(f"⚡ Đã auto-convert {len(converted_docx)} file Word sang Excel trước khi scan anomalies.")
        for src_name, out_name in converted_docx:
            logger.info(f"   ↳ {src_name} -> {out_name}")

    report_data = []
    files = [
        f for f in os.listdir(SOURCE_DIR)
        if not f.startswith('~$') and f.lower().endswith(('.xlsx', '.xls', '.pdf', '.doc', '.docx'))
    ]

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                ignored_qd_map = load_ignored_qd_map(cursor)
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
                units_by_tbmt_ver = {}
                for db_path, db_tbmt, db_qd in db_files:
                    if db_qd in ignored_qd_map.get(db_tbmt, set()):
                        continue
                    db_core_name = os.path.splitext(os.path.basename(db_path))[0]
                    _, _, db_version = parse_unit_from_filename(db_core_name)
                    units_by_tbmt_ver.setdefault((db_tbmt, db_version), set()).add(db_qd)

                file_to_qd_map = {}
                for db_path, db_tbmt, db_qd in db_files:
                    if db_qd in ignored_qd_map.get(db_tbmt, set()):
                        continue
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
                        tbmt, qd_raw, version = parse_unit_from_filename(f)
                        qd_candidates = units_by_tbmt_ver.get((tbmt, version), set())
                        qd_raw = resolve_qd_from_candidates(f, tbmt, version, qd_raw, qd_candidates)
                    if qd_raw in ignored_qd_map.get(tbmt, set()):
                        continue
                        
                    tbmt_qd_map.setdefault(tbmt, set()).add(qd_raw)

                found_tbmts = tuple(tb for tb in tbmt_qd_map.keys() if tb and tb != "UNKNOWN_TBMT")
                if found_tbmts:
                    cursor.execute("""
                        SELECT DISTINCT ma_tbmt, so_qd
                        FROM packages
                        WHERE ma_tbmt IN %s AND is_latest = 1
                    """, (found_tbmts,))
                    for db_tbmt, db_qd in cursor.fetchall():
                        if db_qd in ignored_qd_map.get(db_tbmt, set()):
                            continue
                        tbmt_qd_map.setdefault(db_tbmt, set()).add(db_qd)

                # 3. Ghi nhận lỗi
                for tbmt, qds in tbmt_qd_map.items():
                    if len(qds) > 1 and tbmt not in configured_tbmts:
                        report_data.append({
                            "TBMT": tbmt, "So_qd": "ALL", "Version": "ALL", "Priority": "HIGH", "Issue": "Multi-QD",
                            "Details": f"TBMT có {len(qds)} quyết định phê duyệt khác nhau", "Files": ", ".join(qds)
                        })

                if found_tbmts:
                    cursor.execute("""
                        SELECT ma_tbmt, so_qd, version, file_path
                        FROM packages
                        WHERE ma_tbmt IN %s AND is_latest = 1 AND file_type = 'excel'
                    """, (found_tbmts,))
                    for tbmt, so_qd, version, file_path in cursor.fetchall():
                        if so_qd in ignored_qd_map.get(tbmt, set()):
                            continue

                        sheet_names = get_excel_sheet_names_any(file_path)
                        if len(sheet_names) <= 1:
                            continue

                        report_data.append({
                            "TBMT": tbmt,
                            "So_qd": so_qd,
                            "Version": version,
                            "Priority": "MEDIUM",
                            "Issue": "Multi-Sheet Excel",
                            "Details": (
                                f"File Excel có {len(sheet_names)} sheet "
                                f"({', '.join(sheet_names[:6])}{'...' if len(sheet_names) > 6 else ''}). "
                                f"Hệ thống hiện mặc định đọc sheet đầu tiên, cần kiểm tra tay để tránh sót dữ liệu."
                            ),
                            "Files": os.path.basename(str(file_path or ""))
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
    converted_docx = auto_convert_docx_files_in_source()
    if converted_docx:
        logger.info(f"⚡ Đã auto-convert {len(converted_docx)} file Word sang Excel trước khi finalize.")
        for src_name, out_name in converted_docx:
            logger.info(f"   ↳ {src_name} -> {out_name}")
    
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
            if not f.startswith('~$') and f.endswith(('.xlsx', '.xls', '.pdf', '.doc', '.docx')):
                tbmt_prefix = f.split('_')[0]
                physical_map.setdefault(tbmt_prefix, []).append(f)
                found_tbmts.add(tbmt_prefix)
        if not found_tbmts: return print("⚠️ Folder rỗng.")
        sync_manual_files_in_latest(all_physical_files, found_tbmts)
    except Exception as e: return print(f"❌ Lỗi đọc folder: {e}")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                ignored_qd_map = load_ignored_qd_map(cursor)
                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version
                    FROM daily_manifest
                    WHERE manifest_date = %s AND status = 'PROCESSED'
                """, (TARGET_DATE,))
                processed_units = set(row for row in cursor.fetchall())

                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version
                    FROM packages
                    WHERE ma_tbmt IN %s AND is_latest = 1 AND file_type = 'excel'
                """, (tuple(found_tbmts),))
                ready_excel_units = {
                    row for row in cursor.fetchall()
                    if row[1] not in ignored_qd_map.get(row[0], set())
                }

                cursor.execute("""
                    SELECT ma_tbmt, so_qd, version
                    FROM daily_manifest
                    WHERE manifest_date = %s AND status = 'READY'
                """, (TARGET_DATE,))
                ready_units = {
                    row for row in cursor.fetchall()
                    if row in ready_excel_units
                }

                cursor.execute("""
                    SELECT p.ma_tbmt, p.so_qd, p.version, array_agg(p.file_path) AS file_paths,
                           COALESCE(r.relation_type, 'INDEPENDENT') AS relation_type,
                           COALESCE(r.so_qd_original, p.so_qd) AS qd_original
                    FROM packages p
                    LEFT JOIN qd_relations r
                      ON p.ma_tbmt = r.ma_tbmt AND p.so_qd = r.so_qd AND p.version = r.version
                    WHERE p.ma_tbmt IN %s AND p.is_latest = 1
                    GROUP BY p.ma_tbmt, p.so_qd, p.version, relation_type, qd_original
                """, (tuple(found_tbmts),))

                db_rows = [
                    {
                        "tbmt": row[0],
                        "so_qd": row[1],
                        "version": row[2],
                        "file_paths": row[3] or [],
                        "relation_type": row[4],
                        "qd_original": row[5],
                    }
                    for row in cursor.fetchall()
                    if row[1] not in ignored_qd_map.get(row[0], set())
                ]
                if not db_rows:
                    return print("⚠️ Không tìm thấy metadata trong DB.")

                relation_superseded_map = build_relation_superseded_units(db_rows, physical_map)
                relation_superseded_units = set(relation_superseded_map.keys())

                if relation_superseded_units:
                    unit_tuple = tuple(relation_superseded_units)
                    for schema_name, config in SCHEMAS.items():
                        table_name = config.get("table_name")
                        if not table_name:
                            continue
                        db_map = config.get("db_mapping", {})
                        db_tbmt = db_map.get("Mã TBMT", "ma_tbmt")
                        db_qd = db_map.get("so_qd_sanitized", "so_qd")
                        db_ver = db_map.get("version_code", "version")
                        cursor.execute(f"""
                            DELETE FROM {table_name}
                            WHERE ({db_tbmt}, {db_qd}, {db_ver}) IN %s
                        """, (unit_tuple,))
                    cursor.execute("""
                        DELETE FROM daily_manifest
                        WHERE manifest_date = %s
                          AND (ma_tbmt, so_qd, version) IN %s
                    """, (TARGET_DATE, unit_tuple))
                    cursor.execute("""
                        DELETE FROM human_task_queue
                        WHERE work_date = %s
                          AND (ma_tbmt, so_qd, version) IN %s
                    """, (TARGET_DATE, unit_tuple))
                    conn.commit()
                    ready_units = {row for row in ready_units if row not in relation_superseded_units}
                    processed_units = {row for row in processed_units if row not in relation_superseded_units}

                pending_anomaly_map = build_pending_anomaly_map(cursor, found_tbmts)
                pending_temp_abort_map = build_pending_temp_abort_map(cursor, found_tbmts)

                manifest_data, manifest_issues, processed_filenames = [], [], set()
                todo_count = 0
                ocr_human_tasks, manual_human_tasks = [], []
                total_ocr_source_files = 0
                blocked_by_anomaly_count = 0
                blocked_by_temp_abort_count = 0

                for unit in db_rows:
                    tbmt = unit["tbmt"]
                    qd_raw = unit["so_qd"]
                    version = unit["version"]
                    file_paths = unit["file_paths"]
                    unit_key = (tbmt, qd_raw, version)
                    if unit_key in processed_units or unit_key in ready_units:
                        continue

                    if unit_key in relation_superseded_units:
                        continue

                    pending_temp_abort = pending_temp_abort_map.get(tbmt)
                    if pending_temp_abort:
                        blocked_by_temp_abort_count += 1
                        manifest_issues.append({
                            "TBMT": tbmt,
                            "So_qd": qd_raw,
                            "Version": version,
                            "Filename": None,
                            "Issue_Type": "TEMP_ABORT_PENDING_RETRY",
                            "Issue_Reason": pending_temp_abort["reason"]
                        })
                        print(
                            f"🟠 TẠM HOÃN DO TEMP_ABORT: {tbmt} / {qd_raw} / v{version}\n"
                            f"   => {pending_temp_abort['reason']}"
                        )
                        continue

                    pending_anomaly = get_pending_anomaly_for_unit(tbmt, qd_raw, version, pending_anomaly_map)
                    if pending_anomaly:
                        blocked_by_anomaly_count += 1
                        manifest_issues.append({
                            "TBMT": tbmt,
                            "So_qd": qd_raw,
                            "Version": version,
                            "Filename": None,
                            "Issue_Type": "SCAN_ANOMALY_PENDING",
                            "Issue_Reason": f"{pending_anomaly['issue_type']}: {pending_anomaly['details']}"
                        })
                        print(
                            f"🟡 TẠM HOÃN DO ANOMALY: {tbmt} / {qd_raw} / v{version}\n"
                            f"   => {pending_anomaly['issue_type']}: {pending_anomaly['details']}"
                        )
                        continue

                    todo_count += 1
                    if batch_limit and todo_count > batch_limit: break

                    candidates = physical_map.get(tbmt, [])
                    if not candidates: continue

                    matched_files = find_matched_files_for_unit(candidates, file_paths, tbmt, qd_raw, version)
                    if not matched_files: continue

                    best_file = choose_best_file(matched_files)
                    if not best_file or best_file in processed_filenames: continue
                    processed_filenames.add(best_file)

                    full_path = os.path.join(SOURCE_DIR, best_file)
                    best_ext = os.path.splitext(best_file)[1].lower()

                    manual_file_type = infer_manual_file_type(best_file)
                    if manual_file_type in ('excel', 'pdf'):
                        upsert_manual_file_to_packages(tbmt, qd_raw, version, full_path, manual_file_type)

                    status, reason = identify_file_status_detailed(full_path, best_ext, tbmt, matched_files)

                    if status == "IGNORE": continue
                    if status == "MANUAL_FIX_REQUIRED":
                        print(f"🔴 CẦN SỬA TAY: {best_file}\n   => Lý do: {reason}")
                        manifest_issues.append({
                            "TBMT": tbmt,
                            "So_qd": qd_raw,
                            "Version": version,
                            "Filename": best_file,
                            "Issue_Type": "MANUAL_FIX_REQUIRED",
                            "Issue_Reason": reason
                        })
                        manual_human_tasks.append({
                            "TBMT": tbmt,
                            "So_qd": qd_raw,
                            "Version": version,
                            "Source_Filename": best_file,
                            "Source_Files": matched_files,
                            "Expected_Output_Filename": build_expected_result_filename(best_file),
                            "Issue_Reason": reason,
                        })

                    if status == "OCR_REQUIRED":
                        manifest_issues.append({
                            "TBMT": tbmt,
                            "So_qd": qd_raw,
                            "Version": version,
                            "Filename": best_file,
                            "Issue_Type": "OCR_REQUIRED",
                            "Issue_Reason": reason
                        })
                        pdf_sources = [f for f in matched_files if f.lower().endswith('.pdf')]
                        if pdf_sources:
                            total_ocr_source_files += len(pdf_sources)
                            primary_pdf = next((f for f in pdf_sources if f == best_file), pdf_sources[0])
                            ocr_human_tasks.append({
                                "TBMT": tbmt,
                                "So_qd": qd_raw,
                                "Version": version,
                                "Source_Filename": primary_pdf,
                                "Source_Files": pdf_sources,
                                "Expected_Output_Filename": build_expected_result_filename(primary_pdf, force_excel=True),
                                "Issue_Reason": reason,
                            })
                                
                    manifest_data.append({
                        "TBMT": tbmt, "Filename": best_file, "Schema_Type": status,
                        "Full_Path": full_path, "Size_KB": round(os.path.getsize(full_path)/1024, 2),
                        "So_qd": qd_raw, "Version": version
                    })

                if todo_count == 0 and blocked_by_anomaly_count == 0 and blocked_by_temp_abort_count == 0:
                    return print(f"✅ Tất cả file đã đạt READY.")

                if manifest_issues:
                    save_manifest_issues(manifest_issues)

                if manifest_data:
                    save_manifest_to_db(manifest_data)
                    ocr_exported = export_human_tasks("OCR", ocr_human_tasks)
                    manual_exported = export_human_tasks("MANUAL", manual_human_tasks)

                    ready_count = len([x for x in manifest_data if x['Schema_Type'] in ['MEDICINE_STANDARD', 'GOODS_STANDARD']])
                    ocr_pkg_count = len([x for x in manifest_data if x['Schema_Type'] == 'OCR_REQUIRED'])
                    manual_count = len([x for x in manifest_data if x['Schema_Type'] == 'MANUAL_FIX_REQUIRED'])

                    print(f"✅ Đã bổ sung {len(manifest_data)} gói thầu (Unit) vào Manifest.")
                    print(f"   - Sẵn sàng ETL (READY): {ready_count} gói")
                    print(f"   - Cần OCR: {ocr_pkg_count} gói (Tổng cộng {total_ocr_source_files} file PDF)")
                    print(f"   - Cần sửa tay: {manual_count} gói")
                    if blocked_by_temp_abort_count:
                        print(f"   - Tạm hoãn do TEMP_ABORT: {blocked_by_temp_abort_count} gói")
                    if blocked_by_anomaly_count:
                        print(f"   - Tạm hoãn do Scan Anomalies: {blocked_by_anomaly_count} gói")
                else:
                    if blocked_by_temp_abort_count or blocked_by_anomaly_count:
                        detail_parts = []
                        if blocked_by_temp_abort_count:
                            detail_parts.append(f"{blocked_by_temp_abort_count} gói TEMP_ABORT")
                        if blocked_by_anomaly_count:
                            detail_parts.append(f"{blocked_by_anomaly_count} gói Scan Anomalies")
                        print(f"🟡 Không tạo manifest vì {' và '.join(detail_parts)} đang bị chặn.")
                    else:
                        print("⚠️ Không tạo được manifest mục nào.")

    except psycopg2.Error as e:
        logger.error(f"❌ DB Error finalize: {e}")

# ----------------- TASK 3: AUTO - IMPORT KẾT QUẢ TỪ OCR -----------------
def manage_ocr_workflow():
    import_human_results("OCR")

# ----------------- TASK 4: RE-VALIDATE (SỬA TAY FILE ERROR) -----------------
def revalidate_manual_fixes():
    import_human_results("MANUAL")


def purge_related_records_interactive():
    print("\n🧹 XÓA DỮ LIỆU LIÊN QUAN")
    ma_tbmt = input("Mã TBMT cần xóa (có thể nhập nhiều mã, cách nhau bằng dấu cách/phẩy) [Enter nếu không dùng]: ").strip()
    package_phrase = input("Cụm từ trong tên gói thầu [Enter nếu không dùng]: ").strip()
    investor_phrase = input("Cụm từ trong tên chủ đầu tư [Enter nếu không dùng]: ").strip()
    contractor_phrase = input("Cụm từ trong tên nhà thầu [Enter nếu không dùng]: ").strip()
    preview = input("Chạy dry-run xem trước? [Y/n]: ").strip().lower()
    if preview in ("", "y", "yes"):
        purge_related_records(
            ma_tbmt=ma_tbmt,
            package_phrase=package_phrase,
            investor_phrase=investor_phrase,
            contractor_phrase=contractor_phrase,
            dry_run=True
        )
    confirm = input("Xác nhận xóa? Gõ DELETE để tiếp tục: ").strip()
    if confirm != "DELETE":
        print("ℹ️ Đã hủy thao tác xóa.")
        return

    purge_related_records(
        ma_tbmt=ma_tbmt,
        package_phrase=package_phrase,
        investor_phrase=investor_phrase,
        contractor_phrase=contractor_phrase
    )


def ignore_qd_unit_interactive():
    print("\n🚫 GHI NHẬN TYPO_ERROR CHO QĐ")
    ma_tbmt = input("Mã TBMT: ").strip()
    so_qd = input("Số QĐ cần bỏ qua: ").strip()
    version = input("Version của QĐ typo [Enter = 00]: ").strip() or "00"
    correct_qd = input("Số QĐ đúng để map về trong qd_relations: ").strip()
    note = input("Ghi chú [Enter nếu bỏ trống]: ").strip()
    preview = input("Chạy dry-run xem trước? [Y/n]: ").strip().lower()
    if preview in ("", "y", "yes"):
        ignore_qd_unit(ma_tbmt, so_qd, version, correct_qd, note=note, dry_run=True)
    confirm = input("Xác nhận bỏ qua? Gõ IGNORE để tiếp tục: ").strip()
    if confirm != "IGNORE":
        print("ℹ️ Đã hủy thao tác.")
        return
    ignore_qd_unit(ma_tbmt, so_qd, version, correct_qd, note=note, dry_run=False)


def mark_filtered_skip_records_interactive():
    print("\n🚩 GÁN FILTERED_SKIP VÀ DỌN DỮ LIỆU LIÊN QUAN")
    ma_tbmt = input("Mã TBMT cần gán skip (có thể nhập nhiều mã, cách nhau bằng dấu cách/phẩy) [Enter nếu không dùng]: ").strip()
    package_phrase = input("Cụm từ trong tên gói thầu [Enter nếu không dùng]: ").strip()
    investor_phrase = input("Cụm từ trong tên chủ đầu tư [Enter nếu không dùng]: ").strip()
    contractor_phrase = input("Cụm từ trong tên nhà thầu [Enter nếu không dùng]: ").strip()
    preview = input("Chạy dry-run xem trước? [Y/n]: ").strip().lower()
    if preview in ("", "y", "yes"):
        mark_filtered_skip_records(
            ma_tbmt=ma_tbmt,
            package_phrase=package_phrase,
            investor_phrase=investor_phrase,
            contractor_phrase=contractor_phrase,
            dry_run=True
        )
    confirm = input("Xác nhận gán skip và dọn dữ liệu? Gõ SKIP để tiếp tục: ").strip()
    if confirm != "SKIP":
        print("ℹ️ Đã hủy thao tác.")
        return
    mark_filtered_skip_records(
        ma_tbmt=ma_tbmt,
        package_phrase=package_phrase,
        investor_phrase=investor_phrase,
        contractor_phrase=contractor_phrase,
        dry_run=False
    )


def purge_crawl_batch_interactive():
    print("\n🧨 XÓA THEO CRAWL BATCH")
    print("1. Xóa theo lần crawl gần nhất (latest run_session)")
    print("2. Xóa theo ngày crawl chỉ định")
    mode_choice = input("👉 Chọn mode [1/2]: ").strip()
    if mode_choice == "1":
        mode = "latest_run"
        crawl_date = None
    elif mode_choice == "2":
        mode = "date"
        crawl_date = input("Nhập ngày crawl cần xóa (YYYYMMDD): ").strip()
    else:
        print("❌ Mode không hợp lệ.")
        return

    preview = input("Chạy dry-run xem trước? [Y/n]: ").strip().lower()
    if preview in ("", "y", "yes"):
        purge_crawl_batch(mode=mode, crawl_date=crawl_date, dry_run=True)
    confirm = input("Xác nhận xóa batch crawl? Gõ DELETE_CRAWL để tiếp tục: ").strip()
    if confirm != "DELETE_CRAWL":
        print("ℹ️ Đã hủy thao tác.")
        return
    purge_crawl_batch(mode=mode, crawl_date=crawl_date, dry_run=False)


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
        print("3. Import OCR Results (Nhập kết quả OCR từ human_workspace)")
        print("4. Import Manual Results (Nhập kết quả sửa tay từ human_workspace)")
        print("5. Purge Related Records (Xóa dữ liệu liên quan)")
        print("6. Mark FILTERED_SKIP & Purge (Gán skip vĩnh viễn và dọn dữ liệu liên quan)")
        print("7. Purge Crawl Batch (Xóa theo latest run hoặc ngày crawl)")
        print("0. Thoát")
        
        c = input("👉 Chọn task (0-7): ").strip()
        if c == "0": break
        elif c == "1": scan_anomalies()
        elif c == "2": finalize_and_generate_manifest()
        elif c == "3": manage_ocr_workflow()
        elif c == "4": revalidate_manual_fixes()
        elif c == "5": purge_related_records_interactive()
        elif c == "6": mark_filtered_skip_records_interactive()
        elif c == "7": purge_crawl_batch_interactive()
        else: print("❌ Lựa chọn không hợp lệ!")
        
