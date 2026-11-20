"""Writing the audit trail: utterances and one audit_events row per pipeline step."""
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from src.db.s2_client import cursor
from src.utils.serialize import to_json

STEPS = {
    "transcribe", "route", "extract", "classify", "resolve", "clarify",
    "math", "gate", "store", "balances", "query", "edit", "settle",
}


def new_utterance(session_id: str | None, transcript: str, intent: str | None = None) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO utterances (session_id, transcript, intent) VALUES (%s, %s, %s)",
            (session_id, transcript, intent),
        )
        return cur.lastrowid


def set_intent(utt_id: int, intent: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE utterances SET intent = %s WHERE id = %s", (intent, utt_id))


def link_expense(utt_id: int, expense_id: int) -> None:
    """Attach an expense to every audit row of this utterance that has none yet."""
    with cursor() as cur:
        cur.execute(
            "UPDATE audit_events SET expense_id = %s WHERE utterance_id = %s AND expense_id IS NULL",
            (expense_id, utt_id),
        )


def record(
    utt_id: int, step: str, *, model: str | None = None, input: Any = None,
    output: Any = None, confidence: float | None = None, latency_ms: int = 0,
    expense_id: int | None = None,
) -> int:
    """Write one audit row directly. Prefer step(), which times the block for you."""
    assert step in STEPS, f"unknown audit step: {step}"
    with cursor() as cur:
        cur.execute(
            "INSERT INTO audit_events (utterance_id, expense_id, step, model, input, output, confidence, latency_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (utt_id, expense_id, step, model, to_json(input), to_json(output),
             None if confidence is None else float(confidence), latency_ms),
        )
        return cur.lastrowid


@dataclass
class Step:
    output: Any = None
    confidence: float | None = None
    expense_id: int | None = None
    model: str | None = None


@contextmanager
def step(utt_id: int, name: str, *, model: str | None = None, input: Any = None,
         expense_id: int | None = None):
    """Time the block and write its audit row on exit, also when it raises."""
    s = Step(expense_id=expense_id, model=model)
    t = time.perf_counter()
    try:
        yield s
    except Exception as e:
        s.output = {"error": type(e).__name__, "message": str(e)[:500]}
        raise
    finally:
        record(
            utt_id, name, model=s.model, input=input, output=s.output,
            confidence=s.confidence, latency_ms=int((time.perf_counter() - t) * 1000),
            expense_id=s.expense_id,
        )
