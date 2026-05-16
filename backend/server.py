from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
import time
import copy
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncio
import asyncpg
import json
import os
import ssl

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)

from auth_utils import (
    change_password,
    clear_auth_session_cookie,
    extract_session_token,
    get_auth_config_payload,
    get_authenticated_user,
    login_with_email,
    login_with_google,
    logout_current_session,
    request_password_reset,
    register_with_email,
    reset_password_with_token,
    require_authenticated_user,
    set_auth_session_cookie,
    update_user_profile,
)

logger = logging.getLogger("bidfinder.api")

DATABASE_URL = os.getenv("DATABASE_URL")
db_pool: Optional[asyncpg.Pool] = None
db_pool_lock = asyncio.Lock()
rate_limit_lock = asyncio.Lock()
rate_limit_buckets: Dict[str, deque] = defaultdict(deque)
anonymous_full_query_usage_lock = asyncio.Lock()
anonymous_full_query_usage: Dict[str, Dict[str, int]] = defaultdict(dict)
full_search_usage_lock = asyncio.Lock()
full_search_usage: Dict[str, Dict[str, int]] = defaultdict(dict)
cache_lock = asyncio.Lock()
preview_cache: Dict[str, Dict[str, Any]] = {}
autocomplete_cache: Dict[str, Dict[str, Any]] = {}


def get_env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_anonymous_access_level(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"none", "preview", "full"}:
        return cleaned
    return "preview"


def build_db_ssl_config() -> ssl.SSLContext | bool:
    if get_env_flag("DB_SSL_DISABLE", False):
        return False

    ca_file = os.getenv("DB_SSL_CA_FILE")
    cert_file = os.getenv("DB_SSL_CERT_FILE")
    key_file = os.getenv("DB_SSL_KEY_FILE")

    context = ssl.create_default_context(cafile=ca_file or None)
    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


LEGACY_AUTH_REQUIRED_FOR_DATA_ACCESS = get_env_flag("AUTH_REQUIRED_FOR_DATA_ACCESS", False)
ANONYMOUS_ACCESS_LEVEL = normalize_anonymous_access_level(
    os.getenv(
        "ANONYMOUS_ACCESS_LEVEL",
        "none" if LEGACY_AUTH_REQUIRED_FOR_DATA_ACCESS else "preview",
    )
)
TRUST_PROXY_HEADERS = get_env_flag("TRUST_PROXY_HEADERS", False)
ANONYMOUS_AUTOCOMPLETE_ENABLED = get_env_flag(
    "ANONYMOUS_AUTOCOMPLETE_ENABLED",
    ANONYMOUS_ACCESS_LEVEL in {"preview", "full"},
)
ANONYMOUS_METADATA_ENABLED = get_env_flag(
    "ANONYMOUS_METADATA_ENABLED",
    ANONYMOUS_ACCESS_LEVEL in {"preview", "full"},
)
ANONYMOUS_SINGLE_CHAR_NUMERIC_ONLY = get_env_flag(
    "ANONYMOUS_SINGLE_CHAR_NUMERIC_ONLY",
    True,
)
AUTH_REQUIRED_FOR_DATA_ACCESS = ANONYMOUS_ACCESS_LEVEL == "none"
AUTH_REQUIRED_FOR_FULL_QUERY = ANONYMOUS_ACCESS_LEVEL != "full"
db_ssl_config = build_db_ssl_config()

DEFAULT_ALLOWED_ORIGINS = [
    "https://bidfinder.vn",
    "https://www.bidfinder.vn",
    "https://bidfinder.netlify.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", ",".join(DEFAULT_ALLOWED_ORIGINS)).split(",")
    if origin.strip()
]
RATE_LIMIT_WINDOW_SECONDS = max(10, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
QUERY_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("QUERY_RATE_LIMIT_PER_MINUTE", "30")))
AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE", "120")))
PREVIEW_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("PREVIEW_RATE_LIMIT_PER_MINUTE", "90")))
METADATA_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("METADATA_RATE_LIMIT_PER_MINUTE", "20")))
FILTER_CONFIG_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("FILTER_CONFIG_RATE_LIMIT_PER_MINUTE", "30")))
AUTH_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "20")))
AUTH_CONFIG_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("AUTH_CONFIG_RATE_LIMIT_PER_MINUTE", "60")))
FEEDBACK_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("FEEDBACK_RATE_LIMIT_PER_MINUTE", "10")))
DEFAULT_QUERY_LIMIT = max(50, int(os.getenv("DEFAULT_QUERY_LIMIT", "200")))
MAX_QUERY_LIMIT = max(DEFAULT_QUERY_LIMIT, int(os.getenv("MAX_QUERY_LIMIT", "1000")))
BULK_EXPORT_QUERY_LIMIT = min(MAX_QUERY_LIMIT, max(1, int(os.getenv("BULK_EXPORT_QUERY_LIMIT", "1000"))))
FULL_SEARCH_DAILY_LIMIT = max(0, int(os.getenv("FULL_SEARCH_DAILY_LIMIT", "3")))
PREVIEW_BUCKET_LIMIT = max(10, int(os.getenv("PREVIEW_BUCKET_LIMIT", "100")))
DB_POOL_MAX_SIZE = max(1, int(os.getenv("DB_POOL_MAX_SIZE", "8")))
PREVIEW_CACHE_TTL_SECONDS = max(1, int(os.getenv("PREVIEW_CACHE_TTL_SECONDS", "15")))
AUTOCOMPLETE_CACHE_TTL_SECONDS = max(1, int(os.getenv("AUTOCOMPLETE_CACHE_TTL_SECONDS", "20")))
CACHE_MAX_ENTRIES = max(50, int(os.getenv("CACHE_MAX_ENTRIES", "500")))
STANDARD_QUERY_EXACT_COUNT_ENABLED = get_env_flag("STANDARD_QUERY_EXACT_COUNT_ENABLED", False)
SERVER_ERROR_MESSAGE = "Hệ thống đang bận hoặc gặp lỗi nội bộ. Vui lòng thử lại sau."
DRUG_GROUP_UNKNOWN = "UNKNOWN"
DRUG_GROUP_CANONICAL = ("BDG", "N1", "N2", "N3", "N4", "N5")
DRUG_GROUP_UI_OPTIONS = [
    {"value": "BDG", "label": "Biệt dược gốc"},
    {"value": "N1", "label": "Nhóm 1"},
    {"value": "N2", "label": "Nhóm 2"},
    {"value": "N3", "label": "Nhóm 3"},
    {"value": "N4", "label": "Nhóm 4"},
    {"value": "N5", "label": "Nhóm 5"},
    {"value": DRUG_GROUP_UNKNOWN, "label": "Không xác định"},
]
APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"
try:
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    APP_TIMEZONE = ZoneInfo("UTC")
ANONYMOUS_FULL_QUERY_DAILY_LIMIT = max(
    0,
    int(os.getenv("ANONYMOUS_FULL_QUERY_DAILY_LIMIT", "10")),
)
ANONYMOUS_FULL_QUERY_LIMIT_MESSAGE = (
    f"Bạn đã dùng hết {ANONYMOUS_FULL_QUERY_DAILY_LIMIT} lượt tra cứu hôm nay. "
    "Vui lòng đăng nhập để tiếp tục."
)
FULL_SEARCH_LIMIT_MESSAGE = (
    f"Bạn đã dùng hết {FULL_SEARCH_DAILY_LIMIT} lượt full search hôm nay. "
    "Vui lòng quay lại vào ngày mai."
)


# =========================
# DATASETS / CTE
# =========================

DF1_CTE = """
WITH df1_full AS (
    SELECT
        m.id AS "__row_id",
        EXISTS (
            SELECT 1
            FROM processed_duplicate_flags f
            WHERE f.dataset_scope = 'medicine'
              AND f.processed_row_id = m.id
        ) AS "__has_duplicate_warning",
        'medicine' AS "_dataset",
        m.ma_tbmt AS "Mã TBMT",
        COALESCE(NULLIF(m.qd_display, ''), m.so_qd) AS "Quyết định phê duyệt",
        m.version AS "Version",
        m.ma_thuoc AS "Mã thuốc",
        m.ten_thuoc AS "Tên thuốc",
        m.ten_hoat_chat AS "Tên hoạt chất",
        m.nong_do_ham_luong AS "Nồng độ, hàm lượng",
        m.duong_dung AS "Đường dùng",
        m.dang_bao_che AS "Dạng bào chế",
        m.quy_cach AS "Quy cách",
        m.nhom_thuoc AS "Nhóm thuốc",
        COALESCE(m.nhom_thuoc_filter, ARRAY[]::TEXT[]) AS "__drug_group_filter",
        m.han_dung AS "Hạn dùng",
        m.so_dk_gpnk AS "GĐKLH hoặc GPNK",
        m.co_so_san_xuat AS "Cơ sở sản xuất",
        m.xuat_xu AS "Xuất xứ",
        m.don_vi_tinh AS "Đơn vị tính",
        m.so_luong AS "Số lượng",
        m.don_gia_trung_thau AS "Đơn giá trúng thầu (VND)",
        m.thanh_tien AS "Thành tiền (VND)",
        m.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        m.created_at AS "Ngày cập nhật DB",
        TO_CHAR(p.ngay_het_hieu_luc, 'DD/MM/YYYY') AS "Ngày hết hiệu lực",
        p.ngay_het_hieu_luc AS "__expiry_date",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực"
    FROM processed_medicines m
    LEFT JOIN package_metadata p
        ON m.ma_tbmt = p.ma_tbmt
       AND m.so_qd = p.so_qd
       AND m.version = p.version
)
"""

DF2_CTE = """
WITH df2_full AS (
    SELECT
        g.id AS "__row_id",
        EXISTS (
            SELECT 1
            FROM processed_duplicate_flags f
            WHERE f.dataset_scope = 'goods'
              AND f.processed_row_id = g.id
        ) AS "__has_duplicate_warning",
        'goods' AS "_dataset",
        g.ma_tbmt AS "Mã TBMT",
        COALESCE(NULLIF(g.qd_display, ''), g.so_qd) AS "Quyết định phê duyệt",
        g.version AS "Version",
        g.ma_phan_lo AS "Mã phần/lô",
        g.ten_phan_lo AS "Tên phần/lô",
        g.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        g.danh_muc_hang_hoa AS "Danh mục hàng hóa",
        g.ky_ma_hieu AS "Ký mã hiệu",
        g.nhan_hieu AS "Nhãn hiệu",
        g.hang_san_xuat AS "Hãng sản xuất",
        g.mat_hang_du_thau AS "Mặt hàng dự thầu",
        g.don_vi_tinh AS "Đơn vị tính",
        g.khoi_luong AS "Khối lượng",
        g.xuat_xu AS "Xuất xứ",
        g.nam_san_xuat AS "Năm sản xuất",
        g.tinh_nang_ky_thuat AS "Tính năng kỹ thuật",
        g.don_gia_trung_thau AS "Đơn giá trúng thầu (VND)",
        g.thanh_tien AS "Thành tiền (VND)",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        g.created_at AS "Ngày cập nhật DB",
        TO_CHAR(p.ngay_het_hieu_luc, 'DD/MM/YYYY') AS "Ngày hết hiệu lực",
        p.ngay_het_hieu_luc AS "__expiry_date",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực",
        (
            COALESCE(g.ten_phan_lo, '') || ' | ' ||
            COALESCE(g.danh_muc_hang_hoa, '') || ' | ' ||
            COALESCE(g.ky_ma_hieu, '') || ' | ' ||
            COALESCE(g.nhan_hieu, '') || ' | ' ||
            COALESCE(g.mat_hang_du_thau, '') || ' | ' ||
            COALESCE(g.tinh_nang_ky_thuat, '')
        ) AS "Search blob"
    FROM processed_goods g
    LEFT JOIN package_metadata p
        ON g.ma_tbmt = p.ma_tbmt
       AND g.so_qd = p.so_qd
       AND g.version = p.version
)
"""

