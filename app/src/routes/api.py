"""HTTP routes, all under /api. main.py mounts `router`; endpoints live here, logic lives in src/core.

The webapp (../webapp) is served at / by main.py.
"""
import time

from fastapi import APIRouter

from src.core import audit
from src.core.expenses import ledger
from src.db.s2_client import cursor
from src.model.sl_client import MODELS, sie

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    """Checks SingleStore (expense count) and SIE (model metadata lookup, no inference cost)."""
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


@router.get("/audit")
def audit_feed(after: int = 0, limit: int = 100, tail: int | None = None):
    """Live trail for the UI: poll with ?after=<last id seen>, or ?tail=N for the latest N."""
    if tail is not None:
        return audit.events_tail(min(tail, 500))
    return audit.events_since(after, min(limit, 500))


@router.get("/audit/utterance/{utt_id}")
def audit_utterance(utt_id: int):
    return audit.events_for_utterance(utt_id)


@router.get("/audit/expense/{expense_id}")
def audit_expense(expense_id: int):
    return audit.events_for_expense(expense_id)


@router.get("/balances")
def get_balances():
    """Everyone's net balance; positive = is owed, negative = owes. Money as strings."""
    return ledger.balances()


@router.get("/expenses")
def get_expenses(limit: int = 20):
    """Recent expenses, newest first, with shares."""
    return ledger.recent(min(limit, 100))
