"""Prometheus metrics. Workers use multiprocess mode when PROMETHEUS_MULTIPROC_DIR is set."""

from __future__ import annotations

import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

FETCH_TOTAL = Counter("newsforge_fetch_total", "HTTP fetches by outcome", ["outcome", "status"])
FETCH_DURATION = Histogram(
    "newsforge_fetch_duration_seconds", "HTTP fetch latency", buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
)
FETCH_BYTES = Counter("newsforge_fetch_bytes_total", "Bytes downloaded")
BLOCKED_TOTAL = Counter("newsforge_blocked_total", "Requests blocked before fetching", ["reason"])
RENDER_TOTAL = Counter("newsforge_render_total", "Playwright renders", ["outcome"])
DISCOVERED_TOTAL = Counter("newsforge_urls_discovered_total", "URLs discovered", ["via"])
ARTICLES_TOTAL = Counter("newsforge_articles_total", "Article persistence outcomes", ["outcome"])
EXTRACTION_TOTAL = Counter("newsforge_extractions_total", "Extraction runs", ["primary_method"])
EXTRACTION_CONFIDENCE = Histogram(
    "newsforge_extraction_confidence",
    "Extraction confidence score",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
ARTICLE_SCORE = Histogram(
    "newsforge_article_score", "Article classifier score", buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
)
LLM_CALLS = Counter("newsforge_llm_calls_total", "LLM fallback calls", ["outcome"])
CRAWL_JOBS = Counter("newsforge_jobs_total", "Crawl jobs finished", ["status"])
CRAWL_DURATION = Histogram(
    "newsforge_job_duration_seconds", "Crawl job duration", buckets=(1, 5, 15, 60, 180, 600, 1800, 3600)
)
ACTIVE_CRAWLS = Gauge("newsforge_active_jobs", "Crawl jobs currently running", multiprocess_mode="livesum")
API_REQUESTS = Counter("api_requests_total", "API requests", ["method", "route", "status"])
API_LATENCY = Histogram("api_request_duration_seconds", "API latency", ["method", "route"])


def render_metrics() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
