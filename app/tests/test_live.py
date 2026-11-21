"""Live negotiation: agents draft, people approve or change, a reply window closes rounds.
Fake data, fake clock, scripted model. Run from app/:  python -m unittest tests.test_live -v"""
import json
import unittest
from datetime import timedelta

from src.agents import live
from src.agents.live import LiveError
from tests.test_negotiation import NOW, RAIN, TODAY, FakeData, ScriptedModel, load_seed


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = FakeData(load_seed())
        cls.crew = cls.data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        cls.bowling = next(v["id"] for v in cls.data._venues if v["kind"] == "bowling")
        cls.ids = {n: cls.data.ids[n] for n in ("Nik", "Sam", "Priya", "Alex Chen")}

    def start(self, coordinator_ids=(), **kw):
        self.clock = Clock()
        self.model = ScriptedModel(coordinator_ids=list(coordinator_ids))
        return live.start(self.crew, TODAY + timedelta(days=1), TODAY + timedelta(days=3), chat=self.model,
                          data=self.data, now=NOW, weather=RAIN, clock=self.clock, reply_window_s=120, **kw)

    def approve_all(self, s):
        for name in [n for n in s.public()["waiting_on"]]:
            s.respond(self.ids[name], "approve")

    def test_drafts_wait_for_people_and_stay_private(self):
        s = self.start([self.bowling])
        pub = s.public()
        self.assertEqual(pub["status"], "waiting")
        self.assertEqual(set(pub["waiting_on"]), set(self.ids))
        self.assertFalse([t for t in pub["transcript"] if t.get("decision")])      # nothing sent yet
        self.assertNotIn("draft", json.dumps(pub))
        self.assertNotIn("facts", json.dumps(pub))
        priya = s.for_person(self.ids["Priya"])
        self.assertEqual(priya["your_turn"]["draft"]["decision"], "decline")      # bowling is over her budget
        self.assertFalse(priya["your_turn"]["facts"]["ok"])
        sam = s.for_person(self.ids["Sam"])
        self.assertNotIn(priya["your_turn"]["facts"]["total"], json.dumps(sam))   # Sam can't see Priya's numbers

    def test_approving_every_draft_runs_the_rounds_to_agreement(self):
        s = self.start([self.bowling])
        self.approve_all(s)                                    # round 1: Priya's agent declines -> round 2
        self.assertEqual(s.public()["rounds"], 2)
        self.approve_all(s)
        pub = s.public()
        self.assertEqual(pub["status"], "agreed")
        self.assertNotEqual(pub["agreed"]["venue"]["kind"], "bowling")
        self.assertTrue(all(t["by"] == "agent, approved" for t in pub["transcript"] if t.get("decision")))

    def test_a_person_can_overrule_their_agent(self):
        s = self.start([self.bowling])
        s.respond(self.ids["Priya"], "accept", "I'll splurge, let's bowl!")       # her choice, over her agent's no
        for n in ("Nik", "Sam", "Alex Chen"):
            s.respond(self.ids[n], "approve")
        pub = s.public()
        self.assertEqual(pub["status"], "agreed")
        self.assertEqual(pub["agreed"]["venue"]["kind"], "bowling")
        mine = [t for t in pub["transcript"] if t["from"] == "Priya"][0]
        self.assertEqual((mine["text"], mine["by"]), ("I'll splurge, let's bowl!", "Priya, changed"))

    def test_silence_until_the_window_closes_uses_the_agents_drafts(self):
        s = self.start([self.bowling])
        s.respond(self.ids["Nik"], "approve")
        self.clock.t += 121                                     # nobody else answers in time
        pub = s.public()
        self.assertEqual(pub["rounds"], 2)                      # round 1 closed by the agents
        by = {t["from"]: t["by"] for t in pub["transcript"] if t.get("decision") and t["round"] == 1}
        self.assertEqual(by["Nik"], "agent, approved")
        self.assertEqual(by["Sam"], "agent (no reply in time)")

    def test_organiser_can_stop_waiting(self):
        s = self.start([self.bowling])
        s.close_window()
        self.assertEqual(s.public()["rounds"], 2)

    def test_leaving_replans_for_the_rest(self):
        s = self.start([self.bowling, self.bowling])
        s.respond(self.ids["Priya"], "leave")
        pub = s.public()
        self.assertNotIn("Priya", pub["members"])
        self.assertTrue(any(t.get("event") == "replanned" for t in pub["transcript"]))
        self.assertEqual(pub["rounds"], 2)
        self.assertNotIn("Priya", pub["waiting_on"])
        self.approve_all(s)                                     # without Priya, bowling fits the other three
        self.assertEqual(s.public()["agreed"]["venue"]["kind"], "bowling")
        self.assertTrue(s.for_person(self.ids["Priya"])["you_left"])

    def test_rules(self):
        s = self.start([self.bowling])
        s.respond(self.ids["Nik"], "approve")
        with self.assertRaises(LiveError):
            s.respond(self.ids["Nik"], "accept")                # once per round
        with self.assertRaises(LiveError):
            s.respond(self.data.ids["Alex Park"], "approve")    # not in this group
        with self.assertRaises(LiveError):
            s.respond(self.ids["Sam"], "shrug")

    def test_no_common_time_never_waits(self):
        self.clock = Clock()
        s = live.start(self.crew, TODAY + timedelta(days=3), TODAY + timedelta(days=4), chat=ScriptedModel(),
                       data=self.data, now=NOW, weather=RAIN, clock=self.clock)
        self.assertEqual(s.public()["status"], "no_time")
        self.assertEqual(s.public()["waiting_on"], [])


