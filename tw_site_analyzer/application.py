from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable

from .analysis import SiteSelectionAnalyzer, public_json
from .market_report import build_market_report, build_market_report_text
from .nearby import build_nearby_report, nearby_stores
from .observability import ServiceTelemetry, build_health_report
from .recommendation import build_reverse_report, recommend_locations
from .report import build_chinese_report


@dataclass(frozen=True)
class EndpointResponse:
    payload: dict
    status_code: int = 200


class RequestValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SiteAnalyzerApplication:
    def __init__(
        self,
        analyzer: SiteSelectionAnalyzer | None = None,
        telemetry: ServiceTelemetry | None = None,
    ):
        self.analyzer = analyzer or SiteSelectionAnalyzer()
        self.telemetry = telemetry or ServiceTelemetry()
        self.routes: dict[str, Callable[[dict], dict]] = {
            "/api/analyze": self._analyze,
            "/api/recommend": self._recommend,
            "/api/nearby": self._nearby,
            "/api/market-report": self._market_report,
        }

    def health(self) -> dict:
        return build_health_report(self.analyzer.config, self.telemetry)

    def execute(self, path: str, body: dict) -> EndpointResponse:
        handler = self.routes.get(path)
        if handler is None:
            return EndpointResponse({"error": "NOT_FOUND", "message": "Endpoint not found."}, 404)
        started = monotonic()
        try:
            payload = handler(body)
            response = EndpointResponse(payload)
        except RequestValidationError as error:
            response = EndpointResponse({"error": error.code, "message": error.message}, 400)
        except Exception:
            response = EndpointResponse(
                {"error": "INTERNAL_ERROR", "message": "分析暫時無法完成，請稍後再試。"},
                500,
            )
        self.telemetry.record_request(path, response.status_code)
        elapsed_ms = int((monotonic() - started) * 1000)
        response.payload.setdefault("meta", {})["endpoint_elapsed_ms"] = elapsed_ms
        return response

    def _analyze(self, body: dict) -> dict:
        location = required_text(body, "location", "LOCATION_REQUIRED", "請輸入縣市、行政區、路段或地標。")
        result = public_json(self.analyzer.analyze(location))
        return {"report": build_chinese_report(result), "json": result}

    def _recommend(self, body: dict) -> dict:
        business_type = required_text(body, "business_type", "RECOMMEND_INPUT_REQUIRED", "請輸入業態與縣市。")
        county = required_text(body, "county", "RECOMMEND_INPUT_REQUIRED", "請輸入業態與縣市。")
        district = str(body.get("district", "")).strip()
        result = public_json(recommend_locations(self.analyzer, business_type, county, district))
        return {"report": build_reverse_report(result), "json": result}

    def _nearby(self, body: dict) -> dict:
        location = required_text(body, "location", "LOCATION_REQUIRED", "請輸入查詢地址或地標。")
        keyword = str(body.get("keyword", "")).strip()
        radius_km = number_field(body, "radius_km", 0.8, 0.1, 5.0)
        limit = int(number_field(body, "limit", 40, 1, 60))
        result = public_json(nearby_stores(self.analyzer, location, radius_km, keyword, limit))
        return {"report": build_nearby_report(result), "json": result}

    def _market_report(self, body: dict) -> dict:
        location = required_text(body, "location", "MARKET_REPORT_INPUT_REQUIRED", "請輸入地址與業態。")
        business_type = required_text(
            body,
            "business_type",
            "MARKET_REPORT_INPUT_REQUIRED",
            "請輸入地址與業態。",
        )
        radius_km = number_field(body, "radius_km", 0.8, 0.1, 5.0)
        result = public_json(build_market_report(self.analyzer, location, business_type, radius_km))
        self.telemetry.record_market_report(result)
        return {"report": build_market_report_text(result), "json": result}


def required_text(body: dict, field: str, code: str, message: str) -> str:
    value = str(body.get(field, "")).strip()
    if not value:
        raise RequestValidationError(code, message)
    return value


def number_field(body: dict, field: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = body.get(field, default)
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as error:
        raise RequestValidationError("INVALID_NUMBER", f"{field} 必須是數字。") from error
    if value < minimum or value > maximum:
        raise RequestValidationError(
            "NUMBER_OUT_OF_RANGE",
            f"{field} 必須介於 {minimum:g} 與 {maximum:g} 之間。",
        )
    return value
