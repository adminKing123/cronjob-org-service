import json
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlencode

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from sqlalchemy import func, select

from database import get_session
from models import TriggerLog, WorkflowSchedule

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 25
SORT_OPTIONS = {
    "created_desc": ("Newest first", TriggerLog.created_at.desc()),
    "created_asc": ("Oldest first", TriggerLog.created_at.asc()),
}


def _admin_configured() -> bool:
    from config import ADMIN_PASSWORD, FLASK_SECRET_KEY

    return bool(ADMIN_PASSWORD and FLASK_SECRET_KEY)


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _admin_configured():
            abort(404)
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _log_filters_from_request() -> dict:
    sort = request.args.get("sort", "created_desc")
    if sort not in SORT_OPTIONS:
        sort = "created_desc"
    status = request.args.get("status", "all").lower()
    if status not in ("all", "success", "failed", "pending", "dispatched"):
        status = "all"
    return {
        "status": status,
        "workflow_id": request.args.get("workflow_id", "").strip(),
        "owner_email": request.args.get("owner_email", "").strip(),
        "sort": sort,
    }


def _apply_log_filters(stmt, filters: dict):
    if filters["status"] != "all":
        stmt = stmt.where(TriggerLog.status == filters["status"])
    if filters["workflow_id"]:
        stmt = stmt.where(TriggerLog.workflow_id.ilike(f"%{filters['workflow_id']}%"))
    if filters["owner_email"]:
        stmt = stmt.where(TriggerLog.owner_email.ilike(f"%{filters['owner_email']}%"))
    return stmt


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if not _admin_configured():
        abort(404)
    error = None
    if request.method == "POST":
        from config import ADMIN_PASSWORD
        import secrets

        password = request.form.get("password", "")
        if secrets.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["admin_authenticated"] = True
            session.permanent = True
            dest = request.args.get("next") or url_for("admin.dashboard")
            if not dest.startswith("/admin"):
                dest = url_for("admin.dashboard")
            return redirect(dest)
        error = "Invalid password."
    return render_template("admin_login.html", error=error)


@admin_bp.post("/logout")
@require_admin
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.get("/")
@require_admin
def dashboard():
    filters = _log_filters_from_request()
    page = max(1, request.args.get("page", 1, type=int))
    db = get_session()
    try:
        count_stmt = _apply_log_filters(select(func.count(TriggerLog.id)), filters)
        list_stmt = _apply_log_filters(select(TriggerLog), filters)
        total = db.scalar(count_stmt) or 0
        success_total = db.scalar(
            select(func.count(TriggerLog.id)).where(TriggerLog.status == "success")
        )
        failed_total = db.scalar(
            select(func.count(TriggerLog.id)).where(TriggerLog.status == "failed")
        )
        active_schedules = db.scalar(select(func.count(WorkflowSchedule.workflow_id))) or 0
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(page, pages)
        _, order = SORT_OPTIONS[filters["sort"]]
        logs = db.scalars(
            list_stmt.order_by(order).offset((page - 1) * PER_PAGE).limit(PER_PAGE)
        ).all()
        rows = [_log_row(log) for log in logs]
    finally:
        db.close()

    return render_template(
        "admin_dashboard.html",
        logs=rows,
        page=page,
        pages=pages,
        total=total,
        filters=filters,
        status=filters["status"],
        sort=filters["sort"],
        sort_options=SORT_OPTIONS,
        success_total=success_total or 0,
        failed_total=failed_total or 0,
        active_schedules=active_schedules,
        per_page=PER_PAGE,
    )


@admin_bp.get("/logs/<int:log_id>")
@require_admin
def log_detail(log_id: int):
    db = get_session()
    try:
        log = db.get(TriggerLog, log_id)
        if not log:
            abort(404)
        row = _log_row(log, include_detail=True)
    finally:
        db.close()
    return render_template("admin_log_detail.html", log=row)


@admin_bp.get("/schedules")
@require_admin
def schedules_list():
    db = get_session()
    try:
        rows = db.scalars(
            select(WorkflowSchedule).order_by(WorkflowSchedule.updated_at.desc())
        ).all()
        items = [
            {
                "workflow_id": r.workflow_id,
                "workflow_name": r.workflow_name,
                "owner_email": r.owner_email,
                "cron_expression": r.cron_expression,
                "timezone": r.timezone,
                "cron_org_job_id": r.cron_org_job_id,
                "public_webhook_url": r.public_webhook_url,
                "enabled": r.enabled,
            }
            for r in rows
        ]
    finally:
        db.close()
    return render_template("admin_schedules.html", schedules=items)


@admin_bp.route("/settings", methods=["GET", "POST"])
@require_admin
def settings_page():
    import settings_store

    errors: list[str] = []
    saved = False
    if request.method == "POST":
        errors = settings_store.save_admin_form(request.form)
        saved = not errors
    values = settings_store.admin_form_values()
    callback_url = None
    try:
        from proxy_dispatch import build_callback_url

        callback_url = build_callback_url()
    except Exception:
        pass
    return render_template(
        "admin_settings.html",
        values=values,
        errors=errors,
        saved=saved,
        callback_url=callback_url,
    )


@admin_bp.get("/test")
@require_admin
def test_page():
    import config

    return render_template(
        "admin_test.html",
        api_key=config.SERVICE_API_KEY,
        api_key_masked=_mask_secret(config.SERVICE_API_KEY),
        api_url="/api/schedules/upsert",
    )


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    visible = 4
    middle = max(4, len(value) - visible * 2)
    return f"{value[:visible]}{'•' * middle}{value[-visible:]}"


def _log_row(log: TriggerLog, include_detail: bool = False) -> dict:
    created = log.created_at
    if created.tzinfo is None:
        created_display = created.isoformat(sep=" ", timespec="seconds")
    else:
        created_display = created.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    row = {
        "id": log.id,
        "created_at": created_display,
        "status": log.status,
        "delivery_mode": getattr(log, "delivery_mode", "direct") or "direct",
        "workflow_id": log.workflow_id,
        "workflow_name": log.workflow_name,
        "owner_email": log.owner_email,
        "attempts": log.attempts,
        "noney_status_code": log.noney_status_code,
        "error_detail": log.error_detail,
        "client_ip": log.client_ip,
        "duration_ms": log.duration_ms,
    }
    if include_detail:
        row["error_detail"] = log.error_detail
    return row
