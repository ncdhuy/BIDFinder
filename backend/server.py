from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Literal

import asyncio
import asyncpg
import json
import os
import ssl

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
db_pool: Optional[asyncpg.Pool] = None
db_pool_lock = asyncio.Lock()

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


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
        g.nha_thau_trung_thau AS "Nhà thầu trúng thầu",
        g.ten_hang_hoa AS "Tên hàng hóa",
        g.ky_ma_hieu AS "Ký mã hiệu",
        g.nhan_hieu AS "Nhãn hiệu",
        g.nam_san_xuat AS "Năm sản xuất",
        g.xuat_xu AS "Xuất xứ",
        g.hang_san_xuat AS "Hãng sản xuất",
        g.tinh_nang_ky_thuat AS "Tính năng kỹ thuật",
        g.don_vi_tinh AS "Đơn vị tính",
        g.khoi_luong AS "Khối lượng",
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
            g.ten_hang_hoa,
            g.ky_ma_hieu,
            g.nhan_hieu,
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
    "expiryDate": '"Ngày hết hiệu lực"',
    "unit": '"Đơn vị tính"',
    "unitPrice": '"Đơn giá trúng thầu (VND)"',
    "amount": '"Thành tiền (VND)"',
    "origin": '"Xuất xứ"',
    "winner": '"Nhà thầu trúng thầu"',
    "place": '"Địa điểm"',
    "validity": '"Tình trạng hiệu lực"',
}

ALLOWED_SORT_DF1 = {
    **BASE_SORT_MAP,
    "quantity": '"Số lượng"',
    "drugName": '"Tên thuốc"',
}

ALLOWED_SORT_DF2 = {
    **BASE_SORT_MAP,
    "quantity": '"Khối lượng"',
    "drugName": '"Tên hàng hóa"',
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
    return [{k: clean_value(v) for k, v in dict(r).items()} for r in records]


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
    except Exception as e:
        print(f"Database connection failed: {e}")
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    if db_pool is None:
        return Response(status_code=503)
    return Response(status_code=200)


@app.get("/api/filter-config")
async def get_filter_config():
    return {
        "success": True,
        "fields": FIELD_REGISTRY
    }


@app.post("/api/query")
async def query_data(request: QueryRequest):
    try:
        pool = await ensure_db_pool()
        filters = request.filters or FilterRequest()
        sort_rules = request.sort or []
        limit = max(1, min(request.limit or 200, 1000))

        result = {"success": True}

        async with pool.acquire() as conn:
            if request.scope in ("all", "medicine"):
                q, p, cq, cp = build_result_query("medicine", filters, sort_rules, limit)
                rows = await conn.fetch(q, *p)
                total = await conn.fetchval(cq, *cp)
                result["df1"] = {
                    "data": clean_records(rows),
                    "count": int(total),
                    "displayed": len(rows)
                }

            if request.scope in ("all", "goods"):
                q, p, cq, cp = build_result_query("goods", filters, sort_rules, limit)
                rows = await conn.fetch(q, *p)
                total = await conn.fetchval(cq, *cp)
                result["df2"] = {
                    "data": clean_records(rows),
                    "count": int(total),
                    "displayed": len(rows)
                }

        return JSONResponse(content=result)

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/autocomplete")
async def autocomplete(request: AutocompleteRequest):
    try:
        pool = await ensure_db_pool()
        keyword = (request.keyword or "").strip()
        if len(keyword) < 1:
            return JSONResponse(content={
                "success": True,
                "field": request.field,
                "data": []
            })

        raw_filters = request.filters or {}
        filters_obj = FilterRequest(**raw_filters) if isinstance(raw_filters, dict) else FilterRequest()
        req = AutocompleteRequest(
            scope=request.scope or "all",
            field=request.field,
            keyword=keyword,
            filters=raw_filters,
            excludeSelf=request.excludeSelf if request.excludeSelf is not None else True,
            limit=max(1, min(int(request.limit or 10), 20))
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
            if req.scope in ("all", "medicine"):
                for item in await fetch_autocomplete_suggestions(conn, req, "medicine"):
                    push(item)

            if req.scope in ("all", "goods"):
                for item in await fetch_autocomplete_suggestions(conn, req, "goods"):
                    push(item)

        return JSONResponse(content={
            "success": True,
            "field": request.field,
            "data": merged[: int(req.limit or 10)]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "data": []}
        )


@app.get("/api/metadata")
async def get_metadata():
    try:
        pool = await ensure_db_pool()
        query = """
        SELECT start_time, end_time, duration_seconds, boxes_selected
        FROM run_sessions
        ORDER BY start_time DESC
        LIMIT 10
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)

        history = clean_records(rows)
        if not history:
            return JSONResponse(content={"success": False, "message": "Chưa có lịch sử cập nhật", "history": []})

        return JSONResponse(content={
            "success": True,
            "history": history,
            "last_run": history[0],
            "total_runs": len(history)
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
