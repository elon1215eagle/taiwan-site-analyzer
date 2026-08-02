from __future__ import annotations

import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web_mobile"


class WebMobileTest(unittest.TestCase):
    def test_reverse_recommendation_mode_is_exposed(self):
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('data-view="reverse"', html)
        self.assertIn('id="reverseForm"', html)
        self.assertIn('id="countySelect"', html)
        self.assertIn('id="districtInput"', html)
        self.assertIn('id="reverseBusiness"', html)
        self.assertIn('/api/recommend', javascript)
        self.assertIn('const DEFAULT_COUNTY = "高雄市"', javascript)
        self.assertIn('$(id).value = "炸雞"', javascript)


if __name__ == "__main__":
    unittest.main()
