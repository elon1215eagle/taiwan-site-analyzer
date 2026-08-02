from __future__ import annotations

import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web_mobile"


class WebMobileTest(unittest.TestCase):
    def test_reverse_recommendation_mode_is_exposed(self):
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-mode="reverse"', html)
        self.assertIn('id="reverseForm"', html)
        self.assertIn('id="reverseCountyInput"', html)
        self.assertIn('id="reverseDistrictInput"', html)
        self.assertIn('id="reverseBusinessInput"', html)
        self.assertIn('/api/recommend', html)
        self.assertIn('const DEFAULT_COUNTY = "高雄市"', html)
        self.assertIn('<option value="炸雞" selected>炸雞</option>', html)


if __name__ == "__main__":
    unittest.main()
