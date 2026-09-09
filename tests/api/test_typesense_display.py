from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from typesense_display import (  # noqa: E402
    normalize_bidder_count,
    normalize_location,
    normalize_year,
)


class TypesenseDisplayTest(unittest.TestCase):
    def test_bidder_count_uses_half_up_rounding(self):
        self.assertEqual(1, normalize_bidder_count(1.3))
        self.assertEqual(2, normalize_bidder_count(1.7))
        self.assertEqual(2, normalize_bidder_count(1.5))

    def test_year_preserves_range_values(self):
        self.assertEqual("2024-2025", normalize_year("2024-2025"))
        self.assertIsNone(normalize_year("2025-2024"))

    def test_location_display_keeps_locality_before_province(self):
        self.assertEqual(
            "Xã Dầu Tiếng, Thành phố Hồ Chí Minh",
            normalize_location("Thành phố Hồ Chí Minh, Xã Dầu Tiếng"),
        )

    def test_location_object_display_uses_locality_before_province(self):
        self.assertEqual(
            "Huyện Dầu Tiếng, Tỉnh Bình Dương",
            normalize_location({
                "districtName": "Huyện Dầu Tiếng",
                "provName": "Tỉnh Bình Dương",
            }),
        )


if __name__ == "__main__":
    unittest.main()
