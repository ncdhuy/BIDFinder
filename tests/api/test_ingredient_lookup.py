from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "tools"))

from ingredient_lookup import lookup_where, publication_year, source_key
from import_vss_ingredients import aggregate_xml
from crawler_engine.vss.download_vss_data import ManifestStore


class IngredientLookupTest(unittest.TestCase):
    def test_vss_grouping_preserves_code_and_counts_invalid_dates(self):
        base = {"ma": "40.048", "hoatchat": "Diazepam", "ten": "Seduxen", "sodk": "VN-1", "duongdung": "Uống"}
        rows = [{**base, "congbo": "2020-03-04 00:00:00"},
                {**base, "congbo": "2020-05-06"},
                {**base, "congbo": "invalid"}]
        counts = Counter(map(source_key, rows))
        self.assertEqual(counts[("40.048", "Diazepam", "Seduxen", "VN-1", "Uống", "2020")], 2)
        self.assertEqual(counts[("40.048", "Diazepam", "Seduxen", "VN-1", "Uống", None)], 1)
        self.assertEqual(publication_year("31/12/2021"), "2021")
        self.assertIsNone(publication_year("2021-02-30"))

    def test_lookup_filters_are_and_combined_and_literal(self):
        where, values = lookup_where({"registration": "VN_1%", "drug": "Seduxen", "year": "2020"})
        self.assertEqual(where.count(" AND "), 2)
        self.assertIn("sodk ILIKE $1", where)
        self.assertIn("ten ILIKE $2", where)
        self.assertIn("nam_congbo ILIKE $3", where)
        self.assertEqual(values, ["%VN\\_1\\%%", "%Seduxen%", "%2020%"])

    def test_xml_import_and_relocated_manifest(self):
        fixture = ROOT / "tests" / "fixtures" / "vss"
        raw_dir = fixture / "downloads"
        counts = aggregate_xml(raw_dir)
        self.assertEqual(counts[("40.048", "Diazepam", "Seduxen", "VN-1", "Uống", "2025")], 2)
        self.assertEqual(counts[("40.048", "Diazepam", "Seduxen", "VN-1", "Uống", None)], 1)
        manifest = ManifestStore(fixture / "crawl_manifest.csv", raw_dir)
        self.assertEqual(
            Path(manifest.rows["2025-01-01"]["raw_path"]),
            raw_dir / "2025" / "01" / "vss_export_20250101.xml",
        )


if __name__ == "__main__":
    unittest.main()
