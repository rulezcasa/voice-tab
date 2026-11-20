"""Personal agents: each one represents one person and guards their private context.

The coordinator never reads a person's exact location, budget or calendar labels. It gets:
  1. share_constraints(): free/busy windows, a ~1 km area, a radius and travel preferences.
  2. evaluate_venues(): for each candidate venue, only ok / travel time / estimated cost / a
     generic reason. The exact home location and budget are used here and never returned.

For the hackathon every personal agent runs in this one server, so the boundary is in the
code: only this module calls repo.profile() and repo.busy(). In production each would run
separately per user.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from src.core.meetups import geo

DAY_START = time(9, 0)    # nobody is proposed a meetup before 9am...
DAY_END = time(23, 0)     # ...or after 11pm
MIN_WINDOW = timedelta(minutes=30)


# ---------- pure logic (tested without a database) ----------

def free_windows(busy: list[tuple[datetime, datetime]], start: datetime, end: datetime,
                 day_start: time = DAY_START, day_end: time = DAY_END) -> list[tuple[datetime, datetime]]:
    """Free time inside [start, end), limited to day_start..day_end each day, minus busy blocks."""
    out = []
    day = start.date()
    while datetime.combine(day, time()) < end:
        lo = max(start, datetime.combine(day, day_start))
        hi = min(end, datetime.combine(day, day_end))
        cur = lo
        for b_start, b_end in sorted(busy):
            if b_end <= cur or b_start >= hi:
                continue
            if b_start > cur:
                out.append((cur, b_start))
            cur = max(cur, b_end)
        if cur < hi:
            out.append((cur, hi))
        day += timedelta(days=1)
    return [(s, e) for s, e in out if e - s >= MIN_WINDOW]


def constraints_from(profile: dict, busy: list, start: datetime, end: datetime) -> dict:
    """What a person shares with the group coordinator. No budget, no exact location, no labels."""
    mode = profile.get("travel_mode") or "transit"
    return {
        "person_id": profile["id"],
        "name": profile["name"],
        "free": [[s.isoformat(), e.isoformat()] for s, e in free_windows(busy, start, end)],
        "area": list(geo.coarse(float(profile["home_lat"]), float(profile["home_lng"]))),
        "radius_mi": float(profile.get("max_radius_mi") or geo.DEFAULT_RADIUS_MI.get(mode, 6.0)),
        "max_travel_min": int(profile.get("max_travel_min") or 45),
        "mode": mode,
        "interests": profile.get("interests") or [],
    }


def evaluate_from(profile: dict, venues: list[dict], group_size: int) -> list[dict]:
    """Private check of each venue against this person's exact location, radius, travel limit and budget.

    Returns only what the coordinator needs. Reasons are generic ("over budget"), never the numbers.
    """
    home = (float(profile["home_lat"]), float(profile["home_lng"]))
    mode = profile.get("travel_mode") or "transit"
    radius = float(profile.get("max_radius_mi") or geo.DEFAULT_RADIUS_MI.get(mode, 6.0))
    max_min = int(profile.get("max_travel_min") or 45)
    budget = Decimal(str(profile["meetup_budget"])) if profile.get("meetup_budget") is not None else None

    out = []
    for v in venues:
        minutes, travel_cost, miles = geo.travel(home, (float(v["lat"]), float(v["lng"])), mode,
                                                 parking=v.get("parking") or Decimal("0"), group_size=group_size)
        activity = Decimal(str(v["price_pp"]))
        total = (activity + travel_cost).quantize(geo.CENT)
        reason = None
        if miles > radius:
            reason = "outside radius"
        elif minutes > max_min:
            reason = "too long a trip"
        elif budget is not None and total > budget:
            reason = "over budget"
        out.append({
            "venue_id": v["id"], "ok": reason is None, "reason": reason,
            "travel_min": minutes, "travel_cost": f"{travel_cost:.2f}",
            "activity_cost": f"{activity:.2f}", "total": f"{total:.2f}",
        })
    return out


# ---------- the public API (reads the person's private data from the database) ----------

def share_constraints(person_id: int, start: datetime, end: datetime) -> dict:
    """Free/busy windows, ~1 km area, radius and travel preferences: the consented facts."""
    from src.core.meetups import repo
    return constraints_from(repo.profile(person_id), repo.busy(person_id, start, end), start, end)


def evaluate_venues(person_id: int, venues: list[dict], group_size: int) -> list[dict]:
    """Answer "can you make these?" for each venue, using private data that never leaves here."""
    from src.core.meetups import repo
    return evaluate_from(repo.profile(person_id), venues, group_size)
