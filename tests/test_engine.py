import httpx
from sqlalchemy import func, select

from app.crawler.engine import CrawlEngine, Frontier
from app.db.models import Article, CrawlJob, Page, Source
from app.db.session import get_sessionmaker
from app.services.crawl import create_job, dispatch_due_sources, run_job
from tests.conftest import fixture_text
from tests.helpers import make_fetcher, site

HOST = "https://news.example.com"
ARTICLE = fixture_text("article_jsonld.html")


def article_html(slug: str, title: str, topic: str) -> str:
    """A distinct article per URL (different body so they are not duplicates)."""
    body = " ".join(f"Paragraph {i} about {topic} with details only found in the {slug} story." for i in range(25))
    return ARTICLE.replace("City approves sweeping transit plan", title).replace(
        "https://news.example.com/2024/05/14/city-approves-transit-plan", f"{HOST}/{slug}"
    ).replace("Supporters argued", body + " Supporters argued")


def build_site(log=None, extra=None):
    routes = {
        f"{HOST}/": """<html><head><link rel="alternate" type="application/rss+xml" href="/feed"></head>
            <body><a href="/2024/05/14/city-approves-transit-plan">a</a>
            <a href="/a/b/a/b/a/b/a/b">trap</a><a href="https://elsewhere.org/x">off</a>
            <a href="/private/secret-story-here-now">private</a>
            <a href="/2024/05/11/linked-only-story-here">linked</a></body></html>""",
        f"{HOST}/feed": fixture_text("rss.xml"),
        f"{HOST}/2024/05/14/city-approves-transit-plan": ARTICLE,
        f"{HOST}/2024/05/13/budget-vote-delayed-again": article_html("2024/05/13/budget-vote-delayed-again", "Budget vote delayed", "budgets"),
        f"{HOST}/2024/05/11/linked-only-story-here": article_html("2024/05/11/linked-only-story-here", "Linked story", "parks"),
        f"{HOST}/private/secret-story-here-now": ARTICLE,
    }
    routes.update(extra or {})
    return site(routes, robots="User-agent: *\nDisallow: /private/\n", log=log)


async def make_source(session, **kw) -> Source:
    defaults = dict(name="Example", base_url=f"{HOST}/", domain="news.example.com", allowed_domains=["news.example.com"],
                    start_urls=[], feed_urls=[], sitemap_urls=[], include_patterns=[], exclude_patterns=[],
                    max_pages=50, max_depth=2, min_delay_seconds=0, render_mode="never")
    defaults.update(kw)
    src = Source(**defaults)
    session.add(src)
    await session.commit()
    return src


def test_frontier_priority_and_limits():
    f = Frontier(max_size=2)
    assert f.push("a", 0, "seed", 0.1)
    assert f.push("b", 0, "seed", 0.9)
    assert not f.push("c", 0, "seed", 1.0)  # size cap
    assert not f.push("a", 0, "seed", 1.0)  # dedup
    assert f.pop().url == "b"


async def test_full_crawl(session):
    requested: list[str] = []
    source = await make_source(session)
    fetcher = make_fetcher(build_site(requested))
    engine = CrawlEngine(get_sessionmaker(), fetcher)
    stats = await engine.crawl(source)
    await fetcher.aclose()

    assert stats.articles_new == 3, stats
    assert stats.robots_blocked >= 1
    assert not any("elsewhere.org" in u for u in requested)
    assert not any("/a/b/a/b" in u for u in requested)
    assert not any("/private/" in u for u in requested if not u.endswith("robots.txt"))
    titles = set((await session.execute(select(Article.title))).scalars())
    assert titles == {"City approves sweeping transit plan", "Budget vote delayed", "Linked story"}
    art = (await session.execute(select(Article).where(Article.title == "Budget vote delayed"))).scalar_one()
    assert art.source_id == source.id and art.confidence > 0.8 and art.language == "en"


async def test_recrawl_skips_known_articles_and_does_not_duplicate(session):
    source = await make_source(session, discover_links=False, feed_urls=[f"{HOST}/feed"])
    requested: list[str] = []
    handler = build_site(requested)
    for _ in range(2):
        fetcher = make_fetcher(handler)
        await CrawlEngine(get_sessionmaker(), fetcher).crawl(source)
        await fetcher.aclose()
    story = f"{HOST}/2024/05/14/city-approves-transit-plan"
    assert requested.count(f"{HOST}/feed") == 2  # the feed is re-read every crawl
    assert requested.count(story) == 1  # but a story collected recently is not downloaded again
    assert (await session.execute(select(func.count(Article.id)))).scalar_one() == 2


async def test_feed_entries_beyond_page_limit_are_picked_up_next_crawl(session):
    """Regression: a 304 on the feed used to hide entries an earlier crawl never reached."""

    def feed(request):
        if request.headers.get("if-none-match"):
            return httpx.Response(304)
        return httpx.Response(200, headers={"etag": '"v1"', "content-type": "application/rss+xml"},
                              content=fixture_text("rss.xml").encode())

    source = await make_source(session, max_pages=1, discover_links=False, feed_urls=[f"{HOST}/feed"])
    handler = build_site(extra={f"{HOST}/feed": feed})
    for _ in range(2):
        fetcher = make_fetcher(handler)
        await CrawlEngine(get_sessionmaker(), fetcher).crawl(source)
        await fetcher.aclose()
    assert (await session.execute(select(func.count(Article.id)))).scalar_one() == 2


async def test_max_pages_limit(session):
    source = await make_source(session, max_pages=2)
    fetcher = make_fetcher(build_site())
    stats = await CrawlEngine(get_sessionmaker(), fetcher).crawl(source)
    await fetcher.aclose()
    assert stats.stopped_reason == "max_pages"
    assert stats.pages_fetched <= 2 + 4  # in-flight tasks may finish after the limit is reached


