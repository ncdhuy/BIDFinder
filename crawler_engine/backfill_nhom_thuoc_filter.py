import argparse
import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from drug_group_parser import build_drug_group_filter_array


load_dotenv()


def ensure_schema(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute("""
            ALTER TABLE processed_medicines
            ADD COLUMN IF NOT EXISTS nhom_thuoc_filter TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
        """)
        cursor.execute("""
            UPDATE processed_medicines
            SET nhom_thuoc_filter = ARRAY[]::TEXT[]
            WHERE nhom_thuoc_filter IS NULL
        """)
        cursor.execute("""
            ALTER TABLE processed_medicines
            ALTER COLUMN nhom_thuoc_filter SET DEFAULT ARRAY[]::TEXT[],
            ALTER COLUMN nhom_thuoc_filter SET NOT NULL
        """)
    conn.commit()


def ensure_index(conn) -> None:
    if conn.status != psycopg2.extensions.STATUS_READY:
        conn.rollback()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_medicines_nhom_thuoc_filter
                ON processed_medicines
                USING gin (nhom_thuoc_filter)
            """)
    finally:
        conn.autocommit = previous_autocommit


def backfill(conn, batch_size: int, dry_run: bool, ma_tbmt: str | None = None) -> int:
    total = 0
    last_id = 0
    ma_tbmt = (ma_tbmt or "").strip()

    while True:
        filters_sql = [
            "id > %s",
            """(
                nhom_thuoc_filter IS NULL
                OR nhom_thuoc_filter = ARRAY[]::TEXT[]
                OR nhom_thuoc_filter = ARRAY[nhom_thuoc]
            )""",
        ]
        params = [last_id]
        if ma_tbmt:
            filters_sql.append("ma_tbmt = %s")
            params.append(ma_tbmt)
        params.append(batch_size)

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, nhom_thuoc
                FROM processed_medicines
                WHERE {" AND ".join(filters_sql)}
                ORDER BY id
                LIMIT %s
                """,
                params,
            )
            rows = cursor.fetchall()

        if not rows:
            break

        values = [(row_id, build_drug_group_filter_array(nhom_thuoc)) for row_id, nhom_thuoc in rows]
        last_id = rows[-1][0]

        if not dry_run:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    UPDATE processed_medicines AS p
                    SET nhom_thuoc_filter = data.nhom_thuoc_filter
                    FROM (VALUES %s) AS data(id, nhom_thuoc_filter)
                    WHERE p.id = data.id
                    """,
                    values,
                    template="(%s, %s::TEXT[])",
                    page_size=batch_size,
                )
            conn.commit()

        total += len(rows)
        scope = f"ma_tbmt={ma_tbmt}; " if ma_tbmt else ""
        print(f"Backfilled {total} rows; {scope}last_id={last_id}")

    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill processed_medicines.nhom_thuoc_filter.")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--ma-tbmt", default="", help="Only backfill rows for one ma_tbmt.")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing DATABASE_URL")

    with psycopg2.connect(database_url) as conn:
        ensure_schema(conn)
        total = backfill(conn, max(1, args.batch_size), args.dry_run, ma_tbmt=args.ma_tbmt)

    if not args.skip_index and not args.dry_run:
        conn = psycopg2.connect(database_url)
        try:
            ensure_index(conn)
        finally:
            conn.close()

    print(f"Done. Rows scanned for backfill: {total}")


if __name__ == "__main__":
    main()
