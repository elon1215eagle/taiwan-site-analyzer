from __future__ import annotations

from dataclasses import dataclass
from math import pi
from statistics import median

SUPPORTED_BUSINESSES = ("炸雞", "火鍋", "燒烤", "便當")
PRIMARY_RADIUS_KM = {"炸雞": 1.0, "便當": 1.0, "火鍋": 2.0, "燒烤": 2.0}
COMPARISON_RADII_KM = (0.5, 1.0, 2.0, 3.0)
MODEL_VERSION = "gdo-expert-v1.0"

DIMENSION_LABELS = {
    "demand": "商圈需求",
    "competition": "同業競爭",
    "accessibility": "交通可達性",
    "price": "消費與價格帶",
    "revenue": "營收潛力",
}

BUSINESS_WEIGHTS = {
    "炸雞": {"demand": 0.30, "competition": 0.25, "accessibility": 0.20, "price": 0.10, "revenue": 0.15},
    "便當": {"demand": 0.30, "competition": 0.20, "accessibility": 0.25, "price": 0.10, "revenue": 0.15},
    "火鍋": {"demand": 0.25, "competition": 0.25, "accessibility": 0.20, "price": 0.15, "revenue": 0.15},
    "燒烤": {"demand": 0.30, "competition": 0.25, "accessibility": 0.15, "price": 0.15, "revenue": 0.15},
}

PRICE_LEVEL_BANDS = {
    0: (60, 100),
    1: (100, 180),
    2: (180, 350),
    3: (350, 700),
    4: (700, 1200),
}


@dataclass(frozen=True)
class PropertyInput:
    monthly_rent: int | None = None
    area_ping: float | None = None

    def to_dict(self) -> dict:
        rent_per_ping = None
        if self.monthly_rent is not None and self.area_ping:
            rent_per_ping = round(self.monthly_rent / self.area_ping)
        return {
            "monthly_rent": self.monthly_rent,
            "area_ping": self.area_ping,
            "rent_per_ping": rent_per_ping,
        }


def validate_business_type(value: str) -> str:
    business_type = value.strip()
    if business_type not in SUPPORTED_BUSINESSES:
        raise ValueError("unsupported_business_type")
    return business_type


def primary_radius_for(business_type: str) -> float:
    return PRIMARY_RADIUS_KM[validate_business_type(business_type)]


def score_market(
    business_type: str,
    direct_competitors: list[dict],
    all_stores: list[dict],
    traffic: dict,
    evidence: dict,
    onsite_count: int | None = None,
) -> dict:
    business_type = validate_business_type(business_type)
    radius = primary_radius_for(business_type)
    area = max(pi * radius * radius, 0.1)
    direct_density = len(direct_competitors) / area
    food_density = len(all_stores) / area
    review_counts = [
        int(item["user_ratings_total"])
        for item in direct_competitors
        if item.get("user_ratings_total") is not None
    ]
    review_activity = min(100, median(review_counts) / 8) if review_counts else 0

    demand_score = clamp(round(min(100, food_density * 3.4) * 0.65 + review_activity * 0.35))
    if onsite_count is not None:
        demand_score = clamp(round(demand_score * 0.75 + min(100, onsite_count * 2) * 0.25))

    if not direct_competitors:
        competition_score = 55
    else:
        saturation_penalty = max(0.0, direct_density - 4.0) * 7.5
        leader_pressure = min(25.0, review_activity * 0.25)
        competition_score = clamp(round(88 - saturation_penalty - leader_pressure))

    car_flow = number_or_zero(traffic.get("average_car_flow"))
    motorcycle_flow = number_or_zero(traffic.get("average_motorcycle_flow"))
    station_count = int(traffic.get("station_count") or 0)
    accessibility_score = (
        clamp(round(min(100, car_flow / 12 + motorcycle_flow / 8 + station_count * 4)))
        if traffic.get("available")
        else 0
    )

    ticket = estimate_ticket_band(direct_competitors)
    price_score = 72 if ticket["available"] else 0
    revenue_score = (
        clamp(round(demand_score * 0.65 + price_score * 0.35))
        if ticket["available"]
        else 0
    )

    raw_scores = {
        "demand": demand_score,
        "competition": competition_score,
        "accessibility": accessibility_score,
        "price": price_score,
        "revenue": revenue_score,
    }
    weights = BUSINESS_WEIGHTS[business_type]
    available_weight = sum(
        weight
        for key, weight in weights.items()
        if key not in {"price", "revenue"} or ticket["available"]
    )
    overall = round(
        sum(
            raw_scores[key] * weight
            for key, weight in weights.items()
            if key not in {"price", "revenue"} or ticket["available"]
        )
        / max(available_weight, 0.01)
    )
    confidence = confidence_score(evidence, ticket["available"], onsite_count is not None)
    decision = screening_decision(overall, confidence)

    dimensions = []
    for key in DIMENSION_LABELS:
        available = key not in {"price", "revenue"} or ticket["available"]
        dimensions.append(
            {
                "key": key,
                "label": DIMENSION_LABELS[key],
                "score": raw_scores[key] if available else None,
                "weight": round(weights[key] * 100),
                "available": available,
            }
        )
    return {
        "overall_score": overall,
        "confidence_score": confidence,
        "decision": decision,
        "dimensions": dimensions,
        "model_version": MODEL_VERSION,
        "score_notice": "選址分數為候選初篩指數，不代表開店成功率或投資報酬保證。",
        "ticket": ticket,
        "revenue_scenarios": estimate_revenue_scenarios(
            direct_competitors,
            all_stores,
            traffic,
            ticket,
            onsite_count,
        ),
    }


