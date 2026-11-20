"""SingleStore connection: the one place the app connects to the database.

Usage:
    from src.db.s2_client import cursor

    with cursor() as cur:
        cur.execute("SELECT name FROM people WHERE is_me")
        print(cur.fetchone())

Connections are pooled and kept open. Opening one costs ~700 ms; a query on an
open one ~30 ms. warm() opens POOL_WARM connections at app startup; each
cursor()/transaction() borrows one for the duration of its `with` block and
hands it back (a connection is never used by two threads at once).

- A connection idle for more than IDLE_PING_S is pinged (reconnected) before reuse.
- A connection that hits a database error is discarded, not returned to the pool.
- If the pool is empty a new connection is opened; at most POOL_MAX are kept idle.
- cursor() runs with autocommit on. Use transaction() when several writes must
  succeed or fail together (an expense and its shares).
"""
import json
import queue
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import singlestoredb as s2

from src import config

POOL_WARM = 4
POOL_MAX = 8
IDLE_PING_S = 30

_idle: queue.LifoQueue = queue.LifoQueue()  # (conn, last_used); LIFO keeps hot connections hot


def connect():
    """Open a brand-new, unpooled connection. Prefer cursor()/transaction()."""
    conn = s2.connect(**config.SS, connect_timeout=15)
    conn.autocommit(True)
    return conn


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _borrow():
    while True:
        try:
            conn, last_used = _idle.get_nowait()
        except queue.Empty:
            return connect()
        if time.monotonic() - last_used <= IDLE_PING_S:
            return conn
        try:
            conn.ping(reconnect=True)
            return conn
        except Exception:
            _close(conn)  # dead; try the next idle one


def _give_back(conn, broken: bool) -> None:
    if broken or _idle.qsize() >= POOL_MAX:
        _close(conn)
    else:
        _idle.put((conn, time.monotonic()))


def _is_db_error(e: Exception) -> bool:
    return isinstance(e, (s2.OperationalError, s2.InterfaceError))


@contextmanager
def cursor() -> Iterator:
    conn, broken = _borrow(), False
    try:
        with conn.cursor() as cur:
            yield cur
    except Exception as e:
        broken = _is_db_error(e)
        raise
    finally:
        _give_back(conn, broken)


@contextmanager
def transaction() -> Iterator:
    """All statements commit together, or roll back together on error."""
    conn, broken = _borrow(), False
    try:
        conn.autocommit(False)
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception as e:
        broken = _is_db_error(e)
        try:
            conn.rollback()
        except Exception:
            broken = True
        raise
    finally:
        if not broken:
            try:
                conn.autocommit(True)
            except Exception:
                broken = True
        _give_back(conn, broken)


def warm(n: int = POOL_WARM) -> None:
    """Open n connections in parallel so the first requests don't pay for connecting."""
    with ThreadPoolExecutor(n) as ex:
        for conn in ex.map(lambda _: connect(), range(n)):
            _give_back(conn, broken=False)


def close_all() -> None:
    while True:
        try:
            conn, _ = _idle.get_nowait()
        except queue.Empty:
            return
        _close(conn)


def to_vector(v: Sequence[float]) -> str:
    """Format a vector for a VECTOR(1024) column or a `%s :> VECTOR(1024)` literal."""
    return json.dumps([float(x) for x in v])


def run_sql_file(path, cur) -> None:
    """Execute a .sql file statement by statement (no semicolons inside comments)."""
    lines = [l for l in open(path).read().splitlines() if not l.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        if stmt.strip():
            cur.execute(stmt)
