from __future__ import annotations

import copy
from datetime import date, timedelta
from io import BytesIO
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from crawler_engine.msc.checkpoint import CheckpointStore
from crawler_engine.msc.client import MSCClient, MSCHttpError, MSCResponseError
from crawler_engine.msc.config import MSCConfig
from crawler_engine.msc.contracts import SOURCE_CONTRACTS
from crawler_engine.msc.engine import MSCIngestionEngine
from crawler_engine.msc.models import IngestionStatus, PartitionContext, SearchInterval, SinkWriteResult
from crawler_engine.msc.normalize import NormalizationError, normalize_record, normalize_records
from crawler_engine.msc.partitioning import PartitioningError, official_day_interval, plan_partition, split_search_interval
from crawler_engine.msc.sink import InMemorySink, JsonlValidationSink
from crawler_engine.msc.validation import (
    ValidationError,
    calculate_required_pages,
    union_partition_records,
    validate_parent_completeness,
    validate_raw_records,
    validate_search_pages,
)


ROOT = Path(__file__).resolve().parents[2]


def response(count: int, records: list[dict], page_number: int = 0, page_size: int = 1000, *, total_pages: int | None = None):
    return {
        "agg": [{"buckets": [{"docCount": count}]}],
        "page": {
            "content": records,
            "currentPage": page_number,
            "pageSize": page_size,
            "totalElements": count,
            "totalPages": total_pages if total_pages is not None else (1 if count else 0),
        },
    }


def sample(source_key: str) -> dict:
    slug = SOURCE_CONTRACTS[source_key].fixture_slug
    payload = json.loads((ROOT / "docs" / "msc-contracts" / slug / "search-response-sample.json").read_text(encoding="utf-8"))
    return payload["page"]["content"][0]


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(status: int) -> HTTPError:
    return HTTPError("https://example.invalid", status, "test", {}, BytesIO(b"error"))


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.contract = SOURCE_CONTRACTS["goods_general"]
        self.interval = official_day_interval("2026-08-25")

    def test_timeout_is_forwarded_and_payload_is_public_search_only(self):
        opener = FakeOpener([FakeResponse(response(0, []))])
        client = MSCClient(MSCConfig(timeout_seconds=7, request_delay_seconds=0), opener=opener)
        client.fetch_page(self.contract, self.interval, 0)
        self.assertEqual(7, opener.requests[0][1])
        request = opener.requests[0][0]
        self.assertEqual("POST", request.method)
        self.assertTrue(request.full_url.endswith("/search_prc"))
        self.assertNotIn("export", request.full_url)

    def test_429_and_5xx_retry_with_bounded_backoff(self):
        opener = FakeOpener([http_error(429), http_error(503), FakeResponse(response(0, []))])
        sleeps = []
        client = MSCClient(
            MSCConfig(request_delay_seconds=0, retry_backoff_seconds=0.25, max_retries=2),
            opener=opener,
            sleep=sleeps.append,
        )
        self.assertEqual(0, client.count_interval(self.contract, self.interval))
        self.assertEqual(3, client.stats.request_count)
        self.assertEqual(2, client.stats.retry_count)
        self.assertEqual([0.25, 0.5], sleeps)

    def test_network_failure_retries_but_400_does_not(self):
        opener = FakeOpener([http_error(400)])
        client = MSCClient(MSCConfig(request_delay_seconds=0), opener=opener, sleep=lambda _: None)
        with self.assertRaises(MSCHttpError) as caught:
            client.fetch_page(self.contract, self.interval, 0)
        self.assertEqual(400, caught.exception.status)
        self.assertEqual(1, client.stats.request_count)

        opener = FakeOpener([OSError("offline"), FakeResponse(response(0, []))])
        client = MSCClient(MSCConfig(request_delay_seconds=0, retry_backoff_seconds=0), opener=opener, sleep=lambda _: None)
        self.assertEqual(0, client.count_interval(self.contract, self.interval))
        self.assertEqual(2, client.stats.request_count)

        opener = FakeOpener([IncompleteRead(b"partial", 5), FakeResponse(response(0, []))])
        client = MSCClient(MSCConfig(request_delay_seconds=0, retry_backoff_seconds=0), opener=opener, sleep=lambda _: None)
        self.assertEqual(0, client.count_interval(self.contract, self.interval))
        self.assertEqual(2, client.stats.request_count)

    def test_malformed_json_and_aggregation_fail(self):
        class BadResponse(FakeResponse):
            def read(self):
                return b"not-json"

        client = MSCClient(MSCConfig(request_delay_seconds=0), opener=FakeOpener([BadResponse({})]))
        with self.assertRaises(MSCResponseError):
            client.fetch_page(self.contract, self.interval, 0)
        client = MSCClient(MSCConfig(request_delay_seconds=0), opener=FakeOpener([FakeResponse({"page": {}})]))
        with self.assertRaises(ValidationError):
            client.count_interval(self.contract, self.interval)


