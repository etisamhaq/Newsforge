from __future__ import annotations

import httpx

from app.config import Settings
from app.crawler.fetcher import Fetcher
from app.crawler.security import UrlGuard

PUBLIC_IP = "93.184.216.34"


def public_resolver(overrides: dict[str, list[str]] | None = None):
    overrides = overrides or {}

    async def resolve(host: str, port: int) -> list[str]:
        return overrides.get(host, [PUBLIC_IP])

    return resolve


def make_settings(**kw) -> Settings:
    base = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        default_min_delay=0,
        retry_backoff_base=0,
        max_retries=2,
        respect_robots=True,
        max_article_age_days=0,
    )
    base.update(kw)
    return Settings(**base)


def make_fetcher(handler, *, settings: Settings | None = None, resolver_overrides=None, **kw) -> Fetcher:
    settings = settings or make_settings()
    guard = UrlGuard(allowed_ports=settings.allowed_ports, resolver=public_resolver(resolver_overrides))
    return Fetcher(settings, guard=guard, transport=httpx.MockTransport(handler), **kw)


def site(routes: dict[str, object], *, robots: str | None = "User-agent: *\nAllow: /\n", log: list | None = None):
    """Build a MockTransport handler from {url: body | (status, headers, body) | callable}."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if log is not None:
            log.append(url)
        if request.url.path == "/robots.txt" and url not in routes:
            if robots is None:
                return httpx.Response(404)
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"})
        spec = routes.get(url)
        if spec is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        if callable(spec):
            return spec(request)
        if isinstance(spec, tuple):
            status, headers, body = spec
            return httpx.Response(status, headers=headers, content=body if isinstance(body, bytes) else body.encode())
        ctype = "application/xml" if url.endswith((".xml", "/feed", "/rss")) else "text/html; charset=utf-8"
        return httpx.Response(200, headers={"content-type": ctype}, content=spec.encode())

    return handler
