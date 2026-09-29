"""Aggregated eLMIS ingredient-code lookup in a dedicated Typesense collection."""

from datetime import date, datetime
from hashlib import sha256
import json
from urllib.parse import urlencode


FIELDS = ("ma", "hoatchat", "ten", "sodk", "duongdung", "nam_congbo")
FILTER_COLUMNS = {
    "registration": "sodk",
    "drug": "ten",
    "ingredient": "hoatchat",
    "route": "duongdung",
    "year": "nam_congbo",
}


def publication_year(value: str | None) -> str | None:
    """Derive a valid year from the source's ISO or Vietnamese date text."""
    if not value:
        return None
    value = value.strip()
    try:
        return str(date.fromisoformat(value[:10]).year)
    except ValueError:
        try:
            return str(datetime.strptime(value, "%d/%m/%Y").year)
        except ValueError:
            return None


def source_key(row: dict[str, str]) -> tuple[str | None, ...]:
    return tuple(publication_year(row.get("congbo")) if field == "nam_congbo"
                 else (row.get(field) or None) for field in FIELDS)


COLLECTION_ALIAS = "vss_ingredient_lookup"
SCHEMA_FIELDS = FIELDS


def collection_schema(name: str) -> dict:
    return {"name": name, "fields": [
        *({"name": field, "type": "string"} for field in SCHEMA_FIELDS),
        {"name": "occurrences", "type": "int32", "facet": True},
        {"name": "sort_order", "type": "int32"},
    ], "default_sorting_field": "occurrences"}


def count_document(key: tuple[str | None, ...], count: int, order: int) -> dict:
    values = [value or "" for value in key]
    identity = sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"id": identity, **dict(zip(SCHEMA_FIELDS, values)),
            "occurrences": count, "sort_order": order}


def lookup_filter(filters: dict[str, str]) -> str:
    clauses = []
    for name, field in FILTER_COLUMNS.items():
        value = filters.get(name, "").strip()
        if value:
            if "`" in value:
                raise ValueError("Ký tự ` không được hỗ trợ trong điều kiện tra cứu.")
            operator = ":=" if name == "year" else ":"
            clauses.append(f"{field}{operator}`{value}`")
    return " && ".join(clauses)


def lookup_page(request_json, filters: dict[str, str], page: int, limit: int,
                include_totals: bool = True) -> dict:
    params = {"q": "*", "query_by": "ma", "page": page, "per_page": limit,
              "sort_by": "occurrences:desc,sort_order:asc"}
    if include_totals:
        params.update(facet_by="occurrences", facet_strategy="exhaustive")
    if condition := lookup_filter(filters):
        params["filter_by"] = condition
    result = request_json(f"/collections/{COLLECTION_ALIAS}/documents/search?{urlencode(params)}")
    facets = result.get("facet_counts") or []
    stats = next((facet.get("stats", {}) for facet in facets if facet.get("field_name") == "occurrences"), {})
    return {
        "rows": [{field: (document.get(field) or None) for field in SCHEMA_FIELDS} |
                 {"occurrences": document["occurrences"]}
                 for hit in result.get("hits", []) for document in [hit["document"]]],
        "total_groups": result.get("found", 0),
        "total_records": int(stats.get("sum", 0)),
        "max_count": int(stats.get("max", 0)),
        "page": page,
        "limit": limit,
    }
