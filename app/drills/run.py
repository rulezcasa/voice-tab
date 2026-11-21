"""Firedrill: run multi-agent meetup negotiations against a seeded database and check every outcome and message.

    python -m scripts.reset_db --db tab_drill && python -m scripts.seed --db tab_drill   # once
    python -m drills.run --db tab_drill                     # all scenarios (real model calls)
    python -m drills.run --db tab_drill --only crew-bowling

Writes drills/results/latest.json (scenarios, transcripts, checks). Exit code 1 if any check fails.
"""
import argparse
import json
import sys
from pathlib import Path

from scripts._db import pick_db

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--only", action="append", help="run just this scenario (repeatable)")
args = pick_db(parser)

import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from src import config  # noqa: E402
from src.agents import negotiator  # noqa: E402
from src.core.expenses import ledger  # noqa: E402
from src.core.meetups import repo  # noqa: E402

from drills import checks  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE / "results"


def coming_saturday(today):
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def to_changes(sc: dict, group: dict, sat) -> list[dict]:
    """Scenario changes (by name, busy as day offsets from Saturday) -> negotiator changes (by id, ISO times)."""
    ids = {m["name"]: m["id"] for m in group["members"]}
    out = []
    for c in sc.get("changes", []):
        ch = {k: v for k, v in c.items() if k != "person"}
        ch["person_id"] = ids[c["person"]]
        if isinstance(c.get("busy"), dict):
            day = sat + timedelta(days=c["busy"]["day"])
            ch["busy"] = [[f"{day}T{c['busy']['from']:02d}:00:00", f"{day}T{c['busy']['to']:02d}:00:00"]]
        out.append(ch)
    return out


def play_live(sc: dict, group: dict, chat, seed: int) -> tuple[dict, tuple]:
    """One hands-off game exactly as the app runs it: your casual message, bots for everyone else, your agent
    answering for you. The clock is fast-forwarded instead of waiting for the bots' "thinking" delays."""
    from src.agents import ask, live
    calls0 = chat.calls
    u = ask.understand(sc["message"], ledger.today(), chat)
    me = next(m["id"] for m in group["members"] if m.get("is_me"))
    t = [0.0]
    s = live.start(group, u["start"], u["end"], activity=u["activity"], bots=True, seed=seed, play_as=me,
                   hands_off=True, opening=sc["message"], chat=chat, clock=lambda: t[0], reply_window_s=120)
    for _ in range(60):
        t[0] += 13
        s.tick()
        if s.out["status"] != "waiting":
            break
    r = dict(s.out)
    r.update(understood=u, players=s.public()["players"], me=next(m["name"] for m in group["members"] if m["id"] == me),
             model_calls=chat.calls - calls0, seed=s.seed)
    win = (datetime.combine(u["start"], datetime.min.time()), datetime.combine(u["end"] + timedelta(days=1), datetime.min.time()))
    return r, win


def main() -> None:
    os.environ.setdefault("WEATHER_STUB", "1")    # stable weather: the drill tests the agents, not the forecast
    spec = json.loads((HERE / "scenarios.json").read_text())
    scenarios = [s for s in spec["scenarios"] if not args.only or s["name"] in args.only]
    today = ledger.today()
    sat = coming_saturday(today)
    chat = negotiator.model_chat()
    print(f"Firedrill on '{config.SS['database']}', today {today}, coming Saturday {sat}\n")

    report, failed = [], 0
    for sc in scenarios:
        group = repo.group_by_name(sc["group"])
        if sc.get("engine") == "live":
            profiles = {m["name"]: repo.profile(m["id"]) for m in group["members"]}
            all_ok, games = True, []
            for g in range(sc.get("games", 1)):
                r, win = play_live(sc, group, chat, seed=sc.get("seed", 1000) + g)
                ctx = {"profiles": profiles, "changed": {}, "saturday": sat,
                       "labels": {m["name"]: repo.busy_labels(m["id"], *win) for m in group["members"]}}
                results = [{"check": n, "passed": bool(ok), "detail": d}
                           for n in sc["checks"] for ok, d in [checks.ALL[n](sc, r, ctx)]]
                bad = sum(not c["passed"] for c in results)
                failed += bad
                all_ok &= not bad
                print(f"{'PASS' if not bad else 'FAIL'}  {sc['name']} game {g + 1}  (seed {r['seed']}, {r['status']}, "
                      f"{r['rounds']} round(s), {r['model_calls']} model calls; {', '.join(f'{k}: {v}' for k, v in r['players'].items())})")
                for t in r["transcript"]:
                    tag = f" [{t['decision']} · {t.get('by')}]" if t.get("decision") else ""
                    print(f"      r{t['round']} {t['from']:>11}: {t['text']}{tag}")
                for c in results:
                    print(f"   {'✓' if c['passed'] else '✗'} {c['check']}: {c['detail']}")
                print()
                games.append({"seed": r["seed"], "result": negotiator.public(r), "checks": results})
            report.append({"scenario": sc, "games": games, "checks": [c for gm in games for c in gm["checks"]]})
            continue
        start, end = sat + timedelta(days=sc["days"][0]), sat + timedelta(days=sc["days"][1])
        win = (datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time()))
        r = negotiator.negotiate(group, start, end, activity=sc.get("activity"), probe=sc.get("probe"),
                                 max_rounds=sc.get("max_rounds", negotiator.MAX_ROUNDS),
                                 changes=to_changes(sc, group, sat), chat=chat)
        profiles = {m["name"]: repo.profile(m["id"]) for m in group["members"]}
        changed = {c["person"]: {**profiles[c["person"]], "meetup_budget": c["budget"]}
                   for c in sc.get("changes", []) if "budget" in c}
        ctx = {"profiles": profiles, "changed": changed,
               "labels": {m["name"]: repo.busy_labels(m["id"], *win) for m in group["members"]},
               "saturday": sat}
        results = []
        for name in sc["checks"]:
            ok, detail = checks.ALL[name](sc, r, ctx)
            results.append({"check": name, "passed": bool(ok), "detail": detail})
        n_bad = sum(not c["passed"] for c in results)
        failed += n_bad
        print(f"{'PASS' if not n_bad else 'FAIL'}  {sc['name']}  ({r['status']}, {r['rounds']} round(s), {r['model_calls']} model calls)")
        for t in r["transcript"]:
            tag = f" [{t['decision']}{', ' + t['hint'] if t.get('hint') not in (None, 'none') else ''}]" if t.get("decision") else ""
            print(f"      r{t['round']} {t['from']:>11}: {t['text']}{tag}")
        for c in results:
            print(f"   {'✓' if c['passed'] else '✗'} {c['check']}: {c['detail']}")
        print()
        report.append({"scenario": sc, "result": negotiator.public(r), "leaks_caught": r["audit"]["leaks"],
                       "checks": results})

    total = sum(len(x["checks"]) for x in report)
    summary = {"ran_at": datetime.now().isoformat(timespec="seconds"), "database": config.SS["database"],
               "scenarios": len(report), "checks": total, "failed": failed, "model_calls": chat.calls}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps({"summary": summary, "runs": report}, indent=2, default=str))
    print(f"{total - failed}/{total} checks passed across {len(report)} scenario(s); {chat.calls} model calls. "
          f"Saved drills/results/latest.json")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
