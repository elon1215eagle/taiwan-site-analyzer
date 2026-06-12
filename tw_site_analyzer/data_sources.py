from __future__ import annotations

import csv
import json
import ssl
import time
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError

from .config import AnalyzerConfig
from .models import GeoScope, RestaurantRecord, TrafficRecord
from .utils import haversine_km, normalize_text

TDX_CITY_CODES = {
    "台北市": "Taipei",
    "臺北市": "Taipei",
    "新北市": "NewTaipei",
    "桃園市": "Taoyuan",
    "台中市": "Taichung",
    "臺中市": "Taichung",
    "台南市": "Tainan",
    "臺南市": "Tainan",
    "高雄市": "Kaohsiung",
    "基隆市": "Keelung",
    "新竹市": "Hsinchu",
    "新竹縣": "HsinchuCounty",
    "苗栗縣": "MiaoliCounty",
    "彰化縣": "ChanghuaCounty",
    "南投縣": "NantouCounty",
    "雲林縣": "YunlinCounty",
    "嘉義市": "Chiayi",
    "嘉義縣": "ChiayiCounty",
    "屏東縣": "PingtungCounty",
    "宜蘭縣": "YilanCounty",
    "花蓮縣": "HualienCounty",
    "台東縣": "TaitungCounty",
    "臺東縣": "TaitungCounty",
    "澎湖縣": "PenghuCounty",
    "金門縣": "KinmenCounty",
    "連江縣": "LienchiangCounty",
}


class RestaurantDataSource:
    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        raise NotImplementedError


class CSVRestaurantDataSource(RestaurantDataSource):
    def __init__(self, csv_path: str | None):
        self.csv_path = Path(csv_path) if csv_path else None
        self.records = list(self._load()) if self.csv_path and self.csv_path.exists() else []

    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        if not self.records:
            return []
        matched: list[RestaurantRecord] = []
        for record in self.records:
            if scope.lat is not None and scope.lon is not None and record.lat is not None and record.lon is not None:
                if haversine_km(scope.lat, scope.lon, record.lat, record.lon) <= radius_km:
                    matched.append(record)
                continue
            if record.county and scope.county and normalize_text(record.county) != normalize_text(scope.county):
                continue
            if record.district and scope.district and normalize_text(record.district) != normalize_text(scope.district):
                continue
            if scope.address_or_landmark and normalize_text(scope.address_or_landmark) in normalize_text(record.address):
                matched.append(record)
            elif record.district and scope.district:
                matched.append(record)
        return matched

    def _load(self) -> Iterable[RestaurantRecord]:
        assert self.csv_path is not None
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                yield RestaurantRecord(
                    name=pick(row, "name", "店名", "商業名稱") or "未命名店家",
                    address=pick(row, "address", "地址", "商業地址", "營業地址") or "",
                    county=pick(row, "county", "縣市") or "",
                    district=pick(row, "district", "鄉鎮市區", "行政區") or "",
                    category=pick(row, "category", "類型", "營業類別", "行業代號") or "未分類餐飲",
                    status=pick(row, "status", "狀態", "登記狀態", "營業狀態") or "",
                    lat=parse_float(pick(row, "lat", "latitude", "緯度")),
                    lon=parse_float(pick(row, "lon", "lng", "longitude", "經度")),
                )


class TrafficDataSource:
    def nearest(self, scope: GeoScope, limit: int = 5) -> list[TrafficRecord]:
        raise NotImplementedError


class CompositeRestaurantDataSource(RestaurantDataSource):
    def __init__(self, sources: list[RestaurantDataSource]):
        self.sources = sources

    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        records: list[RestaurantRecord] = []
        seen: set[tuple[str, str]] = set()
        for source in self.sources:
            for record in source.nearby(scope, radius_km):
                key = (record.name.strip().lower(), record.address.strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)
        return records


