"""Admin-editable settings (SQLite app_settings)."""

from __future__ import annotations

from datetime import datetime, timezone

from database import get_session
from models import AppSetting

KEY_PROXY_ENABLED = "proxy_enabled"
KEY_PROXY_APPS_SCRIPT_URL = "proxy_apps_script_url"


def _get(key: str, default: str = "") -> str:
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        return row.value if row is not None else default
    finally:
        session.close()


def _set(key: str, value: str) -> None:
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


def seed_settings() -> None:
    session = get_session()
    try:
        for key, default in (
            (KEY_PROXY_ENABLED, "false"),
            (KEY_PROXY_APPS_SCRIPT_URL, ""),
        ):
            if session.get(AppSetting, key) is None:
                session.add(AppSetting(key=key, value=default))
        session.commit()
    finally:
        session.close()


def proxy_enabled() -> bool:
    return _get(KEY_PROXY_ENABLED, "false").lower() in ("1", "true", "yes", "on")


def proxy_apps_script_url() -> str:
    return _get(KEY_PROXY_APPS_SCRIPT_URL, "").strip()


def admin_form_values() -> dict[str, str]:
    return {
        KEY_PROXY_ENABLED: _get(KEY_PROXY_ENABLED, "false"),
        KEY_PROXY_APPS_SCRIPT_URL: _get(KEY_PROXY_APPS_SCRIPT_URL, ""),
    }


def save_admin_form(form) -> list[str]:
    errors: list[str] = []
    enabled = form.get(KEY_PROXY_ENABLED) == "on"
    url = (form.get(KEY_PROXY_APPS_SCRIPT_URL) or "").strip()
    if enabled and not url:
        errors.append("Apps Script web app URL is required when proxy is enabled.")
    if url and not url.startswith("https://"):
        errors.append("Apps Script URL must start with https://")
    if errors:
        return errors
    _set(KEY_PROXY_ENABLED, "true" if enabled else "false")
    _set(KEY_PROXY_APPS_SCRIPT_URL, url)
    return []
