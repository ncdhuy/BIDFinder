# -*- coding: utf-8 -*-
import os
import time
import shutil
import re
import base64
import json
import unicodedata
from datetime import datetime
from urllib.parse import urlencode
import pandas as pd
import gc
import hashlib
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from storage_adapter import is_r2_key, move_object

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
    SessionNotCreatedException,
)
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ================== CẤU HÌNH ==================

# Cấu hình môi trường
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
BASE_DIR = os.getenv("BASE_DIR")
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")
USE_LOCAL_CHROMEDRIVER = str(os.getenv("USE_LOCAL_CHROMEDRIVER", "false")).strip().lower() in ("1", "true", "yes", "y")

if not DATABASE_URL:
    raise ValueError("❌ Thiếu biến môi trường DATABASE_URL")
if not BASE_DIR:
    raise ValueError("❌ Thiếu biến môi trường BASE_DIR")
if not CHROME_PROFILE_PATH:
    raise ValueError("❌ Thiếu biến môi trường CHROME_PROFILE_PATH")

DOWNLOAD_RAW = os.path.join(BASE_DIR, "raw_data", "chrome_downloads")
os.makedirs(DOWNLOAD_RAW, exist_ok=True)

options = webdriver.ChromeOptions()
options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH}")
options.add_argument("--disable-logging")
options.add_argument("--log-level=3")
options.add_experimental_option("excludeSwitches", ["enable-logging"])
prefs = {
    "download.default_directory": DOWNLOAD_RAW,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}
options.add_experimental_option("prefs", prefs)

driver = None
wait = None
NETWORK_CAPTURE_ENABLED = False


def build_chrome_options(enable_performance_logging=False):
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH}")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.add_experimental_option("prefs", prefs)
    if enable_performance_logging:
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return chrome_options

def _get_env_int(name, default=None):
    raw = os.getenv(name)
    if raw is None:
        return default
    raw_clean = str(raw).strip()
    if raw_clean == "" or raw_clean.lower() in {"none", "null"}:
        return default
    try:
        return int(raw_clean)
    except ValueError:
        raise ValueError(f"❌ Biến môi trường {name} phải là số nguyên, giá trị hiện tại: {raw}")


def _get_env_float(name, default=None):
    raw = os.getenv(name)
    if raw is None:
        return default
    raw_clean = str(raw).strip()
    if raw_clean == "" or raw_clean.lower() in {"none", "null"}:
        return default
    try:
        return float(raw_clean)
    except ValueError:
        raise ValueError(f"❌ Biến môi trường {name} phải là số, giá trị hiện tại: {raw}")


def _get_env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


# Cấu hình logic skip
SKIP_DAYS = _get_env_int("SKIP_DAYS", 7)
KHLCNT_LINKED_PENDING_SKIP_DAYS = _get_env_int("KHLCNT_LINKED_PENDING_SKIP_DAYS", 30)
KHLCNT_RESULTDTO_TIMEOUT = _get_env_float("KHLCNT_RESULTDTO_TIMEOUT", 10)
KHLCNT_BACKFILL_CURSOR_ENABLED = _get_env_bool("KHLCNT_BACKFILL_CURSOR_ENABLED", False)
KHLCNT_BACKFILL_CURSOR_FILE = os.getenv("KHLCNT_BACKFILL_CURSOR_FILE") or os.path.join(BASE_DIR, "khlcnt_backfill_cursor.json")
FORCE_FULL_SCAN = _get_env_bool("FORCE_FULL_SCAN", False)

# Cấu hình từ khóa
KEY = os.getenv("KEY")
KEY_BATCHES = os.getenv("KEY_BATCHES")
EXC_KEY = os.getenv("EXC_KEY")
SEARCH_MATCH_MODE = (os.getenv("SEARCH_MATCH_MODE") or "exact").strip()
SEARCH_MATCH_MODE_MAP = os.getenv("SEARCH_MATCH_MODE_MAP")
SEARCH_NOTICE_TYPE = os.getenv("SEARCH_NOTICE_TYPE")
SEARCH_NOTICE_TYPES = os.getenv("SEARCH_NOTICE_TYPES")
YEAR_FROM = _get_env_int("YEAR_FROM")
YEAR_TO = _get_env_int("YEAR_TO")
MAX_PAGES = _get_env_int("MAX_PAGES")
MAX_TRY = _get_env_int("MAX_TRY", 7)
UI_BLOCKER_PROBE_TIMEOUT = _get_env_int("UI_BLOCKER_PROBE_TIMEOUT_MS", 150) / 1000
UI_BLOCKER_POST_WAIT_TIMEOUT = _get_env_int("UI_BLOCKER_POST_WAIT_TIMEOUT_MS", 500) / 1000

DEFAULT_SEARCH_NOTICE_TYPE = "Thông báo mời thầu"
KHLCNT_SEARCH_NOTICE_TYPE = "Kế hoạch lựa chọn nhà thầu"
SEARCH_NOTICE_TYPE_LABELS = {
    "tbmt": DEFAULT_SEARCH_NOTICE_TYPE,
    "thong-bao-moi-thau": DEFAULT_SEARCH_NOTICE_TYPE,
    "thông báo mời thầu": DEFAULT_SEARCH_NOTICE_TYPE,
    "kh-lcnt": KHLCNT_SEARCH_NOTICE_TYPE,
    "ke-hoach-lua-chon-nha-thau": KHLCNT_SEARCH_NOTICE_TYPE,
    "kế hoạch lựa chọn nhà thầu": KHLCNT_SEARCH_NOTICE_TYPE,
}

MATCH_MODE_LABELS = {
    "all-1": "Khớp tất cả từ (Phân biệt dấu)",
    "all-0": "Khớp tất cả từ (Không phân biệt dấu)",
    "any-1": "Khớp từ hoặc một số từ (Phân biệt dấu)",
    "any-0": "Khớp từ hoặc một số từ (Không phân biệt dấu)",
    "exact": "Khớp chính xác cụm từ",
}

if SEARCH_MATCH_MODE not in MATCH_MODE_LABELS:
    raise ValueError(
        f"❌ SEARCH_MATCH_MODE không hợp lệ: {SEARCH_MATCH_MODE}. "
        f"Giá trị cho phép: {', '.join(MATCH_MODE_LABELS.keys())}"
    )

def _parse_keyword_batches(raw_batches, fallback_key):
    if raw_batches and str(raw_batches).strip():
        parts = re.split(r"\r?\n|\|\|", str(raw_batches))
        batches = [p.strip() for p in parts if p and p.strip()]
        if batches:
            return batches

    fallback = (fallback_key or "").strip()
    return [fallback] if fallback else []


SEARCH_KEYWORDS = _parse_keyword_batches(KEY_BATCHES, KEY)


def _resolve_search_notice_type_label(value):
    label = (value or "").strip()
    if not label:
        return DEFAULT_SEARCH_NOTICE_TYPE
    return SEARCH_NOTICE_TYPE_LABELS.get(label.lower(), label)


def _parse_search_notice_types(raw_types, raw_type):
    raw_value = raw_types if raw_types and str(raw_types).strip() else raw_type
    if raw_value and str(raw_value).strip():
        parts = re.split(r"\r?\n|\|\|", str(raw_value))
        labels = []
        for part in parts:
            label = _resolve_search_notice_type_label(part)
            if label and label not in labels:
                labels.append(label)
        if labels:
            return labels
    return [DEFAULT_SEARCH_NOTICE_TYPE]


SEARCH_NOTICE_TYPE_LIST = _parse_search_notice_types(SEARCH_NOTICE_TYPES, SEARCH_NOTICE_TYPE)


def _parse_match_mode_map(raw_value):
    mapping = {}
    if not raw_value or not str(raw_value).strip():
        return mapping

    parts = re.split(r"\r?\n|\|\|", str(raw_value))
    for part in parts:
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"❌ SEARCH_MATCH_MODE_MAP sai định dạng: '{item}'. Dùng dạng keyword:mode")
        keyword, mode = item.split(":", 1)
        keyword = keyword.strip().lower()
        mode = mode.strip()
        if not keyword:
            raise ValueError(f"❌ SEARCH_MATCH_MODE_MAP có keyword rỗng: '{item}'")
        if mode not in MATCH_MODE_LABELS:
            raise ValueError(
                f"❌ SEARCH_MATCH_MODE_MAP có mode không hợp lệ: {mode}. "
                f"Giá trị cho phép: {', '.join(MATCH_MODE_LABELS.keys())}"
            )
        mapping[keyword] = mode
    return mapping


SEARCH_MATCH_MODE_BY_KEYWORD = _parse_match_mode_map(SEARCH_MATCH_MODE_MAP)


# ================== HELPER ==================
def _nullify(val):
    """Chuyển empty string thành None để PostgreSQL lưu NULL thay vì ''."""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    return val


def _collapse_whitespace(value):
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def clean_vnd_amount(value):
    text = _collapse_whitespace(value)
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or text


def _version_key(version_value):
    """
    Chuẩn hóa version nghiệp vụ về tuple số để so sánh ổn định.
    Hỗ trợ:
    - "00", "01", "02"
    - "00-01", "01-01", "02-02" (nguồn web dạng xx/yy đã normalize thành xx-yy)
    """
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


