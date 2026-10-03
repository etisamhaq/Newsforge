from __future__ import annotations

import gzip
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.models import Article, RawDocument
from app.schemas import ArticleDetail, ArticlePage, ArticleSummary
from app.search.base import SearchQuery, get_search_backend

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ArticlePage)
async def list_articles(
    q: str | None = Query(None, max_length=500, description="Full-text query"),
    source_id: int | None = None,
    language: str | None = Query(None, max_length=8),
    category: str | None = Query(None, max_length=255),
    since: datetime | None = Query(None, description="published_at >= since"),
    until: datetime | None = Query(None, description="published_at < until"),
    min_confidence: float | None = Query(None, ge=0, le=1),
    include_duplicates: bool = False,
    sort: Literal["published", "relevance", "created"] = "published",
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    query = SearchQuery(q=q, source_id=source_id, language=language, category=category, since=since, until=until,
                        min_confidence=min_confidence, include_duplicates=include_duplicates, sort=sort,
                        limit=limit, offset=offset)
    backend = get_search_backend(session.bind.dialect.name)
    page = await backend.search(session, query)
    items = []
    for a in page.items:
        item = ArticleSummary.model_validate(a)
        item.score = page.scores.get(a.id)
        items.append(item)
    return {"items": items, "total": page.total, "limit": limit, "offset": offset, "backend": page.backend}


async def _get_article(session: AsyncSession, article_id: int) -> Article:
    article = await session.get(Article, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "article not found")
    return article


@router.get("/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: int, session: AsyncSession = Depends(get_session)) -> Article:
    return await _get_article(session, article_id)


@router.get("/{article_id}/duplicates", response_model=list[ArticleSummary])
async def get_duplicates(article_id: int, session: AsyncSession = Depends(get_session)) -> list[Article]:
    await _get_article(session, article_id)
    stmt = select(Article).where(Article.duplicate_of_id == article_id).order_by(Article.id).limit(200)
    return list((await session.execute(stmt)).scalars())


@router.get("/{article_id}/raw")
async def get_raw_html(article_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    await _get_article(session, article_id)
    raw = (
        await session.execute(
            select(RawDocument).where(RawDocument.article_id == article_id).order_by(RawDocument.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if raw is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no raw html stored for this article")
    # Served as text/plain so stored third-party HTML can never execute in our origin.
    return Response(
        gzip.decompress(raw.content_gzip),
        media_type="text/plain; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                 "X-Fetched-At": raw.fetched_at.isoformat(), "X-Source-Url": raw.url},
    )
