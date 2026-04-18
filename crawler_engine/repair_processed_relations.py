import os
from dataclasses import dataclass

import psycopg2
from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Thiếu biến môi trường DATABASE_URL trong file .env")


@dataclass
class RepairStats:
    medicines_deleted: int = 0
    goods_deleted: int = 0
    medicines_qd_updated: int = 0
    goods_qd_updated: int = 0
    medicines_qd_fallback: int = 0
    goods_qd_fallback: int = 0


MEDICINE_DELETE_SQL = """
WITH relation_clusters AS (
    SELECT
        base.ma_tbmt,
        base.so_qd_original,
        base.so_qd AS base_so_qd,
        base.version AS base_version,
        rel.so_qd AS target_so_qd,
        rel.version AS target_version
    FROM qd_relations base
    JOIN qd_relations rel
      ON rel.ma_tbmt = base.ma_tbmt
     AND rel.so_qd_original = base.so_qd_original
     AND rel.relation_type IN ('ADJUSTMENT', 'REPLACEMENT')
    WHERE base.relation_type = 'BASE'
),
duplicate_base_rows AS (
    SELECT DISTINCT b.id
    FROM processed_medicines b
    JOIN relation_clusters rc
      ON b.ma_tbmt = rc.ma_tbmt
     AND b.so_qd = rc.base_so_qd
     AND b.version = rc.base_version
    JOIN processed_medicines t
      ON t.ma_tbmt = rc.ma_tbmt
     AND t.so_qd = rc.target_so_qd
     AND t.version = rc.target_version
     AND (
            (
                NULLIF(BTRIM(b.ma_phan_lo), '') IS NOT NULL
                AND NULLIF(BTRIM(t.ma_phan_lo), '') IS NOT NULL
                AND b.ma_phan_lo = t.ma_phan_lo
            )
            OR
            (
                (
                    NULLIF(BTRIM(b.ma_phan_lo), '') IS NULL
                    OR NULLIF(BTRIM(t.ma_phan_lo), '') IS NULL
                )
                AND LOWER(BTRIM(COALESCE(b.ten_thuoc, ''))) = LOWER(BTRIM(COALESCE(t.ten_thuoc, '')))
                AND COALESCE(b.so_luong, -1) = COALESCE(t.so_luong, -1)
                AND COALESCE(b.don_gia_trung_thau, -1) = COALESCE(t.don_gia_trung_thau, -1)
            )
        )
),
deleted AS (
    DELETE FROM processed_medicines p
    USING duplicate_base_rows d
    WHERE p.id = d.id
    RETURNING p.id
)
SELECT COUNT(*) FROM deleted;
"""


GOODS_DELETE_SQL = """
WITH relation_clusters AS (
    SELECT
        base.ma_tbmt,
        base.so_qd_original,
        base.so_qd AS base_so_qd,
        base.version AS base_version,
        rel.so_qd AS target_so_qd,
        rel.version AS target_version
    FROM qd_relations base
    JOIN qd_relations rel
      ON rel.ma_tbmt = base.ma_tbmt
     AND rel.so_qd_original = base.so_qd_original
     AND rel.relation_type IN ('ADJUSTMENT', 'REPLACEMENT')
    WHERE base.relation_type = 'BASE'
),
duplicate_base_rows AS (
    SELECT DISTINCT b.id
    FROM processed_goods b
    JOIN relation_clusters rc
      ON b.ma_tbmt = rc.ma_tbmt
     AND b.so_qd = rc.base_so_qd
     AND b.version = rc.base_version
    JOIN processed_goods t
      ON t.ma_tbmt = rc.ma_tbmt
     AND t.so_qd = rc.target_so_qd
     AND t.version = rc.target_version
     AND (
            (
                NULLIF(BTRIM(b.ma_phan_lo), '') IS NOT NULL
                AND NULLIF(BTRIM(t.ma_phan_lo), '') IS NOT NULL
                AND b.ma_phan_lo = t.ma_phan_lo
            )
            OR
            (
                (
                    NULLIF(BTRIM(b.ma_phan_lo), '') IS NULL
                    OR NULLIF(BTRIM(t.ma_phan_lo), '') IS NULL
                )
                AND LOWER(BTRIM(COALESCE(b.danh_muc_hang_hoa, ''))) = LOWER(BTRIM(COALESCE(t.danh_muc_hang_hoa, '')))
                AND COALESCE(b.khoi_luong, -1) = COALESCE(t.khoi_luong, -1)
                AND COALESCE(b.don_gia_trung_thau, -1) = COALESCE(t.don_gia_trung_thau, -1)
            )
        )
),
deleted AS (
    DELETE FROM processed_goods p
    USING duplicate_base_rows d
    WHERE p.id = d.id
    RETURNING p.id
)
SELECT COUNT(*) FROM deleted;
"""


