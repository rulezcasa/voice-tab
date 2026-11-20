"""Live negotiation: the agents draft, the real people decide.

Same coordinator and personal agents as src/agents/negotiator.py, but nothing a personal agent writes is sent
until its person has seen it on their own private page:

  1. the coordinator proposes a place and time (Qwen, shared info only)
  2. each personal agent DRAFTS a reply from its person's private details (Qwen + code facts)
  3. each person, on their own device, approves the draft, changes it (accept / decline + own words + hint),
     or says they can't come at all
  4. anyone who hasn't answered when the reply window closes is answered by their agent's draft, marked as such
     (the organiser can also close the window early)
  5. everyone in -> agreed. Otherwise the place is crossed off and the coordinator proposes again (max rounds).

The session lives in memory and moves forward on requests (no background threads): every read first checks
whether the reply window has passed. People's drafts and private reasons are only ever returned to that person.
"""
import itertools
import random
import threading
import time
from datetime import date, datetime, timedelta

from src.agents import negotiator, personal
from src.core.meetups import weather as weather_mod

REPLY_WINDOW_S = 180
HINTS = ("cheaper", "closer", "different_kind", "none")


# ---------- simulated people ("bots"): like playing chess against the computer ----------

BOT_STYLES = {                        # chance in round 1 of: overruling their agent, dropping out
    "your agent": {"overrule": 0.0, "leave": 0.0},   # you, hands-off: your agent just sends its draft
    "easygoing": {"overrule": 0.05, "leave": 0.02},
    "picky":     {"overrule": 0.18, "leave": 0.02},
    "flaky":     {"overrule": 0.08, "leave": 0.05},
}
FLEX_PER_ROUND = 0.5   # people get more flexible as the chat goes on: overruling halves every round
BOT_LINES = {
    "accept": ["Eh, why not, I'm in!", "Fine, I'll make it work.", "Actually yeah, count me in.", "Let's do it."],
    "decline": ["Hmm, not feeling that one.", "Can we try something else?", "Not that place, sorry.", "Pass on this one."],
}
BOT_DELAY_S = (3.0, 12.0)


class BotPlayer:
    """Stands in for a person: reads its own agent's draft (and private facts) and answers like someone might.
    Its own random generator is seeded, so the same seed plays the same game."""

    def __init__(self, name: str, rng: random.Random, style: str | None = None):
        self.name, self.rng = name, rng
        self.style = style or rng.choice(sorted(s for s in BOT_STYLES if s != "your agent"))  # random people, never your own agent

    def decide(self, draft: dict, facts: dict, budget, rnd: int = 1) -> tuple[str, str | None, str | None]:
        p, r = BOT_STYLES[self.style], self.rng.random()
        overrule = p["overrule"] * FLEX_PER_ROUND ** (rnd - 1)
        if r < p["leave"]:
            return "leave", None, None
        if r < p["leave"] + overrule:
            if draft["decision"] == "decline":
                # a person might stretch a little past their limit, not a lot
                close = facts.get("reason") == "over budget" and budget is not None \
                    and float(facts["total"]) <= float(budget) * 1.25
                if close or facts.get("reason") is None:
                    return "accept", self.rng.choice(BOT_LINES["accept"]), None
            else:
                return "decline", self.rng.choice(BOT_LINES["decline"]), self.rng.choice(["cheaper", "closer", "different_kind"])
        return "approve", None, None

    def delay(self) -> float:
        if self.style == "your agent":
            return self.rng.uniform(1.5, 3.5)
        return self.rng.uniform(*BOT_DELAY_S)


def shake_profile(profile: dict, rng: random.Random) -> dict:
    """A seeded variation of a bot's private profile, so each game is a little different."""
    p = dict(profile)
    if p.get("meetup_budget") is not None:
        p["meetup_budget"] = round(float(p["meetup_budget"]) * rng.uniform(0.7, 1.4))
    if p.get("max_travel_min") is not None:
        p["max_travel_min"] = max(10, int(p["max_travel_min"]) + rng.choice([-10, -5, 0, 5, 10]))
    return p


