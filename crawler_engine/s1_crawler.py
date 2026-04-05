# -*- coding: utf-8 -*-
import os
import time
import shutil
import re
from datetime import datetime
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


def _get_env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


# Cấu hình logic skip
SKIP_DAYS = _get_env_int("SKIP_DAYS", 7)
FORCE_FULL_SCAN = _get_env_bool("FORCE_FULL_SCAN", False)

# Cấu hình từ khóa
KEY = os.getenv("KEY")
KEY_BATCHES = os.getenv("KEY_BATCHES")
EXC_KEY = os.getenv("EXC_KEY")
SEARCH_MATCH_MODE = (os.getenv("SEARCH_MATCH_MODE") or "exact").strip()
SEARCH_MATCH_MODE_MAP = os.getenv("SEARCH_MATCH_MODE_MAP")
YEAR_FROM = _get_env_int("YEAR_FROM")
YEAR_TO = _get_env_int("YEAR_TO")
MAX_PAGES = _get_env_int("MAX_PAGES")
MAX_TRY = _get_env_int("MAX_TRY", 7)

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

    def check_and_save(self, tbmt, qd_raw, version, file_type, temp_path, target_root_dir, num_cols=0):
        ver_chk = version if version else "00"
        ver_chk_key = _version_key(ver_chk)

        orig_name = os.path.basename(temp_path)
        safe_tbmt = "".join(c for c in tbmt if c.isalnum() or c in ".-_")
        safe_qd_raw = sanitize_filename_part(qd_raw) if qd_raw else "UNKNOWN_QD"
        new_filename = f"{safe_tbmt}_v{ver_chk}_{safe_qd_raw}_{orig_name}"

        self._cleanup_existing_pdf_duplicates(tbmt, qd_raw, ver_chk)

        self._safe_execute("""
            SELECT 1 FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s AND version=%s
        """, (tbmt, qd_raw, file_type, ver_chk))
        if self.cursor.fetchone():
            return "SKIPPED", None

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
            SELECT version, file_path FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s
        """, (tbmt, qd_raw, file_type))
        existing_rows = self.cursor.fetchall() or []
        old_row = max(existing_rows, key=lambda row: _version_key(row["version"])) if existing_rows else None

        if old_row:
            old_ver = old_row["version"]
            old_path = old_row["file_path"]
            old_ver_key = _version_key(old_ver)

            if ver_chk_key > old_ver_key:
                logger.info(f"🔄 Phát hiện bản mới v{ver_chk} (cũ v{old_ver}). Tiến hành archive bản cũ...")
                self._archive_existing_file(tbmt, qd_raw, file_type, old_ver, old_path, archive_dir)
                final_path = os.path.join(latest_dir, new_filename)
            else:
                logger.warning(f"⚠️  Bản hiện tại v{ver_chk} <= bản mới nhất v{old_ver}")
                final_path = os.path.join(archive_dir, new_filename)
        else:
            final_path = os.path.join(latest_dir, new_filename)

        try:
            shutil.move(temp_path, final_path)
        except Exception as e:
            logger.error(f"❌ Error moving file: {e}")
            return "ERROR", None

        self._safe_execute("""
            INSERT INTO packages (ma_tbmt, so_qd, version, file_type, file_path, num_cols, crawled_at, status, is_latest)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'DONE', 0)
        """, (tbmt, qd_raw, ver_chk, file_type, final_path, num_cols, self._now_str()))

        self._safe_execute("""
            UPDATE packages SET is_latest = 0
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s
        """, (tbmt, qd_raw, file_type))

        self._safe_execute("""
            SELECT version FROM packages
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s
        """, (tbmt, qd_raw, file_type))
        latest_versions = self.cursor.fetchall() or []
        latest_ver = max((row["version"] for row in latest_versions), key=_version_key) if latest_versions else ver_chk

        self._safe_execute("""
            UPDATE packages SET is_latest = 1
            WHERE ma_tbmt=%s AND so_qd=%s AND file_type=%s AND version=%s
        """, (tbmt, qd_raw, file_type, latest_ver))

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
            'gia_goi_thau': self._nullify(info_dict.get('Giá gói thầu')),
            'gia_du_toan': self._nullify(info_dict.get('Giá dự toán')),
            'ngay_phe_duyet': self._nullify(info_dict.get('Ngày phê duyệt')),
            'trang_thai_phe_duyet': self._nullify(info_dict.get('Trạng thái phê duyệt')),
            'co_quan_phe_duyet': self._nullify(info_dict.get('Cơ quan phê duyệt')),
            'loai_hop_dong': self._nullify(info_dict.get('Loại hợp đồng')),
            'thoi_gian_thuc_hien': self._nullify(info_dict.get('Thời gian thực hiện gói thầu')),
            'ket_qua_dau_thau': self._nullify(info_dict.get('Kết quả đấu thầu')),
            'dia_diem': self._nullify(info_dict.get('Địa điểm')),
            'cach_thuc_tai_ve': self._nullify(info_dict.get('Cách thức tải về')),
        }

        self._safe_execute("""
            INSERT INTO package_metadata (
                ma_tbmt, so_qd, version, ngay_dang_tai, trang_thai_dang_tai_kq, chu_dau_tu,
                ten_goi_thau, linh_vuc, hinh_thuc_lcnt, phuong_thuc_lcnt, dau_thau_qua_mang,
                trong_nuoc_quoc_te, gia_goi_thau, gia_du_toan, ngay_phe_duyet, trang_thai_phe_duyet,
                co_quan_phe_duyet, loai_hop_dong, thoi_gian_thuc_hien, ket_qua_dau_thau,
                dia_diem, cach_thuc_tai_ve, updated_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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
                trang_thai_phe_duyet = COALESCE(EXCLUDED.trang_thai_phe_duyet, package_metadata.trang_thai_phe_duyet),
                co_quan_phe_duyet = COALESCE(EXCLUDED.co_quan_phe_duyet, package_metadata.co_quan_phe_duyet),
                loai_hop_dong = COALESCE(EXCLUDED.loai_hop_dong, package_metadata.loai_hop_dong),
                thoi_gian_thuc_hien = COALESCE(EXCLUDED.thoi_gian_thuc_hien, package_metadata.thoi_gian_thuc_hien),
                ket_qua_dau_thau = COALESCE(EXCLUDED.ket_qua_dau_thau, package_metadata.ket_qua_dau_thau),
                dia_diem = COALESCE(EXCLUDED.dia_diem, package_metadata.dia_diem),
                cach_thuc_tai_ve = COALESCE(EXCLUDED.cach_thuc_tai_ve, package_metadata.cach_thuc_tai_ve),
                updated_at = EXCLUDED.updated_at
        """, (
            tbmt, qd_raw, ver_save,
            val_map['ngay_dang_tai'], val_map['trang_thai_dang_tai_kq'], val_map['chu_dau_tu'],
            val_map['ten_goi_thau'], val_map['linh_vuc'], val_map['hinh_thuc_lcnt'],
            val_map['phuong_thuc_lcnt'], val_map['dau_thau_qua_mang'], val_map['trong_nuoc_quoc_te'],
            val_map['gia_goi_thau'], val_map['gia_du_toan'], val_map['ngay_phe_duyet'],
            val_map['trang_thai_phe_duyet'], val_map['co_quan_phe_duyet'], val_map['loai_hop_dong'],
            val_map['thoi_gian_thuc_hien'], val_map['ket_qua_dau_thau'], val_map['dia_diem'],
            val_map['cach_thuc_tai_ve'], self._now_str()
        ))
        self.conn.commit()


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

        # 3. Xem lần chạy cuối là khi nào
        self._safe_execute("""
            SELECT MAX(crawled_at) as last_date FROM packages 
            WHERE ma_tbmt=%s AND status='DONE'
        """, (tbmt,))
        row = self.cursor.fetchone()
        last_date_str = row['last_date'] if row else None
        if not last_date_str: return False
        
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


def init_runtime():
    global driver, wait, tracker
    if tracker is None:
        tracker = CrawlerDB()
    if driver is None:
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as first_error:
            if USE_LOCAL_CHROMEDRIVER and CHROMEDRIVER_PATH:
                try:
                    logger.warning(
                        f"⚠️ Selenium Manager không khởi tạo được Chrome ({first_error}). "
                        "Thử fallback sang CHROMEDRIVER_PATH..."
                    )
                    service = Service(executable_path=CHROMEDRIVER_PATH, log_output=os.devnull)
                    driver = webdriver.Chrome(service=service, options=options)
                except SessionNotCreatedException as e:
                    logger.error(
                        f"❌ ChromeDriver tại CHROMEDRIVER_PATH không khớp version Chrome: {e.msg}"
                    )
                    raise
            else:
                raise
        wait = WebDriverWait(driver, 20)


def shutdown_runtime():
    global driver, wait, tracker
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        wait = None
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
    "máy chiết xơ", "nội độc tố", "dung môi", "chất chuẩn", "chuẩn hóa", "kiểm tra", "độ hòa tan", "bình phun thuốc"
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
]

tu_khoa_luu_lai = [
    "generic", "biệt dược gốc", "bdg", 
    "thực phẩm chức năng", "thực phẩm bảo vệ sức khỏe", "thực phẩm dinh dưỡng",
    "mỹ phẩm", "vật tư y tế", "thiết bị y tế", "khám chữa bệnh"
]

def _normalize_keyword_value(value):
    return str(value or "").strip().lower()


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
    ten_thap = ten_goi_thau.lower()
    return any(re.search(rf'\b{re.escape(kw)}\b', ten_thap) for kw in tu_khoa_luu_lai)

def is_loai_chu_dau_tu(ten_chu_dau_tu):
    ten_thap = ten_chu_dau_tu.lower()
    for keyword, exclude_list in loai_chu_dau_tu:
        if re.search(rf'\b{re.escape(keyword)}\b', ten_thap):
            if any(re.search(rf'\b{re.escape(ex)}\b', ten_thap) for ex in exclude_list):
                continue
            else:
                return True
    return False

def is_loai_ten_goi_thau(ten_goi_thau):
    ten_thap = ten_goi_thau.lower()
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
def extract_additional_info():
    info = {}
    
    # Danh sách các trường cần lấy (whitelist)
    target_fields = [
        "Mã TBMT", "Ngày đăng tải", "Trạng thái đăng tải KQ", "Trạng thái KQLCNT",
        "Chủ đầu tư", "Tên gói thầu", "Hình thức LCNT", "Hình thức lựa chọn nhà thầu",
        "Lĩnh vực", "Phương thức lựa chọn nhà thầu", "Đấu thầu qua mạng",
        "Giá gói thầu", "Giá dự toán", "Trong nước/ Quốc tế",
        "Ngày phê duyệt", "Trạng thái phê duyệt", "Cơ quan phê duyệt",
        "Số quyết định phê duyệt", "Loại hợp đồng", "Thời gian thực hiện gói thầu",
        "Kết quả đấu thầu"
    ]
    
    try:
        info_divs = driver.find_elements(By.CSS_SELECTOR, "div.infomation__content")
        for div in info_divs:
            try:
                title_elem = div.find_element(By.CSS_SELECTOR, "div.infomation__content__title")
            except Exception:
                continue
                
            value_divs = div.find_elements(By.CSS_SELECTOR, "div")
            title = title_elem.text.strip()
            
            # Xử lý trường hợp có dấu cách thừa hoặc khác biệt nhỏ
            clean_title = title.replace("  ", " ") 
            
            value = ""
            if len(value_divs) > 1:
                value = value_divs[1].text.strip()
            
            # Chỉ lấy các trường nằm trong danh sách yêu cầu
            # Dùng any để match linh hoạt (ví dụ "Loại hợp đồng " vs "Loại hợp đồng")
            if any(t in title for t in target_fields):
                 info[title] = value
                 
    except Exception as e:
        logger.error(f"❌ Lỗi lấy thông tin bổ sung: {e}")
    return info


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

def get_num_cols_hang_hoa():
    """
    Đếm số cột ở bảng 'Danh sách hàng hóa'.
    Nếu không tìm được thead/th thì trả về 0.
    """
    try:
        if has_legacy_lot_selection_card():
            ensure_select_lot_with_winner()
        table = wait_presence(
            driver,
            By.XPATH,
            "//div[contains(@class,'card-header') and ("
            "contains(normalize-space(),'Danh sách hàng hóa') or "
            "contains(normalize-space(),'Danh mục hàng hóa') or "
            "contains(normalize-space(),'Danh sách thuốc') or "
            "contains(normalize-space(),'Danh mục thuốc'))]"
            "/following-sibling::div//table",
            timeout=10
        )
        header_row = WebDriverWait(table, 10).until(
            EC.presence_of_element_located((By.XPATH, ".//thead//tr"))
        )
        ths = header_row.find_elements(By.TAG_NAME, "th")
        return len(ths)
    except TimeoutException:
        return 0
    except Exception:
        return 0


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

def wait_dom_settled(timeout=15):
    # 1) overlay gone
    wait_overlay_gone(timeout=timeout)
    # 2) document ready
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def wait_until_not_loading(driver, timeout=20):
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
            wait_overlay_gone(timeout=20)
            elem.location_once_scrolled_into_view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            elem.click()
            return True
        except Exception as e:
            logger.error(f"❌ safe_click attempt {attempt+1}/{max_retry} lỗi: {e}")
            try:
                wait_overlay_gone(timeout=10)
                driver.execute_script("arguments[0].click();", elem)
                return True
            except Exception as e_js:
                logger.error(f"❌ JS click attempt {attempt+1}/{max_retry} lỗi: {e_js}")
                wait_dom_settled(timeout=15)
                continue
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
    Select(select_elem).select_by_index(target_index)
    wait_dom_settled(timeout=timeout)

    WebDriverWait(driver, timeout).until(
        lambda d: Select(select_elem).options.index(Select(select_elem).first_selected_option) == target_index
    )

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
    num_cols,
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

    if has_legacy_lot_selection_card():
        ensure_select_lot_with_winner()

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
            return False

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
            target_root_dir=BASE_DIR,
            num_cols=num_cols
        )

        if action == "SKIPPED":
            try: os.remove(actual_file)
            except: pass
            logger.info(f"⏩ Skipped old version: {ma_tbmt} v{version_code}")
            return True # Vẫn return True để báo là process thành công (chỉ là không lưu thôi)
        elif action == "SKIPPED_DUPLICATE":
            logger.info(f"↪️ Bỏ qua file PDF trùng nghĩa cho {ma_tbmt} / {suffix_qd} / v{version_code}")
            return True
        elif action == "NORMALIZED_DUPLICATE":
            logger.info(f"🔁 Đã chuẩn hóa file PDF trùng nghĩa về 1 record packages cho {ma_tbmt} / {suffix_qd} / v{version_code}")
            any_file_downloaded = True
            return any_file_downloaded
            
        elif action in ["INSERT", "UPDATE"]:
            # logger.info(f"✅ [{action}] Saved: {os.path.basename(saved_path)}")
            logger.info(f"✅ [{action}] Đã lưu file đính kèm")
            any_file_downloaded = True
            
            # LƯU METADATA NGAY LẬP TỨC
            info_dict = info_snapshot if info_snapshot is not None else extract_additional_info()

            if ngay_dang_tai_specific:
                info_dict["Ngày đăng tải"] = ngay_dang_tai_specific

            # CẬP NHẬT TRẠNG THÁI RIÊNG
            if trang_thai_specific:     # Ghi đè vào cả 2 key có thể dùng để map vào DB
                info_dict["Trạng thái đăng tải KQ"] = trang_thai_specific
                info_dict["Trạng thái KQLCNT"] = trang_thai_specific
                
            info_dict.update({
                "Mã TBMT": ma_tbmt,
                "Địa điểm": dia_diem,
                "Cách thức tải về": collection_method,
                "File Path": saved_path
            })
            tracker.save_metadata(ma_tbmt, suffix_qd, version_code, info_dict)
            
        else: # ERROR
            raise TempCrawlAbort(ma_tbmt, f"Hệ thống không lưu được file tải về ở box {box_index}")
            
    else:
        raise TempCrawlAbort(ma_tbmt, f"Timeout tải file ({collection_method}) ở box {box_index}")

    return any_file_downloaded


# ========== LOG PDF-ONLY ==========
def log_pdf_only_if_needed(any_downloaded, any_excel_for_box, ma_tbmt, so_qd, ver_code, dia_diem, dest_qd, info_snapshot=None):
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
                target_root_dir=BASE_DIR,
                num_cols=0
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
            raise TempCrawlAbort(ma_tbmt, f"Timeout tải PDF QĐ: {qd_text_raw}")
            
    except Exception as e:
        if isinstance(e, TempCrawlAbort):
            raise
        logger.error(f"❌ Lỗi tải PDF: {e}")
        raise TempCrawlAbort(ma_tbmt, f"Lỗi tải PDF QĐ {qd_text_raw}: {str(e)[:300]}")


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

def _process_one_qd_flow(ma_tbmt, box_index, dia_diem, qd_text_raw, qd_element_pdf, version_code, num_cols, 
                         ngay_dang_tai_specific=None, trang_thai_specific=None, info_snapshot=None):
    """Helper xử lý 1 combo: 1 QĐ + 1 bộ file (PDF + Excel/Attach)"""
    any_dl = False
    any_excel = False
    dest_qd = None
    safe_ver = version_code if version_code else "00"

    # 1. Tải PDF QĐ (nếu có element)
    if qd_element_pdf:
        ok, path = download_single_qd_pdf(
            ma_tbmt=ma_tbmt,
            qd_element=qd_element_pdf,
            qd_text_raw=qd_text_raw,
            version_code=safe_ver
        )
        if ok:
            any_dl = True
            dest_qd = path

    # 2. Tải Excel/Attach
    # suffix_qd dùng cho tên file Excel chính là số QĐ raw
    if download_excel_or_attach_for_current_decision(
        num_cols, ma_tbmt, box_index, dia_diem, suffix_qd=qd_text_raw, version_code=safe_ver, 
        ngay_dang_tai_specific=ngay_dang_tai_specific, trang_thai_specific=trang_thai_specific,
        info_snapshot=info_snapshot
    ):
        any_dl = True
        any_excel = True

    return any_dl, any_excel, dest_qd


def finalize_one_qd_result(ma_tbmt, box_index, dia_diem, so_qd, ver_code, any_dl, any_excel, dest_qd, info_snapshot=None):
    log_pdf_only_if_needed(any_dl, any_excel, ma_tbmt, so_qd, ver_code, dia_diem, dest_qd, info_snapshot=info_snapshot)
    if not any_excel:
        tracker.log_event(
            tbmt=ma_tbmt,
            qd_raw=so_qd,
            version=ver_code,
            action_type="NO_ATTACHMENTS",
            reason=f"Không có Excel/Attach box {box_index}"
        )
        logger.warning(f"⚠️ Đã log NO_ATTACHMENTS cho {ma_tbmt} / {so_qd} / v{ver_code}")

def handle_quyet_dinh_phe_duyet_all(num_cols, ma_tbmt, box_index, box_name_text, ngay_phe_duyet, dia_diem):
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

                    loop_range = range(len(opts)) if len(opts) > 1 else [None]
                    
                    for i_ver in loop_range:
                        ver_code = "00"
                        
                        # --- LOGIC ĐỔI VERSION ---
                        if i_ver is not None:
                            # Phải find lại select vì DOM có thể đã đổi sau lần loop trước
                            current_row = qd_table.find_elements(By.XPATH, ".//tbody/tr")[i_row]
                            ver_select = current_row.find_element(By.CSS_SELECTOR, "select.form-select")
                            
                            ver_code = normalize_version_code(Select(ver_select).options[i_ver].text.strip())
                            logger.info(f"👉 Dòng {i_row+1} - Version {ver_code}")
                            
                            wait_version_applied(ver_select, i_ver)
                            wait_dom_settled(timeout=2)

                        elif len(opts) == 1:
                            try:
                                ver_code = normalize_version_code(opts[0].text.strip())
                            except:
                                ver_code = "00"

                        # --- CLICK RADIO ĐỂ LOAD DETAIL ---
                        # Phải find lại row và radio
                        current_row = qd_table.find_elements(By.XPATH, ".//tbody/tr")[i_row]
                        try:
                            radio = current_row.find_element(By.XPATH, ".//input[@type='radio']")
                            driver.execute_script("arguments[0].click();", radio)
                            wait_dom_settled(timeout=3) # Đợi card detail load
                            
                        except Exception as e:
                            logger.warning(f"⚠️ Lỗi click radio: {e}")

                        info_snapshot = extract_additional_info()

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
                        ok, ok_excel, path = _process_one_qd_flow(
                            ma_tbmt, box_index, dia_diem,
                            qd_text_raw=so_qd, 
                            qd_element_pdf=pdf_tag, 
                            version_code=ver_code, 
                            num_cols=num_cols,
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
                            info_snapshot=info_snapshot
                        )
                        
                        if ok: any_downloaded = True
                        if ok_excel: any_excel_for_box = True
                        if path: last_qd_path = path

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

        info_snapshot_base = extract_additional_info()
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
                info_snapshot = extract_additional_info()
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

            ok, ok_excel, path = _process_one_qd_flow(
                ma_tbmt, box_index, dia_diem,
                qd_text_raw=so_qd, qd_element_pdf=pdf_tag, version_code=ver_code, num_cols=num_cols, 
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
                info_snapshot=info_snapshot
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

    try:
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

        # 2) Lấy số cột bảng (Danh sách hàng hóa)
        try:
            num_cols = get_num_cols_hang_hoa()
        except UnexpectedAlertPresentException:
            logger.warning(f"⚠️ Box {index}: alert trong lúc lấy số cột, xử lý alert rồi lấy lại.")
            handle_connection_alert_once(timeout=20)
            wait_until_not_loading(driver, 10)
            num_cols = get_num_cols_hang_hoa()

        logger.info(f"Box {index}: {ma_tbmt} (Số cột bảng = {num_cols})")

        # 3) Xử lý quyết định (đơn/đa)
        try:
            has_any_download = handle_quyet_dinh_phe_duyet_all(
                num_cols, ma_tbmt, index, box_name_text, ngay_phe_duyet, dia_diem
            )
        except UnexpectedAlertPresentException:
            logger.warning(f"⚠️ Box {index}: alert trong khi xử lý QĐ, xử lý alert rồi thử lại 1 lần.")
            handle_connection_alert_once(timeout=20)
            wait_until_not_loading(driver, 10)
            try:
                has_any_download = handle_quyet_dinh_phe_duyet_all(
                    num_cols, ma_tbmt, index, box_name_text, ngay_phe_duyet, dia_diem
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
            SET crawled_at=%s, status='DONE'
            WHERE ma_tbmt=%s AND is_latest=1
        """, (tracker._now_str(), ma_tbmt))
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


