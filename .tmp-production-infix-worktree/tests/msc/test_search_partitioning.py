from datetime import timedelta
import json
from pathlib import Path
import unittest

from tools.msc_search_pagination import (
    MAX_SAFE_SEARCH_RESULTS,
    PartitionPlan,
    SearchInterval,
    SearchPartitionError,
    plan_partition,
    split_search_interval,
    union_partition_records,
    validate_partition_completeness,
)


PARENT = SearchInterval(
    "2026-08-28T00:00:00.000Z",
    "2026-08-28T23:59:59.059Z",
)
ROOT = Path(__file__).resolve().parents[2]


class IntervalPlanningTest(unittest.TestCase):
    def test_safe_interval_remains_one_leaf(self):
        calls = []

        def count(interval):
            calls.append(interval)
            return 9257

        plan = plan_partition(PARENT, count)

        self.assertIsInstance(plan, PartitionPlan)
        self.assertEqual((PARENT.from_value, PARENT.to_value), (plan.safe_leaves[0].from_value, plan.safe_leaves[0].to_value))
        self.assertEqual(9257, plan.safe_leaves[0].expected_count)
        self.assertEqual(1, len(calls))
        self.assertEqual((), plan.diagnostics)

    def test_unsafe_interval_splits_into_safe_leaves(self):
        def count(interval):
            if interval.depth == 0:
                return MAX_SAFE_SEARCH_RESULTS + 1
            return 4750 if interval.from_value == PARENT.from_value else 4751

        plan = plan_partition(PARENT, count)

        self.assertEqual(2, len(plan.safe_leaves))
        self.assertTrue(all(leaf.expected_count <= MAX_SAFE_SEARCH_RESULTS for leaf in plan.safe_leaves))
        self.assertEqual(1, len(plan.diagnostics))

    def test_recursive_split(self):
        def count(interval):
            if interval.depth == 0:
                return 19001
            if interval.depth == 1:
                return 8000 if interval.from_value == PARENT.from_value else 11001
            return 6000

        plan = plan_partition(PARENT, count, max_depth=3)

        self.assertEqual(3, len(plan.safe_leaves))
        self.assertEqual(2, len(plan.diagnostics))
        self.assertTrue(all(leaf.expected_count <= MAX_SAFE_SEARCH_RESULTS for leaf in plan.safe_leaves))

    def test_zero_result_interval_is_safe_empty_leaf(self):
        plan = plan_partition(PARENT, lambda interval: 0)

        self.assertEqual(0, plan.safe_leaves[0].expected_count)
        self.assertEqual(1, len(plan.safe_leaves))

    def test_maximum_depth_fails_closed(self):
        with self.assertRaisesRegex(SearchPartitionError, "maximum depth"):
            plan_partition(PARENT, lambda interval: MAX_SAFE_SEARCH_RESULTS + 1, max_depth=0)

    def test_minimum_granularity_fails_closed(self):
        with self.assertRaisesRegex(SearchPartitionError, "minimum time span"):
            plan_partition(
                SearchInterval("2026-08-28T00:00:00.000Z", "2026-08-28T00:01:00.000Z"),
                lambda interval: MAX_SAFE_SEARCH_RESULTS + 1,
                minimum_span=timedelta(hours=1),
            )

    def test_zero_progress_split_rejected(self):
        with self.assertRaisesRegex(SearchPartitionError, "zero-progress"):
            split_search_interval(
                SearchInterval("2026-08-28T00:00:00.000Z", "2026-08-28T00:00:10.000Z"),
                overlap=timedelta(seconds=5),
            )

    def test_child_count_deficit_fails_closed(self):
        def count(interval):
            if interval.depth == 0:
                return 100
            return 40 if interval.from_value == PARENT.from_value else 50

        with self.assertRaisesRegex(SearchPartitionError, "child count deficit"):
            plan_partition(PARENT, count, max_safe_results=50)

    def test_split_has_one_second_deterministic_overlap(self):
        left, right = split_search_interval(PARENT)

        midpoint = "2026-08-28T11:59:59.529Z"
        self.assertEqual(midpoint, right.from_value)
        self.assertEqual("2026-08-28T12:00:00.529Z", left.to_value)


