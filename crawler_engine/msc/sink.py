"""Phase 2 sink boundary and local validation sinks."""

from __future__ import annotations

import json
import os
from time import perf_counter
import re
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

from .models import CanonicalRecord, PartitionContext, SinkWriteResult
from .typesense_client import (
    TYPESENSE_IDENTITY_CONFLICT,
    TYPESENSE_IMPORT_ERROR,
    TYPESENSE_SCHEMA_ERROR,
    TypesenseClient,
    TypesenseError,
    validate_identity_union,
)
from .typesense_schema import canonical_to_typesense_document, collection_schema, physical_collection_name, schema_signature, validate_generation_id


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
        return SinkWriteResult(len(records), len(records), 0, batch_count=1 if records else 0)


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
        return SinkWriteResult(len(records), len(records), 0, batch_count=1 if records else 0)


class TypesenseSink:
    """Sequential batched upsert sink that writes only to one physical generation."""

    def __init__(self, client: TypesenseClient, generation_id: str, *, batch_size: int | None = None) -> None:
        self.client = client
        self.generation_id = validate_generation_id(generation_id)
        self.batch_size = client.config.batch_size if batch_size is None else batch_size
        if self.batch_size <= 0:
            raise ValueError("Typesense batch_size must be positive")
        self.sink_target = f"typesense:{self.generation_id}"

    def collection_for(self, context: PartitionContext) -> str:
        return physical_collection_name(context.contract.data_group, self.generation_id)

    def _failure(self, attempted: int, errors: tuple[str, ...], code: str, *, batches: int = 0, elapsed: float = 0.0) -> SinkWriteResult:
        return SinkWriteResult(attempted, 0, max(1, attempted), errors, code, batches, elapsed)

    def write_partition(self, context: PartitionContext, records: Sequence[CanonicalRecord]) -> SinkWriteResult:
        started = perf_counter()
        collection = self.collection_for(context)
        try:
            actual = self.client.get_collection(collection)
            expected = collection_schema(context.contract.data_group, self.generation_id)
            if actual is None or schema_signature(actual) != schema_signature(expected):
                return self._failure(0, (f"physical collection {collection} is missing or incompatible",), TYPESENSE_SCHEMA_ERROR, elapsed=perf_counter() - started)
            validate_identity_union((records,))
            ids = [record.get("id") for record in records]
            if len(ids) != len(set(ids)):
                return self._failure(0, ("duplicate UUIDs in canonical partition",), TYPESENSE_IDENTITY_CONFLICT, elapsed=perf_counter() - started)
            documents = [canonical_to_typesense_document(record, context.contract.data_group) for record in sorted(records, key=lambda item: item["id"])]
        except TypesenseError as exc:
            return self._failure(0, (str(exc),), exc.code, elapsed=perf_counter() - started)
        except (TypeError, ValueError) as exc:
            return self._failure(0, (str(exc),), TYPESENSE_SCHEMA_ERROR, elapsed=perf_counter() - started)

        attempted = accepted = rejected = batch_count = 0
        errors: list[str] = []
        for offset in range(0, len(documents), self.batch_size):
            batch = documents[offset:offset + self.batch_size]
            batch_count += 1
            result = self.client.import_documents(collection, batch)
            attempted += result.attempted_count
            accepted += result.accepted_count
            rejected += result.rejected_count
            errors.extend(f"batch {batch_count}: {error}" for error in result.errors)
            if result.rejected_count:
                return SinkWriteResult(
                    attempted, accepted, rejected, tuple(errors), result.error_code or TYPESENSE_IMPORT_ERROR,
                    batch_count, perf_counter() - started,
                )
        return SinkWriteResult(attempted, accepted, rejected, tuple(errors), None, batch_count, perf_counter() - started)
