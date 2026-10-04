from __future__ import annotations

import ast
from pathlib import Path
import unittest

from crawler_engine.msc.cli import build_parser
from crawler_engine.msc.contracts import SOURCE_CONTRACTS


ROOT = Path(__file__).resolve().parents[2]


class ProductionBoundaryTest(unittest.TestCase):
    def test_new_package_has_no_legacy_or_application_imports(self):
        forbidden = {"s1_crawler", "s2_daily_manager", "s3_etl_pipeline", "selenium", "asyncpg", "psycopg2", "typesense"}
        for path in (ROOT / "crawler_engine" / "msc").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name.split(".")[0] for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                self.assertTrue(forbidden.isdisjoint(names), f"forbidden import in {path}: {names}")

    def test_cli_requires_explicit_crawl_range_and_validates_all_sources(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["crawl", "--sources", "all"])
        args = parser.parse_args(["validate", "--source", "all", "--date", "2026-08-25"])
        self.assertEqual(tuple(SOURCE_CONTRACTS), args.source)


if __name__ == "__main__":
    unittest.main()
