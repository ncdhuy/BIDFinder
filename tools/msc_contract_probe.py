"""Read-only, public-search-only probe for the official MSC contract.

This is research tooling, not an ingestion client. It sends anonymous public
``/search_prc`` requests and never persists response data, cookies, or
credentials. The old ``resultList`` parser remains for offline historical
fixture checks only; this probe never calls ``/search_prc/export``.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import ssl
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from tools.msc_search_pagination import (
        DEFAULT_SEARCH_PAGE_SIZE,
        DEFAULT_PARTITION_OVERLAP,
        MAX_SAFE_SEARCH_RESULTS,
        MIN_PARTITION_GRANULARITY,
        SEARCH_RESULT_WINDOW,
        SearchInterval,
        SearchPaginationError,
        SearchPartitionError,
        calculate_required_pages,
        parse_search_count as _parse_search_count,
        plan_partition,
        union_partition_records,
        validate_partition_completeness,
        validate_search_pages,
    )
except ModuleNotFoundError:  # direct `python tools/msc_contract_probe.py` execution
    from msc_search_pagination import (
        DEFAULT_SEARCH_PAGE_SIZE,
        DEFAULT_PARTITION_OVERLAP,
        MAX_SAFE_SEARCH_RESULTS,
        MIN_PARTITION_GRANULARITY,
        SEARCH_RESULT_WINDOW,
        SearchInterval,
        SearchPaginationError,
        SearchPartitionError,
        calculate_required_pages,
        parse_search_count as _parse_search_count,
        plan_partition,
        union_partition_records,
        validate_partition_completeness,
        validate_search_pages,
    )


SEARCH_ENDPOINT = (
    "https://muasamcong.mpi.gov.vn/"
    "o/egp-portal-winning-bid-data/services/smart/search_prc"
)
ALLOWED_ENDPOINTS = frozenset({SEARCH_ENDPOINT})
USER_AGENT = "BIDFinder-msc-contract-research/1.0"
DATE_FILTER = "ngay_dang_tai_kqlcnt"
EXPORT_CEILING = 30_000
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ContractProbeError(ValueError):
    """Invalid contract payload or an unusable MSC response."""


def weak_msc_tls_context() -> ssl.SSLContext:
    """Compatibility context for MSC's currently weak public TLS parameters."""

    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    return context


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


def with_page(payload: list[dict[str, Any]], page_number: int, page_size: int) -> list[dict[str, Any]]:
    if page_number < 0 or page_size <= 0:
        raise ContractProbeError("page number must be non-negative and page size must be positive")
    updated = copy.deepcopy(payload)
    for envelope in updated:
        envelope["pageNumber"] = page_number
        envelope["pageSize"] = page_size
    return updated


