from __future__ import annotations

from math import cos, radians
from statistics import mean, median

from .analysis import SiteSelectionAnalyzer
from .decision import COMPARISON_RADII_KM, PropertyInput, primary_radius_for, score_market, validate_business_type
from .market_contract import (
    Competitor,
    DistributionItem,
    MarketMap,
    MarketMapPoint,
    MarketReportContract,
    MarketSummary,
    RoadTraffic,
    RevenuePerformance,
    ReviewSummary,
    TicketDistribution,
)
from .market_evidence import MarketEvidenceCollector, MarketEvidenceSnapshot


def build_market_report(
    analyzer: SiteSelectionAnalyzer,
    location: str,
    business_type: str,
    radius_km: float | None = None,
    monthly_rent: int | None = None,
    area_ping: float | None = None,
    onsite_count: int | None = None,
    evidence_collector: MarketEvidenceCollector | None = None,
) -> dict:
    business_type = validate_business_type(business_type)
    primary_radius = primary_radius_for(business_type)
    snapshot = (evidence_collector or MarketEvidenceCollector(analyzer)).collect(
        location,
        business_type,
        max(COMPARISON_RADII_KM),
    )
    formal_direct = stores_within(snapshot.direct_competitors, primary_radius)
    formal_all = stores_within(snapshot.all_stores, primary_radius)
    top_competitors = build_competitor_cards(snapshot, formal_direct[:3], "直接競品")
    adjacent_competitors = build_competitor_cards(
        snapshot,
        stores_within(snapshot.adjacent_competitors, primary_radius)[:3],
        "鄰近競品",
    )
    market_map = build_market_map(snapshot)
    road_traffic = build_road_traffic(snapshot)
    if snapshot.restaurant_numbers_available:
        stores = formal_direct
        same_type_count: int | None = len(stores)
        all_food_count: int | None = len(formal_all)
        market_density = density_level(len(stores), primary_radius)
    else:
        stores = []
        formal_direct = []
        formal_all = []
        same_type_count = None
        all_food_count = None
        market_density = "資料不足"
    evidence_for_score = {
        "geocode": snapshot.evidence["geocoding"],
        "all_market": snapshot.evidence["restaurants"],
        "direct_competition": {
            **snapshot.evidence["restaurants"],
            "status": snapshot.evidence["restaurants"].get("direct_status", "failed"),
        },
        "reviews": snapshot.evidence["reviews"],
        "traffic": snapshot.evidence["traffic"],
    }
    scorecard = score_market(
        business_type,
        formal_direct,
        formal_all,
        road_traffic,
        evidence_for_score,
        onsite_count,
    )
    ticket = ticket_contract(scorecard["ticket"])
    revenue = revenue_contract(scorecard["revenue_scenarios"])
    monthly_distribution = scenario_distribution(scorecard["revenue_scenarios"])
    reviews = summarize_review_signals(top_competitors)

    missing = []
    if not any(store.get("rating") is not None for store in stores):
        missing.append("Google Places 評分與評論數")
    if not any(store.get("price_level") is not None for store in stores):
        missing.append("Google Places 價位等級或菜單價格")
    missing.append("現場行人流量（TDX VD 僅代表道路車流）")
    if snapshot.evidence["reviews"]["status"] in ("partial", "failed"):
        missing.append("Google Place Details 評論文字")

    conclusion = (
        f"{scorecard['decision']}｜{build_snapshot_conclusion(snapshot, market_density, top_competitors, primary_radius)}"
    )
    ring_counts = [
        {
            "radius_km": radius,
            "same_type_count": len(stores_within(snapshot.direct_competitors, radius)),
            "all_food_count": len(stores_within(snapshot.all_stores, radius)),
        }
        for radius in COMPARISON_RADII_KM
    ]
    report = MarketReportContract(
        analysis_id=snapshot.analysis_id,
        analyzed_at=snapshot.analyzed_at,
        analysis_version=snapshot.analysis_version,
        analysis_elapsed_ms=snapshot.elapsed_ms,
        input_location=location,
        business_type=business_type,
        radius_km=primary_radius,
        comparison_radii_km=list(COMPARISON_RADII_KM),
        property=PropertyInput(monthly_rent, area_ping).to_dict(),
        geo_scope={**snapshot.geo_scope, "ring_counts": ring_counts},
        evidence_status={
            "status": snapshot.overall_status,
            "sources": snapshot.evidence,
        },
        summary=MarketSummary(
            title=f"{snapshot.geo_scope.get('county', '')}{snapshot.geo_scope.get('district', '')} {business_type} 開店分析",
            conclusion=conclusion,
            same_type_count=same_type_count,
            all_food_count=all_food_count,
            density_level=market_density,
            data_status=snapshot_status_text(snapshot),
        ),
        market_map=MarketMap(
            status=market_map["status"],
            source=market_map["source"],
            center_label=market_map["center_label"],
            point_count=market_map["point_count"],
            points=[MarketMapPoint(**item) for item in market_map["points"]],
            center_lat=market_map["center_lat"],
            center_lon=market_map["center_lon"],
        ),
        road_traffic=RoadTraffic(**road_traffic),
        revenue_performance=RevenuePerformance(**revenue),
        monthly_revenue_distribution=[DistributionItem(**item) for item in monthly_distribution],
        average_ticket_distribution=TicketDistribution(
            position=ticket["position"],
            distribution=[DistributionItem(**item) for item in ticket["distribution"]],
            basis=ticket["basis"],
            available=ticket.get("available", True),
        ),
        top_competitors=[Competitor(**item) for item in top_competitors],
        adjacent_competitors=[Competitor(**item) for item in adjacent_competitors],
        review_summary=ReviewSummary(**reviews),
        scorecard={
            key: value
            for key, value in scorecard.items()
            if key not in {"ticket", "revenue_scenarios"}
        },
        revenue_scenarios=scorecard["revenue_scenarios"],
        data_as_of=max(
            (
                str(item.get("retrieved_at") or "")
                for item in snapshot.evidence.values()
            ),
            default=snapshot.analyzed_at,
        ),
        data_requirements=missing,
        warnings=snapshot.warnings,
    )
    return report.to_dict()