class PartitionAndValidationTest(unittest.TestCase):
    def test_safe_overflow_recursive_minimum_depth_and_deficit(self):
        parent = official_day_interval("2026-08-28")
        safe = plan_partition(parent, lambda _: 9500)
        self.assertEqual((9500,), tuple(leaf.expected_count for leaf in safe.safe_leaves))

        two_level = plan_partition(
            parent,
            lambda interval: 20_000 if interval.depth == 0 else (10_000 if interval.depth == 1 else 5_000),
        )
        self.assertEqual(4, len(two_level.safe_leaves))
        self.assertTrue(all(leaf.expected_count == 5000 for leaf in two_level.safe_leaves))
        self.assertGreaterEqual(len(two_level.diagnostics), 3)

        with self.assertRaises(PartitioningError):
            plan_partition(parent, lambda _: 9501, config=MSCConfig(max_partition_depth=0))
        with self.assertRaises(PartitioningError):
            split_search_interval(
                SearchInterval("2026-08-28T00:00:00.000Z", "2026-08-28T00:00:00.001Z"),
                overlap=timedelta(seconds=1),
            )
        with self.assertRaises(PartitioningError):
            plan_partition(parent, lambda interval: 10_000 if interval.depth == 0 else 0)

    def test_split_has_deterministic_one_second_overlap(self):
        left, right = split_search_interval(official_day_interval("2026-08-28"))
        self.assertEqual("2026-08-28T00:00:00.000Z", left.from_value)
        self.assertEqual("2026-08-28T11:59:59.529Z", right.from_value)
        self.assertEqual("2026-08-28T12:00:00.529Z", left.to_value)
        self.assertEqual("2026-08-28T23:59:59.059Z", right.to_value)

    def test_pagination_single_multiple_last_partial_and_failures(self):
        one = [{"id": "1", "name": "one"}]
        result = validate_search_pages([response(1, one)])
        self.assertEqual((one[0],), result.records)
        self.assertEqual((1, 1), (result.expected_count, result.required_pages))
        many = [{"id": str(i)} for i in range(1001)]
        first = response(1001, many[:1000], total_pages=2)
        second = response(1001, many[1000:], page_number=1, total_pages=2)
        result = validate_search_pages([first, second])
        self.assertEqual((1001, 2), (len(result.records), result.required_pages))
        self.assertEqual(2, calculate_required_pages(1001))
        with self.assertRaises(ValidationError):
            validate_search_pages([response(2, [{"id": "1"}])])
        with self.assertRaises(ValidationError):
            validate_search_pages([response(2, [{"id": "1"}, {"id": "1"}])])

    def test_union_allows_boundary_duplicate_but_rejects_conflict_and_nonoverlap(self):
        a = {"id": "same", "value": 1}
        left = SearchInterval("2026-08-28T00:00:00.000Z", "2026-08-28T12:00:01.000Z")
        right = SearchInterval("2026-08-28T12:00:00.000Z", "2026-08-28T23:59:59.059Z")
        result = union_partition_records([[a], [a, {"id": "two"}]], expected_count=2, leaf_intervals=[left, right])
        self.assertEqual(1, result.duplicate_uuid_occurrences)
        with self.assertRaises(ValidationError):
            union_partition_records([[a], [{"id": "same", "value": 2}]], expected_count=1, leaf_intervals=[left, right])
        far = SearchInterval("2026-08-29T00:00:00.000Z", "2026-08-29T01:00:00.000Z")
        with self.assertRaises(ValidationError):
            union_partition_records([[a], [a]], expected_count=1, leaf_intervals=[left, far])
        with self.assertRaises(ValidationError):
            validate_parent_completeness(2, 2, 1)


