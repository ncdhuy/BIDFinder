"""Aggregated eLMIS ingredient-code lookup in a dedicated Typesense collection."""

from datetime import date, datetime
from hashlib import sha256
import json
from threading import Lock


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


def _fold(value: str) -> str:
    return " ".join(value.split()).casefold()


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


class IngredientLookupStore:
    """A bounded in-process substring index of the current Typesense alias."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._collection = None
        self._rows = ()
        self._matches = {}

    def _load(self, request_json, export_documents) -> None:
        alias = request_json(f"/aliases/{COLLECTION_ALIAS}")
        collection = alias["collection_name"]
        if collection == self._collection:
            return
        rows = []
        for document in export_documents(collection):
            display = {field: document.get(field) or None for field in SCHEMA_FIELDS}
            display["occurrences"] = int(document["occurrences"])
            folded = tuple(_fold(document.get(field) or "") for field in SCHEMA_FIELDS)
            rows.append((display, folded, int(document["sort_order"])))
        expected = request_json(f"/collections/{collection}")["num_documents"]
        if len(rows) != expected:
            raise RuntimeError("eLMIS Typesense export is incomplete")
        rows.sort(key=lambda row: (-row[0]["occurrences"], row[2]))
        self._rows = tuple((display, folded) for display, folded, _ in rows)
        self._collection = collection
        self._matches.clear()

    def matching(self, request_json, export_documents, filters: dict[str, str]):
        needles = tuple(_fold(filters.get(name, "")) for name in FILTER_COLUMNS)
        with self._lock:
            self._load(request_json, export_documents)
            if needles not in self._matches:
                indexes = [(FIELDS.index(field), needle) for field, needle in zip(FILTER_COLUMNS.values(), needles) if needle]
                matched = tuple(row for row in self._rows if all(needle in row[1][index] for index, needle in indexes))
                total = sum(row[0]["occurrences"] for row in matched)
                maximum = matched[0][0]["occurrences"] if matched else 0
                if len(self._matches) >= 8:
                    self._matches.pop(next(iter(self._matches)))
                self._matches[needles] = (matched, total, maximum)
            return self._matches[needles]


def lookup_page(store: IngredientLookupStore, request_json, export_documents,
                filters: dict[str, str], page: int, limit: int, include_totals: bool = True) -> dict:
    matched, total, maximum = store.matching(request_json, export_documents, filters)
    start = (page - 1) * limit
    return {
        "rows": [row[0] for row in matched[start:start + limit]],
        "total_groups": len(matched),
        "total_records": total if include_totals else 0,
        "max_count": maximum if include_totals else 0,
        "page": page,
        "limit": limit,
    }


def lookup_suggestions(store: IngredientLookupStore, request_json, export_documents,
                       field: str, query: str, filters: dict[str, str], limit: int = 8) -> list[str]:
    if field not in FILTER_COLUMNS:
        raise ValueError("Trường gợi ý không hợp lệ.")
    query = _fold(query)
    if not query:
        return []
    context = {**filters, field: ""}
    matched, _, _ = store.matching(request_json, export_documents, context)
    index = FIELDS.index(FILTER_COLUMNS[field])
    suggestions = {}
    for display, folded in matched:
        value = display[FIELDS[index]]
        if value and query in folded[index]:
            key = folded[index]
            if key in suggestions:
                suggestions[key][1] += display["occurrences"]
            else:
                suggestions[key] = [" ".join(value.split()), display["occurrences"]]
    return [value for value, _ in sorted(suggestions.values(), key=lambda item: (-item[1], item[0].casefold(), item[0]))[:limit]]
