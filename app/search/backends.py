from __future__ import annotations

import re

from sqlalchemy import and_, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article
from app.search.base import (
    SearchBackend,
    SearchPage,
    SearchQuery,
    apply_filters,
    default_order,
    register_backend,
)


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()


class BasicSearchBackend(SearchBackend):
    """Portable LIKE-based search (every term must appear in title, description or body)."""

    name = "basic"

    async def search(self, session: AsyncSession, query: SearchQuery) -> SearchPage:
        stmt = apply_filters(select(Article), query)
        terms = [t for t in re.split(r"\s+", (query.q or "").strip()) if t][:10]
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            stmt = stmt.where(
                or_(
                    Article.title.ilike(pattern, escape="\\"),
                    Article.description.ilike(pattern, escape="\\"),
                    Article.body.ilike(pattern, escape="\\"),
                )
            )
        total = await _count(session, stmt)
        stmt = default_order(stmt, query).limit(query.limit).offset(query.offset)
        items = list((await session.execute(stmt)).scalars())
        return SearchPage(items, total, self.name)


class PostgresSearchBackend(SearchBackend):
    """Postgres full-text search over the generated, GIN-indexed `search_vector` column."""

    name = "postgres"

    async def search(self, session: AsyncSession, query: SearchQuery) -> SearchPage:
        if not (query.q or "").strip():
            page = await BasicSearchBackend().search(session, query)  # plain filtered listing
            page.backend = self.name
            return page
        tsq = func.websearch_to_tsquery(text("'simple'"), query.q)
        vector = literal_column("articles.search_vector")
        rank = func.ts_rank_cd(vector, tsq).label("rank")
        stmt = apply_filters(select(Article, rank), query).where(and_(vector.op("@@")(tsq)))
        total = await _count(session, stmt)
        if query.sort == "relevance":
            stmt = stmt.order_by(rank.desc(), Article.published_at.desc().nulls_last())
        else:
            stmt = default_order(stmt, query)
        rows = (await session.execute(stmt.limit(query.limit).offset(query.offset))).all()
        return SearchPage([r[0] for r in rows], total, self.name, scores={r[0].id: float(r[1]) for r in rows})


register_backend("basic", BasicSearchBackend)
register_backend("postgres", PostgresSearchBackend)
