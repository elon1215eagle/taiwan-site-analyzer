from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


def clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def level_en(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def level_zh(score: int) -> str:
    if score >= 70:
        return "高"
    if score >= 40:
        return "中"
    return "低"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return "".join(str(value).split())
