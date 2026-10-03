import pytest

from app.crawler.security import BlockedURLError, UrlGuard, is_public_ip
from tests.helpers import public_resolver


@pytest.mark.parametrize(
    "ip,public",
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),
        ("2002:7f00:1::", False),  # 6to4 wrapping 127.0.0.1
        ("2606:4700:4700::1111", True),
        ("224.0.0.1", False),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "http://localhost/x",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@example.com/",
        "http://example.com:6379/",
        "http://intranet/",
        "http://printer.local/",
        "http://2130706433/",
    ],
)
async def test_guard_blocks(url):
    guard = UrlGuard(resolver=public_resolver())
    with pytest.raises(BlockedURLError):
        await guard.check(url)


async def test_guard_blocks_dns_to_private():
    guard = UrlGuard(resolver=public_resolver({"evil.example.com": ["93.184.216.34", "10.0.0.5"]}))
    with pytest.raises(BlockedURLError, match="non-public"):
        await guard.check("http://evil.example.com/")


async def test_guard_allows_public():
    guard = UrlGuard(resolver=public_resolver())
    await guard.check("https://news.example.com/article")


async def test_network_backend_refuses_private_ip_at_connect_time():
    import httpcore

    from app.crawler.security import GuardedNetworkBackend

    guard = UrlGuard(resolver=public_resolver({"rebind.example.com": ["127.0.0.1"]}))
    backend = GuardedNetworkBackend(guard)
    with pytest.raises(BlockedURLError):
        await backend.connect_tcp("rebind.example.com", 80)
    assert isinstance(backend, httpcore.AsyncNetworkBackend)
