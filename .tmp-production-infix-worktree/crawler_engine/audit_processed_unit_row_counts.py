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


schema_config = load_module("local_schema_config_rowcount", "schema_config.py")
s3_etl_pipeline = load_module("local_s3_etl_pipeline_rowcount", "s3_etl_pipeline.py")
schema_shared = load_module("local_schema_shared_rowcount", "schema_normalization_shared.py")

SCHEMAS = schema_config.SCHEMAS
load_excel_with_detected_header = s3_etl_pipeline.load_excel_with_detected_header
normalize_data = s3_etl_pipeline.normalize_data
normalize_grouped_rows_generic = s3_etl_pipeline.normalize_grouped_rows_generic
get_group_row_engine_settings = s3_etl_pipeline.get_group_row_engine_settings
detect_autofill_group_header_row = s3_etl_pipeline.detect_autofill_group_header_row
detect_true_group_header_generic = s3_etl_pipeline.detect_true_group_header_generic
detect_wrong_column_group_header_generic = s3_etl_pipeline.detect_wrong_column_group_header_generic
is_generic_summary_row = s3_etl_pipeline.is_generic_summary_row
is_summary_continuation_row = s3_etl_pipeline.is_summary_continuation_row
merge_pseudo_group_rows_generic = s3_etl_pipeline.merge_pseudo_group_rows_generic
autofill_group_header_values = s3_etl_pipeline.autofill_group_header_values
fill_vendor_from_sparse_group_headers = s3_etl_pipeline.fill_vendor_from_sparse_group_headers
drop_summary_rows = s3_etl_pipeline.drop_summary_rows
apply_goods_trade_name_fallback = s3_etl_pipeline.apply_goods_trade_name_fallback
_normalize_stt_value = s3_etl_pipeline._normalize_stt_value
_stt_root_value = s3_etl_pipeline._stt_root_value
_is_blank_cell = s3_etl_pipeline._is_blank_cell
has_detail_signal_generic = s3_etl_pipeline.has_detail_signal_generic

build_schema_mapping_config = schema_shared.build_schema_mapping_config
get_smart_column_mapping = schema_shared.get_smart_column_mapping
collapse_duplicate_columns = schema_shared.collapse_duplicate_columns
drop_header_legend_rows = schema_shared.drop_header_legend_rows

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Thiếu biến môi trường DATABASE_URL trong file .env")


UNIT_SQL_TEMPLATE = """
WITH processed_units AS (
    SELECT
        '{schema_name}' AS schema_name,
        p.ma_tbmt,
        p.so_qd,
        p.version,
        COUNT(*) AS processed_row_count
    FROM {table_name} p
    GROUP BY p.ma_tbmt, p.so_qd, p.version
),
package_pick AS (
    SELECT
        pu.schema_name,
        pu.ma_tbmt,
        pu.so_qd,
        pu.version,
        pu.processed_row_count,
        pkg.file_path,
        pkg.is_latest,
        qr.relation_type,
        qr.so_qd_original
    FROM processed_units pu
    LEFT JOIN LATERAL (
        SELECT p2.file_path, p2.is_latest
        FROM packages p2
        WHERE p2.ma_tbmt = pu.ma_tbmt
          AND p2.so_qd = pu.so_qd
          AND p2.version = pu.version
          AND COALESCE(p2.file_type, 'excel') = 'excel'
        ORDER BY p2.is_latest DESC, p2.crawled_at DESC NULLS LAST, p2.file_path DESC
        LIMIT 1
    ) pkg ON TRUE
    LEFT JOIN qd_relations qr
      ON qr.ma_tbmt = pu.ma_tbmt
     AND qr.so_qd = pu.so_qd
     AND qr.version = pu.version
)
    SELECT
        schema_name,
        ma_tbmt,
        so_qd,
        version,
        processed_row_count,
        file_path,
        COALESCE(is_latest, 0) AS is_latest,
        COALESCE(relation_type, 'UNMATCHED') AS relation_type,
        COALESCE(so_qd_original, so_qd) AS so_qd_original,
        EXISTS (
            SELECT 1
            FROM qd_relations q2
            WHERE q2.ma_tbmt = package_pick.ma_tbmt
              AND q2.so_qd_original = COALESCE(package_pick.so_qd_original, package_pick.so_qd)
              AND q2.relation_type IN ('ADJUSTMENT', 'REPLACEMENT')
        ) AS has_non_base_relation
    FROM package_pick
    ORDER BY ma_tbmt, so_qd, version;
"""