def build_market_report_text(result: dict) -> str:
    lines = [
        "GDO 開店找點分析",
        "",
        f"分析地址：{result['input_location']}",
        f"分析業態：{result['business_type']}",
        f"分析半徑：{result['radius_km']} km",
        "",
        f"結論：{result['summary']['conclusion']}",
        "",
        "重點數據：",
        f"- 同類店家：{display_count(result['summary']['same_type_count'])}",
        f"- 餐飲總店數：{display_count(result['summary']['all_food_count'])}",
        f"- 競爭密度：{result['summary']['density_level']}",
        f"- 營收機會：{result['revenue_performance']['opportunity_level']}",
        "",
        "前三名同類店家：",
    ]
    if result["top_competitors"]:
        for item in result["top_competitors"]:
            rating = item["rating"] if item["rating"] is not None else "未取得"
            count = item["user_ratings_total"] if item["user_ratings_total"] is not None else "未取得"
            lines.append(
                f"{item['rank']}. {item['name']}｜{item['competitor_level']}｜評分 {rating}｜評論 {count}"
            )
    else:
        lines.append("- 查無足夠同類店家資料")
    lines.extend(["", "待接資料："])
    lines.extend(f"- {item}" for item in result["data_requirements"])
    return "\n".join(lines)


def build_competitor_cards(
    snapshot: MarketEvidenceSnapshot,
    competitors: list[dict],
    competitor_level: str,
) -> list[dict]:
    enriched_by_id = {
        store_identity(item): item
        for item in snapshot.top_competitors
    }
    cards = []
    for rank, source_item in enumerate(competitors, 1):
        item = source_item
        reviews = enriched_by_id.get(store_identity(source_item), {}).get("_reviews", [])
        positive = [review for review in reviews if review.get("rating", 0) >= 4]
        negative = [review for review in reviews if review.get("rating", 0) <= 3]
        card = {
            "rank": rank,
            "name": item["name"],
            "address": item["address"],
            "category": item["category"],
            "competitor_level": competitor_level,
            "distance_km": item["distance_km"],
            "rating": item.get("rating"),
            "user_ratings_total": item.get("user_ratings_total"),
            "price_level": item.get("price_level"),
            "place_id": item.get("place_id", ""),
            "maps_url": item.get("maps_url", ""),
            "strength": competitor_strength(item),
            "risk": competitor_risk(item),
            "review_positive": summarize_reviews(positive, "positive"),
            "review_negative": summarize_reviews(negative, "negative"),
            "positive_snippets": review_snippets(positive),
            "negative_snippets": review_snippets(negative),
        }
        cards.append(card)
    return cards


def unavailable_revenue_module() -> dict:
    return {
        "opportunity_level": "資料不足",
        "estimated_monthly_revenue_range": [],
        "basis": "市場證據未完整取得，本次不產生營收推估。",
        "data_status": "部分取得或取得失敗",
        "available": False,
    }


