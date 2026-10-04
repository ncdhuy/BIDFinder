"""Deterministic adaptive time partitioning proven in Phase 1C."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .config import MSCConfig
from .models import PartitionPlan, PartitionSplitDiagnostic, SearchInterval

_ISO_RANGE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class PartitioningError(ValueError):
    code = "SEARCH_WINDOW_OVERFLOW"


def parse_interval_bound(value: str) -> datetime:
    if not isinstance(value, str) or not _ISO_RANGE_RE.fullmatch(value):
        raise PartitioningError("search interval bounds must use YYYY-MM-DDTHH:MM:SS.mmmZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PartitioningError("search interval contains invalid UTC timestamp") from exc


def format_interval_bound(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def official_day_interval(partition_date: date | str) -> SearchInterval:
    if isinstance(partition_date, str):
        try:
            partition_date = date.fromisoformat(partition_date)
        except ValueError as exc:
            raise PartitioningError("partition date must use YYYY-MM-DD") from exc
    if not isinstance(partition_date, date):
        raise PartitioningError("partition date must be a date")
    start = datetime.combine(partition_date, datetime.min.time(), timezone.utc)
    end = datetime.combine(partition_date, datetime.max.time(), timezone.utc).replace(microsecond=59_000)
    return SearchInterval(format_interval_bound(start), format_interval_bound(end))


def _validate_interval(interval: SearchInterval) -> tuple[datetime, datetime]:
    start = parse_interval_bound(interval.from_value)
    end = parse_interval_bound(interval.to_value)
    if not isinstance(interval.depth, int) or isinstance(interval.depth, bool) or interval.depth < 0:
        raise PartitioningError("search interval depth must be a non-negative integer")
    if start >= end:
        raise PartitioningError("search interval must have from < to")
    return start, end


def split_search_interval(
    interval: SearchInterval,
    *,
    overlap: timedelta = timedelta(seconds=1),
    minimum_span: timedelta = timedelta(milliseconds=1),
) -> tuple[SearchInterval, SearchInterval]:
    start, end = _validate_interval(interval)
    if overlap <= timedelta(0):
        raise PartitioningError("partition overlap must be positive")
    if minimum_span <= timedelta(0):
        raise PartitioningError("minimum partition span must be positive")
    span = end - start
    if span <= minimum_span:
        raise PartitioningError(f"interval cannot be split below minimum time span {minimum_span}")
    midpoint = start + span / 2
    if midpoint <= start or midpoint >= end or midpoint + overlap >= end:
        raise PartitioningError("interval cannot be split without zero-progress child after overlap")
    left = SearchInterval(format_interval_bound(start), format_interval_bound(midpoint + overlap), interval.depth + 1)
    right = SearchInterval(format_interval_bound(midpoint), format_interval_bound(end), interval.depth + 1)
    _validate_interval(left)
    _validate_interval(right)
    return left, right


def plan_partition(
    parent: SearchInterval,
    count_interval: Callable[[SearchInterval], int],
    *,
    config: MSCConfig | None = None,
    initial_count: int | None = None,
) -> PartitionPlan:
    config = config or MSCConfig()
    _validate_interval(parent)
    if not callable(count_interval):
        raise PartitioningError("count_interval must be callable")
    diagnostics: list[PartitionSplitDiagnostic] = []

    def checked_count(value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PartitioningError("partition count must be a non-negative integer")
        return value

    def recurse(interval: SearchInterval, count: int | None = None) -> tuple[SearchInterval, ...]:
        count = checked_count(count_interval(interval) if count is None else count)
        counted = interval.with_count(count)
        if count <= config.max_safe_results:
            return (counted,)
        if interval.depth >= config.max_partition_depth:
            raise PartitioningError(
                f"unsafe interval exceeds safe search threshold at maximum depth {config.max_partition_depth}: "
                f"{interval.from_value}..{interval.to_value} count={count}"
            )
        left, right = split_search_interval(
            interval,
            overlap=timedelta(seconds=config.partition_overlap_seconds),
            minimum_span=timedelta(milliseconds=config.minimum_partition_span_milliseconds),
        )
        left_count = checked_count(count_interval(left))
        right_count = checked_count(count_interval(right))
        if left_count + right_count < count:
            raise PartitioningError(f"child count deficit parent={count} left={left_count} right={right_count}")
        left = left.with_count(left_count)
        right = right.with_count(right_count)
        diagnostics.append(PartitionSplitDiagnostic(
            counted, left, right, count, left_count, right_count,
            left_count + right_count, left_count + right_count - count,
        ))
        return recurse(left, left_count) + recurse(right, right_count)

    root_count = checked_count(count_interval(parent) if initial_count is None else initial_count)
    root = parent.with_count(root_count)
    if root_count <= config.max_safe_results:
        return PartitionPlan(root, (root,), ())
    if root.depth >= config.max_partition_depth:
        raise PartitioningError(
            f"unsafe interval exceeds safe search threshold at maximum depth {config.max_partition_depth}: "
            f"{root.from_value}..{root.to_value} count={root_count}"
        )
    return PartitionPlan(root, recurse(root, root_count), tuple(diagnostics))
