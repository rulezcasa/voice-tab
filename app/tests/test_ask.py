"""Casual asks -> dates and activity. No network. Run from app/:  python -m unittest tests.test_ask -v"""
import json
import unittest
from datetime import date

from src.agents.ask import fallback, resolve, understand

FRI = date(2026, 11, 20)
SAT = date(2026, 11, 21)


class Resolve(unittest.TestCase):
    def test_labels_on_a_friday(self):
        self.assertEqual(resolve("today", None, FRI), (FRI, FRI))
        self.assertEqual(resolve("tomorrow", None, FRI), (SAT, SAT))
        self.assertEqual(resolve("this_weekend", None, FRI), (FRI, date(2026, 11, 22)))
        self.assertEqual(resolve("next_weekend", None, FRI), (date(2026, 11, 27), date(2026, 11, 29)))
        self.assertEqual(resolve("this_week", None, FRI), (FRI, date(2026, 11, 22)))
        self.assertEqual(resolve("weekday", "sat", FRI), (SAT, SAT))
        self.assertEqual(resolve("weekday", "fri", FRI), (FRI, FRI))                 # today if it's that day
        self.assertEqual(resolve("weekday", "wed", FRI), (date(2026, 11, 25),) * 2)
        self.assertEqual(resolve("nonsense", None, FRI), (SAT, date(2026, 11, 27)))  # next 7 days

    def test_weekend_when_it_is_already_the_weekend(self):
        self.assertEqual(resolve("this_weekend", None, SAT), (SAT, date(2026, 11, 22)))


class Fallback(unittest.TestCase):
    def test_casual_words(self):
        for text, when in (("guys hang out tomm?", "tomorrow"), ("tmrw?", "tomorrow"), ("anyone free tonight", "today"),
                           ("bowling this weekend?", "this_weekend"), ("next weekend maybe", "next_weekend"),
                           ("hang out?", "next_7_days")):
            self.assertEqual(fallback(text)["when"], when, text)
        self.assertEqual(fallback("dinner saturday?")["weekday"], "sat")


class Understand(unittest.TestCase):
    def test_model_label_turned_into_dates_by_code(self):
        chat = lambda s, u: json.dumps({"when": "tomorrow", "weekday": None, "activity": "bowling"})
        r = understand("bowl tmrw?", FRI, chat)
        self.assertEqual((r["start"], r["end"], r["activity"], r["by"]), (SAT, SAT, "bowling", "model"))

    def test_bad_model_reply_falls_back_to_words(self):
        r = understand("guys hang out tomm?", FRI, lambda s, u: "sure! tomorrow sounds fun")
        self.assertEqual((r["start"], r["by"]), (SAT, "words"))

    def test_model_dates_are_ignored(self):
        chat = lambda s, u: json.dumps({"when": "2026-12-25", "activity": None})       # not a label
        self.assertEqual(understand("xmas?", FRI, chat)["by"], "words")


if __name__ == "__main__":
    unittest.main()