def confidence_score(evidence: dict, ticket_available: bool, onsite_available: bool) -> int:
    weights = {
        "geocode": 20,
        "all_market": 20,
        "direct_competition": 20,
        "reviews": 15,
        "traffic": 10,
    }
    status_values = {"acquired": 1.0, "confirmed_zero": 0.85, "partial": 0.55, "failed": 0.0}
    score = 0.0
    for key, weight in weights.items():
        status = str(evidence.get(key, {}).get("status", "failed"))
        score += weight * status_values.get(status, 0.0)
    if ticket_available:
        score += 10
    if onsite_available:
        score += 5
    return clamp(round(score))


def screening_decision(score: int, confidence: int) -> str:
    if confidence < 60:
        return "補資料後再評估"
    if score >= 75 and confidence >= 70:
        return "優先現勘"
    if score < 55:
        return "不列入優先候選"
    return "補資料後再評估"


def estimate_ticket_band(stores: list[dict]) -> dict:
    levels = [
        int(item["price_level"])
        for item in stores
        if item.get("price_level") is not None and int(item["price_level"]) in PRICE_LEVEL_BANDS
    ]
    if not levels:
        return {
            "available": False,
            "source_level": "unavailable",
            "low": None,
            "median": None,
            "high": None,
            "basis": "未取得公開菜單價格或價位等級，不產生客單價數字。",
        }
    bands = [PRICE_LEVEL_BANDS[level] for level in levels]
    low = round(median([item[0] for item in bands]))
    high = round(median([item[1] for item in bands]))
    return {
        "available": True,
        "source_level": "public_price_level",
        "low": low,
        "median": round((low + high) / 2),
        "high": high,
        "basis": f"依 {len(levels)} 間同業公開價位等級換算概略市場價格帶；非實際交易客單價。",
    }


def estimate_revenue_scenarios(
    direct_competitors: list[dict],
    all_stores: list[dict],
    traffic: dict,
    ticket: dict,
    onsite_count: int | None,
) -> dict:
    if not ticket["available"]:
        return {
            "available": False,
            "basis": "缺少可驗證的市場客單價帶，本次不產生營收情境。",
            "monthly_operating_days": 30,
            "onsite_flow_included": onsite_count is not None,
            "scenarios": [],
        }
    review_counts = [
        int(item["user_ratings_total"])
        for item in direct_competitors
        if item.get("user_ratings_total") is not None
    ]
    review_signal = median(review_counts) / 60 if review_counts else 0
    traffic_signal = 0
    if traffic.get("available"):
        traffic_signal = (
            number_or_zero(traffic.get("average_car_flow")) / 150
            + number_or_zero(traffic.get("average_motorcycle_flow")) / 120
        )
    onsite_signal = onsite_count / 6 if onsite_count is not None else 0
    base_orders = clamp(round(22 + len(all_stores) * 0.65 + review_signal + traffic_signal + onsite_signal), 12, 220)
    assumptions = (("保守", 0.70, ticket["low"]), ("基準", 1.0, ticket["median"]), ("樂觀", 1.30, ticket["high"]))
    scenarios = []
    for label, order_factor, ticket_value in assumptions:
        daily_orders = max(1, round(base_orders * order_factor))
        scenarios.append(
            {
                "label": label,
                "daily_orders": daily_orders,
                "ticket": ticket_value,
                "monthly_operating_days": 30,
                "monthly_revenue": daily_orders * ticket_value * 30,
            }
        )
    return {
        "available": True,
        "basis": "推估日訂單數 × 市場客單價帶 × 每月 30 個營業日；未使用店家 POS 或真實交易資料。",
        "monthly_operating_days": 30,
        "onsite_flow_included": onsite_count is not None,
        "scenarios": scenarios,
    }


def number_or_zero(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def clamp(value: int | float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, round(value)))