if __name__ == "__main__":
    unittest.main()


class Bots(unittest.TestCase):
    """You play yourself; everyone else is a seeded bot."""
    @classmethod
    def setUpClass(cls):
        cls.data = FakeData(load_seed())
        cls.crew = cls.data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        cls.me = cls.data.ids["Nik"]

    def game(self, seed):
        clock = Clock()
        s = live.start(self.crew, TODAY + timedelta(days=1), TODAY + timedelta(days=3), chat=ScriptedModel(),
                       data=self.data, now=NOW, weather=RAIN, clock=clock, reply_window_s=120,
                       bots=True, seed=seed, play_as=self.me)
        return s, clock

    def play(self, seed, rounds=6):
        """Bots answer as time passes; I always approve my agent."""
        s, clock = self.game(seed)
        for _ in range(rounds):
            clock.t += 13                                  # past every bot's delay
            pub = s.public()
            if pub["status"] != "waiting":
                break
            if pub["waiting_on"] == ["Nik"]:
                s.respond(self.me, "approve")
        return s.public()

    def test_bots_answer_by_themselves_and_wait_for_you(self):
        s, clock = self.game(7)
        self.assertEqual(set(s.public()["waiting_on"]), {"Nik", "Sam", "Priya", "Alex Chen"})
        clock.t += 13
        pub = s.public()
        if pub["status"] == "waiting" and pub["rounds"] == 1:
            self.assertEqual(pub["waiting_on"], ["Nik"])   # only the human is left
        self.assertEqual(pub["players"]["Nik"], "you")
        self.assertTrue(all(v.startswith("bot (") for k, v in pub["players"].items() if k != "Nik"))

    def test_you_cannot_answer_for_a_bot(self):
        s, _ = self.game(7)
        with self.assertRaises(LiveError):
            s.respond(self.data.ids["Sam"], "approve")

    def test_same_seed_same_game(self):
        a, b = self.play(42), self.play(42)
        strip = lambda p: [(t["from"], t["text"], t.get("decision"), t.get("by")) for t in p["transcript"]]
        self.assertEqual(strip(a), strip(b))
        self.assertEqual(a["status"], b["status"])

    def test_different_seeds_play_differently(self):
        games = {s: self.play(s) for s in range(1, 13)}
        outcomes = {(g["status"], g["rounds"], (g["agreed"] or {}).get("venue", {}).get("name"), tuple(g["members"]))
                    for g in games.values()}
        self.assertGreater(len(outcomes), 1)               # not the same result every time anymore
        bot_moves = {t["by"] for g in games.values() for t in g["transcript"] if t.get("by")}
        self.assertTrue(any("bot" in b for b in bot_moves))