class LiveError(ValueError):
    """Not allowed right now (already answered, not your turn, session over). Safe to show."""


class LiveNegotiation:
    def __init__(self, sid: int, group: dict, start: date, end: date, *, activity: str | None = None,
                 min_hours: float = 2, max_rounds: int = negotiator.MAX_ROUNDS, reply_window_s: int = REPLY_WINDOW_S,
                 organiser_id: int | None = None, bots: bool = False, seed: int | None = None,
                 play_as: int | None = None, opening: str | None = None, hands_off: bool = False, chat=None, data=None, clock=time.time, now: datetime | None = None,
                 weather=weather_mod.forecast):
        if data is None:
            from src.core.meetups import repo as data
        self.id, self.data, self.clock, self.weather = sid, data, clock, weather
        self.chat = chat or negotiator.model_chat()
        self.activity, self.min_hours, self.max_rounds, self.window = activity, min_hours, max_rounds, reply_window_s
        self.organiser_id = organiser_id
        self.lock = threading.RLock()
        self.started_at = datetime.now().isoformat(timespec="seconds")
        now = now or datetime.now()
        win = (max(datetime.combine(start, datetime.min.time()), now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)),
               datetime.combine(end + timedelta(days=1), datetime.min.time()))
        members = list(group["members"])
        self.out = {"group": {"id": group["id"], "name": group["name"]}, "status": "starting", "reason": None,
                    "agreed": None, "rounds": 0, "transcript": [], "shared": [], "members": [m["name"] for m in members],
                    "audit": {"private": {}, "leaks": [], "model_replies": 0, "ids": {m["name"]: m["id"] for m in members}}}
        self.st = {"members": members, "win": win, "names": {m["id"]: m["name"] for m in members},
                   "profiles": {m["id"]: dict(data.profile(m["id"])) for m in members},
                   "busy": {m["id"]: list(data.busy(m["id"], *win)) for m in members},
                   "labels": {m["id"]: data.busy_labels(m["id"], *win) for m in members},
                   "venues": data.venues(), "ranked": None, "real_pp": {}}
        if activity:
            try:
                self.st["ranked"] = data.venues_by_meaning(activity)
            except Exception:
                pass
        try:
            self.st["real_pp"] = data.real_cost_per_person(group["id"])
        except Exception as e:
            self.out.setdefault("notes", []).append(f"learned prices unavailable ({type(e).__name__})")
        # bots: everyone except the person playing (play_as) is simulated, from one seed
        self.seed = seed if seed is not None else random.randrange(1, 10**6)
        self.play_as = play_as
        self.bots: dict[int, BotPlayer] = {}
        self.bot_due: dict[int, float] = {}
        if bots:
            for m in members:
                if m["id"] == play_as:
                    if hands_off:
                        self.bots[m["id"]] = BotPlayer(m["name"], random.Random(f"{self.seed}:{m['id']}"), style="your agent")
                    continue
                rng = random.Random(f"{self.seed}:{m['id']}")
                self.bots[m["id"]] = BotPlayer(m["name"], rng)
                self.st["profiles"][m["id"]] = shake_profile(self.st["profiles"][m["id"]], rng)
        # hands-off games always get at least one disagreement in round 1, so the chat feels like real friends
        others = [pid for pid, b in self.bots.items() if b.style != "your agent"]
        self.contrarian = random.Random(f"{self.seed}:contrarian").choice(others) if hands_off and others else None
        self.rejected: list[dict] = []
        self.proposal: dict | None = None
        self.drafts: dict[int, dict] = {}
        self.finals: dict[int, dict] = {}
        self.deadline: float | None = None
        self.remembered = False
        if opening:   # the ask that started it all ("guys hang out tomm?"), first in the chat
            who = self.st["names"].get(play_as) or self.st["names"].get(organiser_id) or "Organiser"
            self.out["transcript"].append({"round": 0, "from": who, "to": "group", "text": opening[:280], "event": "ask"})
        stop = negotiator._plan_round(self.st, self.out, data, activity, min_hours, weather)
        if stop:
            self._finish(stop)
        else:
            self._open_round(1)

    # ---------- rounds ----------

    def _open_round(self, rnd: int) -> None:
        st = self.st
        venue, msg, by_model = negotiator.coordinator_pick(st["pool"], self.rejected, st["shared"], self.activity,
                                                           st["slot"], st["center"], self.chat)
        if not venue:
            self.out["reason"] = f"Ran out of places after {self.out['rounds']} round(s)"
            return self._finish("no_agreement")
        self.out["rounds"] = rnd
        self.proposal = {"venue": venue, "starts_at": st["slot"][0].isoformat(), "ends_at": st["slot"][1].isoformat(),
                         "message": msg}
        self.out["transcript"].append({"round": rnd, "from": "coordinator", "to": "group", "text": msg,
                                       "venue": venue["name"], "chosen_by_model": by_model})
        n = len(st["members"])
        self.drafts, self.finals = {}, {}
        for m in st["members"]:
            pid, name = m["id"], st["names"][m["id"]]
            d = personal.reply(name, st["profiles"][pid], st["labels"][pid], self.proposal, n, self.chat)
            self.drafts[pid] = d
            self.out["audit"]["model_replies"] += d["model"]
            self.out["audit"]["leaks"] += [{"round": rnd, "agent": name, "leak": l} for l in d["leaks"]]
        self.deadline = self.clock() + self.window
        self.bot_due = {pid: self.clock() + min(b.delay(), self.window - 1)
                        for pid, b in self.bots.items() if pid in self.drafts}
        self.out["status"] = "waiting"

    def _record(self, pid: int, final: dict) -> None:
        rnd, name = self.out["rounds"], self.st["names"][pid]
        self.finals[pid] = final
        self.out["transcript"].append({"round": rnd, "from": name, "to": "coordinator", "text": final["message"],
                                       "decision": final["decision"], "hint": final["hint"], "by": final["by"]})
        d = self.drafts[pid]
        self.out["audit"]["private"].setdefault(name, []).append(
            {"round": rnd, "venue": self.proposal["venue"]["name"], **d["facts"], "decision": final["decision"],
             "agent_draft": d["decision"], "by": final["by"]})

    def _close_round_if_done(self) -> None:
        if self.out["status"] != "waiting" or any(m["id"] not in self.finals for m in self.st["members"]):
            return
        decliners = [self.st["names"][pid] for pid, f in self.finals.items() if f["decision"] == "decline"]
        if not decliners:
            v, slot = self.proposal["venue"], self.st["slot"]
            self.out.update(agreed={"venue": {**{k: v[k] for k in ("id", "name", "kind", "indoor", "description")},
                                              "lng": float(v["lng"]), "lat": float(v["lat"])},
                                    "starts_at": slot[0].isoformat(), "ends_at": slot[1].isoformat()},
                            members=[m["name"] for m in self.st["members"]])
            self.out["transcript"].append({"round": self.out["rounds"], "from": "coordinator", "to": "group",
                                           "text": f"Everyone's in: {v['name']}, {slot[0]:%a %b %d %-I:%M %p}."})
            return self._finish("agreed")
        self.rejected.append({"venue": self.proposal["venue"], "decliners": decliners,
                              "hints": [f["hint"] for f in self.finals.values() if f["decision"] == "decline"]})
        if self.out["rounds"] >= self.max_rounds:
            self.out["reason"] = f"No place everyone accepted after {self.out['rounds']} rounds"
            self.out["transcript"].append({"round": self.out["rounds"], "from": "coordinator", "to": "group",
                                           "text": self.out["reason"]})
            return self._finish("no_agreement")
        self._open_round(self.out["rounds"] + 1)

    def _finish(self, status: str) -> None:
        self.out["status"] = status
        self.out["members"] = [m["name"] for m in self.st["members"]]
        if status not in ("agreed", "no_agreement") and self.out.get("reason"):
            self.out["transcript"].append({"round": self.out["rounds"], "from": "coordinator", "to": "group",
                                           "text": self.out["reason"]})
        self.deadline, self.drafts = None, {}
        self.out["model_calls"] = getattr(self.chat, "calls", 0)
        if not self.remembered:            # so "What your agent did for you" shows live plans too
            negotiator.remember(self.out)
            self.remembered = True

    # ---------- time ----------

    def tick(self) -> None:
        """If the reply window has passed, agents answer for everyone who hasn't."""
        with self.lock:
            while self.out["status"] == "waiting":
                due = sorted((t, pid) for pid, t in self.bot_due.items()
                             if t <= self.clock() and pid in self.drafts and pid not in self.finals)
                if not due:
                    break
                pid = due[0][1]
                del self.bot_due[pid]
                bot, d = self.bots[pid], self.drafts[pid]
                action, msg, hint = bot.decide(d, d["facts"], self.st["profiles"][pid].get("meetup_budget"), self.out["rounds"])
                if pid == self.contrarian and self.out["rounds"] == 1 and \
                        (action == "accept" or (action == "approve" and d["decision"] == "accept")):
                    action = "decline"
                    msg = bot.rng.choice(BOT_LINES["decline"])
                    hint = bot.rng.choice(["cheaper", "closer", "different_kind"])
                self._respond(pid, action, msg, hint, bot=bot.style != "your agent")
            if self.out["status"] == "waiting" and self.deadline is not None and self.clock() >= self.deadline:
                self._auto_answer("no reply in time")

    def _auto_answer(self, why: str) -> None:
        for m in self.st["members"]:
            pid = m["id"]
            if pid not in self.finals:
                d = self.drafts[pid]
                self._record(pid, {"decision": d["decision"], "message": d["message"], "hint": d["hint"],
                                   "by": f"agent ({why})"})
        self._close_round_if_done()

    def close_window(self, by_id: int | None = None) -> None:
        """The organiser stops waiting: agents answer for whoever hasn't replied yet."""
        with self.lock:
            if self.out["status"] != "waiting":
                raise LiveError("nothing to wait for")
            if self.organiser_id is not None and by_id not in (None, self.organiser_id):
                raise LiveError("only the organiser can stop waiting")
            self._auto_answer("organiser stopped waiting")

    # ---------- a person answers ----------

    def respond(self, pid: int, action: str, message: str | None = None, hint: str | None = None) -> None:
        """action: approve (send my agent's draft) | accept | decline | leave (I can't come at all)."""
        with self.lock:
            self.tick()
            if pid in self.bots:
                raise LiveError("that person is played by a bot in this game")
            self._respond(pid, action, message, hint)

    def _respond(self, pid: int, action: str, message: str | None, hint: str | None, bot: bool = False) -> None:
        with self.lock:
            if self.out["status"] != "waiting":
                raise LiveError("this plan isn't waiting for answers anymore")
            if pid not in {m["id"] for m in self.st["members"]}:
                raise LiveError("you're not part of this plan")
            if pid in self.finals:
                raise LiveError("you've already answered this round")
            name = self.st["names"][pid]
            who = f"{name} (bot)" if bot else name
            if action == "leave":
                # declines already said this round still count: don't re-propose a place someone just turned down
                said_no = [self.st["names"][q] for q, f in self.finals.items() if f["decision"] == "decline" and q != pid]
                if said_no and self.proposal:
                    self.rejected.append({"venue": self.proposal["venue"], "decliners": said_no,
                                          "hints": [f["hint"] for q, f in self.finals.items() if f["decision"] == "decline" and q != pid]})
                negotiator._apply({"person_id": pid, "leaves": True}, self.st, self.out, self.out["rounds"])
                self.drafts.pop(pid, None)
                self.out["members"] = [m["name"] for m in self.st["members"]]
                stop = negotiator._plan_round(self.st, self.out, self.data, self.activity, self.min_hours, self.weather)
                if stop:
                    return self._finish(stop)
                self.rejected = [r for r in self.rejected if set(r["decliners"]) & {self.st["names"][m["id"]] for m in self.st["members"]}]
                self.out["transcript"].append({"round": self.out["rounds"], "from": "coordinator", "to": "group",
                                               "event": "replanned",
                                               "text": f"Plans changed, re-planning for {len(self.st['members'])}."})
                return self._open_round(self.out["rounds"] + 1)
            d = self.drafts[pid]
            text = " ".join((message or "").split())[:200]
            if action == "approve":
                mine_auto = pid == self.play_as and pid in self.bots   # hands-off: your agent answered for you
                final = {"decision": d["decision"], "message": text or d["message"], "hint": d["hint"],
                         "by": "your agent" if mine_auto else f"agent, approved{' by bot' if bot else ''}"}
            elif action in ("accept", "decline"):
                default = personal.GENERIC[None] if action == "accept" else "That one doesn't work for me."
                h = (hint if hint in HINTS else d["hint"] if d["decision"] == "decline" else "none") if action == "decline" else "none"
                final = {"decision": action, "message": text or default, "hint": h,
                         "by": f"agent, approved{' by bot' if bot else ''}" if action == d["decision"] else f"{who}, changed"}
            else:
                raise LiveError("action must be approve, accept, decline or leave")
            self._record(pid, final)
            self._close_round_if_done()

    # ---------- views ----------

    def public(self) -> dict:
        """What the organiser (and the group) sees: the conversation so far and who it's waiting on. No drafts."""
        self.tick()
        with self.lock:
            waiting = [self.st["names"][m["id"]] for m in self.st["members"] if m["id"] not in self.finals] \
                if self.out["status"] == "waiting" else []
            left = max(0, int(self.deadline - self.clock())) if self.deadline else None
            return {"id": self.id, "started_at": self.started_at, **negotiator.public(self.out),
                    "waiting_on": waiting, "seconds_left": left, "seed": self.seed if self.bots else None,
                    "players": {self.st["names"][pid]: (("you (your agent)" if pid in self.bots else "you") if pid == self.play_as else f"bot ({b.style})" if (b := self.bots.get(pid)) else "person")
                                for pid in self.st["names"]},
                    "proposal": ({"venue": self.proposal["venue"]["name"], "starts_at": self.proposal["starts_at"],
                                  "ends_at": self.proposal["ends_at"]} if self.proposal and self.out["status"] == "waiting" else None),
                    "model_calls": getattr(self.chat, "calls", 0)}

    def for_person(self, pid: int) -> dict:
        """The public view plus, for this person only, their agent's draft and its private reason."""
        view = self.public()
        with self.lock:
            name = self.st["names"].get(pid)
            mine = None
            if self.out["status"] == "waiting" and pid in self.drafts and pid not in self.finals:
                d = self.drafts[pid]
                mine = {"draft": {"decision": d["decision"], "message": d["message"], "hint": d["hint"]},
                        "facts": d["facts"]}
            return {**view, "you": name, "your_turn": mine,
                    "you_answered": pid in self.finals, "you_left": name not in view["members"]}


# ---------- the sessions ----------

_SESSIONS: dict[int, LiveNegotiation] = {}
_ids = itertools.count(1)
_reg_lock = threading.Lock()


def start(group: dict, start_date: date, end_date: date, **kw) -> LiveNegotiation:
    with _reg_lock:
        sid = next(_ids)
    s = LiveNegotiation(sid, group, start_date, end_date, **kw)
    with _reg_lock:
        _SESSIONS[sid] = s
    return s


def get(sid: int) -> LiveNegotiation:
    s = _SESSIONS.get(sid)
    if not s:
        raise LiveError("no such plan (the server may have restarted)")
    return s


def for_person(pid: int) -> list[dict]:
    """Live plans this person is part of (or was, before leaving), newest first."""
    return [s.for_person(pid) for sid, s in sorted(_SESSIONS.items(), reverse=True)
            if pid in s.out["audit"]["ids"].values()][:10]