class NormalizationTest(unittest.TestCase):
    def test_all_seven_sources_normalize_to_expected_groups(self):
        expected_groups = {
            "goods_general": "goods", "medical_devices": "goods",
            "medicine_generic": "medicines", "medicine_originator": "medicines", "medicine_herbal": "medicines",
            "herbal_material": "traditional_medicine", "traditional_medicine": "traditional_medicine",
        }
        for source_key, group in expected_groups.items():
            contract = SOURCE_CONTRACTS[source_key]
            raw = sample(source_key)
            normalized = normalize_record(contract, raw, "2026-08-28")
            self.assertEqual(group, normalized["data_group"])
            self.assertEqual(source_key, normalized["source_key"])
            self.assertEqual(contract.source_tab, normalized["source_tab"])
            self.assertEqual(set(contract.canonical_keys) | {"id", "data_group", "source_key", "source_tab", "source_tab_label", "partition_date"}, set(normalized))
            self.assertEqual(raw["id"], normalized["id"])
        self.assertEqual("Thành phố Hồ Chí Minh, Phường Khánh Hội", normalize_record(SOURCE_CONTRACTS["goods_general"], sample("goods_general"), "2026-08-28")["location"])
        self.assertIsNone(normalize_record(SOURCE_CONTRACTS["medical_devices"], sample("medical_devices"), "2026-08-28")["production_year"])
        self.assertEqual(["vn1800665083"], normalize_record(SOURCE_CONTRACTS["medical_devices"], sample("medical_devices"), "2026-08-28")["winning_bidder_id"])

    def test_text_numbers_arrays_year_and_nulls_are_deterministic(self):
        raw = sample("goods_general")
        raw.update({"danhMucHangHoa": "  A\t  B  ", "winningCode": [" A ", "", "B"], "khoiLuongDouble": 2.5, "namSanXuat": "2025 trở về sau"})
        normalized = normalize_record(SOURCE_CONTRACTS["goods_general"], raw, "2026-08-28")
        self.assertEqual("A B", normalized["item_name"])
        self.assertEqual(["A", "B"], normalized["winning_bidder_id"])
        self.assertEqual(2.5, normalized["quantity"])
        self.assertIsNone(normalized["production_year"])
        raw["khoiLuongDouble"] = "2.5"
        with self.assertRaises(NormalizationError):
            normalize_record(SOURCE_CONTRACTS["goods_general"], raw, "2026-08-28")
        raw = sample("goods_general")
        raw.pop("danhMucHangHoa")
        self.assertIsNone(normalize_record(SOURCE_CONTRACTS["goods_general"], raw, "2026-08-28")["item_name"])

    def test_raw_schema_validation_reports_additive_fields_and_rejects_breaking_types(self):
        raw = sample("goods_general")
        raw["futureField"] = "kept as diagnostic"
        drift = validate_raw_records(SOURCE_CONTRACTS["goods_general"], [raw])
        self.assertEqual(("futureField",), drift.additive_fields)
        raw["donGiaDuThau"] = "not numeric"
        with self.assertRaises(ValidationError):
            validate_raw_records(SOURCE_CONTRACTS["goods_general"], [raw])


class CheckpointAndSinkTest(unittest.TestCase):
    def test_checkpoint_state_machine_and_recoverable_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            store = CheckpointStore(path)
            pending = store.ensure("goods_general", "2026-08-25")
            self.assertEqual(IngestionStatus.PENDING, pending.status)
            running = store.start("goods_general", "2026-08-25")
            self.assertEqual(IngestionStatus.RUNNING, running.status)
            recovered = store.start("goods_general", "2026-08-25")
            self.assertEqual(2, recovered.attempt_count)
            store.fail("goods_general", "2026-08-25", "COUNT_MISMATCH", "bad count")
            self.assertEqual(IngestionStatus.FAILED, store.get("goods_general", "2026-08-25").status)
            store.start("goods_general", "2026-08-25")
            store.fail("goods_general", "2026-08-25", "SEARCH_WINDOW_OVERFLOW", "cannot split", quarantine=True)
            self.assertEqual(IngestionStatus.QUARANTINED, store.get("goods_general", "2026-08-25").status)
            with self.assertRaises(ValueError):
                store.fail("goods_general", "2026-08-25", "COUNT_MISMATCH", "not running")
            store.start("goods_general", "2026-08-25")
            store.finish("goods_general", "2026-08-25", IngestionStatus.COMPLETED, normalized_count=1, sink_accepted_count=1)
            with self.assertRaises(ValueError):
                store.start("goods_general", "2026-08-25")
            store.start("goods_general", "2026-08-25", force=True)
            store.close()

    def test_jsonl_sink_is_utf8_sorted_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = JsonlValidationSink(directory)
            contract = SOURCE_CONTRACTS["goods_general"]
            context = PartitionContext(
                "goods_general", "2026-08-25", contract, official_day_interval("2026-08-25"),
                2, 2, 2, 2, 2, 1,
            )
            records = [{"id": "b", "name": "Đường"}, {"id": "a", "name": "Áo"}]
            result = sink.write_partition(context, records)
            self.assertEqual((2, 2, 0), (result.attempted_count, result.accepted_count, result.rejected_count))
            target = sink.path_for(context)
            self.assertEqual(["a", "b"], [json.loads(line)["id"] for line in target.read_text(encoding="utf-8").splitlines()])
            self.assertFalse(list(target.parent.glob("*.tmp")))
            bad = sink.write_partition(context, [{"name": "missing id"}])
            self.assertEqual(0, bad.accepted_count)
            self.assertEqual(["a", "b"], [json.loads(line)["id"] for line in target.read_text(encoding="utf-8").splitlines()])


