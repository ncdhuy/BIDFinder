"""Build the eLMIS lookup table from app_vss/qlt_realtime/combined.csv.

Example: python tools/import_vss_ingredients.py --csv D:/startup/app_vss/qlt_realtime/combined.csv --database-url "$DATABASE_URL"
The table is replaced only after the complete CSV has been grouped successfully.
"""

import argparse
import asyncio
from collections import Counter
import csv
from itertools import islice
import os
from pathlib import Path
import sys

import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from ingredient_lookup import source_key

load_dotenv(Path(__file__).resolve().parents[1] / "apps" / "api" / ".env", override=False)


def aggregate_csv(path: Path) -> Counter:
    counts = Counter()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"ma", "hoatchat", "ten", "sodk", "duongdung", "congbo"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            counts[source_key(row)] += 1
    return counts


async def import_counts(database_url: str, counts: Counter) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vss_ingredient_counts (
                    ma TEXT, hoatchat TEXT, ten TEXT, sodk TEXT, duongdung TEXT,
                    nam_congbo TEXT, occurrences INTEGER NOT NULL CHECK (occurrences > 0)
                )
            """)
            await conn.execute("""
                CREATE TEMP TABLE vss_ingredient_stage
                (LIKE vss_ingredient_counts INCLUDING CONSTRAINTS) ON COMMIT DROP
            """)
            rows = ((*key, count) for key, count in counts.items())
            while batch := list(islice(rows, 5000)):
                await conn.copy_records_to_table(
                    "vss_ingredient_stage", records=batch,
                    columns=["ma", "hoatchat", "ten", "sodk", "duongdung", "nam_congbo", "occurrences"],
                )
            await conn.execute("TRUNCATE vss_ingredient_counts")
            await conn.execute("INSERT INTO vss_ingredient_counts SELECT * FROM vss_ingredient_stage")
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS vss_ingredient_counts_order
                ON vss_ingredient_counts (occurrences DESC)
            """)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Replace the lookup table in Postgres")
    args = parser.parse_args()
    counts = aggregate_csv(args.csv)
    print(f"{sum(counts.values())} source rows; {len(counts)} grouped rows")
    if args.apply:
        if not args.database_url:
            parser.error("--database-url or DATABASE_URL is required with --apply")
        asyncio.run(import_counts(args.database_url, counts))
        print("Lookup table replaced")


if __name__ == "__main__":
    main()
