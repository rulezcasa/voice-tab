"""Print each person's private agent link. Send every link ONLY to its owner (e.g. a direct message).

    python -m scripts.agent_links                                 # links for http://localhost:5173
    python -m scripts.agent_links --base https://xyz.ngrok-free.app --db tab_meetups_test

Set AGENT_LINK_SECRET in .env first: links are signed with it, and changing it invalidates every link.
"""
import argparse

from scripts._db import pick_db

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--base", default="http://localhost:5173", help="where the app is opened from")
args = pick_db(parser)

from src.core.people import links  # noqa: E402
from src.db.s2_client import cursor  # noqa: E402


def main() -> None:
    if links.using_dev_secret():
        print("warning: AGENT_LINK_SECRET is not set, so these links use a development secret anyone could know.\n")
    with cursor() as cur:
        cur.execute("SELECT id, name FROM people ORDER BY is_me DESC, name")
        for pid, name in cur.fetchall():
            print(f"{name:<12} {args.base.rstrip('/')}/?agent={links.token(pid)}")


if __name__ == "__main__":
    main()
