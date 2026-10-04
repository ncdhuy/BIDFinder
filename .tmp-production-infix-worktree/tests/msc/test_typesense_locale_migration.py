from __future__ import annotations

import inspect
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crawler_engine.msc.exception_ledger import exception_rows
from crawler_engine.msc.typesense_client import ImportResult
from crawler_engine.msc.typesense_schema import SEARCH_CONFIGS, collection_schema, physical_collection_name
from tools.migrate_typesense_vietnamese_locale import (
    _cutover_runtime,
    _final_schema,
    _import_group,
    _locale_status,
    _migrate_legacy_document,
)


def source_schema(group: str) -> dict:
    schema = collection_schema(group, "source")
    schema["name"] = physical_collection_name(group, "source")
    schema["fields"] = [{key: value for key, value in field.items() if key != "locale"} for field in schema["fields"]]
    schema["num_documents"] = 0
    return schema


class FakeClient:
    def __init__(self, group: str, documents: list[dict]):
        source = source_schema(group)
        source["num_documents"] = len(documents)
        self.collections = {source["name"]: source}
        self.documents = {source["name"]: documents}
        self.import_calls = 0

    def get_collection(self, name):
        return self.collections.get(name)

    def create_collection(self, schema):
        target = dict(schema)
        target["num_documents"] = 0
        self.collections[target["name"]] = target
        self.documents[target["name"]] = []
        return target

    def export_documents(self, name, *, timeout_seconds=None):
        yield from self.documents[name]

    def import_documents(self, name, documents, *, timeout_seconds=None):
        self.import_calls += 1
        self.documents[name].extend(dict(document) for document in documents)
        self.collections[name]["num_documents"] = len(self.documents[name])
        return ImportResult(len(documents), len(documents), 0)

    def document_count(self, name):
        return int(self.collections[name]["num_documents"])

    def get_document(self, name, document_id):
        return next((document for document in self.documents[name] if document["id"] == document_id), None)


class RejectingClient(FakeClient):
    def import_documents(self, name, documents, *, timeout_seconds=None):
        self.import_calls += 1
        return ImportResult(len(documents), 0, len(documents), ("forced rejection",), "TYPESENSE_PARTIAL_IMPORT")


class VietnameseLocaleMigrationTest(unittest.TestCase):
    def test_final_schema_localizes_search_fields_only(self):
        source = source_schema("goods")
        for field in source["fields"]:
            if field["name"] == "production_year":
                field["type"] = "int32"
        final = _final_schema("goods", "target", source)
        status = _locale_status("goods", final)

        self.assertTrue(status["ok"])
        self.assertEqual(set(SEARCH_CONFIGS["goods"].query_by), set(status["localized_fields"]))
        fields = {field["name"]: field for field in final["fields"]}
        self.assertEqual("string", fields["production_year"]["type"])
        self.assertEqual("msc-source-schema-v1", final["metadata"]["schema_version"])
        self.assertNotIn("locale", fields["production_year"])
        self.assertNotIn("locale", fields["partition_date"])
        self.assertEqual("vi", fields["item_name"]["locale"])
        self.assertEqual(source["fields"][0]["type"], fields[source["fields"][0]["name"]]["type"])

    def test_import_is_sequential_and_idempotent(self):
        group = "goods"
        source = physical_collection_name(group, "source")
        target = physical_collection_name(group, "target")
        documents = [{"id": f"id-{index}", "data_group": group} for index in range(5)]
        client = FakeClient(group, documents)
        with tempfile.TemporaryDirectory() as temporary:
            first = _import_group(
                client, group, source, target, "target", checkpoint_dir=Path(temporary),
                batch_size=2, operation_timeout_seconds=60, progress_every=100,
            )
            calls_after_first = client.import_calls
            second = _import_group(
                client, group, source, target, "target", checkpoint_dir=Path(temporary),
                batch_size=2, operation_timeout_seconds=60, progress_every=100,
            )

        self.assertEqual(5, first["target_documents"])
        self.assertEqual("skip-complete", second["action"])
        self.assertEqual(calls_after_first, client.import_calls)

    def test_failed_batch_records_every_source_id_in_exception_ledger(self):
        group = "goods"
        source = physical_collection_name(group, "source")
        target = physical_collection_name(group, "target")
        documents = [{"id": f"id-{index}", "data_group": group} for index in range(3)]
        client = RejectingClient(group, documents)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                _import_group(
                    client, group, source, target, "target", checkpoint_dir=Path(temporary),
                    batch_size=2, operation_timeout_seconds=60, progress_every=100,
                )
            ledger_path = Path(temporary) / "exception-ledger.sqlite3"
            connection = sqlite3.connect(ledger_path)
            try:
                rows = exception_rows(connection, "migration:target")
            finally:
                connection.close()

        self.assertEqual({"id-0", "id-1"}, {row["source_id"] for row in rows})
        self.assertEqual({"goods"}, {row["logical_group"] for row in rows})
        self.assertEqual({"import_rejected"}, {row["category"] for row in rows})

    def test_legacy_document_migration_preserves_values_and_keys(self):
        document = {
            "id": "id-1",
            "production_year": 2024,
            "bidder_count": 2.333,
            "location": "Việt Nam",
        }
        migrated = _migrate_legacy_document("goods", document)

        self.assertEqual(set(document), set(migrated))
        self.assertEqual("2024", migrated["production_year"])
        self.assertEqual(2.333, migrated["bidder_count"])
        integer_count = _migrate_legacy_document("goods", {"id": "id-2", "bidder_count": 2})["bidder_count"]
        self.assertEqual(2.0, integer_count)
        self.assertIsInstance(integer_count, float)
        self.assertEqual(document["location"], migrated["location"])

    def test_cutover_updates_generation_bound_runtime_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.env"
            path.write_text(
                "BIDFINDER_SERVING_GENERATION=old\n"
                "BIDFINDER_TYPESENSE_SERVING_GENERATION=old\n"
                "BIDFINDER_TYPESENSE_CHECKPOINT=/tmp/old.sqlite3\n",
                encoding="utf-8",
            )
            self.assertEqual("old", _cutover_runtime(path, "new"))
            text = path.read_text(encoding="utf-8")

        self.assertNotIn("old", text)
        self.assertIn("BIDFINDER_TYPESENSE_CHECKPOINT=/tmp/new.sqlite3", text)
        self.assertIn("BIDFINDER_SERVING_GENERATION=new", text)

    def test_migration_tool_has_no_clone_or_schema_patch_path(self):
        source = inspect.getsource(_import_group)
        module_source = Path("tools/migrate_typesense_vietnamese_locale.py").read_text(encoding="utf-8")
        self.assertNotIn("clone_collection", source)
        self.assertNotIn("update_collection_schema", source)
        self.assertNotIn("\"PATCH\"", module_source)


if __name__ == "__main__":
    unittest.main()
