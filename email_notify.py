import logging
import threading
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


def send_failure_email(
    *,
    to_email: str,
    workflow_id: str,
    workflow_name: str,
    error_detail: str,
    status_code: int | None,
    attempts: int,
) -> bool:
    url = f"{config.EMAIL_SERVICE_HOST}/api/send-email"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.EMAIL_SERVICE_API_KEY}",
    }
    subject = f"Scheduled workflow failed to run: {workflow_name or workflow_id}"
    body = (
        f"Your scheduled workflow could not be triggered after {attempts} attempt(s).\n\n"
        f"Workflow: {workflow_name or '(unnamed)'}\n"
        f"Workflow ID: {workflow_id}\n"
        f"HTTP status: {status_code if status_code is not None else 'n/a'}\n\n"
        f"Error:\n{error_detail}\n\n"
        "The schedule is still registered in Cron Service. "
        "Check noney-api logs and re-activate the workflow if needed."
    )
    payload = {
        "to": to_email,
        "subject": subject,
        "body": body,
        "send_as_html": False,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            return True
        logger.error("Email service error (%s): %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        logger.error("Email service network error: %s", exc)
    return False


def send_failure_email_async(**kwargs: Any) -> None:
    """Fire-and-forget failure notification — does not block webhook or callback."""

    threading.Thread(
        target=send_failure_email,
        kwargs=kwargs,
        name="failure-email",
        daemon=True,
    ).start()
