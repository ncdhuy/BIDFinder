from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, List
import asyncpg
from fastapi import Response
import json
from pathlib import Path
import os
import re


# ========== DATABASE CONFIG ==========
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool: Optional[asyncpg.Pool] = None

# ========== PYDANTIC MODELS ==========
class FilterRequest(BaseModel):
    investor: Optional[str] = None
    selectionMethod: Optional[List[str]] = None
    approvalDecision: Optional[str] = None
    drugName: Optional[str] = None
    activeIngredient: Optional[str] = None
    concentration: Optional[str] = None
    route: Optional[str] = None
    dosageForm: Optional[str] = None
    specification: Optional[str] = None
    drugGroup: Optional[str] = None
    regNo: Optional[str] = None
    unit: Optional[str] = None
    manufacturer: Optional[str] = None
    country: Optional[str] = None
    place: Optional[List[str]] = None
    validity: Optional[str] = None
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None

class SortRule(BaseModel):
    column: str
    order: str  # 'asc' or 'desc'

class QueryRequest(BaseModel):
    filters: Optional[FilterRequest] = None
    sort: Optional[List[SortRule]] = None
    limit: Optional[int] = 200

# ========== DATABASE HELPERS ==========
# ========== DATABASE HELPERS ==========
async def get_db_pool():
    """Tạo connection pool"""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")

    return await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,          # Render free nên để thấp
        max_size=10,
        command_timeout=60,
        # Nếu Neon yêu cầu SSL mà DSN không đủ thì bật dòng dưới:
        # ssl="require",
    )

def clean_value(val):
    """Clean giá trị để JSON serializable"""
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)

def clean_records(records):
    """Fix cho JOIN duplicate columns"""
    cleaned = []
    for record in records:
        if isinstance(record, dict):  # Normal Record
            cleaned.append({k: clean_value(v) for k, v in record.items()})
        elif isinstance(record, list):  # Duplicate column → list
            # Chuyển list thành dict, ưu tiên giá trị cuối (ai.*)
            cleaned.append({f"col_{i}": clean_value(record[i]) for i in range(len(record))})
        else:
            cleaned.append({"raw": clean_value(record)})
    return cleaned


# ========== QUERY BUILDER ==========
def parse_search_query(query_text: str):
    """
    Parse search query với các operators:
    - +term: must have
    - -term: must not have
    - "phrase": exact phrase
    - term1 OR term2: at least one
    """
    if not query_text:
        return None
    
    result = {
        'must_have': [],
        'must_not_have': [],
        'should_have': [],
        'phrases': []
    }
    
    # Extract phrases
    phrase_pattern = r'"([^"]+)"'
    phrases = re.findall(phrase_pattern, query_text)
    result['phrases'] = phrases
    remaining = re.sub(phrase_pattern, '', query_text)
    
    # Split by OR
    or_parts = remaining.split(' OR ')
    
    if len(or_parts) > 1:
        # Has OR
        for part in or_parts:
            terms = part.strip().split()
            for term in terms:
                if term.startswith('-'):
                    result['must_not_have'].append(term[1:])
                elif term.startswith('+'):
                    result['must_have'].append(term[1:])
                elif term:
                    result['should_have'].append(term)
    else:
        # No OR, all terms are AND
        terms = remaining.strip().split()
        for term in terms:
            if term.startswith('-'):
                result['must_not_have'].append(term[1:])
            elif term.startswith('+'):
                result['must_have'].append(term[1:])
            elif term:
                result['must_have'].append(term)
    
    return result

