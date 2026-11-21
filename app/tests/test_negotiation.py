"""Multi-agent negotiation tests with the seed script's demo people and venues, in memory.
No database, no network, no real model (a scripted stand-in). Run from app/:  python -m unittest tests.test_negotiation -v"""
import json
import re
import sys
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.agents import negotiator, personal

NOW = datetime(2026, 11, 20, 9, 0)           # a Friday morning
TODAY = NOW.date()
RAIN = lambda lat, lng, when: {"rain_prob": 70, "temp_c": 12.0, "source": "stub"}


def load_seed():
    """The seed script's demo data. Its module code picks a database first, which refuses to run once the app is
    imported (other test files do that), so the pick is skipped here: only the data lists are used."""
    if "scripts.seed" in sys.modules:
        return sys.modules["scripts.seed"]
    import argparse
    import scripts._db as db
    real = db.pick_db
    db.pick_db = lambda parser=None: (parser or argparse.ArgumentParser()).parse_args([])
    try:
        import scripts.seed as seed
    finally:
        db.pick_db = real
    return seed


class FakeData:
    """The seed's people, calendars and venues, served like src.core.meetups.repo."""
    def __init__(self, seed):
        self.seed = seed
        self.people = {}
        for i, (name, _me, _al, (lat, lng), budget, radius, max_min, mode, interests) in enumerate(seed.PEOPLE, 1):
            self.people[i] = {"id": i, "name": name, "home_lat": lat, "home_lng": lng, "meetup_budget": Decimal(budget),
                              "max_radius_mi": radius, "max_travel_min": max_min, "travel_mode": mode, "interests": interests}
        self.ids = {p["name"]: i for i, p in self.people.items()}
        self._venues = [{"id": i, "name": n, "kind": k, "lat": lat, "lng": lng, "price_pp": Decimal(pr),
                         "parking": Decimal(pk), "indoor": ind, "description": d}
                        for i, (n, k, (lat, lng), pr, pk, ind, d) in enumerate(seed.VENUES, 1)]
        wk = seed.weekend(TODAY)
        self.blocks = {}
        for i, name in enumerate(self.ids):
            free = {wk[d]: seed.FREE[d][name] for d in seed.FREE if name in seed.FREE[d]}
            self.blocks[self.ids[name]] = seed.busy_blocks(free, TODAY, TODAY + timedelta(days=9), i)

    def group(self, names):
        return {"id": 99, "name": "Friday crew", "members": [{"id": self.ids[n], "name": n} for n in names]}

    def profile(self, pid): return dict(self.people[pid])
    def busy(self, pid, s, e): return [(a, b) for a, b, _ in self.blocks[pid] if b > s and a < e]
    def busy_labels(self, pid, s, e): return sorted({l for a, b, l in self.blocks[pid] if b > s and a < e})
    def venues(self): return [dict(v) for v in self._venues]
    def real_cost_per_person(self, gid): return {"bowling": Decimal("34.00")}
    def venues_by_meaning(self, text):
        return [v["id"] for v in sorted(self._venues, key=lambda v: text.lower() not in (v["kind"] + " " + v["name"]).lower())]


class ScriptedModel:
    """Stand-in for Qwen. Personal agents follow the code's facts; the coordinator takes the first listed place,
    or follows `coordinator_ids` round by round. `personal_says` overrides personal replies (to test the guards)."""
    def __init__(self, coordinator_ids=None, personal_says=None):
        self.calls, self.coordinator_ids, self.personal_says, self.seen = 0, list(coordinator_ids or []), personal_says, []

    def __call__(self, system, user):
        self.calls += 1
        self.seen.append((system, user))
        if "personal agent" in system:
            if self.personal_says:
                return json.dumps(self.personal_says)
            fits = "fits=True" in system
            return json.dumps({"decision": "accept" if fits else "decline",
                               "message": "Sounds great!" if fits else "Hmm, that one doesn't really work for me.",
                               "hint": "none" if fits else "cheaper"})
        ids = re.findall(r"id=(\d+)", user)
        vid = self.coordinator_ids.pop(0) if self.coordinator_ids else int(ids[0])
        return json.dumps({"venue_id": vid, "message": "Let's try this one!"})


