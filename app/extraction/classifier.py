"""Is this page an article? A transparent, weighted-signal classifier."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.crawler.discovery import article_url_score
from app.extraction.base import Candidate, StrategyResult, word_count


@dataclass
class Classification:
    is_article: bool
    score: float
    reasons: list[str] = field(default_factory=list)


def classify(
    url: str,
    merged: dict[str, Candidate],
    results: list[StrategyResult],
    *,
    min_words: int = 120,
    threshold: float = 0.5,
    noindex: bool = False,
) -> Classification:
    signals: dict = {}
    for r in results:
        signals.update({f"{r.strategy}.{k}": v for k, v in r.signals.items()})

    score = 0.0
    reasons: list[str] = []

    def add(delta: float, why: str) -> None:
        nonlocal score
        score += delta
        reasons.append(f"{delta:+.2f} {why}")

    if signals.get("jsonld.article_type"):
        add(0.4, f"json-ld type {signals['jsonld.article_type']}")
    if signals.get("jsonld.is_listing"):
        add(-0.25, "json-ld listing type")
    if (signals.get("metatags.og_type") or "").lower() == "article":
        add(0.2, "og:type=article")
    if "published_at" in merged:
        add(0.15, "has publish date")
    if "authors" in merged:
        add(0.05, "has author")

    words = word_count(merged["body"].value) if "body" in merged else 0
    if words >= min_words:
        add(0.25, f"body {words} words")
        if words >= 300:
            add(0.1, "long body")
    elif words >= min_words // 2:
        add(0.05, f"short body {words} words")
    else:
        add(-0.2, f"little text ({words} words)")

    if (signals.get("density.paragraphs") or 0) >= 3:
        add(0.1, f"{signals['density.paragraphs']} substantial paragraphs")
    if signals.get("density.has_article_tag"):
        add(0.05, "<article> element")
    link_density = signals.get("density.link_density")
    if link_density is not None and link_density > 0.5:
        add(-0.2, f"high link density {link_density}")

    url_prior = article_url_score(url)
    if url_prior >= 0.5:
        add(0.1, "article-like url")
    elif url_prior <= 0.1:
        add(-0.25, "listing/home url")

    score = round(max(0.0, min(1.0, score)), 3)
    if words < max(30, min_words // 4):
        reasons.append(f"veto: body too short for a text article ({words} words)")
        return Classification(False, score, reasons)
    if noindex:
        reasons.append("veto: meta robots noindex")
        return Classification(False, score, reasons)
    return Classification(score >= threshold, score, reasons)
