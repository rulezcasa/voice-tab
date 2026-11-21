"""Multi-agent meetup negotiation: a coordinator agent and one personal agent per member, talking in rounds.

Who knows what:
  coordinator     only what personal agents chose to share: free/busy windows, a ~1 km area, radius,
                  travel mode, interests. Plus public venue info and the group's past spending per venue kind.
  personal agent  its own person's full private profile (exact home, budget, calendar). Never shared.

Each round:
  1. the coordinator (Qwen) proposes ONE place and time from the candidates, using only shared info and the
     public replies so far (who declined, and their hints: cheaper / closer / different kind)
  2. every personal agent (Qwen, separately, with only its own private context) accepts or declines in a short
     message; code makes sure the decision matches that person's real limits, and a leak guard blocks private
     details from the message
  3. all accept -> agreed. Otherwise the place is crossed off and the next round starts (max MAX_ROUNDS)

Everything said is kept in `transcript` (public). What each agent knew and decided privately is kept in
`audit` (for Firedrill only; the API strips it).
"""
import json
import re
from datetime import date, datetime, time, timedelta

from src.agents import personal
from src.core.meetups import coordinator as plan
from src.core.meetups import geo, weather as weather_mod
from src.core.people import personal_agent as rules

MAX_ROUNDS = 4


def _json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def model_chat():
    """chat(system, user) on Qwen via SIE, counting calls."""
    from src.model.sl_client import MODELS, sie

    def chat(system: str, user: str) -> str:
        chat.calls += 1
        r = sie.chat_completions(MODELS["generate"], [{"role": "system", "content": system},
                                                      {"role": "user", "content": user}],
                                 temperature=0, max_tokens=250)
        return r["choices"][0]["message"].get("content") or ""
    chat.calls = 0
    return chat


# ---------- the coordinator's choice ----------

def _fallback_pick(pool: list[dict], rejected: list[dict], center) -> dict | None:
    """Code choice when the model fails: follow the last round's hints, else the next best candidate."""
    left = [v for v in pool if v["id"] not in {r["venue"]["id"] for r in rejected}]
    if not left:
        return None
    if rejected:
        last = rejected[-1]
        hints = last["hints"]
        dist = lambda v: geo.haversine_mi(center, (float(v["lat"]), float(v["lng"])))
        if "cheaper" in hints:
            cheaper = [v for v in left if float(v["price_pp"]) < float(last["venue"]["price_pp"])]
            left = cheaper or left
        if "closer" in hints:
            left = sorted(left, key=dist)
        if "different_kind" in hints:
            left = [v for v in left if v["kind"] != last["venue"]["kind"]] or left
    return left[0]


def coordinator_pick(pool: list[dict], rejected: list[dict], shared: list[dict], activity: str | None,
                     slot: tuple[datetime, datetime], center, chat) -> tuple[dict | None, str, bool]:
    """(venue, message to the group, chosen_by_model). The model only sees shared and public facts."""
    left = [v for v in pool if v["id"] not in {r["venue"]["id"] for r in rejected}]
    if not left:
        return None, "", False
    lines = [f'id={v["id"]} | {v["name"]} | {v["kind"]} | {"indoor" if v["indoor"] else "outdoor"} | '
             f'listed ~${float(v["price_pp"]):.0f}/pp{" (what this group really paid last time)" if v.get("learned") else ""} | '
             f'{geo.haversine_mi(center, (float(v["lat"]), float(v["lng"]))):.1f} mi from the middle' for v in left]
    history = [f'Round {i + 1}: {r["venue"]["name"]} declined by {", ".join(r["decliners"])}; hints: {", ".join(sorted(set(r["hints"]))) or "none"}'
               for i, r in enumerate(rejected)]
    interests = sorted({i for c in shared for i in c["interests"]})
    system = (
        "You coordinate a group meetup. You do NOT know anyone's budget or home; personal agents check proposals "
        "privately and reply. Propose ONE place from the list. Use the group's interests and the hints from "
        "earlier rounds (cheaper = pick a lower-priced place, closer = nearer the middle, different_kind = a "
        "different kind of place). Write one short friendly message to the group (max 25 words) with the place "
        'and time. Reply with JSON only: {"venue_id": <id>, "message": "..."}'
    )
    user = (f"Group: {', '.join(c['name'] for c in shared)}. Interests: {', '.join(interests) or 'none'}.\n"
            f"Wish: {activity or 'none'}\nTime: {slot[0]:%a %b %d %-I:%M %p} to {slot[1]:%-I:%M %p}\n"
            f"Earlier rounds:\n{chr(10).join(history) or 'none'}\nPlaces:\n" + "\n".join(lines))
    try:
        data = _json(chat(system, user)) or {}
        by_id = {str(v["id"]): v for v in left}
        v = by_id.get(str(data.get("venue_id")))
        msg = " ".join(str(data.get("message", "")).split())[:240]
        if v and msg:
            return v, msg, True
    except Exception:
        pass
    v = _fallback_pick(pool, rejected, center)
    return v, (f"How about {v['name']} on {slot[0]:%a} at {slot[0]:%-I %p}?" if v else ""), False


