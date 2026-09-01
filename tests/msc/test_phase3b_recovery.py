from types import SimpleNamespace
import unittest

from tools.phase3b_historical_backfill import RecoveryBundleManager


class Phase3BRecoveryTest(unittest.TestCase):
    def test_skipped_partition_does_not_create_recovery_milestone(self):
        manager = object.__new__(RecoveryBundleManager)
        manager.last_milestone_accepted = 0
        created = []
        manager.create = lambda label, report: created.append((label, report))
        report = SimpleNamespace(data={"counts": {"records_accepted": 1_100_000}})

        self.assertIsNone(manager.maybe_create(SimpleNamespace(skipped=True), report))
        self.assertEqual([], created)
        self.assertEqual(0, manager.last_milestone_accepted)


if __name__ == "__main__":
    unittest.main()
