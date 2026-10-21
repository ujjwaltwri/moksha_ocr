import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from .config import get_settings
from .db import dispose, get_sessionmaker
from .routers import admin, gate, registrations, review

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose()


app = FastAPI(title="Moksha Entry API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
# The gate manifest is large (25k passes with face thumbnails); phones accept gzip automatically.
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=5)
app.include_router(registrations.router)
app.include_router(review.router)
app.include_router(gate.router)
app.include_router(admin.router)


STATIC = Path(__file__).parent / "static"
NO_CACHE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@app.get("/review", include_in_schema=False)
async def review_page():
    return FileResponse(STATIC / "review.html", headers=NO_CACHE)


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(STATIC / "admin.html", headers=NO_CACHE)


@app.get("/healthz")
async def healthz():
    async with get_sessionmaker()() as s:
        await s.execute(text("select 1"))
    return {"ok": True}