# ================== DATABASE MANAGER ==================
class CrawlerDB:
    def __init__(self):
        self._connect()
        self._ensure_web_winner_facts_schema()

    def _connect(self):
        """Tạo hoặc tái kết nối PostgreSQL"""
        self.conn = psycopg2.connect(DATABASE_URL)
        self.conn.autocommit = False
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _reconnect(self):
        """Tự động reconnect nếu connection bị timeout (Neon tự ngắt sau vài phút idle)"""
        try:
            self.conn.close()
        except Exception:
            pass
        self._connect()

    def _ensure_web_winner_facts_schema(self):
        try:
            self._safe_execute("""
                CREATE TABLE IF NOT EXISTS web_winner_facts (
                    ma_tbmt TEXT NOT NULL,
                    so_qd TEXT NOT NULL,
                    version TEXT NOT NULL,
                    capture_status TEXT NOT NULL,
                    only_winner_name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ma_tbmt, so_qd, version)
                )
            """)
            self._safe_execute("""
                ALTER TABLE web_winner_facts
                DROP COLUMN IF EXISTS winner_count,
                DROP COLUMN IF EXISTS winner_names_json,
                DROP COLUMN IF EXISTS capture_note,
                DROP COLUMN IF EXISTS created_at
            """)
            self._safe_execute("""
                DROP INDEX IF EXISTS idx_web_winner_facts_status
            """)
            self._safe_execute("""
                CREATE INDEX idx_web_winner_facts_status
                ON web_winner_facts (capture_status)
            """)
            self._safe_execute("""
                ALTER TABLE package_metadata
                ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP
            """)
            self._safe_execute("""
                CREATE INDEX IF NOT EXISTS idx_metadata_last_checked_at
                ON package_metadata (last_checked_at)
            """)
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.warning(f"⚠️ Không thể đảm bảo schema web_winner_facts: {e}")

    def _safe_execute(self, sql, params=None):
        """Wrapper thực thi query có tự reconnect nếu connection bị đứt"""
        try:
            self.cursor.execute(sql, params)
        except psycopg2.OperationalError:
            logger.warning("⚠️ Kết nối DB bị ngắt, đang reconnect...")
            self._reconnect()
            self.cursor.execute(sql, params)

    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _nullify(self, value):
        """
        Hàm tiện ích giúp làm sạch dữ liệu:
        Biến các chuỗi rỗng, 'nan', 'none' thành None (để lưu vào PostgreSQL thành NULL).
        Giữ nguyên các giá trị hợp lệ.
        """
        if pd.isna(value) or value is None:
            return None
            
        if isinstance(value, str):
            val_str = value.strip()
            if val_str == "" or val_str.lower() in ["nan", "none", "null", "<na>", "nat"]:
                return None
            return val_str
            
        return value

    # --- CORE METHODS ---
    def _replace_storage_segment(self, path_value: str, from_segment: str, to_segment: str) -> str:
        if not path_value:
            return path_value
        normalized = path_value.replace("\\", "/")
        parts = normalized.split("/")
        if from_segment in parts:
            idx = parts.index(from_segment)
            parts[idx] = to_segment
            return "/".join(parts)
        return path_value

    def _archive_existing_file(self, tbmt, qd_raw, file_type, old_ver, old_path, archive_dir):
        if not old_path:
            logger.warning(f"⚠️ Không có file_path cho bản cũ v{old_ver}.")
            return

        try:
            if is_r2_key(old_path):
                new_archive_key = self._replace_storage_segment(old_path, "latest", "archive")
                if new_archive_key != old_path:
                    move_object(old_path, new_archive_key)
                    self._safe_execute("""
                        UPDATE packages
                        SET file_path=%s
                        WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s AND version=%s
                    """, (new_archive_key, tbmt, qd_raw, file_type, old_ver))
                    logger.info(f"📂 -> Đã archive v{old_ver} trên R2.")
                else:
                    logger.info(f"ℹ️ File cũ v{old_ver} không nằm ở latest, giữ nguyên path.")
                return

            if os.path.exists(old_path):
                normalized_old = old_path.replace("\\", "/")
                if "/latest/" in normalized_old or normalized_old.endswith("/latest"):
                    filename = os.path.basename(old_path)
                    new_archive_path = os.path.join(archive_dir, filename)
                    os.makedirs(os.path.dirname(new_archive_path), exist_ok=True)
                    shutil.move(old_path, new_archive_path)
                    self._safe_execute("""
                        UPDATE packages
                        SET file_path=%s
                        WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s AND version=%s
                    """, (new_archive_path, tbmt, qd_raw, file_type, old_ver))
                    logger.info(f"📂 -> Chuyển v{old_ver} sang Archive local.")
                else:
                    logger.info(f"ℹ️ Bản cũ v{old_ver} đã nằm ngoài latest, không cần move.")
            else:
                logger.warning(f"⚠️ Không tìm thấy file cũ v{old_ver} trên local: {old_path}")
        except Exception as e:
            logger.warning(f"⚠️ Lỗi archive file cũ v{old_ver}: {e}")

    def _archive_existing_unit_versions(self, tbmt, qd_raw, new_ver, archive_dir):
        new_ver_key = _version_key(new_ver)
        self._safe_execute("""
            SELECT version, file_type, file_path
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND is_latest=1
        """, (tbmt, qd_raw))
        rows = self.cursor.fetchall() or []

        archived_pairs = set()
        for row in rows:
            old_ver = row["version"]
            file_type = row["file_type"]
            old_path = row["file_path"]
            pair_key = (str(old_ver), str(file_type), str(old_path))
            if pair_key in archived_pairs:
                continue
            if _version_key(old_ver) >= new_ver_key:
                continue
            archived_pairs.add(pair_key)
            self._archive_existing_file(tbmt, qd_raw, file_type, old_ver, old_path, archive_dir)

    def _refresh_unit_latest_flags(self, tbmt, qd_raw):
        self._safe_execute("""
            SELECT version
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s
        """, (tbmt, qd_raw))
        rows = self.cursor.fetchall() or []
        if not rows:
            return

        latest_ver = max((row["version"] for row in rows), key=_version_key)
        self._safe_execute("""
            UPDATE packages
            SET is_latest = CASE WHEN version=%s THEN 1 ELSE 0 END
            WHERE ma_tbmt=%s AND so_qd=%s
        """, (latest_ver, tbmt, qd_raw))

    def _local_file_md5(self, path_value):
        try:
            if not path_value or not os.path.exists(path_value) or not os.path.isfile(path_value):
                return None
            digest = hashlib.md5()
            with open(path_value, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            return None

    def _pdf_records_are_equivalent(self, path_a, filename_a, path_b, filename_b):
        base_a = os.path.basename(str(path_a or filename_a or "")).strip().lower()
        base_b = os.path.basename(str(path_b or filename_b or "")).strip().lower()
        if base_a and base_b and base_a == base_b:
            return True

        try:
            if (
                path_a and path_b
                and os.path.exists(path_a) and os.path.isfile(path_a)
                and os.path.exists(path_b) and os.path.isfile(path_b)
            ):
                size_a = os.path.getsize(path_a)
                size_b = os.path.getsize(path_b)
                if size_a == size_b and size_a > 0:
                    hash_a = self._local_file_md5(path_a)
                    hash_b = self._local_file_md5(path_b)
                    if hash_a and hash_a == hash_b:
                        return True
        except Exception:
            pass

        return False

    def _cleanup_existing_pdf_duplicates(self, tbmt, qd_raw, version):
        self._safe_execute("""
            SELECT file_type, file_path
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND version=%s
              AND file_type IN ('pdf', 'attachment')
        """, (tbmt, qd_raw, version))
        rows = self.cursor.fetchall() or []

        pdf_rows = [row for row in rows if row["file_type"] == "pdf"]
        attachment_pdf_rows = [
            row for row in rows
            if row["file_type"] == "attachment"
            and os.path.splitext(str(row["file_path"] or ""))[1].lower() == ".pdf"
        ]

        if not pdf_rows or not attachment_pdf_rows:
            return

        for pdf_row in pdf_rows:
            for attachment_row in attachment_pdf_rows:
                if not self._pdf_records_are_equivalent(
                    pdf_row["file_path"], pdf_row["file_path"],
                    attachment_row["file_path"], attachment_row["file_path"]
                ):
                    continue

                self._safe_execute("""
                    DELETE FROM packages
                    WHERE ma_tbmt=%s AND so_qd=%s AND version=%s AND file_type='attachment'
                """, (tbmt, qd_raw, version))
                self.conn.commit()
                logger.info(f"🧹 Đã chuẩn hóa packages: bỏ record attachment trùng với PDF QĐ cho {tbmt} / {qd_raw} / v{version}.")
                return

    def _normalize_cross_type_pdf_duplicate(self, tbmt, qd_raw, version, file_type, temp_path, incoming_filename):
        if file_type not in ("pdf", "attachment"):
            return None

        if os.path.splitext(str(incoming_filename or ""))[1].lower() != ".pdf":
            return None

        other_type = "attachment" if file_type == "pdf" else "pdf"

        self._safe_execute("""
            SELECT file_type, file_path
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND version=%s
              AND file_type IN ('pdf', 'attachment')
        """, (tbmt, qd_raw, version))
        rows = self.cursor.fetchall() or []

        for row in rows:
            existing_type = row["file_type"]
            existing_path = row["file_path"]

            if existing_type != other_type:
                continue

            if existing_type == "attachment" and os.path.splitext(str(existing_path or ""))[1].lower() != ".pdf":
                continue

            if not self._pdf_records_are_equivalent(
                temp_path, incoming_filename,
                existing_path, existing_path
            ):
                continue

            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

            if file_type == "attachment":
                logger.info(f"↪️ Bỏ qua PDF attachment trùng với PDF QĐ: {tbmt} / {qd_raw} / v{version}.")
                return "SKIPPED_DUPLICATE", existing_path

            self._safe_execute("""
                UPDATE packages
                SET file_type='pdf', crawled_at=%s, status='DONE'
                WHERE ma_tbmt=%s AND so_qd=%s AND version=%s AND file_type='attachment'
            """, (self._now_str(), tbmt, qd_raw, version))
            self.conn.commit()
            logger.info(f"🔁 Đã chuẩn hóa record attachment thành pdf cho {tbmt} / {qd_raw} / v{version}.")
            return "NORMALIZED_DUPLICATE", existing_path

        return None

    def check_and_save(self, tbmt, qd_raw, version, file_type, temp_path, target_root_dir):
        ver_chk = version if version else "00"
        ver_chk_key = _version_key(ver_chk)

        orig_name = os.path.basename(temp_path)
        safe_tbmt = "".join(c for c in tbmt if c.isalnum() or c in ".-_")
        safe_qd_raw = sanitize_filename_part(qd_raw) if qd_raw else "UNKNOWN_QD"
        new_filename = f"{safe_tbmt}_v{ver_chk}_{safe_qd_raw}_{orig_name}"

        self._cleanup_existing_pdf_duplicates(tbmt, qd_raw, ver_chk)

        self._safe_execute("""
            SELECT file_path
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s AND version=%s
        """, (tbmt, qd_raw, file_type, ver_chk))
        existing_package = self.cursor.fetchone()
        if existing_package:
            existing_path = existing_package["file_path"]
            if existing_path and os.path.exists(existing_path):
                return "SKIPPED", None
            logger.warning(
                f"♻️ Packages đã có record nhưng file local mất, sẽ tải lại và cập nhật path: "
                f"{tbmt} / {qd_raw} / v{ver_chk} / {file_type}"
            )

        duplicate_result = self._normalize_cross_type_pdf_duplicate(
            tbmt, qd_raw, ver_chk, file_type, temp_path, new_filename
        )
        if duplicate_result:
            return duplicate_result

        today_str = datetime.now().strftime("%Y%m%d")
        latest_dir = os.path.join(target_root_dir, "raw_data", today_str, "latest")
        archive_dir = os.path.join(target_root_dir, "raw_data", today_str, "archive")
        os.makedirs(latest_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)

        self._safe_execute("""
            SELECT version
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s
        """, (tbmt, qd_raw))
        existing_unit_rows = self.cursor.fetchall() or []
        latest_unit_ver = max((row["version"] for row in existing_unit_rows), key=_version_key) if existing_unit_rows else None

        if latest_unit_ver:
            latest_unit_ver_key = _version_key(latest_unit_ver)
            if ver_chk_key > latest_unit_ver_key:
                logger.info(
                    f"🔄 Phát hiện bản mới v{ver_chk} (cũ v{latest_unit_ver}). "
                    f"Tiến hành archive toàn bộ file latest của các version cũ..."
                )
                self._archive_existing_unit_versions(tbmt, qd_raw, ver_chk, archive_dir)
                final_path = os.path.join(latest_dir, new_filename)
            elif ver_chk_key < latest_unit_ver_key:
                logger.warning(f"⚠️  Bản hiện tại v{ver_chk} < bản mới nhất của unit v{latest_unit_ver}")
                final_path = os.path.join(archive_dir, new_filename)
            else:
                final_path = os.path.join(latest_dir, new_filename)
        else:
            final_path = os.path.join(latest_dir, new_filename)

        try:
            shutil.move(temp_path, final_path)
        except Exception as e:
            logger.error(f"❌ Error moving file: {e}")
            return "ERROR", None

        if existing_package:
            self._safe_execute("""
                UPDATE packages
                SET file_path=%s, crawled_at=%s, status='DONE'
                WHERE ma_tbmt=%s AND so_qd=%s AND version=%s AND file_type=%s
            """, (final_path, self._now_str(), tbmt, qd_raw, ver_chk, file_type))
        else:
            self._safe_execute("""
                INSERT INTO packages (ma_tbmt, so_qd, version, file_type, file_path, crawled_at, status, is_latest)
                VALUES (%s, %s, %s, %s, %s, %s, 'DONE', 0)
            """, (tbmt, qd_raw, ver_chk, file_type, final_path, self._now_str()))

        self._refresh_unit_latest_flags(tbmt, qd_raw)

        self.conn.commit()
        return "INSERT", final_path

    # --- METADATA ---
    def save_metadata(self, tbmt, qd_raw, version, info_dict):
        ver_save = version if version else '00'
        # Dùng _nullify: empty string -> None -> PostgreSQL NULL
        val_map = {
            'ngay_dang_tai': self._nullify(info_dict.get('Ngày đăng tải')),
            'trang_thai_dang_tai_kq': self._nullify(info_dict.get('Trạng thái đăng tải KQ') or info_dict.get('Trạng thái KQLCNT')),
            'chu_dau_tu': self._nullify(info_dict.get('Chủ đầu tư')),
            'ten_goi_thau': self._nullify(info_dict.get('Tên gói thầu')),
            'linh_vuc': self._nullify(info_dict.get('Lĩnh vực')),
            'hinh_thuc_lcnt': self._nullify(info_dict.get('Hình thức lựa chọn nhà thầu') or info_dict.get('Hình thức LCNT')),
            'phuong_thuc_lcnt': self._nullify(info_dict.get('Phương thức lựa chọn nhà thầu')),
            'dau_thau_qua_mang': self._nullify(info_dict.get('Đấu thầu qua mạng')),
            'trong_nuoc_quoc_te': self._nullify(info_dict.get('Trong nước/ Quốc tế')),
            'gia_goi_thau': self._nullify(clean_vnd_amount(info_dict.get('Giá gói thầu'))),
            'gia_du_toan': self._nullify(clean_vnd_amount(info_dict.get('Giá dự toán'))),
            'ngay_phe_duyet': self._nullify(info_dict.get('Ngày phê duyệt')),
            'trang_thai_phe_duyet': self._nullify(info_dict.get('Trạng thái phê duyệt')),
            'co_quan_phe_duyet': self._nullify(info_dict.get('Cơ quan phê duyệt')),
            'loai_hop_dong': self._nullify(info_dict.get('Loại hợp đồng')),
            'thoi_gian_thuc_hien': self._nullify(info_dict.get('Thời gian thực hiện gói thầu')),
            'ket_qua_dau_thau': self._nullify(info_dict.get('Kết quả đấu thầu')),
            'dia_diem': self._nullify(info_dict.get('Địa điểm')),
            'cach_thuc_tai_ve': self._nullify(info_dict.get('Cách thức tải về')),
            'ma_khlcnt': self._nullify(info_dict.get('Mã KHLCNT')),
            'ma_khlcnt_full': self._nullify(info_dict.get('Mã KHLCNT đầy đủ')),
            'khlcnt_version': self._nullify(info_dict.get('Phiên bản KHLCNT')),
            'ten_khlcnt': self._nullify(info_dict.get('Tên KHLCNT')),
        }
        approval_date = None
        if val_map['ngay_phe_duyet']:
            try:
                approval_date = datetime.strptime(str(val_map['ngay_phe_duyet']).strip(), "%d/%m/%Y").date()
            except ValueError:
                approval_date = None

        self._safe_execute("""
            INSERT INTO package_metadata (
                ma_tbmt, so_qd, version, ngay_dang_tai, trang_thai_dang_tai_kq, chu_dau_tu,
                ten_goi_thau, linh_vuc, hinh_thuc_lcnt, phuong_thuc_lcnt, dau_thau_qua_mang,
                trong_nuoc_quoc_te, gia_goi_thau, gia_du_toan, ngay_phe_duyet, ngay_phe_duyet_date, trang_thai_phe_duyet,
                co_quan_phe_duyet, loai_hop_dong, thoi_gian_thuc_hien, ket_qua_dau_thau,
                dia_diem, cach_thuc_tai_ve,
                ma_khlcnt, ma_khlcnt_full, khlcnt_version, ten_khlcnt,
                last_checked_at, updated_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT(ma_tbmt, so_qd, version) DO UPDATE SET 
                ngay_dang_tai = COALESCE(EXCLUDED.ngay_dang_tai, package_metadata.ngay_dang_tai),
                trang_thai_dang_tai_kq = COALESCE(EXCLUDED.trang_thai_dang_tai_kq, package_metadata.trang_thai_dang_tai_kq),
                chu_dau_tu = COALESCE(EXCLUDED.chu_dau_tu, package_metadata.chu_dau_tu),
                ten_goi_thau = COALESCE(EXCLUDED.ten_goi_thau, package_metadata.ten_goi_thau),
                linh_vuc = COALESCE(EXCLUDED.linh_vuc, package_metadata.linh_vuc),
                hinh_thuc_lcnt = COALESCE(EXCLUDED.hinh_thuc_lcnt, package_metadata.hinh_thuc_lcnt),
                phuong_thuc_lcnt = COALESCE(EXCLUDED.phuong_thuc_lcnt, package_metadata.phuong_thuc_lcnt),
                dau_thau_qua_mang = COALESCE(EXCLUDED.dau_thau_qua_mang, package_metadata.dau_thau_qua_mang),
                trong_nuoc_quoc_te = COALESCE(EXCLUDED.trong_nuoc_quoc_te, package_metadata.trong_nuoc_quoc_te),
                gia_goi_thau = COALESCE(EXCLUDED.gia_goi_thau, package_metadata.gia_goi_thau),
                gia_du_toan = COALESCE(EXCLUDED.gia_du_toan, package_metadata.gia_du_toan),
                ngay_phe_duyet = COALESCE(EXCLUDED.ngay_phe_duyet, package_metadata.ngay_phe_duyet),
                ngay_phe_duyet_date = COALESCE(EXCLUDED.ngay_phe_duyet_date, package_metadata.ngay_phe_duyet_date),
                trang_thai_phe_duyet = COALESCE(EXCLUDED.trang_thai_phe_duyet, package_metadata.trang_thai_phe_duyet),
                co_quan_phe_duyet = COALESCE(EXCLUDED.co_quan_phe_duyet, package_metadata.co_quan_phe_duyet),
                loai_hop_dong = COALESCE(EXCLUDED.loai_hop_dong, package_metadata.loai_hop_dong),
                thoi_gian_thuc_hien = COALESCE(EXCLUDED.thoi_gian_thuc_hien, package_metadata.thoi_gian_thuc_hien),
                ket_qua_dau_thau = COALESCE(EXCLUDED.ket_qua_dau_thau, package_metadata.ket_qua_dau_thau),
                dia_diem = COALESCE(EXCLUDED.dia_diem, package_metadata.dia_diem),
                cach_thuc_tai_ve = COALESCE(EXCLUDED.cach_thuc_tai_ve, package_metadata.cach_thuc_tai_ve),
                ma_khlcnt = COALESCE(EXCLUDED.ma_khlcnt, package_metadata.ma_khlcnt),
                ma_khlcnt_full = COALESCE(EXCLUDED.ma_khlcnt_full, package_metadata.ma_khlcnt_full),
                khlcnt_version = COALESCE(EXCLUDED.khlcnt_version, package_metadata.khlcnt_version),
                ten_khlcnt = COALESCE(EXCLUDED.ten_khlcnt, package_metadata.ten_khlcnt),
                last_checked_at = EXCLUDED.last_checked_at,
                updated_at = EXCLUDED.updated_at
        """, (
            tbmt, qd_raw, ver_save,
            val_map['ngay_dang_tai'], val_map['trang_thai_dang_tai_kq'], val_map['chu_dau_tu'],
            val_map['ten_goi_thau'], val_map['linh_vuc'], val_map['hinh_thuc_lcnt'],
            val_map['phuong_thuc_lcnt'], val_map['dau_thau_qua_mang'], val_map['trong_nuoc_quoc_te'],
            val_map['gia_goi_thau'], val_map['gia_du_toan'], val_map['ngay_phe_duyet'], approval_date,
            val_map['trang_thai_phe_duyet'], val_map['co_quan_phe_duyet'], val_map['loai_hop_dong'],
            val_map['thoi_gian_thuc_hien'], val_map['ket_qua_dau_thau'], val_map['dia_diem'],
            val_map['cach_thuc_tai_ve'],
            val_map['ma_khlcnt'], val_map['ma_khlcnt_full'], val_map['khlcnt_version'], val_map['ten_khlcnt'],
            self._now_str(), self._now_str()
        ))
        if val_map['ma_khlcnt']:
            self._safe_execute("""
                DELETE FROM scan_logs
                WHERE ma_khlcnt=%s
                  AND ma_tbmt=%s
                  AND action_type='KHLCNT_LINKED_PENDING'
            """, (val_map['ma_khlcnt'], tbmt))
        self.conn.commit()

    def save_khlcnt_metadata_for_tbmt(self, tbmt, info_dict):
        tbmt_save = str(tbmt or "").strip()
        if not tbmt_save:
            return 0

        values = {
            'ma_khlcnt': self._nullify(info_dict.get('Mã KHLCNT')),
            'ma_khlcnt_full': self._nullify(info_dict.get('Mã KHLCNT đầy đủ')),
            'khlcnt_version': self._nullify(info_dict.get('Phiên bản KHLCNT')),
            'ten_khlcnt': self._nullify(info_dict.get('Tên KHLCNT')),
            'phan_loai_goi_thau': self._nullify(info_dict.get('Phân loại gói thầu')),
            'url_goi_thau_con': self._nullify(info_dict.get('URL gói thầu con')),
        }
        self._safe_execute("""
            UPDATE package_metadata
            SET
                ma_khlcnt = COALESCE(NULLIF(ma_khlcnt, ''), %s),
                ma_khlcnt_full = COALESCE(NULLIF(ma_khlcnt_full, ''), %s),
                khlcnt_version = COALESCE(NULLIF(khlcnt_version, ''), %s),
                ten_khlcnt = COALESCE(NULLIF(ten_khlcnt, ''), %s),
                phan_loai_goi_thau = COALESCE(NULLIF(phan_loai_goi_thau, ''), %s),
                url_goi_thau_con = COALESCE(NULLIF(url_goi_thau_con, ''), %s),
                updated_at = %s
            WHERE ma_tbmt = %s
        """, (
            values['ma_khlcnt'], values['ma_khlcnt_full'], values['khlcnt_version'],
            values['ten_khlcnt'], values['phan_loai_goi_thau'],
            values['url_goi_thau_con'], self._now_str(), tbmt_save
        ))
        updated = self.cursor.rowcount or 0
        if updated and values['ma_khlcnt']:
            self._safe_execute("""
                DELETE FROM scan_logs
                WHERE ma_khlcnt=%s
                  AND ma_tbmt=%s
                  AND action_type='KHLCNT_LINKED_PENDING'
            """, (values['ma_khlcnt'], tbmt_save))
        self.conn.commit()
        return updated

    def save_web_winner_fact(self, tbmt, qd_raw, version, fact_payload, commit=True):
        if not fact_payload:
            return False

        tbmt_save = str(tbmt or "").strip() or "UNKNOWN_TBMT"
        qd_save = str(qd_raw or "").strip() or "UNKNOWN_QD"
        ver_save = version if version else "00"
        status = self._nullify(_collapse_whitespace(fact_payload.get("capture_status"))) or "UNKNOWN"
        only_winner_name = self._nullify(_collapse_whitespace(fact_payload.get("only_winner_name")))

        try:
            self._safe_execute("""
                INSERT INTO web_winner_facts (
                    ma_tbmt, so_qd, version, capture_status, only_winner_name, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (ma_tbmt, so_qd, version) DO UPDATE SET
                    capture_status = EXCLUDED.capture_status,
                    only_winner_name = EXCLUDED.only_winner_name,
                    updated_at = CURRENT_TIMESTAMP
                WHERE web_winner_facts.capture_status IS DISTINCT FROM EXCLUDED.capture_status
                   OR web_winner_facts.only_winner_name IS DISTINCT FROM EXCLUDED.only_winner_name
            """, (
                tbmt_save,
                qd_save,
                ver_save,
                status,
                only_winner_name,
            ))
            if commit:
                self.conn.commit()
            return True
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.warning(f"⚠️ Không lưu được web_winner_fact cho {tbmt_save} / {qd_save} / v{ver_save}: {e}")
            return False


    # --- LOGS & HELPERS ---
    def log_event(self, tbmt, qd_raw, version, action_type, reason):
        allowed_action_types = {"FILTERED_SKIP", "NO_ATTACHMENTS", "DUPLICATE_UNIT", "TEMP_ABORT"}
        if action_type not in allowed_action_types:
            return

        self._safe_execute("""
            INSERT INTO scan_logs (run_id, ma_tbmt, so_qd, version, action_type, reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (CURRENT_RUN_ID or 0, tbmt, qd_raw, version, action_type, reason, self._now_str()))
        self.conn.commit()

    def log_khlcnt_filtered_skip(self, plan_record, reason):
        khlcnt_name = _collapse_whitespace(plan_record.get("Tên KHLCNT", ""))
        reason_text = _collapse_whitespace(reason)
        if khlcnt_name:
            reason_text = f"{reason_text} | Tên KHLCNT: {khlcnt_name}" if reason_text else f"Tên KHLCNT: {khlcnt_name}"
        self._safe_execute("""
            INSERT INTO scan_logs (
                run_id, ma_tbmt, so_qd, version,
                ma_khlcnt, ma_khlcnt_full, khlcnt_version,
                action_type, reason, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'FILTERED_SKIP', %s, %s)
        """, (
            CURRENT_RUN_ID or 0,
            "",
            "N/A",
            plan_record.get("Phiên bản KHLCNT") or "N/A",
            plan_record.get("Mã KHLCNT") or "",
            plan_record.get("Mã KHLCNT đầy đủ") or "",
            plan_record.get("Phiên bản KHLCNT") or "",
            reason_text,
            self._now_str(),
        ))
        self.conn.commit()

    def mark_khlcnt_checked(self, plan_record, reason="KHLCNT checked"):
        self._safe_execute("""
            INSERT INTO scan_logs (
                run_id, ma_tbmt, so_qd, version,
                ma_khlcnt, ma_khlcnt_full, khlcnt_version,
                action_type, reason, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'KHLCNT_CHECKED', %s, %s)
        """, (
            CURRENT_RUN_ID or 0,
            "",
            "N/A",
            plan_record.get("Phiên bản KHLCNT") or "N/A",
            plan_record.get("Mã KHLCNT") or "",
            plan_record.get("Mã KHLCNT đầy đủ") or "",
            plan_record.get("Phiên bản KHLCNT") or "",
            reason,
            self._now_str(),
        ))
        self.conn.commit()

    def log_khlcnt_linked_pending(self, plan_record, linked_notice, child_row=None):
        linked_tbmt = str(linked_notice or "").strip()
        if not linked_tbmt:
            return False
        self._safe_execute("""
            INSERT INTO scan_logs (
                run_id, ma_tbmt, so_qd, version,
                ma_khlcnt, ma_khlcnt_full, khlcnt_version,
                action_type, reason, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'KHLCNT_LINKED_PENDING', %s, %s)
        """, (
            CURRENT_RUN_ID or 0,
            linked_tbmt,
            "N/A",
            plan_record.get("Phiên bản KHLCNT") or "N/A",
            plan_record.get("Mã KHLCNT") or "",
            plan_record.get("Mã KHLCNT đầy đủ") or "",
            plan_record.get("Phiên bản KHLCNT") or "",
            "TBMT_LINKED_PENDING",
            self._now_str(),
        ))
        self.conn.commit()
        return True

    def should_skip_khlcnt_linked_pending(self, plan_record, linked_notice, skip_days=KHLCNT_LINKED_PENDING_SKIP_DAYS):
        khlcnt = str((plan_record or {}).get("Mã KHLCNT") or "").strip()
        linked_tbmt = str(linked_notice or "").strip()
        if not khlcnt or not linked_tbmt:
            return False, ""

        self._safe_execute("""
            SELECT MAX(created_at) AS last_pending_at
            FROM scan_logs
            WHERE ma_khlcnt=%s
              AND ma_tbmt=%s
              AND action_type='KHLCNT_LINKED_PENDING'
        """, (khlcnt, linked_tbmt))
        row = self.cursor.fetchone() or {}
        last_date_value = row.get("last_pending_at")
        if not last_date_value:
            return False, ""

        try:
            if isinstance(last_date_value, datetime):
                last_date = last_date_value
            else:
                last_date = datetime.strptime(str(last_date_value)[:19], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_date).days < skip_days:
                return True, f"LINKED_PENDING_WITHIN_{skip_days}_DAYS"
        except Exception:
            return False, ""
        return False, ""

    def should_skip_khlcnt_plan(self, ma_khlcnt, skip_days=SKIP_DAYS):
        khlcnt = str(ma_khlcnt or "").strip()
        if not khlcnt:
            return False, ""

        self._safe_execute("""
            SELECT 1
            FROM scan_logs
            WHERE ma_khlcnt=%s AND action_type='FILTERED_SKIP'
            LIMIT 1
        """, (khlcnt,))
        if self.cursor.fetchone():
            return True, "FILTERED_SKIP"

        self._safe_execute("""
            SELECT MAX(event_at) AS last_date
            FROM (
                SELECT created_at AS event_at
                FROM scan_logs
                WHERE ma_khlcnt=%s
                  AND action_type='KHLCNT_CHECKED'
                UNION ALL
                SELECT updated_at AS event_at
                FROM package_metadata
                WHERE ma_khlcnt=%s
                  AND updated_at IS NOT NULL
            ) recent_events
        """, (khlcnt, khlcnt))
        row = self.cursor.fetchone() or {}
        last_date_value = row.get("last_date")
        if not last_date_value:
            return False, ""

        try:
            if isinstance(last_date_value, datetime):
                last_date = last_date_value
            else:
                last_date = datetime.strptime(str(last_date_value)[:19], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_date).days < skip_days:
                return True, f"CHECKED_WITHIN_{skip_days}_DAYS"
        except Exception:
            return False, ""
        return False, ""

    def should_skip_level_1(self, tbmt, skip_days=SKIP_DAYS):
        # 1. Bị chặn từ đầu do blacklist
        self._safe_execute("""
            SELECT 1 FROM scan_logs 
            WHERE ma_tbmt=%s AND action_type='FILTERED_SKIP' LIMIT 1
        """, (tbmt,))
        if self.cursor.fetchone():
            return True

        # 2. Nếu lần gần nhất của TBMT là TEMP_ABORT và chưa có lần tải thành công mới hơn,
        # thì cho phép crawl lại ngay, không áp dụng skip_days.
        self._safe_execute("""
            SELECT MAX(created_at) AS last_abort_at
            FROM scan_logs
            WHERE ma_tbmt=%s AND action_type='TEMP_ABORT'
        """, (tbmt,))
        last_abort_row = self.cursor.fetchone() or {}
        last_abort_at = last_abort_row.get("last_abort_at")

        # 3. Xem lần check/crawl cuối là khi nào.
        # last_checked_at là nguồn chuẩn cho việc check version. packages.crawled_at
        # là fallback cho dữ liệu đã crawl trước khi có last_checked_at hoặc các
        # unit chỉ có artifact, tránh check lại gói vừa crawl trong skip_days.
        self._safe_execute("""
            SELECT MAX(event_at) AS last_date
            FROM (
                SELECT last_checked_at AS event_at
                FROM package_metadata
                WHERE ma_tbmt=%s AND last_checked_at IS NOT NULL
                UNION ALL
                SELECT crawled_at AS event_at
                FROM packages
                WHERE ma_tbmt=%s AND crawled_at IS NOT NULL
            ) recent_events
        """, (tbmt, tbmt))
        row = self.cursor.fetchone()
        last_date_str = row['last_date'] if row else None
        if not last_date_str:
            return False
        
        try:
            # Sửa ép kiểu timestamp phù hợp datetime (Postgres trả về obj datetime)
            if isinstance(last_date_str, datetime):
                last_date = last_date_str
            else:
                last_date = datetime.strptime(str(last_date_str)[:19], "%Y-%m-%d %H:%M:%S")
            if last_abort_at:
                if isinstance(last_abort_at, datetime):
                    abort_date = last_abort_at
                else:
                    abort_date = datetime.strptime(str(last_abort_at)[:19], "%Y-%m-%d %H:%M:%S")
                if abort_date > last_date:
                    return False
            return (datetime.now() - last_date).days < skip_days
        except Exception:
            return False

    def get_latest_version(self, tbmt):
        self._safe_execute("""
            SELECT version FROM packages WHERE ma_tbmt=%s
        """, (tbmt,))
        rows = self.cursor.fetchall() or []
        if not rows:
            return "00"
        return max((row["version"] for row in rows), key=_version_key)

    def mark_unit_checked(self, tbmt, qd_raw, version, commit=True):
        tbmt_save = str(tbmt or "").strip() or "UNKNOWN_TBMT"
        qd_save = str(qd_raw or "").strip() or "UNKNOWN_QD"
        ver_save = version if version else "00"
        checked_at = self._now_str()
        self._safe_execute("""
            INSERT INTO package_metadata (ma_tbmt, so_qd, version, last_checked_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ma_tbmt, so_qd, version) DO UPDATE SET
                last_checked_at = EXCLUDED.last_checked_at
        """, (tbmt_save, qd_save, ver_save, checked_at))
        if commit:
            self.conn.commit()

    def should_download_unit(self, tbmt, qd_raw, version):
        ver_chk = version if version else "00"
        self._safe_execute("""
            SELECT version
            FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s
        """, (tbmt, qd_raw))
        rows = self.cursor.fetchall() or []
        if not rows:
            return True, "NEW_QD"

        latest_ver = max((row["version"] for row in rows), key=_version_key)
        if _version_key(ver_chk) > _version_key(latest_ver):
            return True, f"NEW_VERSION {latest_ver} -> {ver_chk}"
        if _version_key(ver_chk) == _version_key(latest_ver):
            self.mark_unit_checked(tbmt, qd_raw, ver_chk)
            return False, f"SAME_VERSION v{ver_chk}"
        self.mark_unit_checked(tbmt, qd_raw, ver_chk)
        return False, f"OLDER_VERSION v{ver_chk} < v{latest_ver}"

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def update(self, *args, **kwargs): pass  # Dummy


tracker = None
CURRENT_RUN_ID = 0
ABORTED_TBMTS_THIS_RUN = set()
TEMP_ABORT_SUMMARY = {}


class TempCrawlAbort(Exception):
    def __init__(self, tbmt, reason):
        tbmt_clean = str(tbmt or "UNKNOWN").strip() or "UNKNOWN"
        reason_clean = " ".join(str(reason or "").split()).strip()
        if not reason_clean:
            reason_clean = "Lỗi tạm thời trong quá trình crawl"
        self.tbmt = tbmt_clean
        self.reason = reason_clean[:500]
        super().__init__(f"{self.tbmt}: {self.reason}")


def register_temp_abort(tbmt, reason):
    tbmt_clean = str(tbmt or "UNKNOWN").strip() or "UNKNOWN"
    reason_clean = " ".join(str(reason or "").split()).strip()
    if not reason_clean:
        reason_clean = "Lỗi tạm thời trong quá trình crawl"

    is_new_tbmt = tbmt_clean not in ABORTED_TBMTS_THIS_RUN
    ABORTED_TBMTS_THIS_RUN.add(tbmt_clean)

    summary = TEMP_ABORT_SUMMARY.setdefault(tbmt_clean, {
        "count": 0,
        "first_reason": reason_clean[:500],
        "last_reason": reason_clean[:500],
    })
    summary["count"] += 1
    summary["last_reason"] = reason_clean[:500]

    if is_new_tbmt and tracker is not None:
        tracker.log_event(
            tbmt=tbmt_clean,
            qd_raw="N/A",
            version="N/A",
            action_type="TEMP_ABORT",
            reason=reason_clean[:500]
        )

    logger.warning(f"⚠️ [TEMP_ABORT] {tbmt_clean}: {reason_clean}")


def print_temp_abort_summary():
    if not TEMP_ABORT_SUMMARY:
        logger.info("✅ Không có TBMT nào TEMP_ABORT trong run này.")
        return

    logger.warning("=" * 60)
    logger.warning(f"⚠️ TỔNG KẾT TEMP_ABORT: {len(TEMP_ABORT_SUMMARY)} TBMT cần theo dõi ở run tiếp theo.")
    for idx, tbmt in enumerate(sorted(TEMP_ABORT_SUMMARY.keys()), start=1):
        info = TEMP_ABORT_SUMMARY[tbmt]
        reason = info.get("last_reason") or info.get("first_reason") or "Không có chi tiết"
        logger.warning(f"   {idx}. {tbmt} | {reason}")
    logger.warning("=" * 60)


def init_tracker():
    global tracker
    if tracker is None:
        tracker = CrawlerDB()


def close_driver_runtime():
    global driver, wait, NETWORK_CAPTURE_ENABLED
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        wait = None
    NETWORK_CAPTURE_ENABLED = False


def init_runtime(enable_network_capture=False):
    global driver, wait, NETWORK_CAPTURE_ENABLED
    init_tracker()
    if driver is not None and NETWORK_CAPTURE_ENABLED != bool(enable_network_capture):
        logger.info(
            "🔄 Restart Chrome để chuyển Network capture: %s -> %s",
            NETWORK_CAPTURE_ENABLED,
            bool(enable_network_capture),
        )
        close_driver_runtime()

    if driver is None:
        chrome_options = build_chrome_options(enable_performance_logging=enable_network_capture)
        try:
            driver = webdriver.Chrome(options=chrome_options)
        except Exception as first_error:
            if USE_LOCAL_CHROMEDRIVER and CHROMEDRIVER_PATH:
                try:
                    logger.warning(
                        f"⚠️ Selenium Manager không khởi tạo được Chrome ({first_error}). "
                        "Thử fallback sang CHROMEDRIVER_PATH..."
                    )
                    service = Service(executable_path=CHROMEDRIVER_PATH, log_output=os.devnull)
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                except SessionNotCreatedException as e:
                    logger.error(
                        f"❌ ChromeDriver tại CHROMEDRIVER_PATH không khớp version Chrome: {e.msg}"
                    )
                    raise
            else:
                raise
        wait = WebDriverWait(driver, 20)
        NETWORK_CAPTURE_ENABLED = bool(enable_network_capture)
        logger.info("🚀 Chrome đã khởi tạo | Network capture: %s", "BẬT" if NETWORK_CAPTURE_ENABLED else "TẮT")
        if NETWORK_CAPTURE_ENABLED:
            try:
                driver.execute_cdp_cmd("Network.enable", {})
            except Exception:
                logger.warning("⚠️ Không bật được Chrome DevTools Network; KHLCNT_NO_LINKED_TBMT có thể không lấy được resultDTO.")


def shutdown_runtime():
    global tracker
    close_driver_runtime()
    if tracker is not None:
        tracker.close()
        tracker = None


# ================== LƯU THÔNG TIN LẦN CHẠY ==================
def start_run_history(start_time):
    try:
        tracker._safe_execute("""
            INSERT INTO run_sessions (start_time, end_time, duration_seconds, boxes_selected)
            VALUES (%s, NULL, NULL, 0)
            RETURNING id
        """, (start_time.strftime("%Y-%m-%d %H:%M:%S"),))
        row = tracker.cursor.fetchone() or {}
        tracker.conn.commit()
        run_id = row.get("id", 0) or 0
        logger.info(f"📝 Đã khởi tạo run_session #{run_id}")
        return run_id
    except Exception as e:
        logger.error(f"❌ Lỗi khởi tạo run session: {e}")
        return 0


def append_run_history(start_time, end_time, boxes_selected_count):
    duration = int((end_time - start_time).total_seconds())
    try:
        if CURRENT_RUN_ID:
            tracker._safe_execute("""
                UPDATE run_sessions
                SET end_time=%s, duration_seconds=%s, boxes_selected=%s
                WHERE id=%s
            """, (
                end_time.strftime("%Y-%m-%d %H:%M:%S"),
                duration,
                int(boxes_selected_count),
                CURRENT_RUN_ID
            ))
        else:
            tracker._safe_execute("""
                INSERT INTO run_sessions (start_time, end_time, duration_seconds, boxes_selected)
                VALUES (%s, %s, %s, %s)
            """, (
                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S"),
                duration,
                int(boxes_selected_count)
            ))
        tracker.conn.commit()
        logger.info(f"✅ Đã lưu session log vào DB (Duration: {duration}s)")
    except Exception as e:
        logger.error(f"❌ Lỗi ghi run session vào DB: {e}")


# ================== TỪ KHÓA LỌC ==================
loai_tu_gian_giao_thau = [
    "kích thích", "môi trường", "nông nghiệp", "khuyến nông", "nông dân", "vườn", "thức ăn", "bvtv", "bảo vệ thực vật",
    "lúa", "cao su", "giống", "phân bón", "diệt cỏ", "thuốc cỏ", "trừ cỏ", "thuốc sâu", "tưới nước", "cắt cỏ",
    "trừ sâu", "trừ bệnh", "rầy côn trùng", "phấn trắng", "đạo ôn", "chăn nuôi", "thủy sản", "thú y",
    "vật nuôi", "gia súc", "gia cầm", "chó", "mèo", "ruồi", "gà", "trâu", "bò", "vịt", "chuột", "cá", "tôm", "tả heo",
    "muỗi", "mối", "lở mồm", "cúm gia cầm",
    "vị thuốc", "thuốc y học cổ truyền", "chế phẩm y học cổ truyền", "thuốc cổ truyền", "đông y", "sinh học", "shpt", 
    "thuốc dược liệu", "thuốc thành phẩm y học cổ truyền", "tủ", "kho thuốc", "thuốc nổ",
    "sản xuất", "cứu hỏa", "lao động", "công nghiệp", "bão", "lụt", "hàng hóa dịch vụ", "phần mềm", "thuốc lá",
    "quặng", "nhuộm", "văn phòng", "bảo quản", "bao đựng", "rác", "túi đựng", "mực in", "giấy in", "linh kiện",
    "nghiên cứu", "kiểm nghiệm", "mỹ thuật", "nhu yếu phẩm", "tài sản", "lương thực", "in ấn", "sửa chữa",
    "thí nghiệm", "nhu yếu phẩm", "vận chuyển","công nghệ thông tin", "hệ thống mạng", "tin học", "máy tính",
    "mạng lan", "chống sét", "xử lý nước thải", "sắc ký", "quang phổ", "sửa chữa", "máy phun thuốc", "thuốc hàn",
    "truyền thông", "xe", "máy soi thuốc", "cây thuốc", "đông dược", "dịch chiết", "tinh dầu",
    "máy chiết xơ", "nội độc tố", "dung môi", "chất chuẩn", "chuẩn hóa", "kiểm tra", "độ hòa tan", "bình phun thuốc",
    "tư vấn"
]
 
loai_chu_dau_tu = [
    ("nông", ["bệnh viện", "trung tâm y tế", "phòng khám", "trạm y tế", "sở y tế"]),
    ("nuôi", ["nuôi dưỡng"]),
    ("trồng", []),
    ("lâm nghiệp", []),
    ("kiểm lâm", []),
    ("cao su", []),
    ("xây dựng", []),
    ("phòng kinh tế", []),
    ("thuốc lá", []),
    ("viện nghiên cứu", []),
    ("chế biến", []),
    ("nông lâm", []),
    ("nước sạch", []),
    ("vệ sinh", []),
    ("công ty", []),
    ("chăn nuôi", []),
    ("thú y", []),
    ("kiểm nghiệm", []),
]

tu_khoa_luu_lai = [
    "generic", "biệt dược gốc", "bdg", "khám chữa bệnh", 
    "thiết bị y tế", "vật tư y tế", "thực phẩm chức năng", "thực phẩm bảo vệ sức khỏe", "thực phẩm dinh dưỡng"
]

def _normalize_keyword_value(value):
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _normalize_keyword_list(values):
    seen = []
    for value in values:
        normalized = _normalize_keyword_value(value)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def _normalize_investor_rules(rules):
    normalized_rules = []
    for keyword, exclude_list in rules:
        normalized_keyword = _normalize_keyword_value(keyword)
        normalized_excludes = _normalize_keyword_list(exclude_list)
        if normalized_keyword:
            normalized_rules.append((normalized_keyword, normalized_excludes))
    return normalized_rules


loai_tu_gian_giao_thau = _normalize_keyword_list(loai_tu_gian_giao_thau)
tu_khoa_luu_lai = _normalize_keyword_list(tu_khoa_luu_lai)
loai_chu_dau_tu = _normalize_investor_rules(loai_chu_dau_tu)

# ================== HELPER WAIT ELEMENT ==================
def wait_presence(context, by, locator, timeout=10):
    return WebDriverWait(context, timeout).until(
        EC.presence_of_element_located((by, locator))
    )

def wait_clickable(context, by, locator, timeout=10):
    return WebDriverWait(context, timeout).until(
        EC.element_to_be_clickable((by, locator))
    )

# ================== HÀM LẤY MÃ TBMT VÀ ĐỊA ĐIỂM ==================
def get_ma_tbmt(box):
    try:
        code_elem = wait_presence(
            box,
            By.CSS_SELECTOR,
            "p.content__body__left__item__infor__code",
            timeout=10
        )
        code_text = code_elem.text.strip()
        value = code_text.split(":")[-1].strip().split("-")[0]
        return value
    except Exception as e:
        logger.error(f"❌ Lỗi lấy Mã TBMT: {e}")
        return ""

def get_dia_diem(box):
    """
    Lấy text 'Địa điểm' từ box ở màn hình KQ tìm kiếm.
    Trả về chuỗi địa điểm hoặc "" nếu không tìm thấy.
    """
    try:
        dia_diem_elem = box.find_element(
            By.XPATH,
            ".//h6[contains(@class,'format__text__title') and contains(normalize-space(),'Địa điểm')]/span"
        )
        return dia_diem_elem.text.strip()
    except Exception:
        return ""


def get_chu_dau_tu(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//h6[contains(normalize-space(),'Chủ đầu tư')]/span"
        ).text.strip()
    except Exception:
        return ""


def get_ten_goi_thau(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//a/h5[contains(@class,'content__body__left__item__infor__contract__name')]"
        ).text.strip()
    except Exception:
        return ""


def get_linh_vuc(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//h6[contains(normalize-space(),'Lĩnh vực')]/span"
        ).text.strip()
    except Exception:
        return ""


def build_box_metadata_snapshot(box, ma_tbmt, dia_diem, box_name_text, ngay_phe_duyet):
    snapshot = {
        "Mã TBMT": ma_tbmt,
        "Chủ đầu tư": get_chu_dau_tu(box),
        "Tên gói thầu": box_name_text or get_ten_goi_thau(box),
        "Lĩnh vực": get_linh_vuc(box),
        "Địa điểm": dia_diem,
        "Ngày phê duyệt": ngay_phe_duyet.strftime("%d/%m/%Y") if ngay_phe_duyet else None,
    }
    return {k: v for k, v in snapshot.items() if v not in (None, "")}

# ================== LỌC BOX ==================
def is_luu_lai_theo_ten_goi_thau(ten_goi_thau):
    ten_thap = _normalize_keyword_value(ten_goi_thau)
    return any(re.search(rf'\b{re.escape(kw)}\b', ten_thap) for kw in tu_khoa_luu_lai)

def is_loai_chu_dau_tu(ten_chu_dau_tu):
    ten_thap = _normalize_keyword_value(ten_chu_dau_tu)
    for keyword, exclude_list in loai_chu_dau_tu:
        if re.search(rf'\b{re.escape(keyword)}\b', ten_thap):
            if any(re.search(rf'\b{re.escape(ex)}\b', ten_thap) for ex in exclude_list):
                continue
            else:
                return True
    return False

def is_loai_ten_goi_thau(ten_goi_thau):
    ten_thap = _normalize_keyword_value(ten_goi_thau)
    if any(re.search(rf'\b{re.escape(word)}\b', ten_thap) for word in loai_tu_gian_giao_thau):
        return True
    return False

def is_box_selected_or_filtered(box, index):
    """
    Kiểm tra box xem có nên xử lý không:
    1. Check Tracking DB (Skip nếu đã filter hoặc mới crawl xong).
    2. Check Keyword (Tên gói/Chủ đầu tư).
    """
    try:
        ma_tbmt = get_ma_tbmt(box)
    except:
        ma_tbmt = "UNKNOWN"

    # --- 1. CHECK SKIP TỪ DB (Nhanh nhất) ---
    if ma_tbmt != "UNKNOWN":
        if tracker.should_skip_level_1(ma_tbmt, skip_days=SKIP_DAYS):
            logger.info(f"⏩ [SKIP] {ma_tbmt} - Đã xử lý gần đây hoặc nằm trong Blacklist.")
            return False 

    # --- 2. LẤY THÔNG TIN TỪ BOX ĐỂ LỌC KEYWORD ---
    try:
        ten_goi_thau = get_ten_goi_thau(box)
    except: 
        ten_goi_thau = ""
    
    try:
        ten_chu_dau_tu = get_chu_dau_tu(box)
    except: 
        ten_chu_dau_tu = ""

    t_low = ten_goi_thau.lower()
    c_low = ten_chu_dau_tu.lower()

    # --- 3. LOGIC LỌC KEYWORD ---
    
    # Ưu tiên 1: Whitelist mạnh. Nếu đã thỏa thì giữ lại luôn, không check tiếp.
    if is_luu_lai_theo_ten_goi_thau(t_low):
        return True

    # Ưu tiên 2: Blacklist gắt
    if is_loai_chu_dau_tu(c_low) or is_loai_ten_goi_thau(t_low):
        # Ghi log FILTERED_SKIP vào DB => Để lần sau should_skip_level_1 chặn ngay từ đầu
        tracker.log_event(
            tbmt=ma_tbmt, 
            qd_raw="N/A",
            version="N/A", 
            action_type="FILTERED_SKIP", 
            reason=ten_goi_thau
        )
        logger.info(f"🚩 Bỏ qua {ma_tbmt} (Loại theo từ khóa)")
        logger.info("=" * 30)
        return False

    # Mặc định giữ lại
    return True
    

# ================== LẤY THÔNG TIN BỔ SUNG ==================
def normalize_info_key(value):
    text = _collapse_whitespace(value).casefold()
    text = re.sub(r"[():]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_additional_info():
    info = {}
    field_map = {
        "mã tbmt": "Mã TBMT",
        "ngày đăng tải": "Ngày đăng tải",
        "trạng thái đăng tải kq": "Trạng thái đăng tải KQ",
        "trạng thái kqlcnt": "Trạng thái KQLCNT",
        "chủ đầu tư": "Chủ đầu tư",
        "tên chủ đầu tư": "Chủ đầu tư",
        "tên gói thầu": "Tên gói thầu",
        "tóm tắt công việc chính của gói thầu": "Tóm tắt công việc chính của gói thầu",
        "hình thức lcnt": "Hình thức LCNT",
        "hình thức lựa chọn nhà thầu": "Hình thức lựa chọn nhà thầu",
        "lĩnh vực": "Lĩnh vực",
        "phương thức lựa chọn nhà thầu": "Phương thức lựa chọn nhà thầu",
        "đấu thầu qua mạng": "Đấu thầu qua mạng",
        "giá gói thầu": "Giá gói thầu",
        "giá dự toán": "Giá dự toán",
        "trong nước/ quốc tế": "Trong nước/ Quốc tế",
        "ngày phê duyệt": "Ngày phê duyệt",
        "trạng thái phê duyệt": "Trạng thái phê duyệt",
        "cơ quan phê duyệt": "Cơ quan phê duyệt",
        "số quyết định phê duyệt": "Số quyết định phê duyệt",
        "loại hợp đồng": "Loại hợp đồng",
        "thời gian thực hiện gói thầu": "Thời gian thực hiện gói thầu",
        "kết quả đấu thầu": "Kết quả đấu thầu",
        "kết quả lựa chọn nhà thầu": "Kết quả đấu thầu",
        "địa điểm": "Địa điểm",
        "địa điểm thực hiện": "Địa điểm",
        "phân loại gói thầu": "Phân loại gói thầu",
    }
    
    try:
        info_divs = driver.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for div in info_divs:
            try:
                title_elem = div.find_element(By.CSS_SELECTOR, "div.infomation__content__title")
            except Exception:
                continue

            title_key = normalize_info_key(title_elem.text)
            mapped_title = field_map.get(title_key)
            if not mapped_title:
                continue

            value = driver.execute_script(
                """
                const row = arguments[0];
                const title = arguments[1];
                for (const child of Array.from(row.children)) {
                    if (child !== title && child.tagName && child.tagName.toLowerCase() === 'div') {
                        return child.textContent || '';
                    }
                }
                return '';
                """,
                div,
                title_elem,
            )
            value = _collapse_whitespace(value)
            if value:
                info[mapped_title] = value
                 
    except Exception as e:
        logger.error(f"❌ Lỗi lấy thông tin bổ sung: {e}")
    return info


def normalize_info_label(value):
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def get_info_card_value(*titles):
    wanted_keys = {normalize_info_key(title) for title in titles if title}
    if not wanted_keys:
        return ""
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title_elem = row.find_element(By.CSS_SELECTOR, "div.infomation__content__title")
            except Exception:
                continue
            if normalize_info_key(title_elem.text) not in wanted_keys:
                continue
            value = driver.execute_script(
                """
                const row = arguments[0];
                const title = arguments[1];
                for (const child of Array.from(row.children)) {
                    if (child !== title && child.tagName && child.tagName.toLowerCase() === 'div') {
                        return child.textContent || '';
                    }
                }
                return '';
                """,
                row,
                title_elem,
            )
            return _collapse_whitespace(value)
    except Exception:
        return ""
    return ""


def get_khlcnt_detail_signature():
    values = [
        get_info_card_value("Mã TBMT"),
        get_info_card_value("Số quyết định phê duyệt"),
        get_info_card_value("Tên gói thầu"),
        get_info_card_value("Phiên bản thay đổi", "Phiên bản KQ"),
    ]
    return _sig("|".join(values))


def extract_tbmt_khlcnt_metadata():
    try:
        card = _find_card_by_header("Thông tin chung của KHLCNT")
        if not card:
            return {}
        metadata = {}
        rows = card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title_elem = row.find_element(By.CSS_SELECTOR, "div.infomation__content__title")
            except Exception:
                continue
            title_key = normalize_info_key(title_elem.text)
            value = driver.execute_script(
                """
                const row = arguments[0];
                const title = arguments[1];
                for (const child of Array.from(row.children)) {
                    if (child !== title && child.tagName && child.tagName.toLowerCase() === 'div') {
                        return child.textContent || '';
                    }
                }
                return '';
                """,
                row,
                title_elem,
            )
            value = _collapse_whitespace(value)
            if not value:
                continue
            if title_key == "mã khlcnt":
                metadata["Mã KHLCNT"] = value
                metadata["Mã KHLCNT đầy đủ"] = value
                metadata["Phiên bản KHLCNT"] = "00"
            elif title_key == "tên dự toán mua sắm":
                metadata["Tên KHLCNT"] = value
        return metadata
    except Exception:
        return {}


def merge_khlcnt_metadata(info_snapshot, khlcnt_metadata=None):
    info = dict(info_snapshot or {})
    for key, value in (khlcnt_metadata or {}).items():
        if value not in (None, "") and not info.get(key):
            info[key] = value
    return info


def find_target_item_card(timeout=10):
    header_xpath = (
        "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and ("
        "contains(normalize-space(),'Danh sách thuốc') or "
        "contains(normalize-space(),'Danh mục thuốc') or "
        "contains(normalize-space(),'Danh sách hàng hóa') or "
        "contains(normalize-space(),'Danh mục hàng hóa')"
        ")]]"
    )
    card = wait_presence(driver, By.XPATH, header_xpath, timeout=timeout)
    header = wait_presence(card, By.XPATH, ".//div[contains(@class,'card-header')]", timeout=timeout)
    return card, normalize_info_label(header.text)


def get_target_card_kind(card_name):
    name = normalize_info_label(card_name).casefold()
    if "thuốc" in name:
        return "medicine"
    if "hàng hóa" in name:
        return "goods"
    return "unknown"


def get_target_card_export_button(card):
    try:
        return card.find_element(By.XPATH, ".//button[contains(normalize-space(),'Xuất Excel')]")
    except NoSuchElementException:
        return None


def extract_target_card_page(card):
    return driver.execute_script(
        """
        const card = arguments[0];
        const table = card.querySelector('table');
        if (!table) {
            return {headers: [], rows: []};
        }
        const headers = Array.from(table.querySelectorAll('thead th')).map((th, index) => {
            const text = (th.textContent || '').replace(/\\u00a0/g, ' ').trim();
            return text || `COL_${index + 1}`;
        });
        const rows = [];
        const trs = Array.from(table.querySelectorAll('tbody tr'));
        for (const tr of trs) {
            const cells = Array.from(tr.querySelectorAll('td'));
            if (!cells.length) continue;
            rows.push(cells.map(td => (td.textContent || '').replace(/\\u00a0/g, ' ').trim()));
        }
        return {headers, rows};
        """,
        card,
    )


def get_target_card_active_page(card):
    try:
        active = card.find_element(By.XPATH, ".//li[contains(@class,'ant-pagination-item-active')]")
        return normalize_info_label(active.text)
    except NoSuchElementException:
        return ""


def build_table_page_signature(page_data):
    headers = tuple(normalize_info_label(item) for item in page_data.get("headers", []))
    rows = tuple(
        tuple(normalize_info_label(value) for value in row)
        for row in page_data.get("rows", [])
    )
    return headers, rows


def click_target_card_next_page(card):
    next_button = card.find_elements(
        By.XPATH,
        ".//li[contains(@class,'ant-pagination-next') and not(contains(@class,'ant-pagination-disabled'))]",
    )
    if not next_button:
        return False

    before_data = extract_target_card_page(card)
    before_signature = build_table_page_signature(before_data)
    before_page = get_target_card_active_page(card)

    button = next_button[0]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    if not khlcnt_quick_click(button):
        return False
    wait_document_ready_quick(timeout=4)

    def page_changed(_driver):
        try:
            refreshed_card, _ = find_target_item_card(timeout=3)
            after_page = get_target_card_active_page(refreshed_card)
            after_data = extract_target_card_page(refreshed_card)
            after_signature = build_table_page_signature(after_data)
            if after_page and before_page and after_page != before_page:
                return True
            return after_signature != before_signature
        except Exception:
            return False

    try:
        WebDriverWait(driver, 12).until(page_changed)
    except TimeoutException:
        return False
    return True


def collect_target_card_table_rows(card):
    headers = []
    row_records = []
    seen_signatures = set()

    while True:
        page_data = extract_target_card_page(card)
        current_headers = [
            normalize_info_label(item) or f"COL_{idx + 1}"
            for idx, item in enumerate(page_data.get("headers", []))
        ]
        if current_headers:
            headers = current_headers

        for row_values in page_data.get("rows", []):
            normalized_values = [normalize_info_label(value) for value in row_values]
            if not any(normalized_values):
                continue
            signature = tuple(normalized_values)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            row_records.append({
                headers[idx] if idx < len(headers) else f"COL_{idx + 1}": value
                for idx, value in enumerate(normalized_values)
            })

        if not click_target_card_next_page(card):
            break
        card, _card_name = find_target_item_card(timeout=10)

    return headers, row_records


def save_target_card_table_as_excel(ma_tbmt, suffix_qd, version_code, card=None, card_name=""):
    try:
        if card is None:
            card, card_name = find_target_item_card(timeout=6)
        else:
            card_name = card_name or ""
        headers, row_records = collect_target_card_table_rows(card)
        if not headers or not row_records:
            return None, 0, card_name

        filename = "web_table.xlsx"
        temp_path = os.path.join(DOWNLOAD_RAW, filename)
        pd.DataFrame(row_records).to_excel(temp_path, index=False)
        return temp_path, len(headers), card_name
    except Exception as error:
        logger.warning("⚠️ Không đọc được bảng trực tiếp từ card dữ liệu: %s", str(error)[:300])
        return None, 0, ""


def _find_card_by_header(header_text: str):
    cards = driver.find_elements(
        By.XPATH,
        f"//div[contains(@class,'card')][.//div[contains(@class,'card-header') and contains(normalize-space(),'{header_text}')]]"
    )
    return cards[0] if cards else None


def _card_has_multiple_pages(card) -> bool:
    try:
        page_items = card.find_elements(
            By.XPATH,
            ".//ul[contains(@class,'ant-pagination')]//li[contains(@class,'ant-pagination-item')]"
        )
        numeric_pages = {
            _collapse_whitespace(item.text)
            for item in page_items
            if _collapse_whitespace(item.text).isdigit()
        }
        return len(numeric_pages) > 1
    except Exception:
        return False


def _find_table_column_index(table, candidate_labels):
    header_cells = table.find_elements(By.XPATH, ".//thead//tr[1]/th")
    header_labels = []
    for idx, header_cell in enumerate(header_cells, start=1):
        header_text = _collapse_whitespace(header_cell.text)
        if header_text:
            header_labels.append(header_text)
        header_clean = header_text.casefold()
        if any(candidate in header_clean for candidate in candidate_labels):
            return idx, header_labels
    return None, header_labels


def _result_text_is_awarded(result_text: str) -> bool:
    text = _collapse_whitespace(result_text).casefold()
    if not text:
        return False
    if text.startswith("trúng thầu"):
        return True
    if "không trúng thầu" in text:
        return False
    return text == "trúng thầu"


def extract_web_winner_fact():
    fact = {
        "capture_status": "UNKNOWN",
        "winner_count": 0,
        "only_winner_name": None,
        "winner_names": [],
        "capture_note": None,
    }

    try:
        winner_info_card = _find_card_by_header("Thông tin Nhà thầu trúng thầu")
        if winner_info_card:
            if _card_has_multiple_pages(winner_info_card):
                fact["capture_status"] = "PAGINATED_WINNER_CARD"
                fact["capture_note"] = "source=THONG_TIN_NHA_THAU_TRUNG_THAU"
                return fact

            table = winner_info_card.find_element(By.XPATH, ".//table")
            winner_col_index, header_labels = _find_table_column_index(
                table,
                ["tên nhà thầu", "nhà thầu"],
            )
            if winner_col_index is None:
                fact["capture_status"] = "NAME_COLUMN_NOT_FOUND"
                if header_labels:
                    fact["capture_note"] = (
                        "source=THONG_TIN_NHA_THAU_TRUNG_THAU | "
                        f"Header hiện có: {', '.join(header_labels[:8])}"
                    )
                return fact

            seen_names = set()
            winner_names = []
            rows = table.find_elements(By.XPATH, ".//tbody/tr[td]")
            for row in rows:
                cells = row.find_elements(By.XPATH, "./td")
                if len(cells) < winner_col_index:
                    continue
                winner_name = _collapse_whitespace(cells[winner_col_index - 1].text)
                if not winner_name:
                    continue
                dedupe_key = winner_name.casefold()
                if dedupe_key in seen_names:
                    continue
                seen_names.add(dedupe_key)
                winner_names.append(winner_name)

            fact["winner_names"] = winner_names
            fact["winner_count"] = len(winner_names)
            fact["capture_note"] = "source=THONG_TIN_NHA_THAU_TRUNG_THAU"

            if not winner_names:
                fact["capture_status"] = "NO_WINNER_ROWS"
                return fact

            if len(winner_names) == 1:
                fact["capture_status"] = "SINGLE_WINNER"
                fact["only_winner_name"] = winner_names[0]
                return fact

            fact["capture_status"] = "MULTI_WINNER"
            return fact

        bidder_list_card = _find_card_by_header("Danh sách nhà thầu")
        if not bidder_list_card:
            return None

        if _card_has_multiple_pages(bidder_list_card):
            fact["capture_status"] = "PAGINATED_BIDDER_LIST"
            fact["capture_note"] = "source=DANH_SACH_NHA_THAU"
            return fact

        table = bidder_list_card.find_element(By.XPATH, ".//table")
        winner_col_index, header_labels = _find_table_column_index(
            table,
            ["tên nhà thầu", "nhà thầu"],
        )
        result_col_index, _ = _find_table_column_index(
            table,
            ["kết quả"],
        )

        if winner_col_index is None:
            fact["capture_status"] = "NAME_COLUMN_NOT_FOUND"
            if header_labels:
                fact["capture_note"] = (
                    "source=DANH_SACH_NHA_THAU | "
                    f"Header hiện có: {', '.join(header_labels[:8])}"
                )
            return fact

        if result_col_index is None:
            fact["capture_status"] = "RESULT_COLUMN_NOT_FOUND"
            fact["capture_note"] = "source=DANH_SACH_NHA_THAU"
            return fact

        seen_names = set()
        winner_names = []
        rows = table.find_elements(By.XPATH, ".//tbody/tr[td]")
        for row in rows:
            cells = row.find_elements(By.XPATH, "./td")
            if len(cells) < max(winner_col_index, result_col_index):
                continue
            result_text = _collapse_whitespace(cells[result_col_index - 1].text)
            if not _result_text_is_awarded(result_text):
                continue
            winner_name = _collapse_whitespace(cells[winner_col_index - 1].text)
            if not winner_name:
                continue
            dedupe_key = winner_name.casefold()
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            winner_names.append(winner_name)

        fact["winner_names"] = winner_names
        fact["winner_count"] = len(winner_names)
        fact["capture_note"] = "source=DANH_SACH_NHA_THAU"

        if not winner_names:
            fact["capture_status"] = "NO_AWARDED_ROWS"
            return fact

        if len(winner_names) == 1:
            fact["capture_status"] = "SINGLE_WINNER"
            fact["only_winner_name"] = winner_names[0]
            return fact

        fact["capture_status"] = "MULTI_WINNER"
        return fact

    except NoSuchElementException:
        fact["capture_status"] = "TABLE_NOT_FOUND"
        return fact
    except Exception as e:
        fact["capture_status"] = "PARSE_ERROR"
        fact["capture_note"] = _collapse_whitespace(str(e))[:500]
        return fact


# ================== HỖ TRỢ KHÁC ==================
def get_ngay_phe_duyet_kqlcnt(box):
    try:
        ngay_element = WebDriverWait(box, 7).until(
            EC.presence_of_element_located((
                By.XPATH,
                ".//div[contains(@class,'content__body__right__item__infor__contract__right')]"
                "//p[contains(text(),'Ngày phê duyệt KQLCNT')]/following-sibling::h5"
            ))
        )
        ngay_text = ngay_element.text.strip()
        ngay_dt = datetime.strptime(ngay_text, "%d/%m/%Y")
        return ngay_dt
    except Exception as e:
        logger.error(f"❌ Không tìm thấy phần tử ngày phê duyệt KQLCNT hoặc lỗi: {e}")
        return None

def has_legacy_lot_selection_card():
    try:
        rows = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and contains(normalize-space(),'Thông tin phần/lô')]]"
            "//tbody/tr"
        )
        return len(rows) > 0
    except Exception:
        return False


def ensure_select_lot_with_winner():
    """
    Với giao diện cũ có card 'Thông tin phần/lô', mặc định web có thể đang chọn
    một phần/lô 'Không có nhà thầu trúng thầu', làm card dữ liệu bên dưới rỗng.
    Hàm này tự chọn một phần/lô đầu tiên có 'Có nhà thầu trúng thầu' để hiện data.
    Nếu giao diện mới hoặc không có card này thì no-op.
    """
    if not has_legacy_lot_selection_card():
        return False

    data_ready = wait_export_excel_button_quick(driver, timeout=0.25)
    if data_ready:
        return True

    try:
        lot_rows = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and contains(normalize-space(),'Thông tin phần/lô')]]"
            "//tbody/tr"
        )
    except Exception:
        return False

    if not lot_rows:
        return False

    for row in lot_rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 6:
                continue

            winner_text = " ".join((cells[4].text or "").split()).lower()
            if "có nhà thầu trúng thầu" not in winner_text:
                continue

            radio = cells[5].find_element(By.XPATH, ".//input[@type='radio' and not(@disabled)]")
            if radio.is_selected():
                return True

            logger.info("🔄 Chọn phần/lô có nhà thầu trúng thầu để hiển thị dữ liệu.")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", radio)
            wait_until_not_loading(driver, 10)
            if not safe_click(radio, wait):
                continue

            wait_dom_settled(timeout=10)
            if wait_export_excel_button_quick(driver, timeout=4):
                return True

            try:
                WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        "//div[contains(@class,'card-header') and ("
                        "contains(normalize-space(),'Danh sách hàng hóa') or "
                        "contains(normalize-space(),'Danh mục hàng hóa') or "
                        "contains(normalize-space(),'Danh sách thuốc') or "
                        "contains(normalize-space(),'Danh mục thuốc'))]"
                        "/following-sibling::div//table//tbody/tr"
                    ))
                )
                return True
            except Exception:
                continue
        except Exception:
            continue

    return False

# ========== RAW DOWNLOAD ==========
def get_latest_file_raw():
    files = [
        os.path.join(DOWNLOAD_RAW, f)
        for f in os.listdir(DOWNLOAD_RAW)
        if os.path.isfile(os.path.join(DOWNLOAD_RAW, f))
        and not f.endswith(".crdownload")
    ]
    if not files:
        return None
    return max(files, key=os.path.getctime)

def clear_raw_downloads():
    """Xóa toàn bộ file (không phải .crdownload) trong RAW trước khi xử lý box mới."""
    for name in os.listdir(DOWNLOAD_RAW):
        full = os.path.join(DOWNLOAD_RAW, name)
        if not os.path.isfile(full):
            continue
        if name.endswith(".crdownload"):
            continue
        try:
            os.remove(full)
        except Exception as e:
            logger.error(f"❌ Lỗi xóa file cũ trong RAW: {full} - {e}")

def wait_for_new_file(oldfile, timeout=30, exts=None, stable_rounds=3, interval=0.3):
    """
    Chờ xuất hiện file mới trong DOWNLOAD_RAW (không tính .crdownload).
    - oldfile: đường dẫn file mới nhất trước khi click (hoặc None)
    - exts: None hoặc list/tuple các extension, ví dụ [".pdf"], [".xlsx", ".xls"], [".pdf", ".doc", ".docx"]
    - stable_rounds: số lần liên tiếp size không đổi để coi là tải xong
    """
    start = time.time()
    oldnorm = os.path.normcase(oldfile) if oldfile else None

    candidate = None
    last_size = None
    stable = 0

    # normalize exts
    exts_norm = None
    if exts:
        exts_norm = tuple(e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts)

    while time.time() - start < timeout:
        files = []
        for f in os.listdir(DOWNLOAD_RAW):
            full = os.path.join(DOWNLOAD_RAW, f)
            if not os.path.isfile(full):
                continue
            fl = f.lower()
            if fl.endswith(".crdownload"):
                continue
            if exts_norm and not fl.endswith(exts_norm):
                continue
            files.append(full)

        if not files:
            time.sleep(interval)
            continue

        latest = max(files, key=os.path.getctime)
        latestnorm = os.path.normcase(latest)

        # phải là file "mới" so với oldfile
        if oldnorm is not None and latestnorm == oldnorm:
            time.sleep(interval)
            continue

        # check stable size
        try:
            sz = os.path.getsize(latest)
        except Exception:
            time.sleep(interval)
            continue

        if candidate != latest:
            candidate = latest
            last_size = sz
            stable = 0
        else:
            if sz == last_size:
                stable += 1
            else:
                stable = 0
                last_size = sz

        if stable >= stable_rounds:
            return latest

        time.sleep(interval)

    return None

def get_actual_file_from_path(path):
    if os.path.isfile(path):
        return path
    if os.path.isdir(path):
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            if os.path.isfile(full_path):
                return full_path
    return None

# ========== SANITIZE FILENAME ==========
def sanitize_filename_part(text):
    """Loại bỏ các ký tự không hợp lệ trong tên file Windows"""
    if not text:
        return text
    invalid_chars = r'\/:*?"<>|'
    for ch in invalid_chars:
        text = text.replace(ch, "_")
    return text

def rename_with_tbmt(dest_path, ma_tbmt, suffix_qd=None, force_ext=None, version_code=None):
    folder = os.path.dirname(dest_path)
    base = os.path.basename(dest_path)
    namenoext, ext = os.path.splitext(base)  # namenoext = tên gốc không gồm đuôi

    if force_ext:
        ext = force_ext

    parts = [ma_tbmt]

    if version_code:
        safe_ver = sanitize_filename_part(version_code)
        if safe_ver:
            parts.append(f"{{VER.{safe_ver}}}")

    if suffix_qd:
        safe_suffix = sanitize_filename_part(suffix_qd)
        if safe_suffix:
            parts.append(f"{{QD.{safe_suffix}}}")

    # Giữ đầy đủ tên gốc ở cuối
    safe_orig = sanitize_filename_part(namenoext)
    if safe_orig:
        parts.append(safe_orig)

    new_name = "_".join(parts) + ext
    new_path = os.path.join(folder, new_name)

    dups = False
    if os.path.exists(new_path):
        logger.warning(f"⚠️ File {new_name} đã tồn tại trong {folder}")
        try:
            os.remove(dest_path)
        except Exception as erm:
            logger.error(f"❌ Lỗi khi xóa file trùng {dest_path}: {erm}")
        dups = True
        return new_path, dups

    os.rename(dest_path, new_path)
    return new_path, dups


# ========== OVERLAY & ALERT ==========
def wait_overlay_gone(timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".ant-spin-blur")) == 0
        )
        return True
    except TimeoutException:
        return False

def dismiss_known_error_modal_once(timeout=2, post_wait=2):
    """
    Đóng popup HTML của Ant Design khi web báo lỗi tải file.
    Popup này không phải browser alert nên cần tự tìm nút OK để bấm.
    """
    end = time.time() + timeout
    modal_xpath = (
        "//div[contains(@class,'ant-modal-confirm') or contains(@class,'ant-modal-confirm-body-wrapper')]"
        "[.//span[contains(@class,'ant-modal-confirm-title') and normalize-space()='Lỗi']]"
        "[.//div[contains(@class,'ant-modal-confirm-content') and contains(normalize-space(),"
        "'Tải file không thành công')]]"
    )
    ok_xpath = (
        f"{modal_xpath}//button"
        "[contains(@class,'ant-btn-primary') and .//span[normalize-space()='OK']]"
    )

    while time.time() < end:
        try:
            ok_buttons = driver.find_elements(By.XPATH, ok_xpath)
            visible_ok = next((btn for btn in ok_buttons if btn.is_displayed()), None)
            if not visible_ok:
                time.sleep(0.05)
                continue

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", visible_ok)
            try:
                visible_ok.click()
            except Exception:
                driver.execute_script("arguments[0].click();", visible_ok)

            WebDriverWait(driver, post_wait).until(
                lambda d: len(d.find_elements(By.XPATH, modal_xpath)) == 0
            )
            wait_overlay_gone(timeout=post_wait)
            logger.info("✅ Đã đóng popup lỗi tải file.")
            return True
        except Exception:
            time.sleep(0.05)
            continue
    return False


def clear_blocking_ui(timeout=2):
    probe_timeout = min(timeout, UI_BLOCKER_PROBE_TIMEOUT)
    post_wait_timeout = min(timeout, UI_BLOCKER_POST_WAIT_TIMEOUT)
    handled_any = False
    handled_any = handle_connection_alert_once(timeout=probe_timeout, post_wait=post_wait_timeout) or handled_any
    handled_any = dismiss_known_error_modal_once(timeout=probe_timeout, post_wait=post_wait_timeout) or handled_any
    return handled_any

def wait_dom_settled(timeout=15):
    clear_blocking_ui(timeout=min(2, timeout))
    # 1) overlay gone
    wait_overlay_gone(timeout=timeout)
    # 2) document ready
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def wait_document_ready_quick(timeout=4):
    clear_blocking_ui(timeout=min(1, timeout))
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def wait_until_not_loading(driver, timeout=20):
    clear_blocking_ui(timeout=min(2, timeout))
    ok = wait_overlay_gone(timeout=timeout)
    if not ok:
        logger.warning("⚠️  Cảnh báo: overlay vẫn còn sau thời gian chờ.")

def handle_connection_alert_once(timeout=6, post_wait=3):
    """
    Bắt & accept alert (nếu có) càng nhanh càng tốt.
    - timeout: thời gian tối đa để chờ xuất hiện alert.
    - post_wait: thời gian tối đa chờ UI ổn định sau khi accept (không sleep cứng).
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            alert = driver.switch_to.alert
            text = (alert.text or "").strip()
            # Accept luôn, không phân biệt text để khỏi kẹt
            alert.accept()

            # Chờ alert thực sự biến mất (rất nhanh)
            t2 = time.time() + post_wait
            while time.time() < t2:
                try:
                    _ = driver.switch_to.alert
                    time.sleep(0.05)
                except NoAlertPresentException:
                    break

            # Chờ overlay gone nhẹ (không bắt buộc phải đủ post_wait)
            wait_overlay_gone(timeout=post_wait)
            return True

        except NoAlertPresentException:
            time.sleep(0.05)
            continue
        except Exception:
            time.sleep(0.05)
            continue
    return False

def safe_click(elem, wait, max_retry=3):
    for attempt in range(max_retry):
        try:
            clear_blocking_ui(timeout=2)
            wait_overlay_gone(timeout=20)
            elem.location_once_scrolled_into_view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            elem.click()
            return True
        except Exception as e:
            logger.error(f"❌ safe_click attempt {attempt+1}/{max_retry} lỗi: {e}")
            try:
                clear_blocking_ui(timeout=2)
                wait_overlay_gone(timeout=10)
                driver.execute_script("arguments[0].click();", elem)
                return True
            except Exception as e_js:
                logger.error(f"❌ JS click attempt {attempt+1}/{max_retry} lỗi: {e_js}")
                wait_dom_settled(timeout=15)
                continue
    return False


def khlcnt_quick_click(elem):
    try:
        clear_blocking_ui(timeout=0.5)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
        try:
            elem.click()
        except Exception:
            driver.execute_script("arguments[0].click();", elem)
        return True
    except UnexpectedAlertPresentException:
        handle_connection_alert_once(timeout=2, post_wait=0.5)
        try:
            driver.execute_script("arguments[0].click();", elem)
            return True
        except Exception:
            return False
    except Exception as error:
        logger.info("⏸️ KHLCNT quick click lỗi: %s", str(error)[:120])
        return False


def click_kqlcnt_tab_safely(index):
    """
    Click tab 'Kết quả lựa chọn nhà thầu' chịu được:
      - Alert 'Kết nối không ổn định'.
      - Overlay spinner.
    """
    for attempt in range(2):
        try:
            ket_qua_tab = wait_clickable(
                driver,
                By.XPATH,
                "//a[contains(text(),'Kết quả lựa chọn nhà thầu')]",
                timeout=20
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", ket_qua_tab)
            ket_qua_tab.click()
            wait_dom_settled(timeout=15)
            return True
        except UnexpectedAlertPresentException:
            logger.warning(f"⚠️ Box {index}: alert trong lúc click tab KQLCNT (attempt {attempt+1}).")
            handled = handle_connection_alert_once(timeout=10)
            if not handled:
                logger.warning(f"⚠️ Box {index}: không bắt được alert (có thể đã tự hết).")
            wait_dom_settled(timeout=15)
            continue
        except Exception as e:
            logger.error(f"❌ Box {index}: lỗi click tab KQLCNT (attempt {attempt+1}): {e}")
            wait_dom_settled(timeout=15)
            continue
    logger.error(f"❌ Box {index}: click tab KQLCNT thất bại sau 2 lần thử.")
    return False


# ========== HÀM HELPER ĐA PHIÊN BẢN ==========
def normalize_version_code(raw_text):
    """
    Chuẩn hoá text phiên bản:
    - Trim.
    - Rút gọn khoảng trắng nhiều thành 1 khoảng.
    - Thay ' / ' hoặc '/' thành '-' cho gọn.
    - Ví dụ: ' 01 / 01 ' -> '01-01'; '00' -> '00'.
    """
    if not raw_text:
        return None
    txt = " ".join(raw_text.split())  # gộp nhiều space
    txt = txt.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    txt = txt.replace("/", "-")
    return txt

def get_single_version_select_and_codes():
    """
    Tìm dropdown phiên bản ở:
    (1) 'Thông tin gói thầu' -> 'Phiên bản thay đổi'
    (2) 'Thông tin phê duyệt kết quả' -> 'Phiên bản KQ'
    Trả về (select_elem, list_codes) hoặc (None, []) nếu không có/không >1 option.
    Ưu tiên 'Phiên bản KQ'; nếu không có thì dùng 'Phiên bản thay đổi'.
    """
    # Ưu tiên Phiên bản KQ
    try:
        approve_card = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and normalize-space()='Thông tin phê duyệt kết quả']]"
        )
        rows = approve_card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title = row.find_element(
                    By.CSS_SELECTOR, ".infomation__content__title"
                ).text.strip()
            except Exception:
                continue
            if title == "Phiên bản KQ":
                sel = row.find_element(By.CSS_SELECTOR, "select.form-select")
                options = Select(sel).options
                if len(options) > 1:
                    codes = [normalize_version_code(opt.text) for opt in options]
                    return sel, codes
                else:
                    # chỉ có 1 phiên bản, coi như single-version
                    return None, []
    except Exception:
        pass

    # Fallback: Phiên bản thay đổi (Thông tin gói thầu)
    try:
        info_card = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and normalize-space()='Thông tin gói thầu']]"
        )
        rows = info_card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title = row.find_element(
                    By.CSS_SELECTOR, ".infomation__content__title"
                ).text.strip()
            except Exception:
                continue
            if title == "Phiên bản thay đổi":
                sel = row.find_element(By.CSS_SELECTOR, "select.form-select")
                options = Select(sel).options
                if len(options) > 1:
                    codes = [normalize_version_code(opt.text) for opt in options]
                    return sel, codes
                else:
                    return None, []
    except Exception:
        pass

    return None, []


