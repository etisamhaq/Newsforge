"""Pluggable article search.

A backend implements `search()`; `index()`/`remove()` are hooks for external engines
(Elasticsearch, OpenSearch, Meilisearch, vector DBs) and are no-ops for DB-native backends.
Register new backends with `register_backend("name", factory)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article


@dataclass
class SearchQuery:
    q: str | None = None
    source_id: int | None = None
    language: str | None = None
    category: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    min_confidence: float | None = None
    include_duplicates: bool = False
    sort: str = "published"  # published | relevance | created
    limit: int = 20
    offset: int = 0


@dataclass
class SearchPage:
    items: list[Article]
    total: int
    backend: str
    scores: dict[int, float] = field(default_factory=dict)


def apply_filters(stmt: Select, query: SearchQuery) -> Select:
    if query.source_id is not None:
        stmt = stmt.where(Article.source_id == query.source_id)
    if query.language:
        stmt = stmt.where(Article.language == query.language.lower())
    if query.category:
        stmt = stmt.where(Article.category == query.category)
    if query.since:
        stmt = stmt.where(Article.published_at >= query.since)
    if query.until:
        stmt = stmt.where(Article.published_at < query.until)
    if query.min_confidence is not None:
        stmt = stmt.where(Article.confidence >= query.min_confidence)
    if not query.include_duplicates:
        stmt = stmt.where(Article.duplicate_of_id.is_(None))
    return stmt


def default_order(stmt: Select, query: SearchQuery) -> Select:
    if query.sort == "created":
        return stmt.order_by(Article.created_at.desc(), Article.id.desc())
    return stmt.order_by(Article.published_at.desc().nulls_last(), Article.id.desc())


class SearchBackend(ABC):
    name = "base"

    @abstractmethod
    async def search(self, session: AsyncSession, query: SearchQuery) -> SearchPage: ...

    async def index(self, article: Article) -> None:  # noqa: B027 - optional hook
        """Called after an article is created/updated."""

    async def remove(self, article_id: int) -> None:  # noqa: B027 - optional hook
        """Called after an article is deleted."""


_BACKENDS: dict[str, Callable[[], SearchBackend]] = {}


def register_backend(name: str, factory: Callable[[], SearchBackend]) -> None:
    _BACKENDS[name] = factory


def get_backend(name: str) -> SearchBackend:
    from app.search import backends  # noqa: F401 - registers built-ins

    try:
        return _BACKENDS[name]()
    except KeyError as exc:
        raise ValueError(f"unknown search backend {name!r}; available: {sorted(_BACKENDS)}") from exc


def get_search_backend(dialect: str | None = None) -> SearchBackend:
    from app.config import get_settings

    name = get_settings().search_backend
    if name == "auto":
        name = "postgres" if (dialect or ("postgresql" if get_settings().is_postgres else "sqlite")) == "postgresql" else "basic"
    return get_backend(name)


__all__ = ["SearchBackend", "SearchPage", "SearchQuery", "apply_filters", "default_order", "get_search_backend", "register_backend"]
