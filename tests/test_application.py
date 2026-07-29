from __future__ import annotations

import unittest

from tw_site_analyzer.analysis import SiteSelectionAnalyzer
from tw_site_analyzer.application import SiteAnalyzerApplication
from tw_site_analyzer.config import AnalyzerConfig
from tw_site_analyzer.market_contract import MARKET_REPORT_CONTRACT_VERSION
from tw_site_analyzer.observability import SERVICE_NAME


class ApplicationTest(unittest.TestCase):
    def setUp(self):
        analyzer = SiteSelectionAnalyzer(config=AnalyzerConfig())
        self.application = SiteAnalyzerApplication(analyzer)

    def test_endpoint_validation_is_owned_by_application(self):
        response = self.application.execute("/api/market-report", {"location": "", "business_type": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.payload["error"], "MARKET_REPORT_INPUT_REQUIRED")
        self.assertIn("endpoint_elapsed_ms", response.payload["meta"])

    def test_numeric_validation_returns_client_error(self):
        response = self.application.execute(
            "/api/market-report",
            {"location": "高雄市三民區建工路", "business_type": "炸雞", "radius_km": "很遠"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.payload["error"], "INVALID_NUMBER")

    def test_unknown_endpoint_returns_not_found(self):
        response = self.application.execute("/api/unknown", {})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.payload["error"], "NOT_FOUND")

    def test_market_report_uses_versioned_contract(self):
        response = self.application.execute(
            "/api/market-report",
            {"location": "高雄市三民區建工路", "business_type": "炸雞", "radius_km": 0.8},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload["json"]["contract_version"], MARKET_REPORT_CONTRACT_VERSION)

    def test_health_exposes_deployment_and_runtime_without_secrets(self):
        health = self.application.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], SERVICE_NAME)
        self.assertLessEqual({"deployment", "capabilities", "dependencies", "runtime"}, set(health))
        self.assertNotIn("api_key", str(health).lower())
        self.assertGreaterEqual(health["runtime"]["requests_total"], 0)

    def test_health_tracks_last_market_report(self):
        self.application.execute(
            "/api/market-report",
            {"location": "高雄市三民區建工路", "business_type": "炸雞"},
        )
        runtime = self.application.health()["runtime"]
        self.assertEqual(runtime["requests_by_endpoint"]["/api/market-report"], 1)
        self.assertEqual(runtime["last_market_report"]["business_type"], "炸雞")
        self.assertNotIn("input_location", runtime["last_market_report"])


if __name__ == "__main__":
    unittest.main()