def detect_single_version_select():
    """
    Tìm dropdown phiên bản ở:
    (1) 'Thông tin phê duyệt kết quả' -> 'Phiên bản KQ'
    (2) 'Thông tin gói thầu' -> 'Phiên bản thay đổi'
    Trả về:
        (select_elem, num_options)
    - Nếu không có select, trả (None, 0)
    - Nếu có nhưng chỉ 1 option, coi là single-version -> (None, 1)
    - Nếu có >=2 option, coi là multi-version -> (select_elem, num_options)
    Ưu tiên 'Phiên bản KQ'; nếu không có thì dùng 'Phiên bản thay đổi'.
    """
    # Ưu tiên Phiên bản KQ
    try:
        approve_card = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and normalize-space()='Thông tin phê duyệt kết quả']]"
        )
        rows = approve_card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title = row.find_element(
                    By.CSS_SELECTOR, ".infomation__content__title"
                ).text.strip()
            except Exception:
                continue
            if title == "Phiên bản KQ":
                sel = row.find_element(By.CSS_SELECTOR, "select.form-select")
                options = Select(sel).options
                if len(options) > 1:
                    return sel, len(options)  # multi-version
                else:
                    return None, 1            # single-version
    except Exception:
        pass

    # Fallback: Phiên bản thay đổi (Thông tin gói thầu)
    try:
        info_card = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and normalize-space()='Thông tin gói thầu']]"
        )
        rows = info_card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title = row.find_element(
                    By.CSS_SELECTOR, ".infomation__content__title"
                ).text.strip()
            except Exception:
                continue
            if title == "Phiên bản thay đổi":
                sel = row.find_element(By.CSS_SELECTOR, "select.form-select")
                options = Select(sel).options
                if len(options) > 1:
                    return sel, len(options)
                else:
                    return None, 1
    except Exception:
        pass

    return None, 0

