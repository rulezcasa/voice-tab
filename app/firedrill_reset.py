"""Reset and reseed the isolated Firedrill database."""

import os
import subprocess
import sys


def main():
    # Never inherit the application's default database for a destructive reset.
    database = os.environ.get("TAB_FIREDRILL_DATABASE")
    if database != "tab_drill":
        raise SystemExit("Reset disabled: explicitly set TAB_FIREDRILL_DATABASE=tab_drill after approving that database for disposable drills.")
    for module in ("scripts.reset_db", "scripts.seed"):
        subprocess.run([sys.executable, "-m", module, "--db", database], check=True, timeout=300)


if __name__ == "__main__":
    main()