class FakeEngineClient:
    def __init__(self, records, counts):
        self.config = MSCConfig(request_delay_seconds=0)
        self.records = records
        self.counts = iter(counts)
        self.stats = type("Stats", (), {"request_count": 0, "retry_count": 0})()

    def count_interval(self, contract, interval):
        self.stats.request_count += 1
        return next(self.counts)

    def fetch_page(self, contract, interval, page_number):
        self.stats.request_count += 1
        return response(len(self.records), self.records, page_number=page_number, total_pages=1)


class RejectingSink:
    def write_partition(self, context, records):
        return SinkWriteResult(len(records), 0, len(records), ("test rejection",))


class EngineTest(unittest.TestCase):
    def test_full_partition_completion_requires_sink_acceptance(self):
        records = [sample("goods_general"), {**sample("goods_general"), "id": "00000000-0000-0000-0000-000000000001"}]
        client = FakeEngineClient(records, [2, 2])
        with CheckpointStore(":memory:") as store:
            sink = InMemorySink()
            result = MSCIngestionEngine(client, store, sink).ingest_partition("goods_general", "2026-08-25")
            self.assertEqual(IngestionStatus.COMPLETED, result.status)
            self.assertEqual((2, 2, 2, 2), (result.parent_pre_count, result.parent_post_count, result.unique_source_count, result.sink_accepted_count))
            self.assertEqual(IngestionStatus.COMPLETED, store.get("goods_general", "2026-08-25").status)

    def test_parent_change_normalization_failure_and_sink_failure_do_not_complete(self):
        records = [sample("goods_general")]
        with CheckpointStore(":memory:") as store:
            result = MSCIngestionEngine(FakeEngineClient(records, [1, 1]), store, RejectingSink()).ingest_partition("goods_general", "2026-08-25")
            self.assertEqual(IngestionStatus.FAILED, result.status)
            self.assertEqual("SINK_INCOMPLETE", result.error_code)
            self.assertEqual(IngestionStatus.FAILED, store.get("goods_general", "2026-08-25").status)
        with CheckpointStore(":memory:") as store:
            result = MSCIngestionEngine(FakeEngineClient(records, [1, 0]), store, InMemorySink()).ingest_partition("goods_general", "2026-08-25")
            self.assertEqual("UNSTABLE_PARENT", result.error_code)
            self.assertEqual(IngestionStatus.FAILED, store.get("goods_general", "2026-08-25").status)

    def test_open_day_requires_opt_in_and_only_validates(self):
        records = [sample("goods_general")]
        with patch("crawler_engine.msc.engine.operational_today", return_value=date(2026, 8, 25)):
            with CheckpointStore(":memory:") as store:
                engine = MSCIngestionEngine(FakeEngineClient(records, [1, 1]), store, InMemorySink())
                with self.assertRaises(Exception):
                    engine.ingest_partition("goods_general", "2026-08-25")
                result = engine.ingest_partition("goods_general", "2026-08-25", allow_open_day=True)
                self.assertEqual(IngestionStatus.VALIDATED, result.status)
                self.assertNotEqual(IngestionStatus.COMPLETED, store.get("goods_general", "2026-08-25").status)


if __name__ == "__main__":
    unittest.main()
