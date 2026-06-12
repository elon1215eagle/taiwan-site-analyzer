from __future__ import annotations

import re
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from .models import GeoScope

COUNTY_DISTRICT_RE = re.compile(
    r"(?P<county>[\u4e00-\u9fff]{2,3}(?:市|縣))?\s*(?P<district>[\u4e00-\u9fff]{1,4}(?:區|鎮|鄉|市))?"
)


DISTRICT_CENTROIDS: dict[tuple[str, str], tuple[float, float, int]] = {
    ("台北市", "大安區"): (25.0262, 121.5435, 92),
    ("台北市", "信義區"): (25.0330, 121.5654, 95),
    ("台北市", "中山區"): (25.0644, 121.5335, 90),
    ("新北市", "板橋區"): (25.0138, 121.4618, 86),
    ("桃園市", "桃園區"): (24.9936, 121.3010, 82),
    ("台中市", "西屯區"): (24.1813, 120.6455, 88),
    ("台中市", "北區"): (24.1587, 120.6817, 84),
    ("台南市", "中西區"): (22.9920, 120.1970, 86),
    ("台南市", "東區"): (22.9816, 120.2220, 80),
    ("高雄市", "左營區"): (22.6877, 120.2952, 86),
    ("高雄市", "三民區"): (22.6500, 120.3200, 84),
    ("高雄市", "前鎮區"): (22.6044, 120.3075, 78),
    ("高雄市", "鳳山區"): (22.6273, 120.3573, 80),
}

COUNTY_CENTROIDS: dict[str, tuple[float, float, int]] = {
    "台北市": (25.0375, 121.5637, 88),
    "新北市": (25.0120, 121.4657, 78),
    "桃園市": (24.9937, 121.3009, 74),
    "台中市": (24.1477, 120.6736, 76),
    "台南市": (22.9997, 120.2270, 72),
    "高雄市": (22.6273, 120.3014, 74),
}


class TaiwanGeocoder:
    """Geocoder interface. Swap this class with TGOS, Google, or internal POI providers."""

    def __init__(self, google_maps_api_key: str | None = None):
        self.google_maps_api_key = google_maps_api_key

    def geocode(self, query: str) -> GeoScope:
        if self.google_maps_api_key:
            google_scope = self._geocode_with_google(query)
            if google_scope:
                return google_scope
        county, district, remainder = parse_location(query)
        if county and district and (county, district) in DISTRICT_CENTROIDS:
            lat, lon, _ = DISTRICT_CENTROIDS[(county, district)]
            return GeoScope(county, district, remainder, lat, lon, "district_centroid")
        if county and county in COUNTY_CENTROIDS:
            lat, lon, _ = COUNTY_CENTROIDS[county]
            return GeoScope(county, district, remainder, lat, lon, "county_centroid")
        guessed = guess_from_keywords(query)
        if guessed:
            county, district, lat, lon = guessed
            return GeoScope(county, district, query, lat, lon, "keyword_landmark")
        return GeoScope(county, district, query, None, None, "unresolved")

    def _geocode_with_google(self, query: str) -> GeoScope | None:
        params = urlencode({"address": query, "region": "tw", "language": "zh-TW", "key": self.google_maps_api_key})
        url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"
        try:
            with urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        if payload.get("status") != "OK" or not payload.get("results"):
            return None
        result = payload["results"][0]
        location = result["geometry"]["location"]
        county = ""
        district = ""
        for component in result.get("address_components", []):
            types = component.get("types", [])
            if "administrative_area_level_1" in types or "administrative_area_level_2" in types:
                county = component.get("long_name", "").replace("臺", "台")
            if "administrative_area_level_3" in types or "sublocality_level_1" in types:
                district = component.get("long_name", "").replace("臺", "台")
        parsed_county, parsed_district, remainder = parse_location(query)
        return GeoScope(
            county or parsed_county,
            district or parsed_district,
            remainder or result.get("formatted_address", query),
            float(location["lat"]),
            float(location["lng"]),
            "google_geocoding",
        )


def parse_location(query: str) -> tuple[str, str, str]:
    normalized = query.replace("臺", "台").strip()
    match = COUNTY_DISTRICT_RE.search(normalized)
    county = match.group("county") if match else ""
    district = match.group("district") if match else ""
    remainder = normalized
    if county:
        remainder = remainder.replace(county, "", 1).strip()
    if district:
        remainder = remainder.replace(district, "", 1).strip()
    return county or "", district or "", remainder


def guess_from_keywords(query: str) -> tuple[str, str, float, float] | None:
    text = query.replace("臺", "台")
    keyword_map = {
        "巨蛋": ("高雄市", "左營區", 22.6697, 120.3020),
        "瑞豐": ("高雄市", "左營區", 22.6677, 120.2996),
        "國華街": ("台南市", "中西區", 22.9940, 120.1970),
        "忠孝復興": ("台北市", "大安區", 25.0416, 121.5438),
        "台北101": ("台北市", "信義區", 25.0339, 121.5645),
        "逢甲": ("台中市", "西屯區", 24.1789, 120.6466),
    }
    for keyword, result in keyword_map.items():
        if keyword in text:
            return result
    return None


def commercial_strength_for(scope: GeoScope) -> int:
    if scope.county and scope.district and (scope.county, scope.district) in DISTRICT_CENTROIDS:
        return DISTRICT_CENTROIDS[(scope.county, scope.district)][2]
    if scope.county and scope.county in COUNTY_CENTROIDS:
        return COUNTY_CENTROIDS[scope.county][2]
    return 50
