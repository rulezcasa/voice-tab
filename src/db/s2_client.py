"""SingleStore connection: the one place the app connects to the database.

Usage:
    from src.db.s2_client import cursor

    with cursor() as cur:
        cur.execute("SELECT name FROM people WHERE is_me")
        print(cur.fetchone())

Each `cursor()` opens a short-lived connection (autocommit on) and closes it on exit.
Writes inside one `cursor()` block share a connection. Use `transaction()` when
several writes must succeed or fail together (an expense and its shares).
"""
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import singlestoredb as s2

from src import config


def connect():
    """Open a new connection. Prefer cursor()/transaction(), which close it for you."""
    return s2.connect(**config.SS, connect_timeout=15)


@contextmanager
def cursor() -> Iterator:
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator:
    """All statements commit together, or roll back together on error."""
    conn = connect()
    try:
        conn.autocommit(False)
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def to_vector(v: Sequence[float]) -> str:
    """Format a vector for a VECTOR(1024) column or a `%s :> VECTOR(1024)` literal."""
    return json.dumps([float(x) for x in v])


def run_sql_file(path, cur) -> None:
    """Execute a .sql file statement by statement (no semicolons inside comments)."""
    lines = [l for l in open(path).read().splitlines() if not l.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        if stmt.strip():
            cur.execute(stmt)
