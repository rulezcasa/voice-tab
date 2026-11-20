"""Private agent links and per-person views. No database. Run from app/:  python -m unittest tests.test_private_access -v"""
import unittest

from src.agents import negotiator
from src.core.people import links


class Links(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(links.person_from(links.token(2251799813685250)), 2251799813685250)

    def test_forged_or_edited_links_are_refused(self):
        good = links.token(7)
        pid, sig = good.split(".")
        edited = sig[:-1] + ("A" if sig[-1] != "A" else "B")           # change the last character, whatever it is
        for bad in (f"8.{sig}", f"{pid}.{edited}", "7", "", "abc.def", f"{pid}.", None):
            self.assertIsNone(links.person_from(bad), bad)

    def test_tokens_depend_on_the_secret(self):
        import os
        a = links.token(7)
        os.environ["AGENT_LINK_SECRET"] = "a different secret"
        try:
            self.assertNotEqual(links.token(7), a)
            self.assertIsNone(links.person_from(a))                 # rotating the secret kills old links
        finally:
            del os.environ["AGENT_LINK_SECRET"]


class PersonView(unittest.TestCase):
    def setUp(self):
        negotiator._LOG.clear()
        self.result = {
            "group": {"id": 1, "name": "Friday crew"}, "status": "agreed", "rounds": 1, "members": ["Priya", "Sam"],
            "transcript": [{"round": 1, "from": "Priya", "text": "Works for me!", "decision": "accept"}],
            "shared": [], "agreed": None, "reason": None, "model_calls": 3,
            "audit": {"ids": {"Priya": 3, "Sam": 2}, "leaks": [], "model_replies": 2,
                      "private": {"Priya": [{"round": 1, "ok": True, "total": "27.50"}],
                                  "Sam": [{"round": 1, "ok": True, "total": "41.00"}]}},
        }
        negotiator.remember(self.result)

    def test_you_see_only_your_own_private_notes(self):
        mine = negotiator.for_person(3)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["you"], "Priya")
        self.assertEqual(mine[0]["your_agent"], [{"round": 1, "ok": True, "total": "27.50"}])
        self.assertNotIn("audit", mine[0])
        self.assertNotIn("41.00", str(mine[0]))                     # nothing of Sam's

    def test_people_not_in_it_see_nothing(self):
        self.assertEqual(negotiator.for_person(99), [])


if __name__ == "__main__":
    unittest.main()