def build_text_search_condition(column: str, query_text: str, params: dict, param_counter: list):
    """
    Build PostgreSQL text search condition
    Returns: (condition_string, updated_params)
    """
    if not query_text:
        return None
    
    parsed = parse_search_query(query_text)
    if not parsed:
        return None
    
    conditions = []
    
    # Must have terms (AND)
    for term in parsed['must_have']:
        param_name = f"p{param_counter[0]}"
        param_counter[0] += 1
        params[param_name] = f"%{term}%"
        conditions.append(f'LOWER({column}) LIKE LOWER(${param_name})')
    
    # Must not have terms
    for term in parsed['must_not_have']:
        param_name = f"p{param_counter[0]}"
        param_counter[0] += 1
        params[param_name] = f"%{term}%"
        conditions.append(f'LOWER({column}) NOT LIKE LOWER(${param_name})')
    
    # Should have terms (OR)
    if parsed['should_have']:
        or_conditions = []
        for term in parsed['should_have']:
            param_name = f"p{param_counter[0]}"
            param_counter[0] += 1
            params[param_name] = f"%{term}%"
            or_conditions.append(f'LOWER({column}) LIKE LOWER(${param_name})')
        if or_conditions:
            conditions.append(f"({' OR '.join(or_conditions)})")
    
    # Exact phrases
    for phrase in parsed['phrases']:
        param_name = f"p{param_counter[0]}"
        param_counter[0] += 1
        params[param_name] = f"%{phrase}%"
        conditions.append(f'LOWER({column}) LIKE LOWER(${param_name})')
    
    return ' AND '.join(conditions) if conditions else None

def replace_params(query: str, params: dict) -> tuple[str, list]:
    """Thay $pN → $1, $2... và trả positional params"""
    param_values = []
    query_pos = query
    
    for i, (key, value) in enumerate(params.items(), 1):
        query_pos = query_pos.replace(f'${key}', f'${i}')
        param_values.append(value)
    
    return query_pos, param_values

# base mapping (áp dụng chung cho cả df1_full, df2_full)
BASE_SORT_MAP = {
    "ma_tbmt": '"Mã TBMT"',
    "investor": '"Chủ đầu tư"',
    "approvalDecision": '"Quyết định phê duyệt"',
    "approvalDate": '"Ngày phê duyệt"',
    "expiryDate": '"Ngày hết hiệu lực"',
    "unit": '"Đơn vị tính"',
    "unitPrice": '"Đơn giá trúng thầu (VND)"',
    "amount": '"Thành tiền (VND)"',
    "origin": '"Xuất xứ"',
    "winner": '"Nhà thầu trúng thầu"',
    "place": '"Địa điểm"',
    "validity": '"Tình trạng hiệu lực"'
}

ALLOWED_SORT_DF1 = {
    **BASE_SORT_MAP,
    "quantity": '"Số lượng"',
    "drugName": '"Tên thuốc"'
}

ALLOWED_SORT_DF2 = {
    **BASE_SORT_MAP,
    "quantity": '"Khối lượng"',
    "drugName": '"Tên hàng hóa"'
}

def build_df1_query(filters: FilterRequest, sort_rules: List[SortRule], limit: int):
    """Query df1_full VIEW - SIÊU GỌN!"""
    query = 'SELECT * FROM df1_full'
    conditions = []
    params = {}
    param_counter = [1]
    allowed_sort = ALLOWED_SORT_DF1

    if filters:
        # ✅ Text filters (có sẵn trong VIEW)
        text_filters = {
            '"Tên thuốc"': filters.drugName,
            '"Tên hoạt chất"': filters.activeIngredient,
            '"Nồng độ, hàm lượng"': filters.concentration,
            '"Đường dùng"': filters.route,
            '"Dạng bào chế"': filters.dosageForm,
            '"Quy cách"': filters.specification,
            '"Nhóm thuốc"': filters.drugGroup,
            '"GĐKLH hoặc GPNK"': filters.regNo,
            '"Đơn vị tính"': filters.unit,
            '"Cơ sở sản xuất"': filters.manufacturer,
            '"Xuất xứ"': filters.country,
            '"Chủ đầu tư"': filters.investor,
            '"Quyết định phê duyệt"': filters.approvalDecision,
        }

        for column, query_text in text_filters.items():
            if query_text:
                condition = build_text_search_condition(column, query_text, params, param_counter)
                if condition:
                    conditions.append(condition)

        # Array filters
        if filters.selectionMethod:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.selectionMethod
            conditions.append(f'"Hình thức LCNT" = ANY(${p})')

        if filters.place:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.place
            conditions.append(f'"Địa điểm" = ANY(${p})')

        # Exact match
        if filters.validity:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.validity
            conditions.append(f'"Tình trạng hiệu lực" = ${p}')

        # Date range
        if filters.dateFrom:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.dateFrom
            conditions.append(f'"Ngày phê duyệt" >= ${p}')

        if filters.dateTo:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.dateTo
            conditions.append(f'"Ngày phê duyệt" <= ${p}')

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    # ===== ORDER BY =====
    default_order = ' ORDER BY "Ngày phê duyệt" DESC NULLS LAST, "Mã TBMT" ASC'

    order_clauses = []
    if sort_rules:
        for r in sort_rules:
            col = allowed_sort.get(r.column)
            if not col:
                continue
            direction = "DESC" if r.order == "desc" else "ASC"
            order_clauses.append(f"{col} {direction}")

    if order_clauses:
        query += ' ORDER BY ' + ', '.join(order_clauses)
    else:
        query += default_order

    query += f' LIMIT {limit}'

    base_query = re.sub(r' ORDER BY .*? LIMIT \d+$', '', query)
    count_query = f'SELECT COUNT(*) FROM ({base_query}) AS subq'

    return query, params, count_query

