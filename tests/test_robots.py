from app.crawler.robots import RobotsCache, RobotsRules

ROBOTS = """
User-agent: *
Disallow: /private/
Disallow: /*?print=
Allow: /private/public-note
Disallow: /*.pdf$
Crawl-delay: 2

User-agent: NewsforgeBot
Disallow: /no-bots/

Sitemap: https://example.com/sitemap.xml
"""
UA = "NewsforgeBot/0.1 (+https://github.com/etisamhaq/Newsforge)"


def test_rules_for_generic_agent():
    r = RobotsRules.parse(ROBOTS)
    assert not r.can_fetch("OtherBot/1.0", "https://example.com/private/x")
    assert r.can_fetch("OtherBot/1.0", "https://example.com/private/public-note")
    assert not r.can_fetch("OtherBot/1.0", "https://example.com/story?print=1")
    assert not r.can_fetch("OtherBot/1.0", "https://example.com/doc.pdf")
    assert r.can_fetch("OtherBot/1.0", "https://example.com/doc.pdf?x=1")
    assert r.crawl_delay("OtherBot") == 2
    assert r.sitemaps == ["https://example.com/sitemap.xml"]


def test_specific_group_overrides_generic():
    r = RobotsRules.parse(ROBOTS)
    assert not r.can_fetch(UA, "https://example.com/no-bots/a")
    assert r.can_fetch(UA, "https://example.com/private/x")  # generic group not merged


async def test_cache_status_handling():
    calls = []

    async def fetch(url):
        calls.append(url)
        return {"https://a.com/robots.txt": (404, ""), "https://b.com/robots.txt": (503, "")}[url]

    cache = RobotsCache(fetch, UA)
    assert await cache.allowed("https://a.com/x")
    assert not await cache.allowed("https://b.com/x")
    await cache.allowed("https://a.com/y")
    assert calls.count("https://a.com/robots.txt") == 1


async def test_cache_network_error_disallows():
    async def fetch(url):
        raise OSError("boom")

    assert not await RobotsCache(fetch, UA).allowed("https://c.com/x")


async def test_concurrent_lookups_fetch_robots_once():
    import asyncio

    calls = []

    async def fetch(url):
        calls.append(url)
        await asyncio.sleep(0.05)
        return 200, "User-agent: *\nDisallow: /x"

    cache = RobotsCache(fetch, UA)
    results = await asyncio.gather(*(cache.allowed(f"https://e.com/{i}") for i in range(10)))
    assert all(results) and len(calls) == 1
