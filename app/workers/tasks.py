from __future__ import annotations

import asyncio

from app.logging import get_logger
from app.services.crawl import dispatch_due_sources, run_job, task_id_for
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.crawl_job", max_retries=0)
def crawl_job(job_id: int) -> str:
    """Run one crawl job. Retries happen at the HTTP level; a failed job is recorded, not retried."""
    return asyncio.run(run_job(job_id))


@celery_app.task(name="app.workers.tasks.dispatch_due")
def dispatch_due() -> list[int]:
    job_ids = asyncio.run(dispatch_due_sources())
    for job_id in job_ids:
        crawl_job.apply_async(args=[job_id], queue="crawl", task_id=task_id_for(job_id))
    return job_ids


async def enqueue_crawl(job_id: int) -> None:
    """Enqueue a crawl job from async code (the API)."""
    await asyncio.to_thread(crawl_job.apply_async, args=[job_id], queue="crawl", task_id=task_id_for(job_id))
