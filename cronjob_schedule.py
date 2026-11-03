"""
Map Fuse schedule node config → cron-job.org JobSchedule arrays.

cron-job.org: minutes/hours/mdays/months/wdays; use -1 for "every".
wdays: 0=Sunday … 6=Saturday (UNIX).
"""

from __future__ import annotations

from typing import Any


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


def build_cronjob_schedule(schedule_config: dict, *, timezone: str, expires_at: int = 0) -> dict:
    cfg = schedule_config or {}
    mode = (cfg.get("schedule_mode") or "interval").lower()
    tz = (timezone or cfg.get("timezone") or "UTC").strip() or "UTC"

    schedule: dict[str, Any] = {
        "timezone": tz,
        "expiresAt": int(expires_at or 0),
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
        minute_field = (custom.get("minute") or "").strip() or _cron_part_from_list(
            custom.get("minutes"), 60
        )
        hour_field = (custom.get("hour") or "").strip() or _cron_part_from_list(
            custom.get("hours"), 24
        )
        day_field = (custom.get("day") or "").strip() or _cron_part_from_list(
            custom.get("days_of_month"), 31
        )
        month_field = (custom.get("month") or "").strip() or _cron_part_from_list(
            custom.get("months"), 12
        )
        dow_field = (custom.get("day_of_week") or "").strip() or _cron_part_from_list(
            custom.get("days_of_week"), 7
        )
        return f"{minute_field} {hour_field} {day_field} {month_field} {dow_field}"
    return "0 0 * * *"
