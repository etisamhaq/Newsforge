"""schema.org JSON-LD (and microdata-free) structured metadata - the most reliable source."""

from __future__ import annotations

import json
import re
from typing import Any

from app.extraction.base import Candidate, ExtractionContext, ExtractionStrategy, StrategyResult
from app.extraction.dates import parse_date
from app.extraction.text import as_list, clean_authors, clean_body, clean_text, split_keywords

ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "reportagenewsarticle", "analysisnewsarticle",
    "opinionnewsarticle", "reviewnewsarticle", "backgroundnewsarticle", "askpublicnewsarticle",
    "liveblogposting", "techarticle", "scholarlyarticle", "report", "socialmediaposting", "posting",
}
LISTING_TYPES = {"collectionpage", "itemlist", "searchresultspage", "profilepage", "faqpage"}
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _types(obj: dict) -> set[str]:
    return {str(t).lower().rsplit("/", 1)[-1] for t in as_list(obj.get("@type")) if t}


def _walk(node: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, list):
        for n in node:
            _walk(n, out, depth + 1)
    elif isinstance(node, dict):
        out.append(node)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                _walk(node[key], out, depth + 1)


def parse_jsonld(ctx: ExtractionContext) -> list[dict]:
    if "jsonld" in ctx.cache:
        return ctx.cache["jsonld"]
    objects: list[dict] = []
    for script in ctx.tree.css('script[type="application/ld+json"]'):
        raw = _CTRL.sub(" ", script.text(deep=True) or "").strip()
        if not raw:
            continue
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw)
        data = None
        try:
            data = json.loads(raw)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))  # trailing commas
            except ValueError:
                continue
        _walk(data, objects)
    ctx.cache["jsonld"] = objects
    return objects


def _name(value: Any) -> list[str]:
    out = []
    for v in as_list(value):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict) and v.get("name"):
            out.extend(_name(v["name"]))
    return out


def _image(value: Any) -> str | None:
    for v in as_list(value):
        if isinstance(v, str) and v.startswith(("http", "/")):
            return v
        if isinstance(v, dict):
            url = v.get("url") or v.get("contentUrl") or v.get("@id")
            if isinstance(url, str):
                return url
    return None


def _url(value: Any) -> str | None:
    for v in as_list(value):
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, dict):
            u = v.get("@id") or v.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u
    return None


def _pick_article(objects: list[dict], url: str) -> dict | None:
    articles = [o for o in objects if _types(o) & ARTICLE_TYPES]
    if not articles:
        return None

    def score(o: dict) -> tuple:
        same_page = url.rstrip("/") in {str(_url(o.get("url")) or "").rstrip("/"), str(_url(o.get("mainEntityOfPage")) or "").rstrip("/")}
        return (same_page, bool(o.get("articleBody")), bool(o.get("headline")), len(o))

    return max(articles, key=score)


class JsonLdStrategy(ExtractionStrategy):
    name = "jsonld"
    priority = 10

    async def extract(self, ctx: ExtractionContext, merged: dict[str, Candidate]) -> StrategyResult:
        res = StrategyResult(self.name)
        objects = parse_jsonld(ctx)
        all_types = sorted({t for o in objects for t in _types(o)})
        res.signals["types"] = all_types
        res.signals["is_listing"] = bool(set(all_types) & LISTING_TYPES)
        art = _pick_article(objects, ctx.url)
        res.signals["article_type"] = sorted(_types(art) & ARTICLE_TYPES)[0] if art else None
        if not art:
            return res

        res.add("title", clean_text(art.get("headline") or art.get("name")), 0.95)
        body = clean_body(art.get("articleBody") if isinstance(art.get("articleBody"), str) else None)
        res.add("body", body, 0.85)
        res.add("authors", clean_authors(_name(art.get("author") or art.get("creator"))), 0.9)
        res.add("published_at", parse_date(art.get("datePublished") or art.get("dateCreated")), 0.95)
        res.add("modified_at", parse_date(art.get("dateModified")), 0.9)
        res.add("description", clean_text(art.get("description")), 0.85)
        res.add("image_url", _image(art.get("image") or art.get("thumbnailUrl")), 0.85)
        section = [s for s in as_list(art.get("articleSection")) if isinstance(s, str)]
        res.add("category", clean_text(section[0]) if section else None, 0.85)
        res.add("tags", split_keywords(art.get("keywords") or art.get("about")), 0.8)
        lang = art.get("inLanguage")
        if isinstance(lang, dict):
            lang = lang.get("alternateName") or lang.get("name")
        res.add("language", clean_text(lang), 0.9)
        res.add("canonical_url", _url(art.get("mainEntityOfPage")) or _url(art.get("url")), 0.75)
        publisher = _name(art.get("publisher"))
        res.add("site_name", clean_text(publisher[0]) if publisher else None, 0.85)
        return res
