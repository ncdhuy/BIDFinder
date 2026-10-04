# -*- coding: utf-8 -*-
import argparse
import csv
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


def get_connection():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Missing DATABASE_URL")
    return psycopg2.connect(database_url)


def fetch_suspicious_groups(conn, min_qd_count):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH khlcnt_pdf_only AS (
                SELECT
                    pm.ma_khlcnt,
                    pm.ten_khlcnt,
                    pm.ma_tbmt,
                    pm.version,
                    pm.so_qd,
                    pm.cach_thuc_tai_ve,
                    p.file_path,
                    p.crawled_at,
                    pm.updated_at
                FROM package_metadata pm
                LEFT JOIN packages p
                  ON p.ma_tbmt = pm.ma_tbmt
                 AND p.so_qd = pm.so_qd
                 AND p.version = pm.version
                 AND p.file_type = 'pdf'
                WHERE pm.ma_khlcnt IS NOT NULL
                  AND pm.ma_khlcnt <> ''
                  AND pm.cach_thuc_tai_ve LIKE 'KHLCNT_NO_LINKED_TBMT:%%'
            )
            SELECT
                ma_khlcnt,
                ten_khlcnt,
                ma_tbmt,
                version,
                COUNT(*)::INT AS row_count,
                COUNT(DISTINCT so_qd)::INT AS qd_count,
                MIN(crawled_at) AS first_crawled_at,
                MAX(crawled_at) AS last_crawled_at,
                ARRAY_AGG(DISTINCT so_qd ORDER BY so_qd) AS so_qd_list
            FROM khlcnt_pdf_only
            GROUP BY ma_khlcnt, ten_khlcnt, ma_tbmt, version
            HAVING COUNT(DISTINCT so_qd) >= %s
            ORDER BY qd_count DESC, row_count DESC, ma_khlcnt, ma_tbmt, version
            """,
            (min_qd_count,),
        )
        return cur.fetchall()


def fetch_undefined_multi_qd_groups(conn, min_qd_count, khlcnt_only=False):
    khlcnt_filter = "WHERE has_khlcnt" if khlcnt_only else ""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            WITH units AS (
                SELECT DISTINCT
                    p.ma_tbmt,
                    p.so_qd,
                    p.version,
                    pm.ma_khlcnt,
                    pm.ten_khlcnt,
                    pm.cach_thuc_tai_ve,
                    p.file_type,
                    p.file_path,
                    p.crawled_at,
                    pm.updated_at
                FROM packages p
                LEFT JOIN package_metadata pm
                  ON pm.ma_tbmt = p.ma_tbmt
                 AND pm.so_qd = p.so_qd
                 AND pm.version = p.version
                WHERE p.ma_tbmt IS NOT NULL
                  AND p.ma_tbmt <> ''
                  AND p.so_qd IS NOT NULL
                  AND p.so_qd <> ''

                UNION

                SELECT DISTINCT
                    pm.ma_tbmt,
                    pm.so_qd,
                    pm.version,
                    pm.ma_khlcnt,
                    pm.ten_khlcnt,
                    pm.cach_thuc_tai_ve,
                    p.file_type,
                    p.file_path,
                    p.crawled_at,
                    pm.updated_at
                FROM package_metadata pm
                LEFT JOIN packages p
                  ON p.ma_tbmt = pm.ma_tbmt
                 AND p.so_qd = pm.so_qd
                 AND p.version = pm.version
                WHERE pm.ma_tbmt IS NOT NULL
                  AND pm.ma_tbmt <> ''
                  AND pm.so_qd IS NOT NULL
                  AND pm.so_qd <> ''
            ),
            undefined_units AS (
                SELECT u.*
                FROM units u
                LEFT JOIN qd_relations r
                  ON r.ma_tbmt = u.ma_tbmt
                 AND r.so_qd = u.so_qd
                 AND r.version = u.version
                WHERE r.ma_tbmt IS NULL
            ),
            grouped AS (
                SELECT
                    ma_tbmt,
                    COUNT(DISTINCT so_qd)::INT AS qd_count,
                    COUNT(DISTINCT (so_qd, version))::INT AS unit_count,
                    COUNT(*)::INT AS row_count,
                    BOOL_OR(ma_khlcnt IS NOT NULL AND ma_khlcnt <> '') AS has_khlcnt,
                    (COUNT(DISTINCT ma_khlcnt) FILTER (WHERE ma_khlcnt IS NOT NULL AND ma_khlcnt <> ''))::INT AS khlcnt_count,
                    ARRAY_AGG(DISTINCT so_qd ORDER BY so_qd) AS so_qd_list,
                    ARRAY_AGG(DISTINCT version ORDER BY version) AS version_list,
                    ARRAY_AGG(DISTINCT ma_khlcnt ORDER BY ma_khlcnt) FILTER (WHERE ma_khlcnt IS NOT NULL AND ma_khlcnt <> '') AS ma_khlcnt_list,
                    ARRAY_AGG(DISTINCT cach_thuc_tai_ve ORDER BY cach_thuc_tai_ve) FILTER (WHERE cach_thuc_tai_ve IS NOT NULL AND cach_thuc_tai_ve <> '') AS method_list,
                    MIN(crawled_at) AS first_crawled_at,
                    MAX(crawled_at) AS last_crawled_at
                FROM undefined_units
                GROUP BY ma_tbmt
                HAVING COUNT(DISTINCT so_qd) >= %s
            )
            SELECT *
            FROM grouped
            {khlcnt_filter}
            ORDER BY has_khlcnt DESC, qd_count DESC, unit_count DESC, ma_tbmt
            """,
            (min_qd_count,),
        )
        return cur.fetchall()


