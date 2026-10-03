from __future__ import annotations

import os
from pathlib import Path

# Configure the test environment before the app is imported.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/0")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("DEFAULT_MIN_DELAY", "0")
os.environ.setdefault("RETRY_BACKOFF_BASE", "0")
os.environ.setdefault("MAX_ARTICLE_AGE_DAYS", "0")  # fixtures are dated 2024
# Never let a developer .env leak into tests.
for _k in ("API_KEY", "LLM_ENABLED", "PLAYWRIGHT_ENABLED", "SEARCH_BACKEND", "ANTHROPIC_API_KEY", "GROQ_API_KEY"):
    os.environ[_k] = {"LLM_ENABLED": "false", "PLAYWRIGHT_ENABLED": "false", "SEARCH_BACKEND": "auto"}.get(_k, "")

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_sessionmaker, set_engine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")  # e.g. postgresql+asyncpg://.../crawler_test

FTS_DDL = """
ALTER TABLE articles ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(description, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(body, '')), 'C')) STORED
"""


@pytest.fixture
async def engine(tmp_path, monkeypatch):
    from app.config import get_settings

    if TEST_DATABASE_URL:
        eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(FTS_DDL))
        monkeypatch.setattr(get_settings(), "database_url", TEST_DATABASE_URL)
    else:
        # File-backed so concurrent sessions get their own connections (like Postgres).
        eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db", connect_args={"timeout": 30})
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    set_engine(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client(engine):
    from app.api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
