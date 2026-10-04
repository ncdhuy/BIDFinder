import argparse
import re
import sys
import unicodedata
import warnings
from pathlib import Path

import pandas as pd
from schema_normalization_shared import get_excel_sheet_name_groups


EXCEL_EXTENSIONS = {".xlsx", ".xls"}
SUMMARY_KEYWORDS = (
    "tong cong",
    "thanh tien",
    "tong tien",
    "cong tien",
    "tong gia tri",
    "gia tri cong",
    "tong gia",
)
HEADER_KEYWORDS = (
    "stt",
    "ten hang hoa",
    "ten thuoc",
    "ten vat tu",
    "ten thuong mai",
    "ma hang hoa",
    "ma thuoc",
    "hang san xuat",
    "nuoc san xuat",
    "don vi tinh",
    "so luong",
    "don gia",
    "thanh tien",
    "ky thuat",
    "hoat chat",
    "ham luong",
    "quy cach",
)

warnings.filterwarnings(
    "ignore",
    message=r"Cannot parse header or footer so it will be ignored",
    category=UserWarning,
    module="openpyxl.worksheet.header_footer",
)
warnings.filterwarnings(
    "ignore",
    message=r"Unknown extension is not supported and will be removed",
    category=UserWarning,
    module=r"openpyxl\.worksheet\._reader",
)
warnings.filterwarnings(
    "ignore",
    message=r"Conditional Formatting extension is not supported and will be removed",
    category=UserWarning,
    module=r"openpyxl\.worksheet\._reader",
)


def slugify_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_cell_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_bidder_name(file_stem: str) -> str:
    cleaned = re.sub(r"^\s*\d+\s*[\.\-_)]?\s*", "", file_stem).strip()
    cleaned = re.sub(r"^\s*\d+\s+", "", cleaned).strip()
    return cleaned or file_stem.strip()


