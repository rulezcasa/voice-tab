"""Tab: entry point. Creates the app, manages startup/shutdown, mounts the routes
and serves the webapp.

Run (from app/):  fastapi dev main.py   (dev, auto-reload)
                  fastapi run main.py   (prod)

API at /api/*. The built PWA (../webapp/dist, from `npm run build`) is served at /
when it exists; while developing, use the Vite dev server instead (`npm run dev`).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src import config
from src.db import s2_client
from src.routes.api import router

WEBAPP_DIST = config.APP_DIR.parent / "webapp" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s2_client.warm()  # open pooled SingleStore connections before the first request
    yield
    s2_client.close_all()


app = FastAPI(title="Tab", description="The expense agent you just talk to", lifespan=lifespan)
app.include_router(router)
if WEBAPP_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIST, html=True), name="webapp")  # last: API routes win
