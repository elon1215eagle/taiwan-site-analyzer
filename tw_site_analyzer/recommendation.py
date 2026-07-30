from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .analysis import public_json
from .cleaning import active_restaurants
from .decision import SUPPORTED_BUSINESSES, validate_business_type
from .geo import DISTRICT_CENTROIDS
from .nearby import build_maps_url
from .population import DistrictPopulationSource
from .utils import clamp, level_en


COUNTY_DISTRICTS = {
    "台北市": ["大安區", "信義區", "中山區", "松山區", "士林區", "內湖區"],
    "新北市": ["板橋區", "新莊區", "中和區", "永和區", "三重區", "新店區"],
    "桃園市": ["桃園區", "中壢區", "龜山區", "八德區", "蘆竹區", "平鎮區"],
    "台中市": ["西屯區", "北區", "南屯區", "北屯區", "西區", "豐原區"],
    "台南市": ["中西區", "東區", "北區", "永康區", "安平區", "南區"],
    "高雄市": ["三民區", "左營區", "鳳山區", "前鎮區", "苓雅區", "鼓山區", "新興區", "楠梓區"],
}


AREA_ANCHORS = {
    "food": ["商圈", "夜市", "車站", "市場", "學區", "主要道路"],
    "lunchbox": ["商辦", "科工館", "學區", "車站", "市場", "主要道路"],
    "beauty": ["商圈", "百貨", "住宅區", "捷運站", "主要道路", "生活圈"],
    "default": ["商圈", "車站", "市場", "主要道路", "住宅區", "學區"],
}


@dataclass(frozen=True)
class BusinessProfile:
    key: str
    label: str
    crowd_weights: dict[str, float]
    traffic_weight: float
    restaurant_weight: float
    saturation_start: int
    saturation_factor: float
    anchors: list[str]
    strategy: str


def recommend_locations(
    analyzer,
    business_type: str,
    county: str,
    district: str = "",
    limit: int = 5,
    population_source: DistrictPopulationSource | None = None,
) -> dict:
    business_type = validate_business_type(business_type)
    profile = business_profile_for(business_type)
    if district.strip():
        return recommend_real_areas(analyzer, business_type, county, district, limit=5)
    source = population_source or DistrictPopulationSource()
    warnings = []
    try:
        population_rows = source.districts(county)
    except Exception:
        population_rows = []
        warnings.append("戶政司行政區人口資料暫時無法取得，本次不產生行政區排序。")
    candidates = [
        {
            "label": item["district"],
            "query": f"{county}{item['district']}",
            "population": item["population"],
            "population_source": item["source"],
            "population_data_as_of": item["data_as_of"],
        }
        for item in population_rows[:6]
    ]
    recommendations = []

    if not candidates:
        warnings.append("目前沒有足夠的真實行政區證據可供排序。")

    for candidate in candidates:
        raw = analyzer.analyze(candidate["query"])
        fit = business_fit_score(raw, profile)
        recommendations.append(
            {
                "rank": 0,
                "area": candidate["label"],
                "candidate_location": candidate["query"],
                "fit_score": fit["score"],
                "level": level_en(fit["score"]),
                "reason": fit["reason"],
                "suggested_action": fit["suggested_action"],
                "confidence_score": min(
                    100,
                    int(raw.get("data_quality", {}).get("score", 0)) + 10,
                ),
                "population": candidate["population"],
                "population_source": candidate["population_source"],
                "population_data_as_of": candidate["population_data_as_of"],
                "source_analysis": compact_source_analysis(raw),
            }
        )

    recommendations.sort(key=lambda item: item["fit_score"], reverse=True)
    for index, item in enumerate(recommendations[:limit], 1):
        item["rank"] = index

    result = {
        "business_type": business_type,
        "business_profile": profile.label,
        "geo_scope": {"county": county, "district": district},
        "stage": "district",
        "recommendations": recommendations[:3],
        "overall_conclusion": reverse_conclusion(recommendations[:3], profile),
        "warnings": warnings,
        "assumptions": [
            "反向選址會先產生候選行政區或候選商圈，再沿用單點選址模型計算人潮、車潮、餐飲/商業密度。",
            "若未接入精準人流資料，早中晚半夜人潮仍以人口/商業強度、VD 車流、餐飲或商業密度代理推估。",
            "美容、零售等非餐飲業態目前以餐飲密度作為商業活躍度代理，未代表同業競品完整數量。",
        ],
    }
    return result


