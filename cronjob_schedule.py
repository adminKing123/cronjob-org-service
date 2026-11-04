"""
Map Fuse schedule node config → cron-job.org JobSchedule arrays.

cron-job.org: minutes/hours/mdays/months/wdays; use -1 for "every".
wdays: 0=Sunday … 6=Saturday (UNIX).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def _every() -> list[int]:
    return [-1]


def _list_or_every(values: list | None, span: int) -> list[int]:
    if not values:
        return _every()
    nums = sorted({int(v) for v in values if str(v).strip() != ""})
    if not nums:
        return _every()
    if len(nums) >= span:
        return _every()
    return nums


def _fuse_dow_to_cronjob(d: int) -> int:
    """Fuse custom UI: 0=Monday … 6=Sunday → cron-job wdays (0=Sunday)."""
    return (int(d) + 1) % 7


def _truthy(value: object) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def resolve_expires_at(schedule_config: dict, *, timezone: str) -> int:
    """
    cron-job.org expiresAt: YYYYMMDDhhmmss in the job's timezone, or 0 = never.
    """
    cfg = schedule_config or {}
    if not _truthy(cfg.get("schedule_expires_enabled")):
        return 0

    tz_name = (timezone or cfg.get("timezone") or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    try:
        year = int(cfg.get("schedule_expires_year"))
        month = int(cfg.get("schedule_expires_month"))
        day = int(cfg.get("schedule_expires_day"))
        hour = int(cfg.get("schedule_expires_hour") or 0)
        minute = int(cfg.get("schedule_expires_minute") or 0)
        dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    except (TypeError, ValueError):
        return 0

    return int(dt.strftime("%Y%m%d%H%M%S"))


def build_cronjob_schedule(schedule_config: dict, *, timezone: str, expires_at: int | None = None) -> dict:
    cfg = schedule_config or {}
    mode = (cfg.get("schedule_mode") or "interval").lower()
    tz = (timezone or cfg.get("timezone") or "UTC").strip() or "UTC"

    if expires_at is None:
        expires_at = resolve_expires_at(cfg, timezone=tz)
    else:
        expires_at = int(expires_at or 0)

    schedule: dict[str, Any] = {
        "timezone": tz,
        "expiresAt": expires_at,
        "minutes": _every(),
        "hours": _every(),
        "mdays": _every(),
        "months": _every(),
        "wdays": _every(),
    }

    if mode == "interval":
        try:
            step = max(1, int(cfg.get("interval_minutes") or 15))
        except (TypeError, ValueError):
            step = 15
        if step >= 60:
            schedule["minutes"] = [0]
            schedule["hours"] = _every()
        else:
            schedule["minutes"] = list(range(0, 60, step))
        return schedule

    try:
        hour = int(cfg.get("hour") or 0)
        minute = int(cfg.get("minute") or 0)
    except (TypeError, ValueError):
        hour, minute = 0, 0

    schedule["minutes"] = [minute]
    schedule["hours"] = [hour]

    if mode == "daily":
        return schedule

    if mode == "monthly":
        schedule["mdays"] = [int(cfg.get("day_of_month") or 1)]
        return schedule

    if mode == "yearly":
        schedule["mdays"] = [int(cfg.get("day_of_month") or 1)]
        schedule["months"] = [int(cfg.get("month") or 1)]
        return schedule

    if mode == "custom":
        custom = cfg.get("custom") if isinstance(cfg.get("custom"), dict) else {}
        schedule["minutes"] = _list_or_every(custom.get("minutes"), 60)
        schedule["hours"] = _list_or_every(custom.get("hours"), 24)
        schedule["mdays"] = _list_or_every(custom.get("days_of_month"), 31)
        schedule["months"] = _list_or_every(custom.get("months"), 12)
        dow = custom.get("days_of_week") or []
        if dow:
            schedule["wdays"] = sorted({_fuse_dow_to_cronjob(d) for d in dow})
        return schedule

    return schedule


def _cron_part_from_list(values: list | None, full_span: int | None = None) -> str:
    if not values:
        return "*"
    nums: list[int] = []
    for v in values:
        try:
            nums.append(int(v))
        except (TypeError, ValueError):
            continue
    if not nums:
        return "*"
    nums = sorted(set(nums))
    if full_span is not None and len(nums) == full_span:
        return "*"
    return ",".join(str(n) for n in nums)


def build_cron_expression(schedule_config: dict) -> str:
    """5-field UNIX crontab for admin display (aligned with Fuse UI)."""
    cfg = schedule_config or {}
    mode = (cfg.get("schedule_mode") or "interval").lower()

    if mode == "interval":
        try:
            step = max(1, int(cfg.get("interval_minutes") or 15))
        except (TypeError, ValueError):
            step = 15
        if step >= 60:
            return "0 * * * *"
        return f"*/{step} * * * *"

    try:
        hour = int(cfg.get("hour") or 0)
        minute = int(cfg.get("minute") or 0)
    except (TypeError, ValueError):
        hour, minute = 0, 0

    if mode == "daily":
        return f"{minute} {hour} * * *"
    if mode == "monthly":
        return f"{minute} {hour} {int(cfg.get('day_of_month') or 1)} * *"
    if mode == "yearly":
        return (
            f"{minute} {hour} {int(cfg.get('day_of_month') or 1)} "
            f"{int(cfg.get('month') or 1)} *"
        )
    if mode == "custom":
        custom = cfg.get("custom") if isinstance(cfg.get("custom"), dict) else {}
        return " ".join(
            [
                _cron_part_from_list(custom.get("minutes"), 60),
                _cron_part_from_list(custom.get("hours"), 24),
                _cron_part_from_list(custom.get("days_of_month"), 31),
                _cron_part_from_list(custom.get("months"), 12),
                _cron_part_from_list(custom.get("days_of_week"), 7),
            ]
        )
    return "0 0 * * *"