class Negotiation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = load_seed()
        cls.data = FakeData(cls.seed)
        cls.crew = cls.data.group(["Nik", "Sam", "Priya", "Alex Chen"])

    def run_it(self, model, **kw):
        kw.setdefault("start", TODAY + timedelta(days=1))
        kw.setdefault("end", TODAY + timedelta(days=3))
        return negotiator.negotiate(self.crew, kw.pop("start"), kw.pop("end"), chat=model, data=self.data, now=NOW,
                                    weather=RAIN, **kw)

    def test_coordinator_only_sees_shared_info(self):
        model = ScriptedModel()
        r = self.run_it(model)
        for c in r["shared"]:
            self.assertFalse({"home_lat", "home_lng", "meetup_budget", "busy_label"} & set(c))
            self.assertTrue(all(len(str(x).split(".")[-1]) <= 2 for x in c["area"]))      # ~1 km only
        coord_prompts = [u for s, u in model.seen if "You coordinate" in s]
        for prompt in coord_prompts:
            for p in self.data.people.values():
                self.assertNotIn(f"{p['home_lat']}", prompt)
                self.assertNotIn(f"budget", prompt.lower())

    def test_bowling_is_declined_then_the_group_agrees_elsewhere(self):
        bowling = next(v["id"] for v in self.data._venues if v["kind"] == "bowling")
        model = ScriptedModel(coordinator_ids=[bowling])      # round 1: bowling, then first remaining place
        r = self.run_it(model, activity="bowling")
        self.assertEqual(r["status"], "agreed")
        self.assertGreaterEqual(r["rounds"], 2)
        round1 = [t for t in r["transcript"] if t["round"] == 1 and t["from"] != "coordinator"]
        self.assertEqual({t["from"] for t in round1 if t["decision"] == "decline"}, {"Priya"})  # $34 learned > her budget
        self.assertNotEqual(r["agreed"]["venue"]["kind"], "bowling")
        last = r["rounds"]
        for name, facts in r["audit"]["private"].items():               # the agreed place really fits everyone
            self.assertTrue(next(f for f in facts if f["round"] == last)["ok"], name)
        self.assertEqual(r["agreed"]["starts_at"], f"{self.seed.weekend(TODAY)['sat']}T14:00:00")
        self.assertEqual(r["model_calls"], last * 5)                    # 1 coordinator + 4 agents per round

    def test_no_common_time_ends_without_any_model_call(self):
        model = ScriptedModel()
        r = self.run_it(model, start=TODAY + timedelta(days=3), end=TODAY + timedelta(days=4))  # Mon-Tue
        self.assertEqual(r["status"], "no_time")
        self.assertEqual(model.calls, 0)

    def test_a_leaking_reply_never_reaches_the_group(self):
        model = ScriptedModel(personal_says={"decision": "accept", "message": "Sure, my budget is 30 and I live at 37.76", "hint": "none"})
        r = self.run_it(model, max_rounds=1)
        said = " ".join(t["text"] for t in r["transcript"])
        self.assertNotIn("37.76", said)
        self.assertNotIn("budget is 30", said)
        self.assertTrue(r["audit"]["leaks"])                            # recorded for Firedrill

    def test_model_cannot_accept_what_breaks_a_private_limit(self):
        steak = next(v for v in self.data._venues if v["kind"] == "steakhouse")       # $85 + far: over everyone
        model = ScriptedModel(personal_says={"decision": "accept", "message": "Love it!", "hint": "none"})
        priya = self.data.profile(self.data.ids["Priya"])
        r = personal.reply("Priya", priya, [], {"venue": steak, "starts_at": "2026-11-21T14:00:00", "message": "Steak?"}, 4, model)
        self.assertEqual(r["decision"], "decline")                      # code's facts win over the model
        self.assertFalse(r["facts"]["ok"])
        self.assertIn(r["hint"], ("cheaper", "closer"))

    def test_bad_coordinator_answer_falls_back_to_code_and_follows_hints(self):
        model = ScriptedModel(coordinator_ids=[123456])                  # not a real id
        r = self.run_it(model, max_rounds=1)
        first = [t for t in r["transcript"] if t["from"] == "coordinator"][0]
        self.assertFalse(first["chosen_by_model"])
        self.assertTrue(first["venue"])

    def test_public_view_has_no_audit(self):
        r = self.run_it(ScriptedModel(), max_rounds=1)
        self.assertIn("audit", r)
        self.assertNotIn("audit", negotiator.public(r))