DF1_SEARCH_CTE = """
WITH df1_search AS (
    SELECT
        m.id AS "__row_id",
        m.ma_tbmt AS "Mã TBMT",
        COALESCE(NULLIF(m.qd_display, ''), m.so_qd) AS "Quyết định phê duyệt",
        m.version AS "Version",
        m.ma_thuoc AS "Mã thuốc",
        m.ten_thuoc AS "Tên thuốc",
        m.ten_hoat_chat AS "Tên hoạt chất",
        m.nong_do_ham_luong AS "Nồng độ, hàm lượng",
        m.duong_dung AS "Đường dùng",
        m.dang_bao_che AS "Dạng bào chế",
        m.quy_cach AS "Quy cách",
        m.nhom_thuoc AS "Nhóm thuốc",
        COALESCE(m.nhom_thuoc_filter, ARRAY[]::TEXT[]) AS "__drug_group_filter",
        m.so_dk_gpnk AS "GĐKLH hoặc GPNK",
        m.co_so_san_xuat AS "Cơ sở sản xuất",
        m.xuat_xu AS "Xuất xứ",
        m.don_vi_tinh AS "Đơn vị tính",
        m.so_luong AS "Số lượng",
        m.don_gia_trung_thau AS "Đơn giá trúng thầu (VND)",
        m.thanh_tien AS "Thành tiền (VND)",
        m.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        p.ngay_het_hieu_luc AS "__expiry_date",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực"
    FROM processed_medicines m
    LEFT JOIN package_metadata p
        ON m.ma_tbmt = p.ma_tbmt
       AND m.so_qd = p.so_qd
       AND m.version = p.version
)
"""

DF2_SEARCH_CTE = """
WITH df2_search AS (
    SELECT
        g.id AS "__row_id",
        g.ma_tbmt AS "Mã TBMT",
        COALESCE(NULLIF(g.qd_display, ''), g.so_qd) AS "Quyết định phê duyệt",
        g.version AS "Version",
        g.ma_phan_lo AS "Mã phần/lô",
        g.ten_phan_lo AS "Tên phần/lô",
        g.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        g.danh_muc_hang_hoa AS "Danh mục hàng hóa",
        g.ky_ma_hieu AS "Ký mã hiệu",
        g.nhan_hieu AS "Nhãn hiệu",
        g.hang_san_xuat AS "Hãng sản xuất",
        g.mat_hang_du_thau AS "Mặt hàng dự thầu",
        g.don_vi_tinh AS "Đơn vị tính",
        g.khoi_luong AS "Khối lượng",
        g.xuat_xu AS "Xuất xứ",
        g.nam_san_xuat AS "Năm sản xuất",
        g.tinh_nang_ky_thuat AS "Tính năng kỹ thuật",
        g.don_gia_trung_thau AS "Đơn giá trúng thầu (VND)",
        g.thanh_tien AS "Thành tiền (VND)",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        p.ngay_het_hieu_luc AS "__expiry_date",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực",
        (
            COALESCE(g.ten_phan_lo, '') || ' | ' ||
            COALESCE(g.danh_muc_hang_hoa, '') || ' | ' ||
            COALESCE(g.ky_ma_hieu, '') || ' | ' ||
            COALESCE(g.nhan_hieu, '') || ' | ' ||
            COALESCE(g.mat_hang_du_thau, '') || ' | ' ||
            COALESCE(g.tinh_nang_ky_thuat, '')
        ) AS "Search blob"
    FROM processed_goods g
    LEFT JOIN package_metadata p
        ON g.ma_tbmt = p.ma_tbmt
       AND g.so_qd = p.so_qd
       AND g.version = p.version
)
"""

DF1_PREVIEW_CTE = """
WITH df1_preview AS (
    SELECT
        COALESCE(NULLIF(m.qd_display, ''), m.so_qd) AS "Quyết định phê duyệt",
        m.ten_thuoc AS "Tên thuốc",
        m.ten_hoat_chat AS "Tên hoạt chất",
        m.nong_do_ham_luong AS "Nồng độ, hàm lượng",
        m.duong_dung AS "Đường dùng",
        m.dang_bao_che AS "Dạng bào chế",
        m.quy_cach AS "Quy cách",
        m.nhom_thuoc AS "Nhóm thuốc",
        COALESCE(m.nhom_thuoc_filter, ARRAY[]::TEXT[]) AS "__drug_group_filter",
        m.so_dk_gpnk AS "GĐKLH hoặc GPNK",
        m.don_vi_tinh AS "Đơn vị tính",
        m.co_so_san_xuat AS "Cơ sở sản xuất",
        m.xuat_xu AS "Xuất xứ",
        m.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực"
    FROM processed_medicines m
    LEFT JOIN package_metadata p
        ON m.ma_tbmt = p.ma_tbmt
       AND m.so_qd = p.so_qd
       AND m.version = p.version
)
"""

DF2_PREVIEW_CTE = """
WITH df2_preview AS (
    SELECT
        COALESCE(NULLIF(g.qd_display, ''), g.so_qd) AS "Quyết định phê duyệt",
        g.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        g.don_vi_tinh AS "Đơn vị tính",
        g.hang_san_xuat AS "Hãng sản xuất",
        g.xuat_xu AS "Xuất xứ",
        p.chu_dau_tu AS "Chủ đầu tư",
        p.ngay_phe_duyet AS "Ngày phê duyệt",
        COALESCE(
            p.ngay_phe_duyet_date,
            CASE
                WHEN p.ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(p.ngay_phe_duyet, 'DD/MM/YYYY')
                ELSE NULL
            END
        ) AS "__approval_date",
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        COALESCE(
            NULLIF(
                CASE
                    WHEN p.tinh_trang_hieu_luc = 'CÒN HIỆU LỰC' THEN 'Còn hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'HẾT HIỆU LỰC' THEN 'Hết hiệu lực'
                    WHEN p.tinh_trang_hieu_luc = 'KHÔNG XÁC ĐỊNH' THEN 'Chưa xác định'
                    ELSE p.tinh_trang_hieu_luc
                END,
                ''
            ),
            CASE
                WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
                WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
                ELSE 'Hết hiệu lực'
            END
        ) AS "Tình trạng hiệu lực",
        (
            COALESCE(g.ten_phan_lo, '') || ' | ' ||
            COALESCE(g.danh_muc_hang_hoa, '') || ' | ' ||
            COALESCE(g.ky_ma_hieu, '') || ' | ' ||
            COALESCE(g.nhan_hieu, '') || ' | ' ||
            COALESCE(g.mat_hang_du_thau, '') || ' | ' ||
            COALESCE(g.tinh_nang_ky_thuat, '')
        ) AS "Search blob"
    FROM processed_goods g
    LEFT JOIN package_metadata p
        ON g.ma_tbmt = p.ma_tbmt
       AND g.so_qd = p.so_qd
       AND g.version = p.version
)
"""


# =========================
# MODELS
# =========================

class TokenFilterItem(BaseModel):
    value: str
    op: Literal["OR", "AND", "NOT"] = "OR"


class TokenFilter(BaseModel):
    tokens: List[TokenFilterItem] = Field(default_factory=list)


class FilterRequest(BaseModel):
    investor: Optional[TokenFilter] = None
    approvalDecision: Optional[TokenFilter] = None
    winner: Optional[TokenFilter] = None
    drugName: Optional[TokenFilter] = None
    activeIngredient: Optional[TokenFilter] = None
    concentration: Optional[TokenFilter] = None
    route: Optional[TokenFilter] = None
    dosageForm: Optional[TokenFilter] = None
    specification: Optional[TokenFilter] = None
    drugGroup: Optional[Any] = None
    regNo: Optional[TokenFilter] = None
    unit: Optional[TokenFilter] = None
    manufacturer: Optional[TokenFilter] = None
    country: Optional[TokenFilter] = None
    goodsKeyword: Optional[TokenFilter] = None

    selectionMethod: Optional[List[str]] = None
    place: Optional[List[str]] = None
    validity: Optional[str] = None
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None


class SortRule(BaseModel):
    column: str
    order: Literal["asc", "desc"] = "desc"


class QueryRequest(BaseModel):
    scope: Literal["all", "medicine", "goods"] = "all"
    filters: Optional[FilterRequest] = None
    sort: Optional[List[SortRule]] = None
    limit: int = DEFAULT_QUERY_LIMIT
    searchMode: Literal["standard", "full"] = "standard"


class QueryPreviewRequest(BaseModel):
    scope: Literal["all", "medicine", "goods"] = "all"
    filters: Optional[FilterRequest] = None


class BulkQueryRequest(BaseModel):
    scope: Literal["medicine", "goods"]
    fields: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    diversityMode: Literal["price", "product"] = "price"
    priceLimit: int = 3
    productLimit: int = 3
    limit: int = DEFAULT_QUERY_LIMIT
    searchMode: Literal["standard", "full"] = "standard"


class AutocompleteRequest(BaseModel):
    scope: Optional[str] = "all"
    field: str
    keyword: str
    filters: Optional[Dict[str, Any]] = None
    excludeSelf: Optional[bool] = True
    limit: Optional[int] = 10


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    work_unit: Optional[str] = None
    position: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    work_unit: Optional[str] = None
    position: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str


class FeedbackAnswer(BaseModel):
    question: str
    answer: str


class FeedbackRequest(BaseModel):
    answers: List[FeedbackAnswer] = Field(default_factory=list)
    task: Optional[str] = None
    note: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


# =========================
# FIELD REGISTRY
# =========================

