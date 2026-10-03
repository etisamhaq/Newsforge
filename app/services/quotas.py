"""Per-workspace limits and daily usage (UTC days)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import CrawlJob, JobStatus, Member, Source, Workspace, WorkspaceUsage


@dataclass(frozen=True)
class Limits:
    max_sources: int
    max_pages_per_day: int
    max_pages_per_crawl: int
    min_crawl_interval_minutes: int
    max_concurrent_crawls: int
    llm_calls_per_day: int
    max_members: int

    @classmethod
    def for_workspace(cls, ws: Workspace, settings: Settings | None = None) -> Limits:
        s = settings or get_settings()

        def pick(override: int | None, default: int) -> int:
            return default if override is None else override

        return cls(
            max_sources=pick(ws.max_sources, s.workspace_max_sources),
            max_pages_per_day=pick(ws.max_pages_per_day, s.workspace_max_pages_per_day),
            max_pages_per_crawl=pick(ws.max_pages_per_crawl, s.workspace_max_pages_per_crawl),
            min_crawl_interval_minutes=pick(ws.min_crawl_interval_minutes, s.workspace_min_crawl_interval_minutes),
            max_concurrent_crawls=pick(ws.max_concurrent_crawls, s.workspace_max_concurrent_crawls),
            llm_calls_per_day=pick(ws.llm_calls_per_day, s.workspace_llm_calls_per_day),
            max_members=pick(ws.max_members, s.workspace_max_members),
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Usage:
    pages: int = 0
    llm_calls: int = 0
    crawls: int = 0


class QuotaExceeded(HTTPException):
    def __init__(self, message: str):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, message)


def today() -> date:
    return datetime.now(timezone.utc).date()


async def usage_today(session: AsyncSession, workspace_id: int) -> Usage:
    row = await session.get(WorkspaceUsage, (workspace_id, today()))
    return Usage(row.pages, row.llm_calls, row.crawls) if row else Usage()


async def add_usage(session: AsyncSession, workspace_id: int, *, pages: int = 0, llm_calls: int = 0, crawls: int = 0) -> None:
    """Atomically add to today's counters (upsert). The caller commits."""
    if not (pages or llm_calls or crawls):
        return
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(WorkspaceUsage).values(workspace_id=workspace_id, day=today(), pages=pages, llm_calls=llm_calls, crawls=crawls)
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id", "day"],
        set_={
            "pages": WorkspaceUsage.pages + pages,
            "llm_calls": WorkspaceUsage.llm_calls + llm_calls,
            "crawls": WorkspaceUsage.crawls + crawls,
        },
    )
    await session.execute(stmt)


async def active_crawls(session: AsyncSession, workspace_id: int) -> int:
    stmt = select(func.count(CrawlJob.id)).where(
        CrawlJob.workspace_id == workspace_id,
        CrawlJob.status.in_([JobStatus.pending.value, JobStatus.running.value]),
    )
    return (await session.execute(stmt)).scalar_one()


async def source_count(session: AsyncSession, workspace_id: int) -> int:
    return (await session.execute(select(func.count(Source.id)).where(Source.workspace_id == workspace_id))).scalar_one()


async def member_count(session: AsyncSession, workspace_id: int) -> int:
    return (await session.execute(select(func.count(Member.id)).where(Member.workspace_id == workspace_id))).scalar_one()


async def require_pages(session: AsyncSession, ws: Workspace, needed: int = 1) -> int:
    """Raise if the workspace has fewer than `needed` page fetches left today; return what's left."""
    limits = Limits.for_workspace(ws)
    left = limits.max_pages_per_day - (await usage_today(session, ws.id)).pages
    if left < needed:
        raise QuotaExceeded(
            f"This workspace has used its {limits.max_pages_per_day} page fetches for today. The limit resets at midnight UTC."
        )
    return left


async def llm_calls_left(session: AsyncSession, ws: Workspace) -> int:
    limits = Limits.for_workspace(ws)
    return max(0, limits.llm_calls_per_day - (await usage_today(session, ws.id)).llm_calls)
