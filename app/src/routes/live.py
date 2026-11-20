"""Server-sent events for clients that need immediate ledger updates."""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.core import live

router = APIRouter(prefix="/api")


@router.get("/live")
async def live_events():
    async def stream():
        q = live.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event, separators=(',', ':'), default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            live.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
