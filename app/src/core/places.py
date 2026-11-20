"""Real places near a point. Free, no API keys, all OpenStreetMap data:

  1. Photon (photon.komoot.io): a fast search engine over OpenStreetMap. Matches words in place names, so we
     run a handful of short searches ("coffee", "taqueria", "vegetarian"...) in parallel, each limited to the
     search box and one place type, and merge the results. Usually 1-2 s.
  2. Overpass (overpass-api.de and mirrors): the full OpenStreetMap query service. Only a backup: its public
     servers are often overloaded.

Only a search box (around the group's middle) is sent, never anyone's own location. Results are cached for a
few minutes. OpenStreetMap has no prices or ratings: prices are estimated later, ratings are left empty.
"""
import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "KeepTab-hackathon/0.1 (meetup place search)"
MAX_RESULTS = 60       # places kept per search (nearest to the middle); ranking keeps the best 6
CACHE_TTL_S = 600

# ---------- place types ----------

# UI place kind -> OSM (key, values) that count as that kind
KIND_TAGS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "restaurant": [("amenity", ("restaurant", "fast_food", "food_court"))],
    "cafe": [("amenity", ("cafe", "ice_cream"))],
    "bar": [("amenity", ("bar", "pub", "biergarten"))],
    "retail": [("shop", ("mall", "department_store", "books", "gift", "clothes", "second_hand",
                         "variety_store", "music", "games"))],
    "activity": [("leisure", ("bowling_alley", "amusement_arcade", "escape_game", "miniature_golf",
                              "trampoline_park")),
                 ("amenity", ("cinema", "theatre", "karaoke_box"))],
}

# Photon matches words in names, so each kind gets a few everyday words, each with the OSM tag it must have.
PHOTON_DEFAULTS: dict[str, list[tuple[str, str]]] = {
    "restaurant": [("restaurant", "amenity:restaurant"), ("kitchen", "amenity:restaurant"),
                   ("taqueria", "amenity:restaurant"), ("pizza", "amenity:restaurant")],
    "cafe": [("coffee", "amenity:cafe"), ("cafe", "amenity:cafe")],
    "bar": [("bar", "amenity:bar"), ("pub", "amenity:pub")],
    "retail": [("books", "shop:books"), ("shop", "shop")],
    "activity": [("bowling", "leisure:bowling_alley"), ("cinema", "amenity:cinema"),
                 ("arcade", "leisure:amusement_arcade")],
}
# The tag an extra search word (from the agent: "vegetarian", "ramen") is limited to, per kind.
PHOTON_KIND_TAG = {"restaurant": "amenity:restaurant", "cafe": "amenity:cafe", "bar": "amenity:bar",
                   "retail": "shop", "activity": "leisure"}

_cache: dict[tuple, tuple[float, list[dict]]] = {}


class PlacesError(RuntimeError):
    """No places source could be reached. The message is safe to show the user."""


def classify(tags: dict) -> tuple[str, str] | None:
    """(UI kind, OSM subtype) for a place's tags, e.g. ('restaurant', 'fast_food')."""
    for kind, rules in KIND_TAGS.items():
        for key, values in rules:
            if tags.get(key) in values:
                return kind, tags[key]
    return None


