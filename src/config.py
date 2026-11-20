import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SS = {
    "host": os.environ["SS_HOST"],
    "port": int(os.getenv("SS_PORT") or 3306),
    "user": os.environ["SS_USER"],
    "password": os.environ["SS_PASSWORD"],
    "database": os.getenv("SS_DATABASE") or "tab",
}
SL_BASE_URL = os.environ["SL_BASE_URL"]
SL_API_KEY = os.environ["SL_API_KEY"]
TZ = os.getenv("TZ", "America/Los_Angeles")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")
