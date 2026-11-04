"""cron-job.org schedule timezones (same list as noney-api)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).resolve().parent / "data" / "schedule_timezones.json"


@lru_cache(maxsize=1)
def load_schedule_timezones() -> list[dict]:
    with _DATA_FILE.open(encoding="utf-8") as f:
        payload = json.load(f)
    zones = payload.get("timezones")
    if not isinstance(zones, list):
        raise RuntimeError("schedule_timezones.json: missing timezones array")
    return zones


@lru_cache(maxsize=1)
def allowed_schedule_timezone_ids() -> frozenset[str]:
    return frozenset(str(z["value"]) for z in load_schedule_timezones() if z.get("value"))


def is_allowed_schedule_timezone(tz: str) -> bool:
    return (tz or "").strip() in allowed_schedule_timezone_ids()