class Changes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = load_seed()
        cls.data = FakeData(cls.seed)
        cls.crew = cls.data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        cls.bowling = next(v["id"] for v in cls.data._venues if v["kind"] == "bowling")
        cls.sat = cls.seed.weekend(TODAY)["sat"]

    def run_it(self, changes, coordinator_ids=(), **kw):
        model = ScriptedModel(coordinator_ids=list(coordinator_ids))
        r = negotiator.negotiate(self.crew, TODAY + timedelta(days=1), TODAY + timedelta(days=3), changes=changes,
                                 chat=model, data=self.data, now=NOW, weather=RAIN, **kw)
        return r, model

    def pid(self, name):
        return self.data.ids[name]

    def test_raised_budget_before_the_start_lets_bowling_through(self):
        r, _ = self.run_it([{"when": "before", "person_id": self.pid("Priya"), "budget": "45"}], [self.bowling])
        self.assertEqual(r["status"], "agreed")
        self.assertEqual(r["agreed"]["venue"]["kind"], "bowling")
        self.assertEqual(r["rounds"], 1)
        said = " ".join(t["text"] for t in r["transcript"])
        self.assertNotIn("45", said)                                    # a budget change stays private

    def test_someone_drops_out_after_round_one_and_the_rest_agree(self):
        # round 1 bowling: Priya declines; then Priya leaves -> bowling is back on the table for the other three
        r, _ = self.run_it([{"when": 1, "person_id": self.pid("Priya"), "leaves": True}], [self.bowling, self.bowling])
        self.assertEqual(r["status"], "agreed")
        self.assertNotIn("Priya", r["members"])
        self.assertTrue(any(t.get("event") == "left" and t["from"] == "Priya" for t in r["transcript"]))
        self.assertTrue(any(t.get("event") == "replanned" for t in r["transcript"]))
        self.assertEqual(r["agreed"]["venue"]["kind"], "bowling")          # her decline no longer blocks it
        self.assertFalse([t for t in r["transcript"] if t["round"] == 2 and t["from"] == "Priya"])

    def test_new_calendar_entry_removes_the_only_shared_window(self):
        busy = [[f"{self.sat}T09:00:00", f"{self.sat}T23:00:00"]]
        r, model = self.run_it([{"when": "before", "person_id": self.pid("Alex Chen"), "busy": busy}])
        self.assertEqual(r["status"], "no_time")
        self.assertEqual(model.calls, 0)

    def test_too_many_drop_outs_stops_cleanly(self):
        ch = [{"when": 1, "person_id": self.pid(n), "leaves": True} for n in ("Sam", "Priya", "Alex Chen")]
        r, _ = self.run_it(ch, [self.bowling])
        self.assertEqual(r["status"], "no_people")

    def test_budget_cut_mid_way_is_seen_only_by_that_agent(self):
        r, _ = self.run_it([{"when": 1, "person_id": self.pid("Nik"), "budget": "5"}], [self.bowling], max_rounds=3)
        self.assertNotEqual(r["status"], "agreed")                       # nothing costs under $5
        self.assertFalse(any(t.get("event") == "replanned" for t in r["transcript"]))  # coordinator isn't told
        self.assertTrue(any("change" in e for e in r["audit"]["private"]["Nik"]))


class Consistency(unittest.TestCase):
    def test_message_never_contradicts_the_decision(self):
        seed = load_seed()
        data = FakeData(seed)
        cafe = next(v for v in data._venues if v["name"] == "Steep Coffee Co.")            # fits Alex Chen
        model = ScriptedModel(personal_says={"decision": "decline", "message": "Not my vibe today, sorry!", "hint": "different_kind"})
        r = personal.reply("Alex Chen", data.profile(data.ids["Alex Chen"]), [], {"venue": cafe, "starts_at": "x", "message": ""}, 4, model)
        self.assertEqual(r["decision"], "accept")
        self.assertEqual(r["message"], personal.GENERIC[None])          # not the contradicting text
        self.assertFalse(r["model"])                                    # counted as not written by the model


class LeakGuard(unittest.TestCase):
    PROFILE = {"meetup_budget": Decimal("30"), "max_radius_mi": 4.0, "home_lat": 37.7502, "home_lng": -122.4337}

    def test_finds_private_numbers_coords_and_labels(self):
        s = personal.secrets(self.PROFILE, ["Dentist"])
        self.assertTrue(personal.leaks("I can spend 30 max", s))
        self.assertTrue(personal.leaks("I'm at 37.75 or so", s))
        self.assertTrue(personal.leaks("I have the dentist then", s))
        self.assertTrue(personal.leaks("I'd rather keep it under $30", s))

    def test_lets_ordinary_replies_through(self):
        s = personal.secrets(self.PROFILE, ["Dentist"])
        for ok in ("Sounds great, see you Saturday!", "A bit pricey for me, maybe somewhere cheaper?",
                   "That's far out for me.", "Works for me at 2pm", "Meet 2-4 PM?", "See you at 2:30 PM",
                   "within 4 miles is fine"):                     # the radius is shared on purpose
            self.assertEqual(personal.leaks(ok, s), [], ok)


if __name__ == "__main__":
    unittest.main()
