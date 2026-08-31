from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import unittest

from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.cli import build_parser
from crawler_engine.msc.config import MSCConfig, TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus, PartitionContext, SinkWriteResult
from crawler_engine.msc.normalize import normalize_record
from crawler_engine.msc.partitioning import official_day_interval
from crawler_engine.msc.sink import TypesenseSink
from crawler_engine.msc.typesense_client import (
    ImportResult,
    TYPESENSE_IDENTITY_CONFLICT,
    TYPESENSE_IMPORT_ERROR,
    TYPESENSE_PARTIAL_IMPORT,
    TypesenseCollectionManager,
    TypesenseClient,
    TypesenseError,
    parse_import_response,
    serialize_ndjson,
    validate_identity_union,
)
from crawler_engine.msc.typesense_schema import (
    LOGICAL_ALIASES,
    SEARCH_CONFIGS,
    canonical_to_typesense_document,
    collection_schema,
    physical_collection_name,
    schema_signature,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_MAP = {
    "goods_general": "goods-general",
    "medical_devices": "medical-devices",
    "medicine_generic": "medicine-generic",
    "medicine_originator": "medicine-originator",
    "medicine_herbal": "medicine-herbal",
    "herbal_material": "herbal-material",
    "traditional_medicine": "traditional-medicine",
}


def _doc_tables() -> dict[str, dict[str, dict[str, object]]]:
    lines = (ROOT / "docs" / "msc-typesense-schema-v1.md").read_text(encoding="utf-8").splitlines()
    tables: dict[str, dict[str, dict[str, object]]] = {}
    section: str | None = None
    for line in lines:
        heading = re.match(r"^## (?:`?(bidfinder_[^`]+)`?|Common fields)", line)
        if heading:
            if line == "## Common fields":
                section = "common"
            else:
                section = heading.group(1).removeprefix("bidfinder_")
            tables.setdefault(section, {})
            continue
        if line.startswith("## "):
            section = None
            continue
        if not section or not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"Field", ""}:
            continue
        tables[section][cells[0]] = {
            "type": cells[1],
            "optional": cells[2].lower() == "yes",
            "facet": cells[3].lower() == "yes",
            "sort": cells[4].lower() == "yes",
            "search": cells[5].lower() == "yes",
        }
    return tables


def _sample(source_key: str) -> dict:
    slug = CONTRACT_MAP[source_key]
    payload = json.loads((ROOT / "docs" / "msc-contracts" / slug / "search-response-sample.json").read_text(encoding="utf-8"))
    return payload["page"]["content"][0]


def _doc_query_by() -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    section: str | None = None
    for line in (ROOT / "docs" / "msc-typesense-schema-v1.md").read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## `?(bidfinder_[^`]+)`?", line)
        if heading:
            section = heading.group(1).removeprefix("bidfinder_")
        match = re.match(r"^`query_by` order: `([^`]+)`\.", line)
        if match and section:
            result[section] = tuple(match.group(1).split(","))
    return result


class SchemaContractTest(unittest.TestCase):
    def test_runtime_schema_matches_frozen_documentation(self):
        documented = _doc_tables()
        query_by = _doc_query_by()
        self.assertEqual({"common", "goods", "medicines", "traditional"}, set(documented))
        for group, doc_group in (("goods", "goods"), ("medicines", "medicines"), ("traditional_medicine", "traditional")):
            actual = {
                field["name"]: {
                    "type": field["type"],
                    "optional": field.get("optional", False),
                    "facet": field.get("facet", False),
                    "sort": field.get("sort", False),
                }
                for field in collection_schema(group, "dev1")["fields"]
            }
            expected = {
                name: {key: value for key, value in spec.items() if key != "search"}
                for name, spec in {**documented["common"], **documented[doc_group]}.items()
            }
            self.assertEqual(expected, actual, group)
            self.assertEqual(
                set(query_by[doc_group]),
                set(SEARCH_CONFIGS[group].query_by),
                group,
            )

    def test_all_seven_normalized_fixtures_are_valid_documents(self):
        for source_key in CONTRACT_MAP:
            contract = SOURCE_CONTRACTS[source_key]
            canonical = normalize_record(contract, _sample(source_key), "2026-08-28")
            document = canonical_to_typesense_document(canonical)
            self.assertEqual(contract.data_group, document["data_group"])
            self.assertNotIn("source_key", document)
            self.assertEqual(
                {field["name"] for field in collection_schema(contract.data_group, "dev1")["fields"] if not field.get("optional")},
                set(document) & {"id", "data_group", "source_tab", "source_tab_label", "partition_date"},
            )

    def test_optional_nulls_are_omitted_and_raw_fields_are_rejected(self):
        contract = SOURCE_CONTRACTS["goods_general"]
        raw = _sample("goods_general")
        raw.pop("danhMucHangHoa", None)
        canonical = normalize_record(contract, raw, "2026-08-28")
        document = canonical_to_typesense_document(canonical)
        self.assertNotIn("item_name", document)
        canonical["not_in_schema"] = "raw source must not leak"
        with self.assertRaisesRegex(ValueError, "outside frozen Typesense schema"):
            canonical_to_typesense_document(canonical)


