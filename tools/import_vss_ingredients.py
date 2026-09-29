"""Build the eLMIS lookup table from BIDFinder's local XML or CSV data.

Example: python tools/import_vss_ingredients.py --csv crawler_engine/vss_data/combined.csv
Use --apply to replace the Postgres table after the full input has been grouped.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
from ingredient_lookup import source_key
from crawler_engine.vss.download_vss_data import iter_excel_xml_rows

load_dotenv(ROOT / "apps" / "api" / ".env", override=False)

SOURCE_FIELDS = {"ma", "hoatchat", "ten", "sodk", "duongdung", "congbo"}


def aggregate_csv(path: Path) -> Counter:
    counts = Counter()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = SOURCE_FIELDS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            counts[source_key(row)] += 1
    return counts


def aggregate_xml(raw_dir: Path) -> Counter:
    counts = Counter()
    files = sorted(raw_dir.rglob("*.xml"))
    if not files:
        raise ValueError(f"No XML files found in {raw_dir}")
    for path in files:
        rows = iter_excel_xml_rows(path)
        headers = [value.strip() for value in next(rows, [])]
        if not headers:
            continue  # Valid eLMIS export for a day with no records.
        missing = SOURCE_FIELDS - set(headers)
        if missing:
            raise ValueError(f"{path}: missing XML columns: {', '.join(sorted(missing))}")
        positions = {field: headers.index(field) for field in SOURCE_FIELDS}
        for values in rows:
            if not any(values):
                continue
            row = {field: values[index] if index < len(values) else "" for field, index in positions.items()}
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="Combined eLMIS CSV inside BIDFinder")
    source.add_argument("--raw-dir", type=Path, help="Directory of downloaded eLMIS XML files")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Replace the lookup table in Postgres")
    args = parser.parse_args()
    counts = aggregate_csv(args.csv) if args.csv else aggregate_xml(args.raw_dir)
    print(f"{sum(counts.values())} source rows; {len(counts)} grouped rows")
    if args.apply:
        if not args.database_url:
            parser.error("--database-url or DATABASE_URL is required with --apply")
        asyncio.run(import_counts(args.database_url, counts))
        print("Lookup table replaced")


if __name__ == "__main__":
    main()
