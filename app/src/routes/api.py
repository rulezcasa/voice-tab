"""HTTP routes, all under /api. main.py mounts `router`; endpoints live here, logic lives in src/core."""
import time
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.expenses import ledger
from src.core.expenses.ledger import LedgerError
from src.db.s2_client import cursor
from src.utils import directory
from src.utils.directory import DirectoryError
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


@router.get("/balances")
def get_balances():
    """Everyone's net balance; positive = is owed, negative = owes. Money as strings."""
    return ledger.balances()


@router.get("/balances/groups")
def get_group_balances():
    """Balances per group, plus a "Non-group" bucket for expenses outside any group."""
    return ledger.group_balances()


class GroupIn(BaseModel):
    name: str
    member_ids: list[int] = []                  # I'm added automatically
    aliases: list[str] | None = None


@router.post("/groups")
def create_group(body: GroupIn):
    try:
        return directory.create_group(body.name, body.member_ids, body.aliases)
    except DirectoryError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/expenses")
def get_expenses(limit: int = 20):
    """Recent expenses, newest first, with shares."""
    return ledger.recent(min(limit, 100))


# ---------- direct ledger writes (structured input; the agent uses the same ledger via src/mcp/server.py) ----------

class ExpenseIn(BaseModel):
    amount: Decimal
    description: str
    category: str = "other"
    merchant: str | None = None
    spent_on: date | None = None
    payer_id: int | None = None                 # default: me
    participant_ids: list[int] | None = None    # default: just me (personal)
    custom: dict[int, Decimal] | None = None    # person_id -> exact owed
    group_id: int | None = None


class ExpensePatch(BaseModel):
    amount: Decimal | None = None
    description: str | None = None
    category: str | None = None
    merchant: str | None = None
    spent_on: date | None = None
    payer_id: int | None = None
    participant_ids: list[int] | None = None
    custom: dict[int, Decimal] | None = None
    group_id: int | None = None


class SettlementIn(BaseModel):
    amount: Decimal
    from_id: int
    to_id: int | None = None                    # default: me
    group_id: int | None = None
    spent_on: date | None = None


def _ledger_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LedgerError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/expenses/{expense_id}")
def get_expense(expense_id: int):
    return _ledger_call(ledger.get_expense, expense_id)


@router.post("/expenses")
def create_expense(body: ExpenseIn):
    return _ledger_call(ledger.create_expense, **body.model_dump())


@router.patch("/expenses/{expense_id}")
def update_expense(expense_id: int, body: ExpensePatch):
    return _ledger_call(ledger.update_expense, expense_id, **body.model_dump(exclude_unset=True))


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    return _ledger_call(ledger.delete_expense, expense_id)


@router.post("/settlements")
def record_settlement(body: SettlementIn):
    return _ledger_call(ledger.record_settlement, **body.model_dump())