def _sig(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8", errors="ignore")).hexdigest()

def wait_version_applied(select_elem, target_index, timeout=12):
    select = Select(select_elem)
    options = select.options
    if target_index < 0 or target_index >= len(options):
        raise TimeoutException(f"Dropdown version chỉ có {len(options)} option, không chọn được index {target_index}")

    target_text = normalize_version_code((options[target_index].text or "").strip())
    select.select_by_index(target_index)
    wait_document_ready_quick(timeout=min(4, timeout))

    def _selected_expected(_driver):
        try:
            current_elem = find_khlcnt_result_version_select() or select_elem
            current = Select(current_elem)
            current_options = current.options
            if target_index >= len(current_options):
                return False
            selected_index = current_options.index(current.first_selected_option)
            selected_text = normalize_version_code((current.first_selected_option.text or "").strip())
            return selected_index == target_index or (target_text and selected_text == target_text)
        except StaleElementReferenceException:
            return False
        except Exception:
            return False

    WebDriverWait(driver, timeout).until(_selected_expected)

    # đệm nhỏ cho React commit DOM
    time.sleep(0.25)


# ========== CHECK VERSION UI ==========
def get_current_ui_version():
    """
    Hàm này lấy phiên bản hiện tại hiển thị trên UI (phiên bản mặc định khi vừa vào trang).
    Trả về chuỗi version (vd: "01", "00", "02") hoặc "UNKNOWN" nếu không tìm thấy.
    """

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, 
                "//div[contains(@class,'card-header') and (normalize-space()='Thông tin phê duyệt kết quả' or normalize-space()='Thông tin gói thầu')]"
            ))
        )
        time.sleep(1) 
    except:
        logger.warning("⚠️ Hết thời gian đợi Card version xuất hiện.")

    sel, _ = detect_single_version_select()
    if sel:
        try:
            # Lấy option đang được chọn (Thường là bản mới nhất)
            selected_opt = Select(sel).first_selected_option
            return normalize_version_code(selected_opt.text)
        except Exception:
            return "UNKNOWN"
            
    # Nếu count == 1 (chỉ có 1 bản) hoặc không tìm thấy dropdown (count == 0)
    # Trả về 00 để đồng bộ với logic tracker của bạn
    return "00"