def bbox(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """(min_lng, min_lat, max_lng, max_lat) of the square around the circle."""
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def _get_json(url: str, timeout: float, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _nearest(places: list[dict], lat: float, lng: float) -> list[dict]:
    """Deduplicate by id and keep the MAX_RESULTS closest to the middle."""
    seen, out = set(), []
    for p in places:
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    out.sort(key=lambda p: (p["lat"] - lat) ** 2 + ((p["lng"] - lng) * math.cos(math.radians(lat))) ** 2)
    return out[:MAX_RESULTS]


# ---------- 1. Photon ----------

PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_TIMEOUT_S = 6
PHOTON_LIMIT = 15          # results per search word
PHOTON_MAX_SEARCHES = 10


def photon_searches(kinds: list[str], terms: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(word, osm_tag) searches to run: the agent's words first (they carry the note), then each kind's defaults."""
    out = [(w, PHOTON_KIND_TAG[k]) for w, k in terms if k in kinds]
    out += [s for k in kinds for s in PHOTON_DEFAULTS[k]]
    return list(dict.fromkeys(out))[:PHOTON_MAX_SEARCHES]


def parse_photon(data: dict, word: str) -> list[dict]:
    out = []
    for f in data.get("features", []):
        p, coords = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates")
        tags = {p.get("osm_key"): p.get("osm_value"), "name": p.get("name")}
        kind = classify(tags)
        if not p.get("name") or not coords or not kind:
            continue
        street = p.get("street")
        addr = f"{p['housenumber']} {street}" if street and p.get("housenumber") else street or "No address listed"
        out.append({"id": f"osm-{p.get('osm_type', 'X')}-{p.get('osm_id')}", "name": p["name"], "kind": kind[0],
                    "subtype": kind[1], "lng": float(coords[0]), "lat": float(coords[1]), "address": addr,
                    "tags": tags, "found_by": [word]})
    return out


def nearby_photon(lat: float, lng: float, radius_m: int, kinds: list[str], terms: list[tuple[str, str]]) -> list[dict]:
    box = ",".join(f"{v:.5f}" for v in bbox(lat, lng, radius_m))

    def one(search: tuple[str, str]) -> list[dict]:
        word, tag = search
        q = urllib.parse.urlencode({"q": word, "lat": f"{lat:.5f}", "lon": f"{lng:.5f}", "limit": PHOTON_LIMIT,
                                    "osm_tag": tag, "bbox": box, "lang": "en"})
        return parse_photon(_get_json(f"{PHOTON_URL}?{q}", PHOTON_TIMEOUT_S), word)

    searches = photon_searches(kinds, terms)
    results, failures = [], 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        for got in pool.map(lambda s: _safe(one, s), searches):
            if got is None:
                failures += 1
            else:
                results += got
    if failures == len(searches):
        raise PlacesError("Photon didn't answer")
    merged: dict[str, dict] = {}
    for p in results:  # the same place found by several words: remember all of them
        if p["id"] in merged:
            merged[p["id"]]["found_by"] = list(dict.fromkeys(merged[p["id"]]["found_by"] + p["found_by"]))
        else:
            merged[p["id"]] = p
    return _nearest(list(merged.values()), lat, lng)


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception:
        return None


# ---------- 2. Overpass (backup) ----------

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_TIMEOUT_S = 8


def build_query(lat: float, lng: float, radius_m: int, kinds: list[str]) -> str:
    """Light query: exact tag matches (no regex), nodes and ways only, named places, at most MAX_RESULTS back."""
    around = f"around:{radius_m},{lat:.6f},{lng:.6f}"
    parts = [f'nw({around})["{key}"="{value}"]["name"];'
             for kind in kinds for key, values in KIND_TAGS[kind] for value in values]
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];({''.join(parts)});out center tags qt {MAX_RESULTS};"


def address(tags: dict) -> str:
    street = tags.get("addr:street")
    if not street:
        return "No address listed"
    return f"{tags['addr:housenumber']} {street}" if tags.get("addr:housenumber") else street


def parse(data: dict) -> list[dict]:
    """Overpass JSON -> places (named, classifiable only)."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lng = el.get("lon", (el.get("center") or {}).get("lon"))
        kind = classify(tags)
        if not tags.get("name") or lat is None or lng is None or not kind:
            continue
        out.append({"id": f"osm-{el['type']}-{el['id']}", "name": tags["name"], "kind": kind[0], "subtype": kind[1],
                    "lng": float(lng), "lat": float(lat), "address": address(tags), "tags": tags, "found_by": []})
    return out


def nearby_overpass(lat: float, lng: float, radius_m: int, kinds: list[str]) -> list[dict]:
    query, last = build_query(lat, lng, int(radius_m), kinds), None
    for url in OVERPASS_ENDPOINTS:
        try:
            data = _get_json(url, OVERPASS_TIMEOUT_S, urllib.parse.urlencode({"data": query}).encode())
            if "remark" in data and not data.get("elements"):
                raise RuntimeError(data["remark"][:120])
            return _nearest(parse(data), lat, lng)
        except Exception as e:
            last = e
    raise PlacesError(f"Overpass didn't answer ({type(last).__name__})")


# ---------- entry point ----------

def nearby(lat: float, lng: float, radius_m: int, kinds: list[str], terms: list[tuple[str, str]] = ()) -> list[dict]:
    """Named places of these kinds near (lat, lng): Photon first, Overpass as a backup.
    terms = extra (word, kind) searches from the agent, e.g. [("vegetarian", "restaurant")]."""
    kinds = sorted({k for k in kinds if k in KIND_TAGS}) or ["restaurant", "cafe", "bar"]
    terms = [(w.strip().lower(), k) for w, k in terms if w and w.strip()]
    key = (round(lat, 3), round(lng, 3), int(radius_m // 100), tuple(kinds), tuple(sorted(terms)))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    errors = []
    for source in (lambda: nearby_photon(lat, lng, radius_m, kinds, terms),
                   lambda: nearby_overpass(lat, lng, radius_m, kinds)):
        try:
            places = source()
            _cache[key] = (time.monotonic(), places)
            return places
        except Exception as e:
            errors.append(str(e))
    raise PlacesError(f"Couldn't reach the places services right now ({'; '.join(errors)}). Try again in a moment.")
