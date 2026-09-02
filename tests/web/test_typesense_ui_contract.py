from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TypesenseUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "typesense-search-contract.json").read_text(encoding="utf-8"))
        cls.form_source = (ROOT / "apps/web/typesense-search-form.js").read_text(encoding="utf-8")
        cls.results_source = (ROOT / "apps/web/typesense-results-ui.js").read_text(encoding="utf-8")

    def test_contract_has_three_groups_seven_subtypes_and_88_fields(self):
        groups = self.contract["groups"]
        self.assertEqual({"goods", "medicines", "traditional"}, set(groups))
        self.assertEqual(7, sum(len(group["source_types"]) for group in groups.values()))
        self.assertEqual(88, sum(len(group["fields"]) for group in groups.values()))

    def test_ui_reads_capabilities_from_runtime_metadata(self):
        self.assertIn("search-contract", self.form_source)
        self.assertIn("BIDFinderSearchContractPromise", self.results_source)
        for token in ("group.fields", "field.searchable", "field.filterable", "group.sort_fields", "autocomplete", "sourceTypes", "structuredFilters", "ranges", "dateRanges"):
            self.assertIn(token, self.form_source)
        for token in ("detailFields", "fieldInfo", "ui_visibility", "backend_fallback"):
            self.assertIn(token, self.results_source)

    def test_frontend_never_emits_raw_typesense_query_syntax(self):
        for source in (self.form_source, self.results_source):
            self.assertIsNone(re.search(r"\b(query_by|filter_by|sort_by)\b", source))

    def test_expanded_search_surface_has_responsive_sanity_rules(self):
        style_source = (ROOT / "apps/web/style.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width:700px)", self.form_source)
        self.assertIn("@media (max-width:700px)", self.results_source)
        self.assertIn("overflow-x:auto", self.form_source + self.results_source)
        self.assertIn("typesense-results-ui", style_source)

    def test_capability_counts_match_phase_4b_contract(self):
        expected = {
            "goods": {"searchable": 14, "filterable": 11, "sortable": 5, "autocomplete": 5},
            "medicines": {"searchable": 16, "filterable": 13, "sortable": 4, "autocomplete": 6},
            "traditional": {"searchable": 15, "filterable": 12, "sortable": 4, "autocomplete": 6},
        }
        for group, counts in expected.items():
            fields = self.contract["groups"][group]["fields"]
            actual = {key: sum(bool(field[key]) for field in fields) for key in counts}
            self.assertEqual(counts, actual, group)


if __name__ == "__main__":
    unittest.main()
