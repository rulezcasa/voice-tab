"""A person's own private planning data: read and changed only through their own agent link.

The only code (besides src/core/meetups/repo.py, which the personal agent uses) that touches the private
columns on `people` and the `availability` table.
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

MODES = ("walk", "bike", "transit", "drive")


class PrivateError(ValueError):
    """Bad input for a private profile change. Safe to show the owner."""


def get(person_id: int, days: int = 14) -> dict:
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("SELECT id, name, home_lat, home_lng, meetup_budget, max_radius_mi, max_travel_min, travel_mode,"
                    " interests FROM people WHERE id = %s", (person_id,))
        row = cur.fetchone()
        if not row:
            raise PrivateError("no such person")
        pid, name, lat, lng, budget, radius, max_min, mode, interests = row
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        cur.execute("SELECT id, starts_at, ends_at, busy_label FROM availability WHERE person_id = %s"
                    " AND ends_at > %s AND starts_at < %s ORDER BY starts_at",
                    (person_id, now, now + timedelta(days=days)))
        busy = [{"id": i, "starts_at": s.isoformat(), "ends_at": e.isoformat(), "label": l} for i, s, e, l in cur.fetchall()]
        cur.execute("SELECT g.name FROM group_members m JOIN groups_ g ON g.id = m.group_id WHERE m.person_id = %s"
                    " ORDER BY g.name", (person_id,))
        groups = [r[0] for r in cur.fetchall()]
    return {
        "person": {"id": pid, "name": name},
        "profile": {
            "home": [float(lng), float(lat)] if lat is not None and lng is not None else None,   # [lng, lat] like the map
            "budget": f"{Decimal(budget):.2f}" if budget is not None else None,
            "radius_mi": float(radius) if radius is not None else None,
            "max_travel_min": int(max_min) if max_min is not None else None,
            "travel_mode": mode,
            "interests": json.loads(interests) if isinstance(interests, str) else (interests or []),
        },
        "busy": busy,
        "groups": groups,
    }


def update(person_id: int, changes: dict) -> dict:
    """Change any of: home [lng, lat], budget, radius_mi, max_travel_min, travel_mode, interests."""
    sets: dict = {}
    if "home" in changes:
        home = changes["home"]
        if not (isinstance(home, (list, tuple)) and len(home) == 2):
            raise PrivateError("home must be [lng, lat]")
        lng, lat = float(home[0]), float(home[1])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise PrivateError("home is not a real place")
        sets["home_lat"], sets["home_lng"] = lat, lng
    if "budget" in changes:
        try:
            b = Decimal(str(changes["budget"])).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise PrivateError("budget must be a number")
        if b <= 0 or b > 10000:
            raise PrivateError("budget must be between $1 and $10,000")
        sets["meetup_budget"] = b
    if "radius_mi" in changes:
        r = float(changes["radius_mi"])
        if not 0.2 <= r <= 50:
            raise PrivateError("radius must be between 0.2 and 50 miles")
        sets["max_radius_mi"] = r
    if "max_travel_min" in changes:
        m = int(changes["max_travel_min"])
        if not 5 <= m <= 180:
            raise PrivateError("travel time must be between 5 and 180 minutes")
        sets["max_travel_min"] = m
    if "travel_mode" in changes:
        if changes["travel_mode"] not in MODES:
            raise PrivateError(f"travel mode must be one of {', '.join(MODES)}")
        sets["travel_mode"] = changes["travel_mode"]
    if "interests" in changes:
        ints = [str(i).strip().lower() for i in changes["interests"] if str(i).strip()][:12]
        sets["interests"] = json.dumps(ints)
    if not sets:
        return get(person_id)
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute(f"UPDATE people SET {', '.join(f'{k} = %s' for k in sets)} WHERE id = %s", (*sets.values(), person_id))
    return get(person_id)


def add_busy(person_id: int, starts_at: str, ends_at: str, label: str | None) -> dict:
    try:
        s, e = datetime.fromisoformat(starts_at), datetime.fromisoformat(ends_at)
    except (TypeError, ValueError):
        raise PrivateError("times must look like 2026-11-21T14:00")
    if e <= s:
        raise PrivateError("the end must be after the start")
    if e - s > timedelta(days=2):
        raise PrivateError("a busy block can be at most 2 days")
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("INSERT INTO availability (person_id, starts_at, ends_at, busy_label) VALUES (%s, %s, %s, %s)",
                    (person_id, s, e, (label or "Busy").strip()[:100]))
    return get(person_id)


def remove_busy(person_id: int, busy_id: int) -> dict:
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("DELETE FROM availability WHERE id = %s AND person_id = %s", (busy_id, person_id))  # only your own
    return get(person_id)
