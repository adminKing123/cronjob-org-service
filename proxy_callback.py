"""Handle Apps Script completion callbacks."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from email_notify import send_failure_email
from models import TriggerLog

logger = logging.getLogger(__name__)


def apply_proxy_callback(
    session: Session,
    *,
    dispatch_id: int,
    success: bool,
    attempts: int,
    status_code: int | None,
    error_detail: str | None,
) -> tuple[bool, str | None]:
    """
    Update trigger log from Apps Script. Sends owner email on failure.
    Returns (found, error_message).
    """
    log = session.get(TriggerLog, dispatch_id)
    if log is None:
        return False, "Unknown dispatch_id"

    if log.status not in ("pending", "dispatched"):
        return True, None

    log.attempts = max(0, int(attempts or 0))
    log.noney_status_code = status_code
    log.error_detail = error_detail
    log.status = "success" if success else "failed"
    session.commit()

    if not success and log.owner_email:
        send_failure_email(
            to_email=log.owner_email,
            workflow_id=log.workflow_id,
            workflow_name=log.workflow_name,
            error_detail=error_detail or "Proxy reported failure",
            status_code=status_code,
            attempts=log.attempts,
        )
        logger.warning(
            "Proxy callback failure workflow=%s dispatch=%s",
            log.workflow_id,
            dispatch_id,
        )
    return True, None
