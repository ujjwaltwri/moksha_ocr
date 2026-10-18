import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .db import dispose, get_sessionmaker
from .routers import registrations

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose()


app = FastAPI(title="Moksha Entry API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(registrations.router)


@app.get("/healthz")
async def healthz():
    async with get_sessionmaker()() as s:
        await s.execute(text("select 1"))
    return {"ok": True}
