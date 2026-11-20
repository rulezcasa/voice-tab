import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent  # app/
load_dotenv(APP_DIR / ".env")

SS = {
    "host": os.environ["SS_HOST"],
    "port": int(os.getenv("SS_PORT") or 3306),
    "user": os.environ["SS_USER"],
    "password": os.environ["SS_PASSWORD"],
    "database": os.getenv("SS_DATABASE") or "tab",
}
# Optional SELECT-only user for the agent's SQL queries; without it, queries use SS (guarded in code).
SS_READONLY = (
    {**SS, "user": os.environ["SS_READONLY_USER"], "password": os.getenv("SS_READONLY_PASSWORD", "")}
    if os.getenv("SS_READONLY_USER") else None
)
SL_BASE_URL = os.environ["SL_BASE_URL"]
SL_API_KEY = os.environ["SL_API_KEY"]
TZ = os.getenv("TZ", "America/Los_Angeles")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")