def make_unique_columns(columns: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    output: list[str] = []
    for idx, col in enumerate(columns):
        base = clean_cell_text(col)
        if not base or base.lower().startswith("unnamed:"):
            base = f"cot_{idx + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        output.append(base if count == 0 else f"{base}_{count + 1}")
    return output


def detect_header_row(preview_df: pd.DataFrame) -> int:
    best_index = 0
    best_score = float("-inf")

    for idx in preview_df.index:
        row_values = [clean_cell_text(value) for value in preview_df.loc[idx].tolist()]
        non_empty = [value for value in row_values if value]
        if not non_empty:
            continue

        slugged = [slugify_text(value) for value in non_empty]
        keyword_hits = sum(any(keyword in cell for keyword in HEADER_KEYWORDS) for cell in slugged)
        unique_ratio = len(set(slugged)) / max(len(slugged), 1)
        penalty = 2 if len(non_empty) <= 1 else 0
        score = (keyword_hits * 10) + len(non_empty) + unique_ratio - penalty

        if score > best_score:
            best_score = score
            best_index = int(idx)

    return best_index


def choose_sheet(excel_file: Path) -> tuple[str, int]:
    sheet_groups = get_excel_sheet_name_groups(excel_file)
    sheet_names = sheet_groups["visible"] or sheet_groups["all"]
    best_sheet = sheet_names[0]
    best_header = 0
    best_score = float("-inf")

    for sheet_name in sheet_names:
        try:
            preview_df = pd.read_excel(
                excel_file,
                sheet_name=sheet_name,
                header=None,
                dtype=str,
                nrows=30,
            )
        except Exception:
            continue

        if preview_df.empty:
            continue

        header_idx = detect_header_row(preview_df)
        header_values = [clean_cell_text(value) for value in preview_df.iloc[header_idx].tolist()]
        non_empty = [value for value in header_values if value]
        slugged = [slugify_text(value) for value in non_empty]
        keyword_hits = sum(any(keyword in cell for keyword in HEADER_KEYWORDS) for cell in slugged)
        score = (keyword_hits * 10) + len(non_empty)

        if score > best_score:
            best_score = score
            best_sheet = sheet_name
            best_header = header_idx

    return best_sheet, best_header


def is_summary_row(row: pd.Series) -> bool:
    values = [clean_cell_text(value) for value in row.tolist()]
    non_empty = [value for value in values if value]
    if not non_empty:
        return True

    slugged = [slugify_text(value) for value in non_empty]
    combined = " | ".join(slugged)

    if any(keyword in combined for keyword in SUMMARY_KEYWORDS):
        return True

    first_value = slugged[0]
    if any(first_value.startswith(keyword) for keyword in SUMMARY_KEYWORDS):
        return True

    return False


def clean_dataframe(df: pd.DataFrame, bidder_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_unique_columns(df.columns.tolist())
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")

    if df.empty:
        return df

    mask_summary = df.apply(is_summary_row, axis=1)
    df = df.loc[~mask_summary].copy()
    df = df.dropna(axis=0, how="all")

    if df.empty:
        return df

    df = df.apply(lambda col: col.map(clean_cell_text))
    df.insert(0, "Nhà thầu trúng thầu", bidder_name)
    return df


def read_excel_file(excel_file: Path) -> pd.DataFrame:
    bidder_name = clean_bidder_name(excel_file.stem)
    sheet_name, header_idx = choose_sheet(excel_file)
    df = pd.read_excel(
        excel_file,
        sheet_name=sheet_name,
        header=header_idx,
        dtype=str,
    )
    return clean_dataframe(df, bidder_name)


def iter_excel_files(folder_path: Path) -> list[Path]:
    return sorted(
        path
        for path in folder_path.rglob("*")
        if path.is_file() and path.suffix.lower() in EXCEL_EXTENSIONS and not path.name.startswith("~$")
    )


def merge_folder(folder_path: Path, output_dir: Path) -> tuple[Path | None, int, int]:
    excel_files = iter_excel_files(folder_path)
    if not excel_files:
        return None, 0, 0

    merged_frames: list[pd.DataFrame] = []
    skipped = 0

    for excel_file in excel_files:
        try:
            df = read_excel_file(excel_file)
        except Exception:
            skipped += 1
            continue

        if df.empty:
            skipped += 1
            continue

        merged_frames.append(df)

    if not merged_frames:
        return None, len(excel_files), skipped

    merged_df = pd.concat(merged_frames, ignore_index=True, sort=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{folder_path.name}.xlsx"
    merged_df.to_excel(output_path, index=False)
    return output_path, len(excel_files), skipped


def iter_target_folders(input_root: Path, excluded_names: set[str] | None = None) -> list[Path]:
    excluded_names = excluded_names or set()
    return sorted(path for path in input_root.iterdir() if path.is_dir() and path.name not in excluded_names)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gộp các file Excel trong từng folder đã giải nén thành 1 file Excel tổng hợp."
    )
    parser.add_argument(
        "input_root",
        help="Thư mục gốc chứa các folder đã giải nén.",
    )
    parser.add_argument(
        "--output-dir",
        help="Thư mục xuất file Excel tổng hợp. Mặc định là <input_root>/_merged.",
    )
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_argument_parser()
    args = parser.parse_args()

    input_root = Path(args.input_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else input_root / "_merged"

    if not input_root.exists() or not input_root.is_dir():
        raise SystemExit(f"Thư mục không hợp lệ: {input_root}")

    excluded_names = {output_dir.name} if output_dir.parent == input_root else set()
    target_folders = iter_target_folders(input_root, excluded_names=excluded_names)
    if not target_folders:
        raise SystemExit(f"Không tìm thấy folder con nào trong: {input_root}")

    print(f"Input root: {input_root}")
    print(f"Output dir: {output_dir}")

    merged_count = 0
    for folder_path in target_folders:
        output_path, total_files, skipped = merge_folder(folder_path, output_dir)
        if output_path is None:
            print(f"[SKIP] {folder_path.name}: không tạo được file hợp lệ (tổng file: {total_files}, bỏ qua: {skipped})")
            continue

        merged_count += 1
        print(f"[OK] {folder_path.name}: {output_path.name} | tổng file: {total_files} | bỏ qua: {skipped}")

    print(f"Hoàn tất. Đã tạo {merged_count} file tổng hợp.")


if __name__ == "__main__":
    main()
