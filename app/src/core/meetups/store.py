"""Meetups, their options and votes: the only code that writes meetup tables.

Status: voting -> agreed (a majority picked one option) -> confirmed (venue and time locked in).
A calendar event (.ics) is only offered once confirmed.
"""
import json
from datetime import date, datetime
from decimal import Decimal

STATUSES = ("voting", "agreed", "confirmed", "cancelled")


class MeetupError(ValueError):
    """Bad input (unknown meetup, option, person). Safe to show the user."""


def _publish(meetup: dict) -> None:
    try:
        from src.core import live  # Person 1's live updates; optional until it exists
        live.publish({"type": "meetup", "meetup": meetup})
    except Exception:
        pass


def _plain(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def majority(n_members: int) -> int:
    return n_members // 2 + 1


# ---------- pure ----------

def ics(meetup: dict) -> str:
    """Minimal iCalendar event for a confirmed meetup (times are local, floating)."""
    if meetup["status"] != "confirmed":
        raise MeetupError("only confirmed meetups have a calendar event")
    fmt = lambda iso: datetime.fromisoformat(iso).strftime("%Y%m%dT%H%M%S")
    opt = next(o for o in meetup["options"] if o["option_no"] == meetup["chosen_option"])
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tab//Meetups//EN", "BEGIN:VEVENT",
        f"UID:tab-meetup-{meetup['id']}@tab", f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{fmt(meetup['starts_at'])}", f"DTEND:{fmt(meetup['ends_at'])}",
        f"SUMMARY:{meetup['title']} @ {opt['venue_name']}", f"GEO:{opt['lat']};{opt['lng']}",
        f"DESCRIPTION:{opt['why']}", "END:VEVENT", "END:VCALENDAR", "",
    ])


# ---------- database ----------

def create(group_id: int, title: str, options: list[dict]) -> dict:
    from src.db.s2_client import transaction
    with transaction() as cur:
        cur.execute("INSERT INTO meetups (group_id, title, status) VALUES (%s, %s, 'voting')", (group_id, title))
        mid = cur.lastrowid
        cur.executemany(
            "INSERT INTO meetup_options (meetup_id, option_no, venue_id, starts_at, ends_at, per_person, weather, score, why)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(mid, o["option_no"], o["venue"]["id"], o["starts_at"], o["ends_at"], json.dumps(o["per_person"]),
              json.dumps(o["weather"]), o["score"], o["why"][:500]) for o in options])
    m = get(mid)
    _publish(m)
    return m


