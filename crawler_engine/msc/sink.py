"""Phase 2 sink boundary and local validation sinks."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

from .models import CanonicalRecord, PartitionContext, SinkWriteResult


class Sink(Protocol):
    def write_partition(self, context: PartitionContext, records: Sequence[CanonicalRecord]) -> SinkWriteResult:
        ...


def _valid_records(records: Sequence[CanonicalRecord]) -> tuple[bool, tuple[str, ...]]:
    errors = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            errors.append(f"record[{index}] missing non-empty id")
    return not errors, tuple(errors)


class InMemorySink:
    """Deterministic test sink with UUID-stable replacement semantics."""

    def __init__(self) -> None:
        self.records: dict[str, CanonicalRecord] = {}
        self.partitions: dict[tuple[str, str], tuple[str, ...]] = {}

    def write_partition(self, context: PartitionContext, records: Sequence[CanonicalRecord]) -> SinkWriteResult:
        valid, errors = _valid_records(records)
        if not valid:
            return SinkWriteResult(len(records), 0, len(records), errors)
        ids = []
        for record in sorted(records, key=lambda item: item["id"]):
            self.records[record["id"]] = dict(record)
            ids.append(record["id"])
        self.partitions[(context.source_key, context.partition_date)] = tuple(ids)
        return SinkWriteResult(len(records), len(records), 0)


class JsonlValidationSink:
    """Atomic UTF-8 canonical JSONL staging sink; each run replaces its file."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "unknown"

    def path_for(self, context: PartitionContext) -> Path:
        return self.output_dir / self._safe(context.contract.data_group) / (
            f"{self._safe(context.source_key)}__{self._safe(context.partition_date)}.jsonl"
        )

    def write_partition(self, context: PartitionContext, records: Sequence[CanonicalRecord]) -> SinkWriteResult:
        valid, errors = _valid_records(records)
        if not valid:
            return SinkWriteResult(len(records), 0, len(records), errors)
        target = self.path_for(context)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
                temp_name = handle.name
                for record in sorted(records, key=lambda item: item["id"]):
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
        return SinkWriteResult(len(records), len(records), 0)
