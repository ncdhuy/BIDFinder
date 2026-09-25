from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import server as server_module  # noqa: E402
from server import fetch_update_dashboard, get_update_snapshot  # noqa: E402


class UpdateDashboardFreshnessTest(unittest.TestCase):
    def test_weekend_uses_only_eight_and_seventeen_update_slots(self):
        saturday = datetime(2026, 9, 26, 12, 0)
        sunday = datetime(2026, 9, 27, 12, 0)
        friday = datetime(2026, 9, 25, 12, 15)

        self.assertEqual((date(2026, 9, 26), True, "08:00"), get_update_snapshot(saturday))
        self.assertEqual((date(2026, 9, 27), True, "08:00"), get_update_snapshot(sunday))
        self.assertEqual((date(2026, 9, 25), True, "12:00"), get_update_snapshot(friday))

    def test_before_weekend_first_update_uses_previous_day_and_last_slot(self):
        snapshot = get_update_snapshot(datetime(2026, 9, 26, 7, 59))

        self.assertEqual((date(2026, 9, 25), False, "17:00"), snapshot)

    def test_current_day_schedule_covers_weekday_half_hour_slots_and_weekend_first_slot(self):
        self.assertEqual("07:00", get_update_snapshot(datetime(2026, 9, 25, 7, 0))[2])
        self.assertEqual("16:30", get_update_snapshot(datetime(2026, 9, 25, 16, 45))[2])
        self.assertEqual("17:00", get_update_snapshot(datetime(2026, 9, 25, 17, 0))[2])
        self.assertEqual("08:00", get_update_snapshot(datetime(2026, 9, 26, 16, 45))[2])

    def test_empty_current_day_uses_previous_day_data_and_keeps_current_cutoff(self):
        current_day = date(2026, 9, 26)
        previous_day = date(2026, 9, 25)
        previous_summary = {
            "approved_package_count": 12,
            "highest_package": {"value": 900, "date": previous_day.isoformat()},
            "highest_goods": {"value": 80, "date": previous_day.isoformat()},
        }
        repository = type("Repository", (), {})()
        repository.daily_summary = AsyncMock(side_effect=[{}, previous_summary])

        with patch.object(server_module, "typesense_search_repository", repository):
            dashboard = asyncio.run(
                fetch_update_dashboard(
                    None,
                    current_day,
                    is_current_day=True,
                    snapshot_time="08:00",
                )
            )

        self.assertEqual(
            [current_day, previous_day],
            [call.args[0] for call in repository.daily_summary.await_args_list],
        )
        self.assertEqual(current_day.isoformat(), dashboard["date"])
        self.assertEqual(previous_day.isoformat(), dashboard["data_date"])
        self.assertEqual("08:00", dashboard["cutoff"])
        self.assertTrue(dashboard["used_fallback_data"])
        self.assertEqual(12, dashboard["approved_package_count"])
        self.assertTrue(dashboard["data_available"])

    def test_systemd_timers_match_the_shared_update_schedule(self):
        current_day_timer = (ROOT / "infra" / "systemd" / "bidfinder-incremental-current-day.timer.in").read_text(encoding="utf-8")
        reconciliation_timer = (ROOT / "infra" / "systemd" / "bidfinder-incremental.timer.in").read_text(encoding="utf-8")

        for hour in range(7, 17):
            for minute in (0, 30):
                slot = f"{hour:02d}:{minute:02d}:00"
                self.assertIn(f"OnCalendar=Mon..Fri *-*-* {slot} Asia/Ho_Chi_Minh", current_day_timer)
        self.assertNotIn("OnCalendar=*-*-*", current_day_timer)
        self.assertIn("OnCalendar=Sat,Sun *-*-* 08:00:00 Asia/Ho_Chi_Minh", current_day_timer)
        self.assertNotIn("OnCalendar=Sat,Sun *-*-* 16:30:00 Asia/Ho_Chi_Minh", current_day_timer)
        self.assertIn("OnCalendar=*-*-* 17:00:00 Asia/Ho_Chi_Minh", reconciliation_timer)


if __name__ == "__main__":
    unittest.main()
