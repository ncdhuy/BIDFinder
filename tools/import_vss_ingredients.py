"""Build the eLMIS Typesense lookup collection from local XML data.

Example: python tools/import_vss_ingredients.py --raw-dir crawler_engine/vss_data/downloads
Use --apply to publish a new Typesense collection after the full input is grouped.
"""

import argparse
from collections import Counter
from itertools import islice
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
from ingredient_lookup import COLLECTION_ALIAS, collection_schema, count_document, source_key
from crawler_engine.vss.download_vss_data import iter_excel_xml_rows
from crawler_engine.msc.config import TypesenseConfig
from crawler_engine.msc.typesense_client import TypesenseClient

load_dotenv(ROOT / "apps" / "api" / ".env", override=False)

SOURCE_FIELDS = {"ma", "hoatchat", "ten", "sodk", "duongdung", "congbo"}


def aggregate_xml(raw_dir: Path) -> Counter:
    counts = Counter()
    files = sorted(raw_dir.rglob("*.xml"))
    if not files:
        raise ValueError(f"No XML files found in {raw_dir}")
    for path in files:
        first_part = path.relative_to(raw_dir).parts[0]
        loai = int(first_part.removeprefix("loai_")) if first_part.startswith("loai_") else 1
        if loai not in (1, 2, 3, 4):
            raise ValueError(f"{path}: unsupported eLMIS category {loai}")
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
            counts[source_key(row, loai)] += 1
    return counts


def import_counts(client: TypesenseClient, counts: Counter) -> str:
    if not counts:
        raise ValueError("No eLMIS records to import")
    name = f"{COLLECTION_ALIAS}_{uuid4().hex[:12]}"
    client.create_collection(collection_schema(name))
    # A fresh collection keeps the previous alias serving until every batch succeeds.
    ordered = sorted(counts, key=lambda key: tuple(value or "" for value in key))
    rows = (count_document(key, counts[key], order) for order, key in enumerate(ordered))
    while batch := list(islice(rows, client.config.batch_size)):
        result = client.import_documents(name, batch)
        if result.rejected_count or result.accepted_count != len(batch):
            raise RuntimeError(f"Typesense import stopped at {name}: {result.errors[:3]}")
    actual = client.get_collection(name)
    if not actual or actual.get("num_documents") != len(counts):
        raise RuntimeError(f"Typesense document count mismatch in {name}")
    client.upsert_alias(COLLECTION_ALIAS, name)
    return name


def typesense_client_from_env() -> TypesenseClient:
    config = TypesenseConfig(
        host=os.getenv("BIDFINDER_TYPESENSE_HOST", os.getenv("TYPESENSE_HOST", "127.0.0.1")),
        port=int(os.getenv("BIDFINDER_TYPESENSE_PORT", os.getenv("TYPESENSE_PORT", "8108"))),
        protocol=os.getenv("BIDFINDER_TYPESENSE_PROTOCOL", os.getenv("TYPESENSE_PROTOCOL", "http")),
        api_key=os.getenv("BIDFINDER_TYPESENSE_API_KEY", os.getenv("TYPESENSE_API_KEY", "")),
    )
    return TypesenseClient(config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path, help="Directory of downloaded eLMIS XML files")
    parser.add_argument("--apply", action="store_true", help="Publish a new local Typesense collection")
    args = parser.parse_args()
    counts = aggregate_xml(args.raw_dir)
    print(f"{sum(counts.values())} source rows; {len(counts)} grouped rows")
    if args.apply:
        name = import_counts(typesense_client_from_env(), counts)
        print(f"Published {name} as {COLLECTION_ALIAS}")


if __name__ == "__main__":
    main()
