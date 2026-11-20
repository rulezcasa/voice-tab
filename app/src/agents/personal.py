"""Model-backed personal agent: one per person, holding ONLY that person's private context.

It answers the coordinator's proposals on the person's behalf. Split of work:
  - code decides the hard facts privately (src/core/people/personal_agent.evaluate_from): is it within my
    radius, my travel limit, my budget? The model can't overrule these (it can't accept something over budget).
  - the model (Qwen on SIE) writes the reply to the group and, when declining, a hint for the next proposal
    ("cheaper", "closer", "different kind of place").
  - a leak guard checks the reply for anything private (budget, exact location, radius, calendar labels).
    A leaking reply is replaced with a safe generic one and the leak is recorded for Firedrill.

Nothing private ever goes in the reply: only accept/decline, a generic reason and a hint.
"""
import json
import re
from decimal import Decimal

from src.core.people import personal_agent as rules

HINTS = ("cheaper", "closer", "different_kind", "none")
GENERIC = {
    "over budget": "That one's more than I want to spend.",
    "outside radius": "That's a bit far out for me.",
    "too long a trip": "That trip is too long for me.",
    None: "Works for me!",
}


def private_facts(profile: dict, venue: dict, group_size: int) -> dict:
    """Ground truth for this person and venue, worked out by code. Never sent to the coordinator."""
    a = rules.evaluate_from(profile, [venue], group_size)[0]
    return {"ok": a["ok"], "reason": a["reason"], "travel_min": a["travel_min"], "total": a["total"]}


def secrets(profile: dict, busy_labels: list[str]) -> dict:
    """Everything this agent must never say."""
    nums = set()
    if profile.get("meetup_budget") is not None:
        b = Decimal(str(profile["meetup_budget"]))
        nums |= {f"{b:.2f}", f"{b:.0f}", str(int(b))}
    # max_radius_mi is not a secret: personal agents share it with the coordinator on purpose.
    coords = [f"{float(profile[k]):.2f}" for k in ("home_lat", "home_lng") if profile.get(k) is not None]
    return {"numbers": sorted(nums), "coords": coords, "labels": [l for l in busy_labels if l]}


def leaks(text: str, s: dict) -> list[str]:
    """What private things this text gives away (empty = safe)."""
    found, low = [], text.lower()
    for n in s["numbers"]:
        if re.search(rf"(?<![\d.:]){re.escape(n)}(?![\d:])", text):   # "2:30 PM" is a time, not a budget
            found.append(f"number {n}")
    for c in s["coords"]:
        if c.lstrip("-") in text:
            found.append(f"coordinate {c}")
    for label in s["labels"]:
        if re.search(rf"\b{re.escape(label.lower())}\b", low):
            found.append(f"calendar label '{label}'")
    if re.search(r"\b(budget|limit) (is|of)\s*\$?\d", low) or re.search(r"\bi live (at|on|near)\b", low):
        found.append("states a private limit or home")
    return found


def _json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def reply(name: str, profile: dict, busy_labels: list[str], proposal: dict, group_size: int, chat) -> dict:
    """The agent's answer to one proposal.

    proposal = {"venue": {...}, "starts_at", "message"}; chat(system, user) -> model text.
    Returns {"decision": "accept"|"decline", "message", "hint", "facts" (private), "leaks" (private), "model": bool}.
    """
    facts = private_facts(profile, proposal["venue"], group_size)
    s = secrets(profile, busy_labels)
    v = proposal["venue"]
    system = (
        f"You are {name}'s personal agent in a group chat planning a meetup. You know {name}'s private details; "
        "the group must never learn them. NEVER state any number about budget, money limits, distance limits or "
        "home location, never say where they live, and never mention what is on their calendar. "
        f"Code has already checked the proposal for {name}: fits={facts['ok']}, "
        f"problem={facts['reason'] or 'none'}. You must decline if fits is false and accept if it is true. "
        "Write one short friendly sentence to the group (max 20 words), in first person as "
        f"{name}, giving at most a vague reason. If you decline, pick a hint for the next proposal from "
        f"{list(HINTS)}. "
        'Reply with JSON only: {"decision": "accept|decline", "message": "...", "hint": "..."}'
    )
    private = {"budget_per_meetup": str(profile.get("meetup_budget")), "travel_mode": profile.get("travel_mode"),
               "max_radius_mi": profile.get("max_radius_mi"), "interests": profile.get("interests") or [],
               "trip_to_this_place_min": facts["travel_min"], "estimated_total_cost": facts["total"]}
    user = (f"{name}'s private details (do not repeat): {json.dumps(private)}\n"
            f"Proposal from the coordinator: {proposal.get('message') or ''}\n"
            f"Place: {v['name']} ({v['kind']}, {'indoor' if v.get('indoor') else 'outdoor'}) at {proposal['starts_at']}")

    decision = "accept" if facts["ok"] else "decline"
    message, hint, used_model, found = GENERIC[facts["reason"]], "none", False, []
    try:
        data = _json(chat(system, user)) or {}
        text = " ".join(str(data.get("message", "")).split())[:200]
        agrees = str(data.get("decision", decision)).lower() == decision
        if text and agrees:           # a message arguing the opposite of the real decision would mislead the group
            used_model = True
            found = leaks(text, s)
            message = GENERIC[facts["reason"]] if found else text   # a leaking reply never reaches the group
        h = str(data.get("hint", "none"))
        hint = h if h in HINTS else "none"
    except Exception:
        pass
    if decision == "decline" and hint == "none":  # code knows what would help even if the model didn't say
        hint = {"over budget": "cheaper", "outside radius": "closer", "too long a trip": "closer"}.get(facts["reason"], "none")
    if decision == "accept":
        hint = "none"
    return {"decision": decision, "message": message, "hint": hint, "facts": facts, "leaks": found, "model": used_model}
