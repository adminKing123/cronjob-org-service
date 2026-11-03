"""Background proxy dispatch so cron-job.org and other API calls are not blocked."""

from __future__ import annotations

import logging
import time

from database import get_session
from email_notify import send_failure_email_async
from models import TriggerLog
from proxy_dispatch import dispatch_to_apps_script

logger = logging.getLogger(__name__)


def run_proxy_dispatch_in_background(
    *,
    dispatch_id: int,
    workflow_id: str,
    workflow_name: str,
    owner_email: str,
    noney_trigger_url: str,
    noney_trigger_secret: str,
    apps_script_url: str,
) -> None:
    """Runs in a daemon thread — Apps Script may take minutes (noney retries)."""

    def _worker() -> None:
        started = time.perf_counter()
        session = get_session()
        try:
            log = session.get(TriggerLog, dispatch_id)
            if log is None:
                logger.error("Proxy worker: missing log id=%s", dispatch_id)
                return

            accepted, err = dispatch_to_apps_script(
                dispatch_id=dispatch_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                owner_email=owner_email,
                noney_trigger_url=noney_trigger_url,
                noney_trigger_secret=noney_trigger_secret,
                apps_script_url=apps_script_url,
            )
            log.duration_ms = int((time.perf_counter() - started) * 1000)

            if accepted:
                log.status = "dispatched"
                session.commit()
                logger.info(
                    "Proxy dispatched workflow=%s dispatch_id=%s (Apps Script accepted)",
                    workflow_id,
                    dispatch_id,
                )
                return

            log.status = "failed"
            log.error_detail = err or "Apps Script dispatch failed"
            session.commit()
            logger.warning(
                "Proxy dispatch failed workflow=%s: %s",
                workflow_id,
                log.error_detail,
            )
            if owner_email:
                send_failure_email_async(
                    to_email=owner_email,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    error_detail=log.error_detail,
                    status_code=None,
                    attempts=0,
                )
        except Exception:
            logger.exception("Proxy worker error dispatch_id=%s", dispatch_id)
            try:
                session.rollback()
                log = session.get(TriggerLog, dispatch_id)
                if log:
                    log.status = "failed"
                    log.error_detail = "Background proxy dispatch error"
                    session.commit()
            except Exception:
                pass
        finally:
            session.close()

    import threading

    threading.Thread(target=_worker, name=f"proxy-{dispatch_id}", daemon=True).start()