# ---------- the negotiation ----------

def _apply(change: dict, st: dict, out: dict, rnd: int) -> bool:
    """Apply one change to the negotiation state. Returns True if the coordinator must re-plan.

    change = {"person_id": id, and one of: "leaves": true | "budget": "45" | "radius_mi": 6 |
              "travel_mode": "drive" | "busy": [["2026-11-21T12:00", "2026-11-21T18:00"], ...]}
    Leaving is public (the group sees it). Budget, radius, mode and calendar changes are private: only that
    person's agent sees them; the coordinator only notices that person's shared free time changed.
    """
    pid = change["person_id"]
    name = st["names"].get(pid, str(pid))
    if pid not in st["profiles"]:
        return False
    note = {"round": rnd, "change": {k: v for k, v in change.items() if k != "person_id"}}
    out["audit"]["private"].setdefault(name, []).append(note)
    if change.get("leaves"):
        st["members"] = [m for m in st["members"] if m["id"] != pid]
        out["transcript"].append({"round": rnd, "from": name, "to": "group", "text": "Can't make it anymore, sorry!",
                                  "event": "left"})
        return True
    replan = False
    for key, field in (("budget", "meetup_budget"), ("radius_mi", "max_radius_mi"), ("travel_mode", "travel_mode")):
        if key in change:
            st["profiles"][pid][field] = change[key]
            replan |= key != "budget"            # radius and mode are shared; the budget never is
    if change.get("busy"):
        st["busy"][pid] = st["busy"][pid] + [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in change["busy"]]
        replan = True
    return replan


def _plan_round(st: dict, out: dict, data, activity, min_hours, weather) -> str | None:
    """(Re)compute what the coordinator works from: shared constraints, the time slot and the venue pool.
    Returns a stop status ("no_time", "no_venue", "no_people") or None to continue."""
    members = st["members"]
    if len(members) < 2:
        out["reason"] = "Fewer than two people left in the plan"
        return "no_people"
    shared = [rules.constraints_from(st["profiles"][m["id"]], st["busy"][m["id"]], st["win"][0], st["win"][1])
              for m in members]
    st["shared"] = shared
    out["shared"] = shared
    slots = plan.overlap([plan._parse(c["free"]) for c in shared], timedelta(hours=min_hours))
    if not slots:
        out["reason"] = f"No {min_hours:g}-hour window where all {len(members)} are free"
        return "no_time"
    st["slot"] = (slots[0][0], slots[0][0] + timedelta(hours=min_hours))
    st["center"], radius = plan.search_area(shared)
    pool = plan.apply_learned_costs(plan.pick_candidates(st["venues"], shared, st["center"], radius, st["ranked"]),
                                    st["real_pp"])
    wx = {v["id"]: weather(float(v["lat"]), float(v["lng"]), st["slot"][0]) for v in pool if not v["indoor"]}
    st["pool"] = [v for v in pool if v["indoor"] or wx[v["id"]]["rain_prob"] <= weather_mod.RAINY]
    if not st["pool"]:
        out["reason"] = f"No venues within {radius:g} miles of the group's middle"
        return "no_venue"
    return None


