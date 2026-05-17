import argparse
import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from drug_group_parser import build_drug_group_filter_array


load_dotenv()


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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing DATABASE_URL")

    with psycopg2.connect(database_url) as conn:
        total = backfill(conn, max(1, args.batch_size), args.dry_run, ma_tbmt=args.ma_tbmt)

    print(f"Done. Rows scanned for backfill: {total}")


if __name__ == "__main__":
    main()
