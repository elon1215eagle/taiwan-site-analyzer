from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone

from tw_site_analyzer.analysis import SiteSelectionAnalyzer, public_json
from tw_site_analyzer.config import AnalyzerConfig
from tw_site_analyzer.data_sources import RestaurantDataSource
from tw_site_analyzer.market_evidence import MarketEvidenceCollector, PlaceReviewSource
from tw_site_analyzer.market_report import build_market_report
from tw_site_analyzer.models import GeoScope, RestaurantFetch, RestaurantMarketFetch, RestaurantRecord


class CountingGeocoder:
    def __init__(self):
        self.calls = 0

    def geocode(self, location: str) -> GeoScope:
        self.calls += 1
        return GeoScope("高雄市", "三民區", location, 22.65, 120.32, "google_geocoding")


class FixedGeocoder:
    def __init__(self, county: str, district: str, lat: float, lon: float):
        self.county = county
        self.district = district
        self.lat = lat
        self.lon = lon

    def geocode(self, location: str) -> GeoScope:
        return GeoScope(
            self.county,
            self.district,
            location,
            self.lat,
            self.lon,
            "google_geocoding",
        )


class CountingRestaurantSource(RestaurantDataSource):
    source_name = "test_restaurants"

    def __init__(self, records: list[RestaurantRecord] | None = None, error: Exception | None = None):
        self.records = records or []
        self.error = error
        self.calls = 0

    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.records


class PartialRestaurantSource(CountingRestaurantSource):
    def nearby_evidence(self, scope: GeoScope, radius_km: float) -> RestaurantFetch:
        self.calls += 1
        return RestaurantFetch(self.records, "partial", self.source_name, "2026-07-30T00:00:00+00:00", "upstream_partial")


class SlowRestaurantSource(CountingRestaurantSource):
    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        self.calls += 1
        time.sleep(0.1)
        return self.records


class ExplicitMarketSource(CountingRestaurantSource):
    def __init__(self, all_records: list[RestaurantRecord], direct_records: list[RestaurantRecord]):
        super().__init__(all_records)
        self.direct_records = direct_records

    def market_evidence(
        self,
        scope: GeoScope,
        radius_km: float,
        business_type: str,
    ) -> RestaurantMarketFetch:
        self.calls += 1
        return RestaurantMarketFetch(
            self.records,
            self.direct_records,
            "acquired",
            "acquired",
            self.source_name,
            "2026-07-30T00:00:00+00:00",
        )


class FakeReviewSource(PlaceReviewSource):
    source_name = "test_reviews"

    def __init__(self, failing_place_ids: set[str] | None = None):
        self.failing_place_ids = failing_place_ids or set()
        self.calls: list[str] = []

    def fetch(self, place_id: str, timeout_seconds: float) -> list[dict]:
        self.calls.append(place_id)
        if place_id in self.failing_place_ids:
            raise RuntimeError("review_failed")
        return [
            {"rating": 5, "text": "好吃，服務快速"},
            {"rating": 2, "text": "排隊太慢"},
        ]


def restaurant(
    name: str,
    category: str,
    place_id: str,
    rating: float,
    reviews: int,
    *,
    lat: float = 22.65,
    lon: float = 120.32,
    price_level: int | None = 1,
) -> RestaurantRecord:
    return RestaurantRecord(
        name=name,
        address=f"高雄市三民區{name}路1號",
        county="高雄市",
        district="三民區",
        category=category,
        status="OPERATIONAL",
        lat=lat,
        lon=lon,
        place_id=place_id,
        rating=rating,
        user_ratings_total=reviews,
        price_level=price_level,
    )


class MarketEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.geocoder = CountingGeocoder()
        self.restaurant_source = CountingRestaurantSource(
            [
                restaurant("萊吉多炸雞", "炸雞店", "direct-1", 4.6, 800),
                restaurant("好味雞排", "速食店", "direct-2", 4.3, 300),
                restaurant("街角便當", "便當店", "adjacent-1", 4.5, 500),
            ]
        )
        self.review_source = FakeReviewSource()
        self.analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=self.restaurant_source,
        )

    def collector(self, **overrides) -> MarketEvidenceCollector:
        return MarketEvidenceCollector(
            self.analyzer,
            review_source=overrides.get("review_source", self.review_source),
            budget_seconds=overrides.get("budget_seconds", 1),
            now=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
            id_factory=lambda: "analysis-test-001",
        )

    def test_single_snapshot_calls_geocoder_and_restaurant_source_once(self):
        result = public_json(
            build_market_report(
                self.analyzer,
                "高雄市三民區建工路",
                "炸雞",
                evidence_collector=self.collector(),
            )
        )

        self.assertEqual(self.geocoder.calls, 1)
        self.assertEqual(self.restaurant_source.calls, 1)
        self.assertEqual(set(self.review_source.calls), {"direct-1", "direct-2", "adjacent-1"})
        self.assertEqual(result["analysis_id"], "analysis-test-001")
        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["status"], "acquired")
        self.assertEqual(result["contract_version"], "market-report-v2")
        self.assertEqual(result["market_map"]["status"], "acquired")
        self.assertEqual(result["market_map"]["point_count"], 3)
        self.assertEqual([item["competitor_level"] for item in result["top_competitors"]], ["直接競品", "直接競品", "鄰近競品"])
        self.assertNotIn("_reviews", result["top_competitors"][0])

    def test_confirmed_zero_is_not_reported_as_failure(self):
        source = CountingRestaurantSource([])
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        collector = MarketEvidenceCollector(analyzer, review_source=self.review_source, budget_seconds=1)
        result = build_market_report(analyzer, "高雄市三民區建工路", "炸雞", evidence_collector=collector)

        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["status"], "confirmed_zero")
        self.assertEqual(result["summary"]["same_type_count"], 0)
        self.assertEqual(result["summary"]["all_food_count"], 0)
        self.assertEqual(result["market_map"]["status"], "unavailable")

    def test_failed_restaurant_evidence_suppresses_estimates(self):
        source = CountingRestaurantSource(error=RuntimeError("upstream_down"))
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        result = build_market_report(
            analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(analyzer, review_source=self.review_source, budget_seconds=1),
        )

        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["status"], "failed")
        self.assertIsNone(result["summary"]["same_type_count"])
        self.assertEqual(result["revenue_performance"]["estimated_monthly_revenue_range"], [])
        self.assertEqual(result["monthly_revenue_distribution"], [])
        self.assertEqual(result["average_ticket_distribution"]["distribution"], [])

    def test_partial_restaurant_evidence_suppresses_competition_numbers(self):
        source = PartialRestaurantSource(self.restaurant_source.records)
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        result = build_market_report(
            analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(analyzer, review_source=self.review_source, budget_seconds=1),
        )

        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["status"], "partial")
        self.assertIsNone(result["summary"]["same_type_count"])
        self.assertEqual(result["revenue_performance"]["opportunity_level"], "資料不足")

    def test_review_failure_returns_partial_report_with_acquired_market_numbers(self):
        reviews = FakeReviewSource({"direct-2"})
        result = build_market_report(
            self.analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=self.collector(review_source=reviews),
        )

        self.assertEqual(result["evidence_status"]["sources"]["reviews"]["status"], "partial")
        self.assertIsInstance(result["summary"]["same_type_count"], int)
        self.assertTrue(result["monthly_revenue_distribution"])

    def test_explicit_business_search_marks_direct_competitor(self):
        direct = restaurant("KFC 建工店", "fast_food_restaurant", "kfc-1", 4.4, 900)
        adjacent = restaurant("街角便當", "便當店", "adjacent-1", 4.5, 500)
        source = ExplicitMarketSource([direct, adjacent], [direct])
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        result = build_market_report(
            analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(analyzer, review_source=self.review_source, budget_seconds=1),
        )

        self.assertEqual(source.calls, 1)
        self.assertEqual(result["summary"]["same_type_count"], 1)
        self.assertEqual(result["top_competitors"][0]["name"], "KFC 建工店")
        self.assertEqual(result["top_competitors"][0]["competitor_level"], "直接競品")
        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["direct_status"], "acquired")

    def test_timeout_is_reported_as_failure_without_fake_numbers(self):
        source = SlowRestaurantSource(self.restaurant_source.records)
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        started = time.monotonic()
        result = build_market_report(
            analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(analyzer, review_source=self.review_source, budget_seconds=0.02),
        )

        self.assertLess(time.monotonic() - started, 0.09)
        self.assertEqual(result["evidence_status"]["sources"]["restaurants"]["error_type"], "timeout")
        self.assertEqual(result["revenue_performance"]["estimated_monthly_revenue_range"], [])

    def test_different_centers_change_map_positions_and_decision_summary(self):
        east_store = restaurant(
            "東側炸雞",
            "炸雞店",
            "east-1",
            4.5,
            600,
            lat=22.65,
            lon=120.324,
        )
        source = CountingRestaurantSource([east_store])
        analyzer_a = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=FixedGeocoder("高雄市", "三民區", 22.65, 120.32),
            restaurant_source=source,
        )
        analyzer_b = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=FixedGeocoder("高雄市", "苓雅區", 22.65, 120.323),
            restaurant_source=source,
        )
        report_a = build_market_report(
            analyzer_a,
            "高雄市三民區甲地址",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(
                analyzer_a, review_source=self.review_source, budget_seconds=1
            ),
        )
        report_b = build_market_report(
            analyzer_b,
            "高雄市苓雅區乙地址",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(
                analyzer_b, review_source=self.review_source, budget_seconds=1
            ),
        )

        self.assertNotEqual(
            report_a["market_map"]["points"][0]["x"],
            report_b["market_map"]["points"][0]["x"],
        )
        self.assertIn("甲地址", report_a["summary"]["conclusion"])
        self.assertIn("乙地址", report_b["summary"]["conclusion"])
        self.assertNotEqual(report_a["summary"]["conclusion"], report_b["summary"]["conclusion"])

    def test_ticket_estimate_is_unavailable_without_price_evidence(self):
        no_price = restaurant(
            "無價位炸雞",
            "炸雞店",
            "no-price",
            4.2,
            100,
            price_level=None,
        )
        source = CountingRestaurantSource([no_price])
        analyzer = SiteSelectionAnalyzer(
            config=AnalyzerConfig(),
            geocoder=self.geocoder,
            restaurant_source=source,
        )
        result = build_market_report(
            analyzer,
            "高雄市三民區建工路",
            "炸雞",
            evidence_collector=MarketEvidenceCollector(
                analyzer, review_source=self.review_source, budget_seconds=1
            ),
        )

        self.assertFalse(result["average_ticket_distribution"]["available"])
        self.assertEqual(result["average_ticket_distribution"]["distribution"], [])


if __name__ == "__main__":
    unittest.main()
