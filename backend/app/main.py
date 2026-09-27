import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, analytics, auth, backups, catalog, collection, prices, users
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.migrate import run_migrations
from app.seed.loader import seed_platforms
from app.services import scheduler
from app.services.pricing import mark_interrupted_runs

log = logging.getLogger("vgvault")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings().config_dir.mkdir(parents=True, exist_ok=True)
    run_migrations()
    with SessionLocal() as db:
        added = seed_platforms(db)
        mark_interrupted_runs(db)
    if added:
        log.info("Seeded %d platforms", added)
    if get_settings().scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="VGVault", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

for module in (auth, users, catalog, collection, prices, admin, analytics, backups):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        file = (STATIC_DIR / path).resolve()
        if path and file.is_file() and file.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