class ImportProtocolTest(unittest.TestCase):
    def test_ndjson_is_sorted_stable_and_utf8(self):
        payload = serialize_ndjson([{"id": "b", "name": "Đường"}, {"id": "a", "name": "Áo"}])
        self.assertEqual('{"id":"b","name":"Đường"}\n{"id":"a","name":"Áo"}\n'.encode("utf-8"), payload)

    def test_http_200_with_one_false_result_is_partial_failure(self):
        result = parse_import_response('{"success":true}\n{"success":false,"error":"bad field"}\n', 2)
        self.assertEqual((2, 1, 1), (result.attempted_count, result.accepted_count, result.rejected_count))
        self.assertEqual(TYPESENSE_PARTIAL_IMPORT, result.error_code)
        self.assertIn("bad field", result.errors[0])

    def test_response_line_count_mismatch_fails_closed(self):
        result = parse_import_response('{"success":true}\n', 2)
        self.assertEqual((2, 1, 1), (result.attempted_count, result.accepted_count, result.rejected_count))
        self.assertEqual(TYPESENSE_IMPORT_ERROR, result.error_code)

    def test_full_response_requires_every_line_success(self):
        result = parse_import_response('{"success":true}\n{"success":true}\n', 2)
        self.assertEqual((2, 2, 0), (result.attempted_count, result.accepted_count, result.rejected_count))
        self.assertIsNone(result.error_code)

    def test_client_posts_ndjson_to_import_upsert_endpoint(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"success":true}\n'

        class Opener:
            def __init__(self):
                self.request = None

            def __call__(self, request, **kwargs):
                self.request = request
                return Response()

        opener = Opener()
        result = TypesenseClient(TypesenseConfig(api_key="dev-only"), opener=opener).import_documents(
            "bidfinder_goods_v1_dev1", [{"id": "one"}]
        )
        self.assertEqual((1, 1, 0), (result.attempted_count, result.accepted_count, result.rejected_count))
        self.assertIn("/documents/import?action=upsert", opener.request.full_url)
        self.assertEqual("application/jsonl", opener.request.headers["Content-type"])

    def test_snapshot_uses_supported_operation_and_absolute_host_path(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"success":true}'

        class Opener:
            def __init__(self):
                self.request = None

            def __call__(self, request, **kwargs):
                self.request = request
                return Response()

        opener = Opener()
        result = TypesenseClient(TypesenseConfig(api_key="dev-only"), opener=opener).snapshot("/tmp/bidfinder.snapshot")
        self.assertTrue(result["success"])
        self.assertIn("/operations/snapshot?", opener.request.full_url)
        self.assertIn("snapshot_path=%2Ftmp%2Fbidfinder.snapshot", opener.request.full_url)


class FakeTypesenseClient:
    def __init__(self, generation: str = "dev1", results: list[ImportResult] | None = None):
        self.config = TypesenseConfig(api_key="dev-only")
        self.generation = generation
        self.results = iter(results or [])
        self.import_calls: list[tuple[str, list[dict]]] = []

    def get_collection(self, name):
        for group in LOGICAL_ALIASES:
            if name == physical_collection_name(group, self.generation):
                return collection_schema(group, self.generation)
        return None

    def import_documents(self, collection, documents):
        self.import_calls.append((collection, list(documents)))
        try:
            return next(self.results)
        except StopIteration:
            return ImportResult(len(documents), len(documents), 0)


