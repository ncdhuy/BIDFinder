"""Pure validation for complete public MSC search partitions."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Callable, Sequence


SEARCH_RESULT_WINDOW = 10_000
MAX_SAFE_SEARCH_RESULTS = 9_500
DEFAULT_SEARCH_PAGE_SIZE = 1_000
DEFAULT_PARTITION_OVERLAP = timedelta(seconds=1)
MIN_PARTITION_GRANULARITY = timedelta(milliseconds=1)


_ISO_RANGE_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"


class SearchPaginationError(ValueError):
    """A public search response cannot prove a complete partition."""


class SearchPartitionError(SearchPaginationError):
    """A time partition cannot prove complete, safe public-search retrieval."""


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
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
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
    if expected_count > max_safe_results:
        raise SearchPaginationError(
            f"expected count {expected_count} exceeds safe search threshold {max_safe_results}"
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
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
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


@dataclass(frozen=True)
class SearchInterval:
    """Inclusive conceptual MSC range represented by exact UTC filter bounds."""

    from_value: str
    to_value: str
    depth: int = 0
    expected_count: int | None = None


@dataclass(frozen=True)
class PartitionSplitDiagnostic:
    parent: SearchInterval
    left: SearchInterval
    right: SearchInterval
    parent_count: int
    left_count: int
    right_count: int
    child_count_sum: int
    overlap_surplus: int


@dataclass(frozen=True)
class PartitionPlan:
    parent_interval: SearchInterval
    safe_leaves: tuple[SearchInterval, ...]
    diagnostics: tuple[PartitionSplitDiagnostic, ...]


@dataclass(frozen=True)
class PartitionUnionResult:
    expected_count: int
    raw_record_count: int
    unique_uuid_count: int
    records: tuple[dict[str, Any], ...]
    duplicate_uuids: frozenset[str]
    duplicate_uuid_occurrences: int


def _parse_interval_bound(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(_ISO_RANGE_RE, value):
        raise SearchPartitionError(
            "search interval bounds must use YYYY-MM-DDTHH:MM:SS.mmmZ"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SearchPartitionError("search interval contains invalid UTC timestamp") from exc


def _format_interval_bound(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def _validate_interval(interval: SearchInterval) -> tuple[datetime, datetime]:
    if not isinstance(interval, SearchInterval):
        raise SearchPartitionError("search interval must be a SearchInterval")
    if not isinstance(interval.depth, int) or isinstance(interval.depth, bool) or interval.depth < 0:
        raise SearchPartitionError("search interval depth must be a non-negative integer")
    if interval.expected_count is not None and not _is_non_negative_int(interval.expected_count):
        raise SearchPartitionError("search interval expected count must be a non-negative integer")
    start = _parse_interval_bound(interval.from_value)
    end = _parse_interval_bound(interval.to_value)
    if start >= end:
        raise SearchPartitionError("search interval must have from < to")
    return start, end


def _count_result(value: Any) -> int:
    if not _is_non_negative_int(value):
        raise SearchPartitionError("partition count must be a non-negative integer")
    return value


def split_search_interval(
    interval: SearchInterval,
    *,
    overlap: timedelta = DEFAULT_PARTITION_OVERLAP,
    minimum_span: timedelta = MIN_PARTITION_GRANULARITY,
) -> tuple[SearchInterval, SearchInterval]:
    """Split interval at midpoint with deterministic overlap, rejecting no-progress splits."""

    start, end = _validate_interval(interval)
    if not isinstance(overlap, timedelta) or overlap <= timedelta(0):
        raise SearchPartitionError("partition overlap must be positive")
    if not isinstance(minimum_span, timedelta) or minimum_span <= timedelta(0):
        raise SearchPartitionError("minimum partition span must be positive")
    span = end - start
    if span <= minimum_span:
        raise SearchPartitionError(
            f"interval cannot be split below minimum time span {minimum_span}"
        )
    midpoint = start + span / 2
    if midpoint <= start or midpoint >= end or midpoint + overlap >= end:
        raise SearchPartitionError(
            "interval cannot be split without zero-progress child after overlap"
        )
    left = SearchInterval(
        _format_interval_bound(start),
        _format_interval_bound(midpoint + overlap),
        depth=interval.depth + 1,
    )
    right = SearchInterval(
        _format_interval_bound(midpoint),
        _format_interval_bound(end),
        depth=interval.depth + 1,
    )
    _validate_interval(left)
    _validate_interval(right)
    return left, right


def plan_partition(
    parent: SearchInterval,
    count_interval: Callable[[SearchInterval], int],
    *,
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
    overlap: timedelta = DEFAULT_PARTITION_OVERLAP,
    minimum_span: timedelta = MIN_PARTITION_GRANULARITY,
    max_depth: int = 16,
) -> PartitionPlan:
    """Count and recursively plan safe, deterministically ordered time leaves."""

    _validate_interval(parent)
    if not callable(count_interval):
        raise SearchPartitionError("count_interval must be callable")
    if (
        not isinstance(max_safe_results, int)
        or isinstance(max_safe_results, bool)
        or max_safe_results <= 0
        or max_safe_results > SEARCH_RESULT_WINDOW
    ):
        raise SearchPartitionError("safe result threshold must be within the result window")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0:
        raise SearchPartitionError("maximum partition depth must be a non-negative integer")

    diagnostics: list[PartitionSplitDiagnostic] = []

    def recurse(interval: SearchInterval, count: int | None = None) -> tuple[SearchInterval, ...]:
        count = _count_result(count_interval(interval) if count is None else count)
        counted = SearchInterval(
            interval.from_value,
            interval.to_value,
            depth=interval.depth,
            expected_count=count,
        )
        if count <= max_safe_results:
            return (counted,)
        if interval.depth >= max_depth:
            raise SearchPartitionError(
                f"unsafe interval exceeds safe search threshold at maximum depth {max_depth}: "
                f"{interval.from_value}..{interval.to_value} count={count}"
            )
        left, right = split_search_interval(
            interval, overlap=overlap, minimum_span=minimum_span
        )
        left_count = _count_result(count_interval(left))
        right_count = _count_result(count_interval(right))
        if left_count + right_count < count:
            raise SearchPartitionError(
                f"child count deficit parent={count} left={left_count} right={right_count}"
            )
        left = SearchInterval(left.from_value, left.to_value, left.depth, left_count)
        right = SearchInterval(right.from_value, right.to_value, right.depth, right_count)
        diagnostics.append(
            PartitionSplitDiagnostic(
                parent=counted,
                left=left,
                right=right,
                parent_count=count,
                left_count=left_count,
                right_count=right_count,
                child_count_sum=left_count + right_count,
                overlap_surplus=left_count + right_count - count,
            )
        )
        return recurse(left, left_count) + recurse(right, right_count)

    root_count = _count_result(count_interval(parent))
    root = SearchInterval(parent.from_value, parent.to_value, parent.depth, root_count)
    if root_count <= max_safe_results:
        return PartitionPlan(root, (root,), ())
    if root.depth >= max_depth:
        raise SearchPartitionError(
            f"unsafe interval exceeds safe search threshold at maximum depth {max_depth}: "
            f"{root.from_value}..{root.to_value} count={root_count}"
        )
    leaves = recurse(root, root_count)
    return PartitionPlan(root, leaves, tuple(diagnostics))


def union_partition_records(
    leaf_records: Sequence[Sequence[dict[str, Any]]],
    *,
    expected_count: int,
    leaf_intervals: Sequence[SearchInterval] | None = None,
) -> PartitionUnionResult:
    """Union leaf records by UUID; allow only identical cross-leaf overlap."""

    if not _is_non_negative_int(expected_count):
        raise SearchPartitionError("parent expected count must be a non-negative integer")
    if leaf_intervals is not None:
        if len(leaf_intervals) != len(leaf_records):
            raise SearchPartitionError("leaf intervals must match leaf record groups")
        for interval in leaf_intervals:
            _validate_interval(interval)
    by_uuid: dict[str, dict[str, Any]] = {}
    duplicate_uuids: set[str] = set()
    uuid_leaf_indexes: dict[str, list[int]] = {}
    raw_count = 0
    for leaf_index, records in enumerate(leaf_records):
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise SearchPartitionError(f"leaf {leaf_index} records must be a sequence")
        leaf_seen: set[str] = set()
        for record in records:
            raw_count += 1
            if not isinstance(record, dict):
                raise SearchPartitionError("every partition record must be an object")
            uuid = record.get("id")
            if not isinstance(uuid, str) or not uuid:
                raise SearchPartitionError("every partition record must contain a non-empty string id")
            if uuid in leaf_seen:
                raise SearchPartitionError(f"duplicate UUID within safe leaf: {uuid}")
            leaf_seen.add(uuid)
            uuid_leaf_indexes.setdefault(uuid, []).append(leaf_index)
            if uuid in by_uuid:
                if by_uuid[uuid] != record:
                    raise SearchPartitionError(
                        f"same UUID has different content across overlapping leaves: {uuid}"
                    )
                duplicate_uuids.add(uuid)
            else:
                by_uuid[uuid] = record

    if leaf_intervals is not None:
        for uuid in duplicate_uuids:
            indexes = uuid_leaf_indexes[uuid]
            for left_index, right_index in zip(indexes, indexes[1:]):
                left_start, left_end = _validate_interval(leaf_intervals[left_index])
                right_start, right_end = _validate_interval(leaf_intervals[right_index])
                if max(left_start, right_start) > min(left_end, right_end):
                    raise SearchPartitionError(
                        f"duplicate UUID across non-overlapping safe leaves: {uuid}"
                    )

    unique_count = len(by_uuid)
    if unique_count < expected_count:
        raise SearchPartitionError(
            f"parent UUID union deficit expected={expected_count} unique={unique_count}"
        )
    if unique_count > expected_count:
        raise SearchPartitionError(
            f"parent UUID union surplus expected={expected_count} unique={unique_count}"
        )
    return PartitionUnionResult(
        expected_count=expected_count,
        raw_record_count=raw_count,
        unique_uuid_count=unique_count,
        records=tuple(by_uuid.values()),
        duplicate_uuids=frozenset(duplicate_uuids),
        duplicate_uuid_occurrences=raw_count - unique_count,
    )


def validate_partition_completeness(
    pre_count: int,
    unique_union_count: int,
    *,
    post_count: int | None = None,
) -> None:
    """Require pre-count, optional post-count, and UUID union count to agree."""

    if not _is_non_negative_int(pre_count):
        raise SearchPartitionError("pre-count must be a non-negative integer")
    if not _is_non_negative_int(unique_union_count):
        raise SearchPartitionError("unique UUID count must be a non-negative integer")
    if post_count is not None and not _is_non_negative_int(post_count):
        raise SearchPartitionError("post-count must be a non-negative integer")
    if unique_union_count != pre_count:
        relation = "deficit" if unique_union_count < pre_count else "surplus"
        raise SearchPartitionError(
            f"parent completeness {relation} pre={pre_count} unique={unique_union_count}"
        )
    if post_count is not None and post_count != pre_count:
        raise SearchPartitionError(
            f"pre/post count changed pre={pre_count} post={post_count}"
        )
