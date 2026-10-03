"""HTML <head> metadata: OpenGraph, Twitter cards, Dublin Core, article:* and <link rel=canonical>."""

from __future__ import annotations

from app.extraction.base import Candidate, ExtractionContext, ExtractionStrategy, StrategyResult
from app.extraction.dates import parse_date
from app.extraction.text import clean_authors, clean_text, split_keywords


def meta_map(ctx: ExtractionContext) -> dict[str, list[str]]:
    if "meta" in ctx.cache:
        return ctx.cache["meta"]
    out: dict[str, list[str]] = {}
    for node in ctx.tree.css("meta"):
        attrs = node.attributes
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or attrs.get("http-equiv")
        content = attrs.get("content")
        if key and content:
            out.setdefault(key.strip().lower(), []).append(content.strip())
    ctx.cache["meta"] = out
    return out


def _first(m: dict[str, list[str]], *keys: str) -> str | None:
    for k in keys:
        if m.get(k):
            return m[k][0]
    return None


class MetaTagStrategy(ExtractionStrategy):
    name = "metatags"
    priority = 20

    async def extract(self, ctx: ExtractionContext, merged: dict[str, Candidate]) -> StrategyResult:
        res = StrategyResult(self.name)
        m = meta_map(ctx)
        tree = ctx.tree
        res.signals["og_type"] = _first(m, "og:type")

        og_title = _first(m, "og:title", "twitter:title", "dc.title", "dcterms.title")
        res.add("title", clean_text(og_title), 0.85)
        if not og_title:
            h1 = tree.css_first("h1")
            title_tag = tree.css_first("title")
            if h1 and h1.text(strip=True):
                res.add("title", clean_text(h1.text(strip=True)), 0.6)
            elif title_tag:
                res.add("title", clean_text(title_tag.text(strip=True)), 0.5)

        res.add("description", clean_text(_first(m, "og:description", "description", "twitter:description", "dc.description")), 0.8)
        res.add("image_url", _first(m, "og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"), 0.8)
        authors = m.get("author", []) + m.get("article:author", []) + m.get("dc.creator", []) + m.get("parsely-author", [])
        authors = [a for a in authors if not a.startswith("http")]
        if not authors:
            authors = [n.text(strip=True) for n in tree.css('[rel="author"], [itemprop="author"] [itemprop="name"], .byline .author')][:5]
        res.add("authors", clean_authors(authors), 0.7)
        res.add(
            "published_at",
            parse_date(_first(m, "article:published_time", "og:published_time", "datepublished", "pubdate",
                              "publishdate", "date", "dc.date", "dc.date.issued", "dcterms.created", "sailthru.date",
                              "parsely-pub-date")),
            0.85,
        )
        if "published_at" not in res.fields:
            time_node = tree.css_first("time[datetime]")
            if time_node:
                res.add("published_at", parse_date(time_node.attributes.get("datetime")), 0.6)
        res.add("modified_at", parse_date(_first(m, "article:modified_time", "og:updated_time", "datemodified", "dcterms.modified")), 0.8)
        res.add("category", clean_text(_first(m, "article:section", "parsely-section", "category")), 0.75)
        res.add("tags", split_keywords(m.get("article:tag", []) or m.get("news_keywords", []) or m.get("keywords", []) or m.get("parsely-tags", [])), 0.65)
        res.add("site_name", clean_text(_first(m, "og:site_name", "application-name", "twitter:site")), 0.8)

        canonical = tree.css_first('link[rel="canonical"]')
        if canonical and canonical.attributes.get("href"):
            res.add("canonical_url", canonical.attributes["href"].strip(), 0.9)
        elif _first(m, "og:url"):
            res.add("canonical_url", _first(m, "og:url"), 0.7)

        html_node = tree.css_first("html")
        lang = (html_node.attributes.get("lang") if html_node else None) or _first(m, "og:locale", "content-language", "language", "dc.language")
        lang = lang or ctx.headers.get("content-language")
        res.add("language", clean_text(lang), 0.7)
        return res