def negotiate(group: dict, start: date, end: date, *, activity: str | None = None, min_hours: float = 2,
              max_rounds: int = MAX_ROUNDS, probe: str | None = None, changes: list[dict] | None = None,
              chat=None, data=None, now: datetime | None = None, weather=weather_mod.forecast) -> dict:
    """Run the negotiation for `group` ({"id", "name", "members": [{"id", "name"}]}) between start and end dates.

    data: object with profile(pid), busy(pid, s, e), busy_labels(pid, s, e), venues(), real_cost_per_person(gid),
          venues_by_meaning(text)  (src.core.meetups.repo in the app; a fake in tests)
    probe: extra text appended to every proposal (Firedrill uses it to try to make agents leak).
    changes: things that happen to people, each with "when": "before" or a round number (applied after that
             round), see _apply(). Firedrill uses these for drop-outs, budget changes and new calendar entries.
    """
    if data is None:
        from src.core.meetups import repo as data
    chat = chat or model_chat()
    calls0 = getattr(chat, "calls", 0)
    now = now or datetime.now()
    win = (max(datetime.combine(start, time()), now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)),
           datetime.combine(end + timedelta(days=1), time()))
    members = list(group["members"])
    out = {"group": {"id": group["id"], "name": group["name"]}, "status": None, "reason": None, "agreed": None,
           "rounds": 0, "transcript": [], "shared": [], "members": [m["name"] for m in members],
           "audit": {"private": {}, "leaks": [], "model_replies": 0, "ids": {m["name"]: m["id"] for m in members}}}

    st = {"members": members, "win": win, "names": {m["id"]: m["name"] for m in members},
          "profiles": {m["id"]: dict(data.profile(m["id"])) for m in members},
          "busy": {m["id"]: list(data.busy(m["id"], *win)) for m in members},
          "labels": {m["id"]: data.busy_labels(m["id"], *win) for m in members},
          "venues": data.venues(), "ranked": None, "real_pp": {}}
    if activity:
        try:
            st["ranked"] = data.venues_by_meaning(activity)
        except Exception:
            pass
    try:
        st["real_pp"] = data.real_cost_per_person(group["id"])
    except Exception as e:  # don't hide it: a silent failure here once turned off the learned prices entirely
        out.setdefault("notes", []).append(f"learned prices unavailable ({type(e).__name__}); using listed prices")

    pending = list(changes or [])
    for c in [c for c in pending if c.get("when") == "before"]:
        _apply(c, st, out, 0)
    pending = [c for c in pending if c.get("when") != "before"]

    stop = _plan_round(st, out, data, activity, min_hours, weather)
    if stop:
        return _stop(out, stop, chat, calls0)

    rejected: list[dict] = []
    for rnd in range(1, max_rounds + 1):
        venue, msg, by_model = coordinator_pick(st["pool"], rejected, st["shared"], activity, st["slot"], st["center"], chat)
        if not venue:
            break
        if probe:
            msg = f"{msg} {probe}"
        out["rounds"] = rnd
        slot = st["slot"]
        out["transcript"].append({"round": rnd, "from": "coordinator", "to": "group", "text": msg,
                                  "venue": venue["name"], "chosen_by_model": by_model})
        proposal = {"venue": venue, "starts_at": slot[0].isoformat(), "message": msg}
        decliners, hints = [], []
        n = len(st["members"])
        for m in st["members"]:
            pid, name = m["id"], st["names"][m["id"]]
            r = personal.reply(name, st["profiles"][pid], st["labels"][pid], proposal, n, chat)
            out["transcript"].append({"round": rnd, "from": name, "to": "coordinator",
                                      "text": r["message"], "decision": r["decision"], "hint": r["hint"]})
            out["audit"]["private"].setdefault(name, []).append(
                {"round": rnd, "venue": venue["name"], **r["facts"], "decision": r["decision"]})
            out["audit"]["model_replies"] += r["model"]
            out["audit"]["leaks"] += [{"round": rnd, "agent": name, "leak": l} for l in r["leaks"]]
            if r["decision"] == "decline":
                decliners.append(name)
                hints.append(r["hint"])
        if not decliners:
            out.update(status="agreed", members=[m["name"] for m in st["members"]],
                       agreed={"venue": {**{k: venue[k] for k in ("id", "name", "kind", "indoor", "description")},
                                         "lng": float(venue["lng"]), "lat": float(venue["lat"])},
                               "starts_at": slot[0].isoformat(), "ends_at": slot[1].isoformat()})
            out["transcript"].append({"round": rnd, "from": "coordinator", "to": "group",
                                      "text": f"Everyone's in: {venue['name']}, {slot[0]:%a %b %d %-I:%M %p}."})
            return _finish(out, chat, calls0)
        rejected.append({"venue": venue, "decliners": decliners, "hints": hints})

        due = [c for c in pending if c.get("when") == rnd]
        pending = [c for c in pending if c.get("when") != rnd]
        if due and any([_apply(c, st, out, rnd) for c in due]):
            before = len(st["members"])
            stop = _plan_round(st, out, data, activity, min_hours, weather)
            if stop:
                return _stop(out, stop, chat, calls0, rnd)
            rejected = [r for r in rejected if set(r["decliners"]) & set(st["names"][m["id"]] for m in st["members"])]
            out["transcript"].append({"round": rnd, "from": "coordinator", "to": "group", "event": "replanned",
                                      "text": f"Plans changed, re-planning for {len(st['members'])} "
                                              f"({', '.join(st['names'][m['id']] for m in st['members'])})."})

    out.update(status="no_agreement", members=[m["name"] for m in st["members"]],
               reason=f"No place everyone accepted after {out['rounds']} round{'s' if out['rounds'] != 1 else ''}")
    out["transcript"].append({"round": out["rounds"], "from": "coordinator", "to": "group", "text": out["reason"]})
    return _finish(out, chat, calls0)


