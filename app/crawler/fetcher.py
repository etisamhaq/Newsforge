"""Polite, hardened HTTP fetcher built on httpx.

- SSRF guard on the initial URL and every redirect hop (+ connect-time IP pinning)
- robots.txt enforcement on every hop
- per-host rate limiting (+ robots Crawl-delay)
- bounded retries with exponential backoff and capped Retry-After
- streaming download with a hard byte limit (also for decompressed payloads)
- conditional requests (ETag / Last-Modified) for HTTP caching
"""

from __future__ import annotations

import asyncio
import gzip
import random
import re
import time
import zlib
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx

from app.config import Settings, get_settings
from app.crawler.ratelimit import MemoryRateLimiter, RateLimiter
from app.crawler.robots import RobotsCache
from app.crawler.security import BlockedURLError, GuardedNetworkBackend, UrlGuard
from app.crawler.urls import host_of
from app.logging import get_logger
from app.metrics import BLOCKED_TOTAL, FETCH_BYTES, FETCH_DURATION, FETCH_TOTAL

log = get_logger(__name__)

HTML_TYPES = ("text/html", "application/xhtml+xml")
FEED_TYPES = (
    "application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/xml",
    "text/xml", "application/feed+json", "application/json",
)
SITEMAP_TYPES = ("application/xml", "text/xml", "application/gzip", "application/x-gzip", "text/plain")
ANY_TEXT = HTML_TYPES + FEED_TYPES + SITEMAP_TYPES
REDIRECT_CODES = {301, 302, 303, 307, 308}
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-:.]+)""", re.I)


class FetchError(Exception):
    def __init__(self, url: str, reason: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(f"{reason}: {url}")
        self.url = url
        self.reason = reason
        self.retryable = retryable
        self.status = status


class RobotsDisallowed(FetchError):
    def __init__(self, url: str):
        super().__init__(url, "disallowed by robots.txt")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    content_type: str
    elapsed: float
    redirects: list[str] = field(default_factory=list)
    not_modified: bool = False
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")

    @property
    def text(self) -> str:
        return decode_body(self.content, self.headers.get("content-type", ""))

    @property
    def is_html(self) -> bool:
        return self.content_type in HTML_TYPES or (
            not self.content_type and self.content[:512].lstrip().lower().startswith((b"<!doctype html", b"<html"))
        )


def decode_body(content: bytes, content_type: str) -> str:
    charset = None
    m = re.search(r"charset=([\w\-:.]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    if not charset:
        m2 = _META_CHARSET.search(content[:4096])
        if m2:
            charset = m2.group(1).decode("ascii", "ignore")
    for enc in (charset, "utf-8"):
        if not enc:
            continue
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def safe_gunzip(data: bytes, limit: int) -> bytes:
    """Decompress gzip without allowing decompression bombs."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(data, limit + 1)
    if len(out) > limit or d.unconsumed_tail:
        raise ValueError("decompressed payload exceeds limit")
    return out


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class Fetcher:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        guard: UrlGuard | None = None,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        respect_robots: bool | None = None,
    ):
        self.settings = settings or get_settings()
        s = self.settings
        self.guard = guard or UrlGuard(
            allowed_ports=s.allowed_ports, allow_private=s.allow_private_networks, max_url_length=s.max_url_length
        )
        self.rate_limiter = rate_limiter or MemoryRateLimiter()
        self.respect_robots = s.respect_robots if respect_robots is None else respect_robots
        if transport is None:
            transport = httpx.AsyncHTTPTransport(retries=0, http2=False)
            # Pin connections to vetted IPs (DNS-rebinding protection).
            pool = getattr(transport, "_pool", None)
            if pool is not None and hasattr(pool, "_network_backend"):
                pool._network_backend = GuardedNetworkBackend(self.guard)
        self.client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,  # never route through env proxies (would bypass the guard)
            timeout=httpx.Timeout(s.read_timeout, connect=s.connect_timeout),
            headers={
                "User-Agent": s.user_agent,
                "Accept-Language": "*",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self.robots = RobotsCache(self._fetch_robots, agent=s.user_agent, ttl=s.robots_cache_ttl)
        self._host_delays: dict[str, float] = {}

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def set_host_delay(self, host: str, delay: float) -> None:
        self._host_delays[host] = delay

    async def _delay_for(self, url: str) -> float:
        host = host_of(url)
        delay = self._host_delays.get(host, self.settings.default_min_delay)
        if self.respect_robots:
            crawl_delay = await self.robots.crawl_delay(url)
            if crawl_delay:
                delay = max(delay, min(crawl_delay, 60.0))
        return delay

    async def _fetch_robots(self, robots_url: str) -> tuple[int, str]:
        result = await self.fetch(
            robots_url, check_robots=False, accept=("text/plain", "text/html", ""), max_retries=1,
            max_bytes=512 * 1024, raise_for_type=False,
        )
        return result.status_code, result.text

    async def is_allowed(self, url: str) -> bool:
        return not self.respect_robots or await self.robots.allowed(url)

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: tuple[str, ...] = ANY_TEXT,
        check_robots: bool = True,
        max_retries: int | None = None,
        max_bytes: int | None = None,
        raise_for_type: bool = True,
    ) -> FetchResult:
        s = self.settings
        max_retries = s.max_retries if max_retries is None else min(max_retries, s.max_retries)
        max_bytes = max_bytes or s.max_response_bytes
        start = time.perf_counter()
        # Resolve robots.txt up front, outside the per-attempt timeout, so a slow robots.txt is
        # fetched (and cached) once instead of being cancelled and retried for every page.
        if check_robots and self.respect_robots:
            await self.guard.check(url)
            if not await self.robots.allowed(url):
                BLOCKED_TOTAL.labels("robots").inc()
                raise RobotsDisallowed(url)
            await self._delay_for(url)
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await asyncio.wait_for(
                    self._fetch_once(url, etag, last_modified, check_robots, max_bytes),
                    timeout=s.total_timeout,
                )
                result.attempts = attempt
                if result.status_code in RETRY_STATUS and attempt <= max_retries:
                    wait = self._backoff(attempt, result.headers.get("retry-after"))
                    if wait is not None:
                        log.info("fetch.retry", url=url, status=result.status_code, wait=round(wait, 2))
                        await asyncio.sleep(wait)
                        continue
                break
            except (BlockedURLError, RobotsDisallowed):
                raise
            except FetchError as exc:
                if not exc.retryable or attempt > max_retries:
                    FETCH_TOTAL.labels("error", exc.reason[:32]).inc()
                    raise
                await asyncio.sleep(self._backoff(attempt, None) or 0)
            except (httpx.TimeoutException, asyncio.TimeoutError, httpx.TransportError) as exc:
                if attempt > max_retries:
                    FETCH_TOTAL.labels("error", type(exc).__name__).inc()
                    raise FetchError(url, f"network error: {type(exc).__name__}", retryable=True) from exc
                await asyncio.sleep(self._backoff(attempt, None) or 0)

        result.elapsed = time.perf_counter() - start
        FETCH_DURATION.observe(result.elapsed)
        FETCH_TOTAL.labels("not_modified" if result.not_modified else "ok", str(result.status_code)).inc()
        if raise_for_type and result.ok and accept and result.content_type and result.content_type not in accept:
            raise FetchError(url, f"unsupported content-type {result.content_type}", status=result.status_code)
        return result

    def _backoff(self, attempt: int, retry_after: str | None) -> float | None:
        s = self.settings
        ra = _parse_retry_after(retry_after)
        if ra is not None:
            if ra > s.max_retry_after:
                return None  # server asks us to wait too long: give up instead of hogging a worker
            return ra
        base = s.retry_backoff_base * (2 ** (attempt - 1))
        return min(s.retry_backoff_max, base) * (0.5 + random.random() / 2)

    async def _fetch_once(
        self, url: str, etag: str | None, last_modified: str | None, check_robots: bool, max_bytes: int
    ) -> FetchResult:
        redirects: list[str] = []
        current = url
        for _hop in range(self.settings.max_redirects + 1):
            await self.guard.check(current)
            if check_robots and self.respect_robots and not await self.robots.allowed(current):
                BLOCKED_TOTAL.labels("robots").inc()
                raise RobotsDisallowed(current)
            await self.rate_limiter.wait(host_of(current), await self._delay_for(current) if check_robots else 0)

            headers = {}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            request = self.client.build_request("GET", current, headers=headers)
            response = await self.client.send(request, stream=True)
            try:
                if response.status_code in REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError(current, "redirect without location", status=response.status_code)
                    nxt = urljoin(current, location)
                    redirects.append(current)
                    if nxt in redirects:
                        raise FetchError(url, "redirect loop")
                    current = nxt
                    continue
                content = await self._read_limited(response, max_bytes, current)
            finally:
                await response.aclose()

            hdrs = {k.lower(): v for k, v in response.headers.items()}
            ctype = hdrs.get("content-type", "").split(";", 1)[0].strip().lower()
            if (ctype in ("application/gzip", "application/x-gzip") or current.endswith(".gz")) and content[:2] == b"\x1f\x8b":
                try:
                    content = safe_gunzip(content, max_bytes)
                except (ValueError, zlib.error, OSError, EOFError, gzip.BadGzipFile) as exc:
                    raise FetchError(current, f"bad gzip payload: {exc}") from exc
                ctype = "application/xml"
            return FetchResult(
                url=url,
                final_url=current,
                status_code=response.status_code,
                headers=hdrs,
                content=content,
                content_type=ctype,
                elapsed=0.0,
                redirects=redirects,
                not_modified=response.status_code == 304,
            )
        raise FetchError(url, "too many redirects")

    async def _read_limited(self, response: httpx.Response, max_bytes: int, url: str) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            BLOCKED_TOTAL.labels("oversized").inc()
            raise FetchError(url, f"response too large ({declared} bytes)", status=response.status_code)
        chunks: list[bytes] = []
        total = 0
        # aiter_bytes decodes Content-Encoding, so this bounds the *decompressed* size too.
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                BLOCKED_TOTAL.labels("oversized").inc()
                raise FetchError(url, f"response exceeded {max_bytes} bytes", status=response.status_code)
            chunks.append(chunk)
        FETCH_BYTES.inc(total)
        return b"".join(chunks)