class HandsOff(unittest.TestCase):
    """After your first message you only watch: your own agent answers for you."""
    def test_game_finishes_with_no_input_from_you(self):
        data = FakeData(load_seed())
        crew = data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        me = data.ids["Nik"]
        for seed in range(20):
            clock = Clock()
            s = live.start(crew, TODAY + timedelta(days=1), TODAY + timedelta(days=1), chat=ScriptedModel(), data=data,
                           now=NOW, weather=RAIN, clock=clock, reply_window_s=120, bots=True, seed=seed, play_as=me,
                           hands_off=True, opening="guys hang out tomm?")
            for _ in range(12):
                clock.t += 13
                if s.public()["status"] != "waiting":
                    break
            pub = s.public()
            self.assertNotEqual(pub["status"], "waiting", seed)                 # never stuck waiting on you
            self.assertEqual(pub["transcript"][0]["text"], "guys hang out tomm?")
            self.assertEqual(pub["players"]["Nik"], "you (your agent)")
            mine = [t for t in pub["transcript"] if t["from"] == "Nik" and t.get("decision")]
            self.assertTrue(mine and all(t["by"] == "your agent" for t in mine))
            self.assertFalse([t for t in pub["transcript"] if t["from"] == "Nik" and "changed" in (t.get("by") or "")])


class BotPersonalities(unittest.TestCase):
    def test_random_bots_never_get_your_agents_style(self):
        import random
        styles = {live.BotPlayer("x", random.Random(i)).style for i in range(300)}
        self.assertEqual(styles, {"easygoing", "picky", "flaky"})


class Disagreement(unittest.TestCase):
    def test_every_hands_off_game_has_a_disagreement(self):
        data = FakeData(load_seed())
        crew = data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        for seed in range(40):
            clock = Clock()
            s = live.start(crew, TODAY + timedelta(days=1), TODAY + timedelta(days=1), chat=ScriptedModel(), data=data,
                           now=NOW, weather=RAIN, clock=clock, reply_window_s=120, bots=True, seed=seed,
                           play_as=data.ids["Nik"], hands_off=True, opening="hang out tomm?")
            for _ in range(12):
                clock.t += 13
                if s.public()["status"] != "waiting":
                    break
            t = s.public()["transcript"]
            pushback = [x for x in t if x.get("decision") == "decline" or x.get("event") == "left"]
            self.assertTrue(pushback, f"seed {seed}: nobody disagreed")


class NoRepeatAfterLeaving(unittest.TestCase):
    def test_a_place_declined_this_round_is_not_proposed_again_after_someone_leaves(self):
        data = FakeData(load_seed())
        crew = data.group(["Nik", "Sam", "Priya", "Alex Chen"])
        bowling = next(v["id"] for v in data._venues if v["kind"] == "bowling")
        clock = Clock()
        model = ScriptedModel(coordinator_ids=[bowling])          # then the first place left on the list
        s = live.start(crew, TODAY + timedelta(days=1), TODAY + timedelta(days=3), chat=model, data=data, now=NOW,
                       weather=RAIN, clock=clock, reply_window_s=120)
        s.respond(data.ids["Priya"], "approve")                   # her agent declines bowling
        s.respond(data.ids["Sam"], "leave")                       # then Sam leaves mid-round
        pub = s.public()
        proposals = [t["venue"] for t in pub["transcript"] if t["from"] == "coordinator" and t.get("venue")]
        self.assertEqual(proposals[0], "Lucky Lanes Bowling")
        self.assertNotEqual(proposals[-1], "Lucky Lanes Bowling")  # not offered to Priya again
