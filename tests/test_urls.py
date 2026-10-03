import pytest

from app.crawler.urls import has_trap_pattern, is_same_site, looks_like_non_html, normalize_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HTTP://Example.COM:80/a/../b/./c?utm_source=x&b=2&a=1#frag", "http://example.com/b/c?a=1&b=2"),
        ("https://example.com:443//news//2024/", "https://example.com/news/2024/"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/caf%C3%A9?fbclid=1", "https://example.com/caf%C3%A9"),
        ("https://bücher.de/x", "https://xn--bcher-kva.de/x"),
        ("https://example.com:8443/x?q=a%20b", "https://example.com:8443/x?q=a+b"),
    ],
)
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


def test_relative_resolution():
    assert normalize_url("../x?gclid=1", "https://a.com/news/today/") == "https://a.com/news/x"


def test_same_site():
    assert is_same_site("https://www.news.com/a", ["news.com"])
    assert not is_same_site("https://evilnews.com/a", ["news.com"])


def test_non_html_and_traps():
    assert looks_like_non_html("https://a.com/x.jpg")
    assert not looks_like_non_html("https://a.com/news/story")
    assert has_trap_pattern("https://a.com/a/b/a/b/a/b/a/b")
    assert has_trap_pattern("https://a.com/x?PHPSESSID=123")
    assert not has_trap_pattern("https://a.com/2024/05/01/story-title")