def recommend_real_areas(
    analyzer,
    business_type: str,
    county: str,
    district: str,
    limit: int = 5,
) -> dict:
    query = f"{county.replace('臺', '台').strip()}{district.replace('臺', '台').strip()}"
    scope = analyzer.geocoder.geocode(query)
    fetch = analyzer.restaurant_source.market_evidence(scope, 5.0, business_type)
    records = active_restaurants(fetch.all_records)
    road_groups: dict[str, list] = defaultdict(list)
    for record in records:
        if not belongs_to_district(record.address, record.district, district):
            continue
        road = extract_road_name(record.address)
        if road:
            road_groups[road].append(record)
    ranked = []
    for road, items in road_groups.items():
        direct = [item for item in items if business_matches(item.category, business_type)]
        ratings = [float(item.rating) for item in items if item.rating is not None]
        reviews = [int(item.user_ratings_total) for item in items if item.user_ratings_total is not None]
        activity = len(items)
        score = clamp(
            48
            + min(28, activity * 3)
            + min(12, len(direct) * 3)
            + min(12, (sum(reviews) / max(len(reviews), 1)) / 80 if reviews else 0)
        )
        confidence = clamp(35 + min(45, activity * 5) + (10 if ratings else 0))
        ranked.append(
            {
                "rank": 0,
                "area": f"{district}{road}",
                "candidate_location": f"{query}{road}",
                "fit_score": score,
                "confidence_score": confidence,
                "level": level_en(score),
                "reason": (
                    f"此道路由 {activity} 間可定位餐飲店家地址聚合而成，"
                    f"其中辨識到 {len(direct)} 間{business_type}同類店家。"
                ),
                "suggested_action": "開啟地圖查看道路範圍，取得實際出租店面後帶入指定地址分析。",
                "maps_url": build_maps_url(f"{district}{road}", query),
                "source_analysis": {
                    "restaurant_nearby_count": activity,
                    "direct_competitor_count": len(direct),
                    "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
                    "data_status": fetch.status,
                },
            }
        )
    ranked.sort(key=lambda item: (item["fit_score"], item["confidence_score"]), reverse=True)
    ranked = ranked[:limit]
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
    warning = []
    if not ranked:
        warning.append("此行政區未取得足夠的真實道路地址資料，不產生空泛商圈名稱。")
    return {
        "business_type": business_type,
        "business_profile": business_profile_for(business_type).label,
        "geo_scope": {"county": county, "district": district},
        "stage": "area",
        "recommendations": ranked,
        "overall_conclusion": (
            f"{district}已找到 {len(ranked)} 個可定位道路熱點。"
            if ranked
            else f"{district}目前資料不足，無法形成可定位候選區域。"
        ),
        "warnings": warning,
        "assumptions": [
            "道路熱點來自實際餐飲店家地址聚合，不等於可出租店面。",
            "取得實際物件後，仍須進入指定地址分析。",
        ],
    }


def extract_road_name(address: str) -> str:
    cleaned = re.sub(r"^\d{3,6}", "", address or "")
    cleaned = re.sub(r"^.*?[縣市].*?[區鄉鎮市]", "", cleaned)
    cleaned = re.sub(r"^.*?(?:里|村)", "", cleaned)
    match = re.search(
        r"([\u4e00-\u9fff\d]{1,8}?(?:大道|路|街)(?:\d+段|[一二三四五六七八九十]+段)?)",
        cleaned,
    )
    return match.group(1) if match else ""


def belongs_to_district(address: str, record_district: str, district: str) -> bool:
    normalized = district.replace("臺", "台").strip()
    source_district = (record_district or "").replace("臺", "台").strip()
    if source_district:
        return source_district == normalized
    text = (address or "").replace("臺", "台")
    if normalized in text:
        return True
    has_local_district = bool(re.search(r"[\u4e00-\u9fff]{1,4}(?:區|鄉|鎮)", text))
    return not has_local_district


def business_matches(category: str, business_type: str) -> bool:
    text = str(category or "").lower()
    aliases = {
        "炸雞": ("炸雞", "雞排", "速食"),
        "便當": ("便當", "餐盒", "飯盒"),
        "火鍋": ("火鍋", "鍋物", "涮涮鍋"),
        "燒烤": ("燒烤", "烤肉", "串燒"),
    }
    return any(keyword in text for keyword in aliases[business_type])


