"""Create the final local Typesense collections and import JSONL files once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.config import TypesenseConfig  # noqa: E402
from crawler_engine.msc.typesense_client import TypesenseClient  # noqa: E402
from crawler_engine.msc.typesense_schema import LOGICAL_ALIASES, physical_collection_name  # noqa: E402


EXPECTED_COUNTS = {
    "goods": 9_596_715,
    "medicines": 585_449,
    "traditional_medicine": 32_022,
}


def _local_config() -> TypesenseConfig:
    config = TypesenseConfig.from_env()
    if config.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"refusing non-local Typesense host: {config.host}")
    return config


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("source"), dict):
        raise RuntimeError(f"invalid export manifest: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--progress-every", type=int, default=10_000)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    args = parser.parse_args()
    if args.batch_size <= 0 or args.progress_every <= 0 or args.timeout_seconds <= 0:
        raise SystemExit("batch, progress, and timeout values must be positive")

    manifest = _load_manifest(Path(args.manifest).expanduser())
    generation = manifest.get("target_generation")
    if not isinstance(generation, str) or not generation:
        raise RuntimeError("manifest has no target generation")

    client = TypesenseClient(_local_config())
    if client.health().get("ok") is not True:
        raise RuntimeError("fresh Typesense is not ready")
    if client.list_collections():
        raise RuntimeError("fresh Typesense is not empty; refuse import")

    for group in LOGICAL_ALIASES:
        entry = manifest["source"].get(group)
        if not isinstance(entry, dict):
            raise RuntimeError(f"manifest is missing group: {group}")
        expected = EXPECTED_COUNTS[group]
        source_file = Path(str(entry.get("file", ""))).expanduser()
        target_name = physical_collection_name(group, generation)
        if entry.get("target_collection") != target_name:
            raise RuntimeError(f"manifest target mismatch for {group}")
        target_schema = entry.get("target_schema")
        if not isinstance(target_schema, dict):
            raise RuntimeError(f"manifest schema is missing for {group}")
        if not source_file.is_file():
            raise RuntimeError(f"local JSONL file is missing: {source_file}")

        print(f"CREATE {group}: {target_name}", flush=True)
        created = client.create_collection(target_schema)
        if created.get("name") != target_name:
            raise RuntimeError(f"created collection name mismatch for {group}")

        imported = 0
        batch: list[dict[str, Any]] = []
        with source_file.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                document = json.loads(raw_line)
                if not isinstance(document, dict):
                    raise RuntimeError(f"non-object JSON at {source_file}:{line_number}")
                batch.append(document)
                if len(batch) < args.batch_size:
                    continue
                result = client.import_documents(target_name, batch, timeout_seconds=args.timeout_seconds)
                if result.accepted_count != len(batch) or result.rejected_count:
                    raise RuntimeError(
                        f"import failed for {group} at {imported + len(batch)}/{expected}: "
                        f"accepted={result.accepted_count} rejected={result.rejected_count} errors={result.errors[:3]}"
                    )
                imported += len(batch)
                if imported % args.progress_every < args.batch_size or imported == expected:
                    print(f"{group}: {imported} / {expected}", flush=True)
                batch.clear()
        if batch:
            result = client.import_documents(target_name, batch, timeout_seconds=args.timeout_seconds)
            if result.accepted_count != len(batch) or result.rejected_count:
                raise RuntimeError(
                    f"import failed for {group} at end: accepted={result.accepted_count} "
                    f"rejected={result.rejected_count} errors={result.errors[:3]}"
                )
            imported += len(batch)
        if imported != expected:
            raise RuntimeError(f"local JSONL count mismatch for {group}: {imported} != {expected}")
        target = client.get_collection(target_name)
        if target is None or int(target.get("num_documents", 0)) != expected:
            raise RuntimeError(f"target count mismatch for {group}")
        print(f"VERIFIED {group}: {expected}", flush=True)

    print("IMPORT_PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
