"""Article URL discovery: RSS/Atom/RDF/JSON feeds, XML sitemaps (incl. news & index), page links."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

import feedparser
from lxml import etree
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.crawler.urls import looks_like_non_html, normalize_url
from app.extraction.dates import parse_date

FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/feed+json"}
COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/feeds/all.atom.xml")
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/news-sitemap.xml", "/sitemap_index.xml")
MAX_FEED_ITEMS = 1000
MAX_SITEMAP_URLS = 50_000

_LISTING = re.compile(
    r"/(tag|tags|topic|topics|category|categories|section|author|authors|page|search|archive|"
    r"login|signin|signup|register|subscribe|account|newsletter|contact|about|privacy|terms|cookie|"
    r"video|videos|gallery|galleries|live|podcast|podcasts)(/|$)",
    re.I,
)
_DATE_PATH = re.compile(r"/(19|20)\d{2}[/-](0?[1-9]|1[0-2])([/-](0?[1-9]|[12]\d|3[01]))?(/|$|-)")


@dataclass
class DiscoveredURL:
    url: str
    via: str  # feed | sitemap | link | seed
    title: str | None = None
    published_at: datetime | None = None
    lastmod: datetime | None = None


def _unsafe_xml(content: bytes) -> bool:
    # Reject DTD entity declarations up front (billion laughs / XXE).
    return b"<!ENTITY" in content[:65536].upper()


def is_feed_content(content: bytes, content_type: str = "") -> bool:
    if content_type in FEED_TYPES:
        return True
    head = content[:2048].lstrip().lower()
    return b"<rss" in head or b"<feed" in head or b"<rdf:rdf" in head or b'"version": "https://jsonfeed.org' in head


def is_sitemap_content(content: bytes) -> bool:
    head = content[:2048].lower()
    return b"<urlset" in head or b"<sitemapindex" in head


def parse_feed(content: bytes, base_url: str) -> list[DiscoveredURL]:
    if _unsafe_xml(content):
        return []
    head = content[:256].lstrip()
    if head.startswith(b"{"):
        return _parse_json_feed(content, base_url)
    parsed = feedparser.parse(content, sanitize_html=False, resolve_relative_uris=False)
    out: list[DiscoveredURL] = []
    for entry in parsed.entries[:MAX_FEED_ITEMS]:
        link = entry.get("link") or entry.get("id")
        if not link or not isinstance(link, str):
            continue
        try:
            url = normalize_url(link, base_url)
        except ValueError:
            continue
        published = parse_date(entry.get("published") or entry.get("updated") or entry.get("dc_date"))
        out.append(DiscoveredURL(url, "feed", title=entry.get("title"), published_at=published))
    return out


def _parse_json_feed(content: bytes, base_url: str) -> list[DiscoveredURL]:
    try:
        data = json.loads(content)
    except ValueError:
        return []
    out = []
    for item in (data.get("items") or [])[:MAX_FEED_ITEMS]:
        link = item.get("url") or item.get("external_url")
        if isinstance(link, str):
            out.append(
                DiscoveredURL(normalize_url(link, base_url), "feed", item.get("title"), parse_date(item.get("date_published")))
            )
    return out


def parse_sitemap(content: bytes, base_url: str) -> tuple[list[DiscoveredURL], list[DiscoveredURL]]:
    """Return (page urls, child sitemaps). Child entries carry <lastmod> for prioritization."""
    if _unsafe_xml(content):
        return [], []
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError:
        return [], []
    if root is None:
        return [], []
    urls: list[DiscoveredURL] = []
    children: list[DiscoveredURL] = []
    tag = etree.QName(root).localname.lower()
    for node in root:
        if not isinstance(node.tag, str):
            continue
        fields: dict[str, str] = {}
        for child in node.iter():
            if isinstance(child.tag, str) and child.text:
                fields.setdefault(etree.QName(child).localname.lower(), child.text.strip())
        loc = fields.get("loc")
        if not loc:
            continue
        try:
            loc = normalize_url(loc, base_url)
        except ValueError:
            continue
        if tag == "sitemapindex":
            children.append(DiscoveredURL(loc, "sitemap-index", lastmod=parse_date(fields.get("lastmod"))))
        else:
            urls.append(
                DiscoveredURL(
                    loc,
                    "sitemap",
                    title=fields.get("title"),
                    published_at=parse_date(fields.get("publication_date")),
                    lastmod=parse_date(fields.get("lastmod")),
                )
            )
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return urls, children


def page_robots_directives(tree: HTMLParser) -> set[str]:
    out: set[str] = set()
    for node in tree.css("meta[name]"):
        name = (node.attributes.get("name") or "").lower()
        if name in ("robots", "googlebot") or name.startswith("newsforge"):
            content = (node.attributes.get("content") or "").lower()
            out.update(p.strip() for p in content.split(","))
    return out


def extract_links(html: str | HTMLParser, base_url: str) -> list[str]:
    tree = html if isinstance(html, HTMLParser) else HTMLParser(html)
    base_node = tree.css_first("base[href]")
    base = normalize_url(base_node.attributes["href"], base_url) if base_node and base_node.attributes.get("href") else base_url
    seen: dict[str, None] = {}
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        rel = (a.attributes.get("rel") or "").lower()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")) or "nofollow" in rel:
            continue
        try:
            url = normalize_url(href, base)
        except ValueError:
            continue
        if url.startswith(("http://", "https://")) and not looks_like_non_html(url):
            seen.setdefault(url, None)
    return list(seen)


def discover_feed_links(html: str | HTMLParser, base_url: str) -> list[str]:
    tree = html if isinstance(html, HTMLParser) else HTMLParser(html)
    out = []
    for link in tree.css("link[rel][href]"):
        rel = (link.attributes.get("rel") or "").lower()
        typ = (link.attributes.get("type") or "").lower()
        if "alternate" in rel and typ in FEED_TYPES:
            try:
                out.append(normalize_url(link.attributes["href"], base_url))
            except (ValueError, KeyError):
                continue
    return list(dict.fromkeys(out))


def article_url_score(url: str) -> float:
    """Cheap prior (0..1) that a URL points to an article; used to prioritize the frontier."""
    from urllib.parse import urlsplit

    path = urlsplit(url).path
    if path in ("", "/"):
        return 0.05
    score = 0.3
    if _DATE_PATH.search(path):
        score += 0.35
    last = [s for s in path.split("/") if s]
    slug = last[-1] if last else ""
    if slug.count("-") >= 3:
        score += 0.25
    if re.search(r"\d{5,}", path):
        score += 0.1
    if path.endswith((".html", ".htm")):
        score += 0.05
    if _LISTING.search(path):
        score -= 0.35
    return max(0.0, min(1.0, score))
