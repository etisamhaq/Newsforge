"""Crawl job lifecycle: create, run (with a per-source distributed lock), schedule, reap."""

from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crawler.engine import CrawlEngine, CrawlQuota
from app.crawler.fetcher import Fetcher
from app.crawler.ratelimit import MemoryRateLimiter, RedisRateLimiter
from app.db.base import utcnow
from app.db.models import CrawlJob, JobStatus, Source, Workspace
from app.db.session import task_session_factory
from app.logging import get_logger
from app.metrics import ACTIVE_CRAWLS, CRAWL_DURATION, CRAWL_JOBS
from app.search.base import get_search_backend
from app.services.quotas import Limits, active_crawls, add_usage, usage_today

log = get_logger(__name__)

ACTIVE_STATUSES = (JobStatus.pending.value, JobStatus.running.value)


async def get_redis():
    """Return a connected asyncio Redis client, or None if Redis is unavailable."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=5)
    try:
        await client.ping()
        return client
    except Exception:  # noqa: BLE001
        await client.aclose()
        return None


def task_id_for(job_id: int) -> str:
    return f"crawl-job-{job_id}"


async def create_job(session: AsyncSession, source: Source, trigger: str = "manual") -> CrawlJob:
    job = CrawlJob(workspace_id=source.workspace_id, source_id=source.id, trigger=trigger,
                   status=JobStatus.pending.value, stats={})
    # Any crawl (manual or scheduled) resets the schedule, so the scheduler doesn't immediately repeat it.
    source.next_crawl_at = utcnow() + timedelta(minutes=max(1, source.crawl_interval_minutes))
    session.add(job)
    await session.flush()
    job.task_id = task_id_for(job.id)
    return job


async def has_active_job(session: AsyncSession, source_id: int) -> bool:
    stmt = select(CrawlJob.id).where(CrawlJob.source_id == source_id, CrawlJob.status.in_(ACTIVE_STATUSES)).limit(1)
    return (await session.execute(stmt)).first() is not None


async def run_job(job_id: int, *, fetcher: Fetcher | None = None, renderer=None) -> str:
    """Execute a crawl job end-to-end. Returns the final job status."""
    settings = get_settings()
    async with task_session_factory() as session_factory:
        async with session_factory() as session:
            job = await session.get(CrawlJob, job_id)
            if job is None:
                log.warning("crawl.job_missing", job_id=job_id)
                return "missing"
            if job.status != JobStatus.pending.value:
                return job.status
            source = await session.get(Source, job.source_id)
            workspace = await session.get(Workspace, job.workspace_id)
            limits = Limits.for_workspace(workspace, settings)
            used = await usage_today(session, workspace.id)
            quota = CrawlQuota(
                pages_left=max(0, limits.max_pages_per_day - used.pages),
                llm_calls_left=max(0, limits.llm_calls_per_day - used.llm_calls),
                max_pages_per_crawl=limits.max_pages_per_crawl,
            )
            job.status = JobStatus.running.value
            job.started_at = utcnow()
            await session.commit()
            session.expunge(source)

        redis = await get_redis()
        lock = None
        if redis is not None:
            lock = redis.lock(f"crawl-lock:source:{source.id}", timeout=settings.crawl_time_budget_seconds + 600, blocking=False)
            if not await lock.acquire():
                await _finish(session_factory, job_id, JobStatus.cancelled.value, error="another crawl of this source is running")
                await redis.aclose()
                return JobStatus.cancelled.value

        own_fetcher = fetcher is None
        if fetcher is None:
            limiter = RedisRateLimiter(redis) if redis is not None else MemoryRateLimiter()
            fetcher = Fetcher(settings, rate_limiter=limiter)
        if renderer is None and settings.playwright_enabled:
            from app.crawler.renderer import PlaywrightRenderer

            renderer = PlaywrightRenderer(settings, guard=fetcher.guard)

        ACTIVE_CRAWLS.inc()
        start = time.monotonic()
        status, error, stats = JobStatus.failed.value, None, None
        try:
            async with session_factory() as s:
                dialect = s.bind.dialect.name
            engine = CrawlEngine(session_factory, fetcher, renderer=renderer,
                                 search_backend=get_search_backend(dialect), settings=settings, quota=quota)
            stats = await engine.crawl(source, job_id=job_id)
            status = JobStatus.cancelled.value if stats.stopped_reason == "cancelled" else JobStatus.succeeded.value
        except Exception as exc:  # noqa: BLE001 - recorded on the job
            log.exception("crawl.failed", job_id=job_id)
            error = f"{type(exc).__name__}: {exc}"[:2000]
        finally:
            ACTIVE_CRAWLS.dec()
            CRAWL_DURATION.observe(time.monotonic() - start)
            if own_fetcher:
                await fetcher.aclose()
            if renderer is not None:
                await renderer.aclose()
            if lock is not None:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001 - lock may have expired
                    pass
            if redis is not None:
                await redis.aclose()

        await _finish(session_factory, job_id, status, error=error, stats=stats)
        return status


async def _finish(session_factory, job_id: int, status: str, *, error: str | None = None, stats=None) -> None:
    async with session_factory() as session:
        job = await session.get(CrawlJob, job_id)
        if job is None:
            return
        if job.status == JobStatus.cancelled.value and status == JobStatus.succeeded.value:
            status = JobStatus.cancelled.value
        job.status = status
        job.finished_at = utcnow()
        job.error = error
        if stats is not None:
            job.pages_fetched = stats.pages_fetched
            job.pages_failed = stats.pages_failed
            job.pages_skipped = stats.pages_skipped
            job.articles_found = stats.articles_found
            job.articles_new = stats.articles_new
            job.articles_updated = stats.articles_updated
            job.duplicates = stats.duplicates
            job.stats = stats.as_dict()
            await add_usage(session, job.workspace_id, pages=stats.fetches, llm_calls=stats.llm_calls)
        source = await session.get(Source, job.source_id)
        if source is not None:
            source.last_crawl_at = job.finished_at
        await session.commit()
    CRAWL_JOBS.labels(status).inc()


async def dispatch_due_sources() -> list[int]:
    """Create jobs for sources whose next_crawl_at has passed; the caller enqueues them."""
    settings = get_settings()
    now = utcnow()
    job_ids: list[int] = []
    async with task_session_factory() as session_factory, session_factory() as session:
        await reap_stale_jobs(session)
        stmt = (
            select(Source)
            .where(Source.enabled.is_(True), or_(Source.next_crawl_at.is_(None), Source.next_crawl_at <= now))
            .order_by(Source.next_crawl_at.asc().nulls_first())
            .limit(100)
        )
        if settings.is_postgres:
            stmt = stmt.with_for_update(skip_locked=True)
        workspaces: dict[int, Workspace] = {}
        for source in (await session.execute(stmt)).scalars():
            source.next_crawl_at = now + timedelta(minutes=max(1, source.crawl_interval_minutes))
            if await has_active_job(session, source.id):
                continue
            ws = workspaces.get(source.workspace_id) or await session.get(Workspace, source.workspace_id)
            workspaces[ws.id] = ws
            limits = Limits.for_workspace(ws, settings)
            # Respect the workspace's limits: skip this round if it's at its crawl or daily page cap.
            if await active_crawls(session, ws.id) >= limits.max_concurrent_crawls:
                continue
            if (await usage_today(session, ws.id)).pages >= limits.max_pages_per_day:
                continue
            job = await create_job(session, source, trigger="scheduled")
            await add_usage(session, ws.id, crawls=1)
            await session.flush()
            job_ids.append(job.id)
        await session.commit()
    if job_ids:
        log.info("scheduler.dispatched", jobs=job_ids)
    return job_ids


async def reap_stale_jobs(session: AsyncSession) -> int:
    """Fail jobs stuck in running/pending far beyond the time budget (e.g. worker crash)."""
    cutoff = utcnow() - timedelta(seconds=get_settings().crawl_time_budget_seconds * 2 + 900)
    result = await session.execute(
        update(CrawlJob)
        .where(CrawlJob.status.in_(ACTIVE_STATUSES), CrawlJob.created_at < cutoff)
        .values(status=JobStatus.failed.value, error="stale job reaped", finished_at=utcnow())
    )
    return result.rowcount or 0
