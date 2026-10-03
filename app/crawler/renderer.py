"""Headless-browser rendering fallback for JavaScript-built pages (Playwright / Chromium).

Every request the page makes (documents, XHR, redirects) is checked by the SSRF guard;
heavy resources are blocked. This is a rendering fallback only: no CAPTCHA solving,
fingerprint spoofing or other anti-bot evasion.
"""

from __future__ import annotations

import asyncio
import re

from app.config import Settings, get_settings
from app.crawler.security import BlockedURLError, UrlGuard
from app.logging import get_logger
from app.metrics import RENDER_TOTAL

log = get_logger(__name__)

BLOCKED_RESOURCES = {"image", "media", "font", "stylesheet", "websocket", "eventsource", "manifest", "other"}
_JS_HINTS = re.compile(
    r'id=["\'](root|app|__next|__nuxt|svelte)["\']|data-reactroot|ng-app|window\.__INITIAL_STATE__|'
    r"<noscript>[^<]*(enable|requires?) javascript",
    re.I,
)


def looks_js_rendered(html: str, extracted_words: int, min_words: int) -> bool:
    """Heuristic: little extractable text but signs of a client-side app shell."""
    if extracted_words >= min_words:
        return False
    return bool(_JS_HINTS.search(html[:200_000])) or html.count("<script") >= 10


class RenderError(Exception):
    pass


class PlaywrightRenderer:
    def __init__(self, settings: Settings | None = None, guard: UrlGuard | None = None):
        self.settings = settings or get_settings()
        self.guard = guard or UrlGuard(allowed_ports=self.settings.allowed_ports, allow_private=self.settings.allow_private_networks)
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        async with self._lock:
            if self._browser is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError as exc:  # pragma: no cover
                    raise RenderError("playwright is not installed") from exc
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        return self._browser

    async def render(self, url: str) -> tuple[str, str]:
        """Return (final_url, html)."""
        await self.guard.check(url)
        browser = await self._ensure()
        context = await browser.new_context(
            user_agent=self.settings.user_agent, java_script_enabled=True, service_workers="block",
            accept_downloads=False,
        )
        page = await context.new_page()

        async def route_handler(route):
            req = route.request
            if req.resource_type in BLOCKED_RESOURCES:
                return await route.abort()
            try:
                await self.guard.check(req.url)
            except BlockedURLError:
                RENDER_TOTAL.labels("blocked_subrequest").inc()
                return await route.abort("blockedbyclient")
            return await route.continue_()

        await page.route("**/*", route_handler)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.settings.playwright_timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(5000, self.settings.playwright_timeout_ms))
            except Exception:  # noqa: BLE001 - best effort; long-polling pages never go idle
                pass
            html = await page.content()
            if len(html.encode()) > self.settings.max_response_bytes:
                raise RenderError("rendered page exceeds size limit")
            RENDER_TOTAL.labels("ok").inc()
            return page.url, html
        except RenderError:
            RENDER_TOTAL.labels("error").inc()
            raise
        except Exception as exc:
            RENDER_TOTAL.labels("error").inc()
            raise RenderError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = self._pw = None
