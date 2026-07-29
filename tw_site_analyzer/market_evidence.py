from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Thread
from typing import Callable, TypeVar
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

from .analysis import SiteSelectionAnalyzer
from .cleaning import active_restaurants
from .models import EvidenceStatus, GeoScope, RestaurantMarketFetch, RestaurantRecord
from .nearby import build_maps_url
from .utils import haversine_km, normalize_text

ANALYSIS_VERSION = "market-evidence-v2"
STATUS_LABELS: dict[EvidenceStatus, str] = {
    "acquired": "已取得",
    "confirmed_zero": "已確認零筆",
    "partial": "部分取得",
    "failed": "取得失敗",
}

BUSINESS_ALIASES = {
    "炸雞": ("炸雞", "雞排", "鹹酥雞", "香雞排", "fried chicken", "chicken"),
    "便當": ("便當", "餐盒", "快餐", "盒餐", "bento"),
    "早餐": ("早餐", "早午餐", "蛋餅", "吐司", "breakfast", "brunch"),
    "飲料": ("飲料", "手搖", "茶飲", "果汁", "bubble tea", "tea"),
    "火鍋": ("火鍋", "涮涮鍋", "麻辣鍋", "hot pot"),
    "燒肉": ("燒肉", "烤肉", "串燒", "yakiniku", "barbecue"),
    "咖啡": ("咖啡", "coffee", "cafe", "咖啡廳"),
}

T = TypeVar("T")


@dataclass(frozen=True)
class ReviewFetch:
    reviews: list[dict]
    status: EvidenceStatus
    source: str
    retrieved_at: str
    error_type: str | None = None


class PlaceReviewSource:
    source_name = "place_reviews"

    def is_configured(self) -> bool:
        return True

    def fetch(self, place_id: str, timeout_seconds: float) -> list[dict]:
        raise NotImplementedError


