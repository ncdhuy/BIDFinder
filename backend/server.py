from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Literal
import time

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

from auth_utils import (
    ensure_auth_schema as init_auth_schema,
    get_auth_config_payload,
    login_with_email,
    login_with_google,
    logout_current_session,
    register_with_email,
    require_authenticated_user,
    update_user_profile,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
db_pool: Optional[asyncpg.Pool] = None
db_pool_lock = asyncio.Lock()
auth_schema_lock = asyncio.Lock()
rate_limit_lock = asyncio.Lock()
rate_limit_buckets: Dict[str, deque] = defaultdict(deque)
auth_schema_ready = False

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

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
METADATA_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("METADATA_RATE_LIMIT_PER_MINUTE", "20")))
FILTER_CONFIG_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("FILTER_CONFIG_RATE_LIMIT_PER_MINUTE", "30")))
AUTH_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "20")))
AUTH_CONFIG_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("AUTH_CONFIG_RATE_LIMIT_PER_MINUTE", "60")))
MAX_QUERY_LIMIT = max(50, int(os.getenv("MAX_QUERY_LIMIT", "200")))
AUTH_REQUIRED_FOR_DATA_ACCESS = os.getenv("AUTH_REQUIRED_FOR_DATA_ACCESS", "false").strip().lower() in {"1", "true", "yes", "on"}


# =========================
# DATASETS / CTE
# =========================

