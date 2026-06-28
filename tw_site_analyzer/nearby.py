from __future__ import annotations

from .cleaning import active_restaurants
from .analysis import SiteSelectionAnalyzer
from .utils import haversine_km


def nearby_stores(
    analyzer: SiteSelectionAnalyzer,
    location: str,
    radius_km: float = 1.0,
    keyword: str = "",
    limit: int = 30,
) -> dict:
    radius_km = max(0.1, min(float(radius_km or 1.0), 5.0))
    limit = max(1, min(int(limit or 30), 60))
    keyword = keyword.strip()
    scope = analyzer.geocoder.geocode(location)
    records = active_restaurants(analyzer.restaurant_source.nearby(scope, radius_km))

    if keyword:
        normalized_keyword = keyword.lower()
        records = [
            record
            for record in records
            if normalized_keyword in record.name.lower()
            or normalized_keyword in record.category.lower()
            or normalized_keyword in record.address.lower()
        ]

    stores = []
    for record in records:
        distance_km = None
        if scope.lat is not None and scope.lon is not None and record.lat is not None and record.lon is not None:
            distance_km = haversine_km(scope.lat, scope.lon, record.lat, record.lon)
        stores.append(
            {
                "name": record.name,
                "address": record.address,
                "category": record.category,
                "status": record.status,
                "distance_km": round(distance_km, 2) if distance_km is not None else None,
                "place_id": record.place_id,
                "rating": record.rating,
                "user_ratings_total": record.user_ratings_total,
                "price_level": record.price_level,
                "reviews": record.reviews,
                "maps_url": build_maps_url(record.name, record.address),
            }
        )

    stores.sort(key=lambda item: item["distance_km"] if item["distance_km"] is not None else 999999)
    stores = stores[:limit]

    warnings = []
    if scope.precision != "google_geocoding":
        warnings.append("目前地址定位不是 Google 精準座標，附近店家結果可能只適合初步判斷。")
    if not stores:
        warnings.append("查無附近店家資料。請確認已設定 GOOGLE_MAPS_API_KEY，或改用更完整地址再查。")

    return {
        "input_location": location,
        "query": {
            "radius_km": radius_km,
            "keyword": keyword,
            "limit": limit,
        },
        "geo_scope": {
            "county": scope.county,
            "district": scope.district,
            "address_or_landmark": scope.address_or_landmark,
            "lat": scope.lat,
            "lon": scope.lon,
            "precision": scope.precision,
        },
        "store_count": len(stores),
        "stores": stores,
        "warnings": warnings,
    }


def build_nearby_report(result: dict) -> str:
    lines = [
        "附近店家查詢結果",
        "",
        f"查詢位置：{result['input_location']}",
        f"查詢半徑：{result['query']['radius_km']} km",
        f"店家數量：{result['store_count']} 間",
        "",
    ]
    if result["stores"]:
        lines.append("店家清單：")
        for index, store in enumerate(result["stores"], start=1):
            distance = f"{store['distance_km']} km" if store["distance_km"] is not None else "距離未取得"
            lines.append(f"{index}. {store['name']}｜{store['category']}｜{distance}")
            if store["address"]:
                lines.append(f"   地址：{store['address']}")
    if result["warnings"]:
        lines.append("")
        lines.append("注意事項：")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines)


def build_maps_url(name: str, address: str) -> str:
    query = " ".join(part for part in (name, address) if part).strip()
    if not query:
        return ""
    from urllib.parse import quote_plus

    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
