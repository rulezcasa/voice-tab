"""Tab: entry point.

Run:  fastapi dev main.py        (dev, auto-reload)
      fastapi run main.py        (prod)
"""
import time

from fastapi import FastAPI

from src import config  # noqa: F401  (importing validates .env at startup: missing keys fail fast)
from src.db.s2_client import cursor
from src.model.sl_client import MODELS, sie

app = FastAPI(title="Tab", description="The expense agent you just talk to")


@app.get("/health")
def health():
    """Checks SingleStore (SELECT 1) and SIE (model metadata lookup, no inference cost)."""
    out = {}

    t = time.perf_counter()
    try:
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM expenses")
            out["singlestore"] = {"ok": True, "expenses": cur.fetchone()[0]}
    except Exception as e:
        out["singlestore"] = {"ok": False, "error": type(e).__name__}
    out["singlestore"]["ms"] = int((time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    try:
        sie.get_model(MODELS["embed"])
        out["sie"] = {"ok": True}
    except Exception as e:
        out["sie"] = {"ok": False, "error": type(e).__name__}
    out["sie"]["ms"] = int((time.perf_counter() - t) * 1000)

    out["ok"] = out["singlestore"]["ok"] and out["sie"]["ok"]
    return out
