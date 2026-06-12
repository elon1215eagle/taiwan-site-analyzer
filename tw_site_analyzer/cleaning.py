from __future__ import annotations

from collections import Counter

from .models import RestaurantRecord, TrafficRecord


ACTIVE_STATUS_KEYWORDS = ("核准設立", "營業中", "開業", "存續")
CLOSED_STATUS_KEYWORDS = ("歇業", "停業", "撤銷", "廢止")


def active_restaurants(records: list[RestaurantRecord]) -> list[RestaurantRecord]:
    cleaned = []
    for record in records:
        status = record.status.strip()
        if any(keyword in status for keyword in CLOSED_STATUS_KEYWORDS):
            continue
        cleaned.append(record)
    return cleaned


def summarize_categories(records: list[RestaurantRecord], top_n: int = 6) -> list[dict[str, int | str]]:
    counter = Counter(normalize_category(record.category) for record in records)
    return [{"category": category, "count": count} for category, count in counter.most_common(top_n)]


def normalize_category(category: str) -> str:
    text = category.strip()
    if not text:
        return "未分類餐飲"
    mapping = {
        "F501060": "餐館業",
        "F501030": "飲料店業",
        "F501050": "飲酒店業",
        "F501040": "其他餐飲",
        "F501990": "其他餐飲",
        "taiwanese_restaurant": "台式餐飲",
        "chinese_restaurant": "中式餐飲",
        "japanese_restaurant": "日式餐飲",
        "korean_restaurant": "韓式餐飲",
        "yakiniku_restaurant": "燒肉",
        "fast_food_restaurant": "速食",
        "breakfast_restaurant": "早餐",
        "vegetarian_restaurant": "素食",
        "seafood_restaurant": "海鮮",
        "hot_pot_restaurant": "火鍋",
        "italian_restaurant": "義式餐飲",
        "cafe": "咖啡廳",
        "cafeteria": "自助餐/簡餐",
        "bakery": "烘焙",
        "meal_takeaway": "外帶餐飲",
        "meal_delivery": "外送餐飲",
        "restaurant": "餐廳",
        "飲料": "飲料店",
        "小吃": "小吃",
        "餐館": "餐館",
        "早餐": "早餐",
        "火鍋": "火鍋",
        "炸": "炸物速食",
    }
    for keyword, label in mapping.items():
        if keyword in text:
            return label
    return text[:16]


def average_flow(records: list[TrafficRecord], field: str) -> float | None:
    values = [getattr(record, field) for record in records if getattr(record, field) is not None]
    if not values:
        return None
    return sum(values) / len(values)
