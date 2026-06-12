from __future__ import annotations

from .cleaning import active_restaurants, average_flow, summarize_categories
from .config import AnalyzerConfig
from .data_sources import RestaurantDataSource, TrafficDataSource, build_data_sources
from .geo import TaiwanGeocoder, commercial_strength_for
from .models import Evidence, GeoScope
from .utils import clamp, haversine_km, level_en, level_zh


class SiteSelectionAnalyzer:
    def __init__(
        self,
        config: AnalyzerConfig | None = None,
        geocoder: TaiwanGeocoder | None = None,
        restaurant_source: RestaurantDataSource | None = None,
        traffic_source: TrafficDataSource | None = None,
    ):
        self.config = config or AnalyzerConfig.from_env()
        self.geocoder = geocoder or TaiwanGeocoder(self.config.google_maps_api_key)
        if restaurant_source is None or traffic_source is None:
            built_restaurants, built_traffic = build_data_sources(self.config)
            restaurant_source = restaurant_source or built_restaurants
            traffic_source = traffic_source or built_traffic
        self.restaurant_source = restaurant_source
        self.traffic_source = traffic_source

    def analyze(self, input_location: str) -> dict:
        scope = self.geocoder.geocode(input_location)
        evidence = Evidence()
        if scope.precision == "google_geocoding":
            evidence.data_used.append("Google Geocoding API")
        elif scope.precision in ("district_centroid", "county_centroid", "keyword_landmark"):
            evidence.data_used.append(f"內建地理編碼代理資料:{scope.precision}")
            evidence.warnings.append("目前未接入正式 TGOS/Google 地理編碼，座標可能為行政區或地標代理座標。")
        else:
            evidence.warnings.append("無法解析精準座標，分析改用縣市/行政區與文字匹配推估。")

        restaurant = self._analyze_restaurants(scope, evidence)
        traffic = self._analyze_traffic(scope, evidence)
        crowd = self._analyze_crowd(scope, restaurant, traffic, evidence)
        overall_score = self._overall_score(crowd, traffic, restaurant)
        data_quality = self._data_quality(scope, restaurant, traffic)

        return {
            "input_location": input_location,
            "geo_scope": {
                "county": scope.county,
                "district": scope.district,
                "address_or_landmark": scope.address_or_landmark,
            },
            "crowd_analysis": crowd,
            "traffic_analysis": traffic,
            "restaurant_analysis": restaurant,
            "overall_score": overall_score,
            "overall_conclusion": self._overall_conclusion(overall_score, restaurant, traffic),
            "data_quality": data_quality,
            "warnings": dedupe(evidence.warnings),
            "assumptions": dedupe(evidence.assumptions),
        }

    def _analyze_restaurants(self, scope: GeoScope, evidence: Evidence) -> dict:
        counts_by_radius = {}
        max_radius = max(self.config.restaurant_radii_km)
        records_3km = active_restaurants(self.restaurant_source.nearby(scope, max_radius))
        for radius in self.config.restaurant_radii_km:
            records = restaurants_within_radius(scope, records_3km, radius)
            counts_by_radius[f"{int(radius)}km"] = len(records)

        if records_3km:
            evidence.data_used.append("餐飲資料:Google Places 或 TW_RESTAURANT_CSV")
        else:
            evidence.warnings.append("未提供或未命中餐飲業登記/店家資料，餐飲密度採商業強度代理推估。")
            evidence.assumptions.append("餐飲店數缺資料時，以行政區商業強度推估競爭程度，不代表實際店數。")

        nearby_count = len(records_3km)
        if nearby_count:
            density_score = min(100, nearby_count * 2)
            category_summary = summarize_categories(records_3km)
            reason = f"3km 內命中 {nearby_count} 筆餐飲資料；1/2/3km 分別為 {counts_by_radius}。"
        else:
            density_score = commercial_strength_for(scope)
            category_summary = [{"category": "資料不足，需接入商業登記或地圖店家資料", "count": 0}]
            reason = "未命中可計算半徑的餐飲資料，改用行政區商業強度、商圈屬性作為推估。"

        density_level = level_zh(density_score)
        competition_score = clamp(density_score * 0.75 + commercial_strength_for(scope) * 0.25)
        return {
            "nearby_count": nearby_count,
            "density_level": density_level,
            "category_summary": category_summary,
            "competition_level": level_zh(competition_score),
            "reason": reason,
            "counts_by_radius": counts_by_radius,
            "_score": density_score,
            "_counts_by_radius": counts_by_radius,
        }

    def _analyze_traffic(self, scope: GeoScope, evidence: Evidence) -> dict:
        records = self.traffic_source.nearest(scope)
        car_avg = average_flow(records, "car_flow")
        motorcycle_avg = average_flow(records, "motorcycle_flow")
        if records:
            evidence.data_used.append("交通資料:TDX VD 或 TW_TRAFFIC_VD_JSON")
        else:
            evidence.warnings.append("未提供或未命中道路監測點 VD 資料，車潮採行政區商業強度代理推估。")
            evidence.assumptions.append("車潮缺資料時，以商業強度推估；商圈型區域通常機車流量高於汽車。")

        car_score = flow_to_score(car_avg, "car") if car_avg is not None else clamp(commercial_strength_for(scope) * 0.85)
        motorcycle_score = (
            flow_to_score(motorcycle_avg, "motorcycle")
            if motorcycle_avg is not None
            else clamp(commercial_strength_for(scope) * 0.95)
        )
        data_used = ["TDX VD/本地快照"] if records else ["行政區商業強度代理推估"]
        nearest_distance = min((record.distance_km for record in records if record.distance_km is not None), default=None)
        return {
            "car": {
                "score": car_score,
                "level": level_en(car_score),
                "reason": traffic_reason(car_avg, car_score, "汽車", records),
                "data_used": data_used,
            },
            "motorcycle": {
                "score": motorcycle_score,
                "level": level_en(motorcycle_score),
                "reason": traffic_reason(motorcycle_avg, motorcycle_score, "機車", records),
                "data_used": data_used,
            },
            "_record_count": len(records),
            "_has_car_flow": car_avg is not None,
            "_has_motorcycle_flow": motorcycle_avg is not None,
            "_nearest_vd_distance_km": nearest_distance,
        }

    def _analyze_crowd(self, scope: GeoScope, restaurant: dict, traffic: dict, evidence: Evidence) -> dict:
        commercial = commercial_strength_for(scope)
        restaurant_score = restaurant["_score"]
        car_score = traffic["car"]["score"]
        motorcycle_score = traffic["motorcycle"]["score"]
        base = commercial * 0.38 + restaurant_score * 0.28 + motorcycle_score * 0.20 + car_score * 0.14
        evidence.assumptions.append("人潮分數以人口/商業強度、餐飲聚集度、汽機車流量加權合成；若未接入精準人流，皆屬推估值。")
        evidence.assumptions.append("早上偏通勤與早餐需求；中午偏上班/商業用餐；晚上偏餐飲與逛街；半夜偏夜市、娛樂與交通節點。")
        time_adjustments = {
            "morning": (-4, "早上以通勤、早餐與上班族活動為主。"),
            "noon": (6, "中午受商業密度與餐飲聚集度拉動。"),
            "evening": (10, "晚上通常是餐飲消費與逛街人潮高峰。"),
            "midnight": (-22, "半夜需依夜市、娛樂、車站等特殊場景才會放大；目前保守推估。"),
        }
        result = {}
        for period, (adjustment, reason) in time_adjustments.items():
            score = clamp(base + adjustment)
            result[period] = {
                "score": score,
                "level": level_en(score),
                "reason": f"{reason} 本分數為推估值，合成基礎含商業強度、車潮與餐飲密度。",
                "data_used": ["行政區商業強度代理", "餐飲密度", "汽機車流量/代理車潮"],
            }
        return result

    def _overall_score(self, crowd: dict, traffic: dict, restaurant: dict) -> int:
        crowd_avg = sum(item["score"] for item in crowd.values()) / 4
        traffic_avg = (traffic["car"]["score"] + traffic["motorcycle"]["score"]) / 2
        competition_penalty = max(0, restaurant["_score"] - 75) * 0.18
        return clamp(crowd_avg * 0.45 + traffic_avg * 0.30 + restaurant["_score"] * 0.25 - competition_penalty)

    def _overall_conclusion(self, score: int, restaurant: dict, traffic: dict) -> str:
        if score >= 75:
            return "具備高商圈可行性，可進入租金、坪效、競品菜單與尖峰動線的第二階段評估。"
        if score >= 55:
            return "具備中等可行性，建議補強實地人流、租金成本與競品營業額推估後再決策。"
        return "目前可行性偏低或資料不足，建議先補齊精準地理編碼、餐飲店家與道路監測資料。"

    def _data_quality(self, scope: GeoScope, restaurant: dict, traffic: dict) -> dict:
        signals = []
        score = 0
        if scope.precision == "google_geocoding":
            score += 35
            signals.append("地址已由 Google Geocoding 解析為座標。")
        elif scope.lat is not None and scope.lon is not None:
            score += 20
            signals.append("已取得代理座標，但精準度低於正式地理編碼。")
        else:
            signals.append("未取得座標，半徑型分析可信度較低。")

        nearby_count = restaurant.get("nearby_count", 0)
        if nearby_count >= 40:
            score += 30
            signals.append("餐飲樣本數充足，競爭密度判斷較穩。")
        elif nearby_count >= 10:
            score += 20
            signals.append("餐飲樣本數中等，可作初步判斷。")
        elif nearby_count > 0:
            score += 10
            signals.append("餐飲樣本數偏少，可能低估熱區密度。")
        else:
            signals.append("餐飲資料未命中，餐飲競爭主要為代理推估。")

        traffic_records = traffic.get("_record_count", 0)
        if traffic_records and traffic.get("_has_car_flow") and traffic.get("_has_motorcycle_flow"):
            score += 30
            signals.append("已命中附近 VD 且含汽車、機車流量。")
        elif traffic_records:
            score += 18
            signals.append("已命中附近 VD，但車種流量欄位不完整。")
        else:
            signals.append("未命中附近 VD，車潮為代理推估。")

        nearest_vd_distance = traffic.get("_nearest_vd_distance_km")
        if nearest_vd_distance is not None and nearest_vd_distance <= 1.5:
            score += 5
            signals.append("最近 VD 距離在 1.5km 內。")

        quality_score = clamp(score)
        return {
            "score": quality_score,
            "level": level_en(quality_score),
            "signals": signals,
        }


def flow_to_score(flow: float, mode: str) -> int:
    high_flow_threshold = 45 if mode == "car" else 35
    return clamp(flow / high_flow_threshold * 100)


def traffic_reason(avg: float | None, score: int, label: str, records: list) -> str:
    if avg is None:
        return f"未取得附近 VD {label}流量，分數 {score} 為商業強度代理推估。"
    return f"附近 {len(records)} 個道路監測點平均{label}流量約 {avg:.0f}，換算為 {score}/100。"


def restaurants_within_radius(scope: GeoScope, records: list, radius_km: float) -> list:
    if scope.lat is None or scope.lon is None:
        return records
    filtered = []
    for record in records:
        if record.lat is None or record.lon is None:
            filtered.append(record)
            continue
        if haversine_km(scope.lat, scope.lon, record.lat, record.lon) <= radius_km:
            filtered.append(record)
    return filtered


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def public_json(result: dict) -> dict:
    clean = {}
    for key, value in result.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            clean[key] = public_json(value)
        else:
            clean[key] = value
    return clean
