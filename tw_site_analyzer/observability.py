from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock

from .config import AnalyzerConfig

SERVICE_NAME = "taiwan-site-selection-analyzer"
SERVICE_VERSION = "2026.07-market-evidence"


@dataclass
class ServiceTelemetry:
    started_monotonic: float = field(default_factory=time.monotonic)
    requests_total: int = 0
    errors_total: int = 0
    requests_by_endpoint: dict[str, int] = field(default_factory=dict)
    last_market_report: dict | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_request(self, endpoint: str, status_code: int) -> None:
        with self._lock:
            self.requests_total += 1
            self.requests_by_endpoint[endpoint] = self.requests_by_endpoint.get(endpoint, 0) + 1
            if status_code >= 500:
                self.errors_total += 1

    def record_market_report(self, result: dict) -> None:
        restaurant = result["evidence_status"]["sources"]["restaurants"]
        with self._lock:
            self.last_market_report = {
                "analysis_id": result["analysis_id"],
                "district": result["geo_scope"].get("district", "") or "unknown",
                "business_type": result["business_type"],
                "status": result["evidence_status"]["status"],
                "restaurant_status": restaurant["status"],
                "elapsed_ms": result["analysis_elapsed_ms"],
                "error_type": restaurant.get("error_type"),
                "analyzed_at": result["analyzed_at"],
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "uptime_seconds": int(time.monotonic() - self.started_monotonic),
                "requests_total": self.requests_total,
                "errors_total": self.errors_total,
                "requests_by_endpoint": dict(self.requests_by_endpoint),
                "last_market_report": dict(self.last_market_report) if self.last_market_report else None,
            }


def build_health_report(config: AnalyzerConfig, telemetry: ServiceTelemetry) -> dict:
    dependencies = {
        "google_maps": {
            "configured": bool(config.google_maps_api_key),
            "provides": ["geocoding", "restaurants", "reviews"],
        },
        "tdx": {
            "configured": bool(config.tdx_client_id and config.tdx_client_secret),
            "provides": ["traffic"],
        },
        "restaurant_csv": {
            "configured": bool(config.restaurant_csv),
            "provides": ["restaurants"],
        },
        "traffic_json": {
            "configured": bool(config.traffic_vd_json),
            "provides": ["traffic"],
        },
    }
    restaurant_ready = dependencies["google_maps"]["configured"] or dependencies["restaurant_csv"]["configured"]
    traffic_ready = dependencies["tdx"]["configured"] or dependencies["traffic_json"]["configured"]
    capabilities = {
        "market_report": "ready" if restaurant_ready else "degraded",
        "site_analysis": "ready" if restaurant_ready and traffic_ready else "degraded",
        "reverse_recommendation": "ready",
    }
    status = "healthy" if all(value == "ready" for value in capabilities.values()) else "degraded"
    return {
        "ok": True,
        "status": status,
        "service": SERVICE_NAME,
        "service_version": SERVICE_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "deployment": {
            "environment": os.getenv("RENDER", "false") == "true" and "render" or "local",
            "service_name": os.getenv("RENDER_SERVICE_NAME", SERVICE_NAME),
            "commit_sha": os.getenv("RENDER_GIT_COMMIT", os.getenv("GIT_COMMIT", "unknown")),
            "external_url": os.getenv("RENDER_EXTERNAL_URL", ""),
        },
        "capabilities": capabilities,
        "dependencies": dependencies,
        "runtime": telemetry.snapshot(),
    }