async def test_failing_urls_are_eventually_skipped(session):
    source = await make_source(session, start_urls=[f"{HOST}/broken"], discover_links=False, feed_urls=[f"{HOST}/none.xml"])
    calls = []

    def broken(request):
        calls.append(1)
        return httpx.Response(500)

    from tests.helpers import make_settings
    settings = make_settings(max_retries=0, max_page_failures=2)
    for _ in range(4):
        fetcher = make_fetcher(build_site(extra={f"{HOST}/broken": broken}), settings=settings)
        await CrawlEngine(get_sessionmaker(), fetcher, settings=settings).crawl(source)
        await fetcher.aclose()
    assert len(calls) == 2
    page = (await session.execute(select(Page).where(Page.url == f"{HOST}/broken"))).scalar_one()
    assert page.failure_count == 2


async def test_run_job_lifecycle(session):
    source = await make_source(session)
    job = await create_job(session, source)
    await session.commit()
    status = await run_job(job.id, fetcher=make_fetcher(build_site()))
    assert status == "succeeded"
    await session.refresh(job)
    assert job.status == "succeeded" and job.articles_new == 3 and job.finished_at is not None
    assert job.task_id == f"crawl-job-{job.id}"
    assert job.stats["stopped_reason"] == "frontier_exhausted"


async def test_scheduler_dispatches_due_sources_once(session):
    s1 = await make_source(session, name="one")
    await make_source(session, name="two", enabled=False)
    first = await dispatch_due_sources()
    second = await dispatch_due_sources()
    assert len(first) == 1 and second == []
    job = await session.get(CrawlJob, first[0])
    assert job.source_id == s1.id and job.trigger == "scheduled"


async def test_seed_fetches_do_not_consume_page_budget(session):
    # 3 sitemaps + 1 feed are seeds; with max_pages=2 we must still extract 2 articles.
    sm = f"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>{HOST}/sm-a.xml</loc></sitemap><sitemap><loc>{HOST}/sm-news.xml</loc></sitemap></sitemapindex>"""
    source = await make_source(session, max_pages=2, discover_links=False,
                               feed_urls=[f"{HOST}/feed"], sitemap_urls=[f"{HOST}/sitemap.xml"])
    extra = {f"{HOST}/sitemap.xml": sm, f"{HOST}/sm-a.xml": fixture_text("news_sitemap.xml"),
             f"{HOST}/sm-news.xml": fixture_text("news_sitemap.xml")}
    fetcher = make_fetcher(build_site(extra=extra))
    stats = await CrawlEngine(get_sessionmaker(), fetcher).crawl(source)
    await fetcher.aclose()
    assert stats.seed_fetches >= 3
    assert stats.articles_new == 2


async def test_unreachable_host_circuit_breaker(session):
    calls = []

    def timeout(request):
        calls.append(str(request.url))
        raise httpx.ReadTimeout("slow")

    from tests.helpers import make_settings

    settings = make_settings(max_retries=0)
    routes = {f"{HOST}/{i}-story-about-something-here": timeout for i in range(20)}
    feed = "<rss><channel>" + "".join(f"<item><link>{u}</link></item>" for u in routes) + "</channel></rss>"
    source = await make_source(session, feed_urls=[f"{HOST}/feed"], discover_links=False)
    fetcher = make_fetcher(build_site(extra={**routes, f"{HOST}/feed": feed}), settings=settings)
    stats = await CrawlEngine(get_sessionmaker(), fetcher, settings=settings).crawl(source)
    await fetcher.aclose()
    assert len(calls) < 12  # 5 failures trip the breaker (+ in-flight concurrency)
    assert stats.hosts_unreachable == ["news.example.com"]


async def test_manual_job_pushes_next_crawl(session):
    source = await make_source(session, crawl_interval_minutes=30)
    await create_job(session, source)
    await session.commit()
    assert await dispatch_due_sources() == []


async def test_stale_feed_and_sitemap_entries_are_ignored(session):
    from tests.helpers import make_settings

    settings = make_settings(max_article_age_days=30)
    source = await make_source(session, discover_links=False, feed_urls=[f"{HOST}/feed"],
                               sitemap_urls=[f"{HOST}/news-sitemap.xml"])
    fetcher = make_fetcher(build_site(extra={f"{HOST}/news-sitemap.xml": fixture_text("news_sitemap.xml")}), settings=settings)
    stats = await CrawlEngine(get_sessionmaker(), fetcher, settings=settings).crawl(source)
    await fetcher.aclose()
    assert stats.discovered == 0 and stats.articles_new == 0  # all fixture entries are from 2024


async def test_short_media_pages_are_not_articles():
    from app.extraction.pipeline import ExtractionPipeline

    html = ARTICLE.split("<article")[0] + "<article><h1>Watch: storm footage</h1><p>Video, 2 minutes.</p></article></body></html>"
    report = await ExtractionPipeline().run(f"{HOST}/2024/05/14/watch-storm-footage-video", html)
    assert not report.article.is_article
    assert any("too short" in r for r in report.classification.reasons)


async def test_depth_zero_still_crawls_feed_entries(session):
    source = await make_source(session, max_depth=0, feed_urls=[f"{HOST}/feed"])
    fetcher = make_fetcher(build_site())
    stats = await CrawlEngine(get_sessionmaker(), fetcher).crawl(source)
    await fetcher.aclose()
    # Both feed stories are fetched; links on pages (the linked-only story) are not followed.
    assert stats.articles_new == 2
    titles = set((await session.execute(select(Article.title))).scalars())
    assert "Linked story" not in titles