def unavailable_ticket_module() -> dict:
    return {
        "position": "資料不足",
        "distribution": [],
        "basis": "未取得同業價位證據，本次不產生客單價帶推估。",
        "available": False,
    }


def build_market_map(snapshot: MarketEvidenceSnapshot) -> dict:
    center_lat = snapshot.geo_scope.get("lat")
    center_lon = snapshot.geo_scope.get("lon")
    center_label = snapshot.geo_scope.get("address_or_landmark") or snapshot.input_location
    if center_lat is None or center_lon is None:
        return {
            "status": "unavailable",
            "source": "座標未取得",
            "center_label": center_label,
            "point_count": 0,
            "points": [],
            "center_lat": None,
            "center_lon": None,
        }

    direct_keys = {store_identity(item) for item in snapshot.direct_competitors}
    points = []
    radius = max(snapshot.radius_km, 0.1)
    longitude_scale = 111.32 * max(cos(radians(float(center_lat))), 0.1)
    for store in snapshot.all_stores[:100]:
        lat = store.get("_lat")
        lon = store.get("_lon")
        if lat is None or lon is None:
            continue
        east_km = (float(lon) - float(center_lon)) * longitude_scale
        north_km = (float(lat) - float(center_lat)) * 110.57
        points.append(
            {
                "name": store.get("name") or "未命名店家",
                "kind": "direct" if store_identity(store) in direct_keys else "adjacent",
                "x": round(clamp(50 + east_km / radius * 46, 4, 96), 1),
                "y": round(clamp(50 - north_km / radius * 46, 4, 96), 1),
            }
        )
    return {
        "status": "acquired" if points else "unavailable",
        "source": "Google Places 店家座標相對分布" if points else "店家座標未取得",
        "center_label": center_label,
        "point_count": len(points),
        "points": points,
        "center_lat": float(center_lat),
        "center_lon": float(center_lon),
    }


def build_road_traffic(snapshot: MarketEvidenceSnapshot) -> dict:
    evidence = snapshot.evidence["traffic"]
    records = snapshot.traffic_records
    if evidence["status"] != "acquired" or not records:
        return {
            "available": False,
            "status": evidence["status_label"],
            "source": evidence["source"],
            "station_count": 0,
            "average_car_flow": None,
            "average_motorcycle_flow": None,
            "average_speed": None,
            "nearest_station_distance_km": None,
            "observed_at": "",
            "interpretation": "未取得附近 TDX VD 測站資料；不以代理值補算。",
        }

    car_values = [float(item["car_flow"]) for item in records if item.get("car_flow") is not None]
    motorcycle_values = [
        float(item["motorcycle_flow"])
        for item in records
        if item.get("motorcycle_flow") is not None
    ]
    speed_values = [float(item["speed"]) for item in records if item.get("speed") is not None]
    distances = [
        float(item["distance_km"])
        for item in records
        if item.get("distance_km") is not None
    ]
    observed_at = max((str(item.get("timestamp") or "") for item in records), default="")
    available_values = []
    if car_values:
        available_values.append(f"汽車平均觀測值 {round(mean(car_values), 1):g}")
    if motorcycle_values:
        available_values.append(f"機車平均觀測值 {round(mean(motorcycle_values), 1):g}")
    detail = "、".join(available_values) or "測站未回傳有效流量值"
    return {
        "available": bool(car_values or motorcycle_values or speed_values),
        "status": evidence["status_label"],
        "source": evidence["source"],
        "station_count": len(records),
        "average_car_flow": round(mean(car_values), 1) if car_values else None,
        "average_motorcycle_flow": round(mean(motorcycle_values), 1) if motorcycle_values else None,
        "average_speed": round(mean(speed_values), 1) if speed_values else None,
        "nearest_station_distance_km": round(min(distances), 2) if distances else None,
        "observed_at": observed_at,
        "interpretation": (
            f"附近 {len(records)} 個道路測站：{detail}。此資料代表道路車流，不代表行人流量。"
        ),
    }


def store_identity(store: dict) -> str:
    place_id = str(store.get("place_id") or "").strip()
    if place_id:
        return f"place:{place_id}"
    return f"text:{store.get('name', '')}|{store.get('address', '')}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def build_snapshot_conclusion(
    snapshot: MarketEvidenceSnapshot,
    density: str,
    top_competitors: list[dict],
    primary_radius: float,
) -> str:
    if not snapshot.restaurant_numbers_available:
        return (
            f"「{snapshot.input_location}」的市場店家證據未完整取得，本次不做競爭與營收判斷；"
            "建議確認地址或稍後重查。"
        )
    return build_evidence_conclusion(snapshot, density, top_competitors, primary_radius)


