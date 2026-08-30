"""Small typed value objects shared by MSC ingestion components."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, TypeAlias

CanonicalRecord: TypeAlias = dict[str, Any]
RawRecord: TypeAlias = dict[str, Any]


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class FilterSpec:
    field_name: str
    search_type: str
    field_values: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fieldName": self.field_name,
            "searchType": self.search_type,
            "fieldValues": list(self.field_values),
        }


@dataclass(frozen=True)
class FieldMapping:
    canonical_key: str
    source_field: str
    optional: bool = True


@dataclass(frozen=True)
class SourceContract:
    key: str
    source_tab_label: str
    data_group: str
    source_tab: str
    type: str
    tab: str
    match_fields: tuple[str, ...]
    fixed_filters: tuple[FilterSpec, ...]
    special_filters: tuple[str, ...]
    observed_source_fields: tuple[str, ...]
    known_numeric_fields: tuple[str, ...]
    date_fields: tuple[str, ...]
    canonical_mapping: tuple[FieldMapping, ...]
    fixture_slug: str
    request_index: str = "es-smart-pricing"
    date_filter: str = "ngay_dang_tai_kqlcnt"
    contract_version: str = "msc-contract-v1"

    @property
    def canonical_keys(self) -> frozenset[str]:
        return frozenset(item.canonical_key for item in self.canonical_mapping)


@dataclass(frozen=True)
class SearchInterval:
    from_value: str
    to_value: str
    depth: int = 0
    expected_count: int | None = None

    def with_count(self, count: int) -> "SearchInterval":
        return SearchInterval(self.from_value, self.to_value, self.depth, count)


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
    records: tuple[RawRecord, ...]
    duplicate_uuids: frozenset[str]
    duplicate_uuid_occurrences: int


@dataclass(frozen=True)
class SearchPaginationResult:
    expected_count: int
    required_pages: int
    records: tuple[RawRecord, ...]
    page_metadata: tuple[dict[str, Any], ...]
    uuids: frozenset[str]


@dataclass(frozen=True)
class DriftDiagnostic:
    raw_fields: tuple[str, ...]
    additive_fields: tuple[str, ...] = ()
    type_errors: tuple[str, ...] = ()

    @property
    def has_breaking_change(self) -> bool:
        return bool(self.type_errors)


@dataclass(frozen=True)
class SinkWriteResult:
    attempted_count: int
    accepted_count: int
    rejected_count: int
    errors: tuple[str, ...] = ()
    error_code: str | None = None
    batch_count: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class PartitionContext:
    source_key: str
    partition_date: str
    contract: SourceContract
    parent_interval: SearchInterval
    parent_pre_count: int
    parent_post_count: int
    raw_fetched_count: int
    unique_source_count: int
    normalized_count: int
    leaf_count: int
    drift: DriftDiagnostic = field(default_factory=lambda: DriftDiagnostic(()))
    sink_target: str = "validation-jsonl"


@dataclass(frozen=True)
class PartitionResult:
    source_key: str
    partition_date: str
    status: IngestionStatus
    parent_pre_count: int | None = None
    parent_post_count: int | None = None
    raw_fetched_count: int = 0
    unique_source_count: int = 0
    normalized_count: int = 0
    sink_accepted_count: int = 0
    leaf_count: int = 0
    request_count: int = 0
    retry_count: int = 0
    elapsed_seconds: float = 0.0
    drift: DriftDiagnostic = field(default_factory=lambda: DriftDiagnostic(()))
    error_code: str | None = None
    error_message: str | None = None
    skipped: bool = False
    sink_target: str = "validation-jsonl"
    sink_attempted_count: int = 0
    sink_batch_count: int = 0
    sink_elapsed_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "partition_date": self.partition_date,
            "status": self.status.value,
            "parent_pre_count": self.parent_pre_count,
            "parent_post_count": self.parent_post_count,
            "raw_fetched_count": self.raw_fetched_count,
            "unique_source_count": self.unique_source_count,
            "normalized_count": self.normalized_count,
            "sink_accepted_count": self.sink_accepted_count,
            "leaf_count": self.leaf_count,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "additive_schema_fields": list(self.drift.additive_fields),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "skipped": self.skipped,
            "sink_target": self.sink_target,
            "sink_attempted_count": self.sink_attempted_count,
            "sink_batch_count": self.sink_batch_count,
            "sink_elapsed_seconds": round(self.sink_elapsed_seconds, 3),
        }


def copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep sink-facing records plain and detached from response objects."""

    return dict(value)
