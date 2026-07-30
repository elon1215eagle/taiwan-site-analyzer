from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from urllib.request import Request, urlopen


class DistrictPopulationSource:
    source_name = "內政部戶政司 ODRP019"

    def __init__(self, statistic_year: str = "114", timeout_seconds: float = 8):
        self.statistic_year = statistic_year
        self.timeout_seconds = timeout_seconds
        self._cache: list[dict] | None = None

    def districts(self, county: str) -> list[dict]:
        normalized_county = county.replace("臺", "台").strip()
        rows = self._load()
        totals: dict[str, int] = defaultdict(int)
        for row in rows:
            site_id = str(row.get("site_id") or "").replace("臺", "台")
            if not site_id.startswith(normalized_county):
                continue
            district = site_id[len(normalized_county) :]
            if not district:
                continue
            totals[district] += sum(
                integer(row.get(field))
                for field in (
                    "household_ordinary_m",
                    "household_ordinary_f",
                    "household_business_m",
                    "household_business_f",
                    "household_single_m",
                    "household_single_f",
                )
            )
        return [
            {
                "county": normalized_county,
                "district": district,
                "population": population,
                "data_as_of": f"{self.statistic_year} 年",
                "source": self.source_name,
            }
            for district, population in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]

    def _load(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        first = self._fetch_page(1)
        pages = max(1, integer(first.get("totalPage")))
        rows = list(first.get("responseData") or [])
        for page in range(2, pages + 1):
            rows.extend(self._fetch_page(page).get("responseData") or [])
        self._cache = rows
        return rows

    def _fetch_page(self, page: int) -> dict:
        url = (
            "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/"
            f"ODRP019/{self.statistic_year}?page={page}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "GDO-Site-Selection/1.0",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()
