"""Reading the ledger: balances per person and recent expenses with their shares.

Money is returned as strings ("13.34") so cents stay exact all the way to the UI.
"""
from src.db.s2_client import cursor
from src.utils.sql import rows_as_dicts


def _money(v) -> str:
    return f"{v:.2f}"


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


def recent(limit: int = 20) -> list[dict]:
    """Latest expenses (newest first), each with group name and per-person shares."""
    with cursor() as cur:
        cur.execute(
            "SELECT e.id, e.created_at, e.spent_on, e.amount, e.currency, e.description, e.merchant,"
            " e.category, e.status, e.is_demo, g.name AS group_name"
            " FROM expenses e LEFT JOIN groups_ g ON g.id = e.group_id"
            " ORDER BY e.spent_on DESC, e.created_at DESC LIMIT %s",
            (limit,),
        )
        expenses = rows_as_dicts(cur)
        if not expenses:
            return []
        ids = [e["id"] for e in expenses]
        cur.execute(
            "SELECT s.expense_id, p.name, p.is_me, s.paid, s.owed FROM expense_shares s"
            " JOIN people p ON p.id = s.person_id"
            f" WHERE s.expense_id IN ({','.join(['%s'] * len(ids))})"
            " ORDER BY p.is_me DESC, p.name",
            ids,
        )
        shares = rows_as_dicts(cur)

    by_expense: dict[int, list] = {}
    for s in shares:
        by_expense.setdefault(s["expense_id"], []).append(
            {"name": s["name"], "is_me": bool(s["is_me"]), "paid": _money(s["paid"]), "owed": _money(s["owed"])}
        )
    for e in expenses:
        e["amount"] = _money(e["amount"])
        e["is_demo"] = bool(e["is_demo"])
        e["shares"] = by_expense.get(e["id"], [])
    return expenses