def build_reverse_report(result: dict) -> str:
    lines = [
        "# GDO反向店面選址建議報告",
        "",
        "## 一、輸入條件",
        f"- 業態：{result['business_type']}",
        f"- 範圍：{result['geo_scope'].get('county', '')}{result['geo_scope'].get('district', '')}",
        f"- 業態模型：{result['business_profile']}",
        "",
        "## 二、總結",
        f"- {result['overall_conclusion']}",
        "",
        "## 三、推薦區域排序",
    ]
    for item in result["recommendations"]:
        source = item["source_analysis"]
        lines.extend(
            [
                f"### No.{item['rank']} {item['area']}｜{item['fit_score']}/100（{item['level']}）",
                f"- 候選點：{item['candidate_location']}",
                f"- 推薦原因：{item['reason']}",
                f"- 管理動作：{item['suggested_action']}",
                f"- 資料可信度：{item.get('confidence_score', 0)}/100",
            ]
        )
        if result.get("stage") == "district":
            lines.extend(
                [
                    f"- 單點綜合分：{source['overall_score']}/100",
                    f"- 餐飲/商業密度：3km {source['restaurant_nearby_count']} 筆，競爭 {source['competition_level']}",
                    f"- 車潮：汽車 {source['car_score']}/100，機車 {source['motorcycle_score']}/100",
                ]
            )
        else:
            lines.extend(
                [
                    f"- 可定位餐飲店家：{source['restaurant_nearby_count']} 間",
                    f"- 同類店家：{source['direct_competitor_count']} 間",
                ]
            )
        lines.append("")
    if result["warnings"]:
        lines.append("## 四、資料限制")
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    if result["assumptions"]:
        lines.append("")
        lines.append("## 五、推估假設")
        for assumption in result["assumptions"]:
            lines.append(f"- {assumption}")
    return "\n".join(lines).strip()


def business_profile_for(business_type: str) -> BusinessProfile:
    text = business_type.strip().lower()
    if any(keyword in text for keyword in ("炸雞", "雞排", "鹽酥", "速食")):
        return BusinessProfile(
            key="food",
            label="炸雞/速食外帶型",
            crowd_weights={"morning": 0.05, "noon": 0.25, "evening": 0.55, "midnight": 0.15},
            traffic_weight=0.26,
            restaurant_weight=0.22,
            saturation_start=95,
            saturation_factor=0.14,
            anchors=AREA_ANCHORS["food"],
            strategy="優先看晚上人潮、機車流量、外帶動線與餐飲聚集；高密度區可做，但需避開租金過高與同質競品過密。",
        )
    if any(keyword in text for keyword in ("餐盒", "便當", "飯盒", "外送", "午餐")):
        return BusinessProfile(
            key="lunchbox",
            label="餐盒/便當午餐型",
            crowd_weights={"morning": 0.15, "noon": 0.60, "evening": 0.20, "midnight": 0.05},
            traffic_weight=0.22,
            restaurant_weight=0.18,
            saturation_start=85,
            saturation_factor=0.18,
            anchors=AREA_ANCHORS["lunchbox"],
            strategy="優先看中午人潮、商辦/學區/工業區、機車外送動線；競爭過密時要用出餐速度與客單價取勝。",
        )
    if "火鍋" in text:
        return BusinessProfile(
            key="hotpot",
            label="火鍋聚餐型",
            crowd_weights={"morning": 0.05, "noon": 0.20, "evening": 0.60, "midnight": 0.15},
            traffic_weight=0.20,
            restaurant_weight=0.25,
            saturation_start=70,
            saturation_factor=0.18,
            anchors=AREA_ANCHORS["food"],
            strategy="優先看晚餐與假日聚餐需求、停車便利、住宅人口與兩公里競品壓力。",
        )
    if "燒烤" in text:
        return BusinessProfile(
            key="barbecue",
            label="燒烤晚餐聚餐型",
            crowd_weights={"morning": 0.02, "noon": 0.12, "evening": 0.61, "midnight": 0.25},
            traffic_weight=0.15,
            restaurant_weight=0.25,
            saturation_start=65,
            saturation_factor=0.20,
            anchors=AREA_ANCHORS["food"],
            strategy="優先看晚間與宵夜活動、聚餐人口、停車及兩公里內同類競爭。",
        )
    return BusinessProfile(
        key="default",
        label="一般店面/零售服務型",
        crowd_weights={"morning": 0.20, "noon": 0.30, "evening": 0.40, "midnight": 0.10},
        traffic_weight=0.22,
        restaurant_weight=0.16,
        saturation_start=100,
        saturation_factor=0.10,
        anchors=AREA_ANCHORS["default"],
        strategy="以全天人潮、車潮、商業密度與競爭強度做平衡評估，適合作為初篩模型。",
    )


