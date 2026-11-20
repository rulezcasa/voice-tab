"""The ledger: the only code that writes expenses and shares."""
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from zoneinfo import ZoneInfo

from src import config
from src.core import live
from src.core.expenses import settle
from src.core.expenses.categories import ALL_CATEGORIES, SETTLEMENT
from src.core.expenses.splits import Share, SplitError, build_shares, settlement_shares, to_money
from src.db.s2_client import cursor, to_vector, transaction
from src.model.embeddings import embed, expense_embed_text
from src.utils.query import rows_as_dicts


class LedgerError(ValueError):
    """Bad input (unknown person, category, expense). The message is safe to show the user."""


# ---------- helpers ----------

def _money(v) -> str:
    return f"{v:.2f}"


def today() -> date:
    return datetime.now(ZoneInfo(config.TZ)).date()


@cache
def me_id() -> int:
    with cursor() as cur:
        cur.execute("SELECT id FROM people WHERE is_me LIMIT 1")
        row = cur.fetchone()
    if not row:
        raise LedgerError("no account owner (people.is_me) in the database")
    return row[0]


def _check_people(cur, ids: set[int]) -> None:
    if not ids:
        return
    cur.execute(f"SELECT id FROM people WHERE id IN ({','.join(['%s'] * len(ids))})", list(ids))
    missing = ids - {r[0] for r in cur.fetchall()}
    if missing:
        raise LedgerError(f"unknown person id(s): {sorted(missing)}")


def _check_group(cur, group_id: int | None) -> None:
    if group_id is None:
        return
    cur.execute("SELECT 1 FROM groups_ WHERE id = %s", (group_id,))
    if not cur.fetchone():
        raise LedgerError(f"unknown group id: {group_id}")


def _check_category(category: str, allow_settlement: bool = False) -> str:
    c = (category or "other").strip().lower()
    if c not in ALL_CATEGORIES or (c == SETTLEMENT and not allow_settlement):
        raise LedgerError(f"unknown category: {category}")
    return c


def _embedding(description: str | None, category: str, merchant: str | None) -> str | None:
    """Vector literal for the expense, or None if SIE failed (the row is still saved)."""
    try:
        return to_vector(embed([expense_embed_text(description or "", category, merchant)])[0])
    except Exception:
        return None


def _insert_shares(cur, expense_id: int, shares: list[Share]) -> None:
    cur.executemany(
        "INSERT INTO expense_shares (expense_id, person_id, paid, owed) VALUES (%s, %s, %s, %s)",
        [(expense_id, s.person_id, s.paid, s.owed) for s in shares],
    )


def _shares(amount, payer_id, participant_ids, custom) -> list[Share]:
    try:
        return build_shares(amount, payer_id, participant_ids, custom)
    except SplitError as e:
        raise LedgerError(str(e)) from e


# ---------- reads ----------

def balances() -> list[dict]:
    """Every person (me first) with their net: positive = is owed, negative = owes."""
    with cursor() as cur:
        cur.execute(
            "SELECT p.id, p.name, p.is_me, COALESCE(b.net, 0) AS net"
            " FROM people p LEFT JOIN balances b ON b.person_id = p.id"
            " ORDER BY p.is_me DESC, p.name"
        )
        rows = rows_as_dicts(cur)
    for r in rows:
        r["is_me"] = bool(r["is_me"])
        r["net"] = _money(r["net"])
    return rows


def balances_for(person_ids: list[int]) -> dict[int, str]:
    ids = list(dict.fromkeys(person_ids))
    if not ids:
        return {}
    with cursor() as cur:
        cur.execute(
            "SELECT person_id, COALESCE(SUM(paid - owed), 0) FROM expense_shares"
            f" WHERE person_id IN ({','.join(['%s'] * len(ids))}) GROUP BY person_id",
            ids,
        )
        got = {pid: _money(net) for pid, net in cur.fetchall()}
    return {pid: got.get(pid, "0.00") for pid in ids}


_EXPENSE_COLS = (
    "SELECT e.id, e.created_at, e.spent_on, e.amount, e.currency, e.description,"
    " e.merchant, e.category, e.group_id, e.meetup_id, e.status, e.is_demo, g.name AS group_name"
    " FROM expenses e LEFT JOIN groups_ g ON g.id = e.group_id"
)


