from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        clean_key = key.strip().lstrip("\ufeff")
        os.environ.setdefault(clean_key, value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class AnalyzerConfig:
    restaurant_csv: str | None = None
    traffic_vd_json: str | None = None
    google_maps_api_key: str | None = None
    tdx_client_id: str | None = None
    tdx_client_secret: str | None = None
    tdx_vd_url: str | None = None
    default_radius_km: float = 3.0
    restaurant_radii_km: tuple[float, float, float] = (1.0, 2.0, 3.0)

    @classmethod
    def from_env(cls) -> "AnalyzerConfig":
        load_local_env()
        return cls(
            restaurant_csv=os.getenv("TW_RESTAURANT_CSV"),
            traffic_vd_json=os.getenv("TW_TRAFFIC_VD_JSON"),
            google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
            tdx_client_id=os.getenv("TDX_CLIENT_ID"),
            tdx_client_secret=os.getenv("TDX_CLIENT_SECRET"),
            tdx_vd_url=os.getenv("TDX_VD_URL"),
        )
