"""SingleStore connection: the one place the app connects to the database."""
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

_idle: queue.LifoQueue = queue.LifoQueue()     # (conn, last_used); LIFO keeps hot connections hot
_idle_ro: queue.LifoQueue = queue.LifoQueue()  # same, for the read-only user (config.SS_READONLY)


def connect(readonly: bool = False):
    """Open a brand-new, unpooled connection. Prefer cursor()/transaction()."""
    conn = s2.connect(**(config.SS_READONLY if readonly else config.SS), connect_timeout=15)
    conn.autocommit(True)
    return conn


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _borrow(readonly: bool = False):
    pool = _idle_ro if readonly else _idle
    while True:
        try:
            conn, last_used = pool.get_nowait()
        except queue.Empty:
            return connect(readonly)
        if time.monotonic() - last_used <= IDLE_PING_S:
            return conn
        try:
            conn.ping(reconnect=True)
            return conn
        except Exception:
            _close(conn)  # dead; try the next idle one


def _give_back(conn, broken: bool, readonly: bool = False) -> None:
    pool = _idle_ro if readonly else _idle
    if broken or pool.qsize() >= POOL_MAX:
        _close(conn)
    else:
        pool.put((conn, time.monotonic()))


def _is_db_error(e: Exception) -> bool:
    return isinstance(e, (s2.OperationalError, s2.InterfaceError))


@contextmanager
def cursor(readonly: bool = False) -> Iterator:
    """readonly=True uses the SELECT-only user when SS_READONLY_USER is set, else the normal one."""
    readonly = readonly and config.SS_READONLY is not None
    conn, broken = _borrow(readonly), False
    try:
        with conn.cursor() as cur:
            yield cur
    except Exception as e:
        broken = _is_db_error(e)
        raise
    finally:
        _give_back(conn, broken, readonly)


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
    for pool in (_idle, _idle_ro):
        while True:
            try:
                conn, _ = pool.get_nowait()
            except queue.Empty:
                break
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
