from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
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

    def test_prune_keeps_validated_bundles(self):
        manager = object.__new__(RecoveryBundleManager)
        with TemporaryDirectory() as temporary:
            manager.recovery_dir = Path(temporary)
            names = (
                "bundle-00001-milestone-1000000",
                "bundle-00002-milestone-2000000",
                "bundle-00003-milestone-3000000",
            )
            for name in names:
                (manager.recovery_dir / name).mkdir()

            manager._prune()

            self.assertEqual(names, tuple(path.name for path in sorted(manager.recovery_dir.iterdir())))


if __name__ == "__main__":
    unittest.main()
