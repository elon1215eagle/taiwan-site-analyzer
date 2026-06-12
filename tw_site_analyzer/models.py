from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Level = Literal["high", "medium", "low"]
ChineseLevel = Literal["高", "中", "低"]


@dataclass(frozen=True)
class GeoScope:
    county: str
    district: str
    address_or_landmark: str
    lat: float | None = None
    lon: float | None = None
    precision: str = "unknown"


@dataclass(frozen=True)
class RestaurantRecord:
    name: str
    address: str
    county: str = ""
    district: str = ""
    category: str = "未分類餐飲"
    status: str = ""
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class TrafficRecord:
    lat: float
    lon: float
    car_flow: float | None = None
    motorcycle_flow: float | None = None
    speed: float | None = None
    timestamp: str = ""
    source: str = ""
    distance_km: float | None = None


@dataclass
class Evidence:
    data_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
