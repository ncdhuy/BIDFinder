import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv


CURRENT_DIR = Path(__file__).resolve().parent

load_dotenv(CURRENT_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Thiếu biến môi trường DATABASE_URL trong file .env")


EXPAND_CLUSTER_SQL = """
WITH seed_units AS (
    SELECT DISTINCT
        ma_tbmt,
        so_qd,
        version
    FROM repair_seed_units
),
seed_with_rel AS (
    SELECT
        s.ma_tbmt,
        s.so_qd,
        s.version,
        qr.so_qd_original
    FROM seed_units s
    LEFT JOIN qd_relations qr
      ON qr.ma_tbmt = s.ma_tbmt
     AND qr.so_qd = s.so_qd
     AND qr.version = s.version
),
cluster_keys AS (
    SELECT DISTINCT
        ma_tbmt,
        COALESCE(so_qd_original, so_qd) AS so_qd_original
    FROM seed_with_rel
),
expanded_relation_units AS (
    SELECT DISTINCT
        qr.ma_tbmt,
        qr.so_qd,
        qr.version,
        qr.relation_type,
        qr.so_qd_original
    FROM qd_relations qr
    JOIN cluster_keys ck
      ON ck.ma_tbmt = qr.ma_tbmt
     AND ck.so_qd_original = qr.so_qd_original
),
expanded_units AS (
    SELECT
        eru.ma_tbmt,
        eru.so_qd,
        eru.version,
        COALESCE(dm.schema_type, 'UNKNOWN') AS schema_type,
        eru.relation_type,
        eru.so_qd_original
    FROM expanded_relation_units eru
    LEFT JOIN daily_manifest dm
      ON dm.ma_tbmt = eru.ma_tbmt
     AND dm.so_qd = eru.so_qd
     AND dm.version = eru.version

    UNION

    SELECT
        s.ma_tbmt,
        s.so_qd,
        s.version,
        COALESCE(dm.schema_type, 'UNKNOWN') AS schema_type,
        COALESCE(qr.relation_type, 'UNMATCHED') AS relation_type,
        COALESCE(qr.so_qd_original, s.so_qd) AS so_qd_original
    FROM seed_units s
    LEFT JOIN daily_manifest dm
      ON dm.ma_tbmt = s.ma_tbmt
     AND dm.so_qd = s.so_qd
     AND dm.version = s.version
    LEFT JOIN qd_relations qr
      ON qr.ma_tbmt = s.ma_tbmt
     AND qr.so_qd = s.so_qd
     AND qr.version = s.version
)
SELECT DISTINCT
    ma_tbmt,
    so_qd,
    version,
    schema_type,
    relation_type,
    so_qd_original
FROM expanded_units
ORDER BY ma_tbmt, so_qd, version;
"""


COUNT_PROCESSED_SQL = """
SELECT COUNT(*)
FROM {table_name}
WHERE (ma_tbmt, so_qd, version) IN (
    SELECT ma_tbmt, so_qd, version
    FROM repair_target_units
    WHERE schema_type = %s
);
"""


DELETE_PROCESSED_SQL = """
DELETE FROM {table_name}
WHERE (ma_tbmt, so_qd, version) IN (
    SELECT ma_tbmt, so_qd, version
    FROM repair_target_units
    WHERE schema_type = %s
);
"""


COUNT_MANIFEST_SQL = """
SELECT COUNT(*)
FROM daily_manifest
WHERE (ma_tbmt, so_qd, version) IN (
    SELECT ma_tbmt, so_qd, version
    FROM repair_target_units
);
"""


RESET_MANIFEST_SQL = """
UPDATE daily_manifest
SET status = 'READY'
WHERE (ma_tbmt, so_qd, version) IN (
    SELECT ma_tbmt, so_qd, version
    FROM repair_target_units
);
"""


DELETE_ISSUES_SQL = """
DELETE FROM manifest_issues
WHERE (ma_tbmt, so_qd, version) IN (
    SELECT ma_tbmt, so_qd, version
    FROM repair_target_units
);
"""


def normalize_version(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def load_seed_units(audit_path: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(audit_path, sheet_name=sheet_name)
    required = {"ma_tbmt", "so_qd", "version"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Sheet '{sheet_name}' thiếu cột bắt buộc: {sorted(missing)}")

    seed = df.loc[:, ["ma_tbmt", "so_qd", "version"]].copy()
    seed["ma_tbmt"] = seed["ma_tbmt"].astype(str).str.strip()
    seed["so_qd"] = seed["so_qd"].astype(str).str.strip()
    seed["version"] = seed["version"].map(normalize_version)
    seed = seed[(seed["ma_tbmt"] != "") & (seed["so_qd"] != "") & (seed["version"] != "")]
    seed = seed.drop_duplicates().reset_index(drop=True)
    return seed


def create_temp_table(cursor, table_name: str, df: pd.DataFrame):
    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    cursor.execute(
        f"""
        CREATE TEMP TABLE {table_name} (
            ma_tbmt TEXT,
            so_qd TEXT,
            version TEXT,
            schema_type TEXT,
            relation_type TEXT,
            so_qd_original TEXT
        ) ON COMMIT DROP
        """
    )
    if df.empty:
        return
    rows = []
    for row in df.to_dict(orient="records"):
        rows.append(
            (
                row.get("ma_tbmt"),
                row.get("so_qd"),
                row.get("version"),
                row.get("schema_type"),
                row.get("relation_type"),
                row.get("so_qd_original"),
            )
        )
    with cursor.connection.cursor() as cur2:
        from psycopg2.extras import execute_values

        execute_values(
            cur2,
            f"""
            INSERT INTO {table_name} (
                ma_tbmt, so_qd, version, schema_type, relation_type, so_qd_original
            ) VALUES %s
            """,
            rows,
        )


def expand_units(conn, seed_df: pd.DataFrame) -> pd.DataFrame:
    with conn.cursor() as cursor:
        create_temp_table(
            cursor,
            "repair_seed_units",
            seed_df.assign(schema_type=None, relation_type=None, so_qd_original=None),
        )
        cursor.execute(EXPAND_CLUSTER_SQL)
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=cols)


def classify_schema(expanded_df: pd.DataFrame) -> pd.DataFrame:
    df = expanded_df.copy()
    unknown_mask = df["schema_type"].astype(str).eq("UNKNOWN")
    if unknown_mask.any():
        medicine_mask = df["so_qd"].astype(str).notna()
        df.loc[unknown_mask & medicine_mask, "schema_type"] = "UNKNOWN"
    return df


def count_rows(cursor, sql: str, schema_type: str | None = None) -> int:
    if schema_type is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, (schema_type,))
    return int(cursor.fetchone()[0] or 0)


def run_repair(conn, target_df: pd.DataFrame, apply_changes: bool) -> dict:
    stats = {
        "target_units": int(len(target_df)),
        "medicine_units": int((target_df["schema_type"] == "MEDICINE_STANDARD").sum()),
        "goods_units": int((target_df["schema_type"] == "GOODS_STANDARD").sum()),
        "unknown_units": int((~target_df["schema_type"].isin(["MEDICINE_STANDARD", "GOODS_STANDARD"])).sum()),
    }

    with conn.cursor() as cursor:
        create_temp_table(cursor, "repair_target_units", target_df)

        stats["processed_medicines_rows"] = count_rows(
            cursor,
            COUNT_PROCESSED_SQL.format(table_name="processed_medicines"),
            "MEDICINE_STANDARD",
        )
        stats["processed_goods_rows"] = count_rows(
            cursor,
            COUNT_PROCESSED_SQL.format(table_name="processed_goods"),
            "GOODS_STANDARD",
        )
        stats["manifest_rows"] = count_rows(cursor, COUNT_MANIFEST_SQL)

        if not apply_changes:
            return stats

        cursor.execute(
            DELETE_PROCESSED_SQL.format(table_name="processed_medicines"),
            ("MEDICINE_STANDARD",),
        )
        stats["deleted_medicines_rows"] = cursor.rowcount

        cursor.execute(
            DELETE_PROCESSED_SQL.format(table_name="processed_goods"),
            ("GOODS_STANDARD",),
        )
        stats["deleted_goods_rows"] = cursor.rowcount

        cursor.execute(RESET_MANIFEST_SQL)
        stats["manifest_reset_rows"] = cursor.rowcount

        cursor.execute(DELETE_ISSUES_SQL)
        stats["deleted_manifest_issues"] = cursor.rowcount

    return stats


def write_preview_excel(seed_df: pd.DataFrame, expanded_df: pd.DataFrame, output_path: Path):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        seed_df.to_excel(writer, sheet_name="seed_units", index=False)
        expanded_df.to_excel(writer, sheet_name="expanded_units", index=False)


def main():
    parser = argparse.ArgumentParser(
        description="One-off repair script: read mismatch units from audit Excel, expand relation clusters, delete processed rows, reset manifest to READY."
    )
    parser.add_argument(
        "--audit-file",
        default=str(CURRENT_DIR / "processed_unit_row_count_audit_v4.xlsx"),
        help="Path to audit Excel file.",
    )
    parser.add_argument(
        "--sheet",
        default="mismatch",
        help="Sheet name containing mismatch units.",
    )
    parser.add_argument(
        "--preview-output",
        default=str(CURRENT_DIR / "temp_repair_mismatch_preview.xlsx"),
        help="Excel preview output path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete processed rows and reset manifest. Without this flag, script only does dry-run.",
    )
    args = parser.parse_args()

    audit_path = Path(args.audit_file).resolve()
    if not audit_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file audit: {audit_path}")

    seed_df = load_seed_units(audit_path, args.sheet)
    if seed_df.empty:
        raise ValueError("Không có unit hợp lệ trong sheet mismatch.")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        expanded_df = expand_units(conn, seed_df)
        expanded_df = classify_schema(expanded_df)
        write_preview_excel(seed_df, expanded_df, Path(args.preview_output).resolve())

        with conn:
            stats = run_repair(conn, expanded_df, apply_changes=args.apply)
    finally:
        conn.close()

    print(f"Seed units from audit: {len(seed_df)}")
    print(f"Expanded target units: {stats['target_units']}")
    print(f"  - MEDICINE_STANDARD: {stats['medicine_units']}")
    print(f"  - GOODS_STANDARD: {stats['goods_units']}")
    print(f"  - UNKNOWN schema: {stats['unknown_units']}")
    print(f"Processed rows to affect:")
    print(f"  - processed_medicines: {stats['processed_medicines_rows']}")
    print(f"  - processed_goods: {stats['processed_goods_rows']}")
    print(f"Manifest rows to affect: {stats['manifest_rows']}")
    print(f"Preview Excel: {Path(args.preview_output).resolve()}")

    if args.apply:
        print("Applied changes:")
        print(f"  - deleted processed_medicines rows: {stats.get('deleted_medicines_rows', 0)}")
        print(f"  - deleted processed_goods rows: {stats.get('deleted_goods_rows', 0)}")
        print(f"  - manifest rows reset to READY: {stats.get('manifest_reset_rows', 0)}")
        print(f"  - manifest_issues rows deleted: {stats.get('deleted_manifest_issues', 0)}")
    else:
        print("Dry-run only. Add --apply to execute the repair.")


if __name__ == "__main__":
    main()
