"""Call noney-api schedule webhook with retries and failure email."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

import config
from email_notify import send_failure_email

logger = logging.getLogger(__name__)


def _post_once(url: str, secret: str) -> tuple[bool, int | None, str | None]:
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }
    payload = {"fired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if 200 <= resp.status_code < 300:
            return True, resp.status_code, None
        return False, resp.status_code, resp.text[:2000]
    except requests.RequestException as exc:
        return False, None, str(exc)


def trigger_noney_with_retries(
    *,
    noney_trigger_url: str,
    noney_trigger_secret: str,
    workflow_id: str,
    workflow_name: str,
    owner_email: str,
) -> tuple[bool, int, int | None, str | None]:
    """
    Returns (ok, attempts, last_status_code, error_detail).
    Linear backoff: base * attempt seconds between tries.
    """
    attempts = 0
    last_code: int | None = None
    last_error: str | None = None
    max_attempts = max(1, config.WEBHOOK_RETRY_ATTEMPTS)

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        ok, code, err = _post_once(noney_trigger_url, noney_trigger_secret)
        last_code, last_error = code, err
        if ok:
            return True, attempts, last_code, None
        if attempt < max_attempts:
            delay = config.WEBHOOK_RETRY_BASE_SECONDS * attempt
            logger.warning(
                "noney trigger failed workflow=%s attempt=%s/%s — retry in %ss: %s",
                workflow_id,
                attempt,
                max_attempts,
                delay,
                err,
            )
            time.sleep(delay)

    if owner_email:
        send_failure_email(
            to_email=owner_email,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            error_detail=last_error or "Unknown error",
            status_code=last_code,
            attempts=attempts,
        )

    return False, attempts, last_code, last_error
