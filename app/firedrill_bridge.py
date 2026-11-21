"""Firedrill JSONL bridge for one-shot meetup negotiation requests.

The bridge is intentionally small: Firedrill owns the request lifecycle and this
process owns only the translation from JSONL input to the existing app agents.
Logs go to stderr; stdout carries a readiness record then one response per request.
"""
from __future__ import annotations

import json
import logging
import sys
import os
from datetime import date, datetime, timedelta

os.environ["SS_DATABASE"] = "tab_drill"
os.environ["WEATHER_STUB"] = "1"

from src import config  # noqa: F401  (loads the app environment before imports)
from src.agents import ask, live, negotiator
from src.core.expenses import ledger
from src.core.meetups import repo


logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    return date.fromisoformat(value)


def _run_live(request: dict, group: dict, chat) -> dict:
    message = request["message"]
    understood = ask.understand(message, ledger.today(), chat)
    me = next((m["id"] for m in group["members"] if m.get("is_me")), None)
    if me is None:
        raise ValueError("group has no organiser")

    clock = [0.0]
    session = live.start(
        group,
        understood["start"],
        understood["end"],
        activity=understood["activity"],
        bots=True,
        seed=int(request.get("seed", 1000)),
        play_as=me,
        hands_off=True,
        opening=message,
        chat=chat,
        clock=lambda: clock[0],
        reply_window_s=int(request.get("reply_window_s", 120)),
    )
    for _ in range(60):
        clock[0] += 13
        session.tick()
        if session.out["status"] != "waiting":
            break
    result = dict(session.out)
    result.update(
        understood=understood,
        players=session.public()["players"],
        me=next(m["name"] for m in group["members"] if m["id"] == me),
        model_calls=chat.calls,
        seed=session.seed,
    )
    return result


def _run_direct(request: dict, group: dict, chat) -> dict:
    today = ledger.today()
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    if "days" in request:
        start, end = [saturday + timedelta(days=int(d)) for d in request["days"]]
    else:
        start = _date(request["start"], "start")
        end = _date(request.get("end", request["start"]), "end")
    ids = {m["name"]: m["id"] for m in group["members"]}
    changes = [{**{k: v for k, v in c.items() if k != "person"}, "person_id": ids[c["person"]]} for c in request.get("changes", [])]
    result = negotiator.negotiate(
        group,
        start,
        end,
        activity=request.get("activity"),
        min_hours=float(request.get("min_hours", 2)),
        max_rounds=int(request.get("max_rounds", negotiator.MAX_ROUNDS)),
        probe=request.get("probe"),
        changes=changes,
        chat=chat,
    )
    from drills import checks
    win = (datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time()))
    profiles = {name: repo.profile(pid) for name, pid in ids.items()}
    ctx = {"profiles": profiles, "labels": {name: repo.busy_labels(pid, *win) for name, pid in ids.items()},
           "changed": {c["person"]: {**profiles[c["person"]], "meetup_budget": c["budget"]} for c in request.get("changes", []) if "budget" in c}, "saturday": saturday}
    names = ["no_leaks_in_messages", "coordinator_saw_only_shared"]
    if result["status"] == "agreed":
        names.append("agreed_fits_everyone")
    result["verification"] = {name: bool(checks.ALL[name](request, result, ctx)[0]) for name in names}
    result["verification"]["private_limits_applicable"] = result["status"] == "agreed"
    proposals = [t["venue"] for t in result["transcript"] if t.get("venue")]
    result["verification"]["no_repeated_venue"] = len(proposals) == len(set(proposals))
    result["scenario_events_applied"] = [{"round": f["round"], "person": name, "fields": sorted(f["change"])} for name, facts in result["audit"]["private"].items() for f in facts if "change" in f]
    return result


def handle(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("input must be an object")
    group_name = request.get("group")
    if not isinstance(group_name, str) or not group_name.strip():
        raise ValueError("input.group is required")
    group = repo.group_by_name(group_name)
    chat = negotiator.model_chat()
    result = _run_live(request, group, chat) if "message" in request else _run_direct(request, group, chat)
    return negotiator.public(result)


def main() -> None:
    # Firedrill hashes this line to attest startup before admitting a drill.
    # Emit only after configuration and agent imports have succeeded.
    print('{"ready":"tab-negotiation-bridge.v1"}', flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            envelope = json.loads(line)
            request_id = envelope.get("id")
            result = handle(envelope.get("input", envelope))
            reply = {"id": request_id, "output": result}
        except Exception as exc:  # one bad request must not kill the bridge
            logging.error("request failed: %s", type(exc).__name__)
            reply = {"id": request_id, "error": {"type": type(exc).__name__, "message": "Negotiation failed; inspect local configuration."}}
        sys.stdout.write(json.dumps(reply, default=str, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
