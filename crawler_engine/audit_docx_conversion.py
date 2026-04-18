import argparse
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def clean_col_str(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_docx_cell_text(text, keep_newlines=False):
    if text is None:
        return ""
    text = str(text).replace("\r", "\n")
    if keep_newlines:
        parts = [" ".join(part.split()) for part in text.split("\n")]
        return "\n".join(part for part in parts if part).strip()
    return " ".join(text.replace("\n", " ").split()).strip()


def trim_docx_row_values(values):
    trimmed = list(values or [])
    while trimmed and not normalize_docx_cell_text(trimmed[-1], keep_newlines=False):
        trimmed.pop()
    return trimmed


def extract_docx_row_values(row):
    values = []
    previous_tc = None
    for cell in row.cells:
        current_tc = cell._tc
        if previous_tc is not None and current_tc is previous_tc:
            values.append("")
        else:
            values.append(cell.text)
        previous_tc = current_tc
    return trim_docx_row_values(values)


def is_docx_numbering_row(values):
    non_empty = [str(v).strip() for v in values if str(v).strip()]
    if not non_empty:
        return False

    numbered = 0
    for value in non_empty:
        if (
            re.match(r"^\(\d+\)(=.*)?$", value)
            or re.match(r"^\(\d+\)$", value)
            or re.match(r"^\d+(\.\d+)?$", value)
            or re.match(r"^[\d\s().=xX*/+\-]+$", value)
        ):
            numbered += 1
    return numbered / len(non_empty) >= 0.7


def score_docx_header_row(values):
    normalized = [
        normalize_docx_cell_text(v, keep_newlines=False).lower()
        for v in trim_docx_row_values(values)
    ]
    non_empty = [v for v in normalized if v]
    if len(non_empty) < 3:
        return float("-inf")

    header_keywords = (
        "stt", "tên thuốc", "tên hàng hóa", "danh mục hàng hóa", "tên thương mại",
        "nhà thầu", "đơn vị tính", "số lượng", "khối lượng", "đơn giá", "thành tiền",
        "nồng độ", "hàm lượng", "đường dùng", "dạng bào chế", "quy cách", "số đăng ký",
        "ký mã hiệu", "nhãn hiệu", "hãng sản xuất", "xuất xứ", "tính năng kỹ thuật",
        "cấu hình", "mã phần", "tên phần", "hoạt chất"
    )

    keyword_hits = sum(
        1 for value in non_empty
        if any(keyword in value for keyword in header_keywords)
    )
    unique_count = len(set(non_empty))
    repeated_penalty = 8 if unique_count == 1 else 0
    numbering_penalty = 6 if is_docx_numbering_row(non_empty) else 0
    return keyword_hits * 10 + unique_count - repeated_penalty - numbering_penalty


def choose_docx_header_index(rows):
    if not rows:
        return 0

    best_idx = 0
    best_score = float("-inf")
    for idx, row in enumerate(rows[: min(len(rows), 12)]):
        score = score_docx_header_row(row)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def make_docx_headers_unique(header_values, width):
    padded = list(header_values[:width]) + [""] * max(0, width - len(header_values))
    result = []
    seen = {}
    for idx, value in enumerate(padded, start=1):
        base = normalize_docx_cell_text(value, keep_newlines=False) or f"Unnamed_{idx}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result


def docx_header_has_excluded_columns(header_values):
    excluded_targets = {
        clean_col_str("mã số thuế"),
        clean_col_str("mã định danh"),
        clean_col_str("địa chỉ"),
    }
    normalized_headers = {
        clean_col_str(value)
        for value in (header_values or [])
        if normalize_docx_cell_text(value, keep_newlines=False)
    }
    return any(header in excluded_targets for header in normalized_headers)


def iter_docx_block_items(document):
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def extract_docx_bidder_name(paragraph_texts):
    for text in reversed(paragraph_texts or []):
        normalized = normalize_docx_cell_text(text, keep_newlines=False)
        if not normalized:
            continue
        match = re.search(r"nhà\s*thầu\s*:?\s*(.+)$", normalized, flags=re.IGNORECASE)
        if match:
            bidder_name = re.sub(r"\s+", " ", match.group(1)).strip(" .:-")
            if bidder_name:
                return bidder_name
    return None


def convert_docx_table_rows_to_dataframe(rows, bidder_name=None):
    if len(rows) < 2:
        return None

    header_idx = choose_docx_header_index(rows)
    header = [normalize_docx_cell_text(v, keep_newlines=False) for v in rows[header_idx]]
    if docx_header_has_excluded_columns(header):
        return None
    data_rows = rows[header_idx + 1:]
    while data_rows and is_docx_numbering_row([
        normalize_docx_cell_text(v, keep_newlines=False) for v in data_rows[0]
    ]):
        data_rows = data_rows[1:]

    cleaned_rows = []
    for row in data_rows:
        normalized = [normalize_docx_cell_text(v, keep_newlines=True) for v in trim_docx_row_values(row)]
        if any(normalized):
            cleaned_rows.append(normalized)

    if not cleaned_rows:
        return None

    width = max(
        len(header),
        max((len(row) for row in cleaned_rows), default=0),
    )
    header = make_docx_headers_unique(header, width)
    normalized_rows = [
        list(row[:width]) + [""] * max(0, width - len(row))
        for row in cleaned_rows
    ]

    df = pd.DataFrame(normalized_rows, columns=header)
    if bidder_name:
        bidder_col = next((c for c in df.columns if clean_col_str(c) == clean_col_str("Nhà thầu trúng thầu")), None)
        if bidder_col:
            df[bidder_col] = df[bidder_col].replace("", np.nan).fillna(bidder_name)
        else:
            df.insert(0, "Nhà thầu trúng thầu", bidder_name)
    return df


def rebuild_docx_to_dataframe(docx_path: Path):
    doc = Document(docx_path)
    frames = []
    recent_paragraphs = []
    table_count = 0

    for block in iter_docx_block_items(doc):
        if isinstance(block, Paragraph):
            text = normalize_docx_cell_text(block.text, keep_newlines=False)
            if text:
                recent_paragraphs.append(text)
                recent_paragraphs = recent_paragraphs[-5:]
            continue

        table_count += 1
        rows = []
        for row in block.rows:
            values = extract_docx_row_values(row)
            if any(normalize_docx_cell_text(v) for v in values):
                rows.append(values)

        bidder_name = extract_docx_bidder_name(recent_paragraphs)
        table_df = convert_docx_table_rows_to_dataframe(rows, bidder_name=bidder_name)
        if table_df is not None and not table_df.empty:
            frames.append(table_df)
        recent_paragraphs = []

    merged = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    return table_count, merged


def read_existing_xlsx_info(xlsx_path: Path):
    if not xlsx_path.exists():
        return {
            "xlsx_exists": False,
            "xlsx_rows": None,
            "xlsx_columns": None,
            "xlsx_vendor_count": None,
        }

    try:
        df = pd.read_excel(xlsx_path)
    except Exception:
        return {
            "xlsx_exists": True,
            "xlsx_rows": None,
            "xlsx_columns": None,
            "xlsx_vendor_count": None,
        }

    vendor_col = next((c for c in df.columns if clean_col_str(c) == clean_col_str("Nhà thầu trúng thầu")), None)
    vendor_count = None
    if vendor_col:
        vendor_count = df[vendor_col].replace("", np.nan).dropna().astype(str).nunique()

    return {
        "xlsx_exists": True,
        "xlsx_rows": len(df),
        "xlsx_columns": len(df.columns),
        "xlsx_vendor_count": vendor_count,
    }


def audit_docx_file(docx_path: Path):
    xlsx_path = docx_path.with_suffix(".xlsx")
    table_count, rebuilt_df = rebuild_docx_to_dataframe(docx_path)
    rebuilt_vendor_col = next((c for c in rebuilt_df.columns if clean_col_str(c) == clean_col_str("Nhà thầu trúng thầu")), None)
    rebuilt_vendor_count = 0
    if rebuilt_vendor_col:
        rebuilt_vendor_count = rebuilt_df[rebuilt_vendor_col].replace("", np.nan).dropna().astype(str).nunique()

    existing = read_existing_xlsx_info(xlsx_path)

    needs_rebuild = (
        table_count > 1
        and (
            not existing["xlsx_exists"]
            or existing["xlsx_rows"] != len(rebuilt_df)
            or (rebuilt_vendor_count and existing["xlsx_vendor_count"] not in (None, rebuilt_vendor_count))
        )
    )

    return {
        "docx_path": str(docx_path),
        "xlsx_path": str(xlsx_path),
        "table_count": table_count,
        "rebuilt_rows": len(rebuilt_df),
        "rebuilt_columns": len(rebuilt_df.columns),
        "rebuilt_vendor_count": rebuilt_vendor_count,
        "xlsx_exists": existing["xlsx_exists"],
        "xlsx_rows": existing["xlsx_rows"],
        "xlsx_columns": existing["xlsx_columns"],
        "xlsx_vendor_count": existing["xlsx_vendor_count"],
        "needs_rebuild": needs_rebuild,
    }


def rewrite_xlsx(docx_path: Path, output_suffix: str = ""):
    _, rebuilt_df = rebuild_docx_to_dataframe(docx_path)
    if rebuilt_df.empty:
        return None
    if output_suffix:
        out_path = docx_path.with_name(docx_path.stem + output_suffix + ".xlsx")
    else:
        out_path = docx_path.with_suffix(".xlsx")
    rebuilt_df.to_excel(out_path, index=False)
    return out_path


def iter_docx_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() == ".docx" and not path.name.startswith("~$"):
            yield path


def build_parser():
    parser = argparse.ArgumentParser(description="Audit va rebuild file docx convert sang xlsx.")
    parser.add_argument("--root", default="raw_data", help="Thu muc goc chua file .docx")
    parser.add_argument("--report", default="docx_conversion_audit.csv", help="Ten file report CSV")
    parser.add_argument("--rewrite-flagged", action="store_true", help="Rewrite cac file can rebuild")
    parser.add_argument("--output-suffix", default="", help="Suffix khi rewrite, vi du '.fixed'")
    return parser


def main():
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    report_path = Path(args.report).resolve()

    rows = []
    rewritten = 0
    blocked = 0

    for docx_path in iter_docx_files(root):
        try:
            audit_row = audit_docx_file(docx_path)
        except Exception as exc:
            rows.append({
                "docx_path": str(docx_path),
                "xlsx_path": str(docx_path.with_suffix(".xlsx")),
                "table_count": None,
                "rebuilt_rows": None,
                "rebuilt_columns": None,
                "rebuilt_vendor_count": None,
                "xlsx_exists": docx_path.with_suffix(".xlsx").exists(),
                "xlsx_rows": None,
                "xlsx_columns": None,
                "xlsx_vendor_count": None,
                "needs_rebuild": None,
                "error": str(exc),
            })
            continue

        audit_row["error"] = ""
        rows.append(audit_row)

        if args.rewrite_flagged and audit_row["needs_rebuild"]:
            try:
                rewrite_xlsx(docx_path, output_suffix=args.output_suffix)
                rewritten += 1
            except PermissionError:
                blocked += 1
            except Exception:
                blocked += 1

    report_df = pd.DataFrame(rows)
    report_df.to_csv(report_path, index=False, encoding="utf-8-sig")

    flagged = int(report_df["needs_rebuild"].fillna(False).sum()) if not report_df.empty else 0
    print(f"Scanned: {len(report_df)}")
    print(f"Flagged: {flagged}")
    print(f"Rewritten: {rewritten}")
    print(f"Blocked: {blocked}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
