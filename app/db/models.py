"""Database models."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, JSONType, utcnow


class RenderMode(str, enum.Enum):
    never = "never"
    auto = "auto"
    always = "always"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    start_urls: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    feed_urls: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    sitemap_urls: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    include_patterns: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    exclude_patterns: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    crawl_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    min_delay_seconds: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    render_mode: Mapped[str] = mapped_column(String(16), default=RenderMode.auto.value, nullable=False)
    store_raw_html: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discover_links: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    jobs: Mapped[list[CrawlJob]] = relationship(back_populates="source", cascade="all, delete-orphan")


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.pending.value, nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64))
    triggered_by: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    articles_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    articles_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    articles_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    source: Mapped[Source] = relationship(back_populates="jobs")


class Page(Base):
    """Every URL the crawler fetched: HTTP cache validators and failure bookkeeping."""

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    is_article: Mapped[bool | None] = mapped_column(Boolean)
    fetch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Article(TimestampMixin, Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), index=True)
    site_name: Mapped[str | None] = mapped_column(String(255))
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    # 4 x 16-bit bands of the simhash for indexed near-duplicate candidate lookup
    simhash_b0: Mapped[int | None] = mapped_column(Integer, index=True)
    simhash_b1: Mapped[int | None] = mapped_column(Integer, index=True)
    simhash_b2: Mapped[int | None] = mapped_column(Integer, index=True)
    simhash_b3: Mapped[int | None] = mapped_column(Integer, index=True)
    extraction_method: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    article_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), index=True
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    __table_args__ = (Index("ix_articles_source_published", "source_id", "published_at"),)


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    content_gzip: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rendered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MemberRole(str, enum.Enum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"


class Member(TimestampMixin, Base):
    """A person allowed to use Newsforge. Identity comes from Supabase Auth; access from here."""

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # Supabase auth user id; filled in the first time the invited person signs in.
    user_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default=MemberRole.viewer.value, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(String(320))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
