#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Raw VSS crawler for BIDFinder.

This script intentionally downloads and catalogs raw VSS export files only.
Cleaning, parsing, deduplication, and business-specific ETL should happen in a
later pipeline after the raw source has been captured reliably.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://quanlythuocv1.vss.gov.vn/kqdt/export"
DEFAULT_RAW_DIR = "../vss_data/downloads"
DEFAULT_MANIFEST_FILE = "../vss_data/crawl_manifest.csv"
DEFAULT_LOG_FILE = "../vss_data/download_log.log"
DEFAULT_EXCEL_FILE = "../vss_data/combined_raw_for_cleaning.xlsx"
EXCEL_MAX_ROWS = 1048576
SOURCE_COLUMNS = ["_source_date", "_source_file"]
SPREADSHEET_NS = "{urn:schemas-microsoft-com:office:spreadsheet}"
ILLEGAL_XML_CHARS_RE = re.compile(
    "[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)
STRAY_LT_RE = re.compile(r"<(?!/?[A-Za-z_][\w:.-]*(?:\s|>|/)|!|\?)")
UNSAFE_AMP_RE = re.compile(
    r"&(?!(?:amp|lt|gt|apos|quot);|#[0-9]+;|#x[0-9a-fA-F]+;)"
)

MANIFEST_COLUMNS = [
    "date",
    "status",
    "url",
    "raw_path",
    "bytes",
    "sha256",
    "http_status",
    "content_type",
    "attempts",
    "error",
    "downloaded_at",
]


@dataclass
class CrawlResult:
    date: str
    status: str
    url: str
    raw_path: str = ""
    bytes: int = 0
    sha256: str = ""
    http_status: str = ""
    content_type: str = ""
    attempts: int = 0
    error: str = ""
    downloaded_at: str = ""

    def as_row(self) -> Dict[str, str]:
        return {
            "date": self.date,
            "status": self.status,
            "url": self.url,
            "raw_path": self.raw_path,
            "bytes": str(self.bytes),
            "sha256": self.sha256,
            "http_status": str(self.http_status),
            "content_type": self.content_type,
            "attempts": str(self.attempts),
            "error": self.error,
            "downloaded_at": self.downloaded_at,
        }


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def parse_yyyy_mm_dd(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def parse_manifest_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def iter_dates(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def extract_date_from_path(path: Path) -> Optional[date]:
    match = re.search(r"(\d{8})", path.name)
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def sanitize_xml_bytes(payload: bytes) -> bytes:
    text = payload.decode("utf-8", errors="ignore")
    text = ILLEGAL_XML_CHARS_RE.sub("", text)
    text = STRAY_LT_RE.sub("&lt;", text)
    text = UNSAFE_AMP_RE.sub("&amp;", text)
    return text.encode("utf-8")


def cell_text(cell: ET.Element) -> str:
    data = cell.find(f"{SPREADSHEET_NS}Data")
    if data is None:
        data = cell.find("Data")
    if data is None:
        return ""
    return "".join(data.itertext()).strip()


def row_values(row: ET.Element) -> List[str]:
    values: List[str] = []
    for cell in list(row):
        if not cell.tag.endswith("Cell"):
            continue

        index_value = cell.attrib.get(f"{SPREADSHEET_NS}Index") or cell.attrib.get("ss:Index")
        if index_value:
            try:
                target_index = int(index_value) - 1
                while len(values) < target_index:
                    values.append("")
            except ValueError:
                pass

        values.append(cell_text(cell))
    return values


def iter_excel_xml_rows(xml_file: Path) -> Iterator[List[str]]:
    payload = sanitize_xml_bytes(xml_file.read_bytes())
    context = ET.iterparse(io.BytesIO(payload), events=("end",))

    for _, element in context:
        if element.tag.endswith("Row"):
            yield row_values(element)
            element.clear()


def read_xml_header(xml_file: Path) -> List[str]:
    for row in iter_excel_xml_rows(xml_file):
        if any(value != "" for value in row):
            return row
    return []


def make_session(
    retries: int,
    backoff_factor: float,
    user_agent: str,
) -> requests.Session:
    retry_config = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_config, pool_connections=32, pool_maxsize=32)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
    )
    return session


class ManifestStore:
    def __init__(self, manifest_file: Path, raw_dir: Path):
        self.manifest_file = manifest_file
        self.raw_dir = raw_dir
        self.rows: Dict[str, Dict[str, str]] = self._load()

    def _load(self) -> Dict[str, Dict[str, str]]:
        if not self.manifest_file.exists():
            return {}

        with self.manifest_file.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            rows = {}
            for row in reader:
                row_date = row.get("date")
                if row_date:
                    entry = {column: row.get(column, "") for column in MANIFEST_COLUMNS}
                    parsed_date = parse_manifest_date(row_date)
                    if parsed_date:
                        local_path = (
                            self.raw_dir / parsed_date.strftime("%Y") / parsed_date.strftime("%m")
                            / f"vss_export_{parsed_date:%Y%m%d}.xml"
                        )
                        legacy_path = self.raw_dir / f"data_{parsed_date:%Y%m%d}.xml"
                        entry["raw_path"] = (
                            str(local_path) if local_path.exists()
                            else str(legacy_path) if legacy_path.exists() else ""
                        )
                    rows[row_date] = entry
            return rows

    def should_skip(self, item_date: date, force: bool) -> bool:
        if force:
            return False

        row = self.rows.get(item_date.isoformat())
        if not row:
            return False

        raw_path = row.get("raw_path", "")
        return row.get("status") in {"downloaded", "existing"} and raw_path and Path(raw_path).exists()

    def upsert(self, result: CrawlResult) -> None:
        self.rows[result.date] = result.as_row()
        self.flush()

    def flush(self) -> None:
        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.manifest_file.with_suffix(self.manifest_file.suffix + ".tmp")
        ordered_dates = sorted(self.rows)

        with temp_file.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=MANIFEST_COLUMNS)
            writer.writeheader()
            for row_date in ordered_dates:
                writer.writerow({column: self.rows[row_date].get(column, "") for column in MANIFEST_COLUMNS})

        os.replace(temp_file, self.manifest_file)