class BoundaryUnionTest(unittest.TestCase):
    def test_no_overlap_children_union_exactly(self):
        result = union_partition_records(
            [[{"id": "a"}], [{"id": "b"}]],
            expected_count=2,
        )

        self.assertEqual(2, result.raw_record_count)
        self.assertEqual(2, result.unique_uuid_count)
        self.assertEqual(0, result.duplicate_uuid_occurrences)

    def test_same_content_overlap_is_deduplicated(self):
        result = union_partition_records(
            [[{"id": "a", "value": 1}], [{"id": "a", "value": 1}, {"id": "b"}]],
            expected_count=2,
        )

        self.assertEqual(3, result.raw_record_count)
        self.assertEqual(1, result.duplicate_uuid_occurrences)
        self.assertEqual(frozenset({"a"}), result.duplicate_uuids)

    def test_same_uuid_different_content_rejected(self):
        with self.assertRaisesRegex(SearchPartitionError, "different content"):
            union_partition_records(
                [[{"id": "a", "value": 1}], [{"id": "a", "value": 2}]],
                expected_count=1,
            )

    def test_duplicate_across_non_overlapping_leaves_rejected(self):
        intervals = [
            SearchInterval("2026-08-28T00:00:00.000Z", "2026-08-28T01:00:00.000Z"),
            SearchInterval("2026-08-28T02:00:00.000Z", "2026-08-28T03:00:00.000Z"),
        ]
        with self.assertRaisesRegex(SearchPartitionError, "non-overlapping"):
            union_partition_records(
                [[{"id": "a"}], [{"id": "a"}]],
                expected_count=1,
                leaf_intervals=intervals,
            )

    def test_duplicate_within_leaf_rejected(self):
        with self.assertRaisesRegex(SearchPartitionError, "within safe leaf"):
            union_partition_records([[{"id": "a"}, {"id": "a"}]], expected_count=1)

    def test_missing_record_is_count_deficit(self):
        with self.assertRaisesRegex(SearchPartitionError, "union deficit"):
            union_partition_records([[{"id": "a"}]], expected_count=2)

    def test_unexpected_uuid_is_count_surplus(self):
        with self.assertRaisesRegex(SearchPartitionError, "union surplus"):
            union_partition_records([[{"id": "a"}, {"id": "b"}]], expected_count=1)

    def test_pre_post_count_equality(self):
        validate_partition_completeness(2, 2, post_count=2)
        with self.assertRaisesRegex(SearchPartitionError, "pre/post count changed"):
            validate_partition_completeness(2, 2, post_count=3)
        with self.assertRaisesRegex(SearchPartitionError, "completeness deficit"):
            validate_partition_completeness(2, 1)

    def test_positive_child_sum_surplus_is_diagnostic(self):
        plan = plan_partition(
            PARENT,
            lambda interval: 100 if interval.depth == 0 else 60 if interval.depth == 1 else 30,
            max_safe_results=50,
        )

        self.assertEqual(20, plan.diagnostics[0].overlap_surplus)
        self.assertEqual(120, plan.diagnostics[0].child_count_sum)

    def test_sanitized_live_partition_fixture_is_consistent(self):
        fixture = json.loads(
            (ROOT / "docs" / "msc-contracts" / "partition-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("Phase 1C", fixture["phase"])
        self.assertEqual(9500, fixture["max_safe_search_results"])
        self.assertEqual("PT1S", fixture["overlap_policy"]["duration"])
        self.assertEqual(16248, fixture["intraday_range_proof"]["union_uuid_count"])
        self.assertTrue(all(item["http"] == 200 for item in fixture["intraday_range_proof"]["ranges"]))
        self.assertEqual(
            {"2026-08-28", "2026-08-27", "2026-08-26", "2026-08-21"},
            {item["date"] for item in fixture["overflow_days"]},
        )
        for day in fixture["overflow_days"]:
            self.assertEqual(day["parent_count"], day["unique_uuid_count"])
            self.assertEqual(day["parent_count"], day["pre_count"])
            self.assertEqual(day["pre_count"], day["post_count"])
            self.assertEqual(
                sum(leaf["fetched"] for leaf in day["leaves"]), day["raw_fetched_count"]
            )
            self.assertTrue(all(leaf["count"] <= 9500 for leaf in day["leaves"]))
            for split in day["split_diagnostics"]:
                self.assertEqual(split["left"] + split["right"], split["child_sum"])
                self.assertEqual(split["child_sum"] - split["parent"], split["overlap_surplus"])
        self.assertEqual(1, fixture["normal_day"]["leaf_count"])
        self.assertEqual(2, fixture["overlap_boundary_probe"]["duplicate_uuid_occurrences"])
        self.assertEqual(0, fixture["overlap_boundary_probe"]["same_uuid_content_conflicts"])


if __name__ == "__main__":
    unittest.main()
