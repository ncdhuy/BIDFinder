from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_contract import resolve_serving_generation  # noqa: E402


class ServingGenerationResolutionTest(unittest.TestCase):
    def test_report_is_canonical_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "reports" / "serving-state-active.json"
            (root / "reports").mkdir()
            (root / "checkpoints").mkdir()
            generation = "serving_v1_test"
            report.write_text(json.dumps({"serving_generation": generation}), encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "BIDFINDER_SERVING_REPORT_PATH": str(report),
                    "BIDFINDER_TYPESENSE_SERVING_GENERATION": generation,
                    "BIDFINDER_SERVING_GENERATION": generation,
                },
                clear=False,
            ):
                self.assertEqual(generation, resolve_serving_generation())

    def test_mismatched_report_and_environment_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "serving-state.json"
            report.write_text(json.dumps({"serving_generation": "serving_v1_report"}), encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "BIDFINDER_SERVING_REPORT_PATH": str(report),
                    "BIDFINDER_TYPESENSE_SERVING_GENERATION": "serving_v1_env",
                    "BIDFINDER_SERVING_GENERATION": "serving_v1_env",
                },
                clear=False,
            ), self.assertRaises(RuntimeError):
                resolve_serving_generation()


if __name__ == "__main__":
    unittest.main()
