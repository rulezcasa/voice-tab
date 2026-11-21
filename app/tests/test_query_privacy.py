"""The agent's text-to-SQL can't read anyone's private planning data. No database needed for the refusals.
Run from app/:  python -m unittest tests.test_query_privacy -v"""
import unittest

from src.utils import query


class Refused(unittest.TestCase):
    def test_private_columns_and_calendar_are_refused(self):
        for sql in (
            "SELECT name, meetup_budget FROM people",
            "SELECT home_lat, home_lng FROM people WHERE name = 'Priya'",
            "SELECT * FROM availability",
            "SELECT busy_label FROM availability a JOIN people p ON p.id = a.person_id",
            "SELECT p.name FROM people p WHERE p.max_radius_mi > 3",
            "WITH x AS (SELECT interests FROM people) SELECT * FROM x",
        ):
            with self.assertRaises(query.QueryError, msg=sql):
                query.check(sql)

    def test_ordinary_ledger_questions_still_work(self):
        for sql in (
            "SELECT SUM(s.owed) FROM expense_shares s JOIN people p ON p.id = s.person_id WHERE p.is_me",
            "SELECT name, net FROM balances",
            "SELECT e.description FROM expenses e WHERE e.description = 'home lat test'",   # words inside a string are fine
        ):
            self.assertEqual(query.check(sql), sql)

    def test_select_star_results_drop_private_columns(self):
        class Cur:
            description = [("id",), ("name",), ("home_lat",), ("meetup_budget",), ("embedding",), ("interests",)]
            def execute(self, sql, params): pass
            def fetchmany(self, n): return [(1, "Priya", 37.75, 30, b"x", "[]")]
        class Ctx:
            def __enter__(self): return Cur()
            def __exit__(self, *a): return False
        real = query.cursor
        query.cursor = lambda readonly=False: Ctx()
        try:
            r = query.run("SELECT * FROM people")
        finally:
            query.cursor = real
        self.assertEqual(r["columns"], ["id", "name"])
        self.assertEqual(r["rows"], [[1, "Priya"]])


if __name__ == "__main__":
    unittest.main()
