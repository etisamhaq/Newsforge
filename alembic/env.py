from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection

from alembic import context
from app.config import get_settings
from app.db import models  # noqa: F401 - register models
from app.db.base import Base
from app.db.session import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


# Postgres-only objects managed by hand in migrations (not mapped on the ORM model).
UNMAPPED = {"search_vector", "ix_articles_search_vector"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return name not in UNMAPPED


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = make_engine(_url(), pooled=False)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