def build_df2_query(filters: FilterRequest, sort_rules: List[SortRule], limit: int):
    """Tương tự df1, chỉ đổi tên columns"""
    query = 'SELECT * FROM df2_full'
    conditions = []
    params = {}
    param_counter = [1]
    allowed_sort = ALLOWED_SORT_DF2

    if filters:
        text_filters = {
            '"Tên hàng hóa"': filters.drugName,
            '"Nhãn hiệu"': filters.manufacturer,
            '"Tính năng kỹ thuật"': filters.specification,
            '"Xuất xứ"': filters.country,
            '"Đơn vị tính"': filters.unit,
            '"Chủ đầu tư"': filters.investor,
            '"Quyết định phê duyệt"': filters.approvalDecision,
        }

        for column, query_text in text_filters.items():
            if query_text:
                condition = build_text_search_condition(column, query_text, params, param_counter)
                if condition:
                    conditions.append(condition)

        # Array + exact + date (giống df1)
        if filters.selectionMethod:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.selectionMethod
            conditions.append(f'"Hình thức LCNT" = ANY(${p})')

        if filters.place:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.place
            conditions.append(f'"Địa điểm" = ANY(${p})')

        if filters.validity:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.validity
            conditions.append(f'"Tình trạng hiệu lực" = ${p}')

        if filters.dateFrom:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.dateFrom
            conditions.append(f'"Ngày phê duyệt" >= ${p}')

        if filters.dateTo:
            p = f"p{param_counter[0]}"; param_counter[0] += 1
            params[p] = filters.dateTo
            conditions.append(f'"Ngày phê duyệt" <= ${p}')

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    # ===== ORDER BY =====
    default_order = ' ORDER BY "Ngày phê duyệt" DESC NULLS LAST, "Mã TBMT" ASC'

    order_clauses = []
    if sort_rules:
        for r in sort_rules:
            col = allowed_sort.get(r.column)
            if not col:
                continue
            direction = "DESC" if r.order == "desc" else "ASC"
            order_clauses.append(f"{col} {direction}")

    if order_clauses:
        query += ' ORDER BY ' + ', '.join(order_clauses)
    else:
        query += default_order

    query += f' LIMIT {limit}'

    base_query = re.sub(r' ORDER BY .*? LIMIT \d+$', '', query)
    count_query = f'SELECT COUNT(*) FROM ({base_query}) AS subq'

    return query, params, count_query


# ========== LIFESPAN ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    
    print("=" * 60)
    print("🚀 SERVER STARTING UP")
    print("=" * 60)
    
    try:
        db_pool = await get_db_pool()
        print(f"✅ Connected to PostgreSQL")
        
        async with db_pool.acquire() as conn:
            count1 = await conn.fetchval("SELECT COUNT(*) FROM df1_standard")
            count2 = await conn.fetchval("SELECT COUNT(*) FROM df2_extended")
            print(f"📊 df1_standard: {count1:,} rows")
            print(f"📊 df2_extended: {count2:,} rows")
            
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise
    
    print("=" * 60)
    print("✅ SERVER READY")
    print("=" * 60)
    
    yield
    
    if db_pool:
        await db_pool.close()
        print("🛑 Database pool closed")

