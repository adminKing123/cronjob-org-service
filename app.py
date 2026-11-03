import secrets
import time
from functools import wraps

from flask import Flask, jsonify, render_template, request

import config
from admin_routes import admin_bp
from database import get_session, init_db
from email_notify import send_failure_email
from models import TriggerLog, WorkflowSchedule
from noney_trigger import trigger_noney_with_retries
from proxy_callback import apply_proxy_callback
from proxy_dispatch import dispatch_to_apps_script
from schedule_service import delete_schedule, upsert_schedule
from settings_store import proxy_apps_script_url, proxy_enabled

app = Flask(__name__)
app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 12
app.register_blueprint(admin_bp)
init_db()


def _extract_api_key() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return request.headers.get("X-API-Key", "").strip() or None


def require_api_key(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        provided = _extract_api_key()
        if not provided or not secrets.compare_digest(provided, config.SERVICE_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def _client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


@app.get("/docs")
def public_api_docs():
    return render_template("api_docs.html", in_admin=False)


@app.post("/api/schedules/upsert")
@require_api_key
def api_upsert_schedule():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = (
        "workflow_id",
        "noney_trigger_url",
        "noney_trigger_secret",
        "schedule_config",
    )
    for key in required:
        if not data.get(key):
            return jsonify({"error": f"Missing required field: {key}"}), 400

    session = get_session()
    try:
        row = upsert_schedule(session, data)
        return jsonify(
            {
                "ok": True,
                "workflow_id": row.workflow_id,
                "cron_org_job_id": row.cron_org_job_id,
                "public_webhook_url": row.public_webhook_url,
                "cron_expression": row.cron_expression,
            }
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 502
    finally:
        session.close()


@app.delete("/api/schedules/<workflow_id>")
@require_api_key
def api_delete_schedule(workflow_id: str):
    session = get_session()
    try:
        removed = delete_schedule(session, workflow_id.strip())
        if not removed:
            return jsonify({"ok": True, "removed": False}), 200
        return jsonify({"ok": True, "removed": True})
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 502
    finally:
        session.close()


@app.post("/api/proxy/callback")
@require_api_key
def api_proxy_callback():
    """
    Apps Script reports noney webhook result after retries.
    Body: dispatch_id, success, attempts?, status_code?, error?
    """
    data = request.get_json(silent=True) or {}
    try:
        dispatch_id = int(data.get("dispatch_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "dispatch_id required"}), 400

    success = bool(data.get("success"))
    attempts = int(data.get("attempts") or 0)
    status_code = data.get("status_code")
    if status_code is not None:
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            status_code = None
    error_detail = (data.get("error") or data.get("error_detail") or "").strip() or None

    session = get_session()
    try:
        found, err = apply_proxy_callback(
            session,
            dispatch_id=dispatch_id,
            success=success,
            attempts=attempts,
            status_code=status_code,
            error_detail=error_detail,
        )
        if not found:
            return jsonify({"error": err}), 404
        return jsonify({"ok": True, "dispatch_id": dispatch_id, "status": "success" if success else "failed"})
    finally:
        session.close()


@app.get("/webhook/<workflow_id>")
def cron_org_callback(workflow_id: str):
    """Called by cron-job.org (GET). Direct noney POST or Apps Script proxy."""
    session = get_session()
    started = time.perf_counter()
    use_proxy = proxy_enabled()
    log = TriggerLog(
        status="failed",
        delivery_mode="proxy" if use_proxy else "direct",
        workflow_id=workflow_id,
        workflow_name="",
        owner_email="",
        attempts=0,
        client_ip=_client_ip(),
    )
    try:
        row = session.get(WorkflowSchedule, workflow_id)
        if row is None or not row.enabled:
            log.error_detail = "Schedule not found or disabled"
            session.add(log)
            session.commit()
            return jsonify({"error": "Schedule not found"}), 404

        log.workflow_name = row.workflow_name
        log.owner_email = row.owner_email

        if use_proxy:
            script_url = proxy_apps_script_url()
            if not script_url:
                log.error_detail = "Proxy enabled but Apps Script URL is not configured"
                log.status = "failed"
                log.duration_ms = int((time.perf_counter() - started) * 1000)
                session.add(log)
                session.commit()
                if row.owner_email:
                    send_failure_email(
                        to_email=row.owner_email,
                        workflow_id=row.workflow_id,
                        workflow_name=row.workflow_name,
                        error_detail=log.error_detail,
                        status_code=None,
                        attempts=0,
                    )
                return jsonify({"error": log.error_detail}), 503

            log.status = "pending"
            session.add(log)
            session.flush()

            accepted, err = dispatch_to_apps_script(
                dispatch_id=log.id,
                workflow_id=row.workflow_id,
                workflow_name=row.workflow_name,
                owner_email=row.owner_email,
                noney_trigger_url=row.noney_trigger_url,
                noney_trigger_secret=row.noney_trigger_secret,
                apps_script_url=script_url,
            )
            log.duration_ms = int((time.perf_counter() - started) * 1000)
            if accepted:
                log.status = "dispatched"
                session.commit()
                return jsonify(
                    {
                        "ok": True,
                        "workflow_id": workflow_id,
                        "mode": "proxy",
                        "dispatch_id": log.id,
                    }
                ), 200

            log.status = "failed"
            log.error_detail = err or "Apps Script dispatch failed"
            session.commit()
            if row.owner_email:
                send_failure_email(
                    to_email=row.owner_email,
                    workflow_id=row.workflow_id,
                    workflow_name=row.workflow_name,
                    error_detail=log.error_detail,
                    status_code=None,
                    attempts=0,
                )
            return jsonify({"error": log.error_detail}), 502

        ok, attempts, status_code, err = trigger_noney_with_retries(
            noney_trigger_url=row.noney_trigger_url,
            noney_trigger_secret=row.noney_trigger_secret,
            workflow_id=row.workflow_id,
            workflow_name=row.workflow_name,
            owner_email=row.owner_email,
        )
        log.attempts = attempts
        log.noney_status_code = status_code
        log.error_detail = err
        log.status = "success" if ok else "failed"
        log.duration_ms = int((time.perf_counter() - started) * 1000)
        session.add(log)
        session.commit()

        if ok:
            return jsonify({"ok": True, "workflow_id": workflow_id, "mode": "direct"}), 200
        return jsonify({"error": err or "Trigger failed", "attempts": attempts}), 502
    except Exception as exc:
        session.rollback()
        log.error_detail = str(exc)
        log.duration_ms = int((time.perf_counter() - started) * 1000)
        session.add(log)
        session.commit()
        return jsonify({"error": "Internal error"}), 500
    finally:
        session.close()


if __name__ == "__main__":
    app.run()