QD_DISPLAY_UPDATE_SQL_TEMPLATE = """
WITH cluster_summary AS (
    SELECT
        ma_tbmt,
        so_qd_original,
        MAX(so_qd) FILTER (WHERE relation_type = 'BASE') AS base_qd,
        STRING_AGG(DISTINCT so_qd, '; ' ORDER BY so_qd)
            FILTER (WHERE relation_type = 'CANCELLATION') AS cancellation_qds,
        STRING_AGG(DISTINCT so_qd, ', ' ORDER BY so_qd)
            FILTER (WHERE relation_type = 'ADJUSTMENT') AS adj_qds,
        STRING_AGG(DISTINCT so_qd, ', ' ORDER BY so_qd)
            FILTER (WHERE relation_type = 'REPLACEMENT') AS rep_qds
    FROM qd_relations
    GROUP BY ma_tbmt, so_qd_original
),
display_map AS (
    SELECT
        r.ma_tbmt,
        r.so_qd,
        r.version,
        CASE
            WHEN COALESCE(cs.rep_qds, '') <> '' THEN
                CONCAT(
                    COALESCE(
                        SPLIT_PART(cs.rep_qds, ', ', array_length(string_to_array(cs.rep_qds, ', '), 1)),
                        COALESCE(cs.base_qd, r.so_qd_original)
                    ),
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            WHEN COALESCE(cs.adj_qds, '') <> '' THEN
                CONCAT(
                    SPLIT_PART(cs.adj_qds, ', ', array_length(string_to_array(cs.adj_qds, ', '), 1)),
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            WHEN COALESCE(cs.base_qd, '') <> '' THEN
                CONCAT(
                    cs.base_qd,
                    CASE
                        WHEN COALESCE(cs.cancellation_qds, '') <> '' THEN '; ' || cs.cancellation_qds
                        ELSE ''
                    END
                )
            ELSE r.so_qd
        END AS qd_display
    FROM qd_relations r
    JOIN cluster_summary cs
      ON cs.ma_tbmt = r.ma_tbmt
     AND cs.so_qd_original = r.so_qd_original
),
updated AS (
    UPDATE {table_name} p
    SET qd_display = dm.qd_display
    FROM display_map dm
    WHERE p.ma_tbmt = dm.ma_tbmt
      AND p.so_qd = dm.so_qd
      AND p.version = dm.version
      AND COALESCE(p.qd_display, '') IS DISTINCT FROM COALESCE(dm.qd_display, '')
    RETURNING p.id
)
SELECT COUNT(*) FROM updated;
"""


QD_DISPLAY_FALLBACK_SQL_TEMPLATE = """
WITH updated AS (
    UPDATE {table_name}
    SET qd_display = so_qd
    WHERE COALESCE(BTRIM(qd_display), '') = ''
      AND COALESCE(BTRIM(so_qd), '') <> ''
    RETURNING id
)
SELECT COUNT(*) FROM updated;
"""


def run_scalar(cursor, sql: str) -> int:
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def ensure_qd_display_columns(cursor):
    cursor.execute("""
        ALTER TABLE processed_medicines
        ADD COLUMN IF NOT EXISTS qd_display TEXT
    """)
    cursor.execute("""
        ALTER TABLE processed_goods
        ADD COLUMN IF NOT EXISTS qd_display TEXT
    """)


def main():
    stats = RepairStats()
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor() as cursor:
                ensure_qd_display_columns(cursor)

                stats.medicines_deleted = run_scalar(cursor, MEDICINE_DELETE_SQL)
                stats.goods_deleted = run_scalar(cursor, GOODS_DELETE_SQL)

                stats.medicines_qd_updated = run_scalar(
                    cursor,
                    QD_DISPLAY_UPDATE_SQL_TEMPLATE.format(table_name="processed_medicines"),
                )
                stats.goods_qd_updated = run_scalar(
                    cursor,
                    QD_DISPLAY_UPDATE_SQL_TEMPLATE.format(table_name="processed_goods"),
                )

                stats.medicines_qd_fallback = run_scalar(
                    cursor,
                    QD_DISPLAY_FALLBACK_SQL_TEMPLATE.format(table_name="processed_medicines"),
                )
                stats.goods_qd_fallback = run_scalar(
                    cursor,
                    QD_DISPLAY_FALLBACK_SQL_TEMPLATE.format(table_name="processed_goods"),
                )

        print("Repair completed successfully.")
        print(f"processed_medicines: deleted base duplicates = {stats.medicines_deleted}")
        print(f"processed_goods: deleted base duplicates = {stats.goods_deleted}")
        print(f"processed_medicines: qd_display updated from relations = {stats.medicines_qd_updated}")
        print(f"processed_goods: qd_display updated from relations = {stats.goods_qd_updated}")
        print(f"processed_medicines: qd_display fallback from so_qd = {stats.medicines_qd_fallback}")
        print(f"processed_goods: qd_display fallback from so_qd = {stats.goods_qd_fallback}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
