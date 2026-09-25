from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
import server as server_module  # noqa: E402
from server import fetch_approval_timeline  # noqa: E402
from crawler_engine import sync_daily_approval_summary as summary_module  # noqa: E402


class DailyApprovalSummaryTest(unittest.TestCase):
    def test_collect_daily_counts_keeps_zero_days_and_unions_groups(self):
        responses = {
            ("goods", date(2026, 9, 20)): {"TBMT-1", "TBMT-2"},
            ("medicines", date(2026, 9, 20)): {"TBMT-2", "TBMT-3"},
            ("traditional_medicine", date(2026, 9, 20)): set(),
            ("goods", date(2026, 9, 21)): set(),
            ("medicines", date(2026, 9, 21)): set(),
            ("traditional_medicine", date(2026, 9, 21)): set(),
        }

        def fake_fetch(_base_url, _api_key, _timeout, group, day, _generation):
            return responses[(group, day)]

        with (
            patch.object(summary_module, "_resolve_typesense_config", return_value=("http://typesense:8108", "key", 30.0)),
            patch.object(summary_module, "_fetch_package_codes", side_effect=fake_fetch),
        ):
            rows = summary_module.collect_daily_counts(
                date(2026, 9, 20),
                date(2026, 9, 21),
                generation="serving_v1_test",
                workers=3,
            )

        self.assertEqual(
            rows,
            [(date(2026, 9, 20), 3), (date(2026, 9, 21), 0)],
        )

    def test_api_reads_dense_rollup_without_calling_typesense(self):
        repository = type("Repository", (), {})()
        repository.config = type("Config", (), {"serving_generation": "serving_v1_test"})()
        repository.update_timeline = AsyncMock()
        connection = type("Connection", (), {})()
        connection.fetch = AsyncMock(
            return_value=[
                {"data_date": date(2026, 9, 20), "approved_package_count": 3},
                {"data_date": date(2026, 9, 21), "approved_package_count": 0},
            ]
        )

        with patch.object(server_module, "typesense_search_repository", repository):
            result = asyncio.run(
                fetch_approval_timeline(connection, date(2026, 9, 21), date(2026, 9, 20))
            )

        self.assertEqual(
            result,
            [
                {"date": "2026-09-20", "count": 3},
                {"date": "2026-09-21", "count": 0},
            ],
        )
        repository.update_timeline.assert_not_awaited()

    def test_api_falls_back_when_rollup_table_is_missing(self):
        repository = type("Repository", (), {})()
        repository.config = type("Config", (), {"serving_generation": "serving_v1_test"})()
        repository.update_timeline = AsyncMock(
            return_value=[{"date": "2026-09-21", "count": 4}]
        )
        connection = type("Connection", (), {})()
        connection.fetch = AsyncMock(side_effect=asyncpg.UndefinedTableError())

        with patch.object(server_module, "typesense_search_repository", repository):
            result = asyncio.run(
                fetch_approval_timeline(connection, date(2026, 9, 21), date(2026, 9, 21))
            )

        self.assertEqual(result, [{"date": "2026-09-21", "count": 4}])
        repository.update_timeline.assert_awaited_once_with(
            today=date(2026, 9, 21),
            start_day=date(2026, 9, 21),
        )

    def test_api_scans_only_missing_days(self):
        repository = type("Repository", (), {})()
        repository.config = type("Config", (), {"serving_generation": "serving_v1_test"})()
        repository.update_timeline = AsyncMock(
            return_value=[{"date": "2026-09-22", "count": 4}]
        )
        connection = type("Connection", (), {})()
        connection.fetch = AsyncMock(
            return_value=[
                {"data_date": date(2026, 9, 21), "approved_package_count": 3},
                {"data_date": date(2026, 9, 23), "approved_package_count": 0},
            ]
        )

        with patch.object(server_module, "typesense_search_repository", repository):
            result = asyncio.run(
                fetch_approval_timeline(connection, date(2026, 9, 23), date(2026, 9, 21))
            )

        self.assertEqual(
            result,
            [
                {"date": "2026-09-21", "count": 3},
                {"date": "2026-09-22", "count": 4},
                {"date": "2026-09-23", "count": 0},
            ],
        )
        repository.update_timeline.assert_awaited_once_with(
            today=date(2026, 9, 22),
            start_day=date(2026, 9, 22),
        )


if __name__ == "__main__":
    unittest.main()
