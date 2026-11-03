"""Forward schedule fires to Google Apps Script (proxy mode)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

import config

logger = logging.getLogger(__name__)


def build_callback_url() -> str:
    return f"{config.PUBLIC_HOST.rstrip('/')}/api/proxy/callback"


def dispatch_to_apps_script(
    *,
    dispatch_id: int,
    workflow_id: str,
    workflow_name: str,
    owner_email: str,
    noney_trigger_url: str,
    noney_trigger_secret: str,
    apps_script_url: str,
) -> tuple[bool, str | None]:
    """
    POST job to Apps Script. Returns (accepted, error_detail).
    Apps Script must call noney and report via callback.
    """
    fired_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "dispatch_id": dispatch_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "owner_email": owner_email,
        "fired_at": fired_at,
        "noney_trigger_url": noney_trigger_url,
        "noney_trigger_secret": noney_trigger_secret,
        "callback_url": build_callback_url(),
        "callback_secret": config.SERVICE_API_KEY,
        "max_attempts": config.WEBHOOK_RETRY_ATTEMPTS,
        "retry_base_seconds": config.WEBHOOK_RETRY_BASE_SECONDS,
    }
    try:
        resp = requests.post(
            apps_script_url,
            json=payload,
            timeout=90,
            headers={"Content-Type": "application/json"},
        )
        if 200 <= resp.status_code < 300:
            return True, None
        return False, f"Apps Script HTTP {resp.status_code}: {resp.text[:500]}"
    except requests.RequestException as exc:
        logger.exception("Apps Script dispatch failed workflow=%s", workflow_id)
        return False, str(exc)