def with_empty_keyword(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = copy.deepcopy(payload)
    for envelope in updated:
        for query in envelope["query"]:
            query["keyWord"] = ""
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
        return _parse_search_count(response)
    except SearchPaginationError as exc:
        raise ContractProbeError(str(exc)) from exc


def parse_search_records(response: Any) -> list[dict[str, Any]]:
    try:
        records = response["page"]["content"]
    except (KeyError, TypeError) as exc:
        raise ContractProbeError("missing search result path page.content") from exc
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ContractProbeError("search result path page.content must be an object array")
    return records


def parse_export_records(response: Any) -> list[dict[str, Any]]:
    """Parse historical export fixtures; never used for production probing."""

    if not isinstance(response, dict) or not isinstance(response.get("resultList"), list):
        raise ContractProbeError("missing historical export result path resultList")
    if not all(isinstance(record, dict) for record in response["resultList"]):
        raise ContractProbeError("historical export resultList must be an object array")
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
    """Historical export comparison retained for offline fixture tests only."""

    if expected_count >= EXPORT_CEILING:
        return f"REFUSED: expected count {expected_count} reaches export ceiling {EXPORT_CEILING}"
    if expected_count != exported_count:
        return f"FAIL: count mismatch expected={expected_count} export={exported_count}"
    return f"PASS: expected={expected_count} export={exported_count}"


def _request_json(
    url: str,
    payload: list[dict[str, Any]],
    timeout: float,
    retries: int = 3,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, Any, int]:
    if url not in ALLOWED_ENDPOINTS:
        raise ContractProbeError("only the public MSC search endpoint is allowed")
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
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
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
    source_label: str | None,
    data_group: str | None,
    source_tab: str | None,
    date_range: str,
    timeout: float,
    page_size: int,
    repeat_first_page: bool,
    ssl_context: ssl.SSLContext | None,
) -> int:
    validate_payload(payload)
    payload = with_empty_keyword(payload)
    first_payload = with_page(payload, 0, page_size)
    started = time.monotonic()
    status, first_response, byte_count = _request_json(
        SEARCH_ENDPOINT, first_payload, timeout, ssl_context=ssl_context
    )
    print(f"source={source}")
    if source_label:
        print(f"source_label={source_label}")
    if data_group:
        print(f"data_group={data_group}")
    if source_tab:
        print(f"source_tab={source_tab}")
    print(f"date_range={date_range}")
    print(f"search_http={status}")
    if status != 200 or first_response is None:
        print(f"search_response_bytes={byte_count}")
        print("completeness=FAIL: malformed or non-200 public search response")
        return 1

    try:
        expected_count = parse_search_count(first_response)
        required = calculate_required_pages(expected_count, page_size)
    except SearchPaginationError as exc:
        print("agg_docCount=ERROR")
        print(f"completeness=FAIL: {exc}")
        return 1
    except ContractProbeError as exc:
        print(f"completeness=FAIL: {exc}")
        return 1

    responses = [first_response]
    request_pages = max(1, required)
    for page_number in range(1, request_pages):
        page_status, response, page_bytes = _request_json(
            SEARCH_ENDPOINT,
            with_page(payload, page_number, page_size),
            timeout,
            ssl_context=ssl_context,
        )
        if page_status != 200 or response is None:
            print(f"page_{page_number}_http={page_status}")
            print(f"page_{page_number}_response_bytes={page_bytes}")
            print("completeness=FAIL: required page was not a valid HTTP 200 JSON response")
            return 1
        responses.append(response)

    try:
        result = validate_search_pages(responses, page_size=page_size)
    except SearchPaginationError as exc:
        print(f"completeness=FAIL: {exc}")
        return 1

    records = list(result.records)
    ids = [record["id"] for record in records]
    print(f"expected_count={result.expected_count}")
    print(f"page_size={page_size}")
    print(f"max_safe_search_results={MAX_SAFE_SEARCH_RESULTS}")
    print(f"search_result_window={SEARCH_RESULT_WINDOW}")
    print(f"page_count={request_pages}")
    print(
        "page_metadata="
        + json.dumps(
            [
                {
                    "currentPage": page.get("currentPage"),
                    "pageSize": page.get("pageSize"),
                    "totalElements": page.get("totalElements"),
                    "totalPages": page.get("totalPages"),
                    "content_length": len(page.get("content", [])),
                }
                for page in result.page_metadata
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    print(f"collected_row_count={len(records)}")
    print(f"unique_uuid_count={len(result.uuids)}")
    print("duplicate_uuid_count=0")
    print("page_overlap_uuid_count=0")
    print(f"first_uuid={ids[0] if ids else None}")
    print(f"last_uuid={ids[-1] if ids else None}")
    print(f"field_names={','.join(_field_names(records))}")
    if repeat_first_page:
        repeat_status, repeat_response, _ = _request_json(
            SEARCH_ENDPOINT, first_payload, timeout, ssl_context=ssl_context
        )
        repeat_ids = []
        if repeat_status == 200 and repeat_response is not None:
            repeat_ids = [record.get("id") for record in parse_search_records(repeat_response)]
        same = repeat_status == 200 and repeat_ids == [record["id"] for record in responses[0]["page"]["content"]]
        print(f"repeat_page0_http={repeat_status}")
        print(f"repeat_page0_same_uuid_order={same}")
    print(f"latency_ms={round((time.monotonic() - started) * 1000)}")
    print("completeness=PASS")
    return 0


def _count_search_interval(
    payload: list[dict[str, Any]],
    interval: SearchInterval,
    *,
    page_size: int,
    timeout: float,
    ssl_context: ssl.SSLContext | None,
) -> int:
    ranged = with_date_range(payload, interval.from_value, interval.to_value)
    status, response, byte_count = _request_json(
        SEARCH_ENDPOINT,
        with_page(ranged, 0, page_size),
        timeout,
        ssl_context=ssl_context,
    )
    if status != 200 or response is None:
        raise SearchPartitionError(
            f"count interval HTTP {status} or malformed response bytes={byte_count}: "
            f"{interval.from_value}..{interval.to_value}"
        )
    count = parse_search_count(response)
    parse_search_records(response)
    page = response.get("page") if isinstance(response, dict) else None
    if not isinstance(page, dict):
        raise SearchPartitionError("count interval missing page envelope")
    if page.get("currentPage") != 0 or page.get("pageSize") != page_size:
        raise SearchPartitionError("count interval page metadata does not match page 0 request")
    if page.get("totalElements") != count and not (
        count > MAX_SAFE_SEARCH_RESULTS
        and page.get("totalElements") == SEARCH_RESULT_WINDOW
    ):
        raise SearchPartitionError(
            f"count interval totalElements {page.get('totalElements')} does not match agg {count}"
        )
    return count


def _leaf_records_for_child(
    leaf_results: list[tuple[SearchInterval, Any]], child: SearchInterval
) -> list[dict[str, Any]]:
    records = []
    for leaf, result in leaf_results:
        if child.from_value <= leaf.from_value and leaf.to_value <= child.to_value:
            records.extend(result.records)
    return records


def _observed_child_overlap(
    leaf_results: list[tuple[SearchInterval, Any]],
    diagnostic: Any,
) -> int:
    left_ids = {record["id"] for record in _leaf_records_for_child(leaf_results, diagnostic.left)}
    right_ids = {record["id"] for record in _leaf_records_for_child(leaf_results, diagnostic.right)}
    return len(left_ids & right_ids)


def run_partitioned_probe(
    payload: list[dict[str, Any]],
    *,
    source: str,
    source_label: str | None,
    data_group: str | None,
    source_tab: str | None,
    parent_from: str,
    parent_to: str,
    timeout: float,
    page_size: int,
    post_count: bool,
    overlap: timedelta = DEFAULT_PARTITION_OVERLAP,
    minimum_span: timedelta = MIN_PARTITION_GRANULARITY,
    max_depth: int = 16,
    ssl_context: ssl.SSLContext | None,
) -> int:
    validate_payload(payload)
    payload = with_empty_keyword(payload)
    parent = SearchInterval(parent_from, parent_to)

    print(f"source={source}")
    if source_label:
        print(f"source_label={source_label}")
    if data_group:
        print(f"data_group={data_group}")
    if source_tab:
        print(f"source_tab={source_tab}")
    print(f"parent_range={parent_from}..{parent_to}")
    print(f"safe_threshold={MAX_SAFE_SEARCH_RESULTS}")
    print(f"page_size={page_size}")
    print(f"overlap_ms={round(overlap.total_seconds() * 1000)}")

    try:
        plan = plan_partition(
            parent,
            lambda interval: _count_search_interval(
                payload,
                interval,
                page_size=page_size,
                timeout=timeout,
                ssl_context=ssl_context,
            ),
            max_safe_results=MAX_SAFE_SEARCH_RESULTS,
            overlap=overlap,
            minimum_span=minimum_span,
            max_depth=max_depth,
        )
        parent_count = plan.parent_interval.expected_count
        if parent_count is None:
            raise SearchPartitionError("partition plan missing parent count")
        print(f"parent_count={parent_count}")
        print(f"leaf_count={len(plan.safe_leaves)}")

        leaf_results: list[tuple[SearchInterval, Any]] = []
        total_pages = 0
        for index, leaf in enumerate(plan.safe_leaves, start=1):
            expected_count = leaf.expected_count
            if expected_count is None:
                raise SearchPartitionError(f"leaf {index} missing expected count")
            ranged = with_date_range(payload, leaf.from_value, leaf.to_value)
            required = calculate_required_pages(expected_count, page_size)
            responses = []
            for page_number in range(max(1, required)):
                status, response, byte_count = _request_json(
                    SEARCH_ENDPOINT,
                    with_page(ranged, page_number, page_size),
                    timeout,
                    ssl_context=ssl_context,
                )
                if status != 200 or response is None:
                    raise SearchPartitionError(
                        f"leaf {index} page {page_number} HTTP {status} or malformed response "
                        f"bytes={byte_count}"
                    )
                responses.append(response)
            actual_count = parse_search_count(responses[0])
            if actual_count != expected_count:
                raise SearchPartitionError(
                    f"leaf {index} count changed after planning expected={expected_count} "
                    f"actual={actual_count}"
                )
            result = validate_search_pages(responses, page_size=page_size)
            leaf_results.append((leaf, result))
            total_pages += result.required_pages or 1
            print(
                f"leaf_{index}={leaf.from_value}..{leaf.to_value} "
                f"count={result.expected_count} pages={result.required_pages or 1} "
                f"fetched={len(result.records)}"
            )

        union = union_partition_records(
            [result.records for _, result in leaf_results],
            expected_count=parent_count,
            leaf_intervals=[leaf for leaf, _ in leaf_results],
        )
        validate_partition_completeness(
            parent_count,
            union.unique_uuid_count,
        )
        print(f"raw_fetched_count={union.raw_record_count}")
        print(f"pages_required={total_pages}")
        print(f"boundary_duplicate_uuid_count={len(union.duplicate_uuids)}")
        print(f"boundary_duplicate_uuid_occurrences={union.duplicate_uuid_occurrences}")
        print("uuid_content_conflict_count=0")
        for split_index, diagnostic in enumerate(plan.diagnostics, start=1):
            print(
                f"split_{split_index}="
                f"parent={diagnostic.parent_count} left={diagnostic.left_count} "
                f"right={diagnostic.right_count} child_sum={diagnostic.child_count_sum} "
                f"overlap_surplus={diagnostic.overlap_surplus} "
                f"observed_child_overlap_uuid_count={_observed_child_overlap(leaf_results, diagnostic)}"
            )
        if post_count:
            post = _count_search_interval(
                payload,
                plan.parent_interval,
                page_size=page_size,
                timeout=timeout,
                ssl_context=ssl_context,
            )
            validate_partition_completeness(
                parent_count,
                union.unique_uuid_count,
                post_count=post,
            )
            print(f"pre_count={parent_count}")
            print(f"post_count={post}")
        else:
            print(f"pre_count={parent_count}")
            print("post_count=not_requested")
        print(f"unique_uuid_count={union.unique_uuid_count}")
        print("completeness=PASS")
        return 0
    except (ContractProbeError, SearchPaginationError) as exc:
        print(f"completeness=FAIL: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="raw MSC search request JSON file")
    parser.add_argument(
        "--contract",
        type=Path,
        help="verified source contract; sibling search-request.json is used by default",
    )
    parser.add_argument("--source", default="unknown", help="source identifier for summary output")
    parser.add_argument("--date", help="official calendar day, YYYY-MM-DD")
    parser.add_argument("--from", dest="from_value", help="explicit range start, ISO UTC")
    parser.add_argument("--to", dest="to_value", help="explicit range end, ISO UTC")
    parser.add_argument("--page-size", type=int, default=DEFAULT_SEARCH_PAGE_SIZE)
    parser.add_argument(
        "--validate-partitioned-search",
        action="store_true",
        help="developer-only adaptive intraday overflow validation; never production ingestion",
    )
    parser.add_argument(
        "--post-count",
        action="store_true",
        help="re-count parent interval after leaf retrieval",
    )
    parser.add_argument("--max-depth", type=int, default=16)
    parser.add_argument("--overlap-seconds", type=float, default=1.0)
    parser.add_argument("--minimum-span-milliseconds", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--no-repeat", action="store_true", help="skip repeat page-0 stability check")
    parser.add_argument(
        "--allow-weak-tls",
        action="store_true",
        help="research-only compatibility for MSC weak DH TLS parameters; never use in production",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.request and not args.contract:
            raise ContractProbeError("one of --contract or --request is required")
        contract = None
        if args.contract:
            contract = json.loads(args.contract.read_text(encoding="utf-8"))
            if contract.get("contract_evidence_status") != "VERIFIED":
                raise ContractProbeError("source contract must have VERIFIED evidence status")
            request_path = args.request or args.contract.with_name("search-request.json")
            source = args.source if args.source != "unknown" else args.contract.parent.name
        else:
            request_path = args.request
            source = args.source
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        validate_payload(payload)
        from_value, to_value, date_range = date_range_from_args(args)
        if from_value and to_value:
            payload = with_date_range(payload, from_value, to_value)
        elif date_range == "request payload":
            date_range = payload_date_range(payload)
        if args.validate_partitioned_search:
            if not from_value or not to_value:
                raise ContractProbeError(
                    "--validate-partitioned-search requires --date or --from/--to"
                )
            if args.overlap_seconds <= 0 or args.minimum_span_milliseconds <= 0:
                raise ContractProbeError("partition overlap and minimum span must be positive")
            return run_partitioned_probe(
                payload,
                source=source,
                source_label=contract.get("source_tab_label") if contract else None,
                data_group=contract.get("data_group") if contract else None,
                source_tab=contract.get("source_tab") if contract else None,
                parent_from=from_value,
                parent_to=to_value,
                timeout=args.timeout,
                page_size=args.page_size,
                post_count=args.post_count,
                overlap=timedelta(seconds=args.overlap_seconds),
                minimum_span=timedelta(milliseconds=args.minimum_span_milliseconds),
                max_depth=args.max_depth,
                ssl_context=weak_msc_tls_context() if args.allow_weak_tls else None,
            )
        payload = with_page(payload, 0, args.page_size)
        return run_probe(
            payload,
            source=source,
            source_label=contract.get("source_tab_label") if contract else None,
            data_group=contract.get("data_group") if contract else None,
            source_tab=contract.get("source_tab") if contract else None,
            date_range=date_range,
            timeout=args.timeout,
            page_size=args.page_size,
            repeat_first_page=not args.no_repeat,
            ssl_context=weak_msc_tls_context() if args.allow_weak_tls else None,
        )
    except (OSError, json.JSONDecodeError, ContractProbeError) as exc:
        print(f"probe_error={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
