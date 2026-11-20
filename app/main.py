"""Tab: entry point. Creates the app, manages startup/shutdown, mounts the routes and serves the webapp."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src import config
from src.db import s2_client
from src.mcp.server import mcp
from src.routes.api import router
from src.routes.ingest import router as ingest_router
from src.routes.live import router as live_router
from src.core import live

WEBAPP_DIST = config.APP_DIR.parent / "webapp" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s2_client.warm()  # open pooled SingleStore connections before the first request
    live.set_loop(asyncio.get_running_loop())
    async with mcp.session_manager.run():
        yield
    s2_client.close_all()


app = FastAPI(title="Tab", description="The expense agent you just talk to", lifespan=lifespan)
app.include_router(router)
app.include_router(ingest_router)
app.include_router(live_router)
app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))  # agent tools over streamable HTTP
if WEBAPP_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIST, html=True), name="webapp")  # last: API routes win
