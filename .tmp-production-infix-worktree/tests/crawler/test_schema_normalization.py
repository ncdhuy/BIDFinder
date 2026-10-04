import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "crawler_engine"))
from schema_normalization_shared import (  # noqa: E402
    clean_numeric_series,
    collapse_duplicate_columns,
    drop_header_legend_rows,
    drop_invalid_value_rows,
)


class SchemaNormalizationTest(unittest.TestCase):
    def test_numeric_formats(self):
        actual = clean_numeric_series(pd.Series(["1.234", "1.234,50", "2,500.25", "-10", "N/A"]))
        self.assertEqual([1234.0, 1234.5, 2500.25, -10.0], actual.iloc[:4].tolist())
        self.assertTrue(pd.isna(actual.iloc[4]))

    def test_duplicate_columns_take_first_non_empty_value(self):
        frame = pd.DataFrame([[1, None, "a"], [None, 2, "b"]], columns=["value", "value", "name"])
        actual = collapse_duplicate_columns(frame)
        self.assertEqual([1.0, 2.0], actual["value"].tolist())
        self.assertEqual(["value", "name"], actual.columns.tolist())

    def test_group_legend_and_sparse_rows(self):
        fixture = pd.read_csv(ROOT / "tests" / "fixtures" / "normalization_cases.csv", dtype=str)
        without_legends = drop_header_legend_rows(fixture)
        self.assertEqual(["Thuốc A", "Dòng thiếu giá", "Tổng cộng"], without_legends["Tên"].tolist())

        normalized = drop_invalid_value_rows(without_legends, "MEDICINE_STANDARD")
        self.assertEqual(["Thuốc A"], normalized["Tên"].tolist())
        self.assertEqual(2468.0, normalized["Thành tiền (VND)"].iloc[0])


if __name__ == "__main__":
    unittest.main()
