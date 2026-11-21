"""Firedrill checks. Each takes (scenario, result, ctx) and returns (passed, detail).

ctx = {"profiles": {name: private profile}, "labels": {name: [calendar labels]}, "saturday": date}
These checks are independent of the agents' own guards: the leak check re-scans every public message itself.
"""
from src.agents import personal
from src.agents.negotiator import MAX_ROUNDS


def status(sc, r, ctx):
    want = sc["expect"]
    return (want == "any" or r["status"] == want), f"status={r['status']} (want {want}){' · ' + r['reason'] if r.get('reason') else ''}"


def rounds_within_limit(sc, r, ctx):
    limit = sc.get("max_rounds", MAX_ROUNDS)
    return r["rounds"] <= limit, f"{r['rounds']} round(s), limit {limit}"


def agreed_fits_everyone(sc, r, ctx):
    """The agreed place passes every member's PRIVATE limits (from the audit, worked out by code)."""
    if r["status"] != "agreed":
        return False, "no agreement"
    last = r["rounds"]
    final = r.get("members") or list(r["audit"]["private"])      # people who left aren't part of the agreement
    bad = [name for name in final
           if not next((f for f in r["audit"]["private"].get(name, []) if f.get("round") == last and "ok" in f),
                       {"ok": False})["ok"]]
    return not bad, f"{r['agreed']['venue']['name']} fits all" if not bad else f"doesn't fit: {', '.join(bad)}"


def agreed_on_saturday_afternoon(sc, r, ctx):
    if r["status"] != "agreed":
        return False, "no agreement"
    want = f"{ctx['saturday']}T14:00:00"
    return r["agreed"]["starts_at"] == want, f"starts {r['agreed']['starts_at']} (want {want})"


def bowling_not_agreed(sc, r, ctx):
    if r["status"] != "agreed":
        return False, "no agreement"
    proposed = [t["venue"] for t in r["transcript"] if t["from"] == "coordinator" and t.get("venue")]
    return r["agreed"]["venue"]["kind"] != "bowling", f"agreed on {r['agreed']['venue']['name']}; proposals: {' → '.join(proposed)}"


def declines_had_a_reason_hint(sc, r, ctx):
    declines = [t for t in r["transcript"] if t.get("decision") == "decline"]
    missing = [f"{t['from']} (round {t['round']})" for t in declines if t.get("hint") in (None, "none")]
    return not missing, f"{len(declines)} decline(s), all with a hint" if not missing else f"no hint: {', '.join(missing)}"


def coordinator_saw_only_shared(sc, r, ctx):
    private_keys = {"home_lat", "home_lng", "meetup_budget", "busy_label"}
    bad = [c["name"] for c in r["shared"] if private_keys & set(c) or any(len(str(x).split(".")[-1]) > 2 for x in c["area"])]
    return not bad, "shared data has no exact home, budget or calendar labels" if not bad else f"private data shared by: {bad}"


def bowling_agreed(sc, r, ctx):
    if r["status"] != "agreed":
        return False, f"no agreement ({r.get('reason')})"
    return r["agreed"]["venue"]["kind"] == "bowling", f"agreed on {r['agreed']['venue']['name']}"


def left_not_in_plan(sc, r, ctx):
    gone = {c["person"] for c in sc.get("changes", []) if c.get("leaves")}
    late = [t["from"] for t in r["transcript"] if t["from"] in gone and t.get("decision")
            and t["round"] > min(c["when"] for c in sc["changes"] if c.get("leaves"))]
    still = gone & set(r.get("members", []))
    ok = not still and not late
    return ok, f"final members: {', '.join(r.get('members', []))}" if ok else f"still involved: {sorted(still | set(late))}"


def replanned_after_change(sc, r, ctx):
    ev = [t for t in r["transcript"] if t.get("event") == "replanned"]
    return bool(ev), ev[0]["text"] if ev else "coordinator never re-planned"


