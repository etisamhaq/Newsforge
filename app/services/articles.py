"""Article persistence with layered deduplication.

1. canonical URL  -> same story: update in place when the content changed
2. content hash   -> exact copy under another URL: stored, linked via duplicate_of_id
3. SimHash bands  -> near-duplicate (syndication, minor edits): stored, linked via duplicate_of_id
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crawler.urls import url_hash
from app.db.models import Article, RawDocument
from app.dedup.hashing import bands, content_hash, hamming, simhash, to_signed, to_unsigned
from app.extraction.pipeline import ExtractedArticle
from app.metrics import ARTICLES_TOTAL
from app.search.base import SearchBackend

MIN_WORDS_FOR_NEAR_DUP = 50
UPDATABLE_FIELDS = (
    "url", "title", "description", "body", "authors", "published_at", "modified_at", "image_url",
    "category", "tags", "language", "site_name", "word_count", "extraction_method", "confidence", "article_score",
)


@dataclass
class UpsertResult:
    article: Article
    outcome: str  # new | updated | unchanged | duplicate | near_duplicate
    duplicate_of: int | None = None
    distance: int | None = None


class ArticleRepository:
    def __init__(self, session: AsyncSession, search_backend: SearchBackend | None = None):
        self.session = session
        self.search_backend = search_backend
        self.settings = get_settings()

    async def find_by_canonical(self, canonical_url: str) -> Article | None:
        return (
            await self.session.execute(select(Article).where(Article.canonical_hash == url_hash(canonical_url)))
        ).scalar_one_or_none()

    async def find_exact_duplicate(self, chash: str, exclude_id: int | None = None) -> Article | None:
        stmt = select(Article).where(Article.content_hash == chash, Article.duplicate_of_id.is_(None))
        if exclude_id:
            stmt = stmt.where(Article.id != exclude_id)
        return (await self.session.execute(stmt.order_by(Article.id).limit(1))).scalar_one_or_none()

    async def find_near_duplicate(self, sh: int, exclude_id: int | None = None) -> tuple[Article, int] | None:
        b = bands(sh)
        stmt = (
            select(Article)
            .where(
                Article.duplicate_of_id.is_(None),
                or_(Article.simhash_b0 == b[0], Article.simhash_b1 == b[1],
                    Article.simhash_b2 == b[2], Article.simhash_b3 == b[3]),
            )
            .order_by(Article.id)
            .limit(500)
        )
        if exclude_id:
            stmt = stmt.where(Article.id != exclude_id)
        best: tuple[Article, int] | None = None
        for cand in (await self.session.execute(stmt)).scalars():
            if cand.simhash is None:
                continue
            d = hamming(sh, to_unsigned(cand.simhash))
            if d <= self.settings.simhash_max_distance and (best is None or d < best[1]):
                best = (cand, d)
        return best

    @staticmethod
    def _apply(article: Article, ex: ExtractedArticle, chash: str | None, sh: int | None) -> None:
        values = {
            "url": ex.url, "title": ex.title, "description": ex.description, "body": ex.body,
            "authors": ex.authors, "published_at": ex.published_at, "modified_at": ex.modified_at,
            "image_url": ex.image_url, "category": ex.category, "tags": ex.tags, "language": ex.language,
            "site_name": ex.site_name, "word_count": ex.word_count, "extraction_method": ex.primary_method,
            "confidence": ex.confidence, "article_score": ex.article_score,
        }
        for k in UPDATABLE_FIELDS:
            setattr(article, k, values[k])
        article.content_hash = chash
        if sh is not None:
            article.simhash = to_signed(sh)
            article.simhash_b0, article.simhash_b1, article.simhash_b2, article.simhash_b3 = bands(sh)
        else:
            article.simhash = article.simhash_b0 = article.simhash_b1 = article.simhash_b2 = article.simhash_b3 = None
        article.extra = {
            **(article.extra or {}),
            "field_sources": ex.field_sources,
            **({"external_canonical": ex.external_canonical} if ex.external_canonical else {}),
        }

    async def upsert(
        self,
        ex: ExtractedArticle,
        source_id: int | None,
        *,
        raw_html: bytes | None = None,
        raw_meta: dict | None = None,
        _retry: bool = True,
    ) -> UpsertResult:
        chash = content_hash(ex.body)
        sh = simhash(ex.body) if ex.word_count >= MIN_WORDS_FOR_NEAR_DUP else None

        existing = await self.find_by_canonical(ex.canonical_url)
        if existing is not None:
            if existing.content_hash == chash and existing.title == ex.title:
                ARTICLES_TOTAL.labels("unchanged").inc()
                return UpsertResult(existing, "unchanged")
            if ex.confidence + 0.1 < existing.confidence:
                # Don't overwrite a good extraction with a clearly worse one.
                ARTICLES_TOTAL.labels("unchanged").inc()
                return UpsertResult(existing, "unchanged")
            self._apply(existing, ex, chash, sh)
            await self._store_raw(existing, raw_html, raw_meta)
            await self.session.flush()
            await self._index(existing)
            ARTICLES_TOTAL.labels("updated").inc()
            return UpsertResult(existing, "updated")

        outcome, dup_of, distance = "new", None, None
        if chash and (exact := await self.find_exact_duplicate(chash)):
            outcome, dup_of = "duplicate", exact.id
        elif sh is not None and (near := await self.find_near_duplicate(sh)):
            outcome, dup_of, distance = "near_duplicate", near[0].id, near[1]

        article = Article(
            source_id=source_id,
            canonical_url=ex.canonical_url,
            canonical_hash=url_hash(ex.canonical_url),
            duplicate_of_id=dup_of,
        )
        self._apply(article, ex, chash, sh)
        if distance is not None:
            article.extra["simhash_distance"] = distance
        try:
            async with self.session.begin_nested():
                self.session.add(article)
                await self.session.flush()
        except IntegrityError:
            # Another worker inserted the same canonical URL concurrently: retry as update.
            if not _retry:
                raise
            return await self.upsert(ex, source_id, raw_html=raw_html, raw_meta=raw_meta, _retry=False)
        await self._store_raw(article, raw_html, raw_meta)
        if outcome == "new":
            await self._index(article)
        ARTICLES_TOTAL.labels(outcome).inc()
        return UpsertResult(article, outcome, dup_of, distance)

    async def _store_raw(self, article: Article, raw_html: bytes | None, meta: dict | None) -> None:
        if raw_html is None:
            return
        meta = meta or {}
        self.session.add(
            RawDocument(
                article_id=article.id,
                page_id=meta.get("page_id"),
                url=meta.get("url", article.url),
                status_code=meta.get("status_code"),
                headers=meta.get("headers", {}),
                content_gzip=gzip.compress(raw_html, compresslevel=6),
                rendered=bool(meta.get("rendered")),
            )
        )
        await self.session.flush()

    async def _index(self, article: Article) -> None:
        if self.search_backend is not None:
            await self.search_backend.index(article)
