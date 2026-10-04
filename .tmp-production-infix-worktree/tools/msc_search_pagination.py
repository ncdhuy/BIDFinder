"""Phase 1 compatibility exports backed by production MSC logic.

The research tests and probe keep their original imports while the canonical
implementation now lives under ``crawler_engine.msc``.
"""

from __future__ import annotations

from datetime import timedelta

from crawler_engine.msc.config import (
    MAX_SAFE_SEARCH_RESULTS,
    SEARCH_PAGE_SIZE as DEFAULT_SEARCH_PAGE_SIZE,
    SEARCH_RESULT_WINDOW,
)
from crawler_engine.msc.models import (
    PartitionPlan,
    PartitionSplitDiagnostic,
    PartitionUnionResult,
    SearchInterval,
    SearchPaginationResult,
)
from crawler_engine.msc.partitioning import (
    PartitioningError,
    plan_partition as _plan_partition,
    split_search_interval as _split_search_interval,
)
from crawler_engine.msc.validation import (
    ValidationError,
    calculate_required_pages as _calculate_required_pages,
    parse_search_count as _parse_search_count,
    union_partition_records as _union_partition_records,
    validate_search_pages as _validate_search_pages,
)


class SearchPaginationError(ValidationError):
    pass


class SearchPartitionError(PartitioningError):
    pass


DEFAULT_PARTITION_OVERLAP = timedelta(seconds=1)
MIN_PARTITION_GRANULARITY = timedelta(milliseconds=1)


def plan_partition(
    parent: SearchInterval,
    count_interval,
    *,
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
    overlap: timedelta = DEFAULT_PARTITION_OVERLAP,
    minimum_span: timedelta = MIN_PARTITION_GRANULARITY,
    max_depth: int = 16,
) -> PartitionPlan:
    from crawler_engine.msc.config import MSCConfig

    config = MSCConfig(
        max_safe_results=max_safe_results,
        max_partition_depth=max_depth,
        partition_overlap_seconds=overlap.total_seconds(),
        minimum_partition_span_milliseconds=max(1, int(minimum_span.total_seconds() * 1000)),
    )
    try:
        return _plan_partition(parent, count_interval, config=config)
    except PartitioningError as exc:
        raise SearchPartitionError(str(exc)) from exc


def split_search_interval(*args, **kwargs):
    try:
        return _split_search_interval(*args, **kwargs)
    except PartitioningError as exc:
        raise SearchPartitionError(str(exc)) from exc


def calculate_required_pages(*args, **kwargs):
    try:
        return _calculate_required_pages(*args, **kwargs)
    except ValidationError as exc:
        raise SearchPaginationError(str(exc), exc.code) from exc


def parse_search_count(*args, **kwargs):
    try:
        return _parse_search_count(*args, **kwargs)
    except ValidationError as exc:
        raise SearchPaginationError(str(exc), exc.code) from exc


def validate_search_pages(*args, **kwargs):
    try:
        return _validate_search_pages(*args, **kwargs)
    except ValidationError as exc:
        raise SearchPaginationError(str(exc), exc.code) from exc


def union_partition_records(*args, **kwargs):
    try:
        return _union_partition_records(*args, **kwargs)
    except ValidationError as exc:
        raise SearchPartitionError(str(exc)) from exc


def validate_partition_completeness(
    pre_count: int, unique_union_count: int, *, post_count: int | None = None
) -> None:
    from crawler_engine.msc.validation import validate_parent_completeness

    try:
        validate_parent_completeness(pre_count, unique_union_count, post_count)
    except ValidationError as exc:
        raise SearchPartitionError(str(exc)) from exc


__all__ = [
    "DEFAULT_PARTITION_OVERLAP", "DEFAULT_SEARCH_PAGE_SIZE", "MAX_SAFE_SEARCH_RESULTS",
    "MIN_PARTITION_GRANULARITY", "PartitionPlan", "PartitionSplitDiagnostic", "PartitionUnionResult",
    "SEARCH_RESULT_WINDOW", "SearchInterval", "SearchPaginationError", "SearchPaginationResult",
    "SearchPartitionError", "calculate_required_pages", "parse_search_count", "plan_partition",
    "split_search_interval", "union_partition_records", "validate_partition_completeness", "validate_search_pages",
]
