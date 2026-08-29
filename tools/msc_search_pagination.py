"""Pure validation for complete public MSC search partitions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence


SEARCH_RESULT_WINDOW = 10_000
MAX_SAFE_DAILY_RESULTS = 9_500
DEFAULT_SEARCH_PAGE_SIZE = 1_000


class SearchPaginationError(ValueError):
    """A public search response cannot prove a complete partition."""


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def parse_search_count(response: Any) -> int:
    try:
        count = response["agg"][0]["buckets"][0]["docCount"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SearchPaginationError(
            "missing search aggregation agg[0].buckets[0].docCount"
        ) from exc
    if not _is_non_negative_int(count):
        raise SearchPaginationError("search docCount must be a non-negative integer")
    return count


def calculate_required_pages(
    expected_count: int,
    page_size: int,
    *,
    max_safe_results: int = MAX_SAFE_DAILY_RESULTS,
    result_window: int = SEARCH_RESULT_WINDOW,
) -> int:
    """Return ceil(expected_count / page_size), rejecting unsafe partitions."""

    if not _is_non_negative_int(expected_count):
        raise SearchPaginationError("expected count must be a non-negative integer")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
        raise SearchPaginationError("page size must be a positive integer")
    if (
        not isinstance(max_safe_results, int)
        or isinstance(max_safe_results, bool)
        or max_safe_results <= 0
        or max_safe_results > result_window
    ):
        raise SearchPaginationError("safe result threshold must be within the result window")
    if expected_count >= max_safe_results:
        raise SearchPaginationError(
            f"expected count {expected_count} reaches safe daily threshold {max_safe_results}"
        )
    required = math.ceil(expected_count / page_size)
    if required and (required - 1) * page_size >= result_window:
        raise SearchPaginationError(
            f"required page offset reaches search result window {result_window}"
        )
    return required


def _parse_page(response: Any, page_number: int, page_size: int) -> dict[str, Any]:
    if not isinstance(response, dict) or not isinstance(response.get("page"), dict):
        raise SearchPaginationError("missing search result envelope page")
    page = response["page"]
    required = ("content", "currentPage", "pageSize", "totalElements", "totalPages")
    missing = [key for key in required if key not in page]
    if missing:
        raise SearchPaginationError(f"missing page metadata: {','.join(missing)}")
    if page["currentPage"] != page_number:
        raise SearchPaginationError(
            f"page currentPage {page['currentPage']} does not match requested {page_number}"
        )
    if page["pageSize"] != page_size:
        raise SearchPaginationError(
            f"page pageSize {page['pageSize']} does not match requested {page_size}"
        )
    if not _is_non_negative_int(page["totalElements"]):
        raise SearchPaginationError("page totalElements must be a non-negative integer")
    if not _is_non_negative_int(page["totalPages"]):
        raise SearchPaginationError("page totalPages must be a non-negative integer")
    if not isinstance(page["content"], list) or not all(
        isinstance(record, dict) for record in page["content"]
    ):
        raise SearchPaginationError("page content must be an object array")
    if len(page["content"]) > page_size:
        raise SearchPaginationError("page content exceeds pageSize")
    return page


@dataclass(frozen=True)
class SearchPaginationResult:
    expected_count: int
    required_pages: int
    records: tuple[dict[str, Any], ...]
    page_metadata: tuple[dict[str, Any], ...]
    uuids: frozenset[str]


def validate_search_pages(
    responses: Sequence[Any],
    *,
    page_size: int = DEFAULT_SEARCH_PAGE_SIZE,
    max_safe_results: int = MAX_SAFE_DAILY_RESULTS,
    result_window: int = SEARCH_RESULT_WINDOW,
) -> SearchPaginationResult:
    """Validate count, page metadata, UUID uniqueness, overlap, and completeness."""

    if not isinstance(responses, Sequence) or isinstance(responses, (str, bytes)) or not responses:
        raise SearchPaginationError("at least one search response is required")
    expected_count = parse_search_count(responses[0])
    required_pages = calculate_required_pages(
        expected_count,
        page_size,
        max_safe_results=max_safe_results,
        result_window=result_window,
    )
    expected_response_count = max(1, required_pages)
    if len(responses) != expected_response_count:
        raise SearchPaginationError(
            f"missing page responses: expected {expected_response_count}, got {len(responses)}"
        )

    records: list[dict[str, Any]] = []
    page_metadata: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_number, response in enumerate(responses):
        page = _parse_page(response, page_number, page_size)
        if page["totalElements"] != expected_count:
            raise SearchPaginationError(
                f"page totalElements {page['totalElements']} does not match expected {expected_count}"
            )
        if expected_count and page["totalPages"] != required_pages:
            raise SearchPaginationError(
                f"page totalPages {page['totalPages']} does not match required {required_pages}"
            )
        if not expected_count and page["totalPages"] not in {0, 1}:
            raise SearchPaginationError("zero-result page totalPages must be 0 or 1")
        if page_number * page_size >= result_window:
            raise SearchPaginationError(
                f"page offset reaches search result window {result_window}"
            )
        for record in page["content"]:
            uuid = record.get("id")
            if not isinstance(uuid, str) or not uuid:
                raise SearchPaginationError("every search record must contain a non-empty string id")
            if uuid in seen:
                raise SearchPaginationError(f"duplicate UUID across or within pages: {uuid}")
            seen.add(uuid)
        records.extend(page["content"])
        page_metadata.append(page)

    if len(records) != expected_count:
        raise SearchPaginationError(
            f"count mismatch expected={expected_count} collected={len(records)}"
        )
    return SearchPaginationResult(
        expected_count=expected_count,
        required_pages=required_pages,
        records=tuple(records),
        page_metadata=tuple(page_metadata),
        uuids=frozenset(seen),
    )
