"""Drop and recreate the selected Tab database from src/db/schema.sql."""
import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", choices=("tab", "tab_drill"), default="tab")
    args = parser.parse_args()

    # config reads this on import, so select the target database first.
    os.environ["SS_DATABASE"] = args.db
    from src import config
    from src.db.s2_client import run_sql_file, transaction

    with transaction() as cur:
        run_sql_file(config.APP_DIR / "src" / "db" / "schema.sql", cur)
    print(f"Reset database {args.db}")


if __name__ == "__main__":
    main()