FIELD_REGISTRY: Dict[str, Dict[str, Any]] = {
    "investor": {
        "type": "token",
        "medicine_column": '"Chủ đầu tư"',
        "goods_column": '"Chủ đầu tư"',
        "autocomplete": True,
    },
        "approvalDecision": {
        "type": "token",
        "medicine_column": '"Quyết định phê duyệt"',
        "goods_column": '"Quyết định phê duyệt"',
        "autocomplete": True,
    },
    "selectionMethod": {
        "type": "fixed_list",
        "medicine_column": '"Hình thức LCNT"',
        "goods_column": '"Hình thức LCNT"',
    },
    "place": {
        "type": "fixed_list",
        "medicine_column": '"Địa điểm"',
        "goods_column": '"Địa điểm"',
    },
    "validity": {
        "type": "fixed_single",
        "medicine_column": '"Tình trạng hiệu lực"',
        "goods_column": '"Tình trạng hiệu lực"',
    },
    "winner": {
        "type": "token",
        "medicine_column": '"Nhà thầu trúng thầu"',
        "goods_column": '"Nhà thầu trúng thầu"',
        "autocomplete": True,
    },
    "drugName": {
        "type": "token",
        "medicine_column": '"Tên thuốc"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "activeIngredient": {
        "type": "token",
        "medicine_column": '"Tên hoạt chất"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "concentration": {
        "type": "token",
        "medicine_column": '"Nồng độ, hàm lượng"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "route": {
        "type": "token",
        "medicine_column": '"Đường dùng"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "dosageForm": {
        "type": "token",
        "medicine_column": '"Dạng bào chế"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "specification": {
        "type": "token",
        "medicine_column": '"Quy cách"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "drugGroup": {
        "type": "drug_group",
        "medicine_column": '"Nhóm thuốc"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "options": DRUG_GROUP_UI_OPTIONS,
    },
    "regNo": {
        "type": "token",
        "medicine_column": '"GĐKLH hoặc GPNK"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
    },
    "unit": {
        "type": "token",
        "medicine_column": '"Đơn vị tính"',
        "goods_column": '"Đơn vị tính"',
        "autocomplete": True,
    },
    "manufacturer": {
        "type": "token",
        "medicine_column": '"Cơ sở sản xuất"',
        "goods_column": '"Hãng sản xuất"',
        "autocomplete": True,
    },
    "country": {
        "type": "token",
        "medicine_column": '"Xuất xứ"',
        "goods_column": '"Xuất xứ"',
        "autocomplete": True,
    }
}


BASE_SORT_MAP = {
    "ma_tbmt": '"Mã TBMT"',
    "investor": '"Chủ đầu tư"',
    "approvalDecision": '"Quyết định phê duyệt"',
    "approvalDate": '"__approval_date"',
    "expiryDate": '"__expiry_date"',
    "unit": '"Đơn vị tính"',
    "unitPrice": '"Đơn giá trúng thầu (VND)"',
    "amount": '"Thành tiền (VND)"',
    "origin": '"Xuất xứ"',
    "winner": '"Nhà thầu trúng thầu"',
    "method": '"Hình thức LCNT"',
    "place": '"Địa điểm"',
    "validity": '"Tình trạng hiệu lực"',
}

ALLOWED_SORT_DF1 = {
    **BASE_SORT_MAP,
    "quantity": '"Số lượng"',
    "drugName": '"Tên thuốc"',
    "activeIngredient": '"Tên hoạt chất"',
    "strength": '"Nồng độ, hàm lượng"',
    "route": '"Đường dùng"',
    "dosageForm": '"Dạng bào chế"',
    "packaging": '"Quy cách"',
    "drugGroup": '"Nhóm thuốc"',
    "license": '"GĐKLH hoặc GPNK"',
    "manufacturer": '"Cơ sở sản xuất"',
}

ALLOWED_SORT_DF2 = {
    **BASE_SORT_MAP,
    "quantity": '"Khối lượng"',
    "lotName": '"Tên phần/lô"',
    "drugName": '"Danh mục hàng hóa"',
    "bidItem": '"Mặt hàng dự thầu"',
    "brand": '"Nhãn hiệu"',
    "model": '"Ký mã hiệu"',
    "technicalSpec": '"Tính năng kỹ thuật"',
    "manufacturer": '"Hãng sản xuất"',
}

BULK_SEARCH_FIELDS: Dict[str, Dict[str, str]] = {
    "medicine": {
        "drugName": '"Tên thuốc"',
        "activeIngredient": '"Tên hoạt chất"',
        "concentration": '"Nồng độ, hàm lượng"',
        "route": '"Đường dùng"',
        "dosageForm": '"Dạng bào chế"',
        "drugGroup": '"Nhóm thuốc"',
        "unit": '"Đơn vị tính"',
        "regNo": '"GĐKLH hoặc GPNK"',
        "specification": '"Quy cách"',
        "manufacturer": '"Cơ sở sản xuất"',
        "country": '"Xuất xứ"',
    },
    "goods": {
        "lotName": '"Tên phần/lô"',
        "goodsName": '"Danh mục hàng hóa"',
        "technicalSpec": '"Tính năng kỹ thuật"',
        "bidItem": '"Mặt hàng dự thầu"',
        "model": '"Ký mã hiệu"',
        "brand": '"Nhãn hiệu"',
        "country": '"Xuất xứ"',
        "manufacturer": '"Hãng sản xuất"',
        "unit": '"Đơn vị tính"',
    },
}


# =========================
# DB HELPERS
# =========================

async def setup_connection(conn):
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def get_db_pool():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")
    return await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,
        max_size=DB_POOL_MAX_SIZE,
        command_timeout=60,
        max_inactive_connection_lifetime=300,
        setup=setup_connection,
        ssl=db_ssl_config,
    )


async def ensure_db_pool() -> asyncpg.Pool:
    global db_pool

    if db_pool is not None:
        return db_pool

    async with db_pool_lock:
        if db_pool is None:
            db_pool = await get_db_pool()

    return db_pool


def clean_value(val):
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def clean_records(records):
    cleaned_records = []
    for record in records:
        normalized = {}
        for key, value in dict(record).items():
            if key in {"__price_rank", "__product_rank", "__product_row_rank", "__recency_bucket", "__drug_group_filter"}:
                continue
            normalized[key] = clean_value(value)
        cleaned_records.append(normalized)
    return cleaned_records


def get_client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip

    return getattr(request.client, "host", "") or "unknown"


def get_rate_limit_client_key(request: Request) -> str:
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "").strip().lower()
    user_agent_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:16] if user_agent else "no-ua"
    return f"{client_ip}:{user_agent_hash}"


def get_usage_day_key() -> str:
    return datetime.now(APP_TIMEZONE).date().isoformat()


def prune_anonymous_full_query_usage(current_day: str) -> None:
    expired_days = [day_key for day_key in list(anonymous_full_query_usage.keys()) if day_key != current_day]
    for day_key in expired_days:
        anonymous_full_query_usage.pop(day_key, None)


async def get_anonymous_full_query_usage_snapshot(request: Request) -> Dict[str, int]:
    if ANONYMOUS_FULL_QUERY_DAILY_LIMIT <= 0:
        return {"used": 0, "remaining": 0, "limit": 0}

    day_key = get_usage_day_key()
    client_key = get_rate_limit_client_key(request)

    async with anonymous_full_query_usage_lock:
        prune_anonymous_full_query_usage(day_key)
        used = int(anonymous_full_query_usage.get(day_key, {}).get(client_key, 0))

    remaining = max(0, ANONYMOUS_FULL_QUERY_DAILY_LIMIT - used)
    return {
        "used": used,
        "remaining": remaining,
        "limit": ANONYMOUS_FULL_QUERY_DAILY_LIMIT,
    }


async def consume_anonymous_full_query_usage(request: Request) -> Dict[str, int]:
    if ANONYMOUS_FULL_QUERY_DAILY_LIMIT <= 0:
        return {"used": 0, "remaining": 0, "limit": 0}

    day_key = get_usage_day_key()
    client_key = get_rate_limit_client_key(request)

    async with anonymous_full_query_usage_lock:
        prune_anonymous_full_query_usage(day_key)
        day_bucket = anonymous_full_query_usage.setdefault(day_key, {})
        used = int(day_bucket.get(client_key, 0)) + 1
        day_bucket[client_key] = used

    remaining = max(0, ANONYMOUS_FULL_QUERY_DAILY_LIMIT - used)
    return {
        "used": used,
        "remaining": remaining,
        "limit": ANONYMOUS_FULL_QUERY_DAILY_LIMIT,
    }


def prune_full_search_usage(current_day: str) -> None:
    expired_days = [day_key for day_key in list(full_search_usage.keys()) if day_key != current_day]
    for day_key in expired_days:
        full_search_usage.pop(day_key, None)


def get_full_search_actor_key(request: Request, user: Optional[Dict[str, Any]]) -> str:
    if user and user.get("id") is not None:
        return f"user:{int(user['id'])}"
    return f"client:{get_rate_limit_client_key(request)}"


