import json
import re
import unittest
from pathlib import Path

from tools.msc_contract_probe import (
    ALLOWED_ENDPOINTS,
    ContractProbeError,
    EXPORT_CEILING,
    check_completeness,
    detect_duplicate_ids,
    parse_export_records,
    parse_search_count,
    parse_search_records,
    payload_date_range,
    validate_payload,
    with_date_range,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "docs" / "msc-contracts"
SOURCE_DIRS = (
    "goods-general",
    "medical-devices",
    "medicine-generic",
    "medicine-originator",
    "medicine-herbal",
    "herbal-material",
    "traditional-medicine",
)
REQUIRED_FILES = (
    "contract.json",
    "search-request.json",
    "search-response-sample.json",
    "export-request.json",
    "export-response-sample.json",
)
SECRET_RE = re.compile(
    rb"(?:cookie\s*:|set-cookie|jsessionid|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]+|session[_ -]?token\s*[:=]|password\s*[:=]|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


class ContractFixtureTest(unittest.TestCase):
    def test_fixture_structure_and_mapping_completeness(self):
        self.assertTrue((FIXTURE_ROOT / "README.md").is_file())
        expected_keys = {
            "id",
            "source_tab",
            "source_tab_label",
            "data_group",
            "partition_date",
        }
        group_keys = {
            "goods": {
                "item_name",
                "unit",
                "quantity",
                "country_of_origin",
                "hs_code",
                "model_mark",
                "brand",
                "production_year",
                "manufacturer",
                "technical_specification",
                "winning_unit_price",
                "winning_bidder_id",
                "winning_bidder_name",
                "bid_invitation_code",
                "procuring_entity_id",
                "procuring_entity_name",
                "selection_method",
                "result_posted_at",
                "decision_number",
                "decision_issued_at",
                "bidder_count",
                "location",
            },
            "medicines": {
                "medicine_name",
                "active_ingredient_or_herbal_component",
                "strength",
                "marketing_authorization_or_import_permit",
                "route_of_administration",
                "dosage_form",
                "shelf_life",
                "manufacturer",
                "production_country",
                "packaging",
                "unit",
                "quantity",
                "winning_unit_price",
                "winning_bidder_id",
                "winning_bidder_name",
                "medicine_group",
                "bid_invitation_code",
                "procuring_entity_id",
                "procuring_entity_name",
                "selection_method",
                "result_posted_at",
                "decision_number",
                "decision_issued_at",
                "bidder_count",
                "location",
            },
            "traditional_medicine": {
                "item_name",
                "used_part",
                "scientific_name",
                "origin",
                "processing_method",
                "registration_or_import_permit_number",
                "manufacturer",
                "production_country",
                "packaging",
                "unit",
                "quantity",
                "winning_unit_price",
                "winning_bidder_id",
                "winning_bidder_name",
                "technical_group",
                "bid_invitation_code",
                "procuring_entity_id",
                "procuring_entity_name",
                "selection_method",
                "result_posted_at",
                "decision_number",
                "decision_issued_at",
                "bidder_count",
                "location",
            },
        }
        expected_discriminators = {
            "goods-general": ("HANG_HOA", "HANG_HOA", []),
            "medical-devices": ("HANG_HOA", "THIET_BI_VAT_TU_Y_TE", []),
            "medicine-generic": ("HANG_HOA", "THUOC_TAN_DUOC", ["0"]),
            "medicine-originator": ("HANG_HOA", "THUOC_TAN_DUOC", ["1"]),
            "medicine-herbal": ("HANG_HOA", "THUOC_TAN_DUOC", ["2"]),
            "herbal-material": ("HANG_HOA", "DUOC_LIEU", [0, None]),
            "traditional-medicine": ("HANG_HOA", "VI_THUOC_CO_TRUYEN", [0, None]),
        }
        for slug in SOURCE_DIRS:
            directory = FIXTURE_ROOT / slug
            self.assertTrue(directory.is_dir(), slug)
            for filename in REQUIRED_FILES:
                self.assertTrue((directory / filename).is_file(), f"{slug}/{filename}")
            contract = json.loads((directory / "contract.json").read_text(encoding="utf-8"))
            self.assertEqual("VERIFIED", contract["contract_evidence_status"])
            self.assertEqual(["page", "agg"], contract["search_envelope_keys"])
            self.assertEqual(["resultList"], contract["export_envelope_keys"])
            expected_type, expected_tab, expected_special = expected_discriminators[slug]
            self.assertEqual(expected_type, contract["type"])
            self.assertEqual(expected_tab, contract["tab"])
            filters = {item["fieldName"]: item["fieldValues"] for item in contract["fixed_filters"]}
            self.assertEqual([expected_type], filters["type"])
            self.assertEqual([expected_tab], filters["tab"])
            if expected_special:
                special_field = "medicines" if slug.startswith("medicine-") else "medicine_type"
                self.assertEqual(expected_special, filters[special_field])
            self.assertEqual(
                {"search_zero_result", "search_nonzero_result", "export_zero_result", "export_nonzero_result", "relevant_errors"},
                set(contract["response_behavior"]),
            )
            self.assertEqual({"http", "docCount", "page_content_length", "keyword"}, set(contract["zero_result_evidence"]))
            self.assertEqual(0, contract["zero_result_evidence"]["docCount"])
            self.assertIn(contract["data_group"], group_keys)
            self.assertEqual(expected_keys, set(contract["provenance_fields"]))
            mapped = {item["canonical_key"] for item in contract["canonical_mapping"]}
            self.assertTrue(group_keys[contract["data_group"]].issubset(mapped), slug)
            search_request = json.loads((directory / "search-request.json").read_text(encoding="utf-8"))
            export_request = json.loads((directory / "export-request.json").read_text(encoding="utf-8"))
            validate_payload(search_request)
            validate_payload(export_request)
            search_response = json.loads((directory / "search-response-sample.json").read_text(encoding="utf-8"))
            export_response = json.loads((directory / "export-response-sample.json").read_text(encoding="utf-8"))
            search_records = parse_search_records(search_response)
            self.assertEqual(1, len(search_records))
            self.assertEqual(1, len(parse_export_records(export_response)))
            self.assertGreater(parse_search_count(search_response), 0)
            query = search_request[0]["query"][0]
            self.assertEqual(contract["match_fields"], query["matchFields"])
            request_filters = {
                (item["fieldName"], json.dumps(item["fieldValues"], sort_keys=True))
                for item in query["filters"]
                if "fieldValues" in item
            }
            for item in contract["fixed_filters"]:
                self.assertIn((item["fieldName"], json.dumps(item["fieldValues"], sort_keys=True)), request_filters)
            self.assertTrue(set(search_records[0]).issubset(set(contract["observed_source_field_names"])))

    def test_fixture_tree_has_no_obvious_session_material(self):
        for path in FIXTURE_ROOT.rglob("*"):
            if path.is_file():
                self.assertIsNone(SECRET_RE.search(path.read_bytes()), str(path))


class ContractParserTest(unittest.TestCase):
    def test_endpoint_allow_list_is_fixed(self):
        self.assertEqual(1, len(ALLOWED_ENDPOINTS))
        self.assertTrue(all(endpoint.startswith("https://muasamcong.mpi.gov.vn/") for endpoint in ALLOWED_ENDPOINTS))

    def test_aggregation_and_export_parsers(self):
        response = {"agg": [{"buckets": [{"docCount": 2}]}], "page": {"content": [{"id": "a"}]}}
        self.assertEqual(2, parse_search_count(response))
        self.assertEqual([{"id": "a"}], parse_search_records(response))
        # Historical export shape stays parser-tested offline; probe never calls it.
        self.assertEqual([{"id": "a"}], parse_export_records({"resultList": [{"id": "a"}]}))

    def test_malformed_response_rejected(self):
        with self.assertRaises(ContractProbeError):
            parse_search_count({"agg": []})
        with self.assertRaises(ContractProbeError):
            parse_search_records({"page": {"content": {}}})
        with self.assertRaises(ContractProbeError):
            parse_export_records({"resultList": None})

    def test_completeness_mismatch_and_ceiling_fail_closed(self):
        self.assertEqual("PASS: expected=2 export=2", check_completeness(2, 2))
        self.assertIn("count mismatch", check_completeness(2, 1))
        self.assertIn(str(EXPORT_CEILING), check_completeness(EXPORT_CEILING, 0))

    def test_duplicate_uuid_detection(self):
        self.assertEqual(["same"], detect_duplicate_ids([{"id": "same"}, {"id": "same"}]))
        self.assertEqual([], detect_duplicate_ids([{"id": "one"}, {"id": None}, {}]))

    def test_date_override_preserves_official_millisecond_bounds(self):
        payload = [{"pageSize": 1, "pageNumber": 0, "query": [{
            "index": "es-smart-pricing", "keyWord": "", "keyWordNotMatch": "",
            "matchType": "all-1", "matchFields": [], "filters": []
        }]}]
        updated = with_date_range(payload, "2026-08-28T00:00:00.000Z", "2026-08-28T23:59:59.059Z")
        self.assertEqual(
            "2026-08-28T00:00:00.000Z..2026-08-28T23:59:59.059Z",
            payload_date_range(updated),
        )

    def test_sample_uuid_sets_are_distinct_across_source_tabs(self):
        ids = []
        for slug in SOURCE_DIRS:
            response = json.loads((FIXTURE_ROOT / slug / "search-response-sample.json").read_text(encoding="utf-8"))
            ids.append(parse_search_records(response)[0]["id"])
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
