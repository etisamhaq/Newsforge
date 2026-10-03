"""Aggregates for the dashboard: totals, last-24h pipeline throughput, daily volume, languages, sources."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.base import utcnow
from app.db.models import Article, CrawlJob, JobStatus, Source

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def stats(days: int = Query(14, ge=1, le=90), session: AsyncSession = Depends(get_session)) -> dict:
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    originals = Article.duplicate_of_id.is_(None)

    async def scalar(stmt):
        return (await session.execute(stmt)).scalar_one() or 0

    totals = {
        "sources": await scalar(select(func.count(Source.id))),
        "sources_enabled": await scalar(select(func.count(Source.id)).where(Source.enabled.is_(True))),
        "articles": await scalar(select(func.count(Article.id)).where(originals)),
        "duplicates": await scalar(select(func.count(Article.id)).where(Article.duplicate_of_id.is_not(None))),
        "jobs_active": await scalar(
            select(func.count(CrawlJob.id)).where(CrawlJob.status.in_([JobStatus.pending.value, JobStatus.running.value]))
        ),
    }

    # Pipeline throughput over the last 24h, summed from the jobs that ran in that window.
    recent_jobs = (await session.execute(select(CrawlJob).where(CrawlJob.created_at >= day_ago))).scalars().all()
    pipeline = {"discovered": 0, "fetched": 0, "articles": 0, "new": 0, "duplicates": 0, "failed": 0, "robots_blocked": 0}
    for job in recent_jobs:
        st = job.stats or {}
        pipeline["discovered"] += int(st.get("discovered", 0) or 0)
        pipeline["fetched"] += job.pages_fetched
        pipeline["articles"] += job.articles_found
        pipeline["new"] += job.articles_new
        pipeline["duplicates"] += job.duplicates
        pipeline["failed"] += job.pages_failed
        pipeline["robots_blocked"] += int(st.get("robots_blocked", 0) or 0)

    # Bucket by UTC calendar day regardless of the database server's timezone.
    created = Article.created_at
    if session.bind.dialect.name == "postgresql":
        created = func.timezone("UTC", Article.created_at)
    day_col = func.date(created)
    per_day_rows = (
        await session.execute(
            select(day_col, func.count(Article.id)).where(Article.created_at >= since, originals).group_by(day_col)
        )
    ).all()
    counts = {str(d): c for d, c in per_day_rows}
    per_day = [
        {"date": (since + timedelta(days=i)).date().isoformat(), "count": counts.get((since + timedelta(days=i)).date().isoformat(), 0)}
        for i in range(days)
    ]

    languages = [
        {"language": lang or "unknown", "count": c}
        for lang, c in (
            await session.execute(
                select(Article.language, func.count(Article.id)).where(originals)
                .group_by(Article.language).order_by(func.count(Article.id).desc()).limit(8)
            )
        ).all()
    ]

    jobs_by_status = dict(
        (await session.execute(select(CrawlJob.status, func.count(CrawlJob.id)).group_by(CrawlJob.status))).all()
    )

    article_counts = dict(
        (await session.execute(select(Article.source_id, func.count(Article.id)).where(originals).group_by(Article.source_id))).all()
    )
    last_status: dict[int, str] = {}
    for source_id, status in (
        await session.execute(select(CrawlJob.source_id, CrawlJob.status).order_by(CrawlJob.id.desc()).limit(500))
    ).all():
        last_status.setdefault(source_id, status)
    sources = [
        {"id": s.id, "name": s.name, "enabled": s.enabled, "articles": article_counts.get(s.id, 0),
         "last_crawl_at": s.last_crawl_at, "next_crawl_at": s.next_crawl_at, "last_status": last_status.get(s.id)}
        for s in (await session.execute(select(Source).order_by(Source.name))).scalars()
    ]

    return {
        "generated_at": now,
        "totals": totals,
        "last_24h": pipeline,
        "articles_per_day": per_day,
        "languages": languages,
        "jobs_by_status": jobs_by_status,
        "sources": sources,
    }