async def get_full_search_usage_snapshot(request: Request, user: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if FULL_SEARCH_DAILY_LIMIT <= 0:
        return {"used": 0, "remaining": 0, "limit": 0}

    day_key = get_usage_day_key()
    actor_key = get_full_search_actor_key(request, user)

    async with full_search_usage_lock:
        prune_full_search_usage(day_key)
        used = int(full_search_usage.get(day_key, {}).get(actor_key, 0))

    remaining = max(0, FULL_SEARCH_DAILY_LIMIT - used)
    return {
        "used": used,
        "remaining": remaining,
        "limit": FULL_SEARCH_DAILY_LIMIT,
    }


async def consume_full_search_usage(request: Request, user: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if FULL_SEARCH_DAILY_LIMIT <= 0:
        return {"used": 0, "remaining": 0, "limit": 0}

    day_key = get_usage_day_key()
    actor_key = get_full_search_actor_key(request, user)

    async with full_search_usage_lock:
        prune_full_search_usage(day_key)
        day_bucket = full_search_usage.setdefault(day_key, {})
        used = int(day_bucket.get(actor_key, 0)) + 1
        day_bucket[actor_key] = used

    remaining = max(0, FULL_SEARCH_DAILY_LIMIT - used)
    return {
        "used": used,
        "remaining": remaining,
        "limit": FULL_SEARCH_DAILY_LIMIT,
    }


async def build_full_search_quota_payload(
    request: Optional[Request],
    *,
    user: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_search_enabled": True,
        "full_search_daily_limit": FULL_SEARCH_DAILY_LIMIT,
        "full_search_daily_used": 0,
        "full_search_daily_remaining": FULL_SEARCH_DAILY_LIMIT,
        "full_search_limit_message": FULL_SEARCH_LIMIT_MESSAGE,
    }

    if FULL_SEARCH_DAILY_LIMIT <= 0:
        payload["full_search_daily_remaining"] = 0
        payload["full_search_enabled"] = False
        return payload

    if request is None:
        return payload

    usage = await get_full_search_usage_snapshot(request, user)
    payload.update({
        "full_search_daily_used": usage["used"],
        "full_search_daily_remaining": usage["remaining"],
    })
    return payload


async def build_anonymous_full_query_quota_payload(
    request: Optional[Request],
    *,
    is_authenticated: bool,
) -> Dict[str, Any]:
    enabled = ANONYMOUS_ACCESS_LEVEL == "full" and ANONYMOUS_FULL_QUERY_DAILY_LIMIT > 0
    payload: Dict[str, Any] = {
        "anonymous_full_query_daily_limit": ANONYMOUS_FULL_QUERY_DAILY_LIMIT,
        "anonymous_full_query_daily_used": 0,
        "anonymous_full_query_daily_remaining": ANONYMOUS_FULL_QUERY_DAILY_LIMIT,
        "anonymous_full_query_login_required": False,
        "anonymous_full_query_limit_message": ANONYMOUS_FULL_QUERY_LIMIT_MESSAGE,
    }

    if not enabled:
        payload["anonymous_full_query_daily_remaining"] = 0
        return payload

    if is_authenticated:
        return payload

    if request is None:
        return payload

    usage = await get_anonymous_full_query_usage_snapshot(request)
    payload.update({
        "anonymous_full_query_daily_used": usage["used"],
        "anonymous_full_query_daily_remaining": usage["remaining"],
        "anonymous_full_query_login_required": usage["remaining"] <= 0,
    })
    return payload


def log_server_exception(context: str, exc: Exception) -> None:
    logger.exception("%s: %s", context, exc)


def internal_error_response(message: str = SERVER_ERROR_MESSAGE) -> JSONResponse:
    return validation_error_response(message, status_code=500)


async def enforce_rate_limit(request: Request, bucket_name: str, limit: int) -> Optional[JSONResponse]:
    cache_key = f"{bucket_name}:{get_rate_limit_client_key(request)}"
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    async with rate_limit_lock:
        bucket = rate_limit_buckets[cache_key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Too many requests",
                    "message": f"Bạn đang gửi quá nhiều request tới {bucket_name}. Vui lòng thử lại sau.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)

    return None


def normalize_ws(value: Any) -> str:
    return " ".join(str(value or "").split())

def extract_goods_snippet(text: str, keyword: str, max_len: int = 100) -> str:
    raw = normalize_ws(text)
    if not raw:
        return ""

    parts = [normalize_ws(p) for p in raw.split("|") if normalize_ws(p)]
    kw = normalize_ws(keyword).lower()

    best_part = ""
    for part in parts:
        if kw and kw in part.lower():
            best_part = part
            break

    if not best_part:
        best_part = parts[0] if parts else raw

    if len(best_part) <= max_len:
        return best_part

    idx = best_part.lower().find(kw) if kw else -1
    if idx < 0:
        return best_part[:max_len].rstrip() + "…"

    start = max(0, idx - 30)
    end = min(len(best_part), idx + len(keyword) + 40)
    snippet = best_part[start:end].strip()

    if start > 0:
        snippet = "…" + snippet
    if end < len(best_part):
        snippet = snippet + "…"

    return snippet[:max_len]


def next_param(params: List[Any], value: Any) -> str:
    params.append(value)
    return f"${len(params)}"


def build_token_condition(column: str, token_filter: TokenFilter, params: List[Any]) -> Optional[str]:
    if not token_filter or not token_filter.tokens:
        return None

    and_parts = []
    or_parts = []
    not_parts = []

    for item in token_filter.tokens:
        value = (item.value or "").strip()
        if not value:
            continue

        p = next_param(params, f"%{value}%")
        expr = f"{column} ILIKE {p}"

        if item.op == "NOT":
            not_parts.append(f"{column} NOT ILIKE {p}")
        elif item.op == "AND":
            and_parts.append(expr)
        else:
            or_parts.append(expr)

    clauses = []
    if and_parts:
        clauses.append("(" + " AND ".join(and_parts) + ")")
    if or_parts:
        clauses.append("(" + " OR ".join(or_parts) + ")")
    clauses.extend(not_parts)

    return " AND ".join(clauses) if clauses else None


def normalize_drug_group_filter_values(value: Any) -> List[str]:
    raw_values: List[str] = []
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, dict) and isinstance(value.get("tokens"), list):
        raw_values = [item.get("value", "") for item in value["tokens"] if isinstance(item, dict)]
    elif isinstance(value, TokenFilter):
        raw_values = [item.value for item in value.tokens]

    normalized: List[str] = []
    labels = {
        "BIET DUOC GOC": "BDG",
        "BIỆT DƯỢC GỐC": "BDG",
        "NHOM 1": "N1",
        "NHÓM 1": "N1",
        "NHOM 2": "N2",
        "NHÓM 2": "N2",
        "NHOM 3": "N3",
        "NHÓM 3": "N3",
        "NHOM 4": "N4",
        "NHÓM 4": "N4",
        "NHOM 5": "N5",
        "NHÓM 5": "N5",
        "KHONG XAC DINH": DRUG_GROUP_UNKNOWN,
        "KHÔNG XÁC ĐỊNH": DRUG_GROUP_UNKNOWN,
    }
    allowed = set(DRUG_GROUP_CANONICAL) | {DRUG_GROUP_UNKNOWN}

    for item in raw_values:
        text = str(item or "").strip()
        if not text:
            continue
        upper = " ".join(text.upper().split())
        value = labels.get(upper, upper)
        if value in allowed and value not in normalized:
            normalized.append(value)
    return normalized


def build_medicine_drug_group_condition(value: Any, params: List[Any]) -> Optional[str]:
    selected = normalize_drug_group_filter_values(value)
    canonical = [item for item in selected if item in DRUG_GROUP_CANONICAL]
    include_unknown = DRUG_GROUP_UNKNOWN in selected
    clauses = []

    if canonical:
        p = next_param(params, canonical)
        clauses.append(f'"__drug_group_filter" && {p}::TEXT[]')

    if include_unknown:
        p = next_param(params, list(DRUG_GROUP_CANONICAL))
        clauses.append(f'NOT ("__drug_group_filter" && {p}::TEXT[])')

    if not clauses:
        return None
    return "(" + " OR ".join(clauses) + ")"


def build_goods_drug_group_condition(blob_col: str, value: Any, params: List[Any]) -> Optional[str]:
    selected = normalize_drug_group_filter_values(value)
    canonical = [item for item in selected if item in DRUG_GROUP_CANONICAL]
    if not canonical:
        return "FALSE" if DRUG_GROUP_UNKNOWN in selected else None

    pattern_map = {
        "BDG": ["%BDG%", "%BGD%", "% BD %", "%Biệt dược%", "%Biet duoc%", "%G2%"],
        "N1": ["%N1%", "%N 1%", "%G1N1%", "%G1 N1%", "%G1 Nhóm 1%"],
        "N2": ["%N2%", "%N 2%", "%G1N2%", "%G1 N2%", "%G1 Nhóm 2%"],
        "N3": ["%N3%", "%N 3%", "%G1N3%", "%G1 N3%", "%G1 Nhóm 3%"],
        "N4": ["%N4%", "%N 4%", "%G1N4%", "%G1 N4%", "%G1 Nhóm 4%"],
        "N5": ["%N5%", "%N 5%", "%G1N5%", "%G1 N5%", "%G1 Nhóm 5%"],
    }
    parts = []
    for item in canonical:
        item_parts = []
        for pattern in pattern_map[item]:
            p = next_param(params, pattern)
            item_parts.append(f"{blob_col} ILIKE {p}")
        if item.startswith("N"):
            number = item[1]
            p = next_param(
                params,
                rf"(nhóm|nhom)\s*([1-5]\s*[,;/]\s*)*{number}(\s*[,;/]\s*[1-5])*([^0-9]|$)",
            )
            item_parts.append(f"{blob_col} ~* {p}")
        parts.append("(" + " OR ".join(item_parts) + ")")
    return "(" + " OR ".join(parts) + ")"


def get_column_for_scope(field_name: str, scope_name: str) -> Optional[str]:
    conf = FIELD_REGISTRY.get(field_name)
    if not conf:
        return None
    return conf.get("medicine_column") if scope_name == "medicine" else conf.get("goods_column")


def get_blob_fallback_for_scope(field_name: str, scope_name: str) -> Optional[str]:
    conf = FIELD_REGISTRY.get(field_name)
    if not conf:
        return None
    if scope_name == "goods":
        return conf.get("goods_blob_fallback")
    return None


def build_scope_filters(scope_name: str, filters: Optional[FilterRequest], params: List[Any], exclude_field: Optional[str] = None) -> List[str]:
    if not filters:
        return []

    conditions = []

    for field_name, conf in FIELD_REGISTRY.items():
        if field_name == exclude_field:
            continue

        field_value = getattr(filters, field_name, None)
        if field_value is None:
            continue

        field_type = conf["type"]
        column = get_column_for_scope(field_name, scope_name)

        if field_type == "drug_group":
            if scope_name == "medicine":
                cond = build_medicine_drug_group_condition(field_value, params)
            else:
                blob_col = get_blob_fallback_for_scope(field_name, scope_name)
                cond = build_goods_drug_group_condition(blob_col, field_value, params) if blob_col else None
            if cond:
                conditions.append(cond)

        elif field_type == "token":
            if column:
                cond = build_token_condition(column, field_value, params)
                if cond:
                    conditions.append(cond)
            else:
                blob_col = get_blob_fallback_for_scope(field_name, scope_name)
                if blob_col and field_value:
                    cond = build_token_condition(blob_col, field_value, params)
                    if cond:
                        conditions.append(cond)

        elif field_type == "fixed_list" and isinstance(field_value, list) and field_value and column:
            p = next_param(params, field_value)
            conditions.append(f"{column} = ANY({p}::text[])")

        elif field_type == "fixed_single" and isinstance(field_value, str) and field_value.strip() and column:
            p = next_param(params, field_value.strip())
            conditions.append(f"{column} = {p}")

    if filters.dateFrom:
        p = next_param(params, filters.dateFrom)
        conditions.append(f'"__approval_date" >= TO_DATE({p}, \'YYYY-MM-DD\')')

    if filters.dateTo:
        p = next_param(params, filters.dateTo)
        conditions.append(f'"__approval_date" <= TO_DATE({p}, \'YYYY-MM-DD\')')

    return conditions


def build_sort_order_parts(scope_name: str, sort_rules: List[SortRule]) -> List[str]:
    sort_map = ALLOWED_SORT_DF1 if scope_name == "medicine" else ALLOWED_SORT_DF2
    order_parts = []
    for rule in sort_rules or []:
        if rule.column in sort_map:
            order_parts.append(f"{sort_map[rule.column]} {'DESC' if rule.order == 'desc' else 'ASC'}")

    if order_parts:
        return order_parts

    return ['"__approval_date" DESC NULLS LAST', '"Mã TBMT" ASC']


def prefix_sort_order_parts(order_parts: List[str], table_alias: str) -> List[str]:
    prefixed = []
    prefix = f'{table_alias}.'
    for part in order_parts:
        prefixed.append(part.replace('"', prefix + '"', 1) if part.startswith('"') else part)
    return prefixed


def build_result_query(
    scope_name: str,
    filters: Optional[FilterRequest],
    sort_rules: List[SortRule],
    limit: int,
    include_overflow_probe: bool = False,
    *,
    diversify_prices: bool = False,
):
    params: List[Any] = []
    search_cte, search_table_name = get_scope_query_parts(scope_name, variant="search")
    full_cte, full_table_name = get_scope_query_parts(scope_name, variant="full")
    conditions = build_scope_filters(scope_name, filters, params)
    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    order_parts = build_sort_order_parts(scope_name, sort_rules)
    order_clause = ", ".join(order_parts)
    selected_order_clause = ", ".join(prefix_sort_order_parts(order_parts, "selected_rows"))
    effective_limit = int(limit) + (1 if include_overflow_probe else 0)

    full_cte_body = full_cte.lstrip().removeprefix("WITH ")

    query = f"""
    {search_cte},
    selected_rows AS MATERIALIZED (
        SELECT *
        FROM {search_table_name}
        {where_clause}
        ORDER BY {order_clause}
        LIMIT {effective_limit}
    ),
    {full_cte_body}
    SELECT full_rows.*
    FROM {full_table_name} full_rows
    JOIN selected_rows
      ON full_rows."__row_id" = selected_rows."__row_id"
    ORDER BY {selected_order_clause}
    """

    return query, params


def build_bulk_item_query(
    scope_name: str,
    selected_fields: List[str],
    row_values: Dict[str, Any],
    diversity_mode: str,
    price_limit: int,
    product_limit: int,
    row_index: int,
):
    params: List[Any] = []
    cte, table_name = get_scope_query_parts(scope_name, variant="full")
    field_map = BULK_SEARCH_FIELDS[scope_name]
    conditions: List[str] = []
    label_parts: List[str] = []

    for field_name in selected_fields:
        if field_name not in field_map:
            continue
        raw_value = str(row_values.get(field_name) or "").strip()
        if not raw_value:
            continue

        label_parts.append(raw_value)
        if scope_name == "medicine" and field_name == "drugGroup":
            cond = build_medicine_drug_group_condition([raw_value], params)
        else:
            token_filter = TokenFilter(tokens=[TokenFilterItem(value=raw_value)])
            cond = build_token_condition(field_map[field_name], token_filter, params)
        if cond:
            conditions.append(cond)

    if not conditions:
        return None, []

    where_clause = " WHERE " + " AND ".join(conditions)
    safe_price_limit = max(1, min(int(price_limit), 10))
    safe_product_limit = max(1, min(int(product_limit), 10))
    product_partition_column = '"Tên thuốc"' if scope_name == "medicine" else '"Search blob"'
    if diversity_mode == "product":
        query = f"""
        {cte}
        SELECT *
        FROM (
            SELECT
                ranked_base.*,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(COALESCE(ranked_base.{product_partition_column}, ''))
                    ORDER BY ranked_base."__approval_date" DESC NULLS LAST, ranked_base."Đơn giá trúng thầu (VND)" ASC NULLS LAST, ranked_base."Mã TBMT" ASC
                ) AS "__product_row_rank",
                DENSE_RANK() OVER (
                    ORDER BY LOWER(COALESCE(ranked_base.{product_partition_column}, '')), ranked_base."Mã TBMT" ASC
                ) AS "__product_rank"
            FROM {table_name} ranked_base
            {where_clause}
              AND ranked_base."Đơn giá trúng thầu (VND)" IS NOT NULL
        ) ranked
        WHERE "__product_rank" <= {safe_product_limit}
          AND "__product_row_rank" = 1
        ORDER BY "__product_rank" ASC, "__approval_date" DESC NULLS LAST, "Đơn giá trúng thầu (VND)" ASC, "Mã TBMT" ASC
        LIMIT {safe_product_limit}
        """
        return query, params

    query = f"""
    {cte}
    SELECT *
    FROM (
        SELECT
            ranked_base.*,
            ROW_NUMBER() OVER (
                PARTITION BY ranked_base."Đơn giá trúng thầu (VND)"
                ORDER BY ranked_base."__approval_date" DESC NULLS LAST, ranked_base."Mã TBMT" ASC
            ) AS "__price_rank"
        FROM {table_name} ranked_base
        {where_clause}
          AND ranked_base."Đơn giá trúng thầu (VND)" IS NOT NULL
    ) ranked
    WHERE "__price_rank" = 1
    ORDER BY "__approval_date" DESC NULLS LAST, "Đơn giá trúng thầu (VND)" ASC, "Mã TBMT" ASC
    LIMIT {safe_price_limit}
    """
    return query, params


def build_bulk_item_count_query(
    scope_name: str,
    selected_fields: List[str],
    row_values: Dict[str, Any],
    diversity_mode: str,
    price_limit: int,
    product_limit: int,
    row_index: int,
):
    query, params = build_bulk_item_query(
        scope_name,
        selected_fields,
        row_values,
        diversity_mode,
        price_limit,
        product_limit,
        row_index,
    )
    if not query:
        return None, []

    return f"SELECT COUNT(*) AS total_count FROM ({query}) bulk_counted", params


def build_total_count_query(scope_name: str, filters: Optional[FilterRequest]):
    params: List[Any] = []
    cte, table_name = get_scope_query_parts(scope_name, variant="search")
    query = f"{cte} SELECT COUNT(*) AS total_count FROM {table_name}"
    conditions = build_scope_filters(scope_name, filters, params)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    return query, params


async def fetch_scope_total_count(
    conn: asyncpg.Connection,
    scope_name: str,
    filters: Optional[FilterRequest],
) -> int:
    query, params = build_total_count_query(scope_name, filters)
    return int(await conn.fetchval(query, *params) or 0)


def allocate_full_search_limits(
    *,
    scope: str,
    total_limit: int,
    medicine_count: Optional[int] = None,
    goods_count: Optional[int] = None,
) -> Dict[str, int]:
    safe_total_limit = max(1, int(total_limit))

    if scope == "medicine":
        return {"medicine": safe_total_limit}
    if scope == "goods":
        return {"goods": safe_total_limit}

    med_count = max(0, int(medicine_count or 0))
    goods_count = max(0, int(goods_count or 0))
    base_split = max(1, safe_total_limit // 2)
    total_available = med_count + goods_count

    if total_available <= safe_total_limit:
        return {
            "medicine": med_count,
            "goods": goods_count,
        }

    if med_count <= base_split and goods_count > base_split:
        med_limit = med_count
        goods_limit = min(goods_count, safe_total_limit - med_limit)
        return {
            "medicine": med_limit,
            "goods": goods_limit,
        }

    if goods_count <= base_split and med_count > base_split:
        goods_limit = goods_count
        med_limit = min(med_count, safe_total_limit - goods_limit)
        return {
            "medicine": med_limit,
            "goods": goods_limit,
        }

    return {
        "medicine": base_split,
        "goods": safe_total_limit - base_split,
    }


def get_scope_query_parts(scope_name: str, variant: Literal["full", "preview", "search"] = "full"):
    query_map = {
        "medicine": {
            "full": (DF1_CTE, "df1_full"),
            "preview": (DF1_PREVIEW_CTE, "df1_preview"),
            "search": (DF1_SEARCH_CTE, "df1_search"),
        },
        "goods": {
            "full": (DF2_CTE, "df2_full"),
            "preview": (DF2_PREVIEW_CTE, "df2_preview"),
            "search": (DF2_SEARCH_CTE, "df2_search"),
        },
    }
    return query_map[scope_name][variant]


def build_preview_query(scope_name: str, filters: Optional[FilterRequest], bucket_limit: int):
    params: List[Any] = []
    cte, table_name = get_scope_query_parts(scope_name, variant="preview")

    query = f"{cte} SELECT 1 FROM {table_name}"
    conditions = build_scope_filters(scope_name, filters, params)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += f" LIMIT {int(bucket_limit) + 1}"
    return query, params


def to_cache_data(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return to_cache_data(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {str(k): to_cache_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_cache_data(item) for item in value]
    return str(value)


def make_cache_key(prefix: str, payload: Dict[str, Any]) -> str:
    serialized = json.dumps(to_cache_data(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}:{serialized}"


def build_count_meta(count: int, exact: bool) -> Dict[str, Any]:
    safe_count = max(0, int(count))
    return {
        "count": safe_count,
        "exact": bool(exact),
        "label": str(safe_count) if exact else f"{safe_count}+",
        "summary": str(safe_count) if exact else f"hơn {safe_count}",
    }


def combine_count_meta(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_count = sum(int(item.get("count") or 0) for item in items)
    total_exact = all(bool(item.get("exact")) for item in items) if items else True
    return build_count_meta(total_count, total_exact)


def combine_preview_count_meta(items: List[Dict[str, Any]], bucket_limit: int) -> Dict[str, Any]:
    safe_limit = max(1, int(bucket_limit))
    total_count = sum(int(item.get("count") or 0) for item in items)
    total_exact = all(bool(item.get("exact")) for item in items) if items else True

    if total_exact and total_count <= safe_limit:
        return build_count_meta(total_count, exact=True)

    return build_count_meta(safe_limit, exact=False)


async def get_cached_payload(cache: Dict[str, Dict[str, Any]], key: str) -> Optional[Any]:
    now = time.monotonic()
    async with cache_lock:
        entry = cache.get(key)
        if not entry:
            return None
        if entry["expires_at"] <= now:
            cache.pop(key, None)
            return None
        return copy.deepcopy(entry["value"])


async def set_cached_payload(cache: Dict[str, Dict[str, Any]], key: str, value: Any, ttl_seconds: int) -> None:
    now = time.monotonic()
    expires_at = now + max(1, int(ttl_seconds))
    payload = copy.deepcopy(value)

    async with cache_lock:
        expired_keys = [cache_key for cache_key, entry in cache.items() if entry["expires_at"] <= now]
        for cache_key in expired_keys:
            cache.pop(cache_key, None)

        if len(cache) >= CACHE_MAX_ENTRIES and cache:
            oldest_key = min(cache.items(), key=lambda item: item[1]["expires_at"])[0]
            cache.pop(oldest_key, None)

        cache[key] = {
            "expires_at": expires_at,
            "value": payload,
        }


def build_autocomplete_query(req: AutocompleteRequest, scope_name: str):
    conf = FIELD_REGISTRY.get(req.field)
    if not conf or not conf.get("autocomplete"):
        return None, None

    column = get_column_for_scope(req.field, scope_name)
    if not column:
        return None, None

    cte, table_name = get_scope_query_parts(scope_name, variant="preview")

    params: List[Any] = []
    conditions = build_scope_filters(
        scope_name=scope_name,
        filters=req.filters,
        params=params,
        exclude_field=req.field if req.excludeSelf else None
    )

    keyword = (req.keyword or "").strip()
    if keyword:
        p = next_param(params, f"%{keyword}%")
        conditions.append(f"{column} ILIKE {p}")

    conditions.append(f"{column} IS NOT NULL")
    conditions.append(f"TRIM({column}) <> ''")

    q = f"""
    {cte}
    SELECT DISTINCT {column} AS suggestion
    FROM {table_name}
    WHERE {" AND ".join(conditions)}
    ORDER BY suggestion
    LIMIT {int(req.limit)}
    """
    return q, params


async def fetch_autocomplete_suggestions(conn, req: AutocompleteRequest, scope_name: str) -> List[str]:
    conf = FIELD_REGISTRY.get(req.field)
    if not conf or not conf.get("autocomplete"):
        return []

    keyword = (req.keyword or "").strip()
    if not keyword:
        return []

    cache_key = make_cache_key(
        "autocomplete",
        {
            "scope": scope_name,
            "field": req.field,
            "keyword": keyword.lower(),
            "filters": req.filters,
            "exclude_self": bool(req.excludeSelf),
            "limit": int(req.limit or 10),
        },
    )
    cached = await get_cached_payload(autocomplete_cache, cache_key)
    if cached is not None:
        return cached

    params: List[Any] = []
    cte, table_name = get_scope_query_parts(scope_name, variant="preview")

    conditions = build_scope_filters(
        scope_name=scope_name,
        filters=req.filters,
        params=params,
        exclude_field=req.field if req.excludeSelf else None,
    )

    seen = set()
    results: List[str] = []
    candidate_limit = max(30, int(req.limit or 10) * 8)
    blob_candidate_limit = max(60, int(req.limit or 10) * 10)

    def push(val: Any):
        text = normalize_ws(val)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        results.append(text)

    if scope_name == "medicine":
        med_col = conf.get("medicine_column")
        if med_col:
            p = next_param(params, f"%{keyword}%")
            q = f"""
            {cte}
            SELECT {med_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{med_col} IS NOT NULL", f"TRIM({med_col}) <> ''", f"{med_col} ILIKE {p}"])}
            LIMIT {candidate_limit}
            """
            rows = await conn.fetch(q, *params)
            for row in rows:
                push(row["suggestion"])
                if len(results) >= int(req.limit or 10):
                    await set_cached_payload(autocomplete_cache, cache_key, results, AUTOCOMPLETE_CACHE_TTL_SECONDS)
                    return results

    if scope_name == "goods":
        goods_col = conf.get("goods_column")
        blob_col = conf.get("goods_blob_fallback")

        if goods_col:
            params_goods = list(params)
            p = next_param(params_goods, f"%{keyword}%")
            q = f"""
            {cte}
            SELECT {goods_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{goods_col} IS NOT NULL", f"TRIM({goods_col}) <> ''", f"{goods_col} ILIKE {p}"])}
            LIMIT {candidate_limit}
            """
            rows = await conn.fetch(q, *params_goods)
            for row in rows:
                push(row["suggestion"])
                if len(results) >= int(req.limit or 10):
                    await set_cached_payload(autocomplete_cache, cache_key, results, AUTOCOMPLETE_CACHE_TTL_SECONDS)
                    return results

        if blob_col:
            params_blob = list(params)
            p = next_param(params_blob, f"%{keyword}%")
            q = f"""
            {cte}
            SELECT {blob_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{blob_col} IS NOT NULL", f"TRIM({blob_col}) <> ''", f"{blob_col} ILIKE {p}"])}
            LIMIT {blob_candidate_limit}
            """
            rows = await conn.fetch(q, *params_blob)
            for row in rows:
                push(extract_goods_snippet(row["suggestion"], keyword))
                if len(results) >= int(req.limit or 10):
                    await set_cached_payload(autocomplete_cache, cache_key, results, AUTOCOMPLETE_CACHE_TTL_SECONDS)
                    return results

    await set_cached_payload(autocomplete_cache, cache_key, results, AUTOCOMPLETE_CACHE_TTL_SECONDS)
    return results


async def fetch_preview_bucket(conn: asyncpg.Connection, scope_name: str, filters: Optional[FilterRequest], bucket_limit: int) -> Dict[str, Any]:
    query, params = build_preview_query(scope_name, filters, bucket_limit)
    rows = await conn.fetch(query, *params)
    exact = len(rows) <= bucket_limit
    count = len(rows) if exact else bucket_limit
    return build_count_meta(count, exact)


async def fetch_preview_bucket_cached(
    conn: asyncpg.Connection,
    scope_name: str,
    filters: Optional[FilterRequest],
    bucket_limit: int,
) -> Dict[str, Any]:
    cache_key = make_cache_key(
        "preview",
        {
            "scope": scope_name,
            "filters": filters,
            "bucket_limit": int(bucket_limit),
        },
    )
    cached = await get_cached_payload(preview_cache, cache_key)
    if cached is not None:
        return cached

    preview = await fetch_preview_bucket(conn, scope_name, filters, bucket_limit)
    await set_cached_payload(preview_cache, cache_key, preview, PREVIEW_CACHE_TTL_SECONDS)
    return preview


async def fetch_combined_preview_meta(
    conn: asyncpg.Connection,
    filters: Optional[FilterRequest],
    bucket_limit: int,
) -> Dict[str, Any]:
    medicine_preview = await fetch_preview_bucket_cached(conn, "medicine", filters, bucket_limit)
    if not medicine_preview.get("exact"):
        return build_count_meta(bucket_limit, exact=False)

    remaining_probe = max(0, int(bucket_limit) - int(medicine_preview.get("count") or 0))
    goods_bucket_limit = max(1, remaining_probe)
    goods_preview = await fetch_preview_bucket_cached(conn, "goods", filters, goods_bucket_limit)

    total_count = int(medicine_preview.get("count") or 0) + int(goods_preview.get("count") or 0)
    if not goods_preview.get("exact") or total_count > bucket_limit:
        return build_count_meta(bucket_limit, exact=False)

    return build_count_meta(total_count, exact=True)


async def fetch_result_page(
    conn: asyncpg.Connection,
    scope_name: str,
    filters: Optional[FilterRequest],
    sort_rules: List[SortRule],
    limit: int,
    *,
    diversify_prices: bool = False,
    exact_count_enabled: bool = False,
) -> Dict[str, Any]:
    query, params = build_result_query(
        scope_name=scope_name,
        filters=filters,
        sort_rules=sort_rules,
        limit=limit,
        include_overflow_probe=True,
        diversify_prices=diversify_prices,
    )
    rows = await conn.fetch(query, *params)
    has_more = len(rows) > limit
    visible_rows = rows[:limit]

    if has_more and exact_count_enabled:
        count_query, count_params = build_total_count_query(scope_name, filters)
        total_count = int(await conn.fetchval(count_query, *count_params) or 0)
        count_meta = build_count_meta(total_count, exact=True)
    elif has_more:
        count_meta = build_count_meta(limit, exact=False)
    else:
        count_meta = build_count_meta(len(visible_rows), exact=True)

    return {
        "data": clean_records(visible_rows),
        "count": int(count_meta["count"]),
        "count_exact": bool(count_meta["exact"]),
        "count_label": count_meta["label"],
        "count_summary": count_meta["summary"],
        "displayed": len(visible_rows),
        "has_more": has_more,
        "approx_total": None if count_meta["exact"] else int(count_meta["count"]),
    }


# =========================
# APP
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    try:
        logger.info(
            "Startup auth config: ANONYMOUS_ACCESS_LEVEL=%s, AUTH_REQUIRED_FOR_DATA_ACCESS=%s, AUTH_REQUIRED_FOR_FULL_QUERY=%s, ANONYMOUS_FULL_QUERY_DAILY_LIMIT=%s",
            ANONYMOUS_ACCESS_LEVEL,
            AUTH_REQUIRED_FOR_DATA_ACCESS,
            AUTH_REQUIRED_FOR_FULL_QUERY,
            ANONYMOUS_FULL_QUERY_DAILY_LIMIT,
        )
        auth_config_payload = get_auth_config_payload()
        logger.info(
            "Startup login config: google_status=%s, password_reset_status=%s",
            auth_config_payload.get("google_status"),
            auth_config_payload.get("password_reset_status"),
        )
        db_pool = await get_db_pool()
    except Exception as e:
        print(f"Database connection failed: {e}")
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "HEAD"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    if db_pool is None:
        return Response(status_code=503)
    return Response(status_code=200)


def auth_error_response(exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "message": exc.detail,
        },
    )


def validation_error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": message,
            "message": message,
        },
    )


async def get_optional_authenticated_user(conn: asyncpg.Connection, request: Request) -> Optional[Dict[str, Any]]:
    raw_token = extract_session_token(request)
    if not raw_token:
        return None
    return await get_authenticated_user(conn, raw_token)


async def build_auth_success_response(
    request: Request,
    *,
    message: str,
    user: Dict[str, Any],
    token: Optional[str] = None,
) -> JSONResponse:
    response = JSONResponse(
        content={
            "success": True,
            "message": message,
            "token": None,
            "legacy_token": None,
            "user": user,
            "auth": await build_auth_config(request, user=user),
        }
    )
    if token:
        set_auth_session_cookie(response, token, request)
    return response


async def build_auth_config(
    request: Optional[Request] = None,
    *,
    user: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    quota_payload = await build_anonymous_full_query_quota_payload(
        request,
        is_authenticated=bool(user),
    )
    full_search_payload = await build_full_search_quota_payload(
        request,
        user=user,
    )
    require_auth_for_full_query = AUTH_REQUIRED_FOR_FULL_QUERY
    if ANONYMOUS_ACCESS_LEVEL == "full" and not user:
        require_auth_for_full_query = bool(quota_payload["anonymous_full_query_login_required"])

    return {
        **get_auth_config_payload(),
        "require_auth_for_data_access": AUTH_REQUIRED_FOR_DATA_ACCESS,
        "require_auth_for_full_query": require_auth_for_full_query,
        "anonymous_access_level": ANONYMOUS_ACCESS_LEVEL,
        "allow_anonymous_preview": ANONYMOUS_ACCESS_LEVEL in {"preview", "full"},
        "allow_anonymous_autocomplete": ANONYMOUS_AUTOCOMPLETE_ENABLED,
        "allow_anonymous_metadata": ANONYMOUS_METADATA_ENABLED,
        "anonymous_single_char_numeric_only": ANONYMOUS_SINGLE_CHAR_NUMERIC_ONLY,
        "auth_transport": "cookie",
        **quota_payload,
        **full_search_payload,
    }


async def enforce_data_access_policy(
    conn: asyncpg.Connection,
    request: Request,
    requirement: Literal["preview", "full_query", "autocomplete", "metadata"],
) -> Optional[Dict[str, Any]]:
    current_user = await get_authenticated_user(conn, extract_session_token(request) or "")

    if requirement == "full_query":
        if current_user:
            return current_user
        if ANONYMOUS_ACCESS_LEVEL == "full":
            quota = await build_anonymous_full_query_quota_payload(request, is_authenticated=False)
            if quota["anonymous_full_query_login_required"]:
                raise HTTPException(status_code=401, detail=quota["anonymous_full_query_limit_message"])
            return None
        return await require_authenticated_user(conn, request)

    if requirement == "preview":
        if ANONYMOUS_ACCESS_LEVEL in {"preview", "full"}:
            return current_user
        return current_user or await require_authenticated_user(conn, request)

    if requirement == "autocomplete":
        if ANONYMOUS_ACCESS_LEVEL in {"preview", "full"} and ANONYMOUS_AUTOCOMPLETE_ENABLED:
            return current_user
        return current_user or await require_authenticated_user(conn, request)

    if requirement == "metadata":
        if ANONYMOUS_ACCESS_LEVEL in {"preview", "full"} and ANONYMOUS_METADATA_ENABLED:
            return current_user
        return current_user or await require_authenticated_user(conn, request)

    if not AUTH_REQUIRED_FOR_DATA_ACCESS:
        return current_user
    return current_user or await require_authenticated_user(conn, request)


@app.get("/api/auth/config")
async def get_auth_config(request: Request):
    limited = await enforce_rate_limit(request, "auth-config", AUTH_CONFIG_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    return {
        "success": True,
        **await build_auth_config(request),
    }


@app.post("/api/auth/register")
async def register_user(request: Request, payload: RegisterRequest):
    limited = await enforce_rate_limit(request, "auth-register", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            result = await register_with_email(
                conn,
                request,
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
                work_unit=payload.work_unit,
                position=payload.position,
            )

        return await build_auth_success_response(
            request,
            message="Tạo tài khoản thành công.",
            user=result["user"],
            token=result["token"],
        )
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        log_server_exception("register_user failed", exc)
        return internal_error_response()


@app.post("/api/auth/login")
async def login_user(request: Request, payload: LoginRequest):
    limited = await enforce_rate_limit(request, "auth-login", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            result = await login_with_email(
                conn,
                request,
                email=payload.email,
                password=payload.password,
            )

        return await build_auth_success_response(
            request,
            message="Đăng nhập thành công.",
            user=result["user"],
            token=result["token"],
        )
    except ValueError as exc:
        return validation_error_response(str(exc), status_code=401)
    except Exception as exc:
        log_server_exception("login_user failed", exc)
        return internal_error_response()


@app.post("/api/auth/google")
async def login_user_with_google(request: Request, payload: GoogleLoginRequest):
    limited = await enforce_rate_limit(request, "auth-google", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            result = await login_with_google(
                conn,
                request,
                credential=payload.credential,
            )

        return await build_auth_success_response(
            request,
            message="Đăng nhập Google thành công.",
            user=result["user"],
            token=result["token"],
        )
    except ValueError as exc:
        return validation_error_response(str(exc), status_code=401)
    except Exception as exc:
        log_server_exception("login_user_with_google failed", exc)
        return internal_error_response()


@app.get("/api/auth/me")
async def get_current_user(request: Request):
    limited = await enforce_rate_limit(request, "auth-me", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            user = await require_authenticated_user(conn, request)

        return JSONResponse(content={
            "success": True,
            "user": user,
            "auth": await build_auth_config(request, user=user),
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("get_current_user failed", exc)
        return internal_error_response()


@app.post("/api/auth/logout")
async def logout_user(request: Request):
    limited = await enforce_rate_limit(request, "auth-logout", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await require_authenticated_user(conn, request)
            await logout_current_session(conn, request)

        response = JSONResponse(content={
            "success": True,
            "message": "Đã đăng xuất.",
        })
        clear_auth_session_cookie(response, request)
        return response
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("logout_user failed", exc)
        return internal_error_response()


@app.patch("/api/auth/profile")
async def patch_profile(request: Request, payload: ProfileUpdateRequest):
    limited = await enforce_rate_limit(request, "auth-profile", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            user = await require_authenticated_user(conn, request)
            updated_user = await update_user_profile(
                conn,
                user_id=int(user["id"]),
                full_name=payload.full_name,
                work_unit=payload.work_unit,
                position=payload.position,
            )

        return JSONResponse(content={
            "success": True,
            "message": "Cập nhật hồ sơ thành công.",
            "user": updated_user,
            "auth": await build_auth_config(request, user=updated_user),
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        log_server_exception("patch_profile failed", exc)
        return internal_error_response()


@app.post("/api/auth/forgot-password")
async def forgot_password(request: Request, payload: ForgotPasswordRequest):
    limited = await enforce_rate_limit(request, "auth-forgot-password", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await request_password_reset(conn, request, payload.email)

        return JSONResponse(content={
            "success": True,
            "message": "Đã gửi email hướng dẫn đặt lại mật khẩu.",
        })
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        log_server_exception("forgot_password failed", exc)
        return internal_error_response()


@app.post("/api/auth/reset-password")
async def reset_password(request: Request, payload: ResetPasswordRequest):
    limited = await enforce_rate_limit(request, "auth-reset-password", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            result = await reset_password_with_token(
                conn,
                request,
                token=payload.token,
                new_password=payload.new_password,
            )

        return await build_auth_success_response(
            request,
            message="Đặt lại mật khẩu thành công.",
            user=result["user"],
            token=result["token"],
        )
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        log_server_exception("reset_password failed", exc)
        return internal_error_response()


@app.post("/api/auth/change-password")
async def patch_password(request: Request, payload: ChangePasswordRequest):
    limited = await enforce_rate_limit(request, "auth-change-password", AUTH_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            user = await require_authenticated_user(conn, request)
            updated_user = await change_password(
                conn,
                request,
                user_id=int(user["id"]),
                current_password=payload.current_password,
                new_password=payload.new_password,
            )

        return JSONResponse(content={
            "success": True,
            "message": "Đổi mật khẩu thành công.",
            "user": updated_user,
            "auth": await build_auth_config(request, user=updated_user),
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        log_server_exception("patch_password failed", exc)
        return internal_error_response()


@app.post("/api/feedback")
async def create_feedback(request: Request, payload: FeedbackRequest):
    limited = await enforce_rate_limit(request, "feedback", FEEDBACK_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    answers = [
        {
            "question": str(item.question or "").strip()[:500],
            "answer": str(item.answer or "").strip()[:50],
        }
        for item in payload.answers
        if str(item.question or "").strip()
    ]
    task = (payload.task or "").strip()
    note = (payload.note or "").strip()

    if not answers and not task and not note:
        return validation_error_response("Vui lòng chọn hoặc nhập ít nhất một nội dung góp ý.")

    context = payload.context if isinstance(payload.context, dict) else {}
    page_url = str(context.get("url") or "")[:2000]
    filter_context = context.get("filters") if isinstance(context.get("filters"), dict) else {}
    user_agent = request.headers.get("user-agent", "")[:500]
    client_ip = get_client_ip(request)

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            current_user = await get_optional_authenticated_user(conn, request)
            feedback_id = await conn.fetchval(
                """
                INSERT INTO app_feedback (
                    user_id,
                    user_email,
                    answers,
                    task,
                    note,
                    page_url,
                    filter_context,
                    user_agent,
                    client_ip
                )
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::jsonb, $8, $9)
                RETURNING id
                """,
                current_user.get("id") if current_user else None,
                current_user.get("email") if current_user else None,
                json.dumps(answers, ensure_ascii=False),
                task[:4000] or None,
                note[:3000] or None,
                page_url or None,
                json.dumps(filter_context, ensure_ascii=False),
                user_agent,
                client_ip,
            )

        return {
            "success": True,
            "id": feedback_id,
            "message": "Cảm ơn bạn đã góp ý. BIDFinder đã ghi nhận phản hồi của bạn.",
        }
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("create_feedback failed", exc)
        return validation_error_response("Không thể lưu góp ý lúc này, vui lòng thử lại sau.", 500)


@app.get("/api/filter-config")
async def get_filter_config(request: Request):
    limited = await enforce_rate_limit(request, "filter-config", FILTER_CONFIG_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await enforce_data_access_policy(conn, request, "preview")

        return {
            "success": True,
            "fields": FIELD_REGISTRY
        }
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("get_filter_config failed", exc)
        return internal_error_response()


@app.post("/api/query")
async def query_data(request: Request, payload: QueryRequest):
    limited = await enforce_rate_limit(request, "query", QUERY_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        filters = payload.filters or FilterRequest()
        sort_rules = payload.sort or []
        search_mode = payload.searchMode if payload.searchMode in {"standard", "full"} else "standard"
        is_full_search = search_mode == "full"
        requested_total_limit = max(1, min(int(payload.limit or MAX_QUERY_LIMIT), MAX_QUERY_LIMIT))

        if is_full_search:
            limit = requested_total_limit
        else:
            limit = max(1, min(int(payload.limit or DEFAULT_QUERY_LIMIT), DEFAULT_QUERY_LIMIT))

        result = {
            "success": True,
            "search_mode": search_mode,
            "diversify_prices": False,
            "applied_limit_per_scope": limit,
            "applied_total_limit": limit * 2 if payload.scope == "all" and not is_full_search else limit,
        }
        count_parts: List[Dict[str, Any]] = []
        current_user: Optional[Dict[str, Any]] = None

        async with pool.acquire() as conn:
            current_user = await enforce_data_access_policy(conn, request, "full_query")

            if is_full_search:
                quota_snapshot = await get_full_search_usage_snapshot(request, current_user)
                if quota_snapshot["remaining"] <= 0:
                    raise HTTPException(status_code=429, detail=FULL_SEARCH_LIMIT_MESSAGE)

                allocation = allocate_full_search_limits(
                    scope=payload.scope,
                    total_limit=requested_total_limit,
                    medicine_count=await fetch_scope_total_count(conn, "medicine", filters) if payload.scope in ("all", "medicine") else None,
                    goods_count=await fetch_scope_total_count(conn, "goods", filters) if payload.scope in ("all", "goods") else None,
                )
            else:
                allocation = {
                    "medicine": limit,
                    "goods": limit,
                }

            if payload.scope in ("all", "medicine"):
                page = await fetch_result_page(
                    conn,
                    "medicine",
                    filters,
                    sort_rules,
                    allocation["medicine"],
                    diversify_prices=False,
                    exact_count_enabled=is_full_search or STANDARD_QUERY_EXACT_COUNT_ENABLED,
                )
                result["df1"] = page
                count_parts.append({
                    "count": page["count"],
                    "exact": page["count_exact"],
                })

            if payload.scope in ("all", "goods"):
                page = await fetch_result_page(
                    conn,
                    "goods",
                    filters,
                    sort_rules,
                    allocation["goods"],
                    diversify_prices=False,
                    exact_count_enabled=is_full_search or STANDARD_QUERY_EXACT_COUNT_ENABLED,
                )
                result["df2"] = page
                count_parts.append({
                    "count": page["count"],
                    "exact": page["count_exact"],
                })

            if is_full_search:
                quota = await consume_full_search_usage(request, current_user)
                result["full_search_daily_used"] = quota["used"]
                result["full_search_daily_remaining"] = quota["remaining"]
                result["applied_limit_per_scope"] = max(
                    int(allocation.get("medicine", 0)),
                    int(allocation.get("goods", 0)),
                )
                result["applied_total_limit"] = int(allocation.get("medicine", 0)) + int(allocation.get("goods", 0))
                result["applied_scope_limits"] = {
                    "medicine": int(allocation.get("medicine", 0)),
                    "goods": int(allocation.get("goods", 0)),
                }

            if current_user is None and ANONYMOUS_ACCESS_LEVEL == "full" and ANONYMOUS_FULL_QUERY_DAILY_LIMIT > 0:
                quota = await consume_anonymous_full_query_usage(request)
                result["anonymous_full_query_daily_used"] = quota["used"]
                result["anonymous_full_query_daily_remaining"] = quota["remaining"]
            result["auth"] = await build_auth_config(request, user=current_user)

        combined_meta = combine_count_meta(count_parts)
        result["total_count"] = int(combined_meta["count"])
        result["total_count_exact"] = bool(combined_meta["exact"])
        result["total_count_label"] = combined_meta["label"]
        result["total_count_summary"] = combined_meta["summary"]

        return JSONResponse(content=result)

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        log_server_exception("query_data failed", e)
        return internal_error_response()


@app.post("/api/bulk-query")
async def bulk_query_data(request: Request, payload: BulkQueryRequest):
    limited = await enforce_rate_limit(request, "bulk-query", QUERY_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    scope_name = payload.scope
    selected_fields = [field for field in payload.fields if field in BULK_SEARCH_FIELDS[scope_name]]
    diversity_mode = payload.diversityMode if payload.diversityMode in {"price", "product"} else "price"
    price_limit = max(1, min(int(payload.priceLimit or 3), 10))
    product_limit = max(1, min(int(payload.productLimit or 3), 10))
    search_mode = "standard"
    is_full_search = False
    result_limit = BULK_EXPORT_QUERY_LIMIT
    rows = [row for row in payload.rows if isinstance(row, dict)]

    if not selected_fields:
        return validation_error_response("Vui lòng chọn ít nhất một trường tra cứu.")
    if not rows:
        return validation_error_response("Vui lòng nhập ít nhất một dòng tra cứu.")

    try:
        pool = await ensure_db_pool()
        result_rows: List[Dict[str, Any]] = []
        total_matched = 0
        matched_input_count = 0
        result_truncated = False
        current_user: Optional[Dict[str, Any]] = None

        async with pool.acquire() as conn:
            current_user = await enforce_data_access_policy(conn, request, "full_query")
            if is_full_search:
                quota_snapshot = await get_full_search_usage_snapshot(request, current_user)
                if quota_snapshot["remaining"] <= 0:
                    raise HTTPException(status_code=429, detail=FULL_SEARCH_LIMIT_MESSAGE)

            for index, row_values in enumerate(rows, start=1):
                count_query, count_params = build_bulk_item_count_query(
                    scope_name,
                    selected_fields,
                    row_values,
                    diversity_mode,
                    price_limit,
                    product_limit,
                    index,
                )
                if not count_query:
                    continue

                row_total = int(await conn.fetchval(count_query, *count_params) or 0)
                total_matched += row_total
                if row_total > 0:
                    matched_input_count += 1
                remaining_result_slots = result_limit - len(result_rows)
                if remaining_result_slots <= 0:
                    result_truncated = result_truncated or row_total > 0
                    continue

                query, params = build_bulk_item_query(
                    scope_name,
                    selected_fields,
                    row_values,
                    diversity_mode,
                    price_limit,
                    product_limit,
                    index,
                )
                if not query:
                    continue

                records = await conn.fetch(query, *params)
                cleaned = clean_records(records)
                if len(cleaned) > remaining_result_slots:
                    cleaned = cleaned[:remaining_result_slots]
                    result_truncated = True
                if row_total > len(cleaned):
                    result_truncated = True
                query_label = " | ".join(
                    str(row_values.get(field) or "").strip()
                    for field in selected_fields
                    if str(row_values.get(field) or "").strip()
                )
                for item in cleaned:
                    item["Tra cứu hàng loạt"] = index
                    item["Dòng tra cứu"] = query_label
                    result_rows.append(item)

                if len(result_rows) >= result_limit and index < len(rows):
                    result_truncated = True

            if is_full_search:
                quota = await consume_full_search_usage(request, current_user)

        result_count_meta = build_count_meta(total_matched, exact=True)

        empty_scope = {
            "data": [],
            "count": 0,
            "count_exact": True,
            "count_label": "0",
            "count_summary": "0",
            "displayed": 0,
            "has_more": False,
            "approx_total": None,
        }
        populated_scope = {
            "data": result_rows,
            "count": int(result_count_meta["count"]),
            "count_exact": bool(result_count_meta["exact"]),
            "count_label": result_count_meta["label"],
            "count_summary": result_count_meta["summary"],
            "displayed": len(result_rows),
            "has_more": result_truncated,
            "approx_total": None,
        }
        response_payload = {
            "success": True,
            "search_mode": "bulk",
            "bulk": {
                "scope": scope_name,
                "search_mode": search_mode,
                "diversity_mode": diversity_mode,
                "input_count": len(rows),
                "matched_count": total_matched,
                "matched_input_count": matched_input_count,
                "price_limit": price_limit,
                "product_limit": product_limit,
                "fields": selected_fields,
                "result_limit": result_limit,
                "truncated": result_truncated,
            },
            "total_count": int(result_count_meta["count"]),
            "total_count_exact": bool(result_count_meta["exact"]),
            "total_count_label": result_count_meta["label"],
            "total_count_summary": result_count_meta["summary"],
            "applied_total_limit": result_limit,
            "applied_limit_per_scope": result_limit,
            "df1": populated_scope if scope_name == "medicine" else empty_scope,
            "df2": populated_scope if scope_name == "goods" else empty_scope,
            "auth": await build_auth_config(request, user=current_user),
        }
        if is_full_search:
            response_payload["full_search_daily_used"] = quota["used"]
            response_payload["full_search_daily_remaining"] = quota["remaining"]
        return response_payload
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        log_server_exception("bulk_query_data failed", e)
        return internal_error_response()


@app.post("/api/query-preview")
async def preview_query(request: Request, payload: QueryPreviewRequest):
    limited = await enforce_rate_limit(request, "query-preview", PREVIEW_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        filters = payload.filters or FilterRequest()
        result = {"success": True}

        async with pool.acquire() as conn:
            await enforce_data_access_policy(conn, request, "preview")

            if payload.scope == "medicine":
                total_meta = await fetch_preview_bucket_cached(conn, "medicine", filters, PREVIEW_BUCKET_LIMIT)
                result["df1"] = total_meta
                result["medicine_estimate"] = total_meta
            elif payload.scope == "goods":
                total_meta = await fetch_preview_bucket_cached(conn, "goods", filters, PREVIEW_BUCKET_LIMIT)
                result["df2"] = total_meta
                result["goods_estimate"] = total_meta
            else:
                total_meta = await fetch_combined_preview_meta(conn, filters, PREVIEW_BUCKET_LIMIT)

        result["total"] = int(total_meta["count"])
        result["exact"] = bool(total_meta["exact"])
        result["display"] = total_meta["label"]
        result["summary"] = total_meta["summary"]
        result["total_estimate"] = total_meta
        result["is_estimated"] = not bool(total_meta["exact"])
        result["bucket_limit"] = PREVIEW_BUCKET_LIMIT

        return JSONResponse(content=result)
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("preview_query failed", exc)
        return internal_error_response()


@app.get("/api/warmup")
async def warmup_database(request: Request):
    limited = await enforce_rate_limit(request, "warmup", METADATA_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    started = time.perf_counter()
    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await enforce_data_access_policy(conn, request, "metadata")
            query_started = time.perf_counter()
            await conn.fetchval("SELECT 1")

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        query_ms = int((time.perf_counter() - query_started) * 1000)
        return JSONResponse(content={
            "success": True,
            "elapsed_ms": elapsed_ms,
            "query_ms": query_ms,
            "suspected_wake": elapsed_ms >= 1000,
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        log_server_exception("warmup_database failed", exc)
        return internal_error_response()


@app.post("/api/autocomplete")
async def autocomplete(request: Request, payload: AutocompleteRequest):
    started = time.perf_counter()
    limited = await enforce_rate_limit(request, "autocomplete", AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        timings: Dict[str, int] = {}
        pool_started = time.perf_counter()
        pool = await ensure_db_pool()
        timings["pool_ms"] = int((time.perf_counter() - pool_started) * 1000)
        keyword = (payload.keyword or "").strip()
        if len(keyword) < 1:
            return JSONResponse(content={
                "success": True,
                "field": payload.field,
                "data": [],
                "timing_ms": {
                    "total": int((time.perf_counter() - started) * 1000),
                    **timings,
                },
            })

        raw_filters = payload.filters or {}
        filters_obj = FilterRequest(**raw_filters) if isinstance(raw_filters, dict) else FilterRequest()
        req = AutocompleteRequest(
            scope=payload.scope or "all",
            field=payload.field,
            keyword=keyword,
            filters=raw_filters,
            excludeSelf=payload.excludeSelf if payload.excludeSelf is not None else True,
            limit=max(1, min(int(payload.limit or 10), 20))
        )
        req.filters = filters_obj

        merged: List[str] = []
        seen = set()

        def push(val: Any):
            text = normalize_ws(val)
            if not text:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            merged.append(text)

        push(keyword)

        db_started = time.perf_counter()
        async with pool.acquire() as conn:
            auth_started = time.perf_counter()
            user = await enforce_data_access_policy(conn, request, "autocomplete")
            timings["auth_ms"] = int((time.perf_counter() - auth_started) * 1000)

            if (
                user is None
                and len(keyword) == 1
                and ANONYMOUS_SINGLE_CHAR_NUMERIC_ONLY
                and not keyword.isdigit()
            ):
                return validation_error_response(
                    "Autocomplete 1 ký tự cho khách chưa đăng nhập chỉ hỗ trợ chữ số. "
                    "Vui lòng nhập thêm ký tự hoặc đăng nhập để tiếp tục."
                )

            if req.scope in ("all", "medicine"):
                medicine_started = time.perf_counter()
                for item in await fetch_autocomplete_suggestions(conn, req, "medicine"):
                    push(item)
                timings["medicine_ms"] = int((time.perf_counter() - medicine_started) * 1000)

            if len(merged) < int(req.limit or 10) and req.scope in ("all", "goods"):
                goods_started = time.perf_counter()
                for item in await fetch_autocomplete_suggestions(conn, req, "goods"):
                    push(item)
                timings["goods_ms"] = int((time.perf_counter() - goods_started) * 1000)
        timings["db_ms"] = int((time.perf_counter() - db_started) * 1000)

        return JSONResponse(content={
            "success": True,
            "field": payload.field,
            "data": merged[: int(req.limit or 10)],
            "timing_ms": {
                "total": int((time.perf_counter() - started) * 1000),
                **timings,
            },
        })

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        log_server_exception("autocomplete failed", e)
        return JSONResponse(status_code=500, content={"success": False, "error": SERVER_ERROR_MESSAGE, "data": []})


@app.get("/api/metadata")
async def get_metadata(request: Request):
    limited = await enforce_rate_limit(request, "metadata", METADATA_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await enforce_data_access_policy(conn, request, "metadata")

            rows = await conn.fetch("""
                SELECT start_time, end_time, duration_seconds, boxes_selected
                FROM run_sessions
                WHERE end_time IS NOT NULL
                ORDER BY end_time DESC, start_time DESC
                LIMIT 50
            """)
            total_runs = await conn.fetchval("""
                SELECT COUNT(*)
                FROM run_sessions
                WHERE end_time IS NOT NULL
            """)
            approval_rows = await conn.fetch("""
                SELECT
                    approval_date,
                    COUNT(*)::INT AS package_count
                FROM (
                    SELECT DISTINCT
                        COALESCE(
                            ngay_phe_duyet_date,
                            CASE
                                WHEN ngay_phe_duyet ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(ngay_phe_duyet, 'DD/MM/YYYY')
                                ELSE NULL
                            END
                        ) AS approval_date,
                        ma_tbmt,
                        so_qd,
                        version
                    FROM package_metadata
                ) approvals
                WHERE approval_date IS NOT NULL
                  AND approval_date >= CURRENT_DATE - INTERVAL '365 days'
                GROUP BY approval_date
                ORDER BY approval_date ASC
            """)

        history = clean_records(rows)
        approval_timeline = [
            {
                "date": row["approval_date"].isoformat() if row["approval_date"] else None,
                "count": int(row["package_count"] or 0),
            }
            for row in approval_rows
            if row["approval_date"]
        ]
        if not history:
            return JSONResponse(content={
                "success": False,
                "message": "Chưa có lịch sử cập nhật",
                "history": [],
                "approval_timeline": approval_timeline,
            })

        return JSONResponse(content={
            "success": True,
            "history": history,
            "approval_timeline": approval_timeline,
            "last_run": history[0],
            "total_runs": int(total_runs or 0)
        })

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        log_server_exception("get_metadata failed", e)
        return internal_error_response()