class SinkTest(unittest.TestCase):
    def test_batches_route_only_to_physical_generation(self):
        client = FakeTypesenseClient()
        sink = TypesenseSink(client, "dev1", batch_size=2)
        contract = SOURCE_CONTRACTS["goods_general"]
        records = [
            {**canonical_to_typesense_document(normalize_record(contract, _sample("goods_general"), "2026-08-28")), "source_key": "goods_general", "id": str(index)}
            for index in range(3)
        ]
        context = PartitionContext("goods_general", "2026-08-28", contract, official_day_interval("2026-08-28"), 3, 3, 3, 3, 3, 1)
        result = sink.write_partition(context, records)
        self.assertEqual((3, 3, 0, 2), (result.attempted_count, result.accepted_count, result.rejected_count, result.batch_count))
        self.assertEqual("typesense:dev1", sink.sink_target)
        self.assertEqual([physical_collection_name("goods", "dev1")] * 2, [call[0] for call in client.import_calls])
        self.assertNotIn("bidfinder_goods", [call[0] for call in client.import_calls])
        self.assertNotIn("source_key", client.import_calls[0][1][0])

    def test_partial_batch_stops_partition_and_returns_rejection(self):
        client = FakeTypesenseClient(results=[ImportResult(2, 1, 1, ("bad field",), TYPESENSE_PARTIAL_IMPORT)])
        sink = TypesenseSink(client, "dev1", batch_size=2)
        contract = SOURCE_CONTRACTS["goods_general"]
        canonical = normalize_record(contract, _sample("goods_general"), "2026-08-28")
        context = PartitionContext("goods_general", "2026-08-28", contract, official_day_interval("2026-08-28"), 2, 2, 2, 2, 2, 1)
        result = sink.write_partition(context, [canonical, {**canonical, "id": "second"}])
        self.assertEqual(TYPESENSE_PARTIAL_IMPORT, result.error_code)
        self.assertGreater(result.rejected_count, 0)
        self.assertEqual(1, len(client.import_calls))

    def test_source_union_rejects_cross_group_uuid(self):
        first = {"id": "same", "data_group": "goods", "source_key": "goods_general"}
        second = {"id": "same", "data_group": "medicines", "source_key": "medicine_generic"}
        with self.assertRaises(TypesenseError) as raised:
            validate_identity_union(([first], [second]))
        self.assertEqual(TYPESENSE_IDENTITY_CONFLICT, raised.exception.code)


class LifecycleTest(unittest.TestCase):
    def test_create_validate_activate_and_noop(self):
        class Admin:
            def __init__(self):
                self.collections = {}
                self.aliases = {}

            def get_collection(self, name):
                return self.collections.get(name)

            def create_collection(self, schema):
                self.collections[schema["name"]] = schema
                return schema

            def get_alias(self, alias):
                target = self.aliases.get(alias)
                return None if target is None else {"name": alias, "collection_name": target}

            def upsert_alias(self, alias, collection):
                self.aliases[alias] = collection
                return {"name": alias, "collection_name": collection}

            def list_aliases(self):
                return [{"name": alias, "collection_name": target} for alias, target in self.aliases.items()]

        client = Admin()
        manager = TypesenseCollectionManager(client)
        manager.create_generation("dev1")
        self.assertEqual(3, len(client.collections))
        self.assertEqual(3, len(manager.validate_generation("dev1")))
        manager.create_generation("dev1")
        activated = manager.activate_generation("dev1")
        self.assertEqual(activated, client.aliases)
        self.assertEqual("bidfinder_goods_v1_dev1", client.aliases["bidfinder_goods"])

    def test_incompatible_existing_collection_fails_closed(self):
        class Admin:
            def __init__(self):
                self.collection = collection_schema("goods", "dev1")

            def get_collection(self, name):
                if name == self.collection["name"]:
                    return {**self.collection, "fields": [{"name": "id", "type": "int32"}]}
                return None

            def create_collection(self, schema):
                raise AssertionError("must not create over incompatible collection")

        with self.assertRaises(TypesenseError):
            TypesenseCollectionManager(Admin()).create_generation("dev1")

    def test_typesense_implicit_id_field_is_compatible(self):
        class Admin:
            def __init__(self):
                expected = collection_schema("goods", "dev1")
                self.collections = {
                    expected["name"]: {
                        **expected,
                        "fields": [field for field in expected["fields"] if field["name"] != "id"],
                    }
                }

            def get_collection(self, name):
                return self.collections.get(name)

            def create_collection(self, schema):
                self.collections[schema["name"]] = schema
                return schema

        created = TypesenseCollectionManager(Admin()).create_generation("dev1")
        self.assertEqual(3, len(created))


