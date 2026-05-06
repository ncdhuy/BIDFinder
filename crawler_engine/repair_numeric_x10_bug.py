import argparse
import csv
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")

DATASETS = {
    "medicine": {
        "table": "processed_medicines",
        "quantity_col": "so_luong",
        "label_cols": ["ma_tbmt", "so_qd", "version", "ten_thuoc", "nha_thau_trung_thau"],
    },
    "goods": {
        "table": "processed_goods",
        "quantity_col": "khoi_luong",
        "label_cols": ["ma_tbmt", "so_qd", "version", "danh_muc_hang_hoa", "nha_thau_trung_thau"],
    },
}


def decimal_or_none(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def is_close(left, right, tolerance=Decimal("0.000001")):
    left = decimal_or_none(left)
    right = decimal_or_none(right)
    if left is None or right is None:
        return False
    scale = max(Decimal(1), abs(left), abs(right))
    return abs(left - right) <= scale * tolerance


def dataset_where(quantity_col):
    return f"""
        {quantity_col} IS NOT NULL
        AND don_gia_trung_thau IS NOT NULL
        AND thanh_tien IS NOT NULL
        AND {quantity_col} <> 0
        AND don_gia_trung_thau <> 0
        AND thanh_tien <> 0
    """


def fetch_summary(cursor, dataset):
    cfg = DATASETS[dataset]
    table = cfg["table"]
    quantity_col = cfg["quantity_col"]
    where = dataset_where(quantity_col)
    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(*) FILTER (WHERE {where}) AS comparable_rows,
            COUNT(*) FILTER (
                WHERE {where}
                  AND abs(({quantity_col} * don_gia_trung_thau) - thanh_tien)
                      <= greatest(1::numeric, abs(thanh_tien)) * 0.000001
            ) AS already_consistent_rows,
            COUNT(*) FILTER (
                WHERE {where}
                  AND abs(({quantity_col} * don_gia_trung_thau) - (thanh_tien * 10))
                      <= greatest(1::numeric, abs(thanh_tien * 10)) * 0.000001
            ) AS suspected_x10_rows
        FROM {table}
        """
    )
    row = cursor.fetchone()
    return dict(row)


def fetch_samples(cursor, dataset, limit):
    cfg = DATASETS[dataset]
    table = cfg["table"]
    quantity_col = cfg["quantity_col"]
    label_cols = cfg["label_cols"]
    select_cols = ["id", *label_cols, quantity_col, "don_gia_trung_thau", "thanh_tien"]
    where = dataset_where(quantity_col)
    cursor.execute(
        f"""
        SELECT {", ".join(select_cols)}
        FROM {table}
        WHERE {where}
          AND abs(({quantity_col} * don_gia_trung_thau) - (thanh_tien * 10))
              <= greatest(1::numeric, abs(thanh_tien * 10)) * 0.000001
        ORDER BY ma_tbmt, so_qd, version, id
        LIMIT %s
        """,
        (limit,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["repaired_" + quantity_col] = decimal_or_none(row[quantity_col]) / Decimal(10)
        row["repaired_don_gia_trung_thau"] = decimal_or_none(row["don_gia_trung_thau"]) / Decimal(10)
        row["repaired_thanh_tien"] = decimal_or_none(row["thanh_tien"]) / Decimal(10)
    return rows


def write_samples(path, samples_by_dataset):
    fieldnames = []
    rows = []
    for dataset, samples in samples_by_dataset.items():
        for sample in samples:
            row = {"dataset": dataset, **sample}
            rows.append(row)
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)

    if not rows:
        return

    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def repair_dataset(cursor, dataset):
    cfg = DATASETS[dataset]
    table = cfg["table"]
    quantity_col = cfg["quantity_col"]
    where = dataset_where(quantity_col)
    cursor.execute(
        f"""
        UPDATE {table}
        SET
            {quantity_col} = {quantity_col} / 10,
            don_gia_trung_thau = don_gia_trung_thau / 10,
            thanh_tien = thanh_tien / 10
        WHERE {where}
          AND abs(({quantity_col} * don_gia_trung_thau) - (thanh_tien * 10))
              <= greatest(1::numeric, abs(thanh_tien * 10)) * 0.000001
        """
    )
    return cursor.rowcount


def ensure_backup_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS numeric_x10_repair_backup (
            run_id TEXT NOT NULL,
            dataset TEXT NOT NULL,
            processed_row_id INTEGER NOT NULL,
            ma_tbmt TEXT,
            so_qd TEXT,
            version TEXT,
            old_quantity NUMERIC,
            old_don_gia_trung_thau NUMERIC,
            old_thanh_tien NUMERIC,
            backed_up_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def backup_dataset(cursor, dataset, run_id):
    cfg = DATASETS[dataset]
    table = cfg["table"]
    quantity_col = cfg["quantity_col"]
    where = dataset_where(quantity_col)
    cursor.execute(
        f"""
        INSERT INTO numeric_x10_repair_backup (
            run_id,
            dataset,
            processed_row_id,
            ma_tbmt,
            so_qd,
            version,
            old_quantity,
            old_don_gia_trung_thau,
            old_thanh_tien
        )
        SELECT
            %s,
            %s,
            id,
            ma_tbmt,
            so_qd,
            version,
            {quantity_col},
            don_gia_trung_thau,
            thanh_tien
        FROM {table}
        WHERE {where}
          AND abs(({quantity_col} * don_gia_trung_thau) - (thanh_tien * 10))
              <= greatest(1::numeric, abs(thanh_tien * 10)) * 0.000001
        """,
        (run_id, dataset),
    )
    return cursor.rowcount


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit/repair rows affected by the old numeric x10 double-cleaning bug."
    )
    parser.add_argument(
        "--scope",
        choices=["all", "medicine", "goods"],
        default="all",
        help="Dataset to audit or repair.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=50,
        help="Number of suspected rows to print/export per dataset.",
    )
    parser.add_argument(
        "--output-csv",
        help="Optional CSV path for suspected-row samples.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually update suspected rows. Without this flag the script is dry-run only.",
    )
    return parser.parse_args()


def main():
    if not DATABASE_URL:
        raise ValueError("Missing DATABASE_URL in crawler_engine/.env")

    args = parse_args()
    datasets = ["medicine", "goods"] if args.scope == "all" else [args.scope]
    samples_by_dataset = {}

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            print("Mode:", "APPLY" if args.apply else "DRY-RUN")
            print()

            for dataset in datasets:
                summary = fetch_summary(cursor, dataset)
                print(f"[{dataset}]")
                print(f"  total_rows: {summary['total_rows']}")
                print(f"  comparable_rows: {summary['comparable_rows']}")
                print(f"  already_consistent_rows: {summary['already_consistent_rows']}")
                print(f"  suspected_x10_rows: {summary['suspected_x10_rows']}")

                samples = fetch_samples(cursor, dataset, max(0, args.sample_limit))
                samples_by_dataset[dataset] = samples
                for sample in samples[:5]:
                    quantity_col = DATASETS[dataset]["quantity_col"]
                    print(
                        "  sample",
                        sample["id"],
                        sample["ma_tbmt"],
                        sample["so_qd"],
                        "old=",
                        sample[quantity_col],
                        sample["don_gia_trung_thau"],
                        sample["thanh_tien"],
                        "new=",
                        sample["repaired_" + quantity_col],
                        sample["repaired_don_gia_trung_thau"],
                        sample["repaired_thanh_tien"],
                    )
                print()

            if args.output_csv:
                write_samples(args.output_csv, samples_by_dataset)
                print(f"Wrote sample CSV: {args.output_csv}")

            if args.apply:
                run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                ensure_backup_table(cursor)
                print(f"Backup run_id: {run_id}")
                for dataset in datasets:
                    backed_up = backup_dataset(cursor, dataset, run_id)
                    updated = repair_dataset(cursor, dataset)
                    print(f"Backed up {backed_up} and updated {updated} {dataset} rows.")
            else:
                conn.rollback()
                print("Dry-run only. Re-run with --apply to update suspected rows.")


if __name__ == "__main__":
    main()
