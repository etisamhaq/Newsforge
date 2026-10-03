from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, current_workspace, get_session, require_editor, require_viewer
from app.api.routes.sources import get_source_or_404
from app.db.base import utcnow
from app.db.models import CrawlJob, JobStatus
from app.schemas import CrawlJobOut, JobPage
from app.services.crawl import create_job, has_active_job
from app.services.quotas import Limits, QuotaExceeded, active_crawls, add_usage, require_pages

router = APIRouter(tags=["crawls"])

Dispatcher = Callable[[int], Awaitable[None]]


def get_dispatcher() -> Dispatcher:
    """How jobs reach workers. Overridable (tests run them inline)."""
    from app.workers.tasks import enqueue_crawl

    return enqueue_crawl


async def _get_job(session: AsyncSession, job_id: int, workspace_id: int) -> CrawlJob:
    job = await session.get(CrawlJob, job_id)
    if job is None or job.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "crawl job not found")
    return job


@router.post("/sources/{source_id}/crawl", response_model=CrawlJobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_crawl(
    source_id: int,
    session: AsyncSession = Depends(get_session),
    dispatch: Dispatcher = Depends(get_dispatcher),
    principal: Principal = Depends(require_editor),
) -> CrawlJob:
    source = await get_source_or_404(session, source_id, principal.workspace_id)
    if await has_active_job(session, source.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "a crawl for this source is already pending or running")
    ws = await current_workspace(session, principal)
    limits = Limits.for_workspace(ws)
    if await active_crawls(session, ws.id) >= limits.max_concurrent_crawls:
        raise QuotaExceeded(
            f"This workspace can run {limits.max_concurrent_crawls} crawls at once. Wait for one to finish."
        )
    await require_pages(session, ws)
    job = await create_job(session, source, trigger="manual")
    job.triggered_by = principal.label
    await add_usage(session, ws.id, crawls=1)
    await session.commit()
    try:
        await dispatch(job.id)
    except Exception as exc:
        job.status = JobStatus.failed.value
        job.error = f"could not enqueue: {type(exc).__name__}"
        job.finished_at = utcnow()
        await session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "task queue unavailable") from exc
    await session.refresh(job)
    return job


@router.get("/crawls", response_model=JobPage)
async def list_crawls(
    source_id: int | None = None,
    status_: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_viewer),
) -> dict:
    stmt = select(CrawlJob).where(CrawlJob.workspace_id == principal.workspace_id)
    if source_id is not None:
        stmt = stmt.where(CrawlJob.source_id == source_id)
    if status_:
        stmt = stmt.where(CrawlJob.status == status_)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (await session.execute(stmt.order_by(CrawlJob.id.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/crawls/{job_id}", response_model=CrawlJobOut)
async def get_crawl(
    job_id: int, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_viewer)
) -> CrawlJob:
    return await _get_job(session, job_id, principal.workspace_id)


@router.post("/crawls/{job_id}/cancel", response_model=CrawlJobOut)
async def cancel_crawl(
    job_id: int, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_editor)
) -> CrawlJob:
    job = await _get_job(session, job_id, principal.workspace_id)
    if job.status not in (JobStatus.pending.value, JobStatus.running.value):
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is already {job.status}")
    # A running engine notices this flag between pages and stops.
    job.status = JobStatus.cancelled.value
    if job.started_at is None:
        job.finished_at = utcnow()
    await session.commit()
    await session.refresh(job)
    return job
