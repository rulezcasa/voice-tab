"""Is SingleStore up and seeded?   python -m scripts.check_s2 [--db tab_drill]"""
import time

from scripts._db import pick_db

pick_db()

from src import config  # noqa: E402
from src.db.s2_client import cursor  # noqa: E402

TABLES = ["people", "groups_", "group_members", "expenses", "expense_shares", "availability",
          "venues", "meetups", "meetup_options", "meetup_votes"]


def main() -> None:
    t = time.perf_counter()
    with cursor() as cur:
        print(f"connected to {config.SS['host']}/{config.SS['database']} in {int((time.perf_counter() - t) * 1000)} ms")
        bad = False
        for table in TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table:<15} {cur.fetchone()[0]:>5} rows")
            except Exception as e:
                bad = True
                print(f"  {table:<15} MISSING ({type(e).__name__}) -> run python -m scripts.reset_db")
        cur.execute("SELECT name, net FROM balances ORDER BY name")
        rows = cur.fetchall()
        print("  balances view:", ", ".join(f"{n} {v}" for n, v in rows) or "empty -> run python -m scripts.seed")
        cur.execute("SELECT COUNT(*) FROM expenses WHERE embedding IS NULL")
        missing = cur.fetchone()[0]
        if missing:
            print(f"  warning: {missing} expenses have no embedding (SIE was down while seeding)")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
