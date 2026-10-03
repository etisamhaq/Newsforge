"""Main-content extraction: trafilatura (primary) and a selectolax text-density fallback."""

from __future__ import annotations

import asyncio

import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from app.extraction.base import Candidate, ExtractionContext, ExtractionStrategy, StrategyResult, word_count
from app.extraction.dates import parse_date
from app.extraction.text import clean_authors, clean_body, clean_text, split_keywords

BOILERPLATE = "script, style, noscript, iframe, svg, form, nav, header, footer, aside, button, select, template"
NEGATIVE_HINTS = ("comment", "share", "social", "related", "promo", "advert", "ad-", "sidebar", "newsletter",
                  "subscribe", "cookie", "footer", "menu", "nav", "breadcrumb", "recommend", "outbrain", "taboola")
POSITIVE_HINTS = ("article", "story", "content", "body", "post", "entry", "main", "text")


class TrafilaturaStrategy(ExtractionStrategy):
    name = "trafilatura"
    priority = 30

    @staticmethod
    def _run(html: str, url: str):
        return trafilatura.bare_extraction(
            html, url=url, with_metadata=True, include_comments=False, include_tables=False,
            favor_precision=True, deduplicate=False,
            # Only trust dates from markup/metadata; free-text guessing produced bogus dates.
            date_extraction_params={"extensive_search": False, "original_date": True},
        )

    async def extract(self, ctx: ExtractionContext, merged: dict[str, Candidate]) -> StrategyResult:
        res = StrategyResult(self.name)
        doc = await asyncio.to_thread(self._run, ctx.html, ctx.url)
        if doc is None:
            return res
        get = (lambda k: doc.get(k)) if isinstance(doc, dict) else (lambda k: getattr(doc, k, None))
        body = clean_body(get("text"))
        res.signals["words"] = word_count(body)
        res.add("body", body, 0.8)
        res.add("title", clean_text(get("title")), 0.7)
        author = get("author")
        res.add("authors", clean_authors(author.split(";")) if author else [], 0.6)
        res.add("published_at", parse_date(get("date")), 0.6)
        res.add("description", clean_text(get("description")), 0.6)
        res.add("image_url", get("image"), 0.6)
        cats = split_keywords(get("categories"))
        res.add("category", cats[0] if cats else None, 0.5)
        res.add("tags", split_keywords(get("tags")), 0.5)
        res.add("site_name", clean_text(get("sitename")), 0.6)
        res.add("language", clean_text(get("language")), 0.5)
        return res


def _class_id(node: Node) -> str:
    a = node.attributes
    return f"{a.get('class') or ''} {a.get('id') or ''}".lower()


def _link_text_len(node: Node) -> int:
    return sum(len(a.text(strip=True)) for a in node.css("a"))


def page_signals(tree: HTMLParser) -> dict:
    body = tree.body
    if body is None:
        return {"page_words": 0, "link_density": 1.0, "paragraphs": 0, "has_article_tag": False}
    text = body.text(separator=" ", strip=True)
    total = len(text) or 1
    return {
        "page_words": word_count(text),
        "link_density": round(min(1.0, _link_text_len(body) / total), 3),
        "paragraphs": len([p for p in body.css("p") if len(p.text(strip=True)) > 60]),
        "has_article_tag": tree.css_first("article") is not None,
    }


class DensityStrategy(ExtractionStrategy):
    """Pick the container whose paragraphs hold the most non-link text."""

    name = "density"
    priority = 40

    async def extract(self, ctx: ExtractionContext, merged: dict[str, Candidate]) -> StrategyResult:
        res = StrategyResult(self.name)
        res.signals.update(page_signals(ctx.tree))
        tree = HTMLParser(ctx.html)
        for node in tree.css(BOILERPLATE):
            node.decompose()
        best: Node | None = None
        best_score = 0.0
        for node in tree.css("article, main, section, div, td"):
            paragraphs = [p.text(separator=" ", strip=True) for p in node.css("p")]
            paragraphs = [p for p in paragraphs if len(p) >= 40]
            if not paragraphs:
                continue
            text_len = sum(len(p) for p in paragraphs)
            link_len = _link_text_len(node)
            hint = _class_id(node)
            score = text_len * (1 - min(0.9, link_len / max(text_len, 1)))
            if any(h in hint for h in NEGATIVE_HINTS):
                score *= 0.3
            if node.tag in ("article", "main") or any(h in hint for h in POSITIVE_HINTS):
                score *= 1.25
            score *= 1 + min(len(paragraphs), 30) / 30
            if score > best_score:
                best, best_score = node, score
        if best is None:
            return res
        paras = [p.text(separator=" ", strip=True) for p in best.css("p, h2, h3, blockquote, li")]
        body = clean_body("\n\n".join(p for p in paras if len(p) >= 25))
        res.signals["words"] = word_count(body)
        res.add("body", body, 0.6)
        h1 = ctx.tree.css_first("h1")
        if h1:
            res.add("title", clean_text(h1.text(strip=True)), 0.55)
        return res
