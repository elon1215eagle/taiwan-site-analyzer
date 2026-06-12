from __future__ import annotations

import json
import unittest

from tw_site_analyzer.analysis import SiteSelectionAnalyzer, public_json
from tw_site_analyzer.config import AnalyzerConfig


def assert_no_internal_keys(value, case: unittest.TestCase):
    if isinstance(value, dict):
        for key, nested in value.items():
            case.assertFalse(key.startswith("_"), key)
            assert_no_internal_keys(nested, case)
    elif isinstance(value, list):
        for item in value:
            assert_no_internal_keys(item, case)


class SiteAnalyzerTest(unittest.TestCase):
    def analyzer(self):
        return SiteSelectionAnalyzer(config=AnalyzerConfig())

    def test_analyzer_returns_required_json_shape(self):
        result = public_json(self.analyzer().analyze("高雄市 左營區 巨蛋商圈"))
        self.assertEqual(result["input_location"], "高雄市 左營區 巨蛋商圈")
        self.assertEqual(set(result["crowd_analysis"]), {"morning", "noon", "evening", "midnight"})
        self.assertEqual(set(result["traffic_analysis"]), {"car", "motorcycle"})
        self.assertIn("restaurant_analysis", result)
        self.assertGreaterEqual(result["overall_score"], 0)
        self.assertLessEqual(result["overall_score"], 100)
        json.dumps(result, ensure_ascii=False)

    def test_crowd_items_have_required_fields(self):
        result = public_json(self.analyzer().analyze("台北市 大安區 忠孝復興站"))
        for item in result["crowd_analysis"].values():
            self.assertLessEqual({"score", "level", "reason", "data_used"}, set(item))
            self.assertGreaterEqual(item["score"], 0)
            self.assertLessEqual(item["score"], 100)
            self.assertIn(item["level"], {"high", "medium", "low"})

    def test_warnings_are_explicit_when_using_proxy_data(self):
        result = public_json(self.analyzer().analyze("台南市 中西區 國華街"))
        joined = "\n".join(result["warnings"] + result["assumptions"])
        self.assertTrue("推估" in joined or "代理" in joined)

    def test_public_json_does_not_leak_internal_fields(self):
        result = public_json(self.analyzer().analyze("高雄市 左營區 巨蛋商圈"))
        assert_no_internal_keys(result, self)


if __name__ == "__main__":
    unittest.main()
