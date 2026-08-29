import copy
import json
import unittest
from pathlib import Path

from tools.msc_search_pagination import (
    DEFAULT_SEARCH_PAGE_SIZE,
    MAX_SAFE_DAILY_RESULTS,
    SearchPaginationError,
    calculate_required_pages,
    validate_search_pages,
)


ROOT = Path(__file__).resolve().parents[2]


def response(count, page_number, page_size, ids, *, total_elements=None, total_pages=None):
    return {
        "agg": [{"buckets": [{"docCount": count}]}],
        "page": {
            "content": [{"id": value} for value in ids],
            "currentPage": page_number,
            "pageSize": page_size,
            "totalElements": count if total_elements is None else total_elements,
            "totalPages": (max(1, (count + page_size - 1) // page_size) if total_pages is None else total_pages),
        },
    }


class SearchPaginationTest(unittest.TestCase):
    def test_required_page_count_and_partial_last_page(self):
        self.assertEqual(0, calculate_required_pages(0, 1000))
        self.assertEqual(1, calculate_required_pages(1, 1000))
        self.assertEqual(2, calculate_required_pages(3, 2))
        self.assertEqual(3, calculate_required_pages(5, 2))

    def test_one_page_result(self):
        result = validate_search_pages(
            [response(2, 0, DEFAULT_SEARCH_PAGE_SIZE, ["one", "two"])],
        )
        self.assertEqual(2, result.expected_count)
        self.assertEqual(1, result.required_pages)
        self.assertEqual(("one", "two"), tuple(record["id"] for record in result.records))

    def test_multi_page_result_and_partial_last_page(self):
        result = validate_search_pages(
            [
                response(5, 0, 2, ["one", "two"]),
                response(5, 1, 2, ["three", "four"]),
                response(5, 2, 2, ["five"]),
            ],
            page_size=2,
        )
        self.assertEqual(3, result.required_pages)
        self.assertEqual(5, len(result.records))
        self.assertEqual(5, len(result.uuids))

    def test_zero_result_accepts_server_zero_total_pages(self):
        result = validate_search_pages([response(0, 0, 1, [], total_pages=0)], page_size=1)
        self.assertEqual(0, result.expected_count)
        self.assertEqual(0, result.required_pages)
        self.assertEqual((), result.records)

    def test_malformed_page_metadata_rejected(self):
        base = response(1, 0, 2, ["one"])
        for key in ("currentPage", "pageSize", "totalElements", "totalPages"):
            malformed = copy.deepcopy(base)
            malformed["page"].pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(SearchPaginationError, "metadata"):
                validate_search_pages([malformed], page_size=2)

        wrong_page = copy.deepcopy(base)
        wrong_page["page"]["currentPage"] = 1
        with self.assertRaisesRegex(SearchPaginationError, "currentPage"):
            validate_search_pages([wrong_page], page_size=2)

    def test_duplicate_uuid_within_and_across_pages_rejected(self):
        with self.assertRaisesRegex(SearchPaginationError, "duplicate UUID"):
            validate_search_pages([response(2, 0, 2, ["same", "same"])], page_size=2)
        with self.assertRaisesRegex(SearchPaginationError, "duplicate UUID"):
            validate_search_pages(
                [response(2, 0, 1, ["same"]), response(2, 1, 1, ["same"])],
                page_size=1,
            )

    def test_missing_page_and_count_mismatch_rejected(self):
        with self.assertRaisesRegex(SearchPaginationError, "missing page responses"):
            validate_search_pages([response(3, 0, 2, ["one", "two"])], page_size=2)
        with self.assertRaisesRegex(SearchPaginationError, "count mismatch"):
            validate_search_pages(
                [response(3, 0, 2, ["one"]), response(3, 1, 2, ["two"])],
                page_size=2,
            )

    def test_unsafe_expected_count_fails_closed(self):
        with self.assertRaisesRegex(SearchPaginationError, "safe daily threshold"):
            validate_search_pages(
                [response(MAX_SAFE_DAILY_RESULTS, 0, DEFAULT_SEARCH_PAGE_SIZE, [])],
            )

    def test_fixture_covers_all_seven_sources_without_secrets(self):
        fixture = json.loads(
            (ROOT / "docs" / "msc-contracts" / "search-only-validation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(7, len(fixture["partitions"]))
        self.assertEqual(
            {
                "goods-general",
                "medical-devices",
                "medicine-generic",
                "medicine-originator",
                "medicine-herbal",
                "herbal-material",
                "traditional-medicine",
            },
            {item["source"] for item in fixture["partitions"]},
        )
        for item in fixture["partitions"]:
            contract = json.loads(
                (ROOT / "docs" / "msc-contracts" / item["source"] / "contract.json").read_text(encoding="utf-8")
            )
            self.assertEqual("PASS", item["completeness"])
            self.assertEqual(200, item["http"])
            self.assertEqual(item["expected_count"], item["collected_row_count"])
            self.assertEqual(item["uuid_count"], item["unique_uuid_count"])
            self.assertEqual(0, item["duplicate_uuid_count"])
            self.assertEqual(0, item["page_overlap_uuid_count"])
            self.assertLess(item["expected_count"], fixture["max_safe_daily_results"])
            self.assertEqual(
                {mapping["canonical_key"] for mapping in contract["canonical_mapping"]},
                set(item["canonical_field_types"]),
            )
            for mapping in contract["canonical_mapping"]:
                source_field = mapping["source_field"]
                observed_type = item["canonical_field_types"][mapping["canonical_key"]]
                if source_field not in item["field_union"]:
                    self.assertTrue(observed_type.endswith("ABSENT_IN_SAMPLE"), mapping["canonical_key"])
            self.assertTrue(all(":" in value for value in item["canonical_field_types"].values()))

        self.assertEqual(
            [
                "goods-general.model",
                "goods-general.registration_or_import_permit_number",
                "herbal-material.bidder_count",
            ],
            fixture["field_parity_summary"]["unknown_without_a_stable_mapping"],
        )
        self.assertEqual([], fixture["field_parity_summary"]["not_available_in_search"])


if __name__ == "__main__":
    unittest.main()