def build_candidates(county: str, district: str, profile: BusinessProfile) -> list[dict]:
    normalized_county = county.replace("臺", "台").strip()
    normalized_district = district.replace("臺", "台").strip()
    if normalized_district:
        return [
            {
                "label": f"{normalized_district}{anchor}",
                "query": f"{normalized_county}{normalized_district}{anchor}",
            }
            for anchor in profile.anchors
        ]

    districts = COUNTY_DISTRICTS.get(normalized_county)
    if not districts:
        districts = [item[1] for item in DISTRICT_CENTROIDS if item[0] == normalized_county]
    return [
        {
            "label": district_name,
            "query": f"{normalized_county}{district_name}",
        }
        for district_name in districts[:8]
    ]


def business_fit_score(result: dict, profile: BusinessProfile) -> dict:
    crowd = result["crowd_analysis"]
    traffic = result["traffic_analysis"]
    restaurant = result["restaurant_analysis"]

    crowd_score = sum(crowd[key]["score"] * weight for key, weight in profile.crowd_weights.items())
    traffic_score = traffic["car"]["score"] * 0.35 + traffic["motorcycle"]["score"] * 0.65
    restaurant_score = restaurant["_score"]
    base_score = result["overall_score"]
    saturation_penalty = max(0, restaurant.get("nearby_count", 0) - profile.saturation_start) * profile.saturation_factor

    score = clamp(
        base_score * 0.28
        + crowd_score * 0.34
        + traffic_score * profile.traffic_weight
        + restaurant_score * profile.restaurant_weight
        - saturation_penalty
    )
    reason = (
        f"{profile.strategy} 本區單點分 {base_score}/100，業態加權後重看目標時段人潮 "
        f"{round(crowd_score)}/100、機車/車潮 {round(traffic_score)}/100、商業密度 {restaurant_score}/100。"
    )
    suggested_action = suggested_action_for(score, restaurant.get("nearby_count", 0), profile)
    return {"score": score, "reason": reason, "suggested_action": suggested_action}


def suggested_action_for(score: int, nearby_count: int, profile: BusinessProfile) -> str:
    if score >= 75:
        return "列入優先看店名單，下一步比對租金、門寬、招牌能見度、尖峰 30 分鐘實地人流。"
    if score >= 60:
        return "列入備選名單，需補租金、競品價格帶與實地動線後再決定。"
    if nearby_count > profile.saturation_start:
        return "商業密度高但可能競爭過重，除非租金合理或產品差異明確，否則不優先。"
    return "暫不列入第一波展店，建議改查鄰近商圈或提高候選範圍。"


def compact_source_analysis(result: dict) -> dict:
    public = public_json(result)
    restaurant = public["restaurant_analysis"]
    traffic = public["traffic_analysis"]
    return {
        "input_location": public["input_location"],
        "geo_scope": public["geo_scope"],
        "overall_score": public["overall_score"],
        "overall_conclusion": public["overall_conclusion"],
        "restaurant_nearby_count": restaurant["nearby_count"],
        "counts_by_radius": restaurant.get("counts_by_radius", {}),
        "competition_level": restaurant["competition_level"],
        "car_score": traffic["car"]["score"],
        "motorcycle_score": traffic["motorcycle"]["score"],
        "data_quality_score": public.get("data_quality", {}).get("score", 0),
    }


def reverse_conclusion(recommendations: list[dict], profile: BusinessProfile) -> str:
    if not recommendations:
        return "目前候選資料不足，無法產生排序。"
    top = recommendations[0]
    if top["fit_score"] >= 75:
        return f"{top['area']} 為目前最優先候選，適合用「{profile.label}」模型進入看店與租金評估。"
    if top["fit_score"] >= 60:
        return f"{top['area']} 為目前較佳候選，但仍需補實地人流、租金與競品價格帶。"
    return "目前候選區域分數未達優先展店標準，建議擴大縣市或改查鄰近商圈。"
