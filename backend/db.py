# db.py - init database lần đầu
import os
import json
import time
import psycopg2
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

import psycopg2
from urllib.parse import urlparse

def get_db_connection():
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    if DATABASE_URL:
        # Parse URL chuẩn
        parsed = urlparse(DATABASE_URL)
        conn_params = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'dbname': parsed.path[1:],
            'user': parsed.username,
            'password': parsed.password
        }
        log_step("✅ Parsed DB", f"{conn_params['host']}:{conn_params['port']}/{conn_params['dbname']}")
        return psycopg2.connect(**conn_params)
    else:
        return psycopg2.connect(
            host='localhost', port=5432, dbname='bidding_data', 
            user='postgres', password=''
        )

def log_step(step, details=""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {step} {details}")

def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.replace([np.nan, np.inf, -np.inf], None)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df

def df_to_records(df: pd.DataFrame):
    records = []
    cols = df.columns.tolist()
    for _, row in df.iterrows():
        records.append(tuple(row[c] for c in cols))
    return records, cols

def insert_chunk(cur, table_name, columns, records, chunk_size=1000):
    if not records:
        return
    cols_str = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f'INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})'
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i+chunk_size]
        cur.executemany(sql, chunk)
        log_step(f"📤 Insert {table_name}", f"chunk {i//chunk_size+1}: {len(chunk)} rows")

