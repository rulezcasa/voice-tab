"""Qwen's two jobs in a hangout search. It never invents a place: places come only from OpenStreetMap.

  search_terms(): the note ("somewhere quiet with vegetarian food") -> a few short search words per place kind,
                  so the places search can look for the right things ("vegetarian", "vegan", "tea").
  pick():         from the real candidates (already filtered by everyone's time and budget), choose the best few
                  for this group and say why in a few words. Any id not in the list is thrown away.

Both return None on any problem, and the caller falls back to plain code ranking.
"""
import json
import re

from src.model.sl_client import MODELS, sie

MAX_TERMS = 4


def _chat(system: str, user: str, max_tokens: int) -> str:
    r = sie.chat_completions(MODELS["generate"], [{"role": "system", "content": system}, {"role": "user", "content": user}],
                             temperature=0, max_tokens=max_tokens)
    return r["choices"][0]["message"].get("content") or ""


def _json(text: str):
    """The first JSON object in the reply (models sometimes wrap it in prose or ``` fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def search_terms(note: str, kinds: list[str]) -> list[tuple[str, str]] | None:
    """[(word, kind)] to search for, e.g. [("vegetarian", "restaurant"), ("tea", "cafe")]."""
    if not note.strip():
        return []
    system = (
        "You turn a group's wish for a meetup place into short search words for a map search that matches words in "
        "place NAMES. Give single words a place name would contain: cuisines (thai, ramen, taqueria, pizza, sushi), "
        "food styles (vegan, vegetarian, bbq), drinks (tea, boba, wine, brewery), or activities (bowling, karaoke). "
        f"Each word goes with one kind from {kinds}. At most {MAX_TERMS} words. Skip vague words like quiet, nice, "
        'cheap. Reply with JSON only: {"terms": [{"word": "...", "kind": "..."}]}'
    )
    try:
        data = _json(_chat(system, f"Kinds: {kinds}\nWish: {note.strip()}", 200)) or {}
        out = []
        for t in data.get("terms", [])[:MAX_TERMS]:
            word, kind = str(t.get("word", "")).strip().lower(), t.get("kind")
            if kind in kinds and re.fullmatch(r"[a-z][a-z\- ]{1,20}", word):
                out.append((word, kind))
        return out
    except Exception:
        return None


def pick(candidates: list[dict], members: list, note: str, n: int) -> list[tuple[str, str]] | None:
    """[(place id, why)] chosen from candidates, best first. Ids not in the list are dropped."""
    if not candidates:
        return []
    names = {m.person_id: ("you" if m.is_me else m.name.split()[0]) for m in members}
    lines = []
    for i, c in enumerate(candidates, 1):
        trips = ", ".join(f"{names[pid]} {mins} min" for pid, mins in c["minutes"].items())
        found = f"; matched search: {', '.join(c['found_by'])}" if c.get("found_by") else ""
        lines.append(f'{i}. id={c["id"]} | {c["name"]} | {c["label"]} | ~${c["per_person"]} pp (estimate) | {trips}{found}')
    system = (
        f"You help a group of friends pick where to meet. Choose up to {n} places ONLY from the numbered list, best "
        "first. Prefer fair trips (nobody travels much longer than the rest), short trips, and places that fit the "
        "group's wish. For each, write a reason of at most 12 words for the group, mentioning the wish if it fits. "
        "Don't mention prices as facts (they are estimates) and don't invent details not in the list. "
        'Reply with JSON only: {"picks": [{"id": "...", "why": "..."}]}'
    )
    user = f"Wish: {note.strip() or '(none)'}\nPlaces:\n" + "\n".join(lines)
    try:
        data = _json(_chat(system, user, 500)) or {}
        valid = {c["id"] for c in candidates}
        out, seen = [], set()
        for p in data.get("picks", []):
            pid, why = str(p.get("id", "")), " ".join(str(p.get("why", "")).split())[:120]
            if pid in valid and pid not in seen and why:
                seen.add(pid)
                out.append((pid, why))
        return out[:n] or None
    except Exception:
        return None
