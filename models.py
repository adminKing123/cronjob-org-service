import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkflowSchedule(Base):
    """Registered Fuse workflow schedule (one row per workflow_id)."""

    __tablename__ = "workflow_schedules"

    workflow_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    workflow_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    cron_expression: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    schedule_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    cron_org_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_webhook_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    noney_trigger_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    noney_trigger_secret: Mapped[str] = mapped_column(String(256), nullable=False)

    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def schedule_config(self) -> dict:
        try:
            return json.loads(self.schedule_config_json or "{}")
        except json.JSONDecodeError:
            return {}


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TriggerLog(Base):
    __tablename__ = "trigger_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    delivery_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")

    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    owner_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noney_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
