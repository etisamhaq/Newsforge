import gzip

import httpx
import pytest

from app.crawler.fetcher import FetchError, RobotsDisallowed
from app.crawler.security import BlockedURLError
from tests.helpers import make_fetcher, make_settings, site

HTML = "<html><head><title>x</title></head><body>hello</body></html>"


async def test_basic_fetch_and_redirect():
    handler = site({
        "https://news.example.com/old": (301, {"location": "/new"}, ""),
        "https://news.example.com/new": HTML,
    })
    async with make_fetcher(handler) as f:
        res = await f.fetch("https://news.example.com/old")
    assert res.ok and res.final_url == "https://news.example.com/new"
    assert res.redirects == ["https://news.example.com/old"]
    assert "hello" in res.text and res.is_html


async def test_redirect_to_private_ip_is_blocked():
    handler = site({"https://news.example.com/r": (302, {"location": "http://169.254.169.254/meta"}, "")})
    async with make_fetcher(handler) as f:
        with pytest.raises(BlockedURLError):
            await f.fetch("https://news.example.com/r")


async def test_redirect_loop_and_limit():
    handler = site({
        "https://news.example.com/a": (302, {"location": "/b"}, ""),
        "https://news.example.com/b": (302, {"location": "/a"}, ""),
    })
    async with make_fetcher(handler) as f:
        with pytest.raises(FetchError, match="redirect loop"):
            await f.fetch("https://news.example.com/a")


async def test_robots_disallowed():
    handler = site({"https://news.example.com/private/x": HTML}, robots="User-agent: *\nDisallow: /private/")
    async with make_fetcher(handler) as f:
        with pytest.raises(RobotsDisallowed):
            await f.fetch("https://news.example.com/private/x")
        assert await f.is_allowed("https://news.example.com/public")


async def test_retries_then_succeeds():
    attempts = {"n": 0}

    def flaky(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, html=HTML)

    async with make_fetcher(site({"https://news.example.com/f": flaky})) as f:
        res = await f.fetch("https://news.example.com/f")
    assert res.ok and res.attempts == 3


async def test_retries_are_bounded():
    calls = {"n": 0}

    def always_fail(request):
        calls["n"] += 1
        return httpx.Response(500)

    settings = make_settings(max_retries=2)
    async with make_fetcher(site({"https://news.example.com/f": always_fail}), settings=settings) as f:
        res = await f.fetch("https://news.example.com/f")
    assert res.status_code == 500 and calls["n"] == 3


async def test_retry_after_too_long_gives_up():
    calls = {"n": 0}

    def limited(request):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "9999"})

    async with make_fetcher(site({"https://news.example.com/f": limited})) as f:
        res = await f.fetch("https://news.example.com/f")
    assert res.status_code == 429 and calls["n"] == 1


async def test_network_errors_retry_and_raise():
    def boom(request):
        raise httpx.ConnectError("refused")

    async with make_fetcher(site({"https://news.example.com/f": boom})) as f:
        with pytest.raises(FetchError, match="network error"):
            await f.fetch("https://news.example.com/f")


async def test_oversized_response_rejected():
    big = "x" * 5000
    settings = make_settings(max_response_bytes=1000)
    async with make_fetcher(site({"https://news.example.com/big": big}), settings=settings) as f:
        with pytest.raises(FetchError, match="too large|exceeded"):
            await f.fetch("https://news.example.com/big")


async def test_oversized_streamed_without_content_length():
    def stream(request):
        async def gen():
            for _ in range(10):
                yield b"y" * 500

        return httpx.Response(200, headers={"content-type": "text/html"}, content=gen())

    settings = make_settings(max_response_bytes=1000)
    async with make_fetcher(site({"https://news.example.com/s": stream}), settings=settings) as f:
        with pytest.raises(FetchError, match="exceeded"):
            await f.fetch("https://news.example.com/s")


async def test_gzip_bomb_rejected():
    bomb = gzip.compress(b"\0" * 200_000)
    settings = make_settings(max_response_bytes=50_000)
    handler = site({"https://news.example.com/sitemap.xml.gz": (200, {"content-type": "application/gzip"}, bomb)})
    async with make_fetcher(handler, settings=settings) as f:
        with pytest.raises(FetchError, match="gzip"):
            await f.fetch("https://news.example.com/sitemap.xml.gz")


async def test_gzip_sitemap_decompressed():
    payload = gzip.compress(b"<urlset></urlset>")
    handler = site({"https://news.example.com/s.xml.gz": (200, {"content-type": "application/x-gzip"}, payload)})
    async with make_fetcher(handler) as f:
        res = await f.fetch("https://news.example.com/s.xml.gz")
    assert res.content == b"<urlset></urlset>"


async def test_conditional_get_304():
    def cond(request):
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(200, html=HTML, headers={"etag": '"v1"'})

    async with make_fetcher(site({"https://news.example.com/c": cond})) as f:
        first = await f.fetch("https://news.example.com/c")
        second = await f.fetch("https://news.example.com/c", etag=first.etag)
    assert first.etag == '"v1"' and second.not_modified


async def test_unsupported_content_type():
    handler = site({"https://news.example.com/img": (200, {"content-type": "image/png"}, b"\x89PNG")})
    async with make_fetcher(handler) as f:
        with pytest.raises(FetchError, match="content-type"):
            await f.fetch("https://news.example.com/img")


async def test_charset_from_meta():
    body = '<html><head><meta charset="iso-8859-1"></head><body>caf\xe9</body></html>'.encode("latin-1")
    handler = site({"https://news.example.com/l": (200, {"content-type": "text/html"}, body)})
    async with make_fetcher(handler) as f:
        res = await f.fetch("https://news.example.com/l")
    assert "café" in res.text