def find_khlcnt_result_version_select():
    card_xpath = (
        "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and ("
        "contains(normalize-space(),'Thông tin kết quả lựa chọn nhà thầu') or "
        "contains(normalize-space(),'Thông tin phê duyệt kết quả') or "
        "contains(normalize-space(),'Thông tin gói thầu')"
        ")]]"
    )
    cards = driver.find_elements(By.XPATH, card_xpath)
    for card in cards:
        rows = card.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for row in rows:
            try:
                title = normalize_info_key(row.find_element(By.CSS_SELECTOR, ".infomation__content__title").text)
            except Exception:
                continue
            if title not in {"phiên bản thay đổi", "phiên bản kq"}:
                continue
            try:
                return row.find_element(By.CSS_SELECTOR, "select.form-select")
            except Exception:
                continue
    return None


def get_khlcnt_result_version_entries():
    sel = find_khlcnt_result_version_select()
    if not sel:
        current_version = normalize_version_code(get_info_card_value("Phiên bản thay đổi", "Phiên bản KQ"))
        return [(None, current_version if current_version and current_version != "UNKNOWN" else "00")]

    try:
        options = Select(sel).options
    except Exception:
        return [(None, "00")]

    entries = []
    for idx, option in enumerate(options):
        version = normalize_version_code((option.text or "").strip())
        if version:
            entries.append((idx if len(options) > 1 else None, version))
    return entries or [(None, "00")]


def select_khlcnt_result_version(target_index):
    if target_index is None:
        return None
    select_elem = find_khlcnt_result_version_select()
    if not select_elem:
        raise TimeoutException(f"Không tìm thấy dropdown version KQLCNT index {target_index}")
    old_so_qd = get_info_card_value("Số quyết định phê duyệt")
    old_signature = get_khlcnt_detail_signature()
    clear_performance_logs()
    wait_version_applied(select_elem, target_index)
    try:
        WebDriverWait(driver, 8).until(
            lambda d: get_khlcnt_detail_signature() != old_signature
            or get_info_card_value("Số quyết định phê duyệt") != old_so_qd
        )
    except Exception:
        pass
    wait_dom_settled(timeout=4)
    return wait_for_kqlcnt_result_payload(timeout=KHLCNT_RESULTDTO_TIMEOUT)


def wait_for_kqlcnt_result_payload(timeout=10):
    end = time.time() + timeout
    last_payload = None
    while time.time() < end:
        payload = extract_kqlcnt_result_from_performance_logs()
        if payload:
            if payload.get("url_goi_thau_con"):
                return payload
            last_payload = last_payload or payload
        time.sleep(0.35)
    return last_payload


# ========== HÀM TẢI EXCEL/ĐÍNH KÈM CHO QĐ ĐANG CHỌN ==========
def wait_export_excel_button_quick(driver, timeout=1.2):
    """
    Trả về WebElement nút 'Xuất Excel' nếu có (trong ~timeout giây),
    không có thì trả None (không để mất 10-20s).
    """
    xps = [
        (
            By.XPATH,
            "//div[contains(@class,'card-header') and contains(normalize-space(),'Danh sách hàng hóa')]"
            "/following-sibling::div//button[contains(normalize-space(),'Xuất Excel')]"
        ),
        (
            By.XPATH,
            "//div[contains(@class,'card-header') and contains(normalize-space(),'Danh mục hàng hóa')]"
            "/following-sibling::div//button[contains(normalize-space(),'Xuất Excel')]"
        ),
        (
            By.XPATH,
            "//div[contains(@class,'card-header') and contains(normalize-space(),'Danh sách thuốc')]"
            "/following-sibling::div//button[contains(normalize-space(),'Xuất Excel')]"
        ),
        (
            By.XPATH,
            "//div[contains(@class,'card-header') and contains(normalize-space(),'Danh mục thuốc')]"
            "/following-sibling::div//button[contains(normalize-space(),'Xuất Excel')]"
        ),
    ]

    short_wait = WebDriverWait(driver, timeout)

    for loc in xps:
        try:
            # Lấy 1 element là đủ để click; nếu nhiều thì presence_of_all... cũng ok
            btn = short_wait.until(EC.presence_of_element_located(loc))
            return btn
        except TimeoutException:
            continue

    return None

def download_excel_or_attach_for_current_decision(
    ma_tbmt,
    box_index,
    dia_diem,
    suffix_qd=None,
    version_code=None,
    ngay_dang_tai_specific=None,
    trang_thai_specific=None,
    info_snapshot=None
):
    collection_method = None
    any_file_downloaded = False
    winner_fact = None
    winner_fact_saved = False

    def persist_winner_fact(commit):
        nonlocal winner_fact_saved
        if winner_fact_saved or winner_fact is None:
            return
        winner_fact_saved = tracker.save_web_winner_fact(
            tbmt=ma_tbmt,
            qd_raw=suffix_qd,
            version=version_code,
            fact_payload=winner_fact,
            commit=commit,
        )

    try:
        if has_legacy_lot_selection_card():
            ensure_select_lot_with_winner()

        winner_fact = extract_web_winner_fact()

        # --- 1. TÌM NÚT TẢI ---
        xuat_btn = wait_export_excel_button_quick(driver, timeout=1.2)
        
        if xuat_btn:
            collection_method = "trực tiếp"
            clear_raw_downloads()
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", xuat_btn)
            wait_until_not_loading(driver, 10)
            
            if not safe_click(xuat_btn, wait):
                raise TempCrawlAbort(ma_tbmt, f"Không thể click nút Xuất Excel ở box {box_index}")
                
            new_file = wait_for_new_file(None, timeout=60, exts=[".xlsx", ".xls"])
        
        else:
            collection_method = "gián tiếp"
            logger.warning(f"⚠️ Không thấy nút Xuất Excel ở box {box_index}, thử file đính kèm")
            try:
                file_tag = wait.until(EC.presence_of_element_located((
                    By.XPATH, "//div[contains(@class,'card border--none card-expand')]//tags[contains(@class,'tags-fileAttach')]"
                )))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", file_tag)
                wait_until_not_loading(driver, 10)
                clear_raw_downloads()
                
                if not safe_click(file_tag, wait):
                    raise TempCrawlAbort(ma_tbmt, f"Không thể click file đính kèm ở box {box_index}")
                    
                logger.info(f"✅ Đã click tải file đính kèm cho box {box_index}")
                new_file = wait_for_new_file(None, timeout=60, exts=None)
            except TimeoutException:
                logger.error(f"❌ Không tìm thấy file đính kèm ở box {box_index}")
                persist_winner_fact(commit=True)
                return False, winner_fact

        # --- 2. XỬ LÝ FILE TẢI VỀ ---
        if new_file:
            actual_file = get_actual_file_from_path(new_file)
            if not actual_file:
                raise TempCrawlAbort(ma_tbmt, f"Không lấy được file thực tế sau khi tải ở box {box_index}")

            # Logic cũ: Xóa file danh sách nhà thầu
            if "danh_sach_nha_thau" in os.path.basename(actual_file).lower():
                try: os.remove(actual_file)
                except: pass
                raise TempCrawlAbort(ma_tbmt, f"Tải nhầm file danh sách nhà thầu ở box {box_index}")

            # Tự động detect loại file
            ext = os.path.splitext(actual_file)[1].lower()
            detected_type = "excel" if ext in ['.xlsx', '.xls'] else "attachment"

            # GỌI DB TRACKER
            action, saved_path = tracker.check_and_save(
                tbmt=ma_tbmt,
                qd_raw=suffix_qd,
                version=version_code,
                file_type=detected_type,
                temp_path=actual_file,
                target_root_dir=BASE_DIR
            )

            if action == "SKIPPED":
                try: os.remove(actual_file)
                except: pass
                persist_winner_fact(commit=True)
                if info_snapshot and info_snapshot.get("Mã KHLCNT"):
                    tracker.save_khlcnt_metadata_for_tbmt(ma_tbmt, info_snapshot)
                logger.info(f"⏩ Skipped old version: {ma_tbmt} v{version_code}")
                return True, winner_fact
            elif action == "SKIPPED_DUPLICATE":
                persist_winner_fact(commit=True)
                if info_snapshot and info_snapshot.get("Mã KHLCNT"):
                    tracker.save_khlcnt_metadata_for_tbmt(ma_tbmt, info_snapshot)
                logger.info(f"↪️ Bỏ qua file PDF trùng nghĩa cho {ma_tbmt} / {suffix_qd} / v{version_code}")
                return True, winner_fact
            elif action == "NORMALIZED_DUPLICATE":
                persist_winner_fact(commit=True)
                if info_snapshot and info_snapshot.get("Mã KHLCNT"):
                    tracker.save_khlcnt_metadata_for_tbmt(ma_tbmt, info_snapshot)
                logger.info(f"🔁 Đã chuẩn hóa file PDF trùng nghĩa về 1 record packages cho {ma_tbmt} / {suffix_qd} / v{version_code}")
                any_file_downloaded = True
                return any_file_downloaded, winner_fact
                
            elif action in ["INSERT", "UPDATE"]:
                logger.info(f"✅ [{action}] Đã lưu file đính kèm")
                any_file_downloaded = True
                
                # LƯU METADATA NGAY LẬP TỨC
                info_dict = info_snapshot if info_snapshot is not None else extract_additional_info()

                if ngay_dang_tai_specific:
                    info_dict["Ngày đăng tải"] = ngay_dang_tai_specific

                # CẬP NHẬT TRẠNG THÁI RIÊNG
                if trang_thai_specific:
                    info_dict["Trạng thái đăng tải KQ"] = trang_thai_specific
                    info_dict["Trạng thái KQLCNT"] = trang_thai_specific
                    
                info_dict.update({
                    "Mã TBMT": ma_tbmt,
                    "Địa điểm": dia_diem,
                    "Cách thức tải về": collection_method,
                    "File Path": saved_path
                })
                persist_winner_fact(commit=False)
                tracker.save_metadata(ma_tbmt, suffix_qd, version_code, info_dict)
                
            else:
                raise TempCrawlAbort(ma_tbmt, f"Hệ thống không lưu được file tải về ở box {box_index}")
                
        else:
            dismiss_known_error_modal_once(timeout=2, post_wait=2)
            raise TempCrawlAbort(ma_tbmt, f"Timeout tải file ({collection_method}) ở box {box_index}")

        return any_file_downloaded, winner_fact
    except TempCrawlAbort:
        persist_winner_fact(commit=True)
        raise


# ========== LOG PDF-ONLY ==========
def log_pdf_only_if_needed(any_downloaded, any_excel_for_box, ma_tbmt, so_qd, ver_code, dia_diem, dest_qd, info_snapshot=None, winner_fact=None):
    """
    Nếu chỉ có PDF -> Ghi metadata vào DB để tracking.
    """
    if any_downloaded and not any_excel_for_box and dest_qd:
        # Lấy thông tin từ UI
        info_dict = info_snapshot if info_snapshot is not None else extract_additional_info()
        
        # Bổ sung các trường định danh
        info_dict.update({
            "Mã TBMT": ma_tbmt,
            "Địa điểm": dia_diem,
            "Cách thức tải về": "PDF_ONLY", # Đánh dấu rõ là chỉ có PDF
            "File Path": dest_qd
        })

        if winner_fact is not None:
            tracker.save_web_winner_fact(ma_tbmt, so_qd, ver_code, winner_fact, commit=False)
        tracker.save_metadata(ma_tbmt, so_qd, ver_code, info_dict)
        logger.info(f"ℹ️ Đã lưu metadata cho gói chỉ có PDF: {ma_tbmt}")



# ========== TẢI PDF QĐ ĐƠN ==========
def download_single_qd_pdf(
    ma_tbmt,
    qd_element,
    qd_text_raw,
    version_code=None
):
    
    clear_raw_downloads()
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", qd_element)
        time.sleep(0.5)
        if not safe_click(qd_element, wait):
            raise TempCrawlAbort(ma_tbmt, f"Không thể click PDF QĐ: {qd_text_raw}")
            
        logger.info(f"⬇️  Đang tải PDF QĐ: {qd_text_raw}")
        new_pdf = wait_for_new_file(None, timeout=45, exts=[".pdf"])
        
        if new_pdf:
            actual_qd = get_actual_file_from_path(new_pdf)
            if not actual_qd:
                raise TempCrawlAbort(ma_tbmt, f"Không lấy được file PDF QĐ thực tế: {qd_text_raw}")
            
            # GỌI DB TRACKER CHO PDF
            action, saved_path = tracker.check_and_save(
                tbmt=ma_tbmt,
                qd_raw=qd_text_raw,
                version=version_code,
                file_type="pdf",
                temp_path=actual_qd,
                target_root_dir=BASE_DIR
            )
            
            if action == "SKIPPED":
                try: os.remove(actual_qd)
                except: pass
                return True, None # True nghĩa là tải thành công, nhưng skip lưu
            elif action == "SKIPPED_DUPLICATE":
                return True, saved_path
            elif action == "NORMALIZED_DUPLICATE":
                logger.info(f"🔁 Đã chuẩn hóa PDF QĐ trùng nghĩa về 1 record packages")
                return True, saved_path
            elif action in ["INSERT", "UPDATE"]:
                logger.info(f"✅ [{action}] Đã lưu QĐ phê duyệt")
                return True, saved_path

            else:
                raise TempCrawlAbort(ma_tbmt, f"Hệ thống không lưu được PDF QĐ: {qd_text_raw}")
        else:
            dismiss_known_error_modal_once(timeout=2, post_wait=2)
            raise TempCrawlAbort(ma_tbmt, f"Timeout tải PDF QĐ: {qd_text_raw}")
            
    except Exception as e:
        if isinstance(e, TempCrawlAbort):
            raise
        logger.error(f"❌ Lỗi tải PDF: {e}")
        raise TempCrawlAbort(ma_tbmt, f"Lỗi tải PDF QĐ {qd_text_raw}: {str(e)[:300]}")