def build_evidence_conclusion(
    snapshot: MarketEvidenceSnapshot,
    density: str,
    top_competitors: list[dict],
    primary_radius: float,
) -> str:
    direct_count = len(stores_within(snapshot.direct_competitors, primary_radius))
    all_count = len(stores_within(snapshot.all_stores, primary_radius))
    scope = f"「{snapshot.input_location}」周邊 {primary_radius:g} 公里"
    if direct_count == 0:
        if all_count >= 12:
            return (
                f"{scope}已找到 {all_count} 間餐飲，但未找到明確{snapshot.business_type}直接競品。"
                "可視為品類空間訊號，但不能等同有需求；建議先現勘尖峰人流與外送訂單密度。"
            )
        return (
            f"{scope}僅找到 {all_count} 間餐飲，且未找到明確{snapshot.business_type}直接競品。"
            "需求與競爭證據都偏弱，建議先做平假日尖峰人流與商圈消費驗證。"
        )

    leader = next(
        (item for item in top_competitors if item["competitor_level"] == "直接競品"),
        top_competitors[0] if top_competitors else None,
    )
    leader_text = ""
    if leader:
        rating = leader.get("rating")
        reviews = leader.get("user_ratings_total")
        proof = []
        if rating is not None:
            proof.append(f"評分 {rating}")
        if reviews is not None:
            proof.append(f"{reviews} 則評論")
        leader_text = f"；頭部競品為「{leader['name']}」"
        if proof:
            leader_text += f"（{'、'.join(proof)}）"

    if density == "高":
        action = "競爭已集中，須先完成產品差異、價格帶與出餐速度測試，再決定承租。"
    elif all_count >= 12:
        action = "商圈餐飲活動存在，建議比對前三名競品評論缺口並完成現場尖峰驗證。"
    else:
        action = "同業雖存在但餐飲聚集度有限，建議先確認人流來源、外送需求與租金損益兩平。"
    return (
        f"{scope}找到 {direct_count} 間{snapshot.business_type}直接競品、共 {all_count} 間餐飲，"
        f"競爭密度為{density}{leader_text}。{action}"
    )


def snapshot_status_text(snapshot: MarketEvidenceSnapshot) -> str:
    labels = {
        "acquired": "市場證據已取得，可進行初步判斷",
        "confirmed_zero": "資料來源已確認零筆",
        "partial": "市場證據部分取得，僅顯示可確認內容",
        "failed": "市場證據取得失敗，不產生推估數字",
    }
    return labels[snapshot.overall_status]


def display_count(value: int | None) -> str:
    return "資料不足" if value is None else f"{value} 間"


def stores_within(stores: list[dict], radius_km: float) -> list[dict]:
    return [
        item
        for item in stores
        if item.get("distance_km") is not None and float(item["distance_km"]) <= radius_km
    ]


def ticket_contract(ticket: dict) -> dict:
    if not ticket["available"]:
        return unavailable_ticket_module()
    low = ticket["low"]
    high = ticket["high"]
    return {
        "position": f"約 {low}-{high} 元",
        "distribution": [
            {
                "range": f"約 {low}-{high} 元",
                "share": 100,
            }
        ],
        "basis": ticket["basis"],
        "available": True,
    }


def revenue_contract(revenue_scenarios: dict) -> dict:
    if not revenue_scenarios["available"]:
        return unavailable_revenue_module()
    values = [item["monthly_revenue"] for item in revenue_scenarios["scenarios"]]
    return {
        "opportunity_level": "情境推估",
        "estimated_monthly_revenue_range": [min(values), max(values)],
        "basis": revenue_scenarios["basis"],
        "data_status": "市場推估，非真實營收",
        "available": True,
    }


def scenario_distribution(revenue_scenarios: dict) -> list[dict]:
    if not revenue_scenarios["available"]:
        return []
    values = [item["monthly_revenue"] for item in revenue_scenarios["scenarios"]]
    maximum = max(values) or 1
    return [
        {
            "range": f"{round(item['monthly_revenue'] / 10000)} 萬",
            "level": item["label"],
            "share": round(item["monthly_revenue"] / maximum * 100),
        }
        for item in revenue_scenarios["scenarios"]
    ]


def review_snippets(reviews: list[dict]) -> list[str]:
    snippets = []
    for review in reviews:
        text = " ".join(str(review.get("text") or "").split())
        if not text:
            continue
        snippets.append(text[:80] + ("…" if len(text) > 80 else ""))
        if len(snippets) == 2:
            break
    return snippets