DF1_CTE = """
WITH df1_full AS (
    SELECT
        'medicine' AS "_dataset",
        m.ma_tbmt AS "Mã TBMT",
        m.so_qd AS "Quyết định phê duyệt",
        m.version AS "Version",
        m.ten_thuoc AS "Tên thuốc",
        m.ten_hoat_chat AS "Tên hoạt chất",
        m.nong_do_ham_luong AS "Nồng độ, hàm lượng",
        m.duong_dung AS "Đường dùng",
        m.dang_bao_che AS "Dạng bào chế",
        m.quy_cach AS "Quy cách",
        m.nhom_thuoc AS "Nhóm thuốc",
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
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        m.created_at AS "Ngày cập nhật DB",
        TO_CHAR(p.ngay_het_hieu_luc, 'DD/MM/YYYY') AS "Ngày hết hiệu lực",
        CASE
            WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
            WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
            ELSE 'Hết hiệu lực'
        END AS "Tình trạng hiệu lực"
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
        'goods' AS "_dataset",
        g.ma_tbmt AS "Mã TBMT",
        g.so_qd AS "Quyết định phê duyệt",
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
        p.hinh_thuc_lcnt AS "Hình thức LCNT",
        p.dia_diem AS "Địa điểm",
        g.created_at AS "Ngày cập nhật DB",
        TO_CHAR(p.ngay_het_hieu_luc, 'DD/MM/YYYY') AS "Ngày hết hiệu lực",
        CASE
            WHEN p.ngay_het_hieu_luc IS NULL THEN 'Chưa xác định'
            WHEN p.ngay_het_hieu_luc >= CURRENT_DATE THEN 'Còn hiệu lực'
            ELSE 'Hết hiệu lực'
        END AS "Tình trạng hiệu lực",
        CONCAT_WS(
            ' | ',
            g.ten_phan_lo,
            g.danh_muc_hang_hoa,
            g.ky_ma_hieu,
            g.nhan_hieu,
            g.mat_hang_du_thau,
            g.tinh_nang_ky_thuat
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
    drugName: Optional[TokenFilter] = None
    activeIngredient: Optional[TokenFilter] = None
    concentration: Optional[TokenFilter] = None
    route: Optional[TokenFilter] = None
    dosageForm: Optional[TokenFilter] = None
    specification: Optional[TokenFilter] = None
    drugGroup: Optional[TokenFilter] = None
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
    limit: int = 200


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
        "type": "token",
        "medicine_column": '"Nhóm thuốc"',
        "goods_column": None,
        "goods_blob_fallback": '"Search blob"',
        "autocomplete": True,
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
    "approvalDate": 'TO_DATE("Ngày phê duyệt", \'DD/MM/YYYY\')',
    "expiryDate": 'TO_DATE("Ngày hết hiệu lực", \'DD/MM/YYYY\')',
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
        max_size=20,
        command_timeout=60,
        max_inactive_connection_lifetime=300,
        setup=setup_connection,
        ssl=ssl_context,
    )


async def ensure_db_pool() -> asyncpg.Pool:
    global db_pool

    if db_pool is not None:
        await ensure_auth_schema_ready(db_pool)
        return db_pool

    async with db_pool_lock:
        if db_pool is None:
            db_pool = await get_db_pool()

    await ensure_auth_schema_ready(db_pool)
    return db_pool


async def ensure_auth_schema_ready(pool: asyncpg.Pool) -> None:
    global auth_schema_ready

    if auth_schema_ready:
        return

    async with auth_schema_lock:
        if auth_schema_ready:
            return

        async with pool.acquire() as conn:
            await init_auth_schema(conn)

        auth_schema_ready = True


def clean_value(val):
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def clean_records(records):
    return [{k: clean_value(v) for k, v in dict(r).items()} for r in records]


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    return getattr(request.client, "host", "") or "unknown"


async def enforce_rate_limit(request: Request, bucket_name: str, limit: int) -> Optional[JSONResponse]:
    client_ip = get_client_ip(request)
    cache_key = f"{bucket_name}:{client_ip}"
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
        expr = f"LOWER({column}) LIKE LOWER({p})"

        if item.op == "NOT":
            not_parts.append(f"LOWER({column}) NOT LIKE LOWER({p})")
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

        if field_type == "token":
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
        conditions.append(f'TO_DATE("Ngày phê duyệt", \'DD/MM/YYYY\') >= TO_DATE({p}, \'YYYY-MM-DD\')')

    if filters.dateTo:
        p = next_param(params, filters.dateTo)
        conditions.append(f'TO_DATE("Ngày phê duyệt", \'DD/MM/YYYY\') <= TO_DATE({p}, \'YYYY-MM-DD\')')

    return conditions


def build_result_query(scope_name: str, filters: Optional[FilterRequest], sort_rules: List[SortRule], limit: int):
    params: List[Any] = []
    cte = DF1_CTE if scope_name == "medicine" else DF2_CTE
    table_name = "df1_full" if scope_name == "medicine" else "df2_full"

    query = f"{cte} SELECT * FROM {table_name}"
    conditions = build_scope_filters(scope_name, filters, params)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    sort_map = ALLOWED_SORT_DF1 if scope_name == "medicine" else ALLOWED_SORT_DF2
    order_parts = []
    for rule in sort_rules or []:
        if rule.column in sort_map:
            order_parts.append(f"{sort_map[rule.column]} {'DESC' if rule.order == 'desc' else 'ASC'}")

    if order_parts:
        query += " ORDER BY " + ", ".join(order_parts)
    else:
        query += ' ORDER BY TO_DATE("Ngày phê duyệt", \'DD/MM/YYYY\') DESC NULLS LAST, "Mã TBMT" ASC'

    query += f" LIMIT {int(limit)}"

    count_query = f"{cte} SELECT COUNT(*) FROM {table_name}"
    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)

    return query, params, count_query, params.copy()


def build_autocomplete_query(req: AutocompleteRequest, scope_name: str):
    conf = FIELD_REGISTRY.get(req.field)
    if not conf or not conf.get("autocomplete"):
        return None, None

    column = get_column_for_scope(req.field, scope_name)
    if not column:
        return None, None

    cte = DF1_CTE if scope_name == "medicine" else DF2_CTE
    table_name = "df1_full" if scope_name == "medicine" else "df2_full"

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
        conditions.append(f"LOWER({column}) LIKE LOWER({p})")

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

    params: List[Any] = []
    cte = DF1_CTE if scope_name == "medicine" else DF2_CTE
    table_name = "df1_full" if scope_name == "medicine" else "df2_full"

    conditions = build_scope_filters(
        scope_name=scope_name,
        filters=req.filters,
        params=params,
        exclude_field=req.field if req.excludeSelf else None,
    )

    seen = set()
    results: List[str] = []

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
            SELECT DISTINCT {med_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{med_col} IS NOT NULL", f"TRIM({med_col}) <> ''", f"LOWER({med_col}) LIKE LOWER({p})"])}
            ORDER BY suggestion
            LIMIT {max(10, int(req.limit or 10))}
            """
            rows = await conn.fetch(q, *params)
            for row in rows:
                push(row["suggestion"])

    if scope_name == "goods":
        goods_col = conf.get("goods_column")
        blob_col = conf.get("goods_blob_fallback")

        if goods_col:
            params_goods = list(params)
            p = next_param(params_goods, f"%{keyword}%")
            q = f"""
            {cte}
            SELECT DISTINCT {goods_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{goods_col} IS NOT NULL", f"TRIM({goods_col}) <> ''", f"LOWER({goods_col}) LIKE LOWER({p})"])}
            ORDER BY suggestion
            LIMIT {max(10, int(req.limit or 10))}
            """
            rows = await conn.fetch(q, *params_goods)
            for row in rows:
                push(row["suggestion"])

        if blob_col:
            params_blob = list(params)
            p = next_param(params_blob, f"%{keyword}%")
            q = f"""
            {cte}
            SELECT DISTINCT {blob_col} AS suggestion
            FROM {table_name}
            WHERE {" AND ".join(conditions + [f"{blob_col} IS NOT NULL", f"TRIM({blob_col}) <> ''", f"LOWER({blob_col}) LIKE LOWER({p})"])}
            LIMIT {max(20, int(req.limit or 10) * 3)}
            """
            rows = await conn.fetch(q, *params_blob)
            for row in rows:
                push(extract_goods_snippet(row["suggestion"], keyword))

    return results