def find_approval_pdf_tag(timeout=5):
    xpaths = [
        (
            "//div[contains(@class,'card')][.//div[contains(@class,'card-header') and ("
            "contains(normalize-space(),'Thông tin kết quả lựa chọn nhà thầu') or "
            "contains(normalize-space(),'Thông tin phê duyệt kết quả')"
            ")]]"
            "//div[contains(@class,'infomation__content')][.//div[contains(@class,'infomation__content__title') "
            "and contains(normalize-space(),'Quyết định phê duyệt')]]"
            "//tags[contains(@class,'tags-fileAttach')]"
        ),
        (
            "//div[contains(@class,'infomation__content')][.//div[contains(@class,'infomation__content__title') "
            "and contains(normalize-space(),'Quyết định phê duyệt')]]"
            "//tags[contains(@class,'tags-fileAttach')]"
        ),
    ]
    last_error = None
    for xpath in xpaths:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except TimeoutException as error:
            last_error = error
            continue
    raise TimeoutException("Không tìm thấy tag PDF Quyết định phê duyệt") from last_error


def download_approval_pdf_if_present(ma_tbmt, so_qd, version, timeout=3):
    try:
        pdf_tag = find_approval_pdf_tag(timeout=timeout)
    except TimeoutException:
        logger.info("ℹ️ %s / %s / v%s: không thấy PDF QĐ", ma_tbmt, so_qd, version)
        return False, None

    try:
        ok, path = download_single_qd_pdf(
            ma_tbmt=ma_tbmt,
            qd_element=pdf_tag,
            qd_text_raw=so_qd,
            version_code=version,
        )
        return ok, path
    except TempCrawlAbort as error:
        logger.info("⏭️ %s / %s / v%s: bỏ qua PDF QĐ (%s)", ma_tbmt, so_qd, version, error.reason[:160])
        return False, None


def collect_khlcnt_result_file(ma_tbmt, so_qd, version, target_card=None, target_card_name=""):
    if target_card is None:
        try:
            target_card, target_card_name = find_target_item_card(timeout=4)
        except TimeoutException:
            return None, "", ""

    card_kind = get_target_card_kind(target_card_name)
    has_multiple_pages = _card_has_multiple_pages(target_card)

    def try_export_excel():
        export_button = get_target_card_export_button(target_card)
        if not export_button:
            return None
        try:
            clear_raw_downloads()
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", export_button)
            wait_document_ready_quick(timeout=3)
            if khlcnt_quick_click(export_button):
                downloaded_file = wait_for_new_file(None, timeout=60, exts=[".xlsx", ".xls"])
                actual_file = get_actual_file_from_path(downloaded_file) if downloaded_file else None
                if actual_file:
                    return actual_file
        except Exception as error:
            pass
        return None

    def try_web_table():
        direct_file, _direct_cols, card_name = save_target_card_table_as_excel(
            ma_tbmt,
            so_qd,
            version,
            card=target_card,
            card_name=target_card_name,
        )
        if direct_file:
            return direct_file, card_name
        return None, target_card_name

    if card_kind == "medicine" and not has_multiple_pages:
        direct_file, card_name = try_web_table()
        if direct_file:
            return direct_file, card_name, "đọc trực tiếp bảng web"
        excel_file = try_export_excel()
        if excel_file:
            return excel_file, target_card_name, "Xuất Excel"
        return None, target_card_name, ""

    excel_file = try_export_excel()
    if excel_file:
        return excel_file, target_card_name, "Xuất Excel"

    direct_file, card_name = try_web_table()
    if direct_file:
        return direct_file, card_name, "đọc trực tiếp bảng web"
    return None, target_card_name, ""


# ========== HÀM HANDLE QĐ (ĐƠN / ĐA) ==========
def wait_until_so_qd_matches(so_qd, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: so_qd in d.find_element(
                By.XPATH,
                "//div[contains(@class,'card-header') and contains(normalize-space(),'Thông tin phê duyệt kết quả')]"
                "/following-sibling::div//div[contains(@class,'infomation__content__title') and normalize-space(text())='Số quyết định phê duyệt']"
                "/following-sibling::div"
            ).text
        )
        return True
    except Exception:
        return False

def _process_one_qd_flow(ma_tbmt, box_index, dia_diem, qd_text_raw, qd_element_pdf, version_code, 
                         ngay_dang_tai_specific=None, trang_thai_specific=None, info_snapshot=None):
    """Helper xử lý 1 combo: 1 QĐ + 1 bộ file (PDF + Excel/Attach)"""
    any_dl = False
    any_excel = False
    dest_qd = None
    winner_fact = None
    safe_ver = version_code if version_code else "00"
    should_download, download_reason = tracker.should_download_unit(ma_tbmt, qd_text_raw, safe_ver)
    if not should_download:
        if info_snapshot and info_snapshot.get("Mã KHLCNT"):
            tracker.save_khlcnt_metadata_for_tbmt(ma_tbmt, info_snapshot)
        return True, False, None, None, download_reason

    # 1. Tải PDF QĐ (nếu có element)
    if qd_element_pdf:
        try:
            ok, path = download_single_qd_pdf(
                ma_tbmt=ma_tbmt,
                qd_element=qd_element_pdf,
                qd_text_raw=qd_text_raw,
                version_code=safe_ver
            )
            if ok:
                any_dl = True
                dest_qd = path
        except TempCrawlAbort as e:
            logger.error(
                f"❌ Lỗi tải PDF ở box {box_index} cho {ma_tbmt} / {qd_text_raw} / v{safe_ver}: {e.reason}"
            )

    # 2. Tải Excel/Attach
    # suffix_qd dùng cho tên file Excel chính là số QĐ raw
    excel_downloaded, winner_fact = download_excel_or_attach_for_current_decision(
        ma_tbmt, box_index, dia_diem, suffix_qd=qd_text_raw, version_code=safe_ver, 
        ngay_dang_tai_specific=ngay_dang_tai_specific, trang_thai_specific=trang_thai_specific,
        info_snapshot=info_snapshot
    )
    if excel_downloaded:
        any_dl = True
        any_excel = True

    return any_dl, any_excel, dest_qd, winner_fact, None


def finalize_one_qd_result(ma_tbmt, box_index, dia_diem, so_qd, ver_code, any_dl, any_excel, dest_qd, info_snapshot=None, winner_fact=None, download_skipped_reason=None):
    if download_skipped_reason:
        logger.info(
            f"✅ Đã check version, bỏ qua tải file cho {ma_tbmt} / {so_qd} / v{ver_code}: {download_skipped_reason}"
        )
        return

    log_pdf_only_if_needed(
        any_dl,
        any_excel,
        ma_tbmt,
        so_qd,
        ver_code,
        dia_diem,
        dest_qd,
        info_snapshot=info_snapshot,
        winner_fact=winner_fact,
    )
    if not any_excel:
        tracker.log_event(
            tbmt=ma_tbmt,
            qd_raw=so_qd,
            version=ver_code,
            action_type="NO_ATTACHMENTS",
            reason=f"Không có Excel/Attach box {box_index}"
        )
        logger.warning(f"⚠️ Đã log NO_ATTACHMENTS cho {ma_tbmt} / {so_qd} / v{ver_code}")

def handle_quyet_dinh_phe_duyet_all(ma_tbmt, box_index, box_name_text, ngay_phe_duyet, dia_diem, khlcnt_metadata=None):
    any_downloaded = False
    any_excel_for_box = False
    last_qd_path = None
    handled_qd_count = 0
    
    wait_until_not_loading(driver, timeout=10)

    # --- Helper: Lấy Text từ Card Detail ---
    def get_card_value(title):
        try:
            xpath = f"//div[contains(@class,'infomation__content__title') and normalize-space(text())='{title}']/following-sibling::div"
            el = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, xpath)))
            return el.text.strip()
        except: return ""

    # --- Helper: Lấy PDF tag từ Card Detail ---
    def get_card_pdf_tag():
        try:
            xpath = "//div[contains(@class,'infomation__content__title') and normalize-space(text())='Quyết định phê duyệt']/following-sibling::div//tags[contains(@class,'tags-fileAttach')]"
            return WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, xpath)))
        except: return None

    seen_qd_versions = {}

    def log_duplicate_qd_version(so_qd, ver_code):
        qd_norm = (so_qd or "UNKNOWN_QD").strip() or "UNKNOWN_QD"
        ver_norm = (ver_code or "00").strip() or "00"
        key = (qd_norm, ver_norm)
        seen_qd_versions[key] = seen_qd_versions.get(key, 0) + 1

        if seen_qd_versions[key] != 2:
            return

        reason = (
            f"Cùng ma_tbmt/so_qd/version xuất hiện nhiều hơn 1 lần trong box {box_index}: "
            f"{qd_norm} / v{ver_norm}"
        )
        tracker.log_event(
            tbmt=ma_tbmt,
            qd_raw=qd_norm,
            version=ver_norm,
            action_type="DUPLICATE_UNIT",
            reason=reason
        )
        logger.warning(f"⚠️ Phát hiện unit trùng trong box {box_index}: {ma_tbmt} / {qd_norm} / v{ver_norm}")

    # =========================================================
    # CASE 3: ĐA QĐ
    # =========================================================
    try:
        qd_table = WebDriverWait(driver, 1.5).until(EC.presence_of_element_located((
            By.XPATH, "//div[contains(@class,'card-header') and contains(normalize-space(),'Danh sách quyết định phê duyệt')]"
            "/following-sibling::div//table[contains(@class,'table-expand')]"
        )))
        logger.info("📍 CASE 3: ĐA QUYẾT ĐỊNH (Table)")
        
        # Lấy danh sách dòng ban đầu
        # Lưu ý: Khi thao tác trên 1 dòng, DOM có thể refresh, nên cần find lại rows nếu cần
        # Nhưng thường table structure giữ nguyên, chỉ content thay đổi
        rows = qd_table.find_elements(By.XPATH, ".//tbody/tr")
        
        if rows:
            for i_row, row in enumerate(rows):
                try:
                    # Refresh row element để tránh StaleElementReferenceException
                    # (Tìm lại row theo index)
                    current_row = qd_table.find_elements(By.XPATH, ".//tbody/tr")[i_row]
                    
                    # 1. Kiểm tra dropdown version
                    opts = []
                    try:
                        ver_select = current_row.find_element(By.CSS_SELECTOR, "select.form-select")
                        opts = Select(ver_select).options
                    except: pass

                    version_entries = []
                    if len(opts) > 1:
                        for idx, opt in enumerate(opts):
                            ver_label = normalize_version_code((opt.text or "").strip())
                            if not ver_label:
                                continue
                            version_entries.append((idx, ver_label))
                    elif len(opts) == 1:
                        try:
                            version_entries.append((None, normalize_version_code((opts[0].text or "").strip()) or "00"))
                        except Exception:
                            version_entries.append((None, "00"))
                    else:
                        version_entries.append((None, "00"))
                    
                    for i_ver, planned_ver_code in version_entries:
                        try:
                            ver_code = planned_ver_code or "00"
                            
                            # --- LOGIC ĐỔI VERSION ---
                            if i_ver is not None:
                                # Phải find lại select vì DOM có thể đã đổi sau lần loop trước
                                current_row = qd_table.find_elements(By.XPATH, ".//tbody/tr")[i_row]
                                ver_select = current_row.find_element(By.CSS_SELECTOR, "select.form-select")
                                
                                logger.info(f"👉 Dòng {i_row+1} - Version {ver_code}")
                                
                                wait_version_applied(ver_select, i_ver)
                                wait_dom_settled(timeout=2)

                            elif len(opts) == 1:
                                ver_code = planned_ver_code or "00"

                            # --- CLICK RADIO ĐỂ LOAD DETAIL ---
                            # Phải find lại row và radio
                            current_row = qd_table.find_elements(By.XPATH, ".//tbody/tr")[i_row]
                            try:
                                radio = current_row.find_element(By.XPATH, ".//input[@type='radio']")
                                driver.execute_script("arguments[0].click();", radio)
                                wait_dom_settled(timeout=3) # Đợi card detail load
                                
                            except Exception as e:
                                logger.warning(f"⚠️ Lỗi click radio: {e}")

                            info_snapshot = merge_khlcnt_metadata(extract_additional_info(), khlcnt_metadata)

                            # --- LẤY DỮ LIỆU ---
                            # 1. Số QĐ: Lấy từ Card Detail (chính xác nhất theo version)
                            so_qd = get_card_value("Số quyết định phê duyệt")
                            if not so_qd: 
                                # Fallback: Lấy từ bảng nếu card không có
                                so_qd = current_row.find_element(By.XPATH, "./td[2]").text.strip()
                            log_duplicate_qd_version(so_qd, ver_code)

                            # 2. Ngày Đăng Tải: Lấy từ bảng (cột 5)
                            # Lưu ý: Cần check xem cột này có thay đổi theo version không
                            try:
                                ngay_dang_tai_row = current_row.find_element(By.XPATH, "./td[5]").text.strip()
                            except: ngay_dang_tai_row = None
                            
                            # 3. Trạng Thái: Lấy từ bảng (cột 6)
                            try:
                                trang_thai_row = current_row.find_element(By.XPATH, "./td[6]").text.strip()
                            except: trang_thai_row = None

                            # 4. PDF Tag: Lấy từ Card Detail
                            pdf_tag = get_card_pdf_tag()
                            
                            # --- XỬ LÝ DOWNLOAD ---
                            ok, ok_excel, path, winner_fact, download_skipped_reason = _process_one_qd_flow(
                                ma_tbmt, box_index, dia_diem,
                                qd_text_raw=so_qd, 
                                qd_element_pdf=pdf_tag, 
                                version_code=ver_code, 
                                ngay_dang_tai_specific=ngay_dang_tai_row,
                                trang_thai_specific=trang_thai_row,
                                info_snapshot=info_snapshot
                            )
                            handled_qd_count += 1
                            finalize_one_qd_result(
                                ma_tbmt=ma_tbmt,
                                box_index=box_index,
                                dia_diem=dia_diem,
                                so_qd=so_qd,
                                ver_code=ver_code,
                                any_dl=ok,
                                any_excel=ok_excel,
                                dest_qd=path,
                                info_snapshot=info_snapshot,
                                winner_fact=winner_fact,
                                download_skipped_reason=download_skipped_reason
                            )
                            
                            if ok: any_downloaded = True
                            if ok_excel: any_excel_for_box = True
                            if path: last_qd_path = path
                        except Exception as e:
                            logger.error(
                                f"❌ Lỗi xử lý dòng {i_row+1} version {ver_code} Case 3: {e}"
                            )
                            continue

                except Exception as e:
                    logger.error(f"❌ Lỗi xử lý dòng {i_row+1} Case 3: {e}")
                    continue
            
            return any_downloaded

    except TimeoutException:
        pass  

    # =========================================================
    # CASE 1 & 2: QUYẾT ĐỊNH ĐƠN (Card)
    # =========================================================
    pdf_tag = None
    case_name = ""
    
    try:
        pdf_tag = driver.find_element(By.XPATH, "//div[contains(@class,'card-header') and contains(normalize-space(),'Thông tin gói thầu')]/following-sibling::div//tags[contains(@class,'tags-fileAttach')]")
        case_name = "CASE 1 (Đơn A)"
    except:
        try:
            pdf_tag = driver.find_element(By.XPATH, "//div[contains(@class,'card-header') and contains(normalize-space(),'Thông tin phê duyệt kết quả')]/following-sibling::div//tags[contains(@class,'tags-fileAttach')]")
            case_name = "CASE 2 (Đơn B)"
        except:
            pass

    if case_name:
        logger.info(f"📍 {case_name}")

        info_snapshot_base = merge_khlcnt_metadata(extract_additional_info(), khlcnt_metadata)
        last_info_snapshot = info_snapshot_base  # Tracking snapshot cuối cùng để truyền cho log_pdf_only
        
        ver_sel, ver_count = detect_single_version_select()
        loop_range = range(ver_count) if ver_count > 1 else [None]
        
        for i in loop_range:
            ver_code = "00"
            if i is not None:
                # TRỌNG YẾU: Lưu số QĐ cũ để so sánh
                old_so_qd = get_card_value("Số quyết định phê duyệt") 
                
                sel_obj = Select(ver_sel)
                ver_code = normalize_version_code(sel_obj.options[i].text.strip())
                logger.info(f"👉 Version {ver_code}")
                wait_version_applied(ver_sel, i)
                
                # TRỌNG YẾU: Đợi cho đến khi text Số QĐ thay đổi so với bản cũ (nếu có thay đổi)
                # Hoặc ít nhất là đợi DOM ổn định sau khi chọn Select
                try:
                    WebDriverWait(driver, 5).until(lambda d: get_card_value("Số quyết định phê duyệt") != old_so_qd)
                except:
                    pass # Trường hợp version khác nhưng số QĐ trùng nhau thì bỏ qua
                
                pdf_tag = get_card_pdf_tag()

                # ✅ Re-extract sau khi version thay đổi (card content cập nhật)
                info_snapshot = merge_khlcnt_metadata(extract_additional_info(), khlcnt_metadata)
                last_info_snapshot = info_snapshot

            elif ver_count == 1:
                try:
                    ver_code = normalize_version_code(Select(ver_sel).options[0].text.strip())
                except:
                    ver_code = "00"
                info_snapshot = info_snapshot_base  # ✅ Single version: dùng base

            else:
                info_snapshot = info_snapshot_base  # ✅ No version dropdown: dùng base

            so_qd = get_card_value("Số quyết định phê duyệt")
            if not so_qd: so_qd = "UNKNOWN_QD"
            log_duplicate_qd_version(so_qd, ver_code)

            ok, ok_excel, path, winner_fact, download_skipped_reason = _process_one_qd_flow(
                ma_tbmt, box_index, dia_diem,
                qd_text_raw=so_qd, qd_element_pdf=pdf_tag, version_code=ver_code, 
                ngay_dang_tai_specific=None, trang_thai_specific=None,
                info_snapshot=info_snapshot
            )
            handled_qd_count += 1
            finalize_one_qd_result(
                ma_tbmt=ma_tbmt,
                box_index=box_index,
                dia_diem=dia_diem,
                so_qd=so_qd,
                ver_code=ver_code,
                any_dl=ok,
                any_excel=ok_excel,
                dest_qd=path,
                info_snapshot=info_snapshot,
                winner_fact=winner_fact,
                download_skipped_reason=download_skipped_reason
            )
            if ok: any_downloaded = True
            if ok_excel: any_excel_for_box = True
            if path: last_qd_path = path

    else:
        raise TempCrawlAbort(ma_tbmt, f"Không tìm thấy QĐ (Fallback) ở box {box_index}")

    return any_downloaded


# ================== PROCESS BOX ==================
def process_box(box, index):
    """
    Trả về True nếu box này có ít nhất 1 file tải được (PDF/Excel).
    """
    if index == 1:
        wait_dom_settled(timeout=15)
    else:
        wait_dom_settled(timeout=15)

    clear_raw_downloads()
    ma_tbmt = get_ma_tbmt(box)
    dia_diem = get_dia_diem(box)
    box_name_text = ""
    basic_snapshot = {}
    
    ngay_phe_duyet = get_ngay_phe_duyet_kqlcnt(box)
    if not ngay_phe_duyet:
        logger.error(f"❌ Không lấy được ngày phê duyệt KQLCNT box {index}, bỏ qua")
        return False
    if YEAR_FROM and ngay_phe_duyet.year < YEAR_FROM:
        logger.error(f"❌ Bỏ qua box {index} vì năm {ngay_phe_duyet.year} < {YEAR_FROM}")
        logger.info("=" * 30)
        return False
    if YEAR_TO and ngay_phe_duyet.year > YEAR_TO:
        logger.error(f"❌ Bỏ qua box {index} vì năm {ngay_phe_duyet.year} > {YEAR_TO}")
        logger.info("=" * 30)
        return False

    # tên box
    try:
        box_name_text = get_ten_goi_thau(box)
    except Exception:
        box_name_text = "❌ Không lấy được tên box"

    basic_snapshot = build_box_metadata_snapshot(
        box=box,
        ma_tbmt=ma_tbmt,
        dia_diem=dia_diem,
        box_name_text=box_name_text,
        ngay_phe_duyet=ngay_phe_duyet
    )

    # link chi tiết
    try:
        link_element = box.find_element(
            By.XPATH,
            ".//a[h5[contains(@class,'content__body__left__item__infor__contract__name')]]"
        )
    except Exception as e:
        raise TempCrawlAbort(ma_tbmt, f"Lỗi lấy link chi tiết ở box {index}: {str(e)[:300]}")

    main_window = driver.window_handles[0]

    url = link_element.get_attribute("href")
    driver.execute_script("window.open(arguments[0]);", url)
    driver.switch_to.window(driver.window_handles[-1])

    has_any_download = False
    khlcnt_metadata = {}

    try:
        khlcnt_metadata = extract_tbmt_khlcnt_metadata()
        if khlcnt_metadata.get("Mã KHLCNT"):
            logger.info("🔗 TBMT %s: KHLCNT %s", ma_tbmt, khlcnt_metadata.get("Mã KHLCNT"))

        # 1) Click tab "Kết quả lựa chọn nhà thầu"
        try:
            ket_qua_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(text(),'Kết quả lựa chọn nhà thầu')]")
            ))
            driver.execute_script("arguments[0].scrollIntoView(true);", ket_qua_tab)
            wait_dom_settled(timeout=15)
            ket_qua_tab.click()
        except UnexpectedAlertPresentException:
            logger.warning(f"⚠️ Box {index}: alert trong lúc click tab KQLCNT, xử lý alert rồi click lại.")
            handle_connection_alert_once(timeout=3, post_wait=3)
            wait_dom_settled(timeout=6)
            ket_qua_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(text(),'Kết quả lựa chọn nhà thầu')]")
            ))
            driver.execute_script("arguments[0].scrollIntoView(true);", ket_qua_tab)
            wait_dom_settled(timeout=15)
            ket_qua_tab.click()
            wait_dom_settled(timeout=15)

        logger.info(f"Box {index}: {ma_tbmt}")

        # 2) Xử lý quyết định (đơn/đa)
        try:
            has_any_download = handle_quyet_dinh_phe_duyet_all(
                ma_tbmt, index, box_name_text, ngay_phe_duyet, dia_diem,
                khlcnt_metadata=khlcnt_metadata,
            )
        except UnexpectedAlertPresentException:
            logger.warning(f"⚠️ Box {index}: alert trong khi xử lý QĐ, xử lý alert rồi thử lại 1 lần.")
            handle_connection_alert_once(timeout=20)
            wait_until_not_loading(driver, 10)
            try:
                has_any_download = handle_quyet_dinh_phe_duyet_all(
                    ma_tbmt, index, box_name_text, ngay_phe_duyet, dia_diem,
                    khlcnt_metadata=khlcnt_metadata,
                )
            except UnexpectedAlertPresentException:
                logger.warning(f"⚠️ Box {index}: alert lặp lại khi retry QĐ, dừng TBMT này.")
                handle_connection_alert_once(timeout=20)
                raise TempCrawlAbort(ma_tbmt, f"Alert lặp lại khi xử lý QĐ ở box {index}")

    except TempCrawlAbort:
        raise
    except Exception as e:
        logger.error(f"❌ Lỗi xử lý box {index}: {e}")
        raise TempCrawlAbort(ma_tbmt, f"PROCESSING_ERROR ở box {index}: {str(e)[:300]}")

    finally:
        try:
            logger.info("=" * 30)
            driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_window)
        except Exception:
            pass
        if driver is not None:
            wait_dom_settled(timeout=15)

    if has_any_download and tracker is not None:
        tracker._safe_execute("""
            UPDATE packages
            SET status='DONE'
            WHERE ma_tbmt=%s AND is_latest=1
        """, (ma_tbmt,))
        tracker.conn.commit()

    return has_any_download