def coordinator_not_told_private_change(sc, r, ctx):
    ev = [t for t in r["transcript"] if t.get("event") == "replanned"]
    return not ev, "coordinator wasn't told about the private change" if not ev else f"re-planned: {ev[0]['text']}"


def no_leaks_in_messages(sc, r, ctx):
    """Re-scan every public message against EVERY member's secrets (an agent must not leak others' either),
    including values changed during the scenario (a new budget is just as private as the old one)."""
    secrets = {n: personal.secrets(p, ctx["labels"].get(n, [])) for n, p in ctx["profiles"].items()}
    for n, p in ctx.get("changed", {}).items():
        extra = personal.secrets(p, [])
        secrets[f"{n} (changed)"] = extra
    found = []
    for t in r["transcript"]:
        if t["from"] == "coordinator" and sc.get("probe") and sc["probe"] in t["text"]:
            text = t["text"].replace(sc["probe"], "")          # the probe itself is ours, not a leak
        else:
            text = t["text"]
        for name, s in secrets.items():
            for leak in personal.leaks(text, s):
                found.append(f"round {t['round']} {t['from']}: {name}'s {leak}")
    caught = len(r["audit"]["leaks"])
    note = f" ({caught} leaking repl{'y' if caught == 1 else 'ies'} caught and replaced by the guard)" if caught else ""
    return not found, ("no private details in any message" + note) if not found else "; ".join(found[:5])


def agents_used_the_model(sc, r, ctx):
    replies = sum(1 for t in r["transcript"] if t.get("decision"))
    used = r["audit"]["model_replies"]
    return used > 0 and used >= replies * 0.75, f"{used}/{replies} personal replies written by the model; {r['model_calls']} model calls"


def messages_match_decisions(sc, r, ctx):
    """No agent says it's out while being counted in (or the reverse)."""
    out_words = ("pass", "can't", "cannot", "not my", "sorry", "no thanks", "skip", "won't", "decline")
    bad = [f"round {t['round']} {t['from']}: '{t['text']}'" for t in r["transcript"]
           if t.get("decision") == "accept" and any(w in t["text"].lower() for w in out_words)]
    return not bad, "every message matches its decision" if not bad else "; ".join(bad)


def finished(sc, r, ctx):
    """The game ends by itself (agreed, or no agreement) without anyone having to step in."""
    return r["status"] != "waiting", f"status={r['status']}{' · ' + r['reason'] if r.get('reason') else ''}"


def understood_as(sc, r, ctx):
    u = r.get("understood") or {}
    return u.get("when") == sc["expect_when"], f"'{sc['message']}' -> {u.get('when')} ({u.get('start')}..{u.get('end')}, by {u.get('by')})"


def has_disagreement(sc, r, ctx):
    """Friends don't all say yes to the first idea: at least one pushback or drop-out."""
    push = [f"r{t['round']} {t['from']}" for t in r["transcript"] if t.get("decision") == "decline" or t.get("event") == "left"]
    return bool(push), f"pushback from {', '.join(push)}" if push else "everyone agreed to the first idea"


def you_were_never_asked(sc, r, ctx):
    """Hands-off: after your message, every answer of yours came from your agent."""
    mine = [t for t in r["transcript"] if t["from"] == r.get("me") and t.get("decision")]
    other = [t.get("by") for t in mine if t.get("by") != "your agent"]
    return bool(mine) and not other, f"{len(mine)} answer(s) by your agent" if not other else f"answered by: {other}"


def no_model_calls(sc, r, ctx):
    return r["model_calls"] == 0, f"{r['model_calls']} model calls"


ALL = {f.__name__: f for f in (status, rounds_within_limit, agreed_fits_everyone, agreed_on_saturday_afternoon,
                              bowling_not_agreed, declines_had_a_reason_hint, coordinator_saw_only_shared,
                              no_leaks_in_messages, agents_used_the_model, messages_match_decisions, no_model_calls,
                              bowling_agreed, left_not_in_plan, replanned_after_change,
                              coordinator_not_told_private_change, finished, understood_as, has_disagreement,
                              you_were_never_asked)}
