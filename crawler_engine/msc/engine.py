"""MSC partition orchestration, completeness gates and sink handoff."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Sequence

from .checkpoint import CheckpointStore
from .client import MSCClient, MSCClientError
from .config import MSCConfig
from .contracts import get_contract
from .models import (
    CanonicalRecord, DriftDiagnostic, IngestionStatus, PartitionContext, PartitionResult, SearchInterval,
)
from .normalize import NormalizationError, normalize_records
from .partitioning import PartitioningError, official_day_interval, plan_partition
from .sink import InMemorySink, Sink
from .validation import (
    ValidationError,
    calculate_required_pages,
    union_partition_records,
    validate_parent_completeness,
    validate_raw_records,
    validate_search_pages,
)

LOGGER = logging.getLogger(__name__)
VIETNAM_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class EngineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def operational_today() -> date:
    return datetime.now(VIETNAM_ZONE).date()


def parse_partition_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EngineError("MSC_CONTRACT_ERROR", "partition date must use YYYY-MM-DD") from exc


class MSCIngestionEngine:
    def __init__(self, client: MSCClient, checkpoint_store: CheckpointStore, sink: Sink | None = None, config: MSCConfig | None = None) -> None:
        self.client = client
        self.config = config or client.config
        self.checkpoint_store = checkpoint_store
        self.sink = sink or InMemorySink()

    def ingest_partition(
        self,
        source_key: str,
        partition_date: str | date,
        *,
        force: bool = False,
        allow_open_day: bool = False,
        max_leaves: int | None = None,
        replace_existing: bool = False,
    ) -> PartitionResult:
        contract = get_contract(source_key)
        day = parse_partition_date(partition_date)
        today = operational_today()
        if day > today:
            raise EngineError("MSC_CONTRACT_ERROR", "future partition dates are not allowed")
        open_day = day == today
        if open_day and not allow_open_day:
            raise EngineError("MSC_CONTRACT_ERROR", "current/open day requires explicit allow_open_day")
        sink_target = getattr(self.sink, "sink_target", "validation-jsonl")
        current = self.checkpoint_store.get(source_key, day.isoformat(), sink_target)
        previous_uuids: set[str] = set()
        if replace_existing:
            if not current or current.status != IngestionStatus.COMPLETED:
                raise EngineError("MSC_CONTRACT_ERROR", "partition replacement requires a completed checkpoint")
            provenance = getattr(self.sink, "provenance", None)
            partition_uuids = getattr(provenance, "partition_uuids", None)
            if not callable(partition_uuids):
                raise EngineError("MSC_CONTRACT_ERROR", "partition replacement requires UUID provenance")
            previous_uuids = partition_uuids(source_key, day.isoformat())
        if current and current.status == IngestionStatus.COMPLETED and not force and not open_day:
            return PartitionResult(source_key, day.isoformat(), IngestionStatus.COMPLETED, skipped=True, sink_target=sink_target)
        self.checkpoint_store.start(source_key, day.isoformat(), force=force, sink_target=sink_target)
        started = time.monotonic()
        request_before = self.client.stats.request_count
        retry_before = self.client.stats.retry_count
        drift = DriftDiagnostic(())
        pre_count: int | None = None
        post_count: int | None = None
        raw_fetched_count = 0
        unique_source_count = 0
        normalized_count = 0
        sink_accepted_count = 0
        sink_attempted_count = 0
        sink_batch_count = 0
        sink_elapsed_seconds = 0.0
        try:
            parent = official_day_interval(day)
            pre_count = self.client.count_interval(contract, parent)
            plan = plan_partition(
                parent,
                lambda interval: self.client.count_interval(contract, interval),
                config=self.config,
                initial_count=pre_count,
            )
            if max_leaves is not None and len(plan.safe_leaves) > max_leaves:
                raise EngineError("SEARCH_WINDOW_OVERFLOW", f"safe leaf count {len(plan.safe_leaves)} exceeds cap {max_leaves}")
            leaf_records: list[tuple[dict, ...]] = []
            for leaf in plan.safe_leaves:
                expected = leaf.expected_count
                if expected is None:
                    raise EngineError("MSC_CONTRACT_ERROR", "safe leaf missing expected count")
                required = max(
                    1,
                    calculate_required_pages(
                        expected,
                        self.config.page_size,
                        max_safe_results=self.config.max_safe_results,
                        result_window=self.config.result_window,
                    ),
                )
                responses = [self.client.fetch_page(contract, leaf, page) for page in range(required)]
                page_result = validate_search_pages(
                    responses,
                    page_size=self.config.page_size,
                    max_safe_results=self.config.max_safe_results,
                    result_window=self.config.result_window,
                )
                leaf_records.append(page_result.records)
            union = union_partition_records(
                leaf_records,
                expected_count=pre_count,
                leaf_intervals=plan.safe_leaves,
            )
            raw_fetched_count = union.raw_record_count
            unique_source_count = union.unique_uuid_count
            drift = validate_raw_records(contract, union.records)
            if drift.additive_fields:
                LOGGER.warning("msc_schema_drift source_key=%s partition_date=%s additive_fields=%s", source_key, day, ",".join(drift.additive_fields))
            post_count = self.client.count_interval(contract, parent)
            validate_parent_completeness(pre_count, union.unique_uuid_count, post_count)
            canonical = normalize_records(contract, union.records, day.isoformat())
            normalized_count = len(canonical)
            if normalized_count != union.unique_uuid_count:
                raise EngineError(
                    "NORMALIZATION_ERROR",
                    f"normalization count {normalized_count} does not match unique source count {union.unique_uuid_count}",
                )
            context = PartitionContext(
                source_key, day.isoformat(), contract, parent, pre_count, post_count,
                union.raw_record_count, union.unique_uuid_count, len(canonical), len(plan.safe_leaves), drift, sink_target,
            )
            if replace_existing:
                current_uuids = {str(record["id"]) for record in canonical}
                stale_uuids = previous_uuids - current_uuids
                replace = getattr(self.sink, "replace_partition", None)
                if not callable(replace):
                    raise EngineError("MSC_CONTRACT_ERROR", "partition replacement requires an audited sink")
                write_result = replace(context, canonical, stale_uuids)
            else:
                write_result = self.sink.write_partition(context, canonical)
            sink_attempted_count = write_result.attempted_count
            sink_accepted_count = write_result.accepted_count
            sink_batch_count = write_result.batch_count
            sink_elapsed_seconds = write_result.elapsed_seconds
            if write_result.accepted_count != len(canonical) or write_result.rejected_count:
                raise EngineError(
                    write_result.error_code or "SINK_INCOMPLETE",
                    f"sink accepted={write_result.accepted_count} rejected={write_result.rejected_count} normalized={len(canonical)}"
                    + (f" errors={'; '.join(write_result.errors)}" if write_result.errors else ""),
                )
            status = IngestionStatus.VALIDATED if open_day else IngestionStatus.COMPLETED
            self.checkpoint_store.finish(
                source_key, day.isoformat(), status,
                sink_target=sink_target,
                parent_pre_count=pre_count, parent_post_count=post_count,
                raw_fetched_count=union.raw_record_count, unique_uuid_count=union.unique_uuid_count,
                normalized_count=len(canonical), sink_accepted_count=write_result.accepted_count,
            )
            LOGGER.info(
                "msc_partition_completed source_key=%s partition_date=%s status=%s pre_count=%s post_count=%s "
                "leaf_count=%s raw_fetched=%s unique_source=%s normalized=%s sink_accepted=%s sink_attempted=%s sink_batches=%s sink_elapsed_seconds=%.3f requests=%s retries=%s elapsed_seconds=%.3f",
                source_key, day, status.value, pre_count, post_count, len(plan.safe_leaves),
                union.raw_record_count, union.unique_uuid_count, len(canonical), write_result.accepted_count,
                write_result.attempted_count, write_result.batch_count, write_result.elapsed_seconds,
                self.client.stats.request_count - request_before, self.client.stats.retry_count - retry_before,
                time.monotonic() - started,
            )
            return PartitionResult(
                source_key, day.isoformat(), status, pre_count, post_count,
                union.raw_record_count, union.unique_uuid_count, len(canonical),
                write_result.accepted_count, len(plan.safe_leaves),
                self.client.stats.request_count - request_before, self.client.stats.retry_count - retry_before,
                time.monotonic() - started, drift, sink_target=sink_target,
                sink_attempted_count=write_result.attempted_count, sink_batch_count=write_result.batch_count,
                sink_elapsed_seconds=write_result.elapsed_seconds,
            )
        except KeyboardInterrupt:
            raise
        except (EngineError, MSCClientError, PartitioningError, ValidationError, NormalizationError, OSError) as exc:
            code = getattr(exc, "code", "SINK_INCOMPLETE" if isinstance(exc, OSError) else "MSC_CONTRACT_ERROR")
            quarantine = isinstance(exc, PartitioningError)
            self.checkpoint_store.fail(
                source_key,
                day.isoformat(),
                code,
                str(exc),
                quarantine=quarantine,
                sink_target=sink_target,
                parent_pre_count=pre_count,
                parent_post_count=post_count,
                raw_fetched_count=raw_fetched_count,
                unique_uuid_count=unique_source_count,
                normalized_count=normalized_count,
                sink_accepted_count=sink_accepted_count,
            )
            LOGGER.error("msc_partition_failed source_key=%s partition_date=%s code=%s error=%s", source_key, day, code, exc)
            return PartitionResult(
                source_key, day.isoformat(), IngestionStatus.QUARANTINED if quarantine else IngestionStatus.FAILED,
                request_count=self.client.stats.request_count - request_before,
                retry_count=self.client.stats.retry_count - retry_before,
                elapsed_seconds=time.monotonic() - started, drift=drift,
                error_code=code, error_message=str(exc), sink_target=sink_target,
                sink_accepted_count=sink_accepted_count, sink_attempted_count=sink_attempted_count,
                sink_batch_count=sink_batch_count, sink_elapsed_seconds=sink_elapsed_seconds,
            )

    def crawl_range(
        self,
        from_date: str | date,
        to_date: str | date,
        source_keys: Sequence[str],
        *,
        force: bool = False,
        allow_open_day: bool = False,
        max_partitions: int | None = None,
    ) -> tuple[PartitionResult, ...]:
        start = parse_partition_date(from_date)
        end = parse_partition_date(to_date)
        if start > end:
            raise EngineError("MSC_CONTRACT_ERROR", "from date cannot be after to date")
        sources = tuple(source_keys)
        if not sources:
            raise EngineError("MSC_CONTRACT_ERROR", "at least one source key is required")
        for source_key in sources:
            get_contract(source_key)
        total = (end - start).days + 1
        requested = total * len(sources)
        if max_partitions is not None and requested > max_partitions:
            raise EngineError("MSC_CONTRACT_ERROR", f"requested partitions {requested} exceed cap {max_partitions}")
        results = []
        for offset in range(total):
            day = start.fromordinal(start.toordinal() + offset)
            for source_key in sources:
                results.append(self.ingest_partition(source_key, day, force=force, allow_open_day=allow_open_day))
        return tuple(results)
