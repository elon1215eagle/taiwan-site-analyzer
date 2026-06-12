from __future__ import annotations

import json
import unittest

from tw_site_analyzer.analysis import SiteSelectionAnalyzer, flow_to_score, public_json
from tw_site_analyzer.config import AnalyzerConfig
from tw_site_analyzer.data_sources import parse_float
from tw_site_analyzer.recommendation import build_reverse_report, recommend_locations


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

    def test_parse_float_keeps_numeric_source_fields(self):
        self.assertEqual(parse_float("25.0339"), 25.0339)
        self.assertEqual(parse_float(120), 120.0)
        self.assertIsNone(parse_float(""))
        self.assertIsNone(parse_float("not-a-number"))

    def test_data_quality_is_returned_for_frontend(self):
        result = public_json(self.analyzer().analyze("高雄市三民區建工路"))
        self.assertIn("data_quality", result)
        self.assertLessEqual({"score", "level", "signals"}, set(result["data_quality"]))
        self.assertGreaterEqual(result["data_quality"]["score"], 0)
        self.assertLessEqual(result["data_quality"]["score"], 100)

    def test_flow_to_score_uses_hundred_point_scale(self):
        self.assertEqual(flow_to_score(45, "car"), 100)
        self.assertEqual(flow_to_score(35, "motorcycle"), 100)
        self.assertGreater(flow_to_score(12, "car"), 20)

    def test_reverse_recommendation_returns_ranked_candidates(self):
        result = public_json(recommend_locations(self.analyzer(), "炸雞", "高雄市", "三民區", limit=3))
        self.assertEqual(result["business_type"], "炸雞")
        self.assertLessEqual(len(result["recommendations"]), 3)
        self.assertGreater(len(result["recommendations"]), 0)
        self.assertLessEqual({"rank", "area", "fit_score", "reason", "source_analysis"}, set(result["recommendations"][0]))
        self.assertIn("GDO反向店面選址建議報告", build_reverse_report(result))


if __name__ == "__main__":
    unittest.main()