def _stop(out: dict, status: str, chat, calls0: int, rnd: int = 0) -> dict:
    out["status"] = status
    out["transcript"].append({"round": rnd, "from": "coordinator", "to": "group", "text": out["reason"]})
    return _finish(out, chat, calls0)


def _finish(out: dict, chat, calls0: int) -> dict:
    out["model_calls"] = getattr(chat, "calls", 0) - calls0
    return out


def public(result: dict) -> dict:
    """What the API may return: everything except the private audit."""
    return {k: v for k, v in result.items() if k != "audit"}


# ---------- recent negotiations, so each person can see what their own agent did ----------

_LOG: list[dict] = []      # newest last; in memory (lost on restart), enough for a demo
LOG_MAX = 50


def remember(result: dict) -> int:
    nid = (_LOG[-1]["id"] + 1) if _LOG else 1
    _LOG.append({"id": nid, "at": datetime.now().isoformat(timespec="seconds"), "result": result})
    del _LOG[:-LOG_MAX]
    return nid


def for_person(person_id: int, limit: int = 10) -> list[dict]:
    """Negotiations this person's agent took part in: the public conversation plus ONLY their own private notes."""
    out = []
    for entry in reversed(_LOG):
        r = entry["result"]
        name = next((n for n, i in r["audit"].get("ids", {}).items() if i == person_id), None)
        if name is None:
            continue
        out.append({"id": entry["id"], "at": entry["at"], "you": name, **public(r),
                    "your_agent": r["audit"]["private"].get(name, [])})
        if len(out) == limit:
            break
    return out