def fetch_processed_units(conn) -> list[dict]:
    units = []
    with conn.cursor() as cursor:
        for schema_name in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
            table_name = SCHEMAS[schema_name]["table_name"]
            cursor.execute(UNIT_SQL_TEMPLATE.format(schema_name=schema_name, table_name=table_name))
            cols = [desc[0] for desc in cursor.description]
            for row in cursor.fetchall():
                units.append(dict(zip(cols, row)))
    return units


def should_compare_directly(unit: dict) -> bool:
    return True


def resolve_local_file_path(file_path: str) -> str:
    path_text = str(file_path or "").strip()
    if not path_text:
        return path_text
    path_obj = Path(path_text)
    if path_obj.is_absolute():
        return str(path_obj)
    local_candidate = (CURRENT_DIR / path_obj).resolve()
    if local_candidate.exists():
        return str(local_candidate)
    return path_text


def _run_structure_trace(raw_df: pd.DataFrame, schema_name: str) -> dict:
    flags = {
        "autocomplete": False,
        "autofill": False,
        "merge": False,
    }
    working_df = raw_df.copy()

    if schema_name in ("MEDICINE_STANDARD", "GOODS_STANDARD"):
        settings = get_group_row_engine_settings(working_df, schema_name)
        stt_col = settings["stt_col"]
        detail_cols = settings["detail_cols"]
        amount_col = settings["amount_col"]
        group_cols = list(settings["existing_group_cols"])
        autofill_source_cols = list(settings["autofill_source_cols"])
        auto_create_target = settings["auto_create_target"]

        if stt_col and detail_cols:
            total_mask = []
            prev_row = None
            for _, row in working_df.iterrows():
                is_total_row = is_generic_summary_row(row, amount_col) or is_summary_continuation_row(row, prev_row, amount_col)
                total_mask.append(is_total_row)
                prev_row = row
            working_df = working_df.loc[[not m for m in total_mask]].reset_index(drop=True)

            current_context = None
            normalized_rows = []

            for idx, (_, row) in enumerate(working_df.iterrows()):
                current = row.copy()
                next_row = working_df.iloc[idx + 1] if idx + 1 < len(working_df) else None

                autofill_group = detect_autofill_group_header_row(
                    current=current,
                    next_row=next_row,
                    stt_col=stt_col,
                    detail_cols=detail_cols,
                    source_cols=autofill_source_cols,
                    amount_col=amount_col,
                )
                if autofill_group:
                    flags["autofill"] = True
                    current_context = autofill_group
                    continue

                true_group = detect_true_group_header_generic(
                    current=current,
                    next_row=next_row,
                    stt_col=stt_col,
                    detail_cols=detail_cols,
                    group_cols=group_cols,
                    amount_col=amount_col,
                )
                if true_group:
                    flags["autofill"] = True
                    current_context = true_group
                    continue

                wrong_group = detect_wrong_column_group_header_generic(
                    current=current,
                    next_row=next_row,
                    stt_col=stt_col,
                    detail_cols=detail_cols,
                    group_cols=group_cols,
                    amount_col=amount_col,
                )
                if wrong_group:
                    flags["autocomplete"] = True
                    if auto_create_target:
                        current_context = {
                            "root": wrong_group["root"],
                            "carry_values": {auto_create_target: wrong_group["text"]},
                            "source_cols": wrong_group["source_cols"],
                        }
                    continue

                current_stt = _normalize_stt_value(current.get(stt_col))
                current_root = _stt_root_value(current_stt)
                if current_context:
                    context_root = current_context["root"]
                    if context_root:
                        belongs_to_context = (
                            (bool(current_stt) and current_root == context_root and current_stt != context_root)
                            or (not current_stt and has_detail_signal_generic(current, detail_cols, amount_col))
                        )
                    else:
                        belongs_to_context = has_detail_signal_generic(current, detail_cols, amount_col)
                    if belongs_to_context:
                        for col, value in current_context["carry_values"].items():
                            if col == amount_col:
                                continue
                            if _is_blank_cell(current.get(col)) and not _is_blank_cell(value):
                                current[col] = value
                    elif context_root and current_stt and current_root and current_root != context_root:
                        current_context = None

                if not all(_is_blank_cell(v) for v in current.tolist()):
                    normalized_rows.append(current)

            normalized_df = pd.DataFrame(normalized_rows, columns=working_df.columns)
            merged_df = merge_pseudo_group_rows_generic(normalized_df, stt_col, detail_cols, amount_col)
            if len(merged_df) < len(normalized_df):
                flags["merge"] = True
            working_df = merged_df

    mapped_df = working_df.copy()
    if schema_name == "GOODS_STANDARD":
        mapped_df = apply_goods_trade_name_fallback(mapped_df)
    config = SCHEMAS[schema_name]
    mapping_config = build_schema_mapping_config(config)
    actual_mapping = get_smart_column_mapping(mapped_df.columns, mapping_config)
    mapped_df = mapped_df.rename(columns=actual_mapping)
    mapped_df = collapse_duplicate_columns(mapped_df)
    mapped_df = drop_header_legend_rows(mapped_df)
    amount_col = next((c for c in mapped_df.columns if str(c).strip().lower() == "thành tiền (vnd)".lower()), None)
    mapped_df = drop_summary_rows(mapped_df, amount_col)

    before_autofill_len = len(mapped_df)
    after_autofill_df = autofill_group_header_values(mapped_df, schema_name)
    if len(after_autofill_df) < before_autofill_len:
        flags["autofill"] = True

    before_vendor_len = len(after_autofill_df)
    before_vendor_blank = None
    if "Nhà thầu trúng thầu" in after_autofill_df.columns:
        before_vendor_blank = int(after_autofill_df["Nhà thầu trúng thầu"].astype("string").fillna("").str.strip().eq("").sum())
    after_vendor_df = fill_vendor_from_sparse_group_headers(after_autofill_df, schema_name)
    if len(after_vendor_df) < before_vendor_len:
        flags["autocomplete"] = True
    if "Nhà thầu trúng thầu" in after_vendor_df.columns:
        after_vendor_blank = int(after_vendor_df["Nhà thầu trúng thầu"].astype("string").fillna("").str.strip().eq("").sum())
        if before_vendor_blank is not None and after_vendor_blank < before_vendor_blank:
            flags["autocomplete"] = True

    if flags["merge"]:
        structure_mode = "merge"
    elif flags["autofill"]:
        structure_mode = "autofill"
    elif flags["autocomplete"]:
        structure_mode = "autocomplete"
    else:
        structure_mode = "already_structured"
    return {
        "structure_mode": structure_mode,
        "structure_flags": ",".join([name for name, enabled in flags.items() if enabled]) or "none",
    }


