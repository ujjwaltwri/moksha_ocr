from collections.abc import AsyncIterator

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine_args(url: str) -> tuple[str, dict]:
    """Managed Postgres URLs carry ?sslmode=require. asyncpg (used directly by the worker and scripts)
    understands sslmode, but SQLAlchemy's asyncpg driver needs it as connect_args={"ssl": ...}."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    connect_args = {}
    if "sslmode" in query:
        connect_args["ssl"] = query.pop("sslmode")
    return urlunsplit(parts._replace(query=urlencode(query))), connect_args


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        s = get_settings()
        url, connect_args = engine_args(s.database_url)
        # Keep connections modest: managed Postgres plans allow only ~20-50 in total.
        _engine = create_async_engine(url, connect_args=connect_args, pool_size=s.db_pool_size,
                                      max_overflow=s.db_pool_size, pool_pre_ping=True, pool_recycle=1800)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = _sessionmaker = None
