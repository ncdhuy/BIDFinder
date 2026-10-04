import argparse
import os
from datetime import datetime

import pandas as pd

from s2_daily_manager import (
    canonicalize_excel_local_path,
    choose_manifest_schema,
    get_db_connection,
    load_excel_validation_frame,
    prepare_schema_validation_frame,
)
from schema_config import SCHEMAS
from storage_adapter import ensure_local_file, is_r2_key
from web_winner_facts import VENDOR_COLUMN, collapse_whitespace, is_blank_vendor_cell


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Find units where, after current cleaning rules, column 'Nha thau trung thau' "
            "still has blanks, has exactly 1 non-blank vendor, and has no web_winner_facts row."
        )
    )
    parser.add_argument(
        "--source-date",
        help="Filter by date token inside file_path, for example 20260406.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of units to scan for a quick dry run.",
    )
    parser.add_argument(
        "--output",
        help="Output .xlsx path. Default: auto-generate under crawler_engine/reports.",
    )
    return parser


def fetch_candidate_units(cursor, source_date=None, limit=None):
    sql = """
        SELECT
            p.ma_tbmt,
            p.so_qd,
            p.version,
            p.file_path,
            pm.trang_thai_dang_tai_kq,
            CASE
                WHEN w.ma_tbmt IS NULL THEN FALSE
                ELSE TRUE
            END AS has_web_winner_fact
        FROM packages p
        LEFT JOIN package_metadata pm
          ON pm.ma_tbmt = p.ma_tbmt
         AND pm.so_qd = p.so_qd
         AND pm.version = p.version
        LEFT JOIN web_winner_facts w
          ON w.ma_tbmt = p.ma_tbmt
         AND w.so_qd = p.so_qd
         AND w.version = p.version
        WHERE p.is_latest = 1
          AND p.file_type = 'excel'
    """
    params = []

    if source_date:
        sql += " AND p.file_path ILIKE %s"
        params.append(f"%{source_date}%")

    sql += " ORDER BY p.ma_tbmt, p.so_qd, p.version"

    if limit and limit > 0:
        sql += " LIMIT %s"
        params.append(limit)

    cursor.execute(sql, tuple(params))
    columns = [
        "ma_tbmt",
        "so_qd",
        "version",
        "file_path",
        "posting_status",
        "has_web_winner_fact",
    ]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def resolve_input_file(file_path):
    local_path = ensure_local_file(file_path, temp_subdir="existing_vendor_fill_audit")
    return canonicalize_excel_local_path(local_path)


def inspect_unit(unit):
    tbmt = unit["ma_tbmt"]
    so_qd = unit["so_qd"]
    version = unit["version"]
    file_path = unit["file_path"]

    if unit["has_web_winner_fact"]:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_HAS_WEB_WINNER_FACT",
            "details": "Unit đã có record trong web_winner_facts",
        }

    try:
        readable_path = resolve_input_file(file_path)
        df_raw = load_excel_validation_frame(readable_path)
    except Exception as exc:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_READ_ERROR",
            "details": str(exc),
        }

    schema_type, schema_reason = choose_manifest_schema(df_raw)
    if not schema_type:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_SCHEMA_UNCLEAR",
            "details": schema_reason,
        }

    working_df, structure_issues = prepare_schema_validation_frame(df_raw, schema_type)
    if working_df.empty:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_EMPTY_AFTER_CLEAN",
            "details": "File rỗng sau chuẩn hóa",
        }

    if VENDOR_COLUMN not in working_df.columns:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_NO_VENDOR_COLUMN",
            "details": f"Schema {schema_type} không có cột '{VENDOR_COLUMN}' sau chuẩn hóa",
        }

    series = working_df[VENDOR_COLUMN]
    blank_mask = series.map(is_blank_vendor_cell)
    blank_count = int(blank_mask.sum())
    non_blank_values = [
        collapse_whitespace(value)
        for value in series[~blank_mask].tolist()
        if collapse_whitespace(value)
    ]
    distinct_vendors = sorted({value.casefold(): value for value in non_blank_values}.values())

    if blank_count <= 0:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_NO_BLANK_VENDOR",
            "details": "Không còn ô trống ở cột Nhà thầu trúng thầu sau chuẩn hóa",
        }

    if len(distinct_vendors) != 1:
        return None, {
            "ma_tbmt": tbmt,
            "so_qd": so_qd,
            "version": version,
            "file_path": file_path,
            "status": "SKIP_VENDOR_COUNT_NOT_1",
            "details": f"Số vendor khác rỗng sau chuẩn hóa = {len(distinct_vendors)}",
        }

    config = SCHEMAS.get(schema_type, {})
    return {
        "ma_tbmt": tbmt,
        "so_qd": so_qd,
        "version": version,
        "schema_type": schema_type,
        "file_path": file_path,
        "resolved_file_path": readable_path,
        "posting_status": unit.get("posting_status"),
        "has_web_winner_fact": unit["has_web_winner_fact"],
        "row_count_after_clean": len(working_df),
        "blank_vendor_count": blank_count,
        "non_blank_vendor_count": len(non_blank_values),
        "distinct_vendor_count": len(distinct_vendors),
        "only_vendor_name": distinct_vendors[0],
        "mandatory_columns": ", ".join(config.get("mandatory_columns", [])),
        "structure_issues": " | ".join(structure_issues) if structure_issues else "",
    }, None


def build_default_output_path():
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(reports_dir, f"existing_vendor_fill_risk_{timestamp}.xlsx")


def main():
    parser = build_parser()
    args = parser.parse_args()
    output_path = args.output or build_default_output_path()

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            units = fetch_candidate_units(
                cursor,
                source_date=args.source_date,
                limit=args.limit,
            )

    matches = []
    skipped = []

    total = len(units)
    for index, unit in enumerate(units, start=1):
        print(
            f"[{index}/{total}] Scan {unit['ma_tbmt']} / {unit['so_qd']} / v{unit['version']}",
            flush=True,
        )
        match_row, skipped_row = inspect_unit(unit)
        if match_row:
            matches.append(match_row)
        elif skipped_row:
            skipped.append(skipped_row)

    summary_rows = [
        {"metric": "scanned_units", "value": total},
        {"metric": "matched_units", "value": len(matches)},
        {"metric": "skipped_units", "value": len(skipped)},
        {"metric": "source_date_filter", "value": args.source_date or ""},
    ]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="summary", index=False)
        pd.DataFrame(matches).to_excel(writer, sheet_name="matches", index=False)
        pd.DataFrame(skipped).to_excel(writer, sheet_name="skipped", index=False)

    print(f"\nDone. Output: {os.path.abspath(output_path)}")
    print(f"Matched units: {len(matches)} / {total}")


if __name__ == "__main__":
    main()