class VSSRawCrawler:
    def __init__(
        self,
        raw_dir: Path,
        manifest: ManifestStore,
        timeout: tuple[float, float],
        retries: int,
        backoff_factor: float,
        throttle_seconds: float,
        user_agent: str,
        force: bool = False,
    ):
        self.raw_dir = raw_dir
        self.manifest = manifest
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.throttle_seconds = throttle_seconds
        self.user_agent = user_agent
        self.force = force

    def build_url(self, item_date: date) -> str:
        params = {
            "ngaycongbo": item_date.strftime("%d/%m/%Y"),
            "loai": "1",
        }
        return f"{BASE_URL}?{urlencode(params)}"

    def raw_path_for(self, item_date: date) -> Path:
        return (
            self.raw_dir
            / item_date.strftime("%Y")
            / item_date.strftime("%m")
            / f"vss_export_{item_date.strftime('%Y%m%d')}.xml"
        )

    def legacy_raw_path_for(self, item_date: date) -> Path:
        return self.raw_dir / f"data_{item_date.strftime('%Y%m%d')}.xml"

    def crawl_range(self, start_date: date, end_date: date, max_workers: int) -> None:
        requested_dates = list(iter_dates(start_date, end_date))
        pending_dates = []

        for item_date in requested_dates:
            if self.manifest.should_skip(item_date, force=self.force):
                logging.info("Skipping %s because manifest already has a raw file", item_date)
                continue

            legacy_path = self.legacy_raw_path_for(item_date)
            target_path = self.raw_path_for(item_date)
            if not self.force and target_path.exists():
                self.manifest.upsert(self._result_from_existing_file(item_date, target_path))
                logging.info("Cataloged existing raw file for %s: %s", item_date, target_path)
                continue

            if not self.force and legacy_path.exists():
                self.manifest.upsert(self._result_from_existing_file(item_date, legacy_path))
                logging.info("Cataloged legacy raw file for %s: %s", item_date, legacy_path)
                continue

            pending_dates.append(item_date)

        if not pending_dates:
            logging.info("No dates to download. Raw catalog is already up to date.")
            return

        logging.info(
            "Downloading %s date(s) with %s worker(s)",
            len(pending_dates),
            max_workers,
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.download_one, item_date): item_date
                for item_date in pending_dates
            }

            for future in as_completed(futures):
                item_date = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logging.exception("Unexpected failure while crawling %s", item_date)
                    result = CrawlResult(
                        date=item_date.isoformat(),
                        status="failed",
                        url=self.build_url(item_date),
                        attempts=self.retries + 1,
                        error=str(exc),
                        downloaded_at=datetime.now().isoformat(timespec="seconds"),
                    )

                self.manifest.upsert(result)
                if result.status == "downloaded":
                    logging.info(
                        "Downloaded %s (%s bytes) -> %s",
                        result.date,
                        result.bytes,
                        result.raw_path,
                    )
                else:
                    logging.warning("%s ended with status=%s error=%s", result.date, result.status, result.error)

    def download_one(self, item_date: date) -> CrawlResult:
        session = make_session(
            retries=self.retries,
            backoff_factor=self.backoff_factor,
            user_agent=self.user_agent,
        )

        item_date_str = item_date.isoformat()
        url = self.build_url(item_date)
        target_path = self.raw_path_for(item_date)
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        attempts = self.retries + 1

        if self.throttle_seconds > 0:
            time.sleep(self.throttle_seconds)

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            response = session.get(url, timeout=self.timeout)
            content_type = response.headers.get("Content-Type", "")
            http_status = str(response.status_code)

            if response.status_code != 200:
                return CrawlResult(
                    date=item_date_str,
                    status="http_error",
                    url=url,
                    http_status=http_status,
                    content_type=content_type,
                    attempts=attempts,
                    error=f"Unexpected HTTP status {response.status_code}",
                    downloaded_at=datetime.now().isoformat(timespec="seconds"),
                )

            payload = response.content or b""
            if not payload:
                return CrawlResult(
                    date=item_date_str,
                    status="empty",
                    url=url,
                    http_status=http_status,
                    content_type=content_type,
                    attempts=attempts,
                    error="Response body is empty",
                    downloaded_at=datetime.now().isoformat(timespec="seconds"),
                )

            digest = hashlib.sha256(payload).hexdigest()
            with temp_path.open("wb") as file:
                file.write(payload)
            os.replace(temp_path, target_path)

            return CrawlResult(
                date=item_date_str,
                status="downloaded",
                url=url,
                raw_path=str(target_path),
                bytes=len(payload),
                sha256=digest,
                http_status=http_status,
                content_type=content_type,
                attempts=attempts,
                downloaded_at=datetime.now().isoformat(timespec="seconds"),
            )
        except requests.RequestException as exc:
            return CrawlResult(
                date=item_date_str,
                status="request_failed",
                url=url,
                attempts=attempts,
                error=str(exc),
                downloaded_at=datetime.now().isoformat(timespec="seconds"),
            )
        finally:
            session.close()
            if temp_path.exists():
                temp_path.unlink()

    def _result_from_existing_file(self, item_date: date, raw_path: Path) -> CrawlResult:
        payload = raw_path.read_bytes()
        return CrawlResult(
            date=item_date.isoformat(),
            status="existing",
            url=self.build_url(item_date),
            raw_path=str(raw_path),
            bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            attempts=0,
            downloaded_at=datetime.now().isoformat(timespec="seconds"),
        )


