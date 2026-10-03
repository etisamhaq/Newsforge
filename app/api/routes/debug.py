"""Extraction debugging: run the full pipeline on a URL (or supplied HTML) and return the trace."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, current_workspace, get_session, require_editor
from app.config import get_settings
from app.crawler.discovery import discover_feed_links, extract_links
from app.crawler.fetcher import Fetcher, FetchError, RobotsDisallowed
from app.crawler.renderer import RenderError
from app.crawler.security import BlockedURLError
from app.crawler.urls import normalize_url
from app.dedup.hashing import content_hash, simhash
from app.extraction.pipeline import ExtractionPipeline
from app.schemas import DebugExtractRequest, _check_url
from app.services.quotas import add_usage, llm_calls_left, require_pages

# Fetches arbitrary pages and can spend LLM credits, so editors and up only.
router = APIRouter(prefix="/debug", tags=["debug"], dependencies=[Depends(require_editor)])


async def get_fetcher() -> AsyncIterator[Fetcher]:
    fetcher = Fetcher()
    try:
        yield fetcher
    finally:
        await fetcher.aclose()


def get_pipeline() -> ExtractionPipeline:
    return ExtractionPipeline()


@router.post("/extract")
async def debug_extract(
    req: DebugExtractRequest,
    fetcher: Fetcher = Depends(get_fetcher),
    pipeline: ExtractionPipeline = Depends(get_pipeline),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_editor),
) -> dict:
    ws = await current_workspace(session, principal)
    fetch_info: dict = {}
    url, html, headers = req.url, req.html, {}
    if html is None:
        # Fetching a page counts against the workspace's daily page limit.
        await require_pages(session, ws)
        await add_usage(session, ws.id, pages=1)
        await session.commit()
        try:
            if req.render:
                if not get_settings().playwright_enabled:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "browser rendering is disabled (PLAYWRIGHT_ENABLED)")
                if not await fetcher.is_allowed(url):
                    raise RobotsDisallowed(url)
                from app.crawler.renderer import PlaywrightRenderer

                renderer = PlaywrightRenderer(guard=fetcher.guard)
                try:
                    url, html = await renderer.render(url)
                finally:
                    await renderer.aclose()
                fetch_info = {"rendered": True, "final_url": url}
            else:
                res = await fetcher.fetch(url)
                if not res.ok:
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"upstream returned HTTP {res.status_code}")
                if not res.is_html:
                    raise HTTPException(422, f"not an html page ({res.content_type})")
                url, html, headers = res.final_url, res.text, res.headers
                fetch_info = {"status_code": res.status_code, "final_url": res.final_url, "redirects": res.redirects,
                              "content_type": res.content_type, "bytes": len(res.content), "attempts": res.attempts,
                              "elapsed_ms": round(res.elapsed * 1000, 1)}
        except BlockedURLError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"url blocked: {exc.reason}") from exc
        except RobotsDisallowed as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "disallowed by robots.txt") from exc
        except FetchError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.reason) from exc
        except RenderError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"render failed: {exc}") from exc

    use_llm = req.use_llm and await llm_calls_left(session, ws) > 0
    report = await pipeline.run(url, html, headers, allow_fallback=use_llm)
    if report.used_fallback and any(s.strategy == "llm" for s in report.strategies):
        await add_usage(session, ws.id, llm_calls=1)
        await session.commit()
    out = report.to_dict()
    out["llm_quota_exhausted"] = req.use_llm and not use_llm
    body = report.article.body
    out["fetch"] = fetch_info
    out["fingerprints"] = {"content_hash": content_hash(body), "simhash": f"{simhash(body):016x}" if simhash(body) else None}
    out["discovery"] = {"feeds": discover_feed_links(html, url), "links": extract_links(html, url)[:100]}
    if req.include_html:
        out["html"] = html
    return out


@router.get("/robots")
async def debug_robots(url: str = Query(..., max_length=2048), fetcher: Fetcher = Depends(get_fetcher)) -> dict:
    try:
        url = _check_url(url)
        await fetcher.guard.check(url)
    except (ValueError, BlockedURLError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"url blocked: {exc}") from exc
    rules = await fetcher.robots.rules_for(url)
    return {
        "url": url,
        "allowed": rules.can_fetch(fetcher.settings.user_agent, url),
        "crawl_delay": rules.crawl_delay(fetcher.settings.user_agent),
        "sitemaps": rules.sitemaps,
        "user_agent": fetcher.settings.user_agent,
    }


@router.get("/normalize")
async def debug_normalize(url: str = Query(..., max_length=2048)) -> dict:
    try:
        return {"input": url, "normalized": normalize_url(url)}
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
