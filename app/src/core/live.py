"""Thread-safe bridge from synchronous ledger writes to async live subscribers."""
import asyncio

_loop: asyncio.AbstractEventLoop | None = None
_subs: set[asyncio.Queue] = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def publish(event: dict) -> None:
    loop = _loop
    if loop is None or loop.is_closed():
        return
    for q in tuple(_subs):
        loop.call_soon_threadsafe(q.put_nowait, event)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)