class RawExcelBuilder:
    def __init__(
        self,
        raw_dir: Path,
        manifest: ManifestStore,
        output_file: Path,
        sheet_row_limit: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        self.raw_dir = raw_dir
        self.manifest = manifest
        self.output_file = output_file
        self.sheet_row_limit = sheet_row_limit
        self.start_date = start_date
        self.end_date = end_date

    def build(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise SystemExit("openpyxl is required to build the combined Excel file.") from exc

        raw_files = self.collect_raw_files()
        if not raw_files:
            logging.warning("No raw XML files found for Excel build.")
            return

        logging.info("Building combined Excel from %s raw XML file(s)", len(raw_files))
        headers = self.collect_headers(raw_files)
        if not headers:
            logging.warning("No headers found in raw XML files.")
            return

        workbook = Workbook(write_only=True)
        sheet_index = 1
        worksheet = workbook.create_sheet(title=self.sheet_name(sheet_index))
        output_headers = SOURCE_COLUMNS + headers
        worksheet.append(output_headers)
        current_sheet_rows = 1
        total_rows = 0
        parsed_files = 0
        failed_files = 0

        for item_date, raw_file in raw_files:
            try:
                row_count = 0
                file_headers: List[str] = []
                for row_index, row in enumerate(iter_excel_xml_rows(raw_file)):
                    if row_index == 0:
                        file_headers = [value.strip() for value in row]
                        continue
                    if not any(value != "" for value in row):
                        continue

                    if current_sheet_rows >= self.sheet_row_limit:
                        sheet_index += 1
                        worksheet = workbook.create_sheet(title=self.sheet_name(sheet_index))
                        worksheet.append(output_headers)
                        current_sheet_rows = 1

                    record = self.align_row(headers, file_headers, row)
                    worksheet.append([item_date.isoformat(), str(raw_file)] + record)
                    current_sheet_rows += 1
                    total_rows += 1
                    row_count += 1

                parsed_files += 1
                logging.info("Added %s row(s) from %s", row_count, raw_file)
            except Exception as exc:
                failed_files += 1
                logging.warning("Failed to add %s to Excel: %s", raw_file, exc)

        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(self.output_file)
        logging.info(
            "Excel build finished: %s rows, %s parsed file(s), %s failed file(s), output=%s",
            total_rows,
            parsed_files,
            failed_files,
            self.output_file,
        )

    def collect_raw_files(self) -> List[Tuple[date, Path]]:
        files: Dict[date, Path] = {}

        for row in self.manifest.rows.values():
            if row.get("status") not in {"downloaded", "existing"}:
                continue
            raw_path = row.get("raw_path", "")
            if not raw_path:
                continue
            item_date = parse_manifest_date(row.get("date", ""))
            path = Path(raw_path)
            if item_date and path.exists() and self.in_date_range(item_date):
                files[item_date] = path

        for pattern in ("*.xml", "**/*.xml"):
            for path in self.raw_dir.glob(pattern):
                item_date = extract_date_from_path(path)
                if item_date and self.in_date_range(item_date):
                    files.setdefault(item_date, path)

        legacy_dir = self.raw_dir
        for path in legacy_dir.glob("data_*.xml"):
            item_date = extract_date_from_path(path)
            if item_date and self.in_date_range(item_date):
                files.setdefault(item_date, path)

        return sorted(files.items(), key=lambda item: item[0])

    def collect_headers(self, raw_files: Sequence[Tuple[date, Path]]) -> List[str]:
        headers: List[str] = []
        seen = set()

        for _, raw_file in raw_files:
            try:
                for header in read_xml_header(raw_file):
                    clean_header = header.strip()
                    if clean_header and clean_header not in seen:
                        headers.append(clean_header)
                        seen.add(clean_header)
            except Exception as exc:
                logging.warning("Failed to read header from %s: %s", raw_file, exc)

        return headers

    def align_row(
        self,
        canonical_headers: Sequence[str],
        file_headers: Sequence[str],
        row: Sequence[str],
    ) -> List[str]:
        if not file_headers:
            values = list(row)
            if len(values) < len(canonical_headers):
                values.extend([""] * (len(canonical_headers) - len(values)))
            return values[: len(canonical_headers)]

        row_by_header = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(file_headers)
            if header
        }
        return [row_by_header.get(header, "") for header in canonical_headers]

    def in_date_range(self, item_date: date) -> bool:
        if self.start_date and item_date < self.start_date:
            return False
        if self.end_date and item_date > self.end_date:
            return False
        return True

    def sheet_name(self, sheet_index: int) -> str:
        return f"raw_{sheet_index:03d}"


def resolve_path(script_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return script_dir / path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download raw VSS export files for BIDFinder and optionally build a combined Excel workbook.",
    )
    parser.add_argument("--start-date", type=parse_yyyy_mm_dd, help="Start date, format YYYY-MM-DD.")
    parser.add_argument("--end-date", type=parse_yyyy_mm_dd, help="End date, format YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR, help=f"Raw output directory. Default: {DEFAULT_RAW_DIR}")
    parser.add_argument(
        "--manifest-file",
        default=DEFAULT_MANIFEST_FILE,
        help=f"CSV manifest path. Default: {DEFAULT_MANIFEST_FILE}",
    )
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help=f"Log file path. Default: {DEFAULT_LOG_FILE}")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent download workers. Default: 4.")
    parser.add_argument("--retries", type=int, default=3, help="Retry count for transient HTTP failures. Default: 3.")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="Connect timeout in seconds. Default: 10.")
    parser.add_argument("--read-timeout", type=float, default=60.0, help="Read timeout in seconds. Default: 60.")
    parser.add_argument("--backoff", type=float, default=1.0, help="Retry backoff factor. Default: 1.")
    parser.add_argument("--throttle", type=float, default=0.0, help="Sleep before each request in seconds. Default: 0.")
    parser.add_argument("--force", action="store_true", help="Re-download even if a raw file is already cataloged.")
    parser.add_argument("--skip-crawl", action="store_true", help="Do not crawl. Useful when only building Excel from raw files.")
    parser.add_argument("--build-excel", action="store_true", help="Build a combined Excel workbook from raw XML files.")
    parser.add_argument(
        "--excel-file",
        default=DEFAULT_EXCEL_FILE,
        help=f"Combined Excel output path. Default: {DEFAULT_EXCEL_FILE}",
    )
    parser.add_argument(
        "--excel-sheet-row-limit",
        type=int,
        default=EXCEL_MAX_ROWS,
        help=f"Rows per Excel sheet including header. Default: {EXCEL_MAX_ROWS}.",
    )
    parser.add_argument(
        "--user-agent",
        default="BIDFinder-VSSRawCrawler/1.0",
        help="User-Agent header for requests.",
    )
    return parser