def prepare_search_form(search_keyword: str):
    driver.get("https://muasamcong.mpi.gov.vn/web/guest/home")
    try:
        close_button = wait.until(EC.element_to_be_clickable((By.ID, "popup-close")))
        close_button.click()
        logger.info("✅ Đã đóng hộp thông báo quan trọng.")
    except (TimeoutException, NoSuchElementException):
        logger.warning("⚠️  Không có hộp thông báo cần đóng hoặc đã tự đóng.")

    driver.find_element(By.XPATH, "//button[contains(text(), 'Tìm kiếm nâng cao')]").click()
    match_mode = resolve_match_mode(search_keyword)
    select_keyword_match_mode(match_mode)
    logger.info(f"🔎 Chế độ khớp từ khóa: {MATCH_MODE_LABELS[match_mode]} ({match_mode})")
    wait_dom_settled(timeout=15)

    exc_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Áp dụng cho tất cả các trường thông tin tìm kiếm']")))
    exc_input.clear()
    if EXC_KEY:
        exc_input.send_keys(EXC_KEY)

    keyword_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Nhập số TBMT/Tên gói thầu (ví dụ: IB0123456789 hoặc Thiết bị)']")))
    keyword_input.clear()
    keyword_input.send_keys(search_keyword)

    wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@name='ck-investField' and @value='HH']"))).click()
    driver.find_element(By.XPATH, "//button[contains(text(), 'Tìm kiếm')]").click()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[contains(@class, 'nav-tabs')]//a[contains(text(),'Đã đóng thầu')]"))).click()
    time.sleep(1)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'content__body__option')]//span[contains(normalize-space(),'Có nhà thầu trúng thầu')]"))).click()
    time.sleep(2)

    select_elem = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(),'Hiển thị')]/select")))
    time.sleep(0.5)
    select = Select(select_elem)
    select.select_by_value("50")
    time.sleep(2)


def go_to_next_results_page():
    next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next:not([disabled])")))
    next_button.click()
    time.sleep(3)
    wait_dom_settled(timeout=15)
    return True


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

    ABORTED_TBMTS_THIS_RUN.clear()
    TEMP_ABORT_SUMMARY.clear()
    CURRENT_RUN_ID = start_run_history(start_time)

    try:
        for idx, search_keyword in enumerate(SEARCH_KEYWORDS, start=1):
            logger.info("=" * 60)
            logger.info(f"Batch {idx}/{len(SEARCH_KEYWORDS)} - Keyword: {search_keyword}")
            logger.info("=" * 60)
            prepare_search_form(search_keyword)
            current_page = 1
            current_batch_limit = MAX_PAGES

            while True:
                processed_count, hit_max_pages, current_page = crawl_current_results(
                    search_keyword,
                    start_page=current_page,
                    page_limit=current_batch_limit,
                )
                total_processed += processed_count

                if not hit_max_pages:
                    break

                action, next_batch_limit = prompt_after_max_pages(
                    search_keyword,
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
                    logger.info(f"Không còn trang tiếp theo cho keyword '{search_keyword}', chuyển keyword khác.")
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
    init_runtime()
    main()
