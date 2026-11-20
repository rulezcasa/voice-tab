"""Pick the database BEFORE anything imports src (src.config reads SS_DATABASE once, at import).

Every script starts with:  from scripts._db import pick_db; args = pick_db(parser)
load_dotenv() never overwrites a variable that is already set, so --db wins over .env.
"""
import argparse
import os
import sys


def pick_db(parser: argparse.ArgumentParser | None = None) -> argparse.Namespace:
    parser = parser or argparse.ArgumentParser()
    parser.add_argument("--db", help="database name (default: SS_DATABASE from .env, usually 'tab'; "
                                     "use 'tab_drill' for Firedrill runs)")
    args = parser.parse_args()
    if "src.config" in sys.modules:
        raise RuntimeError("pick_db() must run before importing src")
    if args.db:
        os.environ["SS_DATABASE"] = args.db
    return args
