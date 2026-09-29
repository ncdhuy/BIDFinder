"""Aggregated eLMIS ingredient-code lookup."""

from datetime import date, datetime


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


def lookup_where(filters: dict[str, str]) -> tuple[str, list[str]]:
    clauses = []
    values = []
    for name, column in FILTER_COLUMNS.items():
        value = filters.get(name, "").strip()
        if value:
            values.append("%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            clauses.append(f"{column} ILIKE ${len(values)} ESCAPE '\\'")
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), values


async def lookup_page(conn, filters: dict[str, str], page: int, limit: int) -> dict:
    where, values = lookup_where(filters)
    async with conn.transaction(readonly=True):
        totals = await conn.fetchrow(
            f"SELECT COUNT(*) AS groups, COALESCE(SUM(occurrences), 0) AS records, "
            f"COALESCE(MAX(occurrences), 0) AS max_count FROM vss_ingredient_counts{where}",
            *values,
        )
        rows = await conn.fetch(
            f"SELECT ma, hoatchat, ten, sodk, duongdung, nam_congbo, occurrences "
            f"FROM vss_ingredient_counts{where} "
            f"ORDER BY occurrences DESC, ma ASC NULLS LAST, hoatchat ASC NULLS LAST, "
            f"ten ASC NULLS LAST, sodk ASC NULLS LAST, duongdung ASC NULLS LAST, "
            f"nam_congbo ASC NULLS LAST LIMIT ${len(values) + 1} OFFSET ${len(values) + 2}",
            *values, limit, (page - 1) * limit,
        )
    return {
        "rows": [dict(row) for row in rows],
        "total_groups": totals["groups"],
        "total_records": totals["records"],
        "max_count": totals["max_count"],
        "page": page,
        "limit": limit,
    }