def _with_shares(cur, expenses: list[dict]) -> list[dict]:
    if not expenses:
        return []
    ids = [e["id"] for e in expenses]
    cur.execute(
        "SELECT s.expense_id, s.person_id, p.name, p.is_me, s.paid, s.owed FROM expense_shares s"
        " JOIN people p ON p.id = s.person_id"
        f" WHERE s.expense_id IN ({','.join(['%s'] * len(ids))})"
        " ORDER BY s.paid DESC, p.is_me DESC, p.name",
        ids,
    )
    by_expense: dict[int, list] = {}
    for s in rows_as_dicts(cur):
        by_expense.setdefault(s["expense_id"], []).append({
            "person_id": s["person_id"], "name": s["name"], "is_me": bool(s["is_me"]),
            "paid": _money(s["paid"]), "owed": _money(s["owed"]),
        })
    for e in expenses:
        e["amount"] = _money(e["amount"])
        e["is_demo"] = bool(e["is_demo"])
        e["shares"] = by_expense.get(e["id"], [])
    return expenses


def recent(limit: int = 20) -> list[dict]:
    """Latest expenses (newest first), each with group name and per-person shares."""
    with cursor() as cur:
        cur.execute(_EXPENSE_COLS + " ORDER BY e.spent_on DESC, e.created_at DESC LIMIT %s", (limit,))
        return _with_shares(cur, rows_as_dicts(cur))


def get_expense(expense_id: int) -> dict:
    with cursor() as cur:
        cur.execute(_EXPENSE_COLS + " WHERE e.id = %s", (expense_id,))
        rows = _with_shares(cur, rows_as_dicts(cur))
    if not rows:
        raise LedgerError(f"no expense with id {expense_id}")
    return rows[0]


def last_expense() -> dict | None:
    """The latest non-demo, non-settlement expense: what "actually it was 45" refers to."""
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM expenses WHERE category <> %s AND NOT is_demo AND status = 'logged'"
            " ORDER BY created_at DESC LIMIT 1",
            (SETTLEMENT,),
        )
        row = cur.fetchone()
    return get_expense(row[0]) if row else None


# ---------- writes ----------

def create_expense(
    *, amount, description: str, category: str = "other",
    payer_id: int | None = None, participant_ids: list[int] | None = None,
    custom: dict[int, object] | None = None, spent_on: date | None = None,
    merchant: str | None = None, currency: str | None = None, group_id: int | None = None,
    meetup_id: int | None = None,
) -> dict:
    """Save a purchase. Defaults: I paid, it's just mine, dated today. meetup_id links it to a confirmed meetup."""
    me = me_id()
    payer = payer_id or me
    participants = participant_ids or [me]
    category = _check_category(category)
    shares = _shares(amount, payer, participants, custom)
    total = to_money(amount)
    spent_on = spent_on or today()
    vec = _embedding(description, category, merchant)

    with transaction() as cur:
        _check_people(cur, {sh.person_id for sh in shares})
        _check_group(cur, group_id)
        cur.execute(
            "INSERT INTO expenses (spent_on, amount, currency, description, merchant,"
            " category, group_id, meetup_id, status, embedding)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'logged', %s)",
            (spent_on, total, (currency or config.DEFAULT_CURRENCY).upper()[:3],
             description, merchant, category, group_id, meetup_id, vec),
        )
        expense_id = cur.lastrowid
        _insert_shares(cur, expense_id, shares)
    return _result(expense_id, "created")


def update_expense(
    expense_id: int, *, amount=None, description: str | None = None, merchant: str | None = None,
    category: str | None = None, spent_on: date | None = None, group_id: int | None = None,
    payer_id: int | None = None, participant_ids: list[int] | None = None,
    custom: dict[int, object] | None = None,
) -> dict:
    """Change an expense. Fields left as None keep their value."""
    old = get_expense(expense_id)
    if old["category"] == SETTLEMENT:
        raise LedgerError("settlements can't be edited, delete and record it again")

    fields: dict = {}
    if description is not None:
        fields["description"] = description
    if merchant is not None:
        fields["merchant"] = merchant
    if category is not None:
        fields["category"] = _check_category(category)
    if spent_on is not None:
        fields["spent_on"] = spent_on
    if group_id is not None:
        fields["group_id"] = group_id
    if amount is not None:
        fields["amount"] = to_money(amount)

    shares = None
    if amount is not None or payer_id or participant_ids or custom:
        old_payer = next((s["person_id"] for s in old["shares"] if Decimal(s["paid"]) > 0), me_id())
        old_people = [s["person_id"] for s in old["shares"] if Decimal(s["owed"]) > 0]
        shares = _shares(fields.get("amount", old["amount"]), payer_id or old_payer,
                         participant_ids or old_people, custom)

    if any(k in fields for k in ("description", "merchant", "category")):
        fields["embedding"] = _embedding(
            fields.get("description", old["description"]),
            fields.get("category", old["category"]),
            fields.get("merchant", old["merchant"]),
        )
    if not fields and shares is None:
        return _result(expense_id, publish=False)

    with transaction() as cur:
        if shares:
            _check_people(cur, {sh.person_id for sh in shares})
        _check_group(cur, fields.get("group_id"))
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            cur.execute(f"UPDATE expenses SET {sets} WHERE id = %s", (*fields.values(), expense_id))
        if shares:
            cur.execute("DELETE FROM expense_shares WHERE expense_id = %s", (expense_id,))
            _insert_shares(cur, expense_id, shares)
    return _result(expense_id, "updated")


