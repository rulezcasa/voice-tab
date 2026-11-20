"""Reading the audit trail (for the UI's live feed and per-expense trails)."""
from src.db.s2_client import cursor
from src.utils.sql import rows_as_dicts

_COLS = ("a.id, a.utterance_id, a.expense_id, a.step, a.model, a.input, a.output,"
         " a.confidence, a.latency_ms, a.created_at")
_JSON = ("input", "output")


def events_since(after_id: int = 0, limit: int = 100) -> list[dict]:
    """Newest-last feed for polling: GET /audit?after=<last id seen>."""
    with cursor() as cur:
        cur.execute(
            f"SELECT {_COLS}, u.transcript, u.intent FROM audit_events a"
            " LEFT JOIN utterances u ON u.id = a.utterance_id"
            " WHERE a.id > %s ORDER BY a.id LIMIT %s",
            (after_id, limit),
        )
        return rows_as_dicts(cur, _JSON)


def events_tail(n: int = 50) -> list[dict]:
    """The latest n events, oldest first (for loading the trail and finding the last id)."""
    with cursor() as cur:
        cur.execute(
            f"SELECT {_COLS}, u.transcript, u.intent FROM audit_events a"
            " LEFT JOIN utterances u ON u.id = a.utterance_id"
            " ORDER BY a.id DESC LIMIT %s",
            (n,),
        )
        return rows_as_dicts(cur, _JSON)[::-1]


def events_for_utterance(utt_id: int) -> list[dict]:
    with cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM audit_events a WHERE a.utterance_id = %s ORDER BY a.id", (utt_id,))
        return rows_as_dicts(cur, _JSON)


def events_for_expense(expense_id: int) -> list[dict]:
    """The full trail behind one expense: every step of the utterance(s) that produced or edited it."""
    with cursor() as cur:
        cur.execute(
            f"SELECT {_COLS} FROM audit_events a WHERE a.utterance_id IN"
            " (SELECT utterance_id FROM audit_events WHERE expense_id = %s)"
            " ORDER BY a.id",
            (expense_id,),
        )
        return rows_as_dicts(cur, _JSON)
