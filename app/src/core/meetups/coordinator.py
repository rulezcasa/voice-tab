"""Group coordinator: finds when and where a friend group can meet, fairly and within everyone's limits.

It only ever sees what personal agents share (free/busy, ~1 km area, radius, travel mode) and
their per-venue answers (ok / travel time / cost / generic reason). Every decision is plain
Python, so it is explainable: each option carries a `why`, and dropped venues are counted by reason.

Flow: constraints -> overlapping free time -> search circle around the group's midpoint ->
candidate venues -> each personal agent checks them privately -> weather -> fairness score -> top 3.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from src.core.meetups import geo, weather as weather_mod

MAX_SEARCH_MI = 10.0     # group search circle never wider than this
MAX_CANDIDATES = 15      # venues sent to personal agents for checking
MAX_SLOTS = 4            # common free windows considered
TOP_N = 3
W_COST, W_FAIR, W_TRAVEL = 0.4, 0.4, 0.2   # lower score is better


# ---------- pure logic ----------

def _parse(windows: list[list[str]]) -> list[tuple[datetime, datetime]]:
    return [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in windows]


def overlap(free_lists: list[list[tuple[datetime, datetime]]], min_len: timedelta) -> list[tuple[datetime, datetime]]:
    """Windows where everyone is free, at least min_len long."""
    if not free_lists:
        return []
    common = sorted(free_lists[0])
    for other in free_lists[1:]:
        nxt, other = [], sorted(other)
        for a_s, a_e in common:
            for b_s, b_e in other:
                s, e = max(a_s, b_s), min(a_e, b_e)
                if s < e:
                    nxt.append((s, e))
        common = nxt
    return [(s, e) for s, e in common if e - s >= min_len]


def search_area(constraints: list[dict]) -> tuple[tuple[float, float], float]:
    """Midpoint of everyone's rough area, and a circle wide enough to be useful but capped."""
    center = geo.midpoint([tuple(c["area"]) for c in constraints])
    return center, min(max(c["radius_mi"] for c in constraints), MAX_SEARCH_MI)


def pick_candidates(venues: list[dict], constraints: list[dict], center: tuple[float, float], radius: float,
                    ranked_ids: list[int] | None = None, kinds: set[str] | None = None) -> list[dict]:
    """Venues inside the circle, best first: by meaning if ranked_ids, else shared interests, then distance."""
    inside = [v for v in venues if geo.within(center, (float(v["lat"]), float(v["lng"])), radius)]
    if kinds:
        inside = [v for v in inside if v["kind"] in kinds] or inside
    if ranked_ids:
        pos = {vid: i for i, vid in enumerate(ranked_ids)}
        inside.sort(key=lambda v: pos.get(v["id"], len(pos)))
    else:
        interests = Counter(i for c in constraints for i in c["interests"])
        inside.sort(key=lambda v: (-interests.get(v["kind"], 0), geo.haversine_mi(center, (float(v["lat"]), float(v["lng"])))))
    return inside[:MAX_CANDIDATES]


def apply_learned_costs(venues: list[dict], real_pp: dict[str, Decimal]) -> list[dict]:
    """Learn step: replace a venue's listed price with what this group really spent at that kind of place."""
    out = []
    for v in venues:
        if v["kind"] in real_pp and Decimal(str(real_pp[v["kind"]])) != Decimal(str(v["price_pp"])):
            v = {**v, "listed_pp": v["price_pp"], "price_pp": real_pp[v["kind"]], "learned": True}
        out.append(v)
    return out


def _money(d: Decimal) -> str:
    return f"${d:,.0f}" if d == d.to_integral() else f"${d:,.2f}"


def _why(n: int, venue: dict, per_person: list[dict], wx: dict) -> str:
    totals = [Decimal(p["total"]) for p in per_person]
    far = max(per_person, key=lambda p: p["travel_min"])
    cost = _money(min(totals)) if min(totals) == max(totals) else f"{_money(min(totals))}–{_money(max(totals))}"
    parts = [f"All {n} can make it", f"{cost} each", f"longest trip {far['travel_min']} min ({far['name']})"]
    sky = "indoor" if venue["indoor"] else "outdoor"
    parts.append(f"{sky}, {wx['rain_prob']}% rain" + (" (est.)" if wx.get("source") == "stub" else ""))
    if venue.get("learned"):
        parts.append(f"priced from your last {venue['kind']} outing ({_money(Decimal(str(venue['price_pp'])))}/pp)")
    return " · ".join(parts)


