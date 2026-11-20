"""Understand a casual ask to the group ("guys hang out tomm?", "bowling this weekend?") as when + what.

Same split as dates: the model only names WHEN as one of a few labels (and pulls out an activity if there is
one); code turns the label into real dates from today. If the model fails, a few plain word checks take over.
"""
import json
import re
from datetime import date, timedelta

WHENS = ("today", "tomorrow", "this_weekend", "next_weekend", "this_week", "next_7_days", "weekday")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_ACTIVITY = 40


def resolve(when: str, weekday: str | None, today: date) -> tuple[date, date]:
    """(start, end) for a label, from today. Unknown labels mean the next 7 days."""
    wd = today.weekday()                                   # Mon = 0 ... Sun = 6
    if when == "today":
        return today, today
    if when == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if when in ("this_weekend", "next_weekend"):
        if wd >= 5:                                        # it's already the weekend: from today to Sunday
            start, sun = today, today + timedelta(days=6 - wd)
        else:                                              # coming Friday evening to Sunday
            start, sun = today + timedelta(days=4 - wd), today + timedelta(days=6 - wd)
        if when == "next_weekend":
            start, sun = start + timedelta(days=7), sun + timedelta(days=7)
        return start, sun
    if when == "this_week":
        return today, today + timedelta(days=6 - wd)
    if when == "weekday" and weekday in WEEKDAYS:
        ahead = (WEEKDAYS.index(weekday) - wd) % 7          # today if it's that day, else the next one
        d = today + timedelta(days=ahead)
        return d, d
    return today + timedelta(days=1), today + timedelta(days=7)


def fallback(text: str) -> dict:
    """Plain word checks for when the model isn't available."""
    t = text.lower()
    if re.search(r"\b(tonight|today|now|later)\b", t):
        when = "today"
    elif re.search(r"\b(tmrw|tmr|tmrw|tomm?o?r?r?o?w?|tom)\b", t):
        when = "tomorrow"
    elif "next weekend" in t:
        when = "next_weekend"
    elif re.search(r"\bweekend\b", t):
        when = "this_weekend"
    elif re.search(r"\bthis week\b", t):
        when = "this_week"
    else:
        day = next((d for d in WEEKDAYS if re.search(rf"\b{d}[a-z]*\b", t)), None)
        return {"when": "weekday" if day else "next_7_days", "weekday": day, "activity": None}
    return {"when": when, "weekday": None, "activity": None}


def understand(text: str, today: date, chat=None) -> dict:
    """{"start", "end", "activity", "when", "by"} for a casual ask. chat(system, user) -> model text."""
    parsed, by = None, "words"
    if chat:
        system = (
            "Someone asked their friends to hang out. Name WHEN with exactly one label from "
            f"{list(WHENS)} (use 'weekday' plus a weekday from {list(WEEKDAYS)} for a named day, and "
            "'next_7_days' if they didn't say), and pull out WHAT they want to do in 1-3 words if they said "
            "(e.g. 'bowling', 'ramen', 'drinks'), else null. Never write dates. "
            'Reply with JSON only: {"when": "...", "weekday": null, "activity": null}'
        )
        try:
            m = re.search(r"\{.*\}", chat(system, text), re.S)
            data = json.loads(m.group(0)) if m else {}
            if data.get("when") in WHENS:
                act = data.get("activity")
                act = " ".join(str(act).split())[:MAX_ACTIVITY] if act and str(act).lower() not in ("null", "none") else None
                wday = data.get("weekday") if data.get("weekday") in WEEKDAYS else None
                parsed, by = {"when": data["when"], "weekday": wday, "activity": act}, "model"
        except Exception:
            parsed = None
    if parsed is None:
        parsed = fallback(text)
    start, end = resolve(parsed["when"], parsed["weekday"], today)
    return {"start": start, "end": end, "activity": parsed["activity"], "when": parsed["when"],
            "weekday": parsed["weekday"], "by": by}
