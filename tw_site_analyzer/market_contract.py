from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MARKET_REPORT_CONTRACT_VERSION = "market-report-v3"


@dataclass(frozen=True)
class MarketSummary:
    title: str
    conclusion: str
    same_type_count: int | None
    all_food_count: int | None
    density_level: str
    data_status: str


@dataclass(frozen=True)
class RevenuePerformance:
    opportunity_level: str
    estimated_monthly_revenue_range: list[int]
    basis: str
    data_status: str
    available: bool = True


@dataclass(frozen=True)
class DistributionItem:
    range: str
    share: int
    level: str | None = None


@dataclass(frozen=True)
class TicketDistribution:
    position: str
    distribution: list[DistributionItem]
    basis: str
    available: bool = True


@dataclass(frozen=True)
class Competitor:
    rank: int
    name: str
    address: str
    category: str
    competitor_level: str
    distance_km: float | None
    rating: float | None
    user_ratings_total: int | None
    price_level: int | None
    place_id: str
    maps_url: str
    strength: str
    risk: str
    review_positive: list[str] = field(default_factory=list)
    review_negative: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewSummary:
    positive: list[str]
    negative: list[str]
    data_status: str


@dataclass(frozen=True)
class MarketMapPoint:
    name: str
    kind: str
    x: float
    y: float


@dataclass(frozen=True)
class MarketMap:
    status: str
    source: str
    center_label: str
    point_count: int
    points: list[MarketMapPoint]


@dataclass(frozen=True)
class RoadTraffic:
    available: bool
    status: str
    source: str
    station_count: int
    average_car_flow: float | None
    average_motorcycle_flow: float | None
    average_speed: float | None
    nearest_station_distance_km: float | None
    observed_at: str
    interpretation: str


@dataclass(frozen=True)
class MarketReportContract:
    analysis_id: str
    analyzed_at: str
    analysis_version: str
    analysis_elapsed_ms: int
    input_location: str
    business_type: str
    radius_km: float
    geo_scope: dict[str, Any]
    evidence_status: dict[str, Any]
    summary: MarketSummary
    market_map: MarketMap
    road_traffic: RoadTraffic
    revenue_performance: RevenuePerformance
    monthly_revenue_distribution: list[DistributionItem]
    average_ticket_distribution: TicketDistribution
    top_competitors: list[Competitor]
    review_summary: ReviewSummary
    data_requirements: list[str]
    warnings: list[str]
    contract_version: str = MARKET_REPORT_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        validate_market_report(payload)
        return payload


def validate_market_report(payload: dict[str, Any]) -> None:
    required = {
        "analysis_id",
        "analyzed_at",
        "analysis_version",
        "analysis_elapsed_ms",
        "input_location",
        "business_type",
        "radius_km",
        "geo_scope",
        "evidence_status",
        "summary",
        "market_map",
        "road_traffic",
        "revenue_performance",
        "monthly_revenue_distribution",
        "average_ticket_distribution",
        "top_competitors",
        "review_summary",
        "data_requirements",
        "warnings",
        "contract_version",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"market_report_missing_fields:{','.join(missing)}")
    if payload["contract_version"] != MARKET_REPORT_CONTRACT_VERSION:
        raise ValueError("market_report_contract_version_mismatch")
    revenue = payload["revenue_performance"]
    revenue_range = revenue["estimated_monthly_revenue_range"]
    if revenue["available"] and len(revenue_range) != 2:
        raise ValueError("market_report_revenue_range_required")
    if not revenue["available"] and revenue_range:
        raise ValueError("market_report_unavailable_revenue_must_be_empty")
    ticket = payload["average_ticket_distribution"]
    if not ticket["available"] and ticket["distribution"]:
        raise ValueError("market_report_unavailable_ticket_must_be_empty")
    market_map = payload["market_map"]
    if market_map["point_count"] != len(market_map["points"]):
        raise ValueError("market_report_map_point_count_mismatch")
    if any(
        item["kind"] not in {"direct", "adjacent"}
        or not 0 <= item["x"] <= 100
        or not 0 <= item["y"] <= 100
        for item in market_map["points"]
    ):
        raise ValueError("market_report_invalid_map_point")
    road_traffic = payload["road_traffic"]
    traffic_values = (
        road_traffic["average_car_flow"],
        road_traffic["average_motorcycle_flow"],
        road_traffic["average_speed"],
    )
    if not road_traffic["available"] and any(value is not None for value in traffic_values):
        raise ValueError("market_report_unavailable_traffic_must_not_have_values")
    valid_levels = {"直接競品", "鄰近競品"}
    if any(item["competitor_level"] not in valid_levels for item in payload["top_competitors"]):
        raise ValueError("market_report_invalid_competitor_level")
