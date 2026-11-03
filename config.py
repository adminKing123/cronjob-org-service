import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


CRON_ORG_API_KEY = _require("CRON_ORG_API_KEY")
SERVICE_API_KEY = _require("SERVICE_API_KEY")
FLASK_SECRET_KEY = _require("FLASK_SECRET_KEY")
ADMIN_PASSWORD = _require("ADMIN_PASSWORD")

PUBLIC_HOST = _require("PUBLIC_HOST").rstrip("/")

EMAIL_SERVICE_HOST = _require("EMAIL_SERVICE_HOST").rstrip("/")
EMAIL_SERVICE_API_KEY = _require("EMAIL_SERVICE_API_KEY")

_database_file = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "sqlite3.db")))
DATABASE_PATH = str(_database_file)
DATABASE_URL = f"sqlite:///{_database_file.as_posix()}"

WEBHOOK_RETRY_ATTEMPTS = int(os.getenv("WEBHOOK_RETRY_ATTEMPTS", "5"))
WEBHOOK_RETRY_BASE_SECONDS = float(os.getenv("WEBHOOK_RETRY_BASE_SECONDS", "2.0"))
