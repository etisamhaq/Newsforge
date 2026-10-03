"""Async engine / session management.

The API process keeps one engine for its lifetime. Celery tasks run each job in a fresh
event loop, so they create a short-lived engine via `task_session_scope()` (asyncpg
connections are bound to the loop that created them).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_engine_injected = False


def make_engine(url: str | None = None, *, pooled: bool = True) -> AsyncEngine:
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs.pop("pool_pre_ping")
    elif pooled:
        kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_pool_size)
    else:
        kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = make_engine()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def set_engine(engine: AsyncEngine) -> None:
    """Override the global engine (used by tests)."""
    global _engine, _sessionmaker, _engine_injected
    _engine = engine
    _engine_injected = True
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def task_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A loop-local sessionmaker for Celery tasks; disposes its engine on exit."""
    if _engine is not None and _engine_injected:
        # Tests / eager mode share the injected global engine.
        yield get_sessionmaker()
        return
    engine = make_engine(pooled=False)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
