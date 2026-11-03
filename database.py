from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

import config
from models import Base

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _migrate_schema() -> None:
    inspector = inspect(engine)
    if inspector.has_table("trigger_logs"):
        columns = {c["name"] for c in inspector.get_columns("trigger_logs")}
        if "delivery_mode" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE trigger_logs ADD COLUMN delivery_mode VARCHAR(16) "
                        "NOT NULL DEFAULT 'direct'"
                    )
                )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    from settings_store import seed_settings

    seed_settings()


def get_session() -> Session:
    return SessionLocal()
