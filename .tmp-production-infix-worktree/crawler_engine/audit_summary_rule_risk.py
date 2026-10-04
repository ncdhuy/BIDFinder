import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

CURRENT_DIR = Path(__file__).resolve().parent
for candidate in (CURRENT_DIR, Path.cwd().resolve()):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_module(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, CURRENT_DIR / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema_config = load_module("local_schema_config", "schema_config.py")
schema_normalization_shared = load_module("local_schema_normalization_shared", "schema_normalization_shared.py")
s3_etl_pipeline = load_module("local_s3_etl_pipeline", "s3_etl_pipeline.py")

SCHEMAS = schema_config.SCHEMAS
shared_drop_header_legend_rows = schema_normalization_shared.drop_header_legend_rows
_clean_cell_text = s3_etl_pipeline._clean_cell_text
_is_blank_cell = s3_etl_pipeline._is_blank_cell
_is_numeric_like_text = s3_etl_pipeline._is_numeric_like_text
build_schema_mapping_config = s3_etl_pipeline.build_schema_mapping_config
clean_col_str = s3_etl_pipeline.clean_col_str
collapse_duplicate_columns = s3_etl_pipeline.collapse_duplicate_columns
get_smart_column_mapping = s3_etl_pipeline.get_smart_column_mapping
has_detail_signal_generic = s3_etl_pipeline.has_detail_signal_generic
is_generic_summary_row = s3_etl_pipeline.is_generic_summary_row
load_excel_with_detected_header = s3_etl_pipeline.load_excel_with_detected_header
read_and_normalize_excel = s3_etl_pipeline.read_and_normalize_excel


SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def old_is_generic_summary_row(row: pd.Series, amount_col=None) -> bool:
    non_blank_count = sum(not _is_blank_cell(v) for v in row.tolist())
    sparse_threshold = max(4, int(len(row) * 0.35))
    is_sparse_row = non_blank_count <= sparse_threshold

    strong_patterns = [
        r"^tổng\b",
        r"^cộng\b",
        r"tổng cộng giá .* hàng hóa",
        r"tổng giá .* hàng hóa",
        r"tổng cộng .* phí.*lệ phí",
    ]

    import re

    for value in row.tolist():
        text = _clean_cell_text(value).lower()
        if not text:
            continue
        if any(re.search(pattern, text) for pattern in strong_patterns):
            return True
        if is_sparse_row and any(text.startswith(prefix) for prefix in ("tổng", "cộng")):
            return True
    return False


def detect_schema(df: pd.DataFrame) -> str | None:
    medicine_config = build_schema_mapping_config(SCHEMAS["MEDICINE_STANDARD"])
    goods_config = build_schema_mapping_config(SCHEMAS["GOODS_STANDARD"])

    med_map = get_smart_column_mapping(df.columns, medicine_config)
    goods_map = get_smart_column_mapping(df.columns, goods_config)

    med_hits = sum(1 for value in med_map.values() if value in {"Tên thuốc", "Tên hoạt chất", "Số lượng"})
    goods_hits = sum(1 for value in goods_map.values() if value in {"Danh mục hàng hóa", "Khối lượng", "Mặt hàng dự thầu"})

    if med_hits == 0 and goods_hits == 0:
        return None
    return "MEDICINE_STANDARD" if med_hits >= goods_hits else "GOODS_STANDARD"


def normalize_preview(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    mapping_config = build_schema_mapping_config(SCHEMAS[schema_name])
    actual_mapping = get_smart_column_mapping(df.columns, mapping_config)
    df = df.rename(columns=actual_mapping)
    df = collapse_duplicate_columns(df)
    df = shared_drop_header_legend_rows(df)
    return df


def iter_excel_files(root: Path):
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTENSIONS and not root.name.startswith("~$"):
            yield root
        return

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("~$"):
            yield path


def parse_unit_from_filename(path: Path) -> tuple[str, str, str]:
    stem = path.stem
    parts = stem.split("_")
    tbmt = parts[0] if len(parts) > 0 else ""
    version = parts[1].lstrip("vV") if len(parts) > 1 else ""
    so_qd = parts[2] if len(parts) > 2 else ""
    return tbmt, so_qd, version


def load_processed_counts(conn) -> dict[str, dict[tuple[str, str, str], int]]:
    queries = {
        "MEDICINE_STANDARD": """
            SELECT ma_tbmt, so_qd, version, COUNT(*)
            FROM processed_medicines
            GROUP BY ma_tbmt, so_qd, version
        """,
        "GOODS_STANDARD": """
            SELECT ma_tbmt, so_qd, version, COUNT(*)
            FROM processed_goods
            GROUP BY ma_tbmt, so_qd, version
        """,
    }
    output = {schema: {} for schema in queries}
    with conn.cursor() as cursor:
        for schema_name, sql in queries.items():
            cursor.execute(sql)
            for ma_tbmt, so_qd, version, row_count in cursor.fetchall():
                output[schema_name][(str(ma_tbmt or ""), str(so_qd or ""), str(version or ""))] = int(row_count or 0)
    return output


def lookup_unit_metadata(conn, path: Path, fallback: tuple[str, str, str]) -> tuple[str, str, str]:
    basename = path.name
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT ma_tbmt, so_qd, version
            FROM packages
            WHERE file_path ILIKE %s
            ORDER BY is_latest DESC, version DESC
            LIMIT 1
            """,
            (f"%{basename}",),
        )
        row = cursor.fetchone()
    if row:
        return tuple(str(value or "") for value in row)
    return fallback


def evaluate_new_rule_row_count(path: Path, schema_name: str, unit_meta: tuple[str, str, str]) -> tuple[int | None, str]:
    try:
        df = read_and_normalize_excel(
            str(path.resolve()),
            schema_name,
            tbmt=unit_meta[0] or None,
            so_qd=unit_meta[1] or None,
            version=unit_meta[2] or None,
        )
        return len(df.index), ""
    except Exception as exc:
        return None, str(exc)


def scan_file(path: Path, schema_name: str | None, processed_counts: dict[str, dict[tuple[str, str, str], int]], conn=None):
    raw_df = load_excel_with_detected_header(str(path), dtype=str)
    effective_schema = schema_name or detect_schema(raw_df)
    if not effective_schema:
        return None

    df = normalize_preview(raw_df, effective_schema)
    if df is None or df.empty:
        return None

    if effective_schema == "MEDICINE_STANDARD":
        detail_cols = [c for c in df.columns if clean_col_str(c) == "tên thuốc"]
    else:
        detail_cols = [c for c in df.columns if clean_col_str(c) in {"danh mục hàng hóa", "tên hàng hóa", "tên thương mại"}]

    if not detail_cols:
        return None

    amount_col = next((c for c in df.columns if clean_col_str(c) == "thành tiền (vnd)"), None)
    risk_row = None

    for idx, row in df.iterrows():
        old_summary = old_is_generic_summary_row(row, amount_col)
        new_summary = is_generic_summary_row(row, amount_col)
        has_detail = has_detail_signal_generic(row, detail_cols, amount_col)
        if old_summary and not new_summary and has_detail:
            risk_row = {
                "row_index": int(idx),
                "label_col": next((col for col, value in row.items() if _clean_cell_text(value).lower().startswith("cộng")), ""),
                "tt": _clean_cell_text(row.get("TT", row.get("STT", ""))),
                "ma": _clean_cell_text(row.get("Mã thuốc", row.get("Mã hàng hóa", ""))),
                "name": _clean_cell_text(row.get("Tên thuốc", row.get("Danh mục hàng hóa", ""))),
                "origin": _clean_cell_text(row.get("Xuất xứ", "")),
                "amount": _clean_cell_text(row.get("Thành tiền (VND)", "")),
            }
            break

    if not risk_row:
        return None

    tbmt, so_qd, version = parse_unit_from_filename(path)
    unit_meta = (tbmt, so_qd, version)
    if conn is not None:
        unit_meta = lookup_unit_metadata(conn, path, unit_meta)

    processed_row_count = processed_counts.get(effective_schema, {}).get(unit_meta)
    normalized_row_count, row_count_error = evaluate_new_rule_row_count(path, effective_schema, unit_meta)
    row_count_mismatch = (
        processed_row_count is not None
        and normalized_row_count is not None
        and processed_row_count != normalized_row_count
    )

    return {
        "file_path": str(path),
        "schema_name": effective_schema,
        "ma_tbmt": unit_meta[0],
        "so_qd": unit_meta[1],
        "version": unit_meta[2],
        "risk_count": 1,
        "processed_row_count": processed_row_count,
        "normalized_row_count": normalized_row_count,
        "row_count_mismatch": row_count_mismatch,
        "row_count_error": row_count_error,
        "risk_row": risk_row,
    }


def write_excel_report(results: list[dict], processed_counts: dict[str, dict[tuple[str, str, str], int]], output_path: Path):
    risk_rows = []
    unit_rows = []
    for item in results:
        unit_rows.append({
            "ma_tbmt": item["ma_tbmt"],
            "so_qd": item["so_qd"],
            "version": item["version"],
            "schema_name": item["schema_name"],
            "risk_count": item["risk_count"],
            "processed_row_count": item["processed_row_count"],
            "normalized_row_count": item["normalized_row_count"],
            "row_count_mismatch": item["row_count_mismatch"],
            "row_count_error": item["row_count_error"],
            "file_path": item["file_path"],
        })
        row = item["risk_row"]
        risk_rows.append({
            "ma_tbmt": item["ma_tbmt"],
            "so_qd": item["so_qd"],
            "version": item["version"],
            "schema_name": item["schema_name"],
            "risk_count": item["risk_count"],
            "processed_row_count": item["processed_row_count"],
            "normalized_row_count": item["normalized_row_count"],
            "row_count_mismatch": item["row_count_mismatch"],
            "row_count_error": item["row_count_error"],
            "row_index": row["row_index"],
            "tt": row["tt"],
            "ma": row["ma"],
            "name": row["name"],
            "origin": row["origin"],
            "amount": row["amount"],
            "file_path": item["file_path"],
        })

    processed_rows = []
    for schema_name, items in processed_counts.items():
        for (ma_tbmt, so_qd, version), row_count in sorted(items.items()):
            processed_rows.append({
                "schema_name": schema_name,
                "ma_tbmt": ma_tbmt,
                "so_qd": so_qd,
                "version": version,
                "processed_row_count": row_count,
            })

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(unit_rows).to_excel(writer, sheet_name="risk_units", index=False)
        pd.DataFrame(risk_rows).to_excel(writer, sheet_name="risk_rows", index=False)
        pd.DataFrame(processed_rows).to_excel(writer, sheet_name="processed_counts", index=False)


def main():
    parser = argparse.ArgumentParser(description="Find units at risk from the old loose summary-row rule.")
    parser.add_argument(
        "--input",
        default="raw_data",
        help="Excel file or directory to scan. Defaults to crawler_engine/raw_data.",
    )
    parser.add_argument(
        "--schema",
        choices=["MEDICINE_STANDARD", "GOODS_STANDARD", "AUTO"],
        default="AUTO",
        help="Schema to evaluate. AUTO tries to infer from columns.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after scanning N Excel files. 0 means no limit.",
    )
    parser.add_argument(
        "--output",
        default="summary_rule_risk_report.xlsx",
        help="Excel output path.",
    )
    args = parser.parse_args()

    root = Path(args.input)
    schema_name = None if args.schema == "AUTO" else args.schema

    processed_counts = {"MEDICINE_STANDARD": {}, "GOODS_STANDARD": {}}
    conn = None
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        processed_counts = load_processed_counts(conn)

    results = []
    scanned = 0
    try:
        for path in iter_excel_files(root):
            scanned += 1
            result = scan_file(path, schema_name, processed_counts, conn=conn)
            if result:
                results.append(result)
                mismatch_label = ""
                if result["row_count_mismatch"]:
                    mismatch_label = (
                        f" | ROW_MISMATCH processed={result['processed_row_count']} "
                        f"new={result['normalized_row_count']}"
                    )
                elif result["row_count_error"]:
                    mismatch_label = f" | ROW_COUNT_ERROR={result['row_count_error']}"
                print(
                    f"[RISK] {result['ma_tbmt']} / {result['so_qd']} / {result['version']} "
                    f"/ {result['schema_name']} -> {result['risk_count']} row(s){mismatch_label} | {path}"
                )
                sample = result["risk_row"]
                print(
                    f"       row={sample['row_index']} tt={sample['tt']} ma={sample['ma']} "
                    f"name={sample['name']} origin={sample['origin']}"
                )
            if args.limit and scanned >= args.limit:
                break
    finally:
        if conn is not None:
            conn.close()

    output_path = Path(args.output)
    write_excel_report(results, processed_counts, output_path)
    print(f"\nScanned files: {scanned}")
    print(f"Units at risk: {len(results)}")
    print(f"Excel report: {output_path.resolve()}")


if __name__ == "__main__":
    main()
