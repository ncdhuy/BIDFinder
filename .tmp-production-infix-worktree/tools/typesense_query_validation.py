"""Deterministic Phase 4B Typesense contract corpus and live runner.

The runner records aggregate evidence only. It never writes raw query values,
documents, credentials, or snapshots to the repository.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_contract import (  # noqa: E402
    IDENTIFIER_FIELDS,
    PUBLIC_GROUPS,
    SAMPLE_VALUES,
    get_group_contract,
)
from typesense_shadow import (  # noqa: E402
    AutocompleteQuery,
    TypesenseSearchRepository,
    TypesenseShadowConfig,
    build_canonical_query,
)


def _sample(group: str, field: str) -> Any:
    value = SAMPLE_VALUES.get(group, {}).get(field)
    return value if value not in (None, "") else "sample"


def _filter_sample(group: str, field: dict[str, Any]) -> Any:
    name = field["name"]
    contract = get_group_contract(group)
    if name == "data_group":
        return contract["schema_group"]
    if name == "source_tab":
        return {"goods": "HANG_HOA", "medicines": "THUOC_TAN_DUOC", "traditional": "DUOC_LIEU"}[group]
    if name == "source_tab_label":
        return contract["source_types"][0]["label"]
    if name == "partition_date":
        return "2026-09-01"
    value = _sample(group, name)
    if value == "sample" and field["type"] in {"float", "int32"}:
        return 0
    return value


def _filter_value_matches(value: Any, expected: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and isinstance(expected, str):
        return value.casefold() == expected.casefold()
    return value == expected


def build_validation_corpus() -> list[dict[str, Any]]:
    """Build 150-250 stable query specifications across all contract classes."""

    corpus: list[dict[str, Any]] = []
    for group in PUBLIC_GROUPS:
        contract = get_group_contract(group)
        searchable = contract["full_text"]["fields"]
        filterable = [field for field in contract["fields"] if field["filterable"]]
        sortable = contract["sort_fields"]
        autocomplete = contract["autocomplete_fields"]
        source_types = [item["key"] for item in contract["source_types"]]
        for field in searchable:
            corpus.append({"group": group, "kind": "text", "field": field, "value": _sample(group, field)})
        for field in filterable:
            value = _filter_sample(group, field)
            corpus.append({"group": group, "kind": "filter_eq", "field": field["name"], "value": value})
            if field["type"] == "string" and field.get("facetable"):
                corpus.append({"group": group, "kind": "filter_in", "field": field["name"], "value": [value, value]})
        for field in filterable:
            if field["type"] in {"float", "int32"}:
                value = _sample(group, field["name"])
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    value = 0
                corpus.append({"group": group, "kind": "range", "field": field["name"], "value": {"min": 0, "max": value}})
        corpus.append({"group": group, "kind": "date_range", "value": {"from": "2023-01-01", "to": "2026-12-31"}})
        for field in sortable:
            for order in ("asc", "desc"):
                corpus.append({"group": group, "kind": "sort", "field": field, "order": order})
        for page in (1, 2, 3, 10):
            corpus.append({"group": group, "kind": "pagination", "page": page, "limit": 10})
        corpus.append({"group": group, "kind": "group_all"})
        corpus.append({"group": group, "kind": "subtypes_all", "source_types": source_types})
        for source_type in source_types:
            corpus.append({"group": group, "kind": "subtype", "source_types": [source_type]})
        for field in IDENTIFIER_FIELDS[group]:
            corpus.append({"group": group, "kind": "exact", "field": field, "value": _sample(group, field)})
        for field in autocomplete:
            value = str(_sample(group, field))
            corpus.append({"group": group, "kind": "autocomplete", "field": field, "value": value[: max(1, min(4, len(value)))]})
        if len(searchable) >= 2 and filterable:
            corpus.extend([
                {"group": group, "kind": "combined", "field": searchable[0], "value": _sample(group, searchable[0]), "filter_field": filterable[0]["name"], "filter_value": _filter_sample(group, filterable[0])},
                {"group": group, "kind": "combined_page", "page": 2, "limit": 5, "field": searchable[1], "value": _sample(group, searchable[1]), "filter_field": filterable[0]["name"], "filter_value": _filter_sample(group, filterable[0])},
            ])
    return corpus


def _query_from_spec(spec: dict[str, Any]):
    group = spec["group"]
    kind = spec["kind"]
    common = {"limit": int(spec.get("limit", 10)), "page": int(spec.get("page", 1)), "source_types": spec.get("source_types", [])}
    if kind == "text":
        return build_canonical_query(group, text=str(spec["value"]), search_fields=[spec["field"]], **common)
    if kind == "filter_eq":
        return build_canonical_query(group, structured_filters={spec["field"]: spec["value"]}, **common)
    if kind == "filter_in":
        return build_canonical_query(group, structured_filters={spec["field"]: {"in": spec["value"]}}, **common)
    if kind == "range":
        return build_canonical_query(group, ranges={spec["field"]: spec["value"]}, **common)
    if kind == "date_range":
        return build_canonical_query(group, date_ranges={"partition_date": spec["value"]}, **common)
    if kind == "sort":
        return build_canonical_query(group, sort=[{"column": spec["field"], "order": spec["order"]}], **common)
    if kind in {"group_all", "subtypes_all", "subtype", "pagination"}:
        return build_canonical_query(group, **common)
    if kind == "exact":
        return build_canonical_query(group, exact_identifiers={spec["field"]: spec["value"]}, query_mode="exact", **common)
    if kind in {"combined", "combined_page"}:
        return build_canonical_query(group, text=str(spec["value"]), search_fields=[spec["field"]], structured_filters={spec["filter_field"]: spec["filter_value"]}, **common)
    raise ValueError(f"unsupported corpus kind: {kind}")


def corpus_summary() -> dict[str, Any]:
    corpus = build_validation_corpus()
    by_group = defaultdict(int)
    by_kind = defaultdict(int)
    by_operator = defaultdict(int)
    for spec in corpus:
        by_group[spec["group"]] += 1
        by_kind[spec["kind"]] += 1
        if spec["kind"] == "filter_eq":
            by_operator["eq"] += 1
        elif spec["kind"] == "filter_in":
            by_operator["in"] += 1
        elif spec["kind"] == "range":
            by_operator["min"] += 1
            by_operator["max"] += 1
        elif spec["kind"] == "date_range":
            by_operator["from"] += 1
            by_operator["to"] += 1
        elif spec["kind"] == "sort":
            by_operator[spec["order"]] += 1
        elif spec["kind"] == "exact":
            by_operator["exact_zero_typo"] += 1
        elif spec["kind"] == "autocomplete":
            by_operator["autocomplete_prefix"] += 1
    return {
        "corpus_size": len(corpus),
        "by_group": dict(by_group),
        "by_kind": dict(by_kind),
        "by_operator": dict(by_operator),
    }


def _load_local_env() -> None:
    paths = [ROOT / "apps" / "api" / ".env", Path.home() / ".config" / "bidfinder" / "typesense.env"]
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name and name not in os.environ:
                os.environ[name] = value.strip("'\"")


async def run_live() -> dict[str, Any]:
    _load_local_env()
    config = TypesenseShadowConfig.from_env()
    summary = corpus_summary()
    if not config.api_key:
        return {**summary, "live_status": "BLOCKED_NO_API_KEY", "generation": config.serving_generation, "errors": []}
    repository = TypesenseSearchRepository(config)
    latencies: dict[str, list[float]] = defaultdict(list)
    errors: list[str] = []
    invariant_failures: list[str] = []
    pagination_ids: dict[tuple[str, int], set[str]] = {}
    for spec in build_validation_corpus():
        started = time.perf_counter()
        try:
            if spec["kind"] == "autocomplete":
                suggestions = await repository.suggest(AutocompleteQuery(spec["group"], spec["field"], spec["value"], limit=10))
                if any(not value.casefold().startswith(spec["value"].casefold()) for value in suggestions):
                    invariant_failures.append("autocomplete_prefix")
            else:
                query = _query_from_spec(spec)
                result = await repository.exact_lookup(query) if spec["kind"] == "exact" else await repository.search(query)
                if spec["kind"] in {"subtype", "subtypes_all"}:
                    allowed = set(spec.get("source_types", []))
                    source_map = {item["key"]: item["selector"] for item in get_group_contract(spec["group"])["source_types"]}
                    expected = {source_map[key]["value"] for key in allowed}
                    field = next(iter({source_map[key]["field"] for key in allowed}), None) if allowed else None
                    if field and any(hit.get(field) not in expected for hit in result.hits):
                        invariant_failures.append("subtype_leakage")
                if spec["kind"] == "pagination":
                    ids = {str(row["id"]) for row in result.hits if row.get("id")}
                    pagination_ids[(spec["group"], spec["page"])] = ids
                if spec["kind"] in {"filter_eq", "filter_in", "combined", "combined_page"}:
                    field = spec["field"] if spec["kind"] == "filter_eq" or spec["kind"] == "filter_in" else spec["filter_field"]
                    expected = spec["value"] if spec["kind"] in {"filter_eq", "filter_in"} else spec["filter_value"]
                    values = []
                    for row in result.hits:
                        value = row.get(field)
                        values.extend(value if isinstance(value, list) else [value])
                    expected_values = expected.get("in", []) if isinstance(expected, dict) else ([expected] if not isinstance(expected, list) else expected)
                    if any(not any(_filter_value_matches(value, expected) for expected in expected_values) for value in values):
                        invariant_failures.append("filter_value")
                if spec["kind"] == "sort":
                    values = [row.get(spec["field"]) for row in result.hits if row.get(spec["field"]) is not None]
                    if spec["order"] == "asc" and values != sorted(values):
                        invariant_failures.append("sort_ascending")
                    if spec["order"] == "desc" and values != sorted(values, reverse=True):
                        invariant_failures.append("sort_descending")
        except Exception as exc:  # noqa: BLE001 - aggregate live evidence only.
            errors.append(type(exc).__name__)
        latencies[spec["kind"]].append((time.perf_counter() - started) * 1000)

    for group in PUBLIC_GROUPS:
        for page in (1, 2, 3):
            if pagination_ids.get((group, page), set()) & pagination_ids.get((group, page + 1), set()):
                invariant_failures.append("pagination_overlap")

    def stats(values: list[float]) -> dict[str, float]:
        values = sorted(values)
        p = lambda q: values[min(len(values) - 1, int(len(values) * q))]
        return {"p50_ms": round(p(0.50), 3), "p95_ms": round(p(0.95), 3), "max_ms": round(values[-1], 3)} if values else {"p50_ms": 0, "p95_ms": 0, "max_ms": 0}

    return {
        **summary,
        "live_status": "PASS" if not errors and not invariant_failures else "FAIL",
        "generation": config.serving_generation,
        "errors": {name: count for name, count in sorted(__import__("collections").Counter(errors).items())},
        "invariant_failures": {name: count for name, count in sorted(__import__("collections").Counter(invariant_failures).items())},
        "latency_ms": {name: stats(values) for name, values in sorted(latencies.items())},
        "outliers_over_500ms": sum(sum(value > 500 for value in values) for values in latencies.values()),
        "outliers_over_500ms_by_kind": {
            name: sum(value > 500 for value in values)
            for name, values in sorted(latencies.items())
            if any(value > 500 for value in values)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = corpus_summary() if args.summary else asyncio.run(run_live())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("live_status", "PASS") != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