def main():
    start = time.time()
    log_step("🚀 DB INIT START", "="*40)

    # 1. Load files
    log_step("📂 Loading Excel/JSON...")
    df1 = clean_df(pd.read_excel("processed/columns_19_20.xlsx"))
    df2 = clean_df(pd.read_excel("processed/columns_13_14.xlsx"))
    add_info = clean_df(pd.read_excel("processed/additional_info_log.xlsx"))

    run_history_file = Path("processed/run_history.json")
    if run_history_file.exists():
        with open(run_history_file, "r", encoding="utf-8") as f:
            run_history_data = json.load(f)
    else:
        run_history_data = []

    log_step("✅ Loaded",
             f"df1={len(df1)}, df2={len(df2)}, add_info={len(add_info)}, runs={len(run_history_data)}")

    conn = None
    try:
        log_step("🔗 Connecting PostgreSQL...")
        conn = get_db_connection()
        cur = conn.cursor()

        # 2. Drop & create tables
        log_step("⚙️ Creating tables...")
        cur.execute("DROP TABLE IF EXISTS df1_standard CASCADE;")
        cur.execute("DROP TABLE IF EXISTS df2_extended CASCADE;")
        cur.execute("DROP TABLE IF EXISTS additional_info_log CASCADE;")
        cur.execute("DROP TABLE IF EXISTS run_history CASCADE;")

        cur.execute("""
        CREATE TABLE df1_standard (
                id SERIAL PRIMARY KEY,
                "Mã TBMT" TEXT,
                "Tên thuốc" TEXT,
                "Tên hoạt chất" TEXT,
                "Nồng độ, hàm lượng" TEXT,
                "Đường dùng" TEXT,
                "Dạng bào chế" TEXT,
                "Quy cách" TEXT,
                "Nhóm thuốc" TEXT,
                "GĐKLH hoặc GPNK" TEXT,
                "Cơ sở sản xuất" TEXT,
                "Xuất xứ" TEXT,
                "Đơn vị tính" TEXT,
                "Số lượng" NUMERIC,
                "Đơn giá trúng thầu (VND)" NUMERIC,
                "Thành tiền (VND)" NUMERIC,
                "Nhà thầu trúng thầu" TEXT,
                "Hạn dùng (tuổi thọ)" TEXT,
                created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE df2_extended (
                id SERIAL PRIMARY KEY,
                "Mã TBMT" TEXT,
                "Tên hàng hóa" TEXT,
                "Nhãn hiệu" TEXT,
                "Ký mã hiệu" TEXT,
                "Tính năng kỹ thuật" TEXT,
                "Xuất xứ" TEXT,
                "Hãng sản xuất" TEXT,
                "Đơn vị tính" TEXT,
                "Khối lượng" NUMERIC,
                "Đơn giá trúng thầu (VND)" NUMERIC,
                "Thành tiền (VND)" NUMERIC,
                "Nhà thầu trúng thầu" TEXT,
                "search" TEXT,
                created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE additional_info_log (
            id SERIAL PRIMARY KEY,
            "Mã TBMT" TEXT,
            "Chủ đầu tư" TEXT,
            "Quyết định phê duyệt" TEXT,
            "Ngày phê duyệt" DATE,
            "Ngày hết hiệu lực" DATE,
            "Địa điểm" TEXT,
            "Hình thức LCNT" TEXT,
            "Tình trạng hiệu lực" TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE run_history (
            id SERIAL PRIMARY KEY,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_seconds INTEGER,
            boxes_selected INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        log_step("✅ Tables created")

        # 3. Insert df1, df2, add_info
        if len(df1) > 0:
            rec1, cols1 = df_to_records(df1)
            insert_chunk(cur, "df1_standard", cols1, rec1)

        if len(df2) > 0:
            rec2, cols2 = df_to_records(df2)
            insert_chunk(cur, "df2_extended", cols2, rec2)

        if len(add_info) > 0:
            rec3, cols3 = df_to_records(add_info)
            insert_chunk(cur, "additional_info_log", cols3, rec3)

        # 4. Insert run_history
        if run_history_data:
            log_step("📤 Inserting run_history...", f"{len(run_history_data)} rows")
            sql = """
                INSERT INTO run_history (start_time, end_time, duration_seconds, boxes_selected)
                VALUES (%s, %s, %s, %s)
            """
            rows = []
            for item in run_history_data:
                rows.append((
                    item.get("start_time"),
                    item.get("end_time"),
                    item.get("duration_seconds"),
                    item.get("boxes_selected"),
                ))
            cur.executemany(sql, rows)

        # 5. Indexes
        log_step("⚙️ Creating VIEWS...")
    
        cur.execute("DROP VIEW IF EXISTS df1_full CASCADE;")
        cur.execute("DROP VIEW IF EXISTS df2_full CASCADE;")
        
        cur.execute("""
            CREATE OR REPLACE VIEW df1_full AS
            SELECT 
                d1.*,
                ai."Chủ đầu tư",
                ai."Quyết định phê duyệt",
                ai."Ngày phê duyệt",
                ai."Ngày hết hiệu lực",
                ai."Địa điểm",
                ai."Hình thức LCNT",
                ai."Tình trạng hiệu lực"
            FROM df1_standard d1
            LEFT JOIN additional_info_log ai ON ai."Mã TBMT" = d1."Mã TBMT"
        """)
        
        cur.execute("""
            CREATE OR REPLACE VIEW df2_full AS
            SELECT 
                d2.*,
                ai."Chủ đầu tư",
                ai."Quyết định phê duyệt",
                ai."Ngày phê duyệt",
                ai."Ngày hết hiệu lực", 
                ai."Địa điểm",
                ai."Hình thức LCNT",
                ai."Tình trạng hiệu lực"
            FROM df2_extended d2
            LEFT JOIN additional_info_log ai ON ai."Mã TBMT" = d2."Mã TBMT"
        """)
        
        conn.commit()
        log_step("✅ VIEWS created")
        
        log_step("⚙️ Creating INDEXES for base tables...")
        indexes = [
            'CREATE INDEX idx_df1_ma_tbmt ON df1_standard("Mã TBMT");',
            'CREATE INDEX idx_df1_donvitinh ON df1_standard("Đơn vị tính");',
            'CREATE INDEX idx_df1_soluong ON df1_standard("Số lượng");',
            'CREATE INDEX idx_df1_dongia ON df1_standard("Đơn giá trúng thầu (VND)");',
            'CREATE INDEX idx_df1_thanhtien ON df1_standard("Thành tiền (VND)");',
            'CREATE INDEX idx_df1_tenthuoc ON df1_standard("Tên thuốc");', 
            'CREATE INDEX idx_df1_xuat_xu ON df1_standard("Xuất xứ");',
            'CREATE INDEX idx_df1_nhathau ON df1_standard("Nhà thầu trúng thầu");',

            'CREATE INDEX idx_df2_ma_tbmt ON df2_extended("Mã TBMT");',
            'CREATE INDEX idx_df2_donvitinh ON df2_extended("Đơn vị tính");',
            'CREATE INDEX idx_df2_soluong ON df2_extended("Khối lượng");',
            'CREATE INDEX idx_df2_dongia ON df2_extended("Đơn giá trúng thầu (VND)");',
            'CREATE INDEX idx_df2_thanhtien ON df2_extended("Thành tiền (VND)");',
            'CREATE INDEX idx_df2_ten_hang_hoa ON df2_extended("Tên hàng hóa");',
            'CREATE INDEX idx_df2_xuat_xu ON df2_extended("Xuất xứ");',
            'CREATE INDEX idx_df2_nhathau ON df2_extended("Nhà thầu trúng thầu");',

            'CREATE INDEX idx_ai_ma_tbmt ON additional_info_log("Mã TBMT");',
            'CREATE INDEX idx_ai_chu_dau_tu ON additional_info_log("Chủ đầu tư");',
            'CREATE INDEX idx_ai_quyet_dinh ON additional_info_log("Quyết định phê duyệt");',
            'CREATE INDEX idx_ai_ngay_phe_duyet ON additional_info_log("Ngày phê duyệt");',
            'CREATE INDEX idx_ai_ngay_het_hieu_luc ON additional_info_log("Ngày hết hiệu lực");',
            'CREATE INDEX idx_ai_dia_diem ON additional_info_log("Địa điểm");',
            'CREATE INDEX idx_ai_tinh_trang ON additional_info_log("Tình trạng hiệu lực");',
        ]
        
        for idx_sql in indexes:
            cur.execute(idx_sql)
        
        log_step("✅ INDEXES created")

        # Verify
        for view_name in ["df1_full", "df2_full"]:
            cur.execute(f"SELECT COUNT(*) FROM {view_name}")
            cnt = cur.fetchone()[0]
            log_step("📊 VIEW rows", f"{view_name}: {cnt:,} rows")

        log_step("🎉 DB INIT COMPLETED", f"{time.time()-start:.1f}s")

    except Exception as e:
        if conn:
            conn.rollback()
        log_step("❌ DB INIT FAILED", str(e))
        import traceback; traceback.print_exc()
    finally:
        if conn:
            conn.close()
            log_step("🔌 CONNECTION CLOSED ========================================")

if __name__ == "__main__":
    main()