def audit_unit(unit: dict) -> dict:
    file_path = unit.get("file_path")
    result = {
        **unit,
        "comparison_mode": "DIRECT" if should_compare_directly(unit) else "CLUSTERED_SKIP",
        "normalized_row_count": None,
        "row_count_match": None,
        "structure_mode": "",
        "structure_flags": "",
        "error": "",
    }

    if not file_path:
        result["comparison_mode"] = "NO_FILE"
        result["error"] = "Missing file_path in packages"
        return result

    if result["comparison_mode"] != "DIRECT":
        return result

    try:
        resolved_file_path = resolve_local_file_path(str(file_path))
        raw_df = load_excel_with_detected_header(
            resolved_file_path,
            dtype=str,
        )
        structure_info = _run_structure_trace(raw_df, unit["schema_name"])
        result.update(structure_info)
        df = normalize_data(
            raw_df,
            unit["schema_name"],
            tbmt=unit["ma_tbmt"],
            so_qd=unit["so_qd"],
            version=unit["version"],
        )
        result["normalized_row_count"] = int(len(df.index))
        result["row_count_match"] = int(result["processed_row_count"] or 0) == result["normalized_row_count"]
    except Exception as exc:
        result["comparison_mode"] = "ERROR"
        result["error"] = str(exc)
    return result


