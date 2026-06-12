from __future__ import annotations

from dataclasses import dataclass

from .analysis import public_json
from .geo import DISTRICT_CENTROIDS
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
) -> dict:
    profile = business_profile_for(business_type)
    candidates = build_candidates(county, district, profile)
    recommendations = []
    warnings = []

    if not candidates:
        warnings.append("目前此縣市/行政區沒有內建候選區域，請改輸入主要縣市或指定行政區。")

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
        "recommendations": recommendations[:limit],
        "overall_conclusion": reverse_conclusion(recommendations[:limit], profile),
        "warnings": warnings,
        "assumptions": [
            "反向選址會先產生候選行政區或候選商圈，再沿用單點選址模型計算人潮、車潮、餐飲/商業密度。",
            "若未接入精準人流資料，早中晚半夜人潮仍以人口/商業強度、VD 車流、餐飲或商業密度代理推估。",
            "美容、零售等非餐飲業態目前以餐飲密度作為商業活躍度代理，未代表同業競品完整數量。",
        ],
    }
    return result


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
                f"- 單點綜合分：{source['overall_score']}/100",
                f"- 餐飲/商業密度：3km {source['restaurant_nearby_count']} 筆，競爭 {source['competition_level']}",
                f"- 車潮：汽車 {source['car_score']}/100，機車 {source['motorcycle_score']}/100",
                f"- 資料精準度：{source['data_quality_score']}/100",
                "",
            ]
        )
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
    if any(keyword in text for keyword in ("美容", "美甲", "美睫", "spa", "沙龍", "醫美")):
        return BusinessProfile(
            key="beauty",
            label="美容/生活服務預約型",
            crowd_weights={"morning": 0.15, "noon": 0.25, "evening": 0.45, "midnight": 0.15},
            traffic_weight=0.18,
            restaurant_weight=0.10,
            saturation_start=120,
            saturation_factor=0.04,
            anchors=AREA_ANCHORS["beauty"],
            strategy="優先看穩定商業生活圈、晚間客流、停車/捷運便利與住宅消費力；不只追求人潮最大，還要看客群品質。",
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
