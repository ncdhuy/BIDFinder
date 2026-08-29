"""Read-only probe for the official MSC winning-bid-data contract.

This is research tooling, not an ingestion client. It accepts a raw MSC
request payload and never persists response data, cookies, or credentials.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SEARCH_ENDPOINT = (
    "https://muasamcong.mpi.gov.vn/"
    "o/egp-portal-winning-bid-data/services/smart/search_prc"
)
EXPORT_ENDPOINT = SEARCH_ENDPOINT + "/export"
ALLOWED_ENDPOINTS = frozenset({SEARCH_ENDPOINT, EXPORT_ENDPOINT})
USER_AGENT = "BIDFinder-msc-contract-research/1.0"
DATE_FILTER = "ngay_dang_tai_kqlcnt"
EXPORT_CEILING = 30_000
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ContractProbeError(ValueError):
    """Invalid contract payload or an unusable MSC response."""


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_payload(payload: Any) -> None:
    """Validate the small, known MSC request envelope before sending it."""

    if not isinstance(payload, list) or not payload:
        raise ContractProbeError("request must be a non-empty JSON array")
    for envelope in payload:
        if not isinstance(envelope, dict):
            raise ContractProbeError("request envelope must be an object")
        if not _is_non_negative_int(envelope.get("pageSize")):
            raise ContractProbeError("pageSize must be a non-negative integer")
        if not _is_non_negative_int(envelope.get("pageNumber")):
            raise ContractProbeError("pageNumber must be a non-negative integer")
        queries = envelope.get("query")
        if not isinstance(queries, list) or not queries:
            raise ContractProbeError("request query must be a non-empty array")
        for query in queries:
            if not isinstance(query, dict):
                raise ContractProbeError("query item must be an object")
            if query.get("index") != "es-smart-pricing":
                raise ContractProbeError("query index must be es-smart-pricing")
            if not isinstance(query.get("keyWord"), str):
                raise ContractProbeError("keyWord must be a string")
            if not isinstance(query.get("keyWordNotMatch"), str):
                raise ContractProbeError("keyWordNotMatch must be a string")
            if not isinstance(query.get("matchType"), str):
                raise ContractProbeError("matchType must be a string")
            if not isinstance(query.get("matchFields"), list) or not all(
                isinstance(field, str) for field in query["matchFields"]
            ):
                raise ContractProbeError("matchFields must be a string array")
            if not isinstance(query.get("filters"), list):
                raise ContractProbeError("filters must be an array")


def with_date_range(payload: list[dict[str, Any]], from_value: str, to_value: str) -> list[dict[str, Any]]:
    """Return payload copy with the official date filter replaced or added."""

    if not _ISO_RE.fullmatch(from_value) or not _ISO_RE.fullmatch(to_value):
        raise ContractProbeError("from/to must use YYYY-MM-DDTHH:MM:SS.mmmZ")
    updated = copy.deepcopy(payload)
    date_filter = {
        "fieldName": DATE_FILTER,
        "searchType": "range",
        "from": from_value,
        "to": to_value,
    }
    for envelope in updated:
        for query in envelope["query"]:
            filters = query["filters"]
            for index, item in enumerate(filters):
                if isinstance(item, dict) and item.get("fieldName") == DATE_FILTER:
                    filters[index] = date_filter
                    break
            else:
                filters.append(date_filter)
    return updated


def date_range_from_args(args: argparse.Namespace) -> tuple[str | None, str | None, str]:
    if args.date and (args.from_value or args.to_value):
        raise ContractProbeError("use --date or --from/--to, not both")
    if bool(args.from_value) != bool(args.to_value):
        raise ContractProbeError("--from and --to must be supplied together")
    if args.date:
        if not _DATE_RE.fullmatch(args.date):
            raise ContractProbeError("--date must use YYYY-MM-DD")
        return (
            f"{args.date}T00:00:00.000Z",
            f"{args.date}T23:59:59.059Z",
            args.date,
        )
    if args.from_value:
        return args.from_value, args.to_value, f"{args.from_value}..{args.to_value}"
    return None, None, "request payload"


def payload_date_range(payload: list[dict[str, Any]]) -> str:
    values = []
    for envelope in payload:
        for query in envelope["query"]:
            for item in query["filters"]:
                if isinstance(item, dict) and item.get("fieldName") == DATE_FILTER:
                    values.append((item.get("from"), item.get("to")))
    if not values:
        return "not specified"
    if len(set(values)) != 1:
        return "multiple ranges"
    start, end = values[0]
    return f"{start}..{end}"


def parse_search_count(response: Any) -> int:
    try:
        count = response["agg"][0]["buckets"][0]["docCount"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ContractProbeError("missing search aggregation agg[0].buckets[0].docCount") from exc
    if not _is_non_negative_int(count):
        raise ContractProbeError("search docCount must be a non-negative integer")
    return count


def parse_search_records(response: Any) -> list[dict[str, Any]]:
    try:
        records = response["page"]["content"]
    except (KeyError, TypeError) as exc:
        raise ContractProbeError("missing search result path page.content") from exc
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ContractProbeError("search result path page.content must be an object array")
    return records


def parse_export_records(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict) or not isinstance(response.get("resultList"), list):
        raise ContractProbeError("missing export result path resultList")
    if not all(isinstance(record, dict) for record in response["resultList"]):
        raise ContractProbeError("export resultList must be an object array")
    return response["resultList"]


def detect_duplicate_ids(records: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = record.get("id")
        if isinstance(value, str) and value in seen:
            duplicates.add(value)
        if isinstance(value, str):
            seen.add(value)
    return sorted(duplicates)


def check_completeness(expected_count: int, exported_count: int) -> str:
    if expected_count >= EXPORT_CEILING:
        return f"REFUSED: expected count {expected_count} reaches export ceiling {EXPORT_CEILING}"
    if expected_count != exported_count:
        return f"FAIL: count mismatch expected={expected_count} export={exported_count}"
    return f"PASS: expected={expected_count} export={exported_count}"


def _request_json(url: str, payload: list[dict[str, Any]], timeout: float, retries: int = 3) -> tuple[int, Any, int]:
    if url not in ALLOWED_ENDPOINTS:
        raise ContractProbeError("endpoint is outside the official MSC allow-list")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries + 1):
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
            if status not in {429, *range(500, 600)} or attempt >= retries:
                return status, None, len(raw)
        except (TimeoutError, URLError, OSError):
            if attempt >= retries:
                raise ContractProbeError("network failure after bounded retries") from None
            raw = b""
            status = 0
        else:
            try:
                return status, json.loads(raw.decode("utf-8")), len(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return status, None, len(raw)
        time.sleep(attempt + 1)
    raise ContractProbeError("request failed after bounded retries")


def _field_names(records: list[dict[str, Any]]) -> list[str]:
    return sorted({key for record in records for key in record})


def run_probe(
    payload: list[dict[str, Any]],
    *,
    source: str,
    date_range: str,
    timeout: float,
    with_export: bool,
) -> int:
    validate_payload(payload)
    status, search_response, byte_count = _request_json(SEARCH_ENDPOINT, payload, timeout)
    print(f"source={source}")
    print(f"date_range={date_range}")
    print(f"search_http={status}")
    if search_response is None:
        print(f"search_response_bytes={byte_count}")
        print("completeness=FAIL: malformed or non-JSON search response")
        return 1
    try:
        expected_count = parse_search_count(search_response)
        records = parse_search_records(search_response)
    except ContractProbeError as exc:
        print(f"completeness=FAIL: {exc}")
        return 1
    ids = [record.get("id") for record in records if isinstance(record.get("id"), str)]
    print(f"agg_docCount={expected_count}")
    print(f"search_record_count={len(records)}")
    print(f"first_uuid={ids[0] if ids else None}")
    print(f"last_uuid={ids[-1] if ids else None}")
    print(f"field_names={','.join(_field_names(records))}")
    duplicates = detect_duplicate_ids(records)
    print(f"search_duplicate_uuid_count={len(duplicates)}")
    if not with_export:
        print("completeness=NOT_REQUESTED: export not requested")
        return 0
    if expected_count >= EXPORT_CEILING:
        print(f"export_http=REFUSED (expected count >= {EXPORT_CEILING})")
        print(f"completeness={check_completeness(expected_count, 0)}")
        return 1
    export_status, export_response, export_bytes = _request_json(EXPORT_ENDPOINT, payload, timeout)
    print(f"export_http={export_status}")
    if export_response is None:
        print(f"export_response_bytes={export_bytes}")
        print("export_result_count=ERROR")
        print("completeness=FAIL: malformed or non-JSON export response")
        return 1
    try:
        exported = parse_export_records(export_response)
    except ContractProbeError as exc:
        print(f"export_result_count=ERROR")
        print(f"completeness=FAIL: {exc}")
        return 1
    print(f"export_result_count={len(exported)}")
    export_ids = [record.get("id") for record in exported if isinstance(record.get("id"), str)]
    print(f"export_first_uuid={export_ids[0] if export_ids else None}")
    print(f"export_last_uuid={export_ids[-1] if export_ids else None}")
    print(f"export_duplicate_uuid_count={len(detect_duplicate_ids(exported))}")
    result = check_completeness(expected_count, len(exported))
    print(f"completeness={result}")
    return 0 if result.startswith("PASS") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="raw MSC request JSON file")
    parser.add_argument("--source", default="unknown", help="source identifier for summary output")
    parser.add_argument("--date", help="official calendar day, YYYY-MM-DD")
    parser.add_argument("--from", dest="from_value", help="explicit range start, ISO UTC")
    parser.add_argument("--to", dest="to_value", help="explicit range end, ISO UTC")
    parser.add_argument("--with-export", action="store_true", help="run search then export")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.request.read_text(encoding="utf-8"))
        validate_payload(payload)
        from_value, to_value, date_range = date_range_from_args(args)
        if from_value and to_value:
            payload = with_date_range(payload, from_value, to_value)
        elif date_range == "request payload":
            date_range = payload_date_range(payload)
        return run_probe(
            payload,
            source=args.source,
            date_range=date_range,
            timeout=args.timeout,
            with_export=args.with_export,
        )
    except (OSError, json.JSONDecodeError, ContractProbeError) as exc:
        print(f"probe_error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
