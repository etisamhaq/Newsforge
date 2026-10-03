from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.crawler.security import BlockedURLError, UrlGuard
from app.crawler.urls import host_of, normalize_url

_syntax_guard = UrlGuard()


def _check_url(value: str) -> str:
    value = value.strip()
    try:
        _syntax_guard.check_syntax(value)
    except BlockedURLError as exc:
        raise ValueError(exc.reason) from exc
    return normalize_url(value)


def _check_urls(values: list[str]) -> list[str]:
    if len(values) > 50:
        raise ValueError("at most 50 urls")
    return [_check_url(v) for v in values]


def _check_patterns(values: list[str]) -> list[str]:
    if len(values) > 20:
        raise ValueError("at most 20 patterns")
    for p in values:
        if len(p) > 200:
            raise ValueError("pattern too long")
        try:
            re.compile(p)
        except re.error as exc:
            raise ValueError(f"invalid regex {p!r}: {exc}") from exc
    return values


def _check_domains(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if len(values) > 20:
        raise ValueError("at most 20 domains")
    out = []
    for d in values:
        d = d.strip().lower().removeprefix("http://").removeprefix("https://").split("/", 1)[0]
        try:
            ascii_d = d.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid domain {d!r}") from exc
        if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", ascii_d):
            raise ValueError(f"invalid domain {d!r}")
        out.append(ascii_d)
    return out


class SourceBase(BaseModel):
    allowed_domains: list[str] | None = None
    start_urls: list[str] = Field(default_factory=list)
    feed_urls: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    enabled: bool = True
    crawl_interval_minutes: int = Field(60, ge=5, le=10080)
    max_pages: int = Field(200, ge=1, le=20000)
    max_depth: int = Field(3, ge=0, le=10)
    min_delay_seconds: float = Field(1.0, ge=0.0, le=120)
    render_mode: Literal["never", "auto", "always"] = "auto"
    store_raw_html: bool = False
    discover_links: bool = True

    @field_validator("start_urls", "feed_urls", "sitemap_urls")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        return _check_urls(v)

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        return _check_patterns(v)

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        return _check_domains(v)


class SourceCreate(SourceBase):
    name: str = Field(min_length=1, max_length=200)
    base_url: str

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str) -> str:
        return _check_url(v)


class SourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    base_url: str | None = None
    allowed_domains: list[str] | None = None
    start_urls: list[str] | None = None
    feed_urls: list[str] | None = None
    sitemap_urls: list[str] | None = None
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    enabled: bool | None = None
    crawl_interval_minutes: int | None = Field(None, ge=5, le=10080)
    max_pages: int | None = Field(None, ge=1, le=20000)
    max_depth: int | None = Field(None, ge=0, le=10)
    min_delay_seconds: float | None = Field(None, ge=0.0, le=120)
    render_mode: Literal["never", "auto", "always"] | None = None
    store_raw_html: bool | None = None
    discover_links: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return _check_url(v) if v is not None else v

    @field_validator("start_urls", "feed_urls", "sitemap_urls")
    @classmethod
    def _urls(cls, v: list[str] | None) -> list[str] | None:
        return _check_urls(v) if v is not None else v

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def _patterns(cls, v: list[str] | None) -> list[str] | None:
        return _check_patterns(v) if v is not None else v

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        return _check_domains(v)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    base_url: str
    domain: str
    allowed_domains: list[str]
    start_urls: list[str]
    feed_urls: list[str]
    sitemap_urls: list[str]
    include_patterns: list[str]
    exclude_patterns: list[str]
    enabled: bool
    crawl_interval_minutes: int
    max_pages: int
    max_depth: int
    min_delay_seconds: float
    render_mode: str
    store_raw_html: bool
    discover_links: bool
    last_crawl_at: datetime | None
    next_crawl_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CrawlJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    status: str
    trigger: str
    triggered_by: str | None = None
    task_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pages_fetched: int
    pages_failed: int
    pages_skipped: int
    articles_found: int
    articles_new: int
    articles_updated: int
    duplicates: int
    error: str | None
    stats: dict[str, Any]


class ArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int | None
    url: str
    canonical_url: str
    title: str | None
    description: str | None
    authors: list[str]
    published_at: datetime | None
    modified_at: datetime | None
    image_url: str | None
    category: str | None
    tags: list[str]
    language: str | None
    site_name: str | None
    word_count: int
    extraction_method: str | None
    confidence: float
    article_score: float
    duplicate_of_id: int | None
    created_at: datetime
    updated_at: datetime
    score: float | None = None


class ArticleDetail(ArticleSummary):
    body: str | None
    content_hash: str | None
    extra: dict[str, Any]


class Paginated(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class ArticlePage(Paginated):
    items: list[ArticleSummary]
    backend: str


class SourcePage(Paginated):
    items: list[SourceOut]


class JobPage(Paginated):
    items: list[CrawlJobOut]


class DebugExtractRequest(BaseModel):
    url: str
    html: str | None = Field(None, description="Extract from this HTML instead of fetching the URL", max_length=10_000_000)
    render: bool = Field(False, description="Render with the headless browser (if enabled)")
    use_llm: bool = Field(False, description="Allow the LLM fallback (if configured)")
    include_html: bool = False

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


def domain_for(base_url: str) -> str:
    host = host_of(base_url)
    return host.removeprefix("www.")