# =========================
# APP
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    try:
        db_pool = await get_db_pool()
        await ensure_auth_schema_ready(db_pool)
    except Exception as e:
        print(f"Database connection failed: {e}")
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "HEAD"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)


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


def build_auth_config() -> Dict[str, Any]:
    return {
        **get_auth_config_payload(),
        "require_auth_for_data_access": AUTH_REQUIRED_FOR_DATA_ACCESS,
    }


async def maybe_require_data_access_auth(conn: asyncpg.Connection, request: Request) -> Optional[Dict[str, Any]]:
    if not AUTH_REQUIRED_FOR_DATA_ACCESS:
        return None
    return await require_authenticated_user(conn, request)


@app.get("/api/auth/config")
async def get_auth_config(request: Request):
    limited = await enforce_rate_limit(request, "auth-config", AUTH_CONFIG_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    return {
        "success": True,
        **build_auth_config(),
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

        return JSONResponse(content={
            "success": True,
            "message": "Tạo tài khoản thành công.",
            "token": result["token"],
            "user": result["user"],
            "auth": build_auth_config(),
        })
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


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

        return JSONResponse(content={
            "success": True,
            "message": "Đăng nhập thành công.",
            "token": result["token"],
            "user": result["user"],
            "auth": build_auth_config(),
        })
    except ValueError as exc:
        return validation_error_response(str(exc), status_code=401)
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


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

        return JSONResponse(content={
            "success": True,
            "message": "Đăng nhập Google thành công.",
            "token": result["token"],
            "user": result["user"],
            "auth": build_auth_config(),
        })
    except ValueError as exc:
        return validation_error_response(str(exc), status_code=401)
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


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
            "auth": build_auth_config(),
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


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

        return JSONResponse(content={
            "success": True,
            "message": "Đã đăng xuất.",
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


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
            "auth": build_auth_config(),
        })
    except HTTPException as exc:
        return auth_error_response(exc)
    except ValueError as exc:
        return validation_error_response(str(exc))
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


@app.get("/api/filter-config")
async def get_filter_config(request: Request):
    limited = await enforce_rate_limit(request, "filter-config", FILTER_CONFIG_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await maybe_require_data_access_auth(conn, request)

        return {
            "success": True,
            "fields": FIELD_REGISTRY
        }
    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as exc:
        return validation_error_response(str(exc), status_code=500)


@app.post("/api/query")
async def query_data(request: Request, payload: QueryRequest):
    limited = await enforce_rate_limit(request, "query", QUERY_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        filters = payload.filters or FilterRequest()
        sort_rules = payload.sort or []
        limit = max(1, min(payload.limit or 200, MAX_QUERY_LIMIT))

        result = {"success": True}

        async with pool.acquire() as conn:
            await maybe_require_data_access_auth(conn, request)

            if payload.scope in ("all", "medicine"):
                q, p, cq, cp = build_result_query("medicine", filters, sort_rules, limit)
                rows = await conn.fetch(q, *p)
                total = await conn.fetchval(cq, *cp)
                result["df1"] = {
                    "data": clean_records(rows),
                    "count": int(total),
                    "displayed": len(rows)
                }

            if payload.scope in ("all", "goods"):
                q, p, cq, cp = build_result_query("goods", filters, sort_rules, limit)
                rows = await conn.fetch(q, *p)
                total = await conn.fetchval(cq, *cp)
                result["df2"] = {
                    "data": clean_records(rows),
                    "count": int(total),
                    "displayed": len(rows)
                }

        return JSONResponse(content=result)

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/autocomplete")
async def autocomplete(request: Request, payload: AutocompleteRequest):
    limited = await enforce_rate_limit(request, "autocomplete", AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        keyword = (payload.keyword or "").strip()
        if len(keyword) < 1:
            return JSONResponse(content={
                "success": True,
                "field": payload.field,
                "data": []
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

        async with pool.acquire() as conn:
            await maybe_require_data_access_auth(conn, request)

            if req.scope in ("all", "medicine"):
                for item in await fetch_autocomplete_suggestions(conn, req, "medicine"):
                    push(item)

            if req.scope in ("all", "goods"):
                for item in await fetch_autocomplete_suggestions(conn, req, "goods"):
                    push(item)

        return JSONResponse(content={
            "success": True,
            "field": payload.field,
            "data": merged[: int(req.limit or 10)]
        })

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "data": []}
        )


@app.get("/api/metadata")
async def get_metadata(request: Request):
    limited = await enforce_rate_limit(request, "metadata", METADATA_RATE_LIMIT_PER_MINUTE)
    if limited:
        return limited

    try:
        pool = await ensure_db_pool()
        async with pool.acquire() as conn:
            await maybe_require_data_access_auth(conn, request)

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

        history = clean_records(rows)
        if not history:
            return JSONResponse(content={"success": False, "message": "Chưa có lịch sử cập nhật", "history": []})

        return JSONResponse(content={
            "success": True,
            "history": history,
            "last_run": history[0],
            "total_runs": int(total_runs or 0)
        })

    except HTTPException as exc:
        return auth_error_response(exc)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
