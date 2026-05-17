import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

import asyncpg
from dotenv import load_dotenv

from server import FilterRequest, SortRule, build_result_query


HOT_CASES: Dict[str, Dict[str, Any]] = {
    "drugName:paracetamol": {
        "scope": "medicine",
        "filters": {"drugName": {"tokens": [{"value": "paracetamol", "op": "OR"}]}},
    },
    "activeIngredient:amoxicillin": {
        "scope": "medicine",
        "filters": {"activeIngredient": {"tokens": [{"value": "amoxicillin", "op": "OR"}]}},
    },
    "winner:cong-ty": {
        "scope": "medicine",
        "filters": {"winner": {"tokens": [{"value": "công ty", "op": "OR"}]}},
    },
    "country:viet-nam": {
        "scope": "medicine",
        "filters": {"country": {"tokens": [{"value": "Việt Nam", "op": "OR"}]}},
    },
    "goodsName:bom-tiem": {
        "scope": "goods",
        "filters": {"drugName": {"tokens": [{"value": "bơm tiêm", "op": "OR"}]}},
    },
    "goodsSpec:xet-nghiem": {
        "scope": "goods",
        "filters": {"specification": {"tokens": [{"value": "xét nghiệm", "op": "OR"}]}},
    },
    "goodsCountry:viet-nam": {
        "scope": "goods",
        "filters": {"country": {"tokens": [{"value": "Việt Nam", "op": "OR"}]}},
    },
}


def build_explain_query(case: Dict[str, Any], *, analyze: bool, limit: int) -> tuple[str, List[Any]]:
    filters = FilterRequest(**case["filters"])
    sort_rules = [SortRule(column="approvalDate", order="desc")]
    query, params = build_result_query(
        scope_name=case["scope"],
        filters=filters,
        sort_rules=sort_rules,
        limit=limit,
        include_overflow_probe=True,
    )
    options = "ANALYZE, BUFFERS, VERBOSE" if analyze else "BUFFERS, VERBOSE"
    return f"EXPLAIN ({options})\n{query}", params


async def run_case(conn: asyncpg.Connection, name: str, case: Dict[str, Any], *, analyze: bool, limit: int) -> None:
    query, params = build_explain_query(case, analyze=analyze, limit=limit)
    rows = await conn.fetch(query, *params)
    print(f"\n=== {name} ===")
    print(f"scope={case['scope']} analyze={analyze} limit={limit}")
    for row in rows:
        print(row[0])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run EXPLAIN for BIDFinder hot search queries.")
    parser.add_argument("--case", choices=[*HOT_CASES.keys(), "all"], default="all")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--analyze", action="store_true", help="Actually execute the queries with EXPLAIN ANALYZE.")
    args = parser.parse_args()

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required. Set it in apps/api/.env or the shell environment.")

    conn = await asyncpg.connect(database_url)
    try:
        selected = HOT_CASES if args.case == "all" else {args.case: HOT_CASES[args.case]}
        for name, case in selected.items():
            await run_case(conn, name, case, analyze=args.analyze, limit=args.limit)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