def plan_options(constraints: list[dict], venues: list[dict], evaluate, *, min_hours: float = 2,
                 weather=weather_mod.forecast, ranked_ids: list[int] | None = None,
                 kinds: set[str] | None = None, real_pp: dict | None = None) -> dict:
    """Pure planner. `evaluate(person_id, venues, group_size)` is each personal agent's private check.

    Returns {"options": [...], "reason": str | None, "dropped": {...}, "center", "search_radius_mi"}.
    """
    n = len(constraints)
    names = {c["person_id"]: c["name"] for c in constraints}
    base = {"options": [], "reason": None, "dropped": {}, "center": None, "search_radius_mi": None}
    if not n:
        return {**base, "reason": "Nobody in this group yet"}

    slots_all = overlap([_parse(c["free"]) for c in constraints], timedelta(hours=min_hours))
    if not slots_all:
        return {**base, "reason": f"No {min_hours:g}-hour window where all {n} are free"}
    slots = [(s, s + timedelta(hours=min_hours)) for s, _ in slots_all[:MAX_SLOTS]]

    center, radius = search_area(constraints)
    base.update(center=[round(center[0], 3), round(center[1], 3)], search_radius_mi=radius)
    cands = apply_learned_costs(pick_candidates(venues, constraints, center, radius, ranked_ids, kinds), real_pp or {})
    if not cands:
        return {**base, "reason": f"No venues within {radius:g} miles of the group's midpoint"}

    answers = {c["person_id"]: {a["venue_id"]: a for a in evaluate(c["person_id"], cands, n)} for c in constraints}
    dropped: Counter = Counter()
    feasible = []
    for v in cands:
        nos = [a["reason"] for pid in answers if not (a := answers[pid][v["id"]])["ok"]]
        if nos:
            for r in set(nos):
                dropped[f"{r} for {nos.count(r)} {'person' if nos.count(r) == 1 else 'people'}"] += 1
        else:
            feasible.append(v)

    scored = []
    for s, e in slots:
        wx_center = weather(center[0], center[1], s)
        for v in feasible:
            wx = wx_center if v["indoor"] else weather(float(v["lat"]), float(v["lng"]), s)
            if not v["indoor"] and wx["rain_prob"] > weather_mod.RAINY:
                dropped["outdoor and likely rain"] += 1
                continue
            per = [{"person_id": pid, "name": names[pid], **{k: answers[pid][v["id"]][k]
                    for k in ("travel_min", "travel_cost", "activity_cost", "total")}} for pid in answers]
            scored.append({"venue": v, "starts_at": s, "ends_at": e, "weather": wx, "per_person": per})
    if not scored:
        return {**base, "dropped": dict(dropped),
                "reason": "Every nearby venue is over someone's limits" + (" or rained out" if feasible else "")}

    max_cost = max(sum(Decimal(p["total"]) for p in o["per_person"]) / n for o in scored) or Decimal(1)
    max_spread = max(max(p["travel_min"] for p in o["per_person"]) - min(p["travel_min"] for p in o["per_person"]) for o in scored) or 1
    max_avg = max(sum(p["travel_min"] for p in o["per_person"]) / n for o in scored) or 1
    for o in scored:
        mins = [p["travel_min"] for p in o["per_person"]]
        avg_cost = sum(Decimal(p["total"]) for p in o["per_person"]) / n
        o["score"] = round(W_COST * float(avg_cost / max_cost) + W_FAIR * (max(mins) - min(mins)) / max_spread
                           + W_TRAVEL * (sum(mins) / n) / max_avg, 4)
    scored.sort(key=lambda o: (o["score"], o["starts_at"]))

    options, seen = [], set()
    for o in scored:
        if o["venue"]["id"] in seen:
            continue
        seen.add(o["venue"]["id"])
        v = o["venue"]
        options.append({
            "option_no": len(options) + 1,
            "venue": {"id": v["id"], "name": v["name"], "kind": v["kind"], "indoor": v["indoor"],
                      "lat": float(v["lat"]), "lng": float(v["lng"])},
            "starts_at": o["starts_at"].isoformat(), "ends_at": o["ends_at"].isoformat(),
            "weather": o["weather"], "per_person": o["per_person"], "score": o["score"],
            "why": _why(n, v, o["per_person"], o["weather"]),
        })
        if len(options) == TOP_N:
            break
    return {**base, "options": options, "dropped": dict(dropped)}


# ---------- the public API ----------

def plan(group_id: int, start: date, end: date, activity: str | None = None, min_hours: float = 2) -> dict:
    """Plan a meetup for a group between start and end (inclusive dates). Saves the options for voting.

    Returns {"meetup_id", "status": "voting", "options": [...], "dropped", "shared", ...}
    or {"meetup_id": None, "reason": "..."} when nothing works.
    """
    from src.core.meetups import repo, store
    from src.core.people import personal_agent

    g = repo.group(group_id)
    win_start = max(datetime.combine(start, time()), datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    win_end = datetime.combine(end + timedelta(days=1), time())
    shared = [personal_agent.share_constraints(m["id"], win_start, win_end) for m in g["members"]]

    ranked = None
    if activity:
        try:
            ranked = repo.venues_by_meaning(activity)
        except Exception:
            ranked = None  # SIE unreachable: fall back to interests + distance
    try:
        real_pp = repo.real_cost_per_person(group_id)
    except Exception:
        real_pp = {}

    result = plan_options(shared, repo.venues(), personal_agent.evaluate_venues,
                          min_hours=min_hours, ranked_ids=ranked, real_pp=real_pp)
    result["shared"] = shared          # what left each personal agent: for the audit trail / Firedrill
    result["group"] = {"id": g["id"], "name": g["name"]}
    if not result["options"]:
        return {**result, "meetup_id": None, "status": None}
    meetup = store.create(group_id, f"{g['name']} meetup", result["options"])
    return {**result, "meetup_id": meetup["id"], "status": meetup["status"]}
