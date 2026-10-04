"""Stream the three local Typesense source collections to JSONL files.

This is an operator-only bridge for the clean data-dir rebuild.  It reads
from a local Typesense instance and never sends a mutation request to it.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_engine.msc.config import TypesenseConfig  # noqa: E402
from crawler_engine.msc.typesense_client import TypesenseClient  # noqa: E402
from crawler_engine.msc.typesense_schema import (  # noqa: E402
    LOGICAL_ALIASES,
    physical_collection_name,
)
from tools.migrate_typesense_vietnamese_locale import _final_schema  # noqa: E402


EXPECTED_COUNTS = {
    "goods": 9_596_715,
    "medicines": 585_449,
    "traditional_medicine": 32_022,
}

OUTPUT_NAMES = {
    "goods": "goods",
    "medicines": "medicines",
    "traditional_medicine": "traditional",
}


def _local_config() -> TypesenseConfig:
    config = TypesenseConfig.from_env()
    if config.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"refusing non-local Typesense host: {config.host}")
    return config


def _last_line(path: Path) -> bytes:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        if end == 0:
            return b""
        position = end
        chunks: list[bytes] = []
        while position > 0:
            size = min(64 * 1024, position)
            position -= size
            handle.seek(position)
            chunks.append(handle.read(size))
            data = b"".join(reversed(chunks))
            lines = data.splitlines()
            if len(lines) >= 2 or position == 0:
                return lines[-1] if lines else b""
    return b""


def _verify_file(path: Path, expected_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"export file is missing or empty: {path}")
    with path.open("rb") as handle:
        first_raw = handle.readline().strip()
    last_raw = _last_line(path).strip()
    try:
        first = json.loads(first_raw)
        last = json.loads(last_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"export sample is not valid JSON: {path}") from exc
    if not isinstance(first, dict) or not isinstance(last, dict):
        raise RuntimeError(f"export samples are not JSON objects: {path}")
    line_count = sum(1 for _ in path.open("rb"))
    if line_count != expected_count:
        raise RuntimeError(f"export count mismatch for {path}: {line_count} != {expected_count}")
    return first, last


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-generation", default="serving_v1_20260901")
    parser.add_argument("--target-generation", required=True)
    parser.add_argument("--export-dir", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--resume-existing", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    export_dir = Path(args.export_dir).expanduser()
    if export_dir.exists():
        if not args.resume_existing or not export_dir.is_dir():
            raise SystemExit(f"export directory already exists: {export_dir}")
    else:
        export_dir.mkdir(parents=True)

    client = TypesenseClient(_local_config())
    health = client.health()
    if health.get("ok") is not True:
        raise RuntimeError(f"Typesense is not ready: {health}")

    inventory = {item.get("name"): item for item in client.list_collections()}
    manifest: dict[str, Any] = {
        "source_generation": args.source_generation,
        "target_generation": args.target_generation,
        "source": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = export_dir / "manifest.json"
    if args.resume_existing and manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("source_generation") == args.source_generation:
            manifest.update(existing)
            manifest.setdefault("source", {})

    for group in LOGICAL_ALIASES:
        source_name = physical_collection_name(group, args.source_generation)
        source_schema = inventory.get(source_name) or client.get_collection(source_name)
        if source_schema is None:
            raise RuntimeError(f"source collection is missing: {source_name}")
        expected = EXPECTED_COUNTS[group]
        source_count = int(source_schema.get("num_documents", 0))
        if source_count != expected:
            raise RuntimeError(f"source count mismatch for {group}: {source_count} != {expected}")

        output_path = export_dir / f"{OUTPUT_NAMES[group]}.jsonl"
        previous = manifest["source"].get(group)
        if isinstance(previous, dict) and previous.get("documents") == expected and output_path.is_file():
            _verify_file(output_path, expected)
            print(f"RESUMED {group}: {expected} JSONL documents; first/last parse OK", flush=True)
            continue
        print(f"EXPORT {group}: {source_name} -> {output_path}", flush=True)
        count = 0
        with output_path.open("x", encoding="utf-8", newline="\n") as handle:
            for document in client.export_documents(source_name, timeout_seconds=args.timeout_seconds):
                if not isinstance(document, dict):
                    raise RuntimeError(f"non-object document in {source_name}")
                handle.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
                if count % 100_000 == 0:
                    print(f"{group}: {count} / {expected}", flush=True)
        if count != expected:
            raise RuntimeError(f"export ended early for {group}: {count} != {expected}")
        first, last = _verify_file(output_path, expected)
        target_name = physical_collection_name(group, args.target_generation)
        manifest["source"][group] = {
            "source_collection": source_name,
            "target_collection": target_name,
            "documents": count,
            "file": str(output_path),
            "source_schema": source_schema,
            "target_schema": _final_schema(group, args.target_generation, source_schema),
            "first_id": first.get("id"),
            "last_id": last.get("id"),
        }
        _write_json(manifest_path, manifest)
        print(f"VERIFIED {group}: {count} JSONL documents; first/last parse OK", flush=True)

    print(f"EXPORT_PASS {export_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