class GooglePlacesRestaurantDataSource(RestaurantDataSource):
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def nearby(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        if not self.api_key or scope.lat is None or scope.lon is None:
            return []
        records = self._nearby_new(scope, radius_km)
        if records:
            return records
        return self._nearby_legacy(scope, radius_km)

    def _nearby_new(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        body = {
            "includedTypes": ["restaurant", "cafe", "bakery", "meal_takeaway", "meal_delivery"],
            "maxResultCount": 20,
            "languageCode": "zh-TW",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": scope.lat, "longitude": scope.lon},
                    "radius": min(radius_km * 1000, 50000),
                }
            },
        }
        request = Request(
            "https://places.googleapis.com/v1/places:searchNearby",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.types,places.location,places.businessStatus",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        records = []
        for place in payload.get("places", []):
            location = place.get("location", {})
            types = place.get("types", [])
            records.append(
                RestaurantRecord(
                    name=place.get("displayName", {}).get("text", "未命名店家"),
                    address=place.get("formattedAddress", ""),
                    county=scope.county,
                    district=scope.district,
                    category=types[0] if types else "餐飲",
                    status=place.get("businessStatus", ""),
                    lat=parse_float(location.get("latitude")),
                    lon=parse_float(location.get("longitude")),
                )
            )
        return records

    def _nearby_legacy(self, scope: GeoScope, radius_km: float) -> list[RestaurantRecord]:
        params = urlencode(
            {
                "location": f"{scope.lat},{scope.lon}",
                "radius": str(int(min(radius_km * 1000, 50000))),
                "type": "restaurant",
                "language": "zh-TW",
                "key": self.api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?{params}"
        try:
            with urlopen(url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        if payload.get("status") not in ("OK", "ZERO_RESULTS"):
            return []
        records = []
        for place in payload.get("results", []):
            location = place.get("geometry", {}).get("location", {})
            records.append(
                RestaurantRecord(
                    name=place.get("name", "未命名店家"),
                    address=place.get("vicinity", ""),
                    county=scope.county,
                    district=scope.district,
                    category=(place.get("types") or ["餐飲"])[0],
                    status=place.get("business_status", ""),
                    lat=parse_float(location.get("lat")),
                    lon=parse_float(location.get("lng")),
                )
            )
        return records


class JSONTrafficDataSource(TrafficDataSource):
    def __init__(self, json_path: str | None):
        self.json_path = Path(json_path) if json_path else None
        self.records = list(self._load()) if self.json_path and self.json_path.exists() else []

    def nearest(self, scope: GeoScope, limit: int = 5) -> list[TrafficRecord]:
        if scope.lat is None or scope.lon is None:
            return []
        enriched = []
        for record in self.records:
            distance = haversine_km(scope.lat, scope.lon, record.lat, record.lon)
            enriched.append(TrafficRecord(**{**record.__dict__, "distance_km": distance}))
        return sorted(enriched, key=lambda item: item.distance_km or 999999)[:limit]

    def _load(self) -> Iterable[TrafficRecord]:
        assert self.json_path is not None
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("records", [])
        for row in rows:
            lat = parse_float(row.get("lat") or row.get("latitude") or row.get("PositionLat"))
            lon = parse_float(row.get("lon") or row.get("lng") or row.get("longitude") or row.get("PositionLon"))
            if lat is None or lon is None:
                continue
            yield TrafficRecord(
                lat=lat,
                lon=lon,
                car_flow=parse_float(row.get("car_flow") or row.get("small_vehicle_flow") or row.get("小型車流量")),
                motorcycle_flow=parse_float(row.get("motorcycle_flow") or row.get("機車流量")),
                speed=parse_float(row.get("speed") or row.get("平均速率")),
                timestamp=str(row.get("timestamp") or row.get("時間戳記") or ""),
                source=str(row.get("source") or "local_vd_json"),
            )


class CompositeTrafficDataSource(TrafficDataSource):
    def __init__(self, sources: list[TrafficDataSource]):
        self.sources = sources

    def nearest(self, scope: GeoScope, limit: int = 5) -> list[TrafficRecord]:
        records: list[TrafficRecord] = []
        for source in self.sources:
            records.extend(source.nearest(scope, limit))
        return sorted(records, key=lambda item: item.distance_km or 999999)[:limit]


class TDXTrafficDataSource(TrafficDataSource):
    def __init__(self, client_id: str | None, client_secret: str | None, vd_url: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.vd_url = vd_url
        self._token: str | None = None

    def nearest(self, scope: GeoScope, limit: int = 5) -> list[TrafficRecord]:
        if not self.client_id or not self.client_secret or scope.lat is None or scope.lon is None:
            return []
        token = self._access_token()
        if not token:
            return []
        static_payload, live_payload = self._fetch_vd_payloads(scope, token)
        if not static_payload and not live_payload:
            return []
        static_by_id = build_static_vd_index(static_payload)
        rows = []
        if live_payload:
            live_rows = live_payload if isinstance(live_payload, list) else live_payload.get("VDLives") or []
            for row in live_rows:
                vd_id = row.get("VDID") or row.get("vdid")
                static_row = static_by_id.get(vd_id, {})
                rows.append(merge_tdx_rows(static_row, row))
        elif static_payload:
            rows = static_payload if isinstance(static_payload, list) else static_payload.get("VDs") or []
        records = [record for record in (tdx_row_to_record(row, scope) for row in rows) if record]
        return sorted(records, key=lambda item: item.distance_km or 999999)[:limit]

    def _fetch_vd_payloads(self, scope: GeoScope, token: str) -> tuple[dict | list | None, dict | list | None]:
        if self.vd_url:
            return None, self._fetch_json(self.vd_url, token, cache_key="custom_live", ttl_seconds=120)
        city = TDX_CITY_CODES.get(scope.county)
        if not city:
            return None, None
        base = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic"
        static_url = f"{base}/VD/City/{city}?$format=JSON"
        live_url = f"{base}/Live/VD/City/{city}?$format=JSON"
        static_payload = self._fetch_json(static_url, token, cache_key=f"{city}_static", ttl_seconds=86400)
        live_payload = self._fetch_json(live_url, token, cache_key=f"{city}_live", ttl_seconds=120)
        return static_payload, live_payload

    def _fetch_json(self, url: str, token: str, cache_key: str, ttl_seconds: int) -> dict | list | None:
        cache_path = Path("outputs") / "tdx_cache" / f"{cache_key}.json"
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime <= ttl_seconds:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if "$format" not in url:
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}{urlencode({'$format': 'JSON'})}"
        request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            payload = urlopen_json(request)
        except Exception:
            return None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def _access_token(self) -> str | None:
        if self._token:
            return self._token
        body = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id or "",
                "client_secret": self.client_secret or "",
            }
        ).encode("utf-8")
        request = Request(
            "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            payload = urlopen_json(request)
        except Exception:
            return None
        self._token = payload.get("access_token")
        return self._token


def build_data_sources(config: AnalyzerConfig) -> tuple[RestaurantDataSource, TrafficDataSource]:
    restaurants = CompositeRestaurantDataSource(
        [
            GooglePlacesRestaurantDataSource(config.google_maps_api_key),
            CSVRestaurantDataSource(config.restaurant_csv),
        ]
    )
    traffic = CompositeTrafficDataSource(
        [
            TDXTrafficDataSource(config.tdx_client_id, config.tdx_client_secret, config.tdx_vd_url),
            JSONTrafficDataSource(config.traffic_vd_json),
        ]
    )
    return restaurants, traffic


def pick(row: dict, *keys: str) -> str | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return None


def parse_float(value: object) -> float | None:
    if value in (None, ""):
        return None


def tdx_row_to_record(row: dict, scope: GeoScope) -> TrafficRecord | None:
    position = row.get("VDPosition") or row.get("Position") or row.get("position") or {}
    lat = parse_float(position.get("PositionLat") or position.get("lat") or row.get("lat"))
    lon = parse_float(position.get("PositionLon") or position.get("lon") or row.get("lon"))
    if lat is None or lon is None:
        return None
    flows = row.get("LinkFlows") or row.get("linkFlows") or []
    car_flow = None
    motorcycle_flow = None
    speed = None
    for link in flows:
        lanes = link.get("Lanes") or link.get("lanes") or []
        for lane in lanes:
            vehicles = lane.get("Vehicles") or lane.get("vehicles") or []
            for vehicle in vehicles:
                vehicle_type = str(vehicle.get("VehicleType") or vehicle.get("vehicleType") or "")
                volume = parse_float(vehicle.get("Volume") or vehicle.get("volume"))
                vehicle_speed = parse_float(vehicle.get("Speed") or vehicle.get("speed"))
                if speed is None and vehicle_speed is not None:
                    speed = vehicle_speed
                if vehicle_type in ("M", "Motorcycle", "31", "機車"):
                    motorcycle_flow = (motorcycle_flow or 0) + (volume or 0)
                elif vehicle_type in ("S", "SmallVehicle", "小型車", "小客車", "21"):
                    car_flow = (car_flow or 0) + (volume or 0)
    return TrafficRecord(
        lat=lat,
        lon=lon,
        car_flow=car_flow,
        motorcycle_flow=motorcycle_flow,
        speed=speed,
        timestamp=str(row.get("DataCollectTime") or row.get("SrcUpdateTime") or row.get("UpdateTime") or ""),
        source="TDX_VD",
        distance_km=haversine_km(scope.lat or lat, scope.lon or lon, lat, lon),
    )


def urlopen_json(request: Request) -> dict | list:
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            context = ssl._create_unverified_context()
            with urlopen(request, timeout=15, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        raise


def build_static_vd_index(payload: dict | list | None) -> dict[str, dict]:
    if not payload:
        return {}
    rows = payload if isinstance(payload, list) else payload.get("VDs") or []
    indexed = {}
    for row in rows:
        vd_id = row.get("VDID") or row.get("vdid")
        if vd_id:
            indexed[vd_id] = row
    return indexed


def merge_tdx_rows(static_row: dict, live_row: dict) -> dict:
    merged = {**static_row, **live_row}
    if "VDPosition" not in merged and "VDPosition" in static_row:
        merged["VDPosition"] = static_row["VDPosition"]
    return merged
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
