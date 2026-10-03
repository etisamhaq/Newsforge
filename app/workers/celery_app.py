from __future__ import annotations

import os

from celery import Celery
from celery.signals import worker_init, worker_process_init

from app.config import get_settings
from app.logging import configure_logging

settings = get_settings()

celery_app = Celery("newsforge", broker=settings.broker_url, backend=settings.result_backend, include=["app.workers.tasks"])
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,  # recycle processes (Chromium / memory hygiene)
    task_time_limit=settings.crawl_time_budget_seconds + 900,
    task_soft_time_limit=settings.crawl_time_budget_seconds + 600,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_default_queue="default",
    # structlog writes JSON to stdout itself; don't let Celery re-wrap it as WARNING log records.
    worker_redirect_stdouts=False,
    # Long crawls run on "crawl"; the scheduler tick runs on "default" so it is never stuck behind them.
    task_routes={
        "app.workers.tasks.crawl_job": {"queue": "crawl"},
        "app.workers.tasks.dispatch_due": {"queue": "default"},
    },
    beat_schedule={
        "dispatch-due-sources": {
            "task": "app.workers.tasks.dispatch_due",
            "schedule": float(settings.scheduler_interval_seconds),
            "options": {"expires": settings.scheduler_interval_seconds},
        }
    },
    timezone="UTC",
)


@worker_init.connect
def _start_metrics_server(**_):
    configure_logging()
    port = os.environ.get("WORKER_METRICS_PORT")
    if not port:
        return
    from prometheus_client import CollectorRegistry, multiprocess, start_http_server

    mp_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if mp_dir:
        os.makedirs(mp_dir, exist_ok=True)
        for f in os.listdir(mp_dir):  # clear stale metrics from a previous run
            os.remove(os.path.join(mp_dir, f))
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        start_http_server(int(port), registry=registry)
    else:
        start_http_server(int(port))


@worker_process_init.connect
def _init_child(**_):
    configure_logging()


app = celery_app