def get(meetup_id: int) -> dict:
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute(
            "SELECT m.id, m.group_id, g.name AS group_name, m.title, m.status, m.venue_id, m.starts_at, m.ends_at,"
            " m.created_at FROM meetups m JOIN groups_ g ON g.id = m.group_id WHERE m.id = %s", (meetup_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            raise MeetupError(f"no meetup with id {meetup_id}")
        m = {k: _plain(v) for k, v in zip(cols, row)}
        cur.execute(
            "SELECT o.option_no, o.venue_id, v.name, v.kind, v.indoor, v.lat, v.lng, o.starts_at, o.ends_at,"
            " o.per_person, o.weather, o.score, o.why FROM meetup_options o JOIN venues v ON v.id = o.venue_id"
            " WHERE o.meetup_id = %s ORDER BY o.option_no", (meetup_id,))
        opts = []
        for no, vid, name, kind, indoor, lat, lng, s, e, pp, wx, score, why in cur.fetchall():
            opts.append({"option_no": no, "venue_id": vid, "venue_name": name, "kind": kind, "indoor": bool(indoor),
                         "lat": float(lat), "lng": float(lng), "starts_at": _plain(s), "ends_at": _plain(e),
                         "per_person": json.loads(pp) if isinstance(pp, str) else pp,
                         "weather": json.loads(wx) if isinstance(wx, str) else wx, "score": score, "why": why})
        cur.execute(
            "SELECT v.person_id, p.name, v.option_no FROM meetup_votes v JOIN people p ON p.id = v.person_id"
            " WHERE v.meetup_id = %s ORDER BY p.name", (meetup_id,))
        votes = [{"person_id": pid, "name": n, "option_no": o} for pid, n, o in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM group_members WHERE group_id = %s", (m["group_id"],))
        size = cur.fetchone()[0]
    tally = {o["option_no"]: sum(1 for v in votes if v["option_no"] == o["option_no"]) for o in opts}
    chosen = next((o["option_no"] for o in opts if o["venue_id"] == m["venue_id"] and o["starts_at"] == m["starts_at"]), None)
    return {**m, "options": opts, "votes": votes, "tally": tally, "group_size": size,
            "needed": majority(size), "chosen_option": chosen}


def vote(meetup_id: int, person_id: int, option_no: int) -> dict:
    """One vote per person (a new vote replaces the old). A majority on one option -> status 'agreed'."""
    from src.db.s2_client import cursor
    m = get(meetup_id)
    if m["status"] in ("confirmed", "cancelled"):
        raise MeetupError(f"this meetup is already {m['status']}")
    if option_no not in m["tally"]:
        raise MeetupError(f"there is no option {option_no}; pick 1 to {len(m['options'])}")
    with cursor() as cur:
        cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND person_id = %s", (m["group_id"], person_id))
        if not cur.fetchone():
            raise MeetupError("only members of this group can vote")
        cur.execute("DELETE FROM meetup_votes WHERE meetup_id = %s AND person_id = %s", (meetup_id, person_id))
        cur.execute("INSERT INTO meetup_votes (meetup_id, person_id, option_no) VALUES (%s, %s, %s)",
                    (meetup_id, person_id, option_no))
        m = get(meetup_id)
        leader = max(m["tally"], key=m["tally"].get)
        status = "agreed" if m["tally"][leader] >= m["needed"] else "voting"
        if status != m["status"]:
            cur.execute("UPDATE meetups SET status = %s WHERE id = %s", (status, meetup_id))
    m = get(meetup_id)
    _publish(m)
    return m


def confirm(meetup_id: int, option_no: int | None = None, force: bool = False) -> dict:
    """Lock in the agreed option (or option_no). Without a majority it needs force=True (the organiser decides)."""
    from src.db.s2_client import cursor
    m = get(meetup_id)
    if m["status"] == "cancelled":
        raise MeetupError("this meetup was cancelled")
    if option_no is None:
        option_no = max(m["tally"], key=m["tally"].get) if any(m["tally"].values()) else 1
    if m["status"] != "agreed" and not force:
        raise MeetupError(f"no majority yet ({max(m['tally'].values(), default=0)} of {m['needed']} votes). "
                          "Ask the group to vote, or confirm anyway as the organiser")
    opt = next((o for o in m["options"] if o["option_no"] == option_no), None)
    if not opt:
        raise MeetupError(f"there is no option {option_no}")
    with cursor() as cur:
        cur.execute("UPDATE meetups SET status = 'confirmed', venue_id = %s, starts_at = %s, ends_at = %s WHERE id = %s",
                    (opt["venue_id"], opt["starts_at"], opt["ends_at"], meetup_id))
    m = get(meetup_id)
    _publish(m)
    return m


def active_for_group(group_id: int, on: date) -> dict | None:
    """The confirmed meetup this group has on that day: shared expenses that day get linked to it."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("SELECT id FROM meetups WHERE group_id = %s AND status = 'confirmed' AND DATE(starts_at) = %s"
                    " ORDER BY starts_at DESC LIMIT 1", (group_id, on))
        row = cur.fetchone()
    return get(row[0]) if row else None


def active_for_people(person_ids: list[int], on: date) -> dict | None:
    """A confirmed meetup that day whose group contains all these people (for expenses with no group named)."""
    from src.db.s2_client import cursor
    ids = list(dict.fromkeys(person_ids))
    if not ids:
        return None
    with cursor() as cur:
        cur.execute(
            "SELECT m.id FROM meetups m JOIN group_members gm ON gm.group_id = m.group_id"
            f" WHERE m.status = 'confirmed' AND DATE(m.starts_at) = %s AND gm.person_id IN ({','.join(['%s'] * len(ids))})"
            " GROUP BY m.id HAVING COUNT(DISTINCT gm.person_id) = %s ORDER BY MAX(m.starts_at) DESC LIMIT 1",
            (on, *ids, len(ids)))
        row = cur.fetchone()
    return get(row[0]) if row else None
