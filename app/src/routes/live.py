"""GET /api/live: a server-sent event stream of ledger and meetup changes, for every open phone.

Events (JSON in `data:`):
  {"type": "hello", "people": [...]}                                       on connect
  {"type": "ledger", "action": "created|updated|settled|deleted", "expense": {...}, "people": [...]}
  {"type": "meetup", "meetup": {...}}                                      planned, voted, confirmed
"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.core import live
from src.core.expenses import ledger

router = APIRouter(prefix="/api")

KEEPALIVE_S = 15


@router.get("/live")
async def live_stream(request: Request):
    q = live.subscribe()

    async def events():
        try:
            people = await asyncio.to_thread(ledger.balances)
            yield f"data: {live.encode({'type': 'hello', 'people': people})}\n\n"
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_S)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            live.unsubscribe(q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