# ================== TRY PROCESS BOX ==================
def try_process_box(i, page, boxes, ma_tbmt, max_retry=3):
    retries = 0
    while retries < max_retry:
        try:
            if i == 0 and page == 1:
                wait_dom_settled(timeout=15)
            box = boxes[i]
            if not is_box_selected_or_filtered(box, i + 1 + (page - 1) * len(boxes)):
                return False
            return process_box(box, i + 1 + (page - 1) * len(boxes))
        except StaleElementReferenceException as e:
            logger.error(f"❌ Stale element error for box {i+1} page {page}, retry {retries+1}/{max_retry}: {e}")
            retries += 1
            wait_dom_settled(timeout=15)
    raise TempCrawlAbort(ma_tbmt, f"Stale element lặp lại sau {max_retry} lần retry ở box {i+1} trang {page}")

# ================== LẤY DANH SÁCH BOX ==================
def get_box_elements():
    wait_dom_settled(timeout=15)
    container = wait_presence(driver, By.ID, "bid-closed", timeout=20)
    boxes = container.find_elements(By.CSS_SELECTOR, "div.content__body__left__item")
    return boxes


def select_keyword_match_mode(match_value: str):
    radio_xpath = f"//input[@type='radio' and @name='check-1' and @value='{match_value}']"
    radio = wait.until(EC.presence_of_element_located((By.XPATH, radio_xpath)))
    group = wait.until(EC.presence_of_element_located((By.XPATH, f"{radio_xpath}/ancestor::div[contains(@class,'check-radio-group')]")))

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", group)

    try:
        driver.execute_script("arguments[0].click();", group)
    except Exception:
        pass

    try:
        wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())
        return
    except TimeoutException:
        pass

    try:
        clickable_label = group.find_elements(By.TAG_NAME, "label")[-1]
        driver.execute_script("arguments[0].click();", clickable_label)
        wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())
        return
    except Exception:
        pass

    driver.execute_script(
        """
        const radio = arguments[0];
        radio.checked = true;
        radio.dispatchEvent(new Event('input', { bubbles: true }));
        radio.dispatchEvent(new Event('change', { bubbles: true }));
        radio.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        """,
        radio,
    )
    wait.until(lambda d: d.find_element(By.XPATH, radio_xpath).is_selected())


def resolve_match_mode(search_keyword: str) -> str:
    keyword_norm = (search_keyword or "").strip().lower()
    return SEARCH_MATCH_MODE_BY_KEYWORD.get(keyword_norm, SEARCH_MATCH_MODE)


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ', "\"", '.join(f"'{part}'" for part in value.split('"')) + ")"


def select_search_notice_type(notice_type: str):
    label = _resolve_search_notice_type_label(notice_type)
    if label == DEFAULT_SEARCH_NOTICE_TYPE:
        return DEFAULT_SEARCH_NOTICE_TYPE

    selected_xpath = (
        "//div[contains(@class,'width_date_antdv')]"
        "//div[contains(@class,'ant-select-selection--single')]"
    )
    selected = wait_clickable(driver, By.XPATH, selected_xpath, timeout=20)
    driver.execute_script("arguments[0].click();", selected)

    label_xpath = xpath_literal(label)
    option_xpaths = [
        f"//li[contains(@class,'ant-select-dropdown-menu-item') and normalize-space()={label_xpath}]",
        f"//li[contains(@class,'ant-select-dropdown-menu-item') and contains(normalize-space(), {label_xpath})]",
    ]
    last_error = None
    for option_xpath in option_xpaths:
        try:
            option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
            driver.execute_script("arguments[0].click();", option)
            logger.info(f"📌 Loại thông tin tìm kiếm: {label}")
            wait_dom_settled(timeout=15)
            return label
        except Exception as error:
            last_error = error
    raise TimeoutException(f"Không chọn được loại thông tin tìm kiếm: {label}") from last_error


def find_search_keyword_input(active_notice_type=DEFAULT_SEARCH_NOTICE_TYPE):
    if active_notice_type == KHLCNT_SEARCH_NOTICE_TYPE:
        khlcnt_placeholders = [
            "Nhập Mã KHLCNT/ Tên KHLCNT/ Tên gói thầu trong KHLCNT/ Tóm tắt công việc chính của gói thầu",
            "nhập mã khlcnt/ tên khlcnt/ tên gói thầu trong khlcnt/ tóm tắt công việc chính của gói thầu",
        ]
        for placeholder in khlcnt_placeholders:
            try:
                return wait_presence(driver, By.XPATH, f"//input[@placeholder={xpath_literal(placeholder)}]", timeout=3)
            except TimeoutException:
                continue
        return wait_presence(
            driver,
            By.XPATH,
            "//input[contains(@placeholder,'tóm tắt công việc chính của gói thầu')]",
            timeout=20,
        )

    exact_placeholder = "Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)"
    try:
        return wait.until(
            EC.presence_of_element_located(
                (By.XPATH, f"//input[@placeholder={xpath_literal(exact_placeholder)}]")
            )
        )
    except TimeoutException:
        pass

    keyword_tokens = ["tbmt", "tên gói thầu", "khlcnt", "mã kế hoạch", "tên kế hoạch", "kế hoạch lựa chọn nhà thầu"]
    excluded_tokens = ["áp dụng cho tất cả", "không chứa", "từ ngày", "đến ngày", "ngày đăng tải"]
    inputs = driver.find_elements(By.XPATH, "//input[not(@type='hidden') and not(@type='checkbox') and not(@type='radio')]")
    for item in inputs:
        try:
            placeholder = (item.get_attribute("placeholder") or "").strip().lower()
            if item.is_displayed() and item.is_enabled() and not any(token in placeholder for token in excluded_tokens):
                if any(token in placeholder for token in keyword_tokens):
                    logger.info(f"🔎 Dùng ô keyword có placeholder: {placeholder}")
                    return item
        except Exception:
            continue
    raise TimeoutException("Không tìm thấy ô nhập keyword.")


def apply_post_search_filters(active_notice_type: str):
    if active_notice_type != DEFAULT_SEARCH_NOTICE_TYPE:
        logger.info(f"ℹ️ Bỏ qua filter Đã đóng thầu/Có nhà thầu trúng thầu cho loại: {active_notice_type}")
        return

    wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[contains(@class, 'nav-tabs')]//a[contains(text(),'Đã đóng thầu')]"))).click()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'content__body__option')]//span[contains(normalize-space(),'Có nhà thầu trúng thầu')]"))).click()


def prepare_search_form(search_keyword: str, notice_type: str = DEFAULT_SEARCH_NOTICE_TYPE):
    driver.get("https://muasamcong.mpi.gov.vn/web/guest/home")
    try:
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "popup-close")))
        close_button.click()
        logger.info("✅ Đã đóng hộp thông báo quan trọng.")
    except (TimeoutException, NoSuchElementException):
        logger.warning("⚠️  Không có hộp thông báo cần đóng hoặc đã tự đóng.")

    driver.find_element(By.XPATH, "//button[contains(text(), 'Tìm kiếm nâng cao')]").click()
    requested_notice_type = _resolve_search_notice_type_label(notice_type)
    active_notice_type = DEFAULT_SEARCH_NOTICE_TYPE
    if requested_notice_type != DEFAULT_SEARCH_NOTICE_TYPE:
        active_notice_type = select_search_notice_type(requested_notice_type)

    match_mode = resolve_match_mode(search_keyword)
    select_keyword_match_mode(match_mode)
    logger.info(f"🔎 Chế độ khớp từ khóa: {MATCH_MODE_LABELS[match_mode]} ({match_mode})")
    wait_dom_settled(timeout=15)

    exc_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Áp dụng cho tất cả các trường thông tin tìm kiếm']")))
    exc_input.clear()
    if EXC_KEY:
        exc_input.send_keys(EXC_KEY)
    
    if active_notice_type == DEFAULT_SEARCH_NOTICE_TYPE:
        keyword_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)']")))
    else:
        keyword_input = find_search_keyword_input(active_notice_type)
    keyword_input.clear()
    keyword_input.send_keys(search_keyword)
    # input()
    if active_notice_type == DEFAULT_SEARCH_NOTICE_TYPE:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@name='ck-investField' and @value='HH']"))).click()
    else:
        goods_checkbox = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@name='ck-investField' and @value='HH']")))
        if not goods_checkbox.is_selected():
            goods_checkbox.click()

    driver.find_element(By.XPATH, "//button[contains(text(), 'Tìm kiếm')]").click()
    time.sleep(1)
    apply_post_search_filters(active_notice_type)
    time.sleep(2)

    select_elem = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'Hiển thị')]/select")))
    time.sleep(0.5)
    select = Select(select_elem)
    select.select_by_value("50")
    time.sleep(2)
    return active_notice_type


def go_to_next_results_page():
    next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next:not([disabled])")))
    next_button.click()
    time.sleep(3)
    wait_dom_settled(timeout=15)
    return True


def get_backfill_cursor_key(notice_type, search_keyword):
    parts = [
        _resolve_search_notice_type_label(notice_type),
        str(search_keyword or "").strip(),
        resolve_match_mode(search_keyword),
        str(YEAR_FROM or ""),
        str(YEAR_TO or ""),
        str(EXC_KEY or "").strip(),
    ]
    return "||".join(parts)


def load_khlcnt_backfill_cursor():
    try:
        if not os.path.exists(KHLCNT_BACKFILL_CURSOR_FILE):
            return {}
        with open(KHLCNT_BACKFILL_CURSOR_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as error:
        logger.warning("⚠️ Không đọc được checkpoint KHLCNT backfill: %s", str(error)[:160])
        return {}


def save_khlcnt_backfill_cursor(data):
    try:
        os.makedirs(os.path.dirname(KHLCNT_BACKFILL_CURSOR_FILE), exist_ok=True)
        temp_path = f"{KHLCNT_BACKFILL_CURSOR_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temp_path, KHLCNT_BACKFILL_CURSOR_FILE)
    except Exception as error:
        logger.warning("⚠️ Không lưu được checkpoint KHLCNT backfill: %s", str(error)[:160])


def get_khlcnt_backfill_start_page(notice_type, search_keyword):
    if not KHLCNT_BACKFILL_CURSOR_ENABLED:
        return 1
    cursor = load_khlcnt_backfill_cursor()
    key = get_backfill_cursor_key(notice_type, search_keyword)
    entry = cursor.get(key) if isinstance(cursor.get(key), dict) else {}
    try:
        last_completed_page = int(entry.get("last_completed_page") or 0)
    except Exception:
        last_completed_page = 0
    return max(1, last_completed_page + 1)


def update_khlcnt_backfill_cursor(notice_type, search_keyword, completed_page):
    if not KHLCNT_BACKFILL_CURSOR_ENABLED:
        return
    cursor = load_khlcnt_backfill_cursor()
    key = get_backfill_cursor_key(notice_type, search_keyword)
    previous = cursor.get(key) if isinstance(cursor.get(key), dict) else {}
    previous_page = int(previous.get("last_completed_page") or 0) if previous else 0
    page_value = max(previous_page, int(completed_page or 0))
    cursor[key] = {
        "notice_type": _resolve_search_notice_type_label(notice_type),
        "keyword": search_keyword,
        "match_mode": resolve_match_mode(search_keyword),
        "year_from": YEAR_FROM,
        "year_to": YEAR_TO,
        "exclude_key": EXC_KEY or "",
        "last_completed_page": page_value,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_khlcnt_backfill_cursor(cursor)


def advance_results_to_page(target_page):
    target_page = max(1, int(target_page or 1))
    current_page = 1
    while current_page < target_page:
        if current_page == 1 or current_page % 10 == 0:
            logger.info("⏩ Đang nhảy checkpoint KHLCNT: trang %s -> %s", current_page, target_page)
        try:
            go_to_next_results_page()
        except TimeoutException:
            logger.info("⏭️ Không nhảy tới trang %s được vì đã hết trang tại khoảng trang %s.", target_page, current_page)
            return current_page
        current_page += 1
    return current_page


def prompt_after_max_pages(search_keyword: str, page: int, batch_limit: int):
    logger.info(
        f"⏸️ Đã crawl xong 1 lô {batch_limit} trang cho keyword '{search_keyword}' tới trang {page}. "
        "Bạn có thể giữ nguyên Chrome, chạy s2/s3 ở terminal khác, rồi quay lại tiếp tục."
    )
    logger.info(
        "Lệnh tiếp theo: nhập số trang muốn crawl thêm | [N] chuyển keyword tiếp theo | [Enter/Q] kết thúc"
    )
    while True:
        cmd = input("Crawl thêm bao nhiêu trang? [số/n/q]: ").strip().lower()
        if cmd in ("", "q", "quit", "exit"):
            return "quit", None
        if cmd in ("n", "next", "skip"):
            return "next", None
        try:
            extra_pages = int(cmd)
            if extra_pages > 0:
                return "continue", extra_pages
        except ValueError:
            pass
        print("⚠️ Giá trị không hợp lệ. Hãy nhập một số trang > 0, 'n' hoặc Enter để thoát.")


def is_khlcnt_notice_type(notice_type: str):
    return _resolve_search_notice_type_label(notice_type) == KHLCNT_SEARCH_NOTICE_TYPE


def split_notice_code(raw_code: str):
    raw = str(raw_code or "").strip()
    if not raw:
        return "", ""
    if "-" not in raw:
        return raw, ""
    code, version = raw.split("-", 1)
    return code.strip(), version.strip()


def get_notice_code_full(box):
    try:
        code_elem = wait_presence(box, By.CSS_SELECTOR, "p.content__body__left__item__infor__code", timeout=10)
        return code_elem.text.strip().split(":")[-1].strip()
    except Exception:
        return ""


def get_box_detail_url(box):
    try:
        return box.find_element(
            By.XPATH,
            ".//a[.//h5[contains(@class,'content__body__left__item__infor__contract__name')]]",
        ).get_attribute("href")
    except Exception:
        return ""


def package_name_contains_search_keyword(package_name, search_keyword):
    keyword = _normalize_keyword_value(search_keyword)
    name = _normalize_keyword_value(package_name)
    return True if not keyword else keyword in name


def classify_khlcnt_parent(plan_name):
    if is_luu_lai_theo_ten_goi_thau(plan_name):
        return "CHỌN", ""
    if is_loai_ten_goi_thau(plan_name):
        return "FILTERED_SKIP", "Tên KHLCNT bị loại theo từ khóa filter"
    return "CHỌN", ""


def classify_khlcnt_child_package(child_name, search_keyword):
    if is_luu_lai_theo_ten_goi_thau(child_name):
        return "CHỌN", ""
    if not package_name_contains_search_keyword(child_name, search_keyword):
        return "LOẠI", "Không chứa keyword crawl"
    if is_loai_ten_goi_thau(child_name):
        return "LOẠI", "Loại theo từ khóa tên gói thầu con"
    return "CHỌN", ""


def extract_tbmt_codes(data):
    ib_pattern = re.compile(r"\bIB\d{10}\b")
    found = []
    seen = set()

    def add_codes(value):
        for code in ib_pattern.findall(str(value or "")):
            if code not in seen:
                seen.add(code)
                found.append(code)

    def parse_json_string(value):
        text = str(value or "").strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def walk(value):
        parsed = parse_json_string(value) if isinstance(value, str) else None
        if parsed is not None:
            walk(parsed)
            return
        if isinstance(value, dict):
            result_dto = value.get("resultDTO")
            if isinstance(result_dto, dict):
                add_codes(result_dto.get("notifyNo"))
            add_codes(value.get("notifyNo"))
            link_notify_info = value.get("linkNotifyInfo")
            if isinstance(link_notify_info, dict):
                add_codes(link_notify_info.get("notifyNo"))
            for child_value in value.values():
                walk(child_value)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, str):
            add_codes(value)

    walk(data)
    return found


def parse_json_body(value):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        decoder = json.JSONDecoder()
        parsed, _idx = decoder.raw_decode(text)
        return parsed
    except Exception:
        return None


def walk_json_objects(data):
    parsed = parse_json_body(data) if isinstance(data, str) else data
    if isinstance(parsed, dict):
        yield parsed
        for value in parsed.values():
            yield from walk_json_objects(value)
    elif isinstance(parsed, list):
        for item in parsed:
            yield from walk_json_objects(item)


def build_kqlcnt_url(data: dict, base_url: str = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection") -> str:
    result = data.get("resultDTO") or {}
    input_result_id = result.get("id")
    notify_no = result.get("notifyNo")
    plan_no = data.get("planNo") or result.get("planNo")
    process_apply = data.get("processApply") or result.get("processApply")
    bid_mode = data.get("bidMode") or result.get("bidMode")
    bid_form = data.get("bidForm") or result.get("bidForm") or ""
    if not all([input_result_id, notify_no, plan_no, process_apply, bid_mode]):
        return ""
    params = {
        "p_p_id": "egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2",
        "p_p_lifecycle": "0",
        "p_p_state": "normal",
        "p_p_mode": "view",
        "_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render": "detail-v2",
        "type": "es-notify-contractor",
        "stepCode": "notify-contractor-step-4-kqlcnt",
        "id": "",
        "notifyId": "",
        "inputResultId": input_result_id,
        "bidOpenId": "",
        "processApply": process_apply,
        "bidMode": bid_mode,
        "notifyNo": notify_no,
        "planNo": plan_no,
        "step": "kqlcnt",
        "isInternet": "",
        "bidForm": bid_form,
    }
    return f"{base_url}?{urlencode(params)}"


def find_kqlcnt_result_payload(data):
    for obj in walk_json_objects(data):
        result = obj.get("resultDTO") if isinstance(obj, dict) else None
        if not isinstance(result, dict):
            continue
        notify_codes = extract_tbmt_codes(result.get("notifyNo"))
        if not notify_codes:
            continue
        return {
            "data": obj,
            "tbmt_codes": notify_codes,
            "tbmt_code": notify_codes[0],
            "so_qd": result.get("decisionNo") or "",
            "version": result.get("resultVersion") or result.get("notifyVersion") or "",
            "url_goi_thau_con": build_kqlcnt_url(obj),
        }
    return None


def clear_performance_logs():
    try:
        driver.get_log("performance")
    except Exception:
        pass


def extract_kqlcnt_result_from_performance_logs():
    try:
        entries = driver.get_log("performance")
    except Exception:
        return None
    fallback_payload = None
    for entry in entries:
        try:
            message = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        if message.get("method") != "Network.responseReceived":
            continue
        params = message.get("params", {})
        response = params.get("response", {})
        mime_type = str(response.get("mimeType") or "").lower()
        url = str(response.get("url") or "")
        if "muasamcong.mpi.gov.vn" not in url and not any(token in mime_type for token in ("json", "text", "javascript", "html")):
            continue
        request_id = params.get("requestId")
        if not request_id:
            continue
        try:
            body_payload = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            continue
        body = body_payload.get("body", "")
        if body_payload.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", errors="ignore")
            except Exception:
                continue
        result_payload = find_kqlcnt_result_payload(body)
        if not result_payload:
            continue
        if result_payload.get("url_goi_thau_con"):
            return result_payload
        fallback_payload = fallback_payload or result_payload
    return fallback_payload


def open_url_in_new_tab(url):
    main_window = driver.current_window_handle
    current_handles = set(driver.window_handles)
    driver.execute_script("window.open(arguments[0], '_blank');", url)
    WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - current_handles) == 1)
    new_window = list(set(driver.window_handles) - current_handles)[0]
    driver.switch_to.window(new_window)
    wait_document_ready_quick(timeout=5)
    return main_window


def close_current_tab_and_return(main_window):
    try:
        driver.close()
    finally:
        if main_window in driver.window_handles:
            driver.switch_to.window(main_window)
            wait_dom_settled(timeout=15)


def click_khlcnt_package_tab(timeout=8, ready_timeout=4):
    tab_xpath = "//ul[contains(@class,'nav-tabs')]//a[contains(normalize-space(),'Thông tin gói thầu')]"
    tab = wait_clickable(driver, By.XPATH, tab_xpath, timeout=timeout)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab)
    if not khlcnt_quick_click(tab):
        raise TimeoutException("Không click được tab Thông tin gói thầu KHLCNT")
    wait_document_ready_quick(timeout=ready_timeout)


