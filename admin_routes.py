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
    "duration_desc": ("Duration (high → low)", TriggerLog.duration_ms.desc().nulls_last()),
    "duration_asc": ("Duration (low → high)", TriggerLog.duration_ms.asc().nulls_last()),
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


def build_logs_query_string(filters: dict, *, page: int | None = None, sort: str | None = None) -> str:
    params: dict[str, str | int] = {}
    for key in ("workflow_id", "owner_email"):
        val = (filters.get(key) or "").strip()
        if val:
            params[key] = val
    status = filters.get("status", "all")
    if status and status != "all":
        params["status"] = status
    sort_val = sort if sort is not None else filters.get("sort", "created_desc")
    if sort_val and sort_val != "created_desc":
        params["sort"] = sort_val
    if page and page > 1:
        params["page"] = page
    return urlencode(params)


def _pagination_range(page: int, pages: int) -> list[int | None]:
    if pages <= 1:
        return [1]
    if pages <= 7:
        return list(range(1, pages + 1))
    nums: list[int | None] = [1]
    if page > 4:
        nums.append(None)
    start = max(2, page - 2)
    end = min(pages - 1, page + 2)
    for n in range(start, end + 1):
        if n not in nums:
            nums.append(n)
    if page < pages - 3:
        nums.append(None)
    if pages not in nums:
        nums.append(pages)
    return nums


@admin_bp.app_context_processor
def _admin_template_globals():
    return {"build_logs_query_string": build_logs_query_string}


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

    page_numbers = _pagination_range(page, pages)
    qs = build_logs_query_string(filters)

    return render_template(
        "admin_dashboard.html",
        logs=rows,
        page=page,
        pages=pages,
        page_numbers=page_numbers,
        total=total,
        filters=filters,
        query_string=qs,
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
                "expires_at": r.expires_at,
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


def _preview(text: str, length: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= length:
        return compact
    return compact[: length - 1] + "…"


def _format_duration_seconds(duration_ms: int | None) -> str | None:
    if duration_ms is None:
        return None
    seconds = duration_ms / 1000
    if seconds < 1:
        return f"{seconds:.2f} s"
    if seconds < 10:
        return f"{seconds:.2f} s"
    return f"{seconds:.1f} s"


def _short_timestamp(display: str) -> str:
    parts = display.split()
    if len(parts) >= 2 and len(parts[0]) >= 10 and "-" in parts[0]:
        return f"{parts[0][5:]} {parts[1][:5]}"
    return display


def _log_row(log: TriggerLog, include_detail: bool = False) -> dict:
    created = log.created_at
    if created.tzinfo is None:
        created_display = created.isoformat(sep=" ", timespec="seconds")
    else:
        created_display = created.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    status = log.status or "failed"
    if status not in ("success", "failed", "pending", "dispatched"):
        status = "failed"

    workflow_label = log.workflow_name or log.workflow_id or ""

    row = {
        "id": log.id,
        "created_at": created_display,
        "created_at_short": _short_timestamp(created_display),
        "status": status,
        "delivery_mode": getattr(log, "delivery_mode", "direct") or "direct",
        "workflow_id": log.workflow_id,
        "workflow_name": log.workflow_name,
        "workflow_label": workflow_label,
        "workflow_short": _preview(workflow_label, 52),
        "owner_email": log.owner_email,
        "owner_short": _preview(log.owner_email or "—", 40),
        "attempts": log.attempts,
        "noney_status_code": log.noney_status_code,
        "error_detail": log.error_detail,
        "client_ip": log.client_ip,
        "duration_ms": log.duration_ms,
        "duration_display": _format_duration_seconds(log.duration_ms),
    }
    if include_detail:
        row["error_detail"] = log.error_detail
    return row
