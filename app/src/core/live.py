"""Live updates: anything that changes money or meetups publishes an event; every open phone gets it.

One process, so an in-memory fan-out is enough (no Redis). publish() is safe from any thread:
ledger writes run in worker threads, the agent runs on the event loop.
"""
import asyncio
import json
from decimal import Decimal
from datetime import date, datetime

QUEUE_MAX = 100

_loop: asyncio.AbstractEventLoop | None = None
_subs: set[asyncio.Queue] = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once at startup (main.py lifespan) with the server's event loop."""
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)


def _default(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def encode(event: dict) -> str:
    return json.dumps(event, default=_default)


def _put(q: asyncio.Queue, data: str) -> None:
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:  # a stalled client: drop its oldest event rather than block everyone
        try:
            q.get_nowait()
            q.put_nowait(data)
        except Exception:
            pass


def publish(event: dict) -> None:
    """Send an event to every subscriber. Never raises: live updates must not break a ledger write."""
    if _loop is None or not _subs:
        return
    try:
        data = encode(event)
        for q in list(_subs):
            _loop.call_soon_threadsafe(_put, q, data)
    except Exception:
        pass
