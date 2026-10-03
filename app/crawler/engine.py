"""Crawl orchestration for one source.

seeds (feeds, sitemaps, start pages) -> prioritized frontier -> fetch -> extract -> dedup/persist
-> link discovery, bounded by max pages, depth, frontier size, time budget and trap heuristics.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.crawler.discovery import (
    COMMON_SITEMAP_PATHS,
    DiscoveredURL,
    article_url_score,
    discover_feed_links,
    extract_links,
    is_feed_content,
    is_sitemap_content,
    parse_feed,
    parse_sitemap,
)
from app.crawler.fetcher import Fetcher, FetchError, FetchResult, RobotsDisallowed
from app.crawler.renderer import PlaywrightRenderer, RenderError, looks_js_rendered
from app.crawler.security import BlockedURLError
from app.crawler.urls import (
    has_trap_pattern,
    host_of,
    is_same_site,
    looks_like_non_html,
    normalize_url,
    origin_of,
    url_hash,
)
from app.db.base import utcnow
from app.db.models import CrawlJob, JobStatus, Page, RenderMode, Source
from app.extraction.pipeline import ExtractionPipeline, ExtractionReport
from app.logging import get_logger
from app.metrics import DISCOVERED_TOTAL
from app.search.base import SearchBackend
from app.services.articles import ArticleRepository

log = get_logger(__name__)

MAX_SITEMAPS = 25
HOST_FAILURE_LIMIT = 5  # consecutive network failures before a host is skipped for the rest of the crawl
ARTICLE_REFRESH = timedelta(hours=24)


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    seed_fetches: int = 0  # feeds / sitemaps / homepage discovery; not counted against max_pages
    pages_failed: int = 0
    pages_skipped: int = 0
    not_modified: int = 0
    robots_blocked: int = 0
    rendered: int = 0
    articles_found: int = 0
    articles_new: int = 0
    articles_updated: int = 0
    duplicates: int = 0
    discovered: int = 0
    hosts_unreachable: list[str] = field(default_factory=list)
    stopped_reason: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["errors"] = self.errors[-20:]
        return d


@dataclass(order=True)
class _Item:
    priority: float
    seq: int
    url: str = field(compare=False)
    depth: int = field(compare=False)
    via: str = field(compare=False)


class Frontier:
    """Max-priority queue with URL de-duplication and a hard size cap."""

    def __init__(self, max_size: int):
        self._heap: list[_Item] = []
        self._seen: set[str] = set()
        self._seq = itertools.count()
        self.max_size = max_size

    def push(self, url: str, depth: int, via: str, priority: float) -> bool:
        if url in self._seen or len(self._seen) >= self.max_size:
            return False
        self._seen.add(url)
        heapq.heappush(self._heap, _Item(-priority, next(self._seq), url, depth, via))
        return True

    def pop(self) -> _Item | None:
        return heapq.heappop(self._heap) if self._heap else None

    def seen(self, url: str) -> bool:
        return url in self._seen

    def __len__(self) -> int:
        return len(self._heap)


class CrawlEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        fetcher: Fetcher,
        pipeline: ExtractionPipeline | None = None,
        *,
        renderer: PlaywrightRenderer | None = None,
        search_backend: SearchBackend | None = None,
        settings: Settings | None = None,
    ):
        self.session_factory = session_factory
        self.fetcher = fetcher
        self.pipeline = pipeline or ExtractionPipeline()
        self.renderer = renderer
        self.search_backend = search_backend
        self.settings = settings or get_settings()
        self._host_failures: dict[str, int] = {}

    # ------------------------------------------------------------------ scope
    def _domains(self, source: Source) -> list[str]:
        return source.allowed_domains or [source.domain]

    def in_scope(self, url: str, source: Source) -> str | None:
        """Return a reason string if the URL must be skipped, else None."""
        if not url.startswith(("http://", "https://")):
            return "scheme"
        if len(url) > self.settings.max_url_length:
            return "too_long"
        if not is_same_site(url, self._domains(source)):
            return "off_site"
        if looks_like_non_html(url):
            return "non_html"
        if has_trap_pattern(url):
            return "trap"
        if source.exclude_patterns and any(re.search(p, url) for p in source.exclude_patterns):
            return "excluded"
        return None

    def _included(self, url: str, source: Source) -> bool:
        return not source.include_patterns or any(re.search(p, url) for p in source.include_patterns)

    # ------------------------------------------------------------------ page cache
    async def _get_page(self, session: AsyncSession, url: str) -> Page | None:
        return (await session.execute(select(Page).where(Page.url_hash == url_hash(url)))).scalar_one_or_none()

    async def _record_page(
        self, url: str, source_id: int, *, result: FetchResult | None = None, error: str | None = None,
        is_article: bool | None = None, content_hash: str | None = None,
    ) -> int | None:
        async with self.session_factory() as session:
            page = await self._get_page(session, url)
            if page is None:
                page = Page(url=url, url_hash=url_hash(url), source_id=source_id, fetch_count=0, failure_count=0)
                session.add(page)
            page.fetch_count += 1
            page.last_fetched_at = utcnow()
            if error:
                page.failure_count += 1
                page.last_error = error[:1000]
            if result is not None:
                page.status_code = result.status_code
                if not result.not_modified:
                    page.etag = (result.etag or "")[:512] or None
                    page.last_modified = (result.last_modified or "")[:128] or None
                if result.ok:
                    page.failure_count = 0
                    page.last_error = None
            if is_article is not None:
                page.is_article = is_article
            if content_hash:
                page.content_hash = content_hash
            await session.commit()
            return page.id

    async def _cached_fetch(
        self, url: str, source: Source, stats: CrawlStats, *, conditional: bool = True, seed: bool = False,
        max_bytes: int | None = None,
    ) -> FetchResult | None:
        """Fetch with HTTP cache validators; returns None when skipped / unchanged / failed."""
        async with self.session_factory() as session:
            page = await self._get_page(session, url)
        if page is not None and page.failure_count >= self.settings.max_page_failures:
            stats.pages_skipped += 1
            return None
        host = host_of(url)
        if self._host_failures.get(host, 0) >= HOST_FAILURE_LIMIT:
            stats.pages_skipped += 1
            stats.hosts_unreachable = sorted(set(stats.hosts_unreachable) | {host})
            return None
        try:
            result = await self.fetcher.fetch(
                url,
                etag=page.etag if (page and conditional) else None,
                last_modified=page.last_modified if (page and conditional) else None,
                max_bytes=max_bytes,
            )
        except RobotsDisallowed:
            stats.robots_blocked += 1
            return None
        except (FetchError, BlockedURLError) as exc:
            stats.pages_failed += 1
            stats.errors.append(f"{url}: {exc}")
            if isinstance(exc, FetchError) and exc.reason.startswith("network error"):
                self._host_failures[host] = self._host_failures.get(host, 0) + 1
            await self._record_page(url, source.id, error=str(exc))
            return None
        self._host_failures[host] = 0
        if seed:
            stats.seed_fetches += 1
        else:
            stats.pages_fetched += 1
        if result.not_modified:
            stats.not_modified += 1
            await self._record_page(url, source.id, result=result)
            return None
        if not result.ok:
            stats.pages_failed += 1
            await self._record_page(url, source.id, result=result, error=f"HTTP {result.status_code}")
            return None
        return result

    # ------------------------------------------------------------------ seeding
    async def _seed(self, source: Source, frontier: Frontier, stats: CrawlStats) -> None:
        base = normalize_url(source.base_url)
        start_urls = [normalize_url(u, base) for u in (source.start_urls or [])] or [base]
        feeds = [normalize_url(u, base) for u in (source.feed_urls or [])]
        sitemaps = [normalize_url(u, base) for u in (source.sitemap_urls or [])]

        if not feeds and not sitemaps:
            # Auto-discover: <link rel=alternate> feeds on the homepage and Sitemap: lines in robots.txt.
            home = await self._cached_fetch(base, source, stats, conditional=False, seed=True)
            if home is not None and home.is_html:
                feeds = discover_feed_links(home.text, home.final_url)[:5]
            rules = await self.fetcher.robots.rules_for(base)
            robots_sitemaps = sorted(rules.sitemaps, key=lambda u: "news" not in u.lower())
            sitemaps = [normalize_url(u, base) for u in robots_sitemaps][:5]
            if not feeds and not sitemaps:
                sitemaps = [origin_of(base) + p for p in COMMON_SITEMAP_PATHS[:1]]

        for feed in feeds:
            for item in await self._load_feed(feed, source, stats):
                self._enqueue(frontier, item, 1, source, stats, boost=1.0)
        for item in await self._load_sitemaps(sitemaps, source, stats):
            self._enqueue(frontier, item, 1, source, stats, boost=0.8)
        for url in start_urls:
            frontier.push(url, 0, "seed", priority=0.5)

    async def _load_feed(self, url: str, source: Source, stats: CrawlStats) -> list[DiscoveredURL]:
        res = await self._cached_fetch(url, source, stats, seed=True)
        if res is None:
            return []
        await self._record_page(url, source.id, result=res, is_article=False)
        items = parse_feed(res.content, res.final_url)
        DISCOVERED_TOTAL.labels("feed").inc(len(items))
        return items

    async def _load_sitemaps(self, urls: list[str], source: Source, stats: CrawlStats) -> list[DiscoveredURL]:
        out: list[DiscoveredURL] = []
        queue, seen = list(urls), set()
        enough = max(source.max_pages * 3, 100)
        while queue and len(seen) < MAX_SITEMAPS and len(out) < enough:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            res = await self._cached_fetch(sm, source, stats, seed=True, max_bytes=self.settings.max_sitemap_bytes)
            if res is None:
                continue
            await self._record_page(sm, source.id, result=res, is_article=False)
            if not is_sitemap_content(res.content):
                continue
            items, children = parse_sitemap(res.content, res.final_url)
            out.extend(i for i in items if not self._too_old(i))
            # Visit news sitemaps first, then the most recently modified; skip stale archive sitemaps.
            children = [c for c in children if is_same_site(c.url, self._domains(source)) and not self._too_old(c)]
            children.sort(key=lambda c: ("news" not in c.url.lower(), -(c.lastmod.timestamp() if c.lastmod else 0)))
            queue[:0] = [c.url for c in children]
        DISCOVERED_TOTAL.labels("sitemap").inc(len(out))
        # Most recent first so large archives don't starve fresh stories.
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        out.sort(key=lambda d: d.published_at or d.lastmod or epoch, reverse=True)
        return out[: max(source.max_pages * 3, 100)]

    def _too_old(self, item: DiscoveredURL) -> bool:
        max_age = self.settings.max_article_age_days
        ts = item.published_at or item.lastmod
        return bool(max_age and ts is not None and datetime.now(timezone.utc) - ts > timedelta(days=max_age))

    def _enqueue(self, frontier: Frontier, item: DiscoveredURL, depth: int, source: Source, stats: CrawlStats, boost: float = 0.0) -> None:
        if self.in_scope(item.url, source) is not None or not self._included(item.url, source) or self._too_old(item):
            return
        recency = 0.0
        ts = item.published_at or item.lastmod
        if ts is not None:
            age_days = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400)
            recency = max(0.0, 1 - age_days / 30) * 0.5
        if frontier.push(item.url, depth, item.via, priority=boost + recency + article_url_score(item.url)):
            stats.discovered += 1

    # ------------------------------------------------------------------ pages
    async def _should_refetch_article(self, url: str) -> bool:
        async with self.session_factory() as session:
            page = await self._get_page(session, url)
        if page is None or not page.is_article or page.last_fetched_at is None:
            return True
        last = page.last_fetched_at if page.last_fetched_at.tzinfo else page.last_fetched_at.replace(tzinfo=timezone.utc)
        return utcnow() - last > ARTICLE_REFRESH

    async def _extract(self, source: Source, result: FetchResult, stats: CrawlStats) -> tuple[ExtractionReport, str, bool]:
        html = result.text
        url = result.final_url
        report = await self.pipeline.run(url, html, result.headers)
        rendered = False
        mode = source.render_mode
        want_render = mode == RenderMode.always.value or (
            mode == RenderMode.auto.value
            and looks_js_rendered(html, report.article.word_count, self.settings.min_article_words)
        )
        if want_render and self.renderer is not None and self.settings.playwright_enabled:
            try:
                final_url, rendered_html = await self.renderer.render(url)
                rendered_report = await self.pipeline.run(final_url, rendered_html, result.headers)
                if rendered_report.article.confidence >= report.article.confidence:
                    report, html, rendered = rendered_report, rendered_html, True
                    stats.rendered += 1
            except (RenderError, BlockedURLError) as exc:
                stats.errors.append(f"render {url}: {exc}")
        return report, html, rendered

    async def _process(self, item: _Item, source: Source, frontier: Frontier, stats: CrawlStats) -> None:
        if item.via in ("feed", "sitemap") and not await self._should_refetch_article(item.url):
            stats.pages_skipped += 1
            return
        result = await self._cached_fetch(item.url, source, stats)
        if result is None:
            return
        if not result.is_html:
            # A link that turned out to be a feed or sitemap: harvest it instead of extracting.
            if is_feed_content(result.content, result.content_type):
                for d in parse_feed(result.content, result.final_url):
                    self._enqueue(frontier, d, item.depth + 1, source, stats, boost=0.5)
            elif is_sitemap_content(result.content):
                for d in parse_sitemap(result.content, result.final_url)[0]:
                    self._enqueue(frontier, d, item.depth + 1, source, stats, boost=0.3)
            await self._record_page(item.url, source.id, result=result, is_article=False)
            return
        if result.final_url != item.url:
            final = normalize_url(result.final_url)
            if self.in_scope(final, source) is not None:
                stats.pages_skipped += 1
                return

        report, html, rendered = await self._extract(source, result, stats)
        art = report.article
        is_article = art.is_article and self._included(art.canonical_url, source)
        page_id = await self._record_page(item.url, source.id, result=result, is_article=is_article)

        if is_article:
            stats.articles_found += 1
            async with self.session_factory() as session:
                repo = ArticleRepository(session, self.search_backend)
                raw = html.encode("utf-8") if source.store_raw_html else None
                upsert = await repo.upsert(
                    art, source.id, raw_html=raw,
                    raw_meta={"page_id": page_id, "url": result.final_url, "status_code": result.status_code,
                              "headers": dict(list(result.headers.items())[:50]), "rendered": rendered},
                )
                await session.commit()
            if upsert.outcome == "new":
                stats.articles_new += 1
            elif upsert.outcome == "updated":
                stats.articles_updated += 1
            elif upsert.outcome in ("duplicate", "near_duplicate"):
                stats.duplicates += 1

        if source.discover_links and item.depth < source.max_depth and not art.nofollow:
            for link in extract_links(html, result.final_url):
                if frontier.seen(link) or self.in_scope(link, source) is not None:
                    continue
                self._enqueue(frontier, DiscoveredURL(link, "link"), item.depth + 1, source, stats)

    # ------------------------------------------------------------------ main loop
    async def _cancelled(self, job_id: int | None) -> bool:
        if job_id is None:
            return False
        async with self.session_factory() as session:
            status = (await session.execute(select(CrawlJob.status).where(CrawlJob.id == job_id))).scalar_one_or_none()
        return status == JobStatus.cancelled.value

    async def _report_progress(self, job_id: int | None, stats: CrawlStats) -> None:
        if job_id is None:
            return
        async with self.session_factory() as session:
            job = await session.get(CrawlJob, job_id)
            if job is not None:
                job.pages_fetched = stats.pages_fetched
                job.articles_new = stats.articles_new
                job.stats = stats.as_dict()
                await session.commit()

    async def crawl(self, source: Source, job_id: int | None = None) -> CrawlStats:
        s = self.settings
        stats = CrawlStats()
        for domain in self._domains(source):
            self.fetcher.set_host_delay(host_of(f"https://{domain}/"), source.min_delay_seconds)
            self.fetcher.set_host_delay(host_of(f"https://www.{domain.removeprefix('www.')}/"), source.min_delay_seconds)
        frontier = Frontier(s.max_frontier_size)
        deadline = time.monotonic() + s.crawl_time_budget_seconds
        log.info("crawl.start", source=source.name, job_id=job_id)

        await self._seed(source, frontier, stats)

        processed = 0
        in_flight: set[asyncio.Task] = set()
        concurrency = max(1, s.crawl_concurrency)

        async def run(item: _Item) -> None:
            try:
                await self._process(item, source, frontier, stats)
            except Exception as exc:  # noqa: BLE001 - one bad page must not kill the crawl
                stats.pages_failed += 1
                stats.errors.append(f"{item.url}: {type(exc).__name__}: {exc}"[:500])
                log.exception("crawl.page_error", url=item.url)

        while True:
            if stats.pages_fetched >= source.max_pages:
                stats.stopped_reason = "max_pages"
                break
            if time.monotonic() > deadline:
                stats.stopped_reason = "time_budget"
                break
            budget_left = source.max_pages - stats.pages_fetched - len(in_flight)
            item = frontier.pop() if len(in_flight) < concurrency and budget_left > 0 else None
            if item is None:
                if not in_flight:
                    stats.stopped_reason = stats.stopped_reason or "frontier_exhausted"
                    break
                _done, in_flight = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                continue
            if item.depth > source.max_depth:
                continue
            in_flight.add(asyncio.create_task(run(item)))
            processed += 1
            if processed % 20 == 0:
                if await self._cancelled(job_id):
                    stats.stopped_reason = "cancelled"
                    break
                await self._report_progress(job_id, stats)

        if in_flight:
            await asyncio.wait(in_flight)
        log.info("crawl.finish", source=source.name, job_id=job_id, **{k: v for k, v in stats.as_dict().items() if k != "errors"})
        return stats