class GooglePlaceReviewSource(PlaceReviewSource):
    source_name = "google_place_details"

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, place_id: str, timeout_seconds: float) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("google_place_details_not_configured")
        if not place_id:
            return []
        params = urlencode(
            {
                "place_id": place_id,
                "fields": "reviews",
                "language": "zh-TW",
                "key": self.api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
        try:
            with urlopen(url, timeout=max(0.1, timeout_seconds)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise RuntimeError("google_place_details_request_failed") from error
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return []
        if status != "OK":
            raise RuntimeError(f"google_place_details_{str(status).lower()}")
        return payload.get("result", {}).get("reviews", []) or []


@dataclass(frozen=True)
class MarketEvidenceSnapshot:
    analysis_id: str
    analyzed_at: str
    analysis_version: str
    input_location: str
    business_type: str
    radius_km: float
    geo_scope: dict
    all_stores: list[dict]
    direct_competitors: list[dict]
    adjacent_competitors: list[dict]
    top_competitors: list[dict]
    evidence: dict
    overall_status: EvidenceStatus
    warnings: list[str]
    elapsed_ms: int

    @property
    def restaurant_numbers_available(self) -> bool:
        return self.evidence["restaurants"]["status"] in ("acquired", "confirmed_zero")


class MarketEvidenceCollector:
    def __init__(
        self,
        analyzer: SiteSelectionAnalyzer,
        review_source: PlaceReviewSource | None = None,
        budget_seconds: float = 12.0,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        self.analyzer = analyzer
        self.review_source = review_source or GooglePlaceReviewSource(analyzer.config.google_maps_api_key)
        self.budget_seconds = max(0.01, float(budget_seconds))
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.id_factory = id_factory or (lambda: str(uuid4()))

    def collect(self, location: str, business_type: str, radius_km: float = 0.8) -> MarketEvidenceSnapshot:
        started = time.monotonic()
        deadline = started + self.budget_seconds
        analyzed_at = self.now().isoformat()
        analysis_id = self.id_factory()
        radius_km = max(0.1, min(float(radius_km or 0.8), 5.0))
        warnings: list[str] = []

        scope, geocoding = self._collect_geocoding(location, deadline)
        restaurant_fetch = self._collect_restaurants(scope, radius_km, business_type, deadline)
        restaurant_evidence = evidence_payload(
            restaurant_fetch.status,
            restaurant_fetch.source,
            restaurant_fetch.retrieved_at,
            restaurant_fetch.error_type,
        )
        restaurant_evidence["direct_status"] = restaurant_fetch.direct_status
        restaurant_evidence["direct_status_label"] = STATUS_LABELS[restaurant_fetch.direct_status]

        records = active_restaurants(restaurant_fetch.all_records)
        stores = [
            store_to_dict(scope, record)
            for record in records
            if record_within_radius(scope, record, radius_km)
        ]
        stores.sort(key=lambda item: item["distance_km"] if item["distance_km"] is not None else 999999)
        direct_by_classification, _ = classify_competitors(stores, business_type)
        source_direct_keys = {
            store_key(store_to_dict(scope, record))
            for record in active_restaurants(restaurant_fetch.direct_records)
            if record_within_radius(scope, record, radius_km)
        }
        direct_keys = source_direct_keys | {store_key(store) for store in direct_by_classification}
        direct = [store for store in stores if store_key(store) in direct_keys]
        adjacent = [store for store in stores if store_key(store) not in direct_keys]
        ranked_direct = rank_store_evidence(direct)
        ranked_adjacent = rank_store_evidence(adjacent)
        top_competitors = [
            *[dict(item, competitor_level="直接競品") for item in ranked_direct[:3]],
            *[dict(item, competitor_level="鄰近競品") for item in ranked_adjacent],
        ][:3]

        review_fetch = self._collect_reviews(top_competitors, deadline)
        review_evidence = evidence_payload(
            review_fetch.status,
            review_fetch.source,
            review_fetch.retrieved_at,
            review_fetch.error_type,
        )
        reviews_by_place = group_reviews(review_fetch.reviews)
        enriched_competitors = []
        for rank, item in enumerate(top_competitors, start=1):
            enriched = dict(item)
            enriched["rank"] = rank
            enriched["_reviews"] = reviews_by_place.get(item.get("place_id", ""), [])
            enriched_competitors.append(enriched)

        evidence = {
            "geocoding": geocoding,
            "restaurants": restaurant_evidence,
            "reviews": review_evidence,
        }
        overall_status = combine_statuses(
            geocoding["status"],
            restaurant_evidence["status"],
            review_evidence["status"],
        )
        if restaurant_fetch.status == "partial":
            warnings.append("餐廳市場證據僅部分取得，營收與競爭數字暫不產生。")
        elif restaurant_fetch.status == "failed":
            warnings.append("餐廳市場證據取得失敗，營收與競爭數字暫不產生。")
        if review_fetch.status in ("partial", "failed"):
            warnings.append("評論證據未完整取得，僅顯示已確認內容。")
        if time.monotonic() >= deadline:
            warnings.append("分析已達 12 秒上限，結果以部分報告提供。")

        return MarketEvidenceSnapshot(
            analysis_id=analysis_id,
            analyzed_at=analyzed_at,
            analysis_version=ANALYSIS_VERSION,
            input_location=location,
            business_type=business_type,
            radius_km=radius_km,
            geo_scope=scope_to_dict(scope),
            all_stores=stores,
            direct_competitors=ranked_direct,
            adjacent_competitors=ranked_adjacent,
            top_competitors=enriched_competitors,
            evidence=evidence,
            overall_status=overall_status,
            warnings=warnings,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    def _collect_geocoding(self, location: str, deadline: float) -> tuple[GeoScope, dict]:
        retrieved_at = self.now().isoformat()
        try:
            scope = run_with_deadline(lambda: self.analyzer.geocoder.geocode(location), deadline)
        except TimeoutError:
            scope = GeoScope("", "", location, None, None, "unresolved")
            return scope, evidence_payload("failed", "geocoder", retrieved_at, "timeout")
        except Exception as error:
            scope = GeoScope("", "", location, None, None, "unresolved")
            return scope, evidence_payload("failed", "geocoder", retrieved_at, type(error).__name__)
        if scope.precision == "google_geocoding":
            status: EvidenceStatus = "acquired"
            source = "google_geocoding"
        elif scope.precision == "unresolved":
            status = "failed"
            source = "geocoder"
        else:
            status = "partial"
            source = f"internal_{scope.precision}"
        return scope, evidence_payload(status, source, retrieved_at)

    def _collect_restaurants(
        self,
        scope: GeoScope,
        radius_km: float,
        business_type: str,
        deadline: float,
    ) -> RestaurantMarketFetch:
        retrieved_at = self.now().isoformat()
        try:
            return run_with_deadline(
                lambda: self.analyzer.restaurant_source.market_evidence(scope, radius_km, business_type),
                deadline,
            )
        except TimeoutError:
            return RestaurantMarketFetch(
                [], [], "failed", "failed", "restaurant_source", retrieved_at, "timeout"
            )
        except Exception as error:
            return RestaurantMarketFetch(
                [], [], "failed", "failed", "restaurant_source", retrieved_at, type(error).__name__
            )

    def _collect_reviews(self, competitors: list[dict], deadline: float) -> ReviewFetch:
        retrieved_at = self.now().isoformat()
        place_ids = [item.get("place_id", "") for item in competitors if item.get("place_id")]
        if not competitors:
            return ReviewFetch([], "confirmed_zero", self.review_source.source_name, retrieved_at)
        if not self.review_source.is_configured():
            return ReviewFetch([], "failed", self.review_source.source_name, retrieved_at, "not_configured")
        if not place_ids:
            return ReviewFetch([], "failed", self.review_source.source_name, retrieved_at, "place_id_unavailable")

        results: Queue = Queue()
        for place_id in place_ids:
            timeout_seconds = max(0.1, min(4.0, deadline - time.monotonic()))
            thread = Thread(
                target=fetch_review_into_queue,
                args=(results, self.review_source, place_id, timeout_seconds),
                daemon=True,
                name=f"gdo-review-{place_id[:12]}",
            )
            thread.start()

        rows: list[dict] = []
        failures = 0
        successes = 0
        received = 0
        while received < len(place_ids):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                place_id, reviews, error = results.get(timeout=remaining)
            except Empty:
                break
            received += 1
            if error:
                failures += 1
                continue
            successes += 1
            rows.extend({"place_id": place_id, "review": review} for review in reviews)
        failures += len(place_ids) - received

        if failures and successes:
            status: EvidenceStatus = "partial"
        elif failures:
            status = "failed"
        elif rows:
            status = "acquired"
        else:
            status = "confirmed_zero"
        error_type = "timeout_or_upstream_failure" if failures else None
        return ReviewFetch(rows, status, self.review_source.source_name, retrieved_at, error_type)


def run_with_deadline(operation: Callable[[], T], deadline: float) -> T:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    result: Queue = Queue(maxsize=1)
    thread = Thread(
        target=run_into_queue,
        args=(result, operation),
        daemon=True,
        name="gdo-evidence",
    )
    thread.start()
    try:
        succeeded, value = result.get(timeout=remaining)
    except Empty as error:
        raise TimeoutError from error
    if succeeded:
        return value
    raise value


def run_into_queue(result: Queue, operation: Callable[[], T]) -> None:
    try:
        result.put((True, operation()))
    except Exception as error:
        result.put((False, error))


def fetch_review_into_queue(
    result: Queue,
    source: PlaceReviewSource,
    place_id: str,
    timeout_seconds: float,
) -> None:
    try:
        result.put((place_id, source.fetch(place_id, timeout_seconds), None))
    except Exception as error:
        result.put((place_id, [], type(error).__name__))


def evidence_payload(
    status: EvidenceStatus,
    source: str,
    retrieved_at: str,
    error_type: str | None = None,
) -> dict:
    payload = {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "source": source,
        "retrieved_at": retrieved_at,
    }
    if error_type:
        payload["error_type"] = error_type
    return payload


def scope_to_dict(scope: GeoScope) -> dict:
    return {
        "county": scope.county,
        "district": scope.district,
        "address_or_landmark": scope.address_or_landmark,
        "lat": scope.lat,
        "lon": scope.lon,
        "precision": scope.precision,
    }


def store_to_dict(scope: GeoScope, record: RestaurantRecord) -> dict:
    distance_km = None
    if scope.lat is not None and scope.lon is not None and record.lat is not None and record.lon is not None:
        distance_km = haversine_km(scope.lat, scope.lon, record.lat, record.lon)
    return {
        "name": record.name,
        "address": record.address,
        "category": record.category,
        "status": record.status,
        "_lat": record.lat,
        "_lon": record.lon,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "place_id": record.place_id,
        "rating": record.rating,
        "user_ratings_total": record.user_ratings_total,
        "price_level": record.price_level,
        "maps_url": build_maps_url(record.name, record.address),
    }


def record_within_radius(scope: GeoScope, record: RestaurantRecord, radius_km: float) -> bool:
    if scope.lat is None or scope.lon is None or record.lat is None or record.lon is None:
        return True
    return haversine_km(scope.lat, scope.lon, record.lat, record.lon) <= radius_km


def store_key(store: dict) -> str:
    place_id = str(store.get("place_id") or "").strip()
    if place_id:
        return f"place:{place_id}"
    return f"text:{normalize_text(store.get('name', '')).lower()}|{normalize_text(store.get('address', '')).lower()}"


def classify_competitors(stores: list[dict], business_type: str) -> tuple[list[dict], list[dict]]:
    normalized_type = normalize_text(business_type).lower()
    aliases = {normalized_type}
    for keyword, values in BUSINESS_ALIASES.items():
        if normalize_text(keyword) in normalized_type or normalized_type in normalize_text(keyword):
            aliases.update(normalize_text(value) for value in values)
    aliases.discard("")

    direct = []
    adjacent = []
    for store in stores:
        haystack = normalize_text(f"{store.get('name', '')} {store.get('category', '')}").lower()
        target = direct if any(alias in haystack for alias in aliases) else adjacent
        target.append(store)
    return direct, adjacent


def rank_store_evidence(stores: list[dict]) -> list[dict]:
    def score(store: dict) -> float:
        rating = store.get("rating") or 0
        reviews = store.get("user_ratings_total") or 0
        distance = store.get("distance_km")
        distance_bonus = 20 if distance is None else max(0, 20 - distance * 10)
        return rating * 20 + min(reviews, 1000) / 20 + distance_bonus

    return sorted(stores, key=score, reverse=True)


def group_reviews(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["place_id"], []).append(row["review"])
    return grouped


def combine_statuses(*statuses: EvidenceStatus) -> EvidenceStatus:
    if all(status in ("acquired", "confirmed_zero") for status in statuses):
        return "acquired"
    if all(status == "failed" for status in statuses):
        return "failed"
    return "partial"
