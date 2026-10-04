"""Rebuild the three disposable Typesense collections from canonical MSC data.

This is intentionally a one-shot runner. It does not export from Typesense,
clone collections, alter schemas, or persist checkpoints. A failed run stops;
restart means a fresh empty Typesense rebuild.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, timedelta
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.backfill import source_population_preflight
from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS, get_contract
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus
from crawler_engine.msc.sink import TypesenseSink
from crawler_engine.msc.typesense_client import TypesenseClient, TypesenseCollectionManager
from crawler_engine.msc.typesense_schema import (
    LOGICAL_ALIASES,
    _VIETNAMESE_SEARCH_FIELDS,
    collection_schema,
    physical_collection_name,
)

GROUP_ORDER = ("goods", "medicines", "traditional_medicine")


class NoPersistentCheckpointStore:
    """Checkpoint-shaped no-op. Rebuild has no resume state by design."""

    def get(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def start(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def finish(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def fail(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _meminfo_bytes() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return values


def _typesense_rss_bytes() -> int | None:
    data_dir = os.getenv("BIDFINDER_TYPESENSE_DATA_DIR", "")
    needle = f"--data-dir={data_dir}".encode()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes()
            if b"typesense-server" in command and needle in command:
                status = (proc / "status").read_text(encoding="ascii")
                for line in status.splitlines():
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return None


def resource_guard(client: TypesenseClient) -> dict[str, int | None]:
    health = client.health()
    if health.get("ok") is not True:
        raise RuntimeError(f"Typesense health failed: {health}")
    memory = _meminfo_bytes()
    snapshot: dict[str, int | None] = {
        "typesense_rss_bytes": _typesense_rss_bytes(),
        "mem_available_bytes": memory.get("MemAvailable"),
        "swap_used_bytes": max(0, memory.get("SwapTotal", 0) - memory.get("SwapFree", 0)),
    }
    print(
        "resources: "
        + " ".join(f"{key}={value if value is not None else 'unknown'}" for key, value in snapshot.items()),
        flush=True,
    )
    ram_warning = int(os.getenv("BIDFINDER_RAM_WARNING_BYTES", str(2 * 1024**3)))
    swap_warning = int(os.getenv("BIDFINDER_SWAP_WARNING_BYTES", str(1 * 1024**3)))
    if snapshot["mem_available_bytes"] is None:
        raise RuntimeError("RESOURCE_GUARD mem_available_bytes unavailable")
    if snapshot["mem_available_bytes"] < ram_warning:
        raise RuntimeError(f"RESOURCE_GUARD RAM near danger: {snapshot}")
    if snapshot["swap_used_bytes"] is not None and snapshot["swap_used_bytes"] > swap_warning:
        raise RuntimeError(f"RESOURCE_GUARD swap too high: {snapshot}")
    return snapshot


def _schema_for_rebuild(group: str, generation: str) -> dict[str, Any]:
    schema = collection_schema(group, generation)
    fields = {field["name"]: field for field in schema["fields"]}
    missing_locale = sorted(
        name
        for name in _VIETNAMESE_SEARCH_FIELDS
        if name in fields and fields[name]["type"] in {"string", "string[]"} and fields[name].get("locale") != "vi"
    )
    if missing_locale:
        raise RuntimeError(f"final schema missing locale=vi: {group}: {missing_locale}")
    return schema


def create_empty_final_collections(client: TypesenseClient, generation: str) -> tuple[str, ...]:
    if client.health().get("ok") is not True:
        raise RuntimeError("Typesense is not healthy before schema creation")
    expected = {group: _schema_for_rebuild(group, generation) for group in GROUP_ORDER}
    names = tuple(schema["name"] for schema in expected.values())
    actual = client.list_collections()
    actual_names = tuple(sorted(item["name"] for item in actual))
    if not actual:
        for schema in expected.values():
            client.create_collection(schema)
        actual_names = tuple(sorted(item["name"] for item in client.list_collections()))
        if actual_names != tuple(sorted(names)):
            raise RuntimeError(f"collection inventory mismatch after create: {actual_names}")
        return names

    # Reuse only the already-created final targets: exact generation, empty,
    # and semantically schema-compatible.
    if actual_names != tuple(sorted(names)):
        raise RuntimeError(f"unexpected collection set; refusing import: {actual_names}")
    for schema in expected.values():
        details = client.get_collection(schema["name"])
        if details is None or details.get("num_documents") != 0:
            raise RuntimeError(f"target collection is not empty: {schema['name']}")
        if not TypesenseCollectionManager._compatible(details, schema):
            raise RuntimeError(f"target collection schema is incompatible: {schema['name']}")
    return names


def rebuild(args: argparse.Namespace) -> dict[str, Any]:
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    if start > end:
        raise ValueError("--from must not be after --to")

    msc_config = MSCConfig(
        page_size=args.page_size,
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        max_retries=args.max_retries,
    )
    msc = MSCClient(msc_config)
    preflight = source_population_preflight(msc, start, end)
    expected = {group: int(preflight["group_totals"].get(group, 0)) for group in GROUP_ORDER}
    if any(value <= 0 for value in expected.values()):
        raise RuntimeError(f"canonical source incomplete: {expected}")

    typesense_config = TypesenseConfig.from_env()
    if args.batch_size is not None:
        typesense_config = replace(typesense_config, batch_size=args.batch_size)
    typesense = TypesenseClient(typesense_config)
    names = create_empty_final_collections(typesense, args.generation)
    sink = TypesenseSink(typesense, args.generation, batch_size=typesense_config.batch_size)
    engine = MSCIngestionEngine(msc, NoPersistentCheckpointStore(), sink, msc_config)

    imported: dict[str, int] = {group: 0 for group in GROUP_ORDER}
    for group in GROUP_ORDER:
        source_keys = [
            key for key in SOURCE_CONTRACTS
            if get_contract(key).data_group == group
        ]
        for source_key in source_keys:
            for partition_date in _date_range(start, end):
                result = engine.ingest_partition(source_key, partition_date, force=True)
                if result.status != IngestionStatus.COMPLETED:
                    raise RuntimeError(
                        f"import stopped: group={group} source={source_key} date={partition_date} "
                        f"code={result.error_code} error={result.error_message}"
                    )
                imported[group] += result.sink_accepted_count
                if imported[group] > expected[group]:
                    raise RuntimeError(f"import exceeded canonical count: {group} {imported[group]} > {expected[group]}")
                print(f"{group}: {imported[group]} / {expected[group]}", flush=True)
                resource_guard(typesense)
        if imported[group] != expected[group]:
            raise RuntimeError(f"import count mismatch: {group} {imported[group]} != {expected[group]}")
        actual = typesense.document_count(physical_collection_name(group, args.generation))
        if actual != expected[group]:
            raise RuntimeError(f"Typesense count mismatch: {group} {actual} != {expected[group]}")

    return {
        "generation": args.generation,
        "collections": list(names),
        "source_counts": expected,
        "typesense_counts": {
            group: typesense.document_count(physical_collection_name(group, args.generation))
            for group in GROUP_ORDER
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--from", dest="from_date", required=True)
    result.add_argument("--to", dest="to_date", required=True)
    result.add_argument("--generation", required=True)
    result.add_argument("--batch-size", type=int)
    result.add_argument("--page-size", type=int, default=1000)
    result.add_argument("--timeout", type=float, default=30.0)
    result.add_argument("--request-delay", type=float, default=1.0)
    result.add_argument("--max-retries", type=int, default=3)
    return result


def main() -> int:
    try:
        import json
        print(json.dumps(rebuild(parser().parse_args()), ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        print(f"REBUILD STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
