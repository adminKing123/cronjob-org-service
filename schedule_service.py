"""Register, update, and remove workflow schedules."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import config
import cron_org_client
from cronjob_schedule import build_cron_expression, build_cronjob_schedule, resolve_expires_at
from schedule_timezones import is_allowed_schedule_timezone
from models import WorkflowSchedule

logger = logging.getLogger(__name__)


def public_webhook_url(workflow_id: str) -> str:
    return f"{config.PUBLIC_HOST}/webhook/{workflow_id}"


def upsert_schedule(session: Session, payload: dict) -> WorkflowSchedule:
    workflow_id = str(payload["workflow_id"]).strip()
    if not workflow_id:
        raise ValueError("workflow_id is required")

    schedule_config = payload.get("schedule_config") or {}
    timezone_name = str(payload.get("timezone") or schedule_config.get("timezone") or "UTC").strip() or "UTC"
    if not is_allowed_schedule_timezone(timezone_name):
        raise ValueError(f"Unsupported schedule timezone: {timezone_name}")
    cron_expression = build_cron_expression(schedule_config)

    row = session.get(WorkflowSchedule, workflow_id)
    if row is None:
        row = WorkflowSchedule(workflow_id=workflow_id)
        session.add(row)

    row.enabled = True
    row.workflow_name = str(payload.get("workflow_name") or "").strip()
    row.owner_id = str(payload.get("owner_id") or "").strip()
    row.owner_email = str(payload.get("owner_email") or "").strip()
    row.cron_expression = cron_expression
    row.timezone = timezone_name
    row.schedule_config_json = json.dumps(schedule_config)
    row.noney_trigger_url = str(payload["noney_trigger_url"]).strip()
    row.noney_trigger_secret = str(payload["noney_trigger_secret"]).strip()
    row.public_webhook_url = public_webhook_url(workflow_id)
    expires_at = resolve_expires_at(schedule_config, timezone=timezone_name)
    row.expires_at = expires_at
    row.updated_at = datetime.now(timezone.utc)

    cj_schedule = build_cronjob_schedule(
        schedule_config,
        timezone=timezone_name,
        expires_at=expires_at,
    )
    title = f"Fuse {row.workflow_name or workflow_id}"[:128]

    if row.cron_org_job_id:
        try:
            cron_org_client.update_job(
                row.cron_org_job_id,
                url=row.public_webhook_url,
                title=title,
                schedule=cj_schedule,
                enabled=True,
            )
        except cron_org_client.CronOrgError:
            logger.warning(
                "cron-job.org update failed for job %s — recreating",
                row.cron_org_job_id,
            )
            old_id = row.cron_org_job_id
            row.cron_org_job_id = None
            try:
                cron_org_client.delete_job(old_id)
            except cron_org_client.CronOrgError:
                pass
            row.cron_org_job_id = cron_org_client.create_job(
                url=row.public_webhook_url,
                title=title,
                schedule=cj_schedule,
            )
    else:
        row.cron_org_job_id = cron_org_client.create_job(
            url=row.public_webhook_url,
            title=title,
            schedule=cj_schedule,
        )

    session.commit()
    session.refresh(row)
    return row


def delete_schedule(session: Session, workflow_id: str) -> bool:
    row = session.get(WorkflowSchedule, workflow_id)
    if row is None:
        return False
    if row.cron_org_job_id:
        try:
            cron_org_client.delete_job(row.cron_org_job_id)
        except cron_org_client.CronOrgError:
            logger.exception("Failed to delete cron-job.org job %s", row.cron_org_job_id)
    session.delete(row)
    session.commit()
    return True
