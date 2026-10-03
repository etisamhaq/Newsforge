"""Extraction orchestration: structured data -> HTML metadata -> content density -> LLM fallback."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.config import Settings, get_settings
from app.crawler.discovery import article_url_score, page_robots_directives
from app.crawler.urls import host_of, normalize_url
from app.extraction.base import (
    Candidate,
    ExtractionContext,
    StrategyRegistry,
    StrategyResult,
    merge_results,
    word_count,
)
from app.extraction.classifier import Classification, classify
from app.extraction.content import DensityStrategy, TrafilaturaStrategy
from app.extraction.jsonld import JsonLdStrategy
from app.extraction.language import detect_language, normalize_language
from app.extraction.llm import LLMStrategy
from app.extraction.metadata import MetaTagStrategy
from app.logging import get_logger
from app.metrics import ARTICLE_SCORE, EXTRACTION_CONFIDENCE, EXTRACTION_TOTAL

log = get_logger(__name__)

CONFIDENCE_WEIGHTS = {
    "title": 0.2, "body": 0.35, "published_at": 0.15, "authors": 0.1,
    "description": 0.05, "image_url": 0.05, "language": 0.05, "canonical_url": 0.05,
}
_TWO_LEVEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "co.jp", "co.in", "com.br",
                       "com.pk", "co.nz", "co.za", "com.mx", "com.tr", "com.cn", "com.sg"}


def registrable_domain(host: str) -> str:
    labels = host.split(".")
    n = 3 if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES else 2
    return ".".join(labels[-n:])


def default_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    for strategy in (JsonLdStrategy(), MetaTagStrategy(), TrafilaturaStrategy(), DensityStrategy(), LLMStrategy()):
        reg.register(strategy)
    return reg


@dataclass
class ExtractedArticle:
    url: str
    canonical_url: str
    title: str | None = None
    body: str | None = None
    authors: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    modified_at: datetime | None = None
    description: str | None = None
    image_url: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    site_name: str | None = None
    word_count: int = 0
    confidence: float = 0.0
    article_score: float = 0.0
    is_article: bool = False
    primary_method: str | None = None
    field_sources: dict[str, str] = field(default_factory=dict)
    noindex: bool = False
    nofollow: bool = False
    external_canonical: str | None = None


@dataclass
class ExtractionReport:
    article: ExtractedArticle
    classification: Classification
    strategies: list[StrategyResult]
    used_fallback: bool
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        def ser(v):
            if isinstance(v, datetime):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: ser(x) for k, x in v.items()}
            if isinstance(v, list):
                return [ser(x) for x in v]
            return v

        return {
            "article": ser(asdict(self.article)),
            "classification": asdict(self.classification),
            "used_fallback": self.used_fallback,
            "duration_ms": round(self.duration_ms, 1),
            "strategies": [
                {
                    "strategy": r.strategy,
                    "duration_ms": round(r.duration_ms, 1),
                    "error": r.error,
                    "signals": ser(r.signals),
                    "fields": {
                        k: {"confidence": c.confidence, "value": ser(c.value if k != "body" else (c.value or "")[:500])}
                        for k, c in r.fields.items()
                    },
                }
                for r in self.strategies
            ],
        }


def compute_confidence(merged: dict[str, Candidate], min_words: int) -> float:
    total = 0.0
    for name, weight in CONFIDENCE_WEIGHTS.items():
        cand = merged.get(name)
        if cand is None:
            continue
        factor = cand.confidence
        if name == "body":
            factor *= min(1.0, word_count(cand.value) / max(min_words, 1))
        total += weight * factor
    return round(min(1.0, total), 3)


class ExtractionPipeline:
    def __init__(self, registry: StrategyRegistry | None = None, settings: Settings | None = None):
        self.registry = registry or default_registry()
        self.settings = settings or get_settings()

    async def _run_strategies(self, strategies, ctx, results, merged) -> dict[str, Candidate]:
        for strategy in strategies:
            start = time.perf_counter()
            try:
                res = await strategy.extract(ctx, merged)
            except Exception as exc:  # noqa: BLE001 - one bad strategy must not sink extraction
                log.warning("extraction.strategy_failed", strategy=strategy.name, url=ctx.url, error=str(exc)[:200])
                res = StrategyResult(strategy.name, error=f"{type(exc).__name__}: {exc}"[:300])
            res.duration_ms = (time.perf_counter() - start) * 1000
            results.append(res)
            merged = merge_results(results)
        return merged

    async def run(
        self, url: str, html: str, headers: dict[str, str] | None = None, *, allow_fallback: bool = True
    ) -> ExtractionReport:
        start = time.perf_counter()
        s = self.settings
        ctx = ExtractionContext(url=url, html=html, headers=headers or {})
        directives = page_robots_directives(ctx.tree)
        noindex = "noindex" in directives or "none" in directives
        results: list[StrategyResult] = []
        merged = await self._run_strategies(self.registry.primary(), ctx, results, {})
        cls = classify(url, merged, results, min_words=s.min_article_words, threshold=s.article_score_threshold, noindex=noindex)
        confidence = compute_confidence(merged, s.min_article_words)

        used_fallback = False
        fallbacks = self.registry.fallbacks()
        if (
            allow_fallback and fallbacks and not noindex
            and confidence < s.llm_confidence_threshold
            and (cls.score >= 0.2 or self._worth_fallback(url, results))
        ):
            used_fallback = True
            merged = await self._run_strategies(fallbacks, ctx, results, merged)
            new_conf = compute_confidence(merged, s.min_article_words)
            llm_verdicts = [r.signals["is_article"] for r in results if "is_article" in r.signals]
            cls = classify(url, merged, results, min_words=s.min_article_words, threshold=s.article_score_threshold, noindex=noindex)
            if llm_verdicts and llm_verdicts[-1] and new_conf > confidence:
                cls.score = max(cls.score, s.article_score_threshold)
                cls.is_article = True
                cls.reasons.append("+ fallback strategy confirmed article")
            elif llm_verdicts and not llm_verdicts[-1]:
                cls.is_article = False
                cls.reasons.append("- fallback strategy rejected article")
            confidence = max(confidence, new_conf)

        article = self._build(url, merged, cls, confidence, directives)
        EXTRACTION_TOTAL.labels(article.primary_method or "none").inc()
        EXTRACTION_CONFIDENCE.observe(confidence)
        ARTICLE_SCORE.observe(cls.score)
        return ExtractionReport(article, cls, results, used_fallback, (time.perf_counter() - start) * 1000)

    def _worth_fallback(self, url: str, results: list[StrategyResult]) -> bool:
        """Heuristics failed, but the URL looks like an article and the page has plenty of text."""
        page_words = max((r.signals.get("page_words", 0) for r in results), default=0)
        return article_url_score(url) >= 0.5 and page_words >= self.settings.min_article_words

    def _build(
        self, url: str, merged: dict[str, Candidate], cls: Classification, confidence: float, directives: set[str]
    ) -> ExtractedArticle:
        val = lambda k: merged[k].value if k in merged else None  # noqa: E731
        page_url = normalize_url(url)
        canonical = page_url
        external = None
        raw_canonical = val("canonical_url")
        if raw_canonical:
            try:
                cand = normalize_url(raw_canonical, url)
                # Only trust canonicals on the same site; others could hijack existing records.
                if cand.startswith("http") and registrable_domain(host_of(cand)) == registrable_domain(host_of(url)):
                    canonical = cand
                else:
                    external = cand
            except ValueError:
                pass

        image = val("image_url")
        if image:
            try:
                image = normalize_url(image, url, strip_tracking=False)
            except ValueError:
                image = None

        body = val("body")
        site_name = val("site_name")
        title = val("title")
        if title and site_name:
            title = re.sub(rf"\s*[|\-–—:]\s*{re.escape(site_name)}\s*$", "", title).strip() or title

        language = normalize_language(val("language")) or detect_language(body)
        primary = merged["body"].source if "body" in merged else (merged["title"].source if "title" in merged else None)
        return ExtractedArticle(
            url=page_url,
            canonical_url=canonical,
            title=title,
            body=body,
            authors=val("authors") or [],
            published_at=val("published_at"),
            modified_at=val("modified_at"),
            description=val("description"),
            image_url=image,
            category=val("category"),
            tags=val("tags") or [],
            language=language,
            site_name=site_name,
            word_count=word_count(body),
            confidence=confidence,
            article_score=cls.score,
            is_article=cls.is_article,
            primary_method=primary,
            field_sources={k: c.source for k, c in merged.items()},
            noindex="noindex" in directives or "none" in directives,
            nofollow="nofollow" in directives or "none" in directives,
            external_canonical=external,
        )
