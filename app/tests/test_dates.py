"""Date resolver tests, no database or models. Run from app/:  python -m unittest tests.test_dates -v"""
import unittest
from datetime import date

from src.core.dates import DateError, fill_range, resolve, resolve_day

FRI = date(2026, 11, 20)  # a Friday


def day(**w):
    return resolve_day(w, FRI)


class SingleDay(unittest.TestCase):
    def test_relative_days(self):
        self.assertEqual(day(), FRI)                              # nothing said -> today
        self.assertEqual(day(days_ago=0), FRI)                    # today
        self.assertEqual(day(days_ago=1), date(2026, 11, 19))     # yesterday
        self.assertEqual(day(days_ago=10), date(2026, 11, 10))    # 10 days ago
        self.assertEqual(day(days_ago=20), date(2026, 10, 31))    # 20 days back, crosses a month

    def test_weeks_and_months_ago(self):
        self.assertEqual(day(weeks_ago=1), date(2026, 11, 13))
        self.assertEqual(day(weeks_ago=2), date(2026, 11, 6))
        self.assertEqual(day(months_ago=1), date(2026, 10, 20))
        self.assertEqual(resolve_day({"months_ago": 1}, date(2026, 3, 31)), date(2026, 2, 28))  # clamped

    def test_weekdays(self):
        self.assertEqual(day(weekday="wed"), date(2026, 11, 18))                # most recent Wednesday
        self.assertEqual(day(weekday="mon"), date(2026, 11, 16))
        self.assertEqual(day(weekday="fri"), date(2026, 11, 13))                # said on a Friday -> a week ago
        self.assertEqual(day(weekday="sat"), date(2026, 11, 14))
        self.assertEqual(day(weekday="wed", weeks_back=1), date(2026, 11, 11))  # last week Wednesday
        self.assertEqual(day(weekday="sun", weeks_back=1), date(2026, 11, 15))
        self.assertEqual(day(weekday="mon", weeks_back=2), date(2026, 11, 2))
        # live run: Qwen wrote "last week Wednesday" as weekday + weeks_ago; it must mean the same thing
        self.assertEqual(day(weekday="wed", weeks_ago=1), date(2026, 11, 11))

    def test_calendar_dates(self):
        self.assertEqual(day(day=3), date(2026, 11, 3))                    # the 3rd, this month
        self.assertEqual(day(day=25), date(2026, 10, 25))                  # the 25th is ahead -> last month
        self.assertEqual(day(month=10, day=28), date(2026, 10, 28))
        self.assertEqual(day(month=12, day=28), date(2025, 12, 28))        # Dec 28 said in Nov -> last year
        self.assertEqual(day(month=2, day=14, year=2026), date(2026, 2, 14))

    def test_refusals(self):
        with self.assertRaises(DateError):
            day(month=2, day=30)                         # not a real date
        with self.assertRaises(DateError):
            day(period="month", offset=-1)               # a range, not one day
        with self.assertRaises(DateError):
            day(days_ago=400)                            # over a year back
        with self.assertRaises(DateError):
            day(month=12, day=25, year=2026)             # in the future
        with self.assertRaises(Exception):
            day(days_ago=-1)                             # negative is rejected by the schema


class Ranges(unittest.TestCase):
    def test_periods(self):
        self.assertEqual(resolve({"period": "month", "offset": -1}, FRI), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(resolve({"period": "month"}, FRI), (date(2026, 11, 1), FRI))
        self.assertEqual(resolve({"period": "week"}, FRI), (date(2026, 11, 16), FRI))
        self.assertEqual(resolve({"period": "week", "offset": -1}, FRI), (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(resolve({"period": "year"}, FRI), (date(2026, 1, 1), FRI))
        self.assertEqual(resolve({"period": "month", "offset": -11}, FRI), (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(resolve({"last_n_days": 10}, FRI), (date(2026, 11, 11), FRI))
        self.assertEqual(resolve({"month": 10}, FRI), (date(2026, 10, 1), date(2026, 10, 31)))   # "in October"

    def test_fill_range(self):
        sql = "SELECT 1 FROM expenses e WHERE e.spent_on BETWEEN :start AND :end"
        self.assertEqual(
            fill_range(sql, {"period": "month", "offset": -1}, FRI),
            "SELECT 1 FROM expenses e WHERE e.spent_on BETWEEN '2026-10-01' AND '2026-10-31'",
        )
        self.assertEqual(fill_range("SELECT 1", None, FRI), "SELECT 1")
        with self.assertRaises(DateError):
            fill_range(sql, None, FRI)
        with self.assertRaises(DateError):
            fill_range("SELECT 1", {"days_ago": 1}, FRI)

    def test_handmade_dates_refused(self):
        for sql in (
            "SELECT 1 FROM expenses e WHERE e.spent_on >= '2026-11-11'",
            "SELECT 1 FROM expenses e WHERE e.spent_on >= DATE_SUB(CURDATE(), INTERVAL 10 DAY)",
            "SELECT 1 FROM expenses e WHERE e.spent_on >= NOW() - INTERVAL 10 DAY",
        ):
            with self.assertRaises(DateError, msg=sql):
                fill_range(sql, None, FRI)


if __name__ == "__main__":
    unittest.main()