def fetch_group_rows(conn, group):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                pm.ma_khlcnt,
                pm.ten_khlcnt,
                pm.ma_tbmt,
                pm.so_qd,
                pm.version,
                pm.cach_thuc_tai_ve,
                p.file_type,
                p.file_path,
                p.crawled_at,
                pm.updated_at
            FROM package_metadata pm
            LEFT JOIN packages p
              ON p.ma_tbmt = pm.ma_tbmt
             AND p.so_qd = pm.so_qd
             AND p.version = pm.version
             AND p.file_type = 'pdf'
            WHERE pm.ma_khlcnt = %s
              AND pm.ma_tbmt = %s
              AND pm.version = %s
              AND pm.cach_thuc_tai_ve LIKE 'KHLCNT_NO_LINKED_TBMT:%%'
            ORDER BY pm.so_qd, p.crawled_at NULLS LAST
            """,
            (group["ma_khlcnt"], group["ma_tbmt"], group["version"]),
        )
        return cur.fetchall()


def fetch_undefined_multi_qd_rows(conn, group):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH units AS (
                SELECT DISTINCT
                    p.ma_tbmt,
                    p.so_qd,
                    p.version,
                    pm.ma_khlcnt,
                    pm.ten_khlcnt,
                    pm.cach_thuc_tai_ve,
                    p.file_type,
                    p.file_path,
                    p.crawled_at,
                    pm.updated_at
                FROM packages p
                LEFT JOIN package_metadata pm
                  ON pm.ma_tbmt = p.ma_tbmt
                 AND pm.so_qd = p.so_qd
                 AND pm.version = p.version
                WHERE p.ma_tbmt = %s

                UNION

                SELECT DISTINCT
                    pm.ma_tbmt,
                    pm.so_qd,
                    pm.version,
                    pm.ma_khlcnt,
                    pm.ten_khlcnt,
                    pm.cach_thuc_tai_ve,
                    p.file_type,
                    p.file_path,
                    p.crawled_at,
                    pm.updated_at
                FROM package_metadata pm
                LEFT JOIN packages p
                  ON p.ma_tbmt = pm.ma_tbmt
                 AND p.so_qd = pm.so_qd
                 AND p.version = pm.version
                WHERE pm.ma_tbmt = %s
            )
            SELECT u.*
            FROM units u
            LEFT JOIN qd_relations r
              ON r.ma_tbmt = u.ma_tbmt
             AND r.so_qd = u.so_qd
             AND r.version = u.version
            WHERE r.ma_tbmt IS NULL
            ORDER BY u.so_qd, u.version, u.file_type NULLS LAST, u.crawled_at NULLS LAST
            """,
            (group["ma_tbmt"], group["ma_tbmt"]),
        )
        return cur.fetchall()


