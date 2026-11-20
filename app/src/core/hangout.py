"""Hangout: real places that everyone in the group can reach in time and afford. Pure Python except `fetch`.

Same travel model as the map (webapp/src/lib/geo.ts): straight-line distance at rough city speeds, so the
reach circles drawn on the map and the places offered agree.

  1. middle = average of everyone's pin
  2. search circle around the middle that covers every place someone could still reach
  3. real places of the chosen kinds inside it (OpenStreetMap, via places.nearby)
  4. keep places everyone reaches within their minutes and whose estimated price fits the smallest budget
  5. rank: short and fair trips first, places matching the note get a boost; top 6
"""
import math
import re
from decimal import Decimal

from pydantic import BaseModel, Field

SPEED_M_PER_MIN = {"walk": 80, "bike": 250, "drive": 450}   # keep in sync with webapp/src/lib/geo.ts
MAX_SEARCH_M = 2000     # keeps the OpenStreetMap query small (with places.MAX_RESULTS)
MIN_SEARCH_M = 300
TOP_N = 6
EARTH_M = 6371008.8

# Estimated spend per person (USD) by OSM subtype. OpenStreetMap has no prices, so these are rough.
PRICE_PP = {
    "fast_food": 12, "food_court": 14, "restaurant": 25, "cafe": 9, "ice_cream": 7,
    "bar": 18, "pub": 18, "biergarten": 18, "cinema": 18, "theatre": 40, "karaoke_box": 25,
    "bowling_alley": 25, "amusement_arcade": 15, "escape_game": 32, "miniature_golf": 15, "trampoline_park": 22,
}
RETAIL_PP = 20
LABEL = {"fast_food": "fast food", "food_court": "food court", "ice_cream": "ice cream", "biergarten": "beer garden",
         "bowling_alley": "bowling", "amusement_arcade": "arcade", "escape_game": "escape room",
         "miniature_golf": "mini golf", "trampoline_park": "trampoline park", "karaoke_box": "karaoke"}


class Member(BaseModel):
    person_id: int
    name: str
    is_me: bool = False
    budget: str = Field(description="dollars per person, e.g. '30'")
    minutes: int = Field(gt=0, le=180)
    mode: str = "walk"
    location: tuple[float, float] = Field(description="[lng, lat]")


class HangoutRequest(BaseModel):
    group_id: int | None = None
    members: list[Member]
    kinds: list[str] = []
    note: str = ""