# ========== FASTAPI APP ==========
app = FastAPI(lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
assets_dir = BASE_DIR / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        # "https://muasamcong.vn"
    ],
    allow_origin_regex=r"^https://.*\.netlify\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# @app.get("/")
# def root():
#     return FileResponse("index.html")

# @app.get("/style.css")
# def get_css():
#     return FileResponse("style.css", media_type="text/css")

# @app.get("/script.js")
# def get_script():
#     return FileResponse("script.js", media_type="application/javascript")

# @app.get("/search-form.js")
# def get_search_form():
#     return FileResponse("search-form.js", media_type="application/javascript")



@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return Response(status_code=200)


@app.get("/api/metadata")
async def get_metadata():
    """Trả về metadata"""
    try:
        query = """
            SELECT end_time, duration_seconds, boxes_selected
            FROM run_history
            ORDER BY created_at DESC
            LIMIT 10
        """
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query)
            history = [dict(row) for row in rows]
        
        if history:
            return JSONResponse(content={
                "success": True,
                "history": clean_records(history),
                "last_run": clean_records([history[0]])[0],
                "total_runs": len(history)
            })
        
        # Fallback to JSON file
        file_path = "processed/run_history.json"
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            return JSONResponse(content={
                "success": True,
                "history": history,
                "total_runs": len(history)
            })
        
        return JSONResponse(content={
            "success": False,
            "message": "Chưa có lịch sử cập nhật",
            "history": []
        })
        
    except Exception as e:
        print(f"❌ Error getting metadata: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

# ========== OLD ENDPOINTS (Backward compatible) ==========
@app.get("/api/df1")
async def get_df1():
    """Get tất cả df1 (backward compatible)"""
    try:
        query = 'SELECT * FROM df1_standard ORDER BY created_at DESC, "Mã TBMT" ASC LIMIT 1000'
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query)
            data = [dict(row) for row in rows]
        
        return JSONResponse(content={
            "success": True,
            "data": clean_records(data),
            "count": len(data)
        })
        
    except Exception as e:
        print(f"❌ Error getting df1: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "data": []}
        )

@app.get("/api/df2")
async def get_df2():
    """Get tất cả df2 (backward compatible)"""
    try:
        query = 'SELECT * FROM df2_extended ORDER BY "Ngày phê duyệt" DESC LIMIT 1000'
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query)
            data = [dict(row) for row in rows]
        
        return JSONResponse(content={
            "success": True,
            "data": clean_records(data),
            "count": len(data)
        })
        
    except Exception as e:
        print(f"❌ Error getting df2: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "data": []}
        )

# ========== NEW ENDPOINTS (With filter/sort) ==========
@app.post("/api/query")
async def query_data(request: QueryRequest):
    try:
        limit = request.limit or 200
        
        # Build queries
        q1, p1, cq1 = build_df1_query(request.filters or FilterRequest(), request.sort or [], limit)
        q2, p2, cq2 = build_df2_query(request.filters or FilterRequest(), request.sort or [], limit)
        
        print(f"📊 Query DF1: {q1[:200]}...")
        print(f"📊 Query DF2: {q2[:200]}...")
        
        # ✅ DATA: thay params → execute
        q1_pos, data1_params = replace_params(q1, p1)
        q2_pos, data2_params = replace_params(q2, p2)
        
        async with db_pool.acquire() as conn:
            # Data queries
            rows1 = await conn.fetch(q1_pos, *data1_params)
            data1 = [dict(row) for row in rows1]
            
            rows2 = await conn.fetch(q2_pos, *data2_params)
            data2 = [dict(row) for row in rows2]
            
            # ✅ COUNT: thay params → execute
            cq1_pos, count1_params = replace_params(cq1, p1)
            cq2_pos, count2_params = replace_params(cq2, p2)
            
            total1 = await conn.fetchval(cq1_pos, *count1_params)
            total2 = await conn.fetchval(cq2_pos, *count2_params)
        
        return JSONResponse(content={
            "success": True,
            "df1": {
                "data": clean_records(data1), 
                "count": int(total1),
                "displayed": len(data1)
            },
            "df2": {
                "data": clean_records(data2),
                "count": int(total2), 
                "displayed": len(data2)
            }
        })
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

