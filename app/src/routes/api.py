"""HTTP routes, all under /api. main.py mounts `router`; endpoints live here, logic lives in src/core."""
import time
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents import hangout_llm
from src.core import hangout, places
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


# ---------- meetups: coordinator + personal agents negotiate in rounds ----------

class NegotiateIn(BaseModel):
    group_id: int
    start: date
    end: date
    activity: str | None = None
    min_hours: float = 2


@router.post("/meetups/negotiate")
def negotiate_meetup(body: NegotiateIn):
    """Run a multi-agent negotiation. Returns the public transcript and the outcome, never the private audit."""
    from src.agents import negotiator
    from src.core.meetups import repo
    if body.end < body.start:
        raise HTTPException(status_code=422, detail="end is before start")
    try:
        group = repo.group(body.group_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    result = negotiator.negotiate(group, body.start, body.end, activity=body.activity, min_hours=body.min_hours)
    return {"id": negotiator.remember(result), **negotiator.public(result)}


# ---------- live negotiation: agents draft, each person approves or changes on their own device ----------

class LiveIn(NegotiateIn):
    start: date | None = None       # optional when `message` is given: worked out from it
    end: date | None = None
    message: str | None = None      # a casual ask: "guys hang out tomm?" -> when + what, and the chat's first line
    reply_window_s: int = 180
    bots: bool = False              # everyone except you is a seeded bot (like playing chess against the computer)
    seed: int | None = None         # only to replay a game; normally empty = a new random game every time
    play_as: int | None = None      # with bots: the person you play (default: you); everyone else is a bot
    hands_off: bool = False         # your own agent answers for you too: after your message you just watch


class RespondIn(BaseModel):
    action: str                     # approve | accept | decline | leave
    message: str | None = None
    hint: str | None = None


def _live_call(fn, *args, **kwargs):
    from src.agents.live import LiveError
    try:
        return fn(*args, **kwargs)
    except LiveError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/meetups/live")
def start_live(body: LiveIn):
    """Start a live plan: round 1's proposal goes out and every person's agent drafts a reply for them to check."""
    from src.agents import ask, live, negotiator
    from src.core.meetups import repo
    chat = negotiator.model_chat()
    understood = None
    if body.message and body.message.strip():
        understood = ask.understand(body.message.strip(), ledger.today(), chat)
        body.start, body.end = understood["start"], understood["end"]
        body.activity = body.activity or understood["activity"]
    if body.start is None or body.end is None:
        raise HTTPException(status_code=422, detail="say when (a message like 'hang out tomorrow?') or give start and end")
    if body.end < body.start:
        raise HTTPException(status_code=422, detail="end is before start")
    if not 20 <= body.reply_window_s <= 3600:
        raise HTTPException(status_code=422, detail="reply window must be 20 seconds to an hour")
    try:
        group = repo.group(body.group_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    me = next((m["id"] for m in group["members"] if m.get("is_me")), None)
    player = body.play_as if body.play_as is not None else me
    if body.bots and player not in {m["id"] for m in group["members"]}:
        raise HTTPException(status_code=422, detail="you can only play as someone in this group")
    s = live.start(group, body.start, body.end, activity=body.activity, min_hours=body.min_hours,
                   reply_window_s=body.reply_window_s, bots=body.bots, seed=body.seed,
                   play_as=player if body.bots else None, organiser_id=me,
                   opening=body.message.strip() if body.message else None, hands_off=body.hands_off, chat=chat)
    out = s.public()
    if understood:
        out["understood"] = {k: str(v) if k in ("start", "end") else v for k, v in understood.items()}
    if body.bots and player is not None:
        from src.core.people import links
        out["player_token"] = links.token(player)   # a game: you answer that person's turns in the panel
    return out


@router.get("/meetups/live/{sid}")
def get_live(sid: int):
    """The conversation so far and who it's waiting on (no drafts, no private reasons)."""
    from src.agents import live
    return _live_call(lambda: live.get(sid).public())


@router.post("/meetups/live/{sid}/stop-waiting")
def stop_waiting(sid: int):
    """Stop waiting: each person who hasn't answered is answered by their agent's draft."""
    from src.agents import live
    s = _live_call(live.get, sid)
    _live_call(s.close_window)
    return s.public()


# ---------- private agent pages: each person, on their own device, via their own secret link ----------

def _me(token: str) -> int:
    from src.core.people import links
    pid = links.person_from(token)
    if pid is None:
        raise HTTPException(status_code=404, detail="This agent link isn't valid. Ask for a new one.")
    return pid


def _private_call(fn, *args):
    from src.core.people.private import PrivateError
    try:
        return fn(*args)
    except PrivateError as e:
        raise HTTPException(status_code=422, detail=str(e))


class ProfileIn(BaseModel):
    home: list[float] | None = None          # [lng, lat]
    budget: str | None = None
    radius_mi: float | None = None
    max_travel_min: int | None = None
    travel_mode: str | None = None
    interests: list[str] | None = None


class BusyIn(BaseModel):
    starts_at: str
    ends_at: str
    label: str | None = None


@router.get("/me/{token}")
def my_agent(token: str):
    """Your own private details (only you can open this link)."""
    from src.core.people import private
    return _private_call(private.get, _me(token))


@router.put("/me/{token}/profile")
def update_my_profile(token: str, body: ProfileIn):
    from src.core.people import private
    return _private_call(private.update, _me(token), body.model_dump(exclude_none=True))


@router.post("/me/{token}/busy")
def add_my_busy(token: str, body: BusyIn):
    from src.core.people import private
    return _private_call(private.add_busy, _me(token), body.starts_at, body.ends_at, body.label)


@router.delete("/me/{token}/busy/{busy_id}")
def remove_my_busy(token: str, busy_id: int):
    from src.core.people import private
    return _private_call(private.remove_busy, _me(token), busy_id)


@router.get("/me/{token}/live")
def my_live_plans(token: str):
    """Live plans you're part of, with your agent's draft and private reason when it's your turn."""
    from src.agents import live
    return live.for_person(_me(token))


@router.post("/me/{token}/live/{sid}/respond")
def respond_live(token: str, sid: int, body: RespondIn):
    """Send your answer for this round: your agent's draft as is, your own accept/decline, or that you can't come."""
    from src.agents import live
    pid = _me(token)
    s = _live_call(live.get, sid)
    _live_call(s.respond, pid, body.action, body.message, body.hint)
    return s.for_person(pid)


@router.get("/me/{token}/agent")
def my_agent_activity(token: str):
    """What your agent said for you in recent negotiations, and why (your private reasons, only for you)."""
    from src.agents import negotiator
    return negotiator.for_person(_me(token))


# ---------- hangout: real places near the group (the map's Hangout panel) ----------

@router.post("/hangout")
def find_hangout(body: hangout.HangoutRequest):
    """Real places (OpenStreetMap) everyone can reach in time and afford. Only the search circle leaves the server."""
    try:
        return hangout.recommend(body, places.nearby, llm=hangout_llm)
    except hangout.HangoutError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except places.PlacesError as e:
        raise HTTPException(status_code=502, detail=str(e))
