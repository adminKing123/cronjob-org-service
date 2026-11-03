"""Background direct noney trigger so cron-job.org webhook returns immediately."""

from __future__ import annotations

import logging
import threading
import time

from database import get_session
from models import TriggerLog
from noney_trigger import trigger_noney_with_retries

logger = logging.getLogger(__name__)


def run_direct_trigger_in_background(
    *,
    dispatch_id: int,
    workflow_id: str,
    workflow_name: str,
    owner_email: str,
    noney_trigger_url: str,
    noney_trigger_secret: str,
) -> None:
    """Runs in a daemon thread — noney retries may take many minutes."""

    def _worker() -> None:
        started = time.perf_counter()
        session = get_session()
        try:
            log = session.get(TriggerLog, dispatch_id)
            if log is None:
                logger.error("Direct worker: missing log id=%s", dispatch_id)
                return

            ok, attempts, status_code, err = trigger_noney_with_retries(
                noney_trigger_url=noney_trigger_url,
                noney_trigger_secret=noney_trigger_secret,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                owner_email=owner_email,
            )
            log.attempts = attempts
            log.noney_status_code = status_code
            log.error_detail = err
            log.status = "success" if ok else "failed"
            log.duration_ms = int((time.perf_counter() - started) * 1000)
            session.commit()
            logger.info(
                "Direct trigger finished workflow=%s dispatch_id=%s ok=%s attempts=%s",
                workflow_id,
                dispatch_id,
                ok,
                attempts,
            )
        except Exception:
            logger.exception("Direct worker error dispatch_id=%s", dispatch_id)
            try:
                session.rollback()
                log = session.get(TriggerLog, dispatch_id)
                if log:
                    log.status = "failed"
                    log.error_detail = "Background direct trigger error"
                    session.commit()
            except Exception:
                pass
        finally:
            session.close()

    threading.Thread(
        target=_worker,
        name=f"direct-{dispatch_id}",
        daemon=True,
    ).start()