def write_excel(results: list[dict], output_path: Path):
    all_df = pd.DataFrame(results)
    mismatch_df = all_df[all_df["row_count_match"] == False].copy()  # noqa: E712
    error_df = all_df[all_df["error"].astype(str).str.len() > 0].copy()
    skipped_df = all_df[all_df["comparison_mode"] != "DIRECT"].copy()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="all_units", index=False)
        mismatch_df.to_excel(writer, sheet_name="mismatch", index=False)
        error_df.to_excel(writer, sheet_name="errors", index=False)
        skipped_df.to_excel(writer, sheet_name="skipped", index=False)


def main():
    parser = argparse.ArgumentParser(description="Audit processed units by comparing processed row count with normalized file row count.")
    parser.add_argument("--schema", choices=["ALL", "MEDICINE_STANDARD", "GOODS_STANDARD"], default="ALL")
    parser.add_argument("--limit", type=int, default=0, help="Audit at most N processed units. 0 means no limit.")
    parser.add_argument("--tbmt", default="", help="Optional ma_tbmt filter.")
    parser.add_argument("--output", default="processed_unit_row_count_audit.xlsx", help="Excel output path.")
    args = parser.parse_args()

    with psycopg2.connect(DATABASE_URL) as conn:
        units = fetch_processed_units(conn)

    if args.schema != "ALL":
        units = [u for u in units if u["schema_name"] == args.schema]
    if args.tbmt:
        units = [u for u in units if str(u["ma_tbmt"] or "") == args.tbmt]
    if args.limit:
        units = units[: args.limit]

    results = []
    for idx, unit in enumerate(units, start=1):
        result = audit_unit(unit)
        results.append(result)
        if idx % 100 == 0:
            print(f"Progress: {idx}/{len(units)}")
        if result["comparison_mode"] == "DIRECT":
            status = "MATCH" if result["row_count_match"] else "MISMATCH"
            print(
                f"[{status}] {result['schema_name']} | {result['ma_tbmt']} / {result['so_qd']} / {result['version']} "
                f"| processed={result['processed_row_count']} new={result['normalized_row_count']}"
            )
        elif result["comparison_mode"] == "CLUSTERED_SKIP":
            print(
                f"[SKIP] {result['schema_name']} | {result['ma_tbmt']} / {result['so_qd']} / {result['version']} "
                f"| relation_type={result['relation_type']}"
            )
        else:
            print(
                f"[{result['comparison_mode']}] {result['schema_name']} | {result['ma_tbmt']} / {result['so_qd']} / {result['version']} "
                f"| {result['error']}"
            )

    output_path = Path(args.output)
    write_excel(results, output_path)
    direct_results = [r for r in results if r["comparison_mode"] == "DIRECT"]
    mismatch_count = sum(1 for r in direct_results if r["row_count_match"] is False)
    print(f"\nAudited units: {len(results)}")
    print(f"Direct comparisons: {len(direct_results)}")
    print(f"Mismatches: {mismatch_count}")
    print(f"Excel report: {output_path.resolve()}")


if __name__ == "__main__":
    main()