def read_date_from_prompt(label: str, default: Optional[date] = None) -> date:
    suffix = f" [{default.isoformat()}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default:
            return default
        try:
            return parse_yyyy_mm_dd(value)
        except argparse.ArgumentTypeError as exc:
            print(exc)


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    parser = build_parser()
    args = parser.parse_args()

    log_file = resolve_path(script_dir, args.log_file)
    configure_logging(log_file)

    start_date = args.start_date
    end_date = args.end_date or date.today()

    should_crawl = not args.skip_crawl
    should_build_excel = args.build_excel
    interactive_mode = should_crawl and start_date is None

    if interactive_mode:
        start_date = read_date_from_prompt("Enter start date (YYYY-MM-DD)")
    if interactive_mode and args.end_date is None and "--end-date" not in sys.argv:
        end_date = read_date_from_prompt("Enter end date (YYYY-MM-DD)", default=end_date)

    if should_crawl and start_date is None:
        raise SystemExit("--start-date is required unless --skip-crawl is used.")
    if start_date and start_date > end_date:
        raise SystemExit("Start date cannot be after end date.")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1.")
    if args.retries < 0:
        raise SystemExit("--retries must be at least 0.")
    if args.excel_sheet_row_limit < 2 or args.excel_sheet_row_limit > EXCEL_MAX_ROWS:
        raise SystemExit(f"--excel-sheet-row-limit must be between 2 and {EXCEL_MAX_ROWS}.")
    if not should_crawl and not should_build_excel:
        raise SystemExit("Nothing to do. Remove --skip-crawl or add --build-excel.")

    raw_dir = resolve_path(script_dir, args.raw_dir)
    manifest_file = resolve_path(script_dir, args.manifest_file)
    manifest = ManifestStore(manifest_file, raw_dir)

    if should_crawl:
        crawler = VSSRawCrawler(
            raw_dir=raw_dir,
            manifest=manifest,
            timeout=(args.connect_timeout, args.read_timeout),
            retries=args.retries,
            backoff_factor=args.backoff,
            throttle_seconds=args.throttle,
            user_agent=args.user_agent,
            force=args.force,
        )

        logging.info("BIDFinder VSS raw crawl started: %s -> %s", start_date, end_date)
        logging.info("Raw dir: %s", raw_dir)
        logging.info("Manifest: %s", manifest_file)
        crawler.crawl_range(start_date, end_date, max_workers=args.workers)
        logging.info("BIDFinder VSS raw crawl finished")

    if should_build_excel:
        excel_file = resolve_path(script_dir, args.excel_file)
        builder = RawExcelBuilder(
            raw_dir=raw_dir,
            manifest=manifest,
            output_file=excel_file,
            sheet_row_limit=args.excel_sheet_row_limit,
            start_date=start_date,
            end_date=end_date if start_date else args.end_date,
        )
        builder.build()


if __name__ == "__main__":
    main()
