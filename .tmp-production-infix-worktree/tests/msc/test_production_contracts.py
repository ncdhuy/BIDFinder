from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import unittest

from crawler_engine.msc.client import build_search_request
from crawler_engine.msc.config import MSC_SEARCH_ENDPOINT, SEARCH_PAGE_SIZE
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.partitioning import official_day_interval


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


class ProductionContractTest(unittest.TestCase):
    def test_registry_has_exactly_seven_verified_fixtures(self):
        self.assertEqual(set(CONTRACT_MAP), set(SOURCE_CONTRACTS))
        for source_key, slug in CONTRACT_MAP.items():
            contract = SOURCE_CONTRACTS[source_key]
            fixture = json.loads((ROOT / "docs" / "msc-contracts" / slug / "contract.json").read_text(encoding="utf-8"))
            self.assertEqual("VERIFIED", fixture["contract_evidence_status"])
            self.assertEqual(fixture["source_tab_label"], contract.source_tab_label)
            self.assertEqual(fixture["data_group"], contract.data_group)
            self.assertEqual(fixture["source_tab"], contract.source_tab)
            self.assertEqual(fixture["type"], contract.type)
            self.assertEqual(fixture["tab"], contract.tab)
            self.assertEqual(tuple(fixture["match_fields"]), contract.match_fields)
            self.assertEqual(fixture["fixed_filters"], [item.to_dict() for item in contract.fixed_filters])
            self.assertEqual(tuple(fixture["special_filters"]), contract.special_filters)
            self.assertEqual(tuple(fixture["observed_source_field_names"]), contract.observed_source_fields)
            self.assertEqual(slug, contract.fixture_slug)
            self.assertEqual(
                fixture["canonical_mapping"],
                [asdict(item) for item in contract.canonical_mapping],
            )

    def test_request_builder_matches_sanitized_fixture_shape(self):
        for source_key, slug in CONTRACT_MAP.items():
            contract = SOURCE_CONTRACTS[source_key]
            fixture = json.loads((ROOT / "docs" / "msc-contracts" / slug / "search-request.json").read_text(encoding="utf-8"))
            query = fixture[0]["query"][0]
            actual = build_search_request(
                contract,
                query["filters"][0]["from"],
                query["filters"][0]["to"],
                fixture[0]["pageNumber"],
                fixture[0]["pageSize"],
                keyword=query["keyWord"],
                keyword_not_match=query["keyWordNotMatch"],
            )
            self.assertEqual(fixture, actual, source_key)
            self.assertEqual(MSC_SEARCH_ENDPOINT, "https://muasamcong.mpi.gov.vn/o/egp-portal-winning-bid-data/services/smart/search_prc")

    def test_official_day_keeps_frozen_end_millisecond(self):
        interval = official_day_interval("2026-08-28")
        self.assertEqual("2026-08-28T00:00:00.000Z", interval.from_value)
        self.assertEqual("2026-08-28T23:59:59.059Z", interval.to_value)
        self.assertEqual(1000, SEARCH_PAGE_SIZE)


if __name__ == "__main__":
    unittest.main()
