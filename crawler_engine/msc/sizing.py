"""Pure calculations and deterministic planning for empirical Typesense sizing."""

from __future__ import annotations

from datetime import date, timedelta
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contracts import SOURCE_CONTRACTS, get_contract
from .typesense_schema import SEARCH_CONFIGS, canonical_to_typesense_document, schema_for_group

SIZING_REPORT_VERSION = "typesense-sizing-report-v1"
SIZING_SAMPLE_TARGET = 500_000
SIZING_SAMPLE_MINIMUM = 250_000
SIZING_SAMPLE_MAXIMUM = 600_000
FULL_DATASET_DOCUMENTS = 9_801_385
RAM_TARGET_UTILIZATION = 0.70
SIZING_YEARS = (2023, 2024, 2025, 2026)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bytes_per_document(
    total_bytes: int | float,
    document_count: int,
    *,
    baseline_bytes: int | float = 0,
    baseline_documents: int = 0,
) -> float:
    """Return incremental bytes/document after subtracting a 0-document baseline."""

    delta_documents = document_count - baseline_documents
    if delta_documents <= 0:
        raise ValueError("document delta must be positive")
    delta_bytes = float(total_bytes) - float(baseline_bytes)
    if delta_bytes < 0:
        raise ValueError("measured bytes cannot be below baseline")
    return delta_bytes / delta_documents


def subtract_baseline(value: int | float, baseline: int | float) -> float:
    """Subtract process/index baseline without treating baseline as dataset memory."""

    result = float(value) - float(baseline)
    if result < 0:
        raise ValueError("measured value cannot be below baseline")
    return result


