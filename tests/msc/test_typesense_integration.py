"""Optional local Typesense 30.2 proof; never part of normal CI."""

from __future__ import annotations

import os
from pathlib import Path
import json
import unittest

from crawler_engine.msc.config import TypesenseConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.models import PartitionContext
from crawler_engine.msc.normalize import normalize_record
from crawler_engine.msc.partitioning import official_day_interval
from crawler_engine.msc.sink import TypesenseSink
from crawler_engine.msc.typesense_client import TypesenseClient, TypesenseCollectionManager, validate_identity_union
from crawler_engine.msc.typesense_schema import LOGICAL_ALIASES, canonical_to_typesense_document, physical_collection_name


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


@unittest.skipUnless(os.getenv("TYPESENSE_INTEGRATION_TEST") == "1", "set TYPESENSE_INTEGRATION_TEST=1")
class TypesenseIntegrationTest(unittest.TestCase):
    def test_fixture_import_upsert_alias_and_multi_search(self):
        config = TypesenseConfig.from_env()
        client = TypesenseClient(config)
        manager = TypesenseCollectionManager(client)
        generation = f"it_{os.getpid()}"
        created: list[str] = []
        previous_aliases = {alias: client.get_alias(alias) for alias in LOGICAL_ALIASES.values()}
        for group in LOGICAL_ALIASES:
            name = physical_collection_name(group, generation)
            if client.get_collection(name) is None:
                created.append(name)
        try:
            manager.create_generation(generation)
            grouped: dict[str, list[dict]] = {group: [] for group in LOGICAL_ALIASES}
            for source_key, slug in CONTRACT_MAP.items():
                contract = SOURCE_CONTRACTS[source_key]
                payload = json.loads((ROOT / "docs" / "msc-contracts" / slug / "search-response-sample.json").read_text(encoding="utf-8"))
                canonical = normalize_record(contract, payload["page"]["content"][0], "2026-08-28")
                validate_identity_union((grouped[contract.data_group], [canonical]))
                grouped[contract.data_group].append(canonical)
            for group, records in grouped.items():
                source_key = records[0]["source_key"]
                contract = SOURCE_CONTRACTS[source_key]
                context = PartitionContext(source_key, "2026-08-28", contract, official_day_interval("2026-08-28"), len(records), len(records), len(records), len(records), len(records), 1)
                result = TypesenseSink(client, generation, batch_size=2).write_partition(context, records)
                self.assertEqual((len(records), len(records), 0), (result.attempted_count, result.accepted_count, result.rejected_count))
            before = {group: client.document_count(physical_collection_name(group, generation)) for group in LOGICAL_ALIASES}
            goods = grouped["goods"][0]
            contract = SOURCE_CONTRACTS[goods["source_key"]]
            context = PartitionContext(goods["source_key"], "2026-08-28", contract, official_day_interval("2026-08-28"), 1, 1, 1, 1, 1, 1)
            rerun = TypesenseSink(client, generation, batch_size=2).write_partition(context, [goods])
            after = {group: client.document_count(physical_collection_name(group, generation)) for group in LOGICAL_ALIASES}
            self.assertEqual((1, 1, 0), (rerun.attempted_count, rerun.accepted_count, rerun.rejected_count))
            self.assertEqual(before, after)
            manager.activate_generation(generation)
            for group, records in grouped.items():
                document = client.get_document(LOGICAL_ALIASES[group], records[0]["id"])
                self.assertEqual(records[0]["id"], document["id"])
                self.assertTrue(client.search_group(group, "*", per_page=1)["found"] >= 1)
            self.assertEqual(3, len(client.multi_search_all("*", per_page=1)["results"]))
        finally:
            for alias, previous in previous_aliases.items():
                if previous and previous.get("collection_name"):
                    client.upsert_alias(alias, previous["collection_name"])
                else:
                    client.delete_alias(alias)
            for name in created:
                client.delete_collection(name)


if __name__ == "__main__":
    unittest.main()
