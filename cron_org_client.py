"""Thin client for https://api.cron-job.org REST API."""

from __future__ import annotations

import json
import logging

import requests

import config

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.cron-job.org"


class CronOrgError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.CRON_ORG_API_KEY}",
        "Content-Type": "application/json",
    }


def create_job(*, url: str, title: str, schedule: dict) -> int:
    payload = {
        "job": {
            "url": url,
            "enabled": True,
            "title": title[:128],
            "requestMethod": 0,
            "saveResponses": True,
            "schedule": schedule,
        }
    }
    resp = requests.put(
        f"{ENDPOINT}/jobs",
        headers=_headers(),
        data=json.dumps(payload),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error("cron-job.org create failed (%s): %s", resp.status_code, resp.text)
        raise CronOrgError(f"cron-job.org create failed: HTTP {resp.status_code}")
    data = resp.json()
    job_id = data.get("jobId")
    if not job_id:
        raise CronOrgError("cron-job.org create returned no jobId")
    return int(job_id)


def update_job(job_id: int, *, url: str, title: str, schedule: dict, enabled: bool = True) -> None:
    payload = {
        "job": {
            "url": url,
            "enabled": enabled,
            "title": title[:128],
            "requestMethod": 0,
            "schedule": schedule,
        }
    }
    resp = requests.patch(
        f"{ENDPOINT}/jobs/{job_id}",
        headers=_headers(),
        data=json.dumps(payload),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error("cron-job.org update failed (%s): %s", resp.status_code, resp.text)
        raise CronOrgError(f"cron-job.org update failed: HTTP {resp.status_code}")


def delete_job(job_id: int) -> None:
    resp = requests.delete(
        f"{ENDPOINT}/jobs/{job_id}",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code not in (200, 404):
        logger.error("cron-job.org delete failed (%s): %s", resp.status_code, resp.text)
        raise CronOrgError(f"cron-job.org delete failed: HTTP {resp.status_code}")