def summarize_reviews(reviews: list[dict], mode: str) -> list[str]:
    if not reviews:
        return []
    keywords = {
        "positive": ["好吃", "份量", "服務", "快速", "親切", "乾淨", "便宜", "CP", "新鮮", "穩定"],
        "negative": ["慢", "排隊", "貴", "少", "冷", "油", "態度", "等", "鹹", "失望"],
    }[mode]
    summaries = []
    for keyword in keywords:
        if any(keyword in str(review.get("text", "")) for review in reviews):
            summaries.append(keyword)
    if summaries:
        label = "好評集中在" if mode == "positive" else "差評集中在"
        return [f"{label}：{'、'.join(summaries[:5])}"]
    return []


def density_level(count: int, radius_km: float) -> str:
    area = max(3.14159 * radius_km * radius_km, 0.1)
    density = count / area
    if density >= 25:
        return "高"
    if density >= 8:
        return "中"
    return "低"


def estimate_revenue_module(stores: list[dict], density: str) -> dict:
    review_counts = [store["user_ratings_total"] for store in stores if store.get("user_ratings_total")]
    median_reviews = int(median(review_counts)) if review_counts else None
    if density == "高":
        opportunity = "中高"
        revenue_range = [450000, 900000]
    elif density == "中":
        opportunity = "中"
        revenue_range = [300000, 650000]
    else:
        opportunity = "待驗證"
        revenue_range = [180000, 420000]
    if median_reviews and median_reviews >= 500:
        revenue_range = [int(revenue_range[0] * 1.15), int(revenue_range[1] * 1.2)]
        opportunity = "高" if opportunity == "中高" else opportunity
    return {
        "opportunity_level": opportunity,
        "estimated_monthly_revenue_range": revenue_range,
        "basis": "以同業密度、評論量與商圈活躍度做初步推估；非真實營收。",
        "data_status": "推估版",
    }


def build_distribution(revenue_range: list[int]) -> list[dict]:
    low, high = revenue_range
    mid = int((low + high) / 2)
    return [
        {"range": f"{low // 10000}-{mid // 10000} 萬", "level": "保守", "share": 50},
        {"range": f"{mid // 10000}-{high // 10000} 萬", "level": "基準", "share": 75},
        {"range": f"{high // 10000} 萬以上", "level": "高標", "share": 100},
    ]


def estimate_ticket_module(stores: list[dict], business_type: str) -> dict:
    price_levels = [store["price_level"] for store in stores if store.get("price_level") is not None]
    if not price_levels:
        return unavailable_ticket_module()
    avg_level = sum(price_levels) / len(price_levels)
    if avg_level <= 1.3:
        ranges = [{"range": "約 80-120 元", "share": 45}]
        position = "平價走量"
    elif avg_level <= 2.2:
        ranges = [{"range": "約 100-180 元", "share": 70}]
        position = "中價位主流"
    else:
        ranges = [{"range": "約 180-300 元以上", "share": 90}]
        position = "中高價位"
    return {
        "position": position,
        "distribution": ranges,
        "basis": f"依 {len(price_levels)} 間同業的 Google Places 價位等級推估；非實際交易分布，需菜單或 POS 校正。",
    }


def summarize_review_signals(top_competitors: list[dict]) -> dict:
    if not top_competitors:
        return {
            "positive": [],
            "negative": [],
            "data_status": "未找到可摘要的競品評論",
        }
    positives = [
        summary
        for item in top_competitors
        for summary in item.get("review_positive", [])
    ]
    negatives = [
        summary
        for item in top_competitors
        for summary in item.get("review_negative", [])
    ]
    if positives or negatives:
        return {
            "positive": positives,
            "negative": negatives,
            "data_status": "已接 Google 評論摘要，仍建議人工複核代表性評論",
        }
    return {
        "positive": [],
        "negative": [],
        "data_status": "評論文字不足，未產生好評或差評主題。",
    }


def competitor_strength(store: dict) -> str:
    rating = store.get("rating")
    total = store.get("user_ratings_total") or 0
    if rating and rating >= 4.3 and total >= 300:
        return "高評價且評論量足，屬於主要競品。"
    if rating and rating >= 4:
        return "評價穩定，需觀察產品與價格帶。"
    return "競爭力需看評論內容與現場人流再判斷。"


def competitor_risk(store: dict) -> str:
    rating = store.get("rating")
    total = store.get("user_ratings_total") or 0
    if rating and rating < 3.8 and total >= 100:
        return "評分偏低，可能代表市場有服務或產品缺口。"
    if total >= 500:
        return "評論量高，代表已有穩定客群，正面競爭壓力較大。"
    return "需補評論文字判斷顧客痛點。"