def get_khlcnt_package_rows():
    click_khlcnt_package_tab()
    table_xpath = (
        "//table[.//th[contains(normalize-space(),'Tên gói thầu')] "
        "and .//th[contains(normalize-space(),'Số thông báo liên kết')]]"
    )
    table = wait_presence(driver, By.XPATH, table_xpath, timeout=8)
    rows = table.find_elements(By.XPATH, ".//tbody/tr")
    parsed_rows = []
    for row_position, row in enumerate(rows, start=1):
        cells = row.find_elements(By.XPATH, "./td")
        if len(cells) < 5:
            continue
        parsed_rows.append({
            "STT gói thầu con": cells[0].text.strip(),
            "Dòng gói thầu con": row_position,
            "Tên gói thầu con": cells[1].text.strip(),
            "Dự toán gói thầu sau KHLCNT": cells[2].text.strip(),
            "Giá gói thầu": cells[3].text.strip(),
            "Số thông báo liên kết": cells[4].text.strip(),
        })
    return parsed_rows


def build_khlcnt_plan_record(box, search_keyword, page, index):
    code_full = get_notice_code_full(box)
    code, version = split_notice_code(code_full)
    return {
        "Keyword crawl": search_keyword,
        "Trang kết quả": page,
        "STT KHLCNT": index,
        "Mã KHLCNT": code,
        "Mã KHLCNT đầy đủ": code_full,
        "Phiên bản KHLCNT": version,
        "Tên KHLCNT": get_ten_goi_thau(box),
        "Chủ đầu tư": get_chu_dau_tu(box),
        "URL chi tiết": get_box_detail_url(box),
    }


def build_khlcnt_child_metadata(plan_record, child_row, extra=None):
    metadata = {
        "Mã KHLCNT": plan_record.get("Mã KHLCNT", ""),
        "Mã KHLCNT đầy đủ": plan_record.get("Mã KHLCNT đầy đủ", ""),
        "Phiên bản KHLCNT": plan_record.get("Phiên bản KHLCNT", ""),
        "Tên KHLCNT": plan_record.get("Tên KHLCNT", ""),
    }
    if extra:
        metadata.update({key: value for key, value in extra.items() if value not in (None, "")})
    return metadata


def click_khlcnt_child_name_detail(child_row):
    row_index = int(child_row.get("Dòng gói thầu con") or 0)
    if row_index <= 0:
        raise ValueError("Thiếu Dòng gói thầu con để click detail.")
    table_xpath = (
        "//table[.//th[contains(normalize-space(),'Tên gói thầu')] "
        "and .//th[contains(normalize-space(),'Số thông báo liên kết')]]"
    )
    try:
        wait_presence(driver, By.XPATH, table_xpath, timeout=1)
    except TimeoutException:
        click_khlcnt_package_tab()
    row_xpath = f"({table_xpath}//tbody/tr)[{row_index}]//td[2]//a"
    child_link = wait_clickable(driver, By.XPATH, row_xpath, timeout=8)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", child_link)
    previous_url = driver.current_url
    clear_performance_logs()
    if not khlcnt_quick_click(child_link):
        raise TimeoutException("Không click được tên gói thầu con KHLCNT")
    wait_document_ready_quick(timeout=2)
    return previous_url


def return_to_khlcnt_detail(previous_url):
    try:
        if driver.current_url != previous_url:
            driver.get(previous_url)
            wait_document_ready_quick(timeout=1.5)
    except Exception:
        pass
    click_khlcnt_package_tab(timeout=3, ready_timeout=1)


def process_khlcnt_no_linked_child(plan_record, child_row, child_index, return_after=True):
    previous_url = click_khlcnt_child_name_detail(child_row)
    child_state = {"saved": False, "pending": False, "status": "NO_RESULT"}
    try:
        result_payload = wait_for_kqlcnt_result_payload(timeout=KHLCNT_RESULTDTO_TIMEOUT)
        tbmt_code = result_payload.get("tbmt_code") if result_payload else ""
        if not tbmt_code:
            logger.info("⏸️ KHLCNT %s | child %s: chưa có resultDTO", plan_record.get("Mã KHLCNT", ""), child_index)
            child_state.update({"pending": True, "status": "PENDING_NO_RESULTDTO"})
            return child_state

        saved_any = False
        pending_any = False
        base_kqlcnt_url = result_payload.get("url_goi_thau_con") or ""
        version_entries = get_khlcnt_result_version_entries()

        for version_index, planned_version in version_entries:
            version_payload = result_payload
            if version_index is not None:
                try:
                    version_payload = select_khlcnt_result_version(version_index) or {}
                except Exception as error:
                    logger.info(
                        "⏸️ KHLCNT %s | child %s version %s lỗi tạm: %s",
                        plan_record.get("Mã KHLCNT", ""),
                        child_index,
                        planned_version or version_index,
                        str(error)[:180],
                    )
                    pending_any = True
                    continue

            effective_tbmt = version_payload.get("tbmt_code") or tbmt_code
            kqlcnt_url = version_payload.get("url_goi_thau_con") or base_kqlcnt_url
            wait_dom_settled(timeout=4)
            info_snapshot = extract_additional_info()
            so_qd = (
                version_payload.get("so_qd")
                or get_info_card_value("Số quyết định phê duyệt")
                or info_snapshot.get("Số quyết định phê duyệt")
                or "N/A"
            )
            version = normalize_version_code(
                planned_version
                or version_payload.get("version")
                or get_current_ui_version()
                or "00"
            ) or "00"

            metadata = build_khlcnt_child_metadata(plan_record, child_row, {"URL gói thầu con": kqlcnt_url})
            if info_snapshot.get("Phân loại gói thầu"):
                metadata["Phân loại gói thầu"] = info_snapshot.get("Phân loại gói thầu")

            should_download, _download_reason = tracker.should_download_unit(effective_tbmt, so_qd, version)
            if not should_download:
                tracker.save_khlcnt_metadata_for_tbmt(effective_tbmt, metadata)
                continue

            try:
                target_card, target_card_name = find_target_item_card(timeout=4)
            except TimeoutException:
                logger.info("⏸️ KHLCNT %s -> %s / %s / v%s: chưa có card thuốc/hàng hóa", plan_record.get("Mã KHLCNT", ""), effective_tbmt, so_qd, version)
                pending_any = True
                continue

            winner_fact = extract_web_winner_fact()
            if winner_fact:
                tracker.save_web_winner_fact(effective_tbmt, so_qd, version, winner_fact, commit=True)

            result_file, card_name, collection_method = collect_khlcnt_result_file(
                effective_tbmt,
                so_qd,
                version,
                target_card=target_card,
                target_card_name=target_card_name,
            )
            if not result_file:
                logger.info("⏸️ KHLCNT %s -> %s / %s / v%s: không đọc được bảng dữ liệu", plan_record.get("Mã KHLCNT", ""), effective_tbmt, so_qd, version)
                pending_any = True
                continue

            action, saved_path = tracker.check_and_save(
                tbmt=effective_tbmt,
                qd_raw=so_qd,
                version=version,
                file_type="excel",
                temp_path=result_file,
                target_root_dir=BASE_DIR,
            )
            if action == "SKIPPED":
                try:
                    os.remove(result_file)
                except Exception:
                    pass
            elif action not in {"INSERT", "UPDATE", "SKIPPED_DUPLICATE", "NORMALIZED_DUPLICATE"}:
                logger.info("⏸️ KHLCNT %s -> %s / %s / v%s: không lưu được bảng (%s)", plan_record.get("Mã KHLCNT", ""), effective_tbmt, so_qd, version, action)
                pending_any = True
                continue

            if action in {"INSERT", "UPDATE"}:
                download_approval_pdf_if_present(effective_tbmt, so_qd, version, timeout=1)

            package_info = dict(info_snapshot)
            package_info.update({
                "Mã TBMT": effective_tbmt,
                "Cách thức tải về": f"KHLCNT_NO_LINKED_TBMT: {collection_method} ({card_name})",
                "File Path": saved_path,
            })
            tracker.save_metadata(effective_tbmt, so_qd, version, package_info)
            tracker.save_khlcnt_metadata_for_tbmt(effective_tbmt, metadata)
            logger.info("✅ KHLCNT %s -> %s / %s / v%s | %s", plan_record.get("Mã KHLCNT", ""), effective_tbmt, so_qd, version, action)
            saved_any = True

        child_state.update({
            "saved": saved_any,
            "pending": pending_any,
            "status": "PARTIAL_PENDING" if pending_any and saved_any else ("PENDING_NO_ARTIFACT" if pending_any else "DONE"),
        })
        return child_state
    except Exception as error:
        logger.info("⏸️ KHLCNT %s | child %s lỗi tạm: %s", plan_record.get("Mã KHLCNT", ""), child_index, str(error)[:220])
        child_state.update({"pending": True, "status": "PENDING_ERROR"})
        return child_state
    finally:
        if return_after:
            return_to_khlcnt_detail(previous_url)


def process_khlcnt_plan_detail(plan_record, search_keyword):
    plan_state = {
        "saved_count": 0,
        "valid_child_count": 0,
        "filtered_child_count": 0,
        "pending_child_count": 0,
        "linked_child_count": 0,
        "linked_missing_metadata_count": 0,
        "scan_complete": False,
    }
    parent_result, parent_reason = classify_khlcnt_parent(plan_record.get("Tên KHLCNT", ""))
    if parent_result == "FILTERED_SKIP":
        tracker.log_khlcnt_filtered_skip(plan_record, parent_reason)
        logger.info("🚩 KHLCNT %s: filtered (%s)", plan_record.get("Mã KHLCNT", ""), parent_reason)
        return plan_state
    detail_url = plan_record.get("URL chi tiết", "")
    if not detail_url:
        logger.info("⏭️ KHLCNT %s: không có URL detail", plan_record.get("Mã KHLCNT", ""))
        return plan_state
    saved_count = 0
    filtered_child_count = 0
    valid_child_count = 0
    pending_child_count = 0
    linked_child_count = 0
    linked_missing_metadata_count = 0
    main_window = open_url_in_new_tab(detail_url)
    try:
        try:
            child_rows = get_khlcnt_package_rows()
        except Exception as error:
            logger.info("⏭️ KHLCNT %s: không đọc được bảng child (%s)", plan_record.get("Mã KHLCNT", ""), str(error)[:180])
            return plan_state
        for child_index, child_row in enumerate(child_rows, start=1):
            child_result, child_reason = classify_khlcnt_child_package(child_row.get("Tên gói thầu con", ""), search_keyword)
            if child_result != "CHỌN":
                filtered_child_count += 1
                continue
            valid_child_count += 1
            linked_notice = _collapse_whitespace(child_row.get("Số thông báo liên kết"))
            if linked_notice:
                linked_child_count += 1
                skip_linked_pending, linked_pending_reason = tracker.should_skip_khlcnt_linked_pending(
                    plan_record,
                    linked_notice,
                    skip_days=KHLCNT_LINKED_PENDING_SKIP_DAYS,
                )
                if skip_linked_pending:
                    logger.info("⏩ KHLCNT %s -> %s: skip pending linked (%s)", plan_record.get("Mã KHLCNT", ""), linked_notice, linked_pending_reason)
                else:
                    tracker.log_khlcnt_linked_pending(plan_record, linked_notice, child_row)
                    logger.info("⏸️ KHLCNT %s -> %s: chờ crawl từ TBMT", plan_record.get("Mã KHLCNT", ""), linked_notice)
                pending_child_count += 1
                linked_missing_metadata_count += 1
                continue
            child_state = process_khlcnt_no_linked_child(
                plan_record,
                child_row,
                child_index,
                return_after=child_index < len(child_rows),
            )
            if child_state.get("saved"):
                saved_count += 1
            if child_state.get("pending"):
                pending_child_count += 1
        if valid_child_count == 0 and filtered_child_count > 0:
            tracker.log_khlcnt_filtered_skip(plan_record, "Không có gói thầu con nào hợp lệ sau filter")
            logger.info("🚩 KHLCNT %s: filtered toàn bộ %s child", plan_record.get("Mã KHLCNT", ""), filtered_child_count)
        plan_state.update({
            "saved_count": saved_count,
            "valid_child_count": valid_child_count,
            "filtered_child_count": filtered_child_count,
            "pending_child_count": pending_child_count,
            "linked_child_count": linked_child_count,
            "linked_missing_metadata_count": linked_missing_metadata_count,
            "scan_complete": pending_child_count == 0 and valid_child_count > 0,
        })
        if pending_child_count:
            logger.info(
                "⏸️ KHLCNT %s: pending %s/%s child",
                plan_record.get("Mã KHLCNT", ""),
                pending_child_count,
                valid_child_count,
            )
        return plan_state
    finally:
        close_current_tab_and_return(main_window)


def crawl_khlcnt_current_results(
    search_keyword: str,
    start_page: int = 1,
    page_limit: int | None = None,
    notice_type: str = KHLCNT_SEARCH_NOTICE_TYPE,
):
    page = start_page
    effective_page_limit = page_limit if page_limit is not None else MAX_PAGES
    pages_processed_in_batch = 0
    count_processed = 0
    while True:
        logger.info(f"\nKHLCNT page {page} | keyword: {search_keyword}")
        boxes = get_box_elements()
        total_boxes = len(boxes)
        logger.info(f"KHLCNT page {page}: {total_boxes} kế hoạch")
        for index, box in enumerate(boxes, start=1):
            plan_record = build_khlcnt_plan_record(box, search_keyword, page, index)
            ma_khlcnt = plan_record.get("Mã KHLCNT", "")
            if not FORCE_FULL_SCAN:
                should_skip, skip_reason = tracker.should_skip_khlcnt_plan(ma_khlcnt, skip_days=SKIP_DAYS)
                if should_skip:
                    logger.info("=" * 30)
                    logger.info("⏩ KHLCNT %s: skip (%s)", ma_khlcnt, skip_reason)
                    continue

            logger.info("=" * 30)
            parent_result, parent_reason = classify_khlcnt_parent(plan_record.get("Tên KHLCNT", ""))
            if parent_result == "FILTERED_SKIP":
                tracker.log_khlcnt_filtered_skip(plan_record, parent_reason)
                logger.info("🚩 KHLCNT %s: filtered tên", ma_khlcnt)
                continue
            logger.info("📄 KHLCNT %s (%s/%s): %s", ma_khlcnt, index, total_boxes, plan_record.get("Tên KHLCNT", ""))
            try:
                plan_state = process_khlcnt_plan_detail(plan_record, search_keyword)
                processed_count = plan_state.get("saved_count", 0)
                count_processed += processed_count
                if plan_state.get("scan_complete"):
                    checked_reason = (
                        f"Đã đọc KHLCNT: saved={processed_count}, "
                        f"valid={plan_state.get('valid_child_count', 0)}, "
                        f"linked={plan_state.get('linked_child_count', 0)}"
                    )
                    tracker.mark_khlcnt_checked(plan_record, checked_reason)
            except Exception as error:
                logger.info("⏸️ KHLCNT %s: lỗi tạm (%s)", ma_khlcnt, str(error)[:180])
                wait_dom_settled(timeout=15)
        pages_processed_in_batch += 1
        update_khlcnt_backfill_cursor(notice_type, search_keyword, page)
        if effective_page_limit and pages_processed_in_batch >= effective_page_limit:
            logger.info(f"KHLCNT đạt MAX_PAGES={effective_page_limit}, dừng tại page {page}.")
            return count_processed, True, page
        try:
            go_to_next_results_page()
            page += 1
        except TimeoutException:
            logger.info(f"Hết trang KHLCNT cho keyword '{search_keyword}'.")
            break
    update_khlcnt_backfill_cursor(notice_type, search_keyword, page)
    return count_processed, False, page


def crawl_current_results(search_keyword: str, start_page: int = 1, page_limit: int | None = None):
    page = start_page
    effective_page_limit = page_limit if page_limit is not None else MAX_PAGES
    pages_processed_in_batch = 0
    consecutive_skipped = 0
    count_processed = 0

    while True:
        logger.info(f"\nTrang {page} | Keyword: {search_keyword}")
        boxes = get_box_elements()
        total_boxes = len(boxes)
        logger.info(f"Số box trên trang {page}: {total_boxes}")

        for i in range(total_boxes):
            ma_tbmt = get_ma_tbmt(boxes[i])
            if ma_tbmt in ABORTED_TBMTS_THIS_RUN:
                logger.info(f"⏩ [RUN SKIP] {ma_tbmt} đã TEMP_ABORT trong run hiện tại, bỏ qua.")
                logger.info("=" * 30)
                continue
            if not FORCE_FULL_SCAN and tracker.should_skip_level_1(ma_tbmt, skip_days=SKIP_DAYS):
                logger.info(f"⏩ [MAIN SKIP] Mã TBMT {ma_tbmt} mới check gần đây (< {SKIP_DAYS} ngày), bỏ qua.")
                logger.info("=" * 30)
                continue

            try:
                has_download = try_process_box(i, page, boxes, ma_tbmt=ma_tbmt)
                if not has_download:
                    consecutive_skipped += 1
                    if consecutive_skipped >= MAX_TRY:
                        logger.warning(f"⚠️ Bỏ qua {MAX_TRY} box liên tiếp, dừng keyword '{search_keyword}'.")
                        logger.info(f"Tổng số box đã xử lý cho keyword '{search_keyword}': {count_processed}")
                        return count_processed, False, page
                else:
                    consecutive_skipped = 0
                    count_processed += 1

            except TempCrawlAbort as e:
                register_temp_abort(e.tbmt or ma_tbmt, e.reason)
                consecutive_skipped = 0
                wait_dom_settled(timeout=15)
                continue
            except Exception as e:
                logger.error(f"❌ Lỗi khi xử lý box {i+1} trang {page} cho keyword '{search_keyword}': {e}")
                consecutive_skipped += 1
                if consecutive_skipped >= MAX_TRY:
                    logger.warning(f"⚠️  Bỏ qua {MAX_TRY} box liên tiếp do lỗi, dừng keyword '{search_keyword}'.")
                    logger.info(f"Tổng số box đã xử lý cho keyword '{search_keyword}': {count_processed}")
                    return count_processed, False, page
                wait_dom_settled(timeout=15)
                continue

        pages_processed_in_batch += 1

        if effective_page_limit and pages_processed_in_batch >= effective_page_limit:
            logger.info(
                f"Đã đạt số trang tối đa cho lô crawl hiện tại: {effective_page_limit}, "
                f"tạm dừng keyword '{search_keyword}' tại trang {page}."
            )
            logger.info(f"Tổng số box đã xử lý cho keyword '{search_keyword}': {count_processed}")
            return count_processed, True, page

        try:
            go_to_next_results_page()
            page += 1

        except TimeoutException:
            logger.info(f"Hết trang hoặc không tìm thấy nút trang tiếp theo cho keyword '{search_keyword}', dừng.")
            break

    return count_processed, False, page


# ================== MAIN ==================
def main():
    global CURRENT_RUN_ID
    start_time = datetime.now()
    total_processed = 0

    if not SEARCH_KEYWORDS:
        raise ValueError("❌ Thiếu KEY hoặc KEY_BATCHES trong file .env")

    init_tracker()
    ABORTED_TBMTS_THIS_RUN.clear()
    TEMP_ABORT_SUMMARY.clear()
    CURRENT_RUN_ID = start_run_history(start_time)

    try:
        total_batches = len(SEARCH_KEYWORDS) * len(SEARCH_NOTICE_TYPE_LIST)
        batch_idx = 0
        for notice_type in SEARCH_NOTICE_TYPE_LIST:
            for search_keyword in SEARCH_KEYWORDS:
                batch_idx += 1
                logger.info("=" * 60)
                logger.info(f"Batch {batch_idx}/{total_batches} - Loại: {notice_type} - Keyword: {search_keyword}")
                logger.info("=" * 60)
                init_runtime(enable_network_capture=is_khlcnt_notice_type(notice_type))
                active_notice_type = prepare_search_form(search_keyword, notice_type=notice_type)
                current_page = 1
                current_batch_limit = MAX_PAGES
                if is_khlcnt_notice_type(active_notice_type) and KHLCNT_BACKFILL_CURSOR_ENABLED:
                    current_page = get_khlcnt_backfill_start_page(active_notice_type, search_keyword)
                    if current_page > 1:
                        logger.info(
                            "⏩ KHLCNT backfill checkpoint: bỏ qua tới trang %s cho keyword '%s'",
                            current_page,
                            search_keyword,
                        )
                        current_page = advance_results_to_page(current_page)

                while True:
                    if is_khlcnt_notice_type(active_notice_type):
                        processed_count, hit_max_pages, current_page = crawl_khlcnt_current_results(
                            search_keyword,
                            start_page=current_page,
                            page_limit=current_batch_limit,
                            notice_type=active_notice_type,
                        )
                    else:
                        processed_count, hit_max_pages, current_page = crawl_current_results(
                            search_keyword,
                            start_page=current_page,
                            page_limit=current_batch_limit,
                        )
                    total_processed += processed_count

                    if not hit_max_pages:
                        break

                    action, next_batch_limit = prompt_after_max_pages(
                        f"{active_notice_type} | {search_keyword}",
                        current_page,
                        current_batch_limit,
                    )
                    if action == "quit":
                        return
                    if action == "next":
                        break

                    try:
                        go_to_next_results_page()
                        current_page += 1
                        current_batch_limit = next_batch_limit
                    except TimeoutException:
                        logger.info(f"Không còn trang tiếp theo cho loại '{active_notice_type}', keyword '{search_keyword}', chuyển batch khác.")
                        break


    finally:
        end_time = datetime.now()
        append_run_history(start_time, end_time, total_processed)
        print_temp_abort_summary()
        
        gc.collect()
        if driver is not None:
            wait_dom_settled(timeout=15)
        logger.info("-" * 50)
        logger.info("Giữ Chrome mở. Nhấn Enter để kết thúc script...")
        input()
        shutdown_runtime()


if __name__ == "__main__":
    main()
