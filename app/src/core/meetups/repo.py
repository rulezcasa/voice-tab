"""Database reads for meetups and personal agents. The only meetup code that runs SELECTs.

Imports of the database client are inside the functions so the pure planning logic
(personal_agent, coordinator) can be imported and tested without a database.
"""
import json
from datetime import datetime
from decimal import Decimal


def _rows(cur) -> list[dict]:
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _json(v):
    return json.loads(v) if isinstance(v, str) else (v or [])


def profile(person_id: int) -> dict:
    """PRIVATE: one person's full planning profile. Only personal_agent may call this."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute(
            "SELECT id, name, home_lat, home_lng, meetup_budget, max_radius_mi, max_travel_min,"
            " travel_mode, interests FROM people WHERE id = %s", (person_id,))
        rows = _rows(cur)
    if not rows:
        raise ValueError(f"no person with id {person_id}")
    p = rows[0]
    p["interests"] = _json(p["interests"])
    return p


def busy(person_id: int, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """PRIVATE: busy blocks overlapping [start, end). Labels are never read here."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute(
            "SELECT starts_at, ends_at FROM availability"
            " WHERE person_id = %s AND ends_at > %s AND starts_at < %s ORDER BY starts_at",
            (person_id, start, end))
        return [(s, e) for s, e in cur.fetchall()]


def busy_labels(person_id: int, start: datetime, end: datetime) -> list[str]:
    """PRIVATE: calendar labels in [start, end). Only used by that person's own agent, to check it never says them."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute(
            "SELECT DISTINCT busy_label FROM availability WHERE person_id = %s AND ends_at > %s AND starts_at < %s",
            (person_id, start, end))
        return [r[0] for r in cur.fetchall() if r[0]]


def group_by_name(name: str) -> dict:
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("SELECT id FROM groups_ WHERE LOWER(name) = LOWER(%s)", (name,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"no group called {name!r}")
    return group(row[0])


def group(group_id: int) -> dict:
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("SELECT id, name FROM groups_ WHERE id = %s", (group_id,))
        rows = _rows(cur)
        if not rows:
            raise ValueError(f"no group with id {group_id}")
        cur.execute(
            "SELECT p.id, p.name, p.is_me FROM group_members m JOIN people p ON p.id = m.person_id"
            " WHERE m.group_id = %s ORDER BY p.is_me DESC, p.name", (group_id,))
        members = _rows(cur)
    for m in members:
        m["is_me"] = bool(m["is_me"])
    return {**rows[0], "members": members}


def venues() -> list[dict]:
    """All venues (public data). Small table, so the coordinator filters in Python."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        cur.execute("SELECT id, name, kind, lat, lng, price_pp, parking, indoor, description FROM venues")
        rows = _rows(cur)
    for v in rows:
        v["indoor"] = bool(v["indoor"])
        v["price_pp"] = Decimal(v["price_pp"] or 0)
        v["parking"] = Decimal(v["parking"] or 0)
    return rows


def venues_by_meaning(text: str, limit: int = 30) -> list[int]:
    """Venue ids ranked by bge-m3 similarity to `text` ("something indoors", "bowling")."""
    from src.db.s2_client import cursor, to_vector
    from src.model.embeddings import embed
    vec = to_vector(embed([text], is_query=True)[0])
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM venues WHERE embedding IS NOT NULL"
            " ORDER BY DOT_PRODUCT(embedding, %s :> VECTOR(1024)) DESC LIMIT %s", (vec, limit))
        return [r[0] for r in cur.fetchall()]


def real_cost_per_person(group_id: int) -> dict[str, Decimal]:
    """Learn step: what this group actually spent per person, per venue kind, at past confirmed meetups."""
    from src.db.s2_client import cursor
    with cursor() as cur:
        # SingleStore rejects a correlated scalar subquery here, so the group size is joined in as a derived table.
        cur.execute(
            "SELECT v.kind, SUM(e.amount) AS spent, COUNT(DISTINCT m.id) AS n_meetups, gs.size"
            " FROM expenses e JOIN meetups m ON m.id = e.meetup_id JOIN venues v ON v.id = m.venue_id"
            " JOIN (SELECT group_id, COUNT(*) AS size FROM group_members GROUP BY group_id) gs ON gs.group_id = m.group_id"
            " WHERE m.group_id = %s AND m.status = 'confirmed' AND e.category <> 'settlement'"
            " GROUP BY v.kind, gs.size", (group_id,))
        out = {}
        for kind, spent, n, size in cur.fetchall():
            if n and size:
                out[kind] = (Decimal(spent) / n / size).quantize(Decimal("0.01"))
    return out