def record_settlement(
    *, amount, from_id: int, to_id: int | None = None, group_id: int | None = None,
    description: str | None = None, spent_on: date | None = None,
) -> dict:
    """from_id paid to_id (default: me) back. Stored as an expense with category 'settlement'."""
    to = to_id or me_id()
    try:
        shares = settlement_shares(amount, from_id, to)
    except SplitError as e:
        raise LedgerError(str(e)) from e
    total = to_money(amount)
    spent_on = spent_on or today()

    with cursor() as cur:
        _check_people(cur, {from_id, to})
        _check_group(cur, group_id)
        cur.execute("SELECT id, name, is_me FROM people WHERE id IN (%s, %s)", (from_id, to))
        names = {pid: ("me" if is_me else name) for pid, name, is_me in cur.fetchall()}
    if description is None:
        description = f"{names[from_id]} paid {names[to]} back".replace("me paid", "I paid")
    vec = _embedding(description, SETTLEMENT, None)

    with transaction() as cur:
        cur.execute(
            "INSERT INTO expenses (spent_on, amount, currency, description,"
            " category, group_id, status, embedding)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'logged', %s)",
            (spent_on, total, config.DEFAULT_CURRENCY, description, SETTLEMENT, group_id, vec),
        )
        expense_id = cur.lastrowid
        _insert_shares(cur, expense_id, shares)
    return _result(expense_id, "settled")


def delete_expense(expense_id: int) -> dict:
    """Remove an expense and its shares. Returns what was deleted and the new balances."""
    old = get_expense(expense_id)
    with transaction() as cur:
        cur.execute("DELETE FROM expense_shares WHERE expense_id = %s", (expense_id,))
        cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
    people = [s["person_id"] for s in old["shares"]]
    live.publish({"type": "ledger", "action": "deleted", "expense": old, "people": balances()})
    return {"deleted": old, "balances": balances_for(people)}


def _result(expense_id: int, action: str = "", publish: bool = True) -> dict:
    e = get_expense(expense_id)
    if publish:
        live.publish({"type": "ledger", "action": action, "expense": e, "people": balances()})
    return {"expense": e, "balances": balances_for([s["person_id"] for s in e["shares"]])}


# ---------- who owes whom ----------

def owes_summary(person_id: int | None = None) -> dict:
    """One person's balance, who they owe and who owes them (netted per pair), plus the
    fewest transfers that would settle the whole ledger. Default person: me."""
    pid = person_id or me_id()
    with cursor() as cur:
        cur.execute("SELECT expense_id, person_id, paid, owed FROM expense_shares")
        shares = [{"expense_id": e, "person_id": p, "paid": pd, "owed": o} for e, p, pd, o in cur.fetchall()]
    people = balances()
    names = {p["id"]: p["name"] for p in people}
    if pid not in names:
        raise LedgerError(f"unknown person id: {pid}")
    pairs = settle.pairwise(shares)
    nets = {p["id"]: Decimal(p["net"]) for p in people}
    return {
        "person_id": pid,
        "name": names[pid],
        "net": _money(nets[pid]),
        "owes": [{"person_id": d["to"], "name": names.get(d["to"]), "amount": _money(d["amount"])}
                 for d in pairs if d["from"] == pid],
        "owed_by": [{"person_id": d["from"], "name": names.get(d["from"]), "amount": _money(d["amount"])}
                    for d in pairs if d["to"] == pid],
        "suggested_transfers": [
            {"from_id": t["from"], "from": names.get(t["from"]), "to_id": t["to"], "to": names.get(t["to"]),
             "amount": _money(t["amount"])} for t in settle.suggest_transfers(nets)],
    }
