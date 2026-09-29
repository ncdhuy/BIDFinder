from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "tools"))

from ingredient_lookup import count_document, lookup_filter, lookup_page, publication_year, source_key
from import_vss_ingredients import aggregate_xml, import_counts
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

    def test_lookup_filters_and_facet_totals(self):
        condition = lookup_filter({"registration": "VN-1", "drug": "Seduxen", "year": "2020"})
        self.assertEqual(condition, "sodk:`VN-1` && ten:`Seduxen` && nam_congbo:=`2020`")
        with self.assertRaises(ValueError):
            lookup_filter({"drug": "x` && occurrences:>0"})

        paths = []
        def request(path):
            paths.append(path)
            return {"found": 2, "hits": [{"document": {
                "ma": "40.048", "hoatchat": "Diazepam", "ten": "Seduxen",
                "sodk": "VN-1", "duongdung": "Uống", "nam_congbo": "2020",
                "occurrences": 3,
            }}], "facet_counts": [{"field_name": "occurrences", "stats": {"sum": 4, "max": 3}}]}
        result = lookup_page(request, {"drug": "Seduxen"}, 1, 10)
        self.assertEqual((result["total_groups"], result["total_records"], result["max_count"]), (2, 4, 3))
        self.assertEqual(result["rows"][0]["ma"], "40.048")
        self.assertIn("sort_by=occurrences%3Adesc%2Csort_order%3Aasc", paths[0])
        self.assertIn("facet_strategy=exhaustive", paths[0])
        lookup_page(request, {}, 2, 250, include_totals=False)
        self.assertNotIn("facet_by", paths[-1])

    def test_import_publishes_only_after_complete_batches(self):
        class Client:
            config = type("Config", (), {"batch_size": 1})()
            def __init__(self): self.calls = []
            def create_collection(self, schema): self.calls.append(("create", schema["name"]))
            def import_documents(self, name, rows):
                self.calls.append(("import", rows[0]["sort_order"]))
                return type("Result", (), {"rejected_count": 0, "accepted_count": len(rows)})()
            def get_collection(self, name): return {"num_documents": 2}
            def upsert_alias(self, alias, name): self.calls.append(("alias", alias))
        client = Client()
        import_counts(client, Counter({("40.048", "A", None, None, None, None): 3,
                                      ("40.49", "B", None, None, None, None): 1}))
        self.assertEqual([call[0] for call in client.calls], ["create", "import", "import", "alias"])
        self.assertEqual(count_document(("40.048", None, None, None, None, None), 2, 0)["ma"], "40.048")
        class RejectingClient(Client):
            def import_documents(self, name, rows):
                return type("Result", (), {"rejected_count": 1, "accepted_count": 0,
                                            "errors": ("rejected",)})()
        rejecting = RejectingClient()
        with self.assertRaises(RuntimeError):
            import_counts(rejecting, Counter({("40.048", None, None, None, None, None): 1}))
        self.assertNotIn("alias", [call[0] for call in rejecting.calls])

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
