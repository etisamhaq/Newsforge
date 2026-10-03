from datetime import datetime, timezone

from app.crawler.discovery import (
    article_url_score,
    discover_feed_links,
    extract_links,
    is_feed_content,
    is_sitemap_content,
    parse_feed,
    parse_sitemap,
)
from tests.conftest import fixture_text

BASE = "https://news.example.com/"


def test_parse_rss():
    content = fixture_text("rss.xml").encode()
    assert is_feed_content(content)
    items = parse_feed(content, BASE)
    assert [i.url for i in items] == [
        "https://news.example.com/2024/05/14/city-approves-transit-plan",
        "https://news.example.com/2024/05/13/budget-vote-delayed-again",
    ]
    assert items[0].published_at == datetime(2024, 5, 14, 8, 30, tzinfo=timezone.utc)
    assert items[0].via == "feed"


def test_parse_atom():
    items = parse_feed(fixture_text("atom.xml").encode(), BASE)
    assert items[0].url == "https://news.example.com/2024/05/10/atom-story-here"
    assert items[0].published_at is not None


def test_parse_json_feed():
    content = b'{"version": "https://jsonfeed.org/version/1.1", "items": [{"url": "/a-b-c-d", "date_published": "2024-01-01T00:00:00Z"}]}'
    assert parse_feed(content, BASE)[0].url == "https://news.example.com/a-b-c-d"


def test_parse_sitemaps():
    idx = fixture_text("sitemap_index.xml").encode()
    assert is_sitemap_content(idx)
    urls, children = parse_sitemap(idx, BASE)
    assert urls == [] and [c.url for c in children] == ["https://news.example.com/news-sitemap.xml"]
    urls, children = parse_sitemap(fixture_text("news_sitemap.xml").encode(), BASE)
    assert len(urls) == 2 and not children
    assert urls[0].title == "New park opens downtown"
    assert urls[0].published_at == datetime(2024, 5, 12, 9, tzinfo=timezone.utc)
    assert urls[1].lastmod is not None


def test_xml_entity_attacks_rejected():
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><urlset><url><loc>&lol2;</loc></url></urlset>'
    assert parse_sitemap(bomb, BASE) == ([], [])
    assert parse_feed(bomb, BASE) == []


def test_extract_links_and_feeds():
    html = fixture_text("article_jsonld.html")
    links = extract_links(html, "https://news.example.com/2024/05/14/city-approves-transit-plan")
    assert "https://news.example.com/2024/05/13/budget-vote-delayed-again" in links
    assert "https://other-site.com/story" in links
    assert not any("new-park" in u for u in links)  # rel=nofollow
    assert discover_feed_links(html, BASE) == ["https://news.example.com/feed"]
    listing_links = extract_links(fixture_text("listing.html"), BASE)
    assert not any(u.endswith(".jpg") for u in listing_links)


def test_article_url_score():
    assert article_url_score("https://a.com/2024/05/14/city-approves-transit-plan") > 0.8
    assert article_url_score("https://a.com/") < 0.1
    assert article_url_score("https://a.com/tag/politics") < 0.3
