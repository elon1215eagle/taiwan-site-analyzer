from __future__ import annotations

from statistics import median

from .analysis import SiteSelectionAnalyzer
from .market_contract import (
    Competitor,
    DistributionItem,
    MarketReportContract,
    MarketSummary,
    RevenuePerformance,
    ReviewSummary,
    TicketDistribution,
)
from .market_evidence import MarketEvidenceCollector, MarketEvidenceSnapshot


def build_market_report(
    analyzer: SiteSelectionAnalyzer,
    location: str,
    business_type: str,
    radius_km: float = 0.8,
    evidence_collector: MarketEvidenceCollector | None = None,
) -> dict:
    snapshot = (evidence_collector or MarketEvidenceCollector(analyzer)).collect(
        location,
        business_type,
        radius_km,
    )
    top_competitors = build_competitor_cards(snapshot)
    if snapshot.restaurant_numbers_available:
        stores = snapshot.direct_competitors
        same_type_count: int | None = len(stores)
        all_food_count: int | None = len(snapshot.all_stores)
        market_density = density_level(len(stores), snapshot.radius_km)
        revenue = estimate_revenue_module(stores, market_density)
        ticket = estimate_ticket_module(stores, business_type)
        monthly_distribution = build_distribution(revenue["estimated_monthly_revenue_range"])
    else:
        stores = []
        same_type_count = None
        all_food_count = None
        market_density = "資料不足"
        revenue = unavailable_revenue_module()
        ticket = unavailable_ticket_module()
        monthly_distribution = []
    reviews = summarize_review_signals(top_competitors)

    missing = []
    if not any(store.get("rating") is not None for store in stores):
        missing.append("Google Places 評分與評論數")
    if not any(store.get("price_level") is not None for store in stores):
        missing.append("Google Places 價位等級或菜單價格")
    missing.append("真實 POS / iCHEF 月營收")
    if snapshot.evidence["reviews"]["status"] in ("partial", "failed"):
        missing.append("Google Place Details 評論文字")

    conclusion = build_snapshot_conclusion(snapshot, market_density, top_competitors)
    report = MarketReportContract(
        analysis_id=snapshot.analysis_id,
        analyzed_at=snapshot.analyzed_at,
        analysis_version=snapshot.analysis_version,
        analysis_elapsed_ms=snapshot.elapsed_ms,
        input_location=location,
        business_type=business_type,
        radius_km=snapshot.radius_km,
        geo_scope=snapshot.geo_scope,
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
        revenue_performance=RevenuePerformance(**revenue),
        monthly_revenue_distribution=[DistributionItem(**item) for item in monthly_distribution],
        average_ticket_distribution=TicketDistribution(
            position=ticket["position"],
            distribution=[DistributionItem(**item) for item in ticket["distribution"]],
            basis=ticket["basis"],
            available=ticket.get("available", True),
        ),
        top_competitors=[Competitor(**item) for item in top_competitors],
        review_summary=ReviewSummary(**reviews),
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


def build_competitor_cards(snapshot: MarketEvidenceSnapshot) -> list[dict]:
    cards = []
    for item in snapshot.top_competitors:
        reviews = item.get("_reviews", [])
        positive = [review for review in reviews if review.get("rating", 0) >= 4]
        negative = [review for review in reviews if review.get("rating", 0) <= 3]
        card = {
            "rank": item["rank"],
            "name": item["name"],
            "address": item["address"],
            "category": item["category"],
            "competitor_level": item["competitor_level"],
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
        "basis": "市場證據未完整取得，本次不產生客單價分布。",
        "available": False,
    }


def build_snapshot_conclusion(
    snapshot: MarketEvidenceSnapshot,
    density: str,
    top_competitors: list[dict],
) -> str:
    if not snapshot.restaurant_numbers_available:
        return "市場證據未完整取得，本次僅提供可追溯的部分報告，不做營收或競爭數字判斷。"
    return build_conclusion(
        snapshot.business_type,
        density,
        len(snapshot.direct_competitors),
        top_competitors,
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
    fallback = "評論多為正向，但需人工複核細節。" if mode == "positive" else "有少數低分評論，需人工複核痛點。"
    return [fallback]


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
        {"range": f"{low // 10000}-{mid // 10000} 萬", "level": "保守", "share": 35},
        {"range": f"{mid // 10000}-{high // 10000} 萬", "level": "主力", "share": 45},
        {"range": f"{high // 10000} 萬以上", "level": "高標", "share": 20},
    ]


def estimate_ticket_module(stores: list[dict], business_type: str) -> dict:
    price_levels = [store["price_level"] for store in stores if store.get("price_level") is not None]
    if price_levels:
        avg_level = sum(price_levels) / len(price_levels)
    else:
        avg_level = default_price_level(business_type)
    if avg_level <= 1.3:
        ranges = [{"range": "80 元以下", "share": 35}, {"range": "80-120 元", "share": 45}, {"range": "120 元以上", "share": 20}]
        position = "平價走量"
    elif avg_level <= 2.2:
        ranges = [{"range": "100 元以下", "share": 20}, {"range": "100-180 元", "share": 55}, {"range": "180 元以上", "share": 25}]
        position = "中價位主流"
    else:
        ranges = [{"range": "180 元以下", "share": 20}, {"range": "180-300 元", "share": 45}, {"range": "300 元以上", "share": 35}]
        position = "中高價位"
    return {
        "position": position,
        "distribution": ranges,
        "basis": "以 Google Places 價位等級與業態預設價格帶推估；需菜單或 POS 資料校正。",
    }


def default_price_level(business_type: str) -> float:
    text = business_type.lower()
    if any(word in text for word in ("便當", "早餐", "飲料", "炸雞")):
        return 1.2
    if any(word in text for word in ("火鍋", "燒肉", "餐酒")):
        return 2.5
    return 1.8


def summarize_review_signals(top_competitors: list[dict]) -> dict:
    if not top_competitors:
        return {
            "positive": ["尚無足夠競品評論資料。"],
            "negative": ["需接 Google Place Details 評論文字後才能整理真實痛點。"],
            "data_status": "待接評論資料",
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
            "positive": positives or ["前三名競品整體有評分資料，但正向評論文字不足。"],
            "negative": negatives or ["目前低分評論不足，需人工複核是否有明確市場缺口。"],
            "data_status": "已接 Google 評論摘要，仍建議人工複核代表性評論",
        }
    strong_names = "、".join(item["name"] for item in top_competitors[:3])
    return {
        "positive": [
            f"前三名競品為 {strong_names}，可先追蹤其高評分原因。",
            "若接入評論文字，可整理口味、份量、速度、服務、環境等好評關鍵字。",
        ],
        "negative": [
            "目前尚未接入評論文字，不能直接判定真實差評內容。",
            "建議下一步接 Google Place Details reviews，抓排隊、出餐慢、價格、份量、服務態度等痛點。",
        ],
        "data_status": "可定位競品，評論文字待接",
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


def build_conclusion(business_type: str, density: str, count: int, top_competitors: list[dict]) -> str:
    if count == 0:
        return f"目前查無明確{business_type}同業資料，不能直接判斷可開，需補資料或擴大半徑。"
    if density == "高":
        return f"該區{business_type}同業密度高，市場需求存在，但必須靠產品差異、速度與價格帶切入。"
    if top_competitors:
        return f"該區有可參考競品且同業密度{density}，適合作為初步觀察點，下一步應補評論與尖峰人流。"
    return f"該區{business_type}競爭密度{density}，可列入候選點，但資料完整度仍需補強。"