def linear_slope(points: Sequence[tuple[float, float]]) -> dict[str, float]:
    """Least-squares line for ``(documents, bytes)`` points."""

    if len(points) < 2:
        raise ValueError("at least two points are required")
    x_mean = sum(point[0] for point in points) / len(points)
    y_mean = sum(point[1] for point in points) / len(points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    if denominator <= 0:
        raise ValueError("document points must not all be equal")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    intercept = y_mean - slope * x_mean
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    total = sum((y - y_mean) ** 2 for _, y in points)
    r_squared = 1.0 if total == 0 and residual == 0 else max(0.0, 1.0 - residual / total)
    return {"bytes_per_document": slope, "intercept_bytes": intercept, "r_squared": r_squared}


def empirical_projection(
    milestones: Sequence[Mapping[str, Any]],
    total_documents: int = FULL_DATASET_DOCUMENTS,
    *,
    metric: str,
) -> dict[str, Any]:
    """Project a metric with largest-sample and all-milestone linear methods."""

    points = [(float(item["documents"]), float(item[metric])) for item in milestones]
    if len(points) < 2 or points[0][0] != 0:
        raise ValueError("milestones must include 0-document baseline and one sample")
    largest = bytes_per_document(points[-1][1], int(points[-1][0]), baseline_bytes=points[0][1])
    baseline_bytes = points[0][1]
    regression = linear_slope([(documents, value - baseline_bytes) for documents, value in points])
    return {
        "metric": metric,
        "total_documents": total_documents,
        "baseline_bytes": baseline_bytes,
        "largest_sample": {
            "bytes_per_document": largest,
            "projected_bytes": largest * total_documents,
        },
        "regression": {
            **regression,
            "projected_bytes": max(0.0, regression["intercept_bytes"] + regression["bytes_per_document"] * total_documents),
        },
    }


def growth_scenarios(
    total_documents: int,
    ram_bytes_per_document: float,
    disk_bytes_per_document: float,
    *,
    growth: Iterable[float] = (0.0, 0.20, 0.50),
) -> list[dict[str, Any]]:
    scenarios = []
    for fraction in growth:
        if fraction < 0:
            raise ValueError("growth fraction cannot be negative")
        documents = round(total_documents * (1 + fraction))
        scenarios.append({
            "growth_fraction": fraction,
            "documents": documents,
            "projected_ram_bytes": round(documents * ram_bytes_per_document),
            "projected_disk_bytes": round(documents * disk_bytes_per_document),
        })
    return scenarios


def capacity_decision(
    projected_ram_bytes: int | float,
    *,
    node_ram_gb: int = 32,
    max_utilization: float = RAM_TARGET_UTILIZATION,
) -> dict[str, Any]:
    if node_ram_gb <= 0 or not 0 < max_utilization < 1:
        raise ValueError("node RAM and utilization threshold must be positive")
    provisioned = node_ram_gb * 1024**3
    limit = provisioned * max_utilization
    approved = float(projected_ram_bytes) <= limit
    return {
        "approved": approved,
        "node_ram_gb": node_ram_gb,
        "projected_ram_bytes": float(projected_ram_bytes),
        "target_max_ram_bytes": limit,
        "projected_utilization": float(projected_ram_bytes) / provisioned,
        "decision": "PASS" if approved else "FAIL",
        "recommendation": "32 GB/node is sufficient" if approved else "use the next available RAM tier above 32 GB/node",
        "swap_counted": False,
    }


def indexed_field_names(logical_group: str) -> tuple[str, ...]:
    if logical_group not in SEARCH_CONFIGS:
        raise ValueError(f"unknown logical group: {logical_group}")
    query_fields = set(SEARCH_CONFIGS[logical_group].query_by)
    return tuple(
        field["name"]
        for field in schema_for_group(logical_group)["fields"]
        if field["name"] in query_fields or field.get("facet") or field.get("sort")
    )


def field_size_contributions(
    records_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Rank serialized contributions of fields that Typesense indexes or searches."""

    totals: dict[tuple[str, str], int] = {}
    counts: dict[str, int] = {}
    for group, records in records_by_group.items():
        names = set(indexed_field_names(group))
        counts[group] = len(records)
        for record in records:
            document = canonical_to_typesense_document(record, group)
            for name in names:
                if name not in document or document[name] is None:
                    continue
                encoded = canonical_json({name: document[name]}).encode("utf-8")
                totals[(group, name)] = totals.get((group, name), 0) + len(encoded)
    grand_total = sum(totals.values())
    result = []
    for (group, name), total in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        result.append({
            "logical_group": group,
            "field": name,
            "serialized_index_input_bytes": total,
            "percentage": (total / grand_total * 100) if grand_total else 0.0,
            "average_bytes_per_group_document": total / counts[group] if counts[group] else 0.0,
        })
    return result


def deterministic_sample_dates() -> dict[str, tuple[str, ...]]:
    """Fixed anchors followed by a deterministic daily fallback for sparse sources."""

    result: dict[str, tuple[str, ...]] = {}
    for year in SIZING_YEARS:
        start_month = 2 if year == 2023 else 1
        end_month = 8 if year == 2026 else 12
        dates = []
        for month in range(start_month, end_month + 1):
            dates.append(f"{year:04d}-{month:02d}-15")
        for month in range(start_month, end_month + 1):
            for day in (1, 4, 8, 12, 20, 22, 26, 28):
                try:
                    date(year, month, day)
                except ValueError:
                    continue
                dates.append(f"{year:04d}-{month:02d}-{day:02d}")
        if year == 2026:
            dates.append("2026-08-29")
        start = date(year, start_month, 1)
        end = date(year, end_month, 29 if year == 2026 else 31)
        current = start
        seen = set(dates)
        while current <= end:
            rendered = current.isoformat()
            if rendered not in seen:
                dates.append(rendered)
                seen.add(rendered)
            current += timedelta(days=1)
        result[str(year)] = tuple(dates)
    return result


def deterministic_sample_plan(
    *,
    source_quotas: Mapping[str, int],
    seed: int = 20230830,
    target_documents: int = SIZING_SAMPLE_TARGET,
    maximum_documents: int = SIZING_SAMPLE_MAXIMUM,
) -> dict[str, Any]:
    ordered = tuple(key for key in SOURCE_CONTRACTS if key in source_quotas)
    unknown = set(source_quotas) - set(SOURCE_CONTRACTS)
    if unknown:
        raise ValueError(f"unknown source key(s): {', '.join(sorted(unknown))}")
    if not ordered or any(int(source_quotas[key]) <= 0 for key in ordered):
        raise ValueError("source quotas must be positive")
    planned = sum(int(source_quotas[key]) for key in ordered)
    if target_documents <= 0 or target_documents > maximum_documents:
        raise ValueError("target documents must be positive and within maximum document guard")
    if planned > maximum_documents:
        raise ValueError("sample plan exceeds maximum document guard")
    return {
        "seed": seed,
        "target_documents": target_documents,
        "maximum_documents": maximum_documents,
        "source_order": list(ordered),
        "source_quotas": {key: int(source_quotas[key]) for key in ordered},
        "date_selection": {
            "method": "monthly day-15 anchors, then deterministic day 01/04/08/12/20/22/26/28 extensions and daily sparse-source fallback, registry/source order",
            "dates_by_year": deterministic_sample_dates(),
        },
    }


def enforce_sample_maximum(document_count: int, maximum_documents: int = SIZING_SAMPLE_MAXIMUM) -> None:
    if document_count < 0 or document_count > maximum_documents:
        raise ValueError(f"sample document count {document_count} exceeds maximum {maximum_documents}")


def serialize_report(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_report(path: str | Path, report: Mapping[str, Any]) -> None:
    Path(path).write_text(serialize_report(report), encoding="utf-8")
