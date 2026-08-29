"""MSC envelope, pagination, UUID, schema and completeness validation."""

from __future__ import annotations

import math
from typing import Any, Sequence

from .config import MAX_SAFE_SEARCH_RESULTS, SEARCH_PAGE_SIZE, SEARCH_RESULT_WINDOW
from .models import DriftDiagnostic, PartitionUnionResult, SearchInterval, SearchPaginationResult, SourceContract


class ValidationError(ValueError):
    code = "MSC_CONTRACT_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def parse_search_count(response: Any) -> int:
    try:
        count = response["agg"][0]["buckets"][0]["docCount"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValidationError("missing search aggregation agg[0].buckets[0].docCount") from exc
    if not _is_non_negative_int(count):
        raise ValidationError("search docCount must be a non-negative integer")
    return count


def calculate_required_pages(
    expected_count: int,
    page_size: int = SEARCH_PAGE_SIZE,
    *,
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
    result_window: int = SEARCH_RESULT_WINDOW,
) -> int:
    if not _is_non_negative_int(expected_count):
        raise ValidationError("expected count must be a non-negative integer")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
        raise ValidationError("page size must be a positive integer")
    if expected_count > max_safe_results:
        raise ValidationError(
            f"expected count {expected_count} exceeds safe search threshold {max_safe_results}",
            "SEARCH_WINDOW_OVERFLOW",
        )
    required = math.ceil(expected_count / page_size)
    if required and (required - 1) * page_size >= result_window:
        raise ValidationError(f"required page offset reaches search result window {result_window}")
    return required


def _parse_page(response: Any, page_number: int, page_size: int) -> dict[str, Any]:
    if not isinstance(response, dict) or not isinstance(response.get("page"), dict):
        raise ValidationError("missing search result envelope page")
    page = response["page"]
    required = ("content", "currentPage", "pageSize", "totalElements", "totalPages")
    missing = [key for key in required if key not in page]
    if missing:
        raise ValidationError(f"missing page metadata: {','.join(missing)}")
    if page["currentPage"] != page_number:
        raise ValidationError(f"page currentPage {page['currentPage']} does not match requested {page_number}")
    if page["pageSize"] != page_size:
        raise ValidationError(f"page pageSize {page['pageSize']} does not match requested {page_size}")
    if not _is_non_negative_int(page["totalElements"]):
        raise ValidationError("page totalElements must be a non-negative integer")
    if not _is_non_negative_int(page["totalPages"]):
        raise ValidationError("page totalPages must be a non-negative integer")
    if not isinstance(page["content"], list) or not all(isinstance(record, dict) for record in page["content"]):
        raise ValidationError("page content must be an object array")
    if len(page["content"]) > page_size:
        raise ValidationError("page content exceeds pageSize")
    return page


def validate_search_pages(
    responses: Sequence[Any],
    *,
    page_size: int = SEARCH_PAGE_SIZE,
    max_safe_results: int = MAX_SAFE_SEARCH_RESULTS,
    result_window: int = SEARCH_RESULT_WINDOW,
) -> SearchPaginationResult:
    if not isinstance(responses, Sequence) or isinstance(responses, (str, bytes)) or not responses:
        raise ValidationError("at least one search response is required")
    expected_count = parse_search_count(responses[0])
    required_pages = calculate_required_pages(expected_count, page_size, max_safe_results=max_safe_results, result_window=result_window)
    if len(responses) != max(1, required_pages):
        raise ValidationError(f"missing page responses: expected {max(1, required_pages)}, got {len(responses)}")
    records: list[dict[str, Any]] = []
    page_metadata: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_number, response in enumerate(responses):
        page = _parse_page(response, page_number, page_size)
        if page["totalElements"] != expected_count:
            raise ValidationError(f"page totalElements {page['totalElements']} does not match expected {expected_count}", "COUNT_MISMATCH")
        if expected_count and page["totalPages"] != required_pages:
            raise ValidationError(f"page totalPages {page['totalPages']} does not match required {required_pages}")
        if not expected_count and page["totalPages"] not in {0, 1}:
            raise ValidationError("zero-result page totalPages must be 0 or 1")
        if page_number * page_size >= result_window:
            raise ValidationError(f"page offset reaches search result window {result_window}", "SEARCH_WINDOW_OVERFLOW")
        for record in page["content"]:
            uuid = record.get("id")
            if not isinstance(uuid, str) or not uuid:
                raise ValidationError("every search record must contain a non-empty string id")
            if uuid in seen:
                raise ValidationError(f"duplicate UUID across or within pages: {uuid}", "UUID_DUPLICATE")
            seen.add(uuid)
        records.extend(page["content"])
        page_metadata.append(page)
    if len(records) != expected_count:
        raise ValidationError(f"count mismatch expected={expected_count} collected={len(records)}", "COUNT_MISMATCH")
    return SearchPaginationResult(expected_count, required_pages, tuple(records), tuple(page_metadata), frozenset(seen))


def union_partition_records(
    leaf_records: Sequence[Sequence[dict[str, Any]]],
    *,
    expected_count: int,
    leaf_intervals: Sequence[SearchInterval] | None = None,
) -> PartitionUnionResult:
    if not _is_non_negative_int(expected_count):
        raise ValidationError("parent expected count must be a non-negative integer")
    if leaf_intervals is not None and len(leaf_intervals) != len(leaf_records):
        raise ValidationError("leaf intervals must match leaf record groups")
    by_uuid: dict[str, dict[str, Any]] = {}
    duplicate_uuids: set[str] = set()
    uuid_leaf_indexes: dict[str, list[int]] = {}
    raw_count = 0
    for leaf_index, records in enumerate(leaf_records):
        leaf_seen: set[str] = set()
        for record in records:
            raw_count += 1
            if not isinstance(record, dict):
                raise ValidationError("every partition record must be an object")
            uuid = record.get("id")
            if not isinstance(uuid, str) or not uuid:
                raise ValidationError("every partition record must contain a non-empty string id")
            if uuid in leaf_seen:
                raise ValidationError(f"duplicate UUID within safe leaf: {uuid}", "UUID_DUPLICATE")
            leaf_seen.add(uuid)
            uuid_leaf_indexes.setdefault(uuid, []).append(leaf_index)
            if uuid in by_uuid:
                if by_uuid[uuid] != record:
                    raise ValidationError(f"same UUID has different content across overlapping leaves: {uuid}", "UUID_CONTENT_CONFLICT")
                duplicate_uuids.add(uuid)
            else:
                by_uuid[uuid] = record
    if leaf_intervals is not None:
        for uuid in duplicate_uuids:
            indexes = uuid_leaf_indexes[uuid]
            for left_index, right_index in zip(indexes, indexes[1:]):
                left = leaf_intervals[left_index]
                right = leaf_intervals[right_index]
                if max(left.from_value, right.from_value) > min(left.to_value, right.to_value):
                    raise ValidationError(f"duplicate UUID across non-overlapping safe leaves: {uuid}", "UUID_DUPLICATE")
    unique_count = len(by_uuid)
    if unique_count != expected_count:
        relation = "deficit" if unique_count < expected_count else "surplus"
        raise ValidationError(f"parent UUID union {relation} expected={expected_count} unique={unique_count}", "COUNT_MISMATCH")
    return PartitionUnionResult(expected_count, raw_count, unique_count, tuple(by_uuid.values()), frozenset(duplicate_uuids), raw_count - unique_count)


def _type_error(field: str, expected: str, value: Any) -> str:
    return f"{field} expected {expected}, got {type(value).__name__}"


def validate_raw_records(contract: SourceContract, records: Sequence[dict[str, Any]]) -> DriftDiagnostic:
    raw_fields = sorted({key for record in records for key in record})
    additive = sorted(set(raw_fields) - set(contract.observed_source_fields))
    errors: list[str] = []
    numeric_fields = set(contract.known_numeric_fields)
    if any(mapping.canonical_key == "bidder_count" for mapping in contract.canonical_mapping):
        numeric_fields.add("soNhaThauThamDu")
    array_fields = {"winningCode", "winningName"}
    mapped_fields = {mapping.source_field for mapping in contract.canonical_mapping}
    for record in records:
        record_id = record.get("id", "<missing>")
        if not isinstance(record.get("id"), str) or not record["id"]:
            errors.append(f"uuid={record_id}: id expected non-empty string")
        if record.get("type") != contract.type:
            errors.append(f"uuid={record_id}: type expected {contract.type}, got {record.get('type')!r}")
        if record.get("tab") != contract.tab:
            errors.append(f"uuid={record_id}: tab expected {contract.tab}, got {record.get('tab')!r}")
        for field in numeric_fields:
            if field in record and record[field] is not None and (
                isinstance(record[field], bool) or not isinstance(record[field], (int, float)) or (isinstance(record[field], float) and not math.isfinite(record[field]))
            ):
                errors.append(f"uuid={record_id}: {_type_error(field, 'JSON number', record[field])}")
        for field in array_fields:
            if field in record and record[field] is not None and (
                not isinstance(record[field], list) or not all(isinstance(item, str) for item in record[field])
            ):
                errors.append(f"uuid={record_id}: {_type_error(field, 'string array', record[field])}")
        for field in contract.date_fields:
            if field in record and record[field] is not None and not isinstance(record[field], str):
                errors.append(f"uuid={record_id}: {_type_error(field, 'date string', record[field])}")
        if "diaDiem" in record and record["diaDiem"] is not None and (
            not isinstance(record["diaDiem"], list) or not all(isinstance(item, dict) for item in record["diaDiem"])
        ):
            errors.append(f"uuid={record_id}: {_type_error('diaDiem', 'object array', record['diaDiem'])}")
        for field in mapped_fields | {"medicines"}:
            if field not in record or record[field] is None:
                continue
            if field in numeric_fields or field in array_fields or field in contract.date_fields or field == "diaDiem":
                continue
            if not isinstance(record[field], str):
                errors.append(f"uuid={record_id}: {_type_error(field, 'string', record[field])}")
    if errors:
        raise ValidationError("; ".join(sorted(set(errors))), "MSC_CONTRACT_ERROR")
    return DriftDiagnostic(tuple(raw_fields), tuple(additive), ())


def validate_parent_completeness(pre_count: int, unique_count: int, post_count: int | None = None) -> None:
    if not _is_non_negative_int(pre_count) or not _is_non_negative_int(unique_count):
        raise ValidationError("parent counts must be non-negative integers", "COUNT_MISMATCH")
    if unique_count != pre_count:
        relation = "deficit" if unique_count < pre_count else "surplus"
        raise ValidationError(f"parent completeness {relation} pre={pre_count} unique={unique_count}", "COUNT_MISMATCH")
    if post_count is not None and not _is_non_negative_int(post_count):
        raise ValidationError("parent counts must be non-negative integers", "COUNT_MISMATCH")
    if post_count is not None and post_count != pre_count:
        raise ValidationError(f"pre/post count changed pre={pre_count} post={post_count}", "UNSTABLE_PARENT")
