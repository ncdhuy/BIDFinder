# update_db.py - update hàng ngày (TRUNCATE + INSERT)
import os
import json
import time
import psycopg2
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from psycopg2.extras import execute_values

load_dotenv()

def get_db_connection():
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")

    if DATABASE_URL:
        parsed = urlparse(DATABASE_URL)

        conn_params = {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "dbname": parsed.path.lstrip("/"),   # ✅ bỏ query string
            "user": parsed.username,
            "password": parsed.password,
            "sslmode": "require",               # ✅ Neon cần SSL
        }

        # optional: log nhẹ để debug
        log_step("✅ Parsed DB", f'{conn_params["host"]}:{conn_params["port"]}/{conn_params["dbname"]}')
        return psycopg2.connect(**conn_params)

    # fallback local
    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="biddingdata",
        user="postgres",
        password=""
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

def insert_chunk(cur, table_name, columns, records, chunk_size=5000):
    if not records:
        return

    cols_str = ", ".join(f'"{c}"' for c in columns)
    sql = f'INSERT INTO "{table_name}" ({cols_str}) VALUES %s'

    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]

        # page_size = số rows per statement (đặt = len(chunk) để 1 statement/chunk)
        execute_values(cur, sql, chunk, page_size=len(chunk))

        log_step(f"📤 Insert {table_name}", f"chunk {i//chunk_size + 1}: {len(chunk)} rows")

def main():
    start = time.time()
    log_step("🚀 DAILY UPDATE START", "="*40)

    # 1. Load latest files
    log_step("📂 Loading latest Excel/JSON...")
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
        
        # 2. TRUNCATE 4 tables
        log_step("🗑️ Truncating tables...", "")
        cur.execute("TRUNCATE TABLE df1_standard RESTART IDENTITY;")
        cur.execute("TRUNCATE TABLE df2_extended RESTART IDENTITY;")
        cur.execute("TRUNCATE TABLE additional_info_log RESTART IDENTITY;")
        cur.execute("TRUNCATE TABLE run_history RESTART IDENTITY;")
        log_step("✅ Tables truncated", "")

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

        conn.commit()
        log_step("✅ Data committed", "")

        # 5. Optional: ANALYZE
        cur.execute("ANALYZE df1_standard;")
        cur.execute("ANALYZE df2_extended;")
        cur.execute("ANALYZE additional_info_log;")
        cur.execute("ANALYZE run_history;")
        conn.commit()
        log_step("✅ & Analyze completed", "")

        # 6. Verify
        for tbl in ["df1_standard", "df2_extended", "additional_info_log", "run_history"]:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            cnt = cur.fetchone()[0]
            log_step("📊 Table rows", f"{tbl}: {cnt} rows")

        log_step("🎉 DAILY UPDATE COMPLETED", f"{time.time()-start:.1f}s")

    except Exception as e:
        if conn:
            conn.rollback()
        log_step("❌ DAILY UPDATE FAILED", str(e))
        import traceback; traceback.print_exc()
    finally:
        if conn:
            conn.close()
            log_step("🔌 Connection closed ", "="*40)

if __name__ == "__main__":
    main()
