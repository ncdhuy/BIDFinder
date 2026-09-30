from collections import Counter
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "tools"))

from ingredient_lookup import IngredientLookupStore, count_document, lookup_page, lookup_suggestions, publication_year, source_key
from import_vss_ingredients import aggregate_xml, import_counts
from update_vss_ingredients import crawl_window, prune_old_collections, validate_crawl
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

    def test_lookup_substrings_and_contextual_suggestions(self):
        store = IngredientLookupStore()
        collection = ["first"]
        documents = {
            "first": [
                {"ma": "40.048", "hoatchat": "Diazepam", "ten": "Seduxen 5mg", "sodk": "VN-123", "duongdung": "Uống", "nam_congbo": "2020", "occurrences": 3, "sort_order": 0},
                {"ma": "40.049", "hoatchat": "Diazepam", "ten": "Seduxen\n 5 mg", "sodk": "VN-124", "duongdung": "Tiêm", "nam_congbo": "2021", "occurrences": 2, "sort_order": 1},
                {"ma": "40.050", "hoatchat": "Paracetamol", "ten": "Other", "sodk": "VN-125", "duongdung": "Uống", "nam_congbo": "2020", "occurrences": 1, "sort_order": 2},
            ],
            "second": [{"ma": "40.048", "hoatchat": "Diazepam", "ten": "Seduxen", "sodk": "VN-123", "duongdung": "Uống", "nam_congbo": "2020", "occurrences": 4, "sort_order": 0}],
        }
        def request(path):
            return {"collection_name": collection[0]} if path.startswith("/aliases/") else {"num_documents": len(documents[collection[0]])}
        def export(name):
            yield from documents[name]

        result = lookup_page(store, request, export, {"drug": "DUX", "ingredient": "aze"}, 1, 1)
        self.assertEqual((result["total_groups"], result["total_records"], result["max_count"]), (2, 5, 3))
        self.assertEqual(result["rows"][0]["ma"], "40.048")
        next_page = lookup_page(store, request, export, {"drug": "dux"}, 2, 1, include_totals=False)
        self.assertEqual(next_page["rows"][0]["ma"], "40.049")
        self.assertEqual(next_page["total_records"], 0)
        self.assertEqual(lookup_suggestions(store, request, export, "drug", "dux", {"ingredient": "dia"}),
                         ["Seduxen 5mg", "Seduxen 5 mg"])
        self.assertEqual(lookup_page(store, request, export, {"drug": "5 mg"}, 1, 10)["total_groups"], 1)
        collection[0] = "second"
        self.assertEqual(lookup_page(store, request, export, {"drug": "dux"}, 1, 10)["total_records"], 4)

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
        validate_crawl(manifest, date(2025, 1, 1), date(2025, 1, 1))
        with self.assertRaisesRegex(RuntimeError, "2025-01-02"):
            validate_crawl(manifest, date(2025, 1, 1), date(2025, 1, 2))

    def test_daily_window_catches_up_and_collection_cleanup_keeps_rollback(self):
        self.assertEqual(
            crawl_window(date(2026, 9, 30), date(2026, 9, 20), 3),
            (date(2026, 9, 21), date(2026, 9, 28)),
        )
        class Client:
            def __init__(self): self.deleted = []
            def get_alias(self, alias): return {"collection_name": f"{alias}_d"}
            def list_collections(self):
                return [{"name": f"vss_ingredient_lookup_{letter}", "created_at": index}
                        for index, letter in enumerate("abcd", 1)]
            def delete_collection(self, name): self.deleted.append(name)
        client = Client()
        prune_old_collections(client)
        self.assertEqual(client.deleted, ["vss_ingredient_lookup_a"])


if __name__ == "__main__":
    unittest.main()