class HangoutError(ValueError):
    """Bad request (too few people, no pins). Safe to show the user."""


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two [lng, lat] points (haversine)."""
    lng1, lat1, lng2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def reach_m(m: Member) -> float:
    return m.minutes * SPEED_M_PER_MIN.get(m.mode, SPEED_M_PER_MIN["walk"])


def travel_min(m: Member, to: tuple[float, float]) -> int:
    return max(1, round(distance_m(m.location, to) / SPEED_M_PER_MIN.get(m.mode, SPEED_M_PER_MIN["walk"])))


def middle(members: list[Member]) -> tuple[float, float]:
    return (sum(m.location[0] for m in members) / len(members), sum(m.location[1] for m in members) / len(members))


def search_radius(members: list[Member], centre: tuple[float, float]) -> int:
    """A place p reachable by everyone satisfies d(centre, p) <= d(centre, i) + reach_i for every i,
    so the smallest of those bounds the search. Clamped so the query stays small."""
    bound = min(distance_m(centre, m.location) + reach_m(m) for m in members)
    return int(min(max(bound, MIN_SEARCH_M), MAX_SEARCH_M))


def price_pp(p: dict) -> int:
    return RETAIL_PP if p["kind"] == "retail" else PRICE_PP.get(p["subtype"], 20)


def price_level(pp: int) -> int:
    return 1 if pp <= 15 else 2 if pp <= 30 else 3 if pp <= 55 else 4


def note_words(note: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", note.lower()) if len(w) >= 3]


def matches_note(p: dict, words: list[str]) -> list[str]:
    """Note words this place backs up: name, the search words that found it, cuisine, diet:*, outdoor seating."""
    t = p["tags"]
    hay = " ".join([p["name"], t.get("cuisine", "").replace(";", " ").replace("_", " "), p["subtype"],
                    *p.get("found_by", [])]).lower()
    hay += " " + " ".join(k.split(":", 1)[1] for k, v in t.items() if k.startswith("diet:") and v in ("yes", "only"))
    if t.get("outdoor_seating") == "yes":
        hay += " outdoor outside patio"
    return [w for w in words if w in hay or (w.endswith("s") and w[:-1] in hay)]


def _why(p: dict, mins: dict[int, int], members: list[Member], matched: list[str]) -> str:
    lo, hi = min(mins.values()), max(mins.values())
    far = max(members, key=lambda m: mins[m.person_id])
    trip = f"Everyone within {hi} min" if lo == hi else f"Everyone {lo}–{hi} min away (longest: {'you' if far.is_me else far.name.split()[0]})"
    kind = p["tags"].get("cuisine", "").split(";")[0].replace("_", " ") or LABEL.get(p["subtype"], p["subtype"])
    parts = [trip, kind.capitalize()]
    if matched:
        parts.append(f"matches “{', '.join(matched)}”")
    parts.append("price estimated")
    return " · ".join(parts)


KINDS = ("restaurant", "cafe", "bar", "retail", "activity")
CANDIDATES_FOR_PICK = 12   # best-by-code places the model chooses from


def _place_out(p: dict, mins: dict[int, int], pp: int, why: str) -> dict:
    return {"id": p["id"], "name": p["name"], "kind": p["kind"], "location": [p["lng"], p["lat"]],
            "address": p["address"], "price_level": price_level(pp), "per_person": str(pp), "rating": None,
            "minutes": mins, "why": why}


def recommend(req: HangoutRequest, fetch, llm=None) -> dict:
    """{meeting_point: [lng, lat], places: [...]} in the UI's HangoutResult shape.

    fetch(lat, lng, radius_m, kinds, terms) returns real places like src.core.places.nearby.
    llm (optional, like src.agents.hangout_llm) turns the note into search words and picks from the real
    candidates; when it is missing or fails, plain code ranking is used."""
    members = req.members
    if len(members) < 2:
        raise HangoutError("pick at least two people who are going")
    centre = middle(members)
    radius = search_radius(members, centre)
    budget = min(Decimal(m.budget) for m in members)
    words = note_words(req.note)
    kinds = [k for k in req.kinds if k in KINDS] or ["restaurant", "cafe", "bar"]

    terms = (llm.search_terms(req.note, kinds) or []) if llm and req.note.strip() else []
    scored = []
    for p in fetch(centre[1], centre[0], radius, kinds, terms):
        loc = (p["lng"], p["lat"])
        mins = {m.person_id: travel_min(m, loc) for m in members}
        if any(mins[m.person_id] > m.minutes for m in members):
            continue                                     # someone can't get there in time
        pp = price_pp(p)
        if pp > budget:
            continue                                     # over the smallest budget
        matched = matches_note(p, words)
        total, spread = sum(mins.values()), max(mins.values()) - min(mins.values())
        scored.append((total + spread - 8 * len(matched), p, mins, pp, matched))

    scored.sort(key=lambda s: (s[0], s[1]["name"]))
    ranked, seen = [], set()
    for _, p, mins, pp, matched in scored:
        if p["name"].lower() in seen:                    # one branch per chain
            continue
        seen.add(p["name"].lower())
        ranked.append((p, mins, pp, matched))

    picked_by, places = "code", []
    if llm and ranked:
        pool = ranked[:CANDIDATES_FOR_PICK]
        cands = [{"id": p["id"], "name": p["name"], "per_person": pp, "minutes": mins, "found_by": p.get("found_by", []),
                  "label": (p["tags"].get("cuisine", "").split(";")[0].replace("_", " ") or LABEL.get(p["subtype"], p["subtype"]))}
                 for p, mins, pp, _ in pool]
        picks = llm.pick(cands, members, req.note, TOP_N)
        if picks:
            by_id = {p["id"]: (p, mins, pp) for p, mins, pp, _ in pool}
            for pid, why in picks:
                p, mins, pp = by_id[pid]
                lo, hi = min(mins.values()), max(mins.values())
                trip = f"{hi} min each" if lo == hi else f"{lo}–{hi} min each"
                places.append(_place_out(p, mins, pp, f"{why} · {trip} · price estimated"))
            picked_by = "qwen"
    if not places:
        places = [_place_out(p, mins, pp, _why(p, mins, members, matched)) for p, mins, pp, matched in ranked[:TOP_N]]
    return {"meeting_point": list(centre), "places": places, "search_radius_m": radius, "source": "openstreetmap",
            "picked_by": picked_by, "search_words": [w for w, _ in terms]}
