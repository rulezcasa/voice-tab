"""Create the database if needed, then drop and recreate every table from src/db/schema.sql.

    python -m scripts.reset_db                 # the demo database (SS_DATABASE, usually 'tab')
    python -m scripts.reset_db --db tab_drill  # the Firedrill database
    python -m scripts.reset_db --grant         # also give SS_READONLY_USER SELECT on the safe tables only

The read-only user (the agent's text-to-SQL) is never granted `availability`: calendars stay private.
"""
import argparse

from scripts._db import pick_db

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--grant", action="store_true", help="grant SELECT on safe tables to SS_READONLY_USER")
args = pick_db(parser)

import singlestoredb as s2  # noqa: E402

from src import config  # noqa: E402
from src.db import s2_client  # noqa: E402

SCHEMA = config.APP_DIR / "src" / "db" / "schema.sql"
# What the agent's read-only SQL may see. Not here: availability (calendars).
# Private columns on `people` (home_lat, meetup_budget, ...) are also refused in src/utils/query.py.
READONLY_TABLES = ["people", "groups_", "group_members", "expenses", "expense_shares", "balances",
                   "venues", "meetups", "meetup_options", "meetup_votes"]


def main() -> None:
    db = config.SS["database"]
    server = s2.connect(**{**config.SS, "database": None}, connect_timeout=15)
    with server.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}`")
    server.close()

    conn = s2_client.connect()
    with conn.cursor() as cur:
        s2_client.run_sql_file(SCHEMA, cur)
        cur.execute("SHOW TABLES")
        tables = sorted(r[0] for r in cur.fetchall())
        print(f"[{db}] tables: {', '.join(tables)}")

        if args.grant:
            if not config.SS_READONLY:
                print("--grant: SS_READONLY_USER is not set, skipping")
            else:
                user = config.SS_READONLY["user"]
                for t in READONLY_TABLES:
                    try:
                        cur.execute(f"GRANT SELECT ON `{db}`.`{t}` TO '{user}'@'%'")
                    except Exception as e:
                        print(f"  grant on {t} failed: {e}")
                print(f"granted SELECT to {user} on: {', '.join(READONLY_TABLES)} (not availability)")
    conn.close()


if __name__ == "__main__":
    main()
