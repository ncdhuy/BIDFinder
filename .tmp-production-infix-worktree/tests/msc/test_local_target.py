from pathlib import Path
import tempfile
import unittest

from crawler_engine.msc.config import TypesenseConfig
from crawler_engine.msc.local_target import (
    FULL_RUN_AUTHORIZATION_PHRASE,
    FUTURE_HISTORICAL_GENERATION,
    historical_source_count_deltas,
    local_generation_artifacts,
    local_target_paths,
    validate_local_typesense_config,
)
from crawler_engine.msc.backfill import BackfillControlError, require_full_run_authorization
from tools.local_typesense_canary import _markdown


class LocalTargetTest(unittest.TestCase):
    def test_runtime_paths_are_separate_and_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runtime"
            repo = Path(temp) / "repo"
            paths = local_target_paths(root, repo_root=repo, create=True)
            self.assertTrue(paths.data_dir.exists())
            self.assertNotEqual(paths.data_dir, paths.snapshots_dir)
            artifacts = local_generation_artifacts(paths, "local_canary_20260831_abc123")
            self.assertEqual("local_canary_20260831_abc123.sqlite3", artifacts["checkpoint"].name)
            self.assertEqual("local_canary_20260831_abc123.snapshot", artifacts["snapshot"].name)

    def test_repository_runtime_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                local_target_paths(repo / "runtime", repo_root=repo)

    def test_local_config_requires_loopback_http_defaults(self):
        validate_local_typesense_config(TypesenseConfig(api_key="test"))
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate_local_typesense_config(TypesenseConfig(host="example.invalid", api_key="test"))
        with self.assertRaisesRegex(ValueError, "HTTP"):
            validate_local_typesense_config(TypesenseConfig(protocol="https", api_key="test"))

    def test_full_run_requires_exact_authorization_phrase(self):
        with self.assertRaises(BackfillControlError):
            require_full_run_authorization(None)
        with self.assertRaises(BackfillControlError):
            require_full_run_authorization("yes")
        require_full_run_authorization(FULL_RUN_AUTHORIZATION_PHRASE)
        self.assertEqual("hist_v1_20260829", FUTURE_HISTORICAL_GENERATION)

    def test_historical_source_delta_report(self):
        actual = {
            "goods_general": 1,
            "medical_devices": 964685,
            "medicine_generic": 494698,
            "medicine_originator": 55239,
            "medicine_herbal": 35489,
            "herbal_material": 9554,
            "traditional_medicine": 22468,
        }
        deltas = historical_source_count_deltas(actual)
        self.assertEqual(-8219251, deltas["goods_general"]["delta"])
        self.assertFalse(deltas["goods_general"]["unchanged"])

    def test_canary_report_markdown_serialization_is_key_free(self):
        markdown = _markdown(
            {
                "status": "PASS",
                "generation": "local_canary_test",
                "runtime": {"typesense_version": "30.2", "persistent_data_path": "/tmp/typesense/data"},
                "checks": {"snapshot_restore": True},
                "canary": {"total_unique_documents": 3},
                "historical_manifest": {"actual_total": 3},
                "future_historical_generation": FUTURE_HISTORICAL_GENERATION,
            }
        )
        self.assertIn("Status: **PASS**", markdown)
        self.assertIn("snapshot_restore | PASS", markdown)
        self.assertNotIn("TYPESENSE_API_KEY", markdown)

    def test_core_msc_modules_do_not_depend_on_wsl_or_windows_apis(self):
        root = Path(__file__).resolve().parents[2] / "crawler_engine" / "msc"
        source = "\n".join(path.read_text(encoding="utf-8").lower() for path in root.glob("*.py"))
        for token in ("wsl.exe", "powershell", "winreg"):
            self.assertNotIn(token, source)

    def test_local_operator_keeps_snapshot_and_restore_separate_from_live_data(self):
        script = (Path(__file__).resolve().parents[2] / "infra" / "typesense" / "local-typesense.sh").read_text(encoding="utf-8")
        self.assertIn("POST --get", script)
        self.assertIn("restore-start", script)
        self.assertIn("restore data must not be live data", script)
        self.assertIn("--peering-address=127.0.0.1", script)


if __name__ == "__main__":
    unittest.main()
