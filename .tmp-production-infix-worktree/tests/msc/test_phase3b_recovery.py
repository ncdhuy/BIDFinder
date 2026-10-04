import json
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crawler_engine.msc.backfill import BackfillReport, build_manifest
from crawler_engine.msc.typesense_client import TypesenseError
from tools.phase3b_historical_backfill import (
    RECOVERY_SNAPSHOT_ERROR,
    RecoveryBundleManager,
    RecoveryError,
    _record_recovery_error,
)


class SnapshotClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.paths = []

    def snapshot(self, path):
        path = Path(path)
        self.paths.append(path)
        if path.exists():
            raise AssertionError(f"snapshot destination already exists: {path}")
        path.mkdir(parents=True)
        (path / "state").write_text("snapshot", encoding="utf-8")
        if self.fail:
            raise TypesenseError("TYPESENSE_CONNECT_ERROR", "HTTP 500: Copy failed.")


class Provenance:
    def total_count(self):
        return 1000000

    def conflict_count(self):
        return 0


class Phase3BRecoveryTest(unittest.TestCase):
    @staticmethod
    def _manager(root, client):
        root = Path(root)
        files = {
            "checkpoint.sqlite3": "checkpoint",
            "uuid.sqlite3": "uuid",
            "report.json": "report",
            "manifest.json": "manifest",
        }
        for name, content in files.items():
            (root / name).write_text(content, encoding="utf-8")
        manager = RecoveryBundleManager(
            client,
            {"generation": "hist_v1_20260829"},
            Provenance(),
            checkpoint_path=root / "checkpoint.sqlite3",
            uuid_path=root / "uuid.sqlite3",
            report_path=root / "report.json",
            manifest_path=root / "manifest.json",
            recovery_dir=root / "recovery",
        )
        manager._validate = lambda *_args: None
        manager._counts = lambda: {"goods": 1, "medicines": 1, "traditional_medicine": 1}
        return manager

    @staticmethod
    def _report():
        return SimpleNamespace(data={"last_completed_partition": {"source_key": "goods_general", "partition_date": "2025-10-22"}, "counts": {"records_accepted": 1000000}})

    def test_each_bundle_uses_unique_nonexistent_snapshot_destination(self):
        with TemporaryDirectory() as temporary:
            client = SnapshotClient()
            manager = self._manager(temporary, client)

            manager.create("milestone-1000000", self._report())
            manager.create("milestone-2000000", self._report())

            self.assertEqual(2, len({str(path) for path in client.paths}))
            self.assertTrue(all(path.parent.name == ".snapshot-staging" for path in client.paths))
            self.assertEqual(2, len(list((Path(temporary) / "recovery").glob("bundle-*"))))

    def test_failed_snapshot_leaves_tmp_and_no_validated_bundle(self):
        with TemporaryDirectory() as temporary:
            client = SnapshotClient(fail=True)
            manager = self._manager(temporary, client)

            with self.assertRaisesRegex(RecoveryError, "HTTP 500: Copy failed") as raised:
                manager.create("milestone-1000000", self._report())

            self.assertEqual(RECOVERY_SNAPSHOT_ERROR, raised.exception.code)
            self.assertEqual([], list((Path(temporary) / "recovery").glob("bundle-*")))
            self.assertEqual(1, len(list((Path(temporary) / "recovery").glob(".bundle-*.tmp"))))
            self.assertEqual(1, len(list((Path(temporary) / "recovery" / ".snapshot-staging").iterdir())))

    def test_stale_snapshot_staging_does_not_block_future_bundle(self):
        with TemporaryDirectory() as temporary:
            client = SnapshotClient(fail=True)
            manager = self._manager(temporary, client)
            with self.assertRaises(RecoveryError):
                manager.create("milestone-1000000", self._report())

            client.fail = False
            manager.create("milestone-1000000", self._report())

            self.assertEqual(2, len({str(path) for path in client.paths}))
            self.assertEqual(1, len(list((Path(temporary) / "recovery").glob("bundle-*"))))
            self.assertEqual(1, len(list((Path(temporary) / "recovery").glob(".bundle-*.tmp"))))

    def test_validated_bundle_is_not_overwritten(self):
        with TemporaryDirectory() as temporary:
            manager = self._manager(temporary, SnapshotClient())
            first = manager.create("milestone-1000000", self._report())
            target = Path(first["path"])
            (target / "sentinel").write_text("keep", encoding="utf-8")

            manager.create("milestone-2000000", self._report())

            self.assertEqual("keep", (target / "sentinel").read_text(encoding="utf-8"))

    def test_recovery_error_is_structured_without_source_failure(self):
        totals = {
            "goods_general": 1,
            "medical_devices": 1,
            "medicine_generic": 1,
            "medicine_originator": 1,
            "medicine_herbal": 1,
            "herbal_material": 1,
            "traditional_medicine": 1,
        }
        manifest = build_manifest("2025-01-01", "2025-01-02", "dev1", totals)
        with TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.json"
            report = BackfillReport(report_path, manifest, "checkpoint.sqlite3")
            report.data["current_partition"] = "goods_general:2025-10-22"
            report.data["last_completed_partition"] = {"source_key": "goods_general", "partition_date": "2025-10-22"}
            _record_recovery_error(report, RecoveryError(RECOVERY_SNAPSHOT_ERROR, "snapshot", "HTTP 500: Copy failed.", recovery_milestone="milestone-7208917"))

            saved = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(RECOVERY_SNAPSHOT_ERROR, saved["recovery_error"]["code"])
            self.assertEqual("snapshot", saved["recovery_error"]["stage"])
            self.assertEqual("milestone-7208917", saved["recovery_error"]["recovery_milestone"])
            self.assertEqual(0, saved["counts"]["failed"])
            self.assertNotIn("source_key", saved["recovery_error"])

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

    def test_resume_uses_existing_milestone_watermark(self):
        with TemporaryDirectory() as temporary:
            recovery_dir = Path(temporary)
            bundle = recovery_dir / "bundle-00003-milestone-6025897"
            bundle.mkdir()
            (bundle / "bundle.json").write_text('{"uuid_audit_total":6025897}\n', encoding="utf-8")

            manager = RecoveryBundleManager(
                object(),
                {"generation": "hist_v1_20260829"},
                object(),
                checkpoint_path=recovery_dir / "checkpoint.sqlite3",
                uuid_path=recovery_dir / "uuid.sqlite3",
                report_path=recovery_dir / "report.json",
                manifest_path=recovery_dir / "manifest.json",
                recovery_dir=recovery_dir,
            )

            self.assertEqual(6025897, manager.last_milestone_accepted)


if __name__ == "__main__":
    unittest.main()
