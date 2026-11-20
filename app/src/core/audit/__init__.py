"""Audit trail: every pipeline step leaves an audit_events row.

Usage:
    from src.core import audit

    utt_id = audit.new_utterance(session_id, transcript)

    with audit.step(utt_id, "extract", model=MODELS["extract"], input={"text": t}) as s:
        fields = sie.extract(...)
        s.output = fields
        s.confidence = 0.91

    audit.set_intent(utt_id, "log")
    audit.link_expense(utt_id, expense_id)   # once the expense row exists

step() times the block and writes the row when it exits, so the row is in the
database before the request returns. If the block raises, the row is still
written (output = {"error": ...}) and the exception propagates.

    trail.py  writes (utterances, steps)
    feed.py   reads (live feed, per-utterance, per-expense)
"""
from src.core.audit.feed import events_for_expense, events_for_utterance, events_since, events_tail
from src.core.audit.trail import STEPS, link_expense, new_utterance, record, set_intent, step

__all__ = [
    "STEPS", "new_utterance", "set_intent", "link_expense", "record", "step",
    "events_since", "events_tail", "events_for_utterance", "events_for_expense",
]