class CheckpointGenerationTest(unittest.TestCase):
    def test_phase2_rows_migrate_and_typesense_target_is_distinct(self):
        with self.subTest("legacy migration"):
            path = ROOT / "tests" / "msc" / "_checkpoint_migration_test.sqlite3"
            try:
                connection = sqlite3.connect(path)
                connection.execute("CREATE TABLE ingestion_checkpoint (source_key TEXT NOT NULL, partition_date TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, parent_pre_count INTEGER, parent_post_count INTEGER, raw_fetched_count INTEGER, unique_uuid_count INTEGER, normalized_count INTEGER, sink_accepted_count INTEGER, started_at TEXT, completed_at TEXT, last_error_code TEXT, last_error_message TEXT, engine_version TEXT NOT NULL, schema_version TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(source_key, partition_date))")
                connection.execute("INSERT INTO ingestion_checkpoint VALUES ('goods_general','2026-08-28','COMPLETED',1,2,2,2,2,2,2,NULL,'now',NULL,NULL,'old-engine','old-schema','now')")
                connection.commit()
                connection.close()
                with CheckpointStore(path) as store:
                    self.assertEqual("COMPLETED", store.get("goods_general", "2026-08-28").status.value)
                    self.assertIsNone(store.get("goods_general", "2026-08-28", "typesense:dev1"))
                    store.start("goods_general", "2026-08-28", sink_target="typesense:dev1")
                    self.assertEqual("typesense:dev1", store.get("goods_general", "2026-08-28", "typesense:dev1").sink_target)
            finally:
                if path.exists():
                    path.unlink()

    def test_engine_completion_is_generation_specific(self):
        contract = SOURCE_CONTRACTS["goods_general"]
        raw = _sample("goods_general")

        class Client:
            config = MSCConfig(request_delay_seconds=0)

            def __init__(self):
                self.stats = type("Stats", (), {"request_count": 0, "retry_count": 0})()

            def count_interval(self, _contract, _interval):
                self.stats.request_count += 1
                return 1

            def fetch_page(self, _contract, _interval, _page):
                self.stats.request_count += 1
                return {
                    "agg": [{"buckets": [{"docCount": 1}]}],
                    "page": {"content": [raw], "currentPage": 0, "pageSize": 1000, "totalElements": 1, "totalPages": 1},
                }

        class TargetSink:
            sink_target = "typesense:dev1"

            def write_partition(self, _context, records):
                return SinkWriteResult(len(records), len(records), 0, batch_count=1)

        with CheckpointStore(":memory:") as store:
            engine = MSCIngestionEngine(Client(), store, TargetSink())
            first = engine.ingest_partition("goods_general", "2026-08-28")
            second = engine.ingest_partition("goods_general", "2026-08-28")
            self.assertEqual(IngestionStatus.COMPLETED, first.status)
            self.assertTrue(second.skipped)
            self.assertEqual(IngestionStatus.COMPLETED, store.get("goods_general", "2026-08-28", "typesense:dev1").status)
            self.assertIsNone(store.get("goods_general", "2026-08-28"))


class SearchConfigTest(unittest.TestCase):
    def test_search_allow_lists_are_conservative(self):
        self.assertIn("source_tab", SEARCH_CONFIGS["goods"].filter_fields)
        self.assertIn("winning_unit_price", SEARCH_CONFIGS["goods"].sort_fields)
        TypesenseClient._validate_filter_fields("goods", "source_tab:=goods_general&&data_group:=goods")
        with self.assertRaises(ValueError):
            TypesenseClient._validate_filter_fields("goods", "source_key:=goods_general")
        with self.assertRaises(ValueError):
            TypesenseClient.__new__(TypesenseClient).multi_search_all("item", per_page=0)
        with self.assertRaises(ValueError):
            TypesenseConfig(api_key="dev-only", batch_size=0)
        self.assertNotIn("dev-only", repr(TypesenseConfig(api_key="dev-only")))

    def test_cli_exposes_explicit_generation_commands(self):
        parser = build_parser()
        admin_args = parser.parse_args(["typesense", "create-generation", "--generation", "dev1"])
        self.assertEqual("typesense", admin_args.operation)
        self.assertEqual("create-generation", admin_args.typesense_operation)
        crawl_args = parser.parse_args([
            "crawl", "--from", "2026-08-28", "--to", "2026-08-28",
            "--sources", "goods_general", "--sink", "typesense", "--generation", "dev1",
        ])
        self.assertEqual("typesense", crawl_args.sink)
        self.assertEqual("dev1", crawl_args.generation)


if __name__ == "__main__":
    unittest.main()
