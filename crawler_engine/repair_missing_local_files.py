import argparse
import csv
import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


def path_missing(path_value):
    return bool(path_value) and os.path.isabs(str(path_value)) and not os.path.exists(str(path_value))


def fetch_missing_packages(cursor):
    cursor.execute(
        """
        SELECT ma_tbmt, so_qd, version, file_type, file_path, status, is_latest, crawled_at
        FROM packages
        WHERE file_path IS NOT NULL
        ORDER BY ma_tbmt, so_qd, version, file_type
        """
    )
    return [dict(row) for row in cursor.fetchall() if path_missing(row["file_path"])]


def fetch_missing_manifest(cursor):
    cursor.execute(
        """
        SELECT id, manifest_date, ma_tbmt, so_qd, version, filename, schema_type, status, full_path
        FROM daily_manifest
        WHERE full_path IS NOT NULL
        ORDER BY manifest_date, ma_tbmt, so_qd, version
        """
    )
    return [dict(row) for row in cursor.fetchall() if path_missing(row["full_path"])]


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_recrawl_keywords(path, missing_packages, missing_manifest):
    tbmts = {
        str(row["ma_tbmt"]).strip()
        for row in [*missing_packages, *missing_manifest]
        if row.get("ma_tbmt")
    }
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(sorted(tbmts)))
        if tbmts:
            handle.write("\n")
    return len(tbmts)


def sync_manifest_from_existing_packages(cursor, schema=None):
    schema_filter = ""
    params = []
    if schema:
        schema_filter = "AND m.schema_type = %s"
        params.append(schema)

    cursor.execute(
        f"""
        SELECT m.id,
               p.file_path
        FROM daily_manifest m
        JOIN packages p
          ON p.ma_tbmt = m.ma_tbmt
         AND p.so_qd = m.so_qd
         AND p.version = m.version
         AND p.file_type = 'excel'
        WHERE m.full_path IS NOT NULL
          {schema_filter}
        """,
        tuple(params),
    )

    updates = []
    for row in cursor.fetchall():
        manifest_id = row["id"]
        package_path = row["file_path"]
        if not package_path or not os.path.exists(package_path):
            continue
        updates.append(
            (
                os.path.basename(package_path),
                package_path,
                round(os.path.getsize(package_path) / 1024, 2),
                manifest_id,
            )
        )

    if not updates:
        return 0

    psycopg2.extras.execute_batch(
        cursor,
        """
        UPDATE daily_manifest
        SET filename = %s,
            full_path = %s,
            file_size_kb = %s
        WHERE id = %s
          AND (full_path IS DISTINCT FROM %s OR filename IS DISTINCT FROM %s)
        """,
        [(filename, full_path, size_kb, manifest_id, full_path, filename) for filename, full_path, size_kb, manifest_id in updates],
        page_size=500,
    )
    return cursor.rowcount


def parse_args():
    parser = argparse.ArgumentParser(description="Audit and repair missing local package/manifest file paths.")
    parser.add_argument("--out-dir", default=os.path.join("crawler_engine", "reports"))
    parser.add_argument("--sync-manifest", action="store_true", help="Update daily_manifest full_path from existing packages excel paths.")
    parser.add_argument(
        "--schema",
        choices=["MEDICINE_STANDARD", "GOODS_STANDARD"],
        help="Limit manifest sync to one schema.",
    )
    return parser.parse_args()


def main():
    if not DATABASE_URL:
        raise ValueError("Missing DATABASE_URL in crawler_engine/.env")

    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            if args.sync_manifest:
                updated = sync_manifest_from_existing_packages(cursor, schema=args.schema)
                print(f"synced manifest rows from existing package paths: {updated}")

            missing_packages = fetch_missing_packages(cursor)
            missing_manifest = fetch_missing_manifest(cursor)

            package_csv = os.path.join(args.out_dir, "missing_packages_files.csv")
            manifest_csv = os.path.join(args.out_dir, "missing_manifest_files.csv")
            keyword_txt = os.path.join(args.out_dir, "recrawl_missing_tbmts.txt")

            write_csv(
                package_csv,
                missing_packages,
                ["ma_tbmt", "so_qd", "version", "file_type", "file_path", "status", "is_latest", "crawled_at"],
            )
            write_csv(
                manifest_csv,
                missing_manifest,
                ["id", "manifest_date", "ma_tbmt", "so_qd", "version", "filename", "schema_type", "status", "full_path"],
            )
            keyword_count = export_recrawl_keywords(keyword_txt, missing_packages, missing_manifest)

            print(f"missing package file records: {len(missing_packages)} -> {package_csv}")
            print(f"missing manifest file records: {len(missing_manifest)} -> {manifest_csv}")
            print(f"distinct TBMTs to recrawl: {keyword_count} -> {keyword_txt}")


if __name__ == "__main__":
    main()
