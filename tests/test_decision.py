import unittest

from tw_site_analyzer.decision import (
    PropertyInput,
    estimate_ticket_band,
    primary_radius_for,
    score_market,
    screening_decision,
    validate_business_type,
)


class DecisionTest(unittest.TestCase):
    def test_supported_businesses_have_fixed_radius(self):
        self.assertEqual(primary_radius_for("炸雞"), 1.0)
        self.assertEqual(primary_radius_for("便當"), 1.0)
        self.assertEqual(primary_radius_for("火鍋"), 2.0)
        self.assertEqual(primary_radius_for("燒烤"), 2.0)
        with self.assertRaises(ValueError):
            validate_business_type("飲料")

    def test_screening_gate_blocks_low_confidence(self):
        self.assertEqual(screening_decision(90, 59), "補資料後再評估")
        self.assertEqual(screening_decision(80, 75), "優先現勘")
        self.assertEqual(screening_decision(40, 70), "不列入優先候選")

    def test_ticket_has_no_business_default(self):
        result = estimate_ticket_band([{"name": "競品", "price_level": None}])
        self.assertFalse(result["available"])
        self.assertIsNone(result["median"])

    def test_score_has_five_dimensions_and_three_revenue_scenarios(self):
        stores = [
            {"name": "甲", "price_level": 1, "user_ratings_total": 420},
            {"name": "乙", "price_level": 2, "user_ratings_total": 180},
        ]
        evidence = {
            key: {"status": "acquired"}
            for key in ("geocode", "all_market", "direct_competition", "reviews", "traffic")
        }
        result = score_market(
            "炸雞",
            stores,
            stores * 8,
            {
                "available": True,
                "average_car_flow": 600,
                "average_motorcycle_flow": 420,
                "station_count": 3,
            },
            evidence,
        )
        self.assertEqual(len(result["dimensions"]), 5)
        self.assertEqual(len(result["revenue_scenarios"]["scenarios"]), 3)
        self.assertGreaterEqual(result["confidence_score"], 70)

    def test_property_calculates_rent_per_ping(self):
        self.assertEqual(PropertyInput(60000, 30).to_dict()["rent_per_ping"], 2000)


if __name__ == "__main__":
    unittest.main()