def write_csv(path, rows):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Audit suspicious stale TBMT identity groups, especially old KHLCNT child crawls."
    )
    parser.add_argument(
        "--mode",
        choices=["undefined-multi-qd", "khlcnt-reused-tbmt", "both"],
        default="undefined-multi-qd",
        help=(
            "undefined-multi-qd: same ma_tbmt has multiple so_qd not defined in qd_relations. "
            "khlcnt-reused-tbmt: old narrow KHLCNT_NO_LINKED_TBMT pattern. both: run both."
        ),
    )
    parser.add_argument("--min-qd-count", type=int, default=2)
    parser.add_argument("--limit-groups", type=int, default=50)
    parser.add_argument("--khlcnt-only", action="store_true", help="For undefined-multi-qd mode, only show groups with KHLCNT metadata.")
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    conn = get_connection()
    try:
        expanded_rows = []
        total_groups = 0

        if args.mode in {"undefined-multi-qd", "both"}:
            groups = fetch_undefined_multi_qd_groups(conn, max(2, args.min_qd_count), khlcnt_only=args.khlcnt_only)
            total_groups += len(groups)
            print(f"Found {len(groups)} undefined multi-QD ma_tbmt group(s).")
            for index, group in enumerate(groups[: args.limit_groups], start=1):
                qd_list = ", ".join(group["so_qd_list"] or [])
                methods = " | ".join(group["method_list"] or [])
                khlcnts = ", ".join(group["ma_khlcnt_list"] or [])
                print(
                    f"\n[undefined:{index}] {group['ma_tbmt']} | {group['qd_count']} QDs | "
                    f"{group['unit_count']} units | KHLCNT={group['has_khlcnt']}"
                )
                if khlcnts:
                    print(f"    KHLCNT: {khlcnts}")
                if methods:
                    print(f"    methods: {methods[:500]}")
                print(f"    QDs: {qd_list}")
                for row in fetch_undefined_multi_qd_rows(conn, group):
                    out = dict(row)
                    out["audit_type"] = "undefined_multi_qd"
                    expanded_rows.append(out)
                    print(
                        f"    - {row['so_qd']} / v{row['version']} | "
                        f"{row.get('ma_khlcnt') or 'NO_KHLCNT'} | {row.get('cach_thuc_tai_ve') or 'NO_METHOD'} | "
                        f"{row.get('file_path') or 'NO_FILE_PATH'}"
                    )

            if len(groups) > args.limit_groups:
                print(f"\nUndefined output limited to {args.limit_groups}/{len(groups)} groups. Raise --limit-groups to see more.")

        if args.mode in {"khlcnt-reused-tbmt", "both"}:
            groups = fetch_suspicious_groups(conn, max(2, args.min_qd_count))
            total_groups += len(groups)
            print(f"\nFound {len(groups)} narrow KHLCNT_NO_LINKED_TBMT reused-TBMT group(s).")
            for index, group in enumerate(groups[: args.limit_groups], start=1):
                qd_list = ", ".join(group["so_qd_list"] or [])
                print(
                    f"\n[khlcnt:{index}] {group['ma_khlcnt']} | {group['ma_tbmt']} | v{group['version']} | "
                    f"{group['qd_count']} QDs | {group.get('ten_khlcnt') or ''}"
                )
                print(f"    QDs: {qd_list}")
                for row in fetch_group_rows(conn, group):
                    out = dict(row)
                    out["audit_type"] = "khlcnt_reused_tbmt"
                    expanded_rows.append(out)
                    print(f"    - {row['so_qd']} | {row['file_path'] or 'NO_PDF_PATH'}")

        if not total_groups:
            print("OK: no suspicious groups found for selected mode.")
            return

        if args.csv:
            write_csv(args.csv, expanded_rows)
            print(f"\nWrote detail CSV: {args.csv}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
