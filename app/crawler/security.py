"""SSRF protection.

Two layers:
1. `UrlGuard.check()` validates scheme/host/port and resolves DNS, rejecting any
   non-public address before a request is attempted (also applied to every redirect hop).
2. `GuardedNetworkBackend` re-resolves and validates at *connect time* and connects to the
   vetted IP, which closes the DNS-rebinding window between check and connect.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import anyio
import httpcore

from app.metrics import BLOCKED_TOTAL

Resolver = Callable[[str, int], Awaitable[list[str]]]

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa")


class BlockedURLError(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"blocked {url!r}: {reason}")
        self.url = url
        self.reason = reason


async def default_resolver(host: str, port: int) -> list[str]:
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour is not None:
            return is_public_ip(str(ip.sixtofour))
        if ip.teredo is not None:
            return False
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_private or ip.is_reserved:
        return False
    return ip.is_global


class UrlGuard:
    def __init__(
        self,
        *,
        allowed_ports: Iterable[int] = (80, 443, 8080, 8443),
        allow_private: bool = False,
        max_url_length: int = 2048,
        resolver: Resolver | None = None,
    ):
        self.allowed_ports = set(allowed_ports)
        self.allow_private = allow_private
        self.max_url_length = max_url_length
        self.resolver = resolver or default_resolver

    def check_syntax(self, url: str) -> tuple[str, int]:
        if len(url) > self.max_url_length:
            raise BlockedURLError(url, "url too long")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise BlockedURLError(url, f"malformed url: {exc}") from exc
        if parts.scheme not in ("http", "https"):
            raise BlockedURLError(url, f"scheme {parts.scheme!r} not allowed")
        if parts.username or parts.password:
            raise BlockedURLError(url, "credentials in url not allowed")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise BlockedURLError(url, "missing host")
        port = port or (443 if parts.scheme == "https" else 80)
        if port not in self.allowed_ports:
            raise BlockedURLError(url, f"port {port} not allowed")
        if not self.allow_private:
            if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
                raise BlockedURLError(url, "internal hostname")
            if _is_ip_literal(host) and not is_public_ip(host):
                raise BlockedURLError(url, "non-public ip address")
            if "." not in host and not _is_ip_literal(host):
                raise BlockedURLError(url, "single-label hostname")
        return host, port

    async def resolve_public(self, host: str, port: int, url: str = "") -> list[str]:
        if _is_ip_literal(host):
            ips = [host]
        else:
            try:
                ips = await self.resolver(host, port)
            except OSError as exc:
                raise BlockedURLError(url or host, f"dns resolution failed: {exc}") from exc
        if not ips:
            raise BlockedURLError(url or host, "no addresses")
        if not self.allow_private:
            bad = [ip for ip in ips if not is_public_ip(ip)]
            if bad:
                raise BlockedURLError(url or host, f"resolves to non-public address {bad[0]}")
        return ips

    async def check(self, url: str) -> None:
        try:
            host, port = self.check_syntax(url)
            await self.resolve_public(host, port, url)
        except BlockedURLError as exc:
            BLOCKED_TOTAL.labels("ssrf").inc()
            raise exc


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    """httpcore network backend that only ever connects to vetted public IPs."""

    def __init__(self, guard: UrlGuard, inner: httpcore.AsyncNetworkBackend | None = None):
        self.guard = guard
        self.inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ips = await self.guard.resolve_public(host.strip("[]"), port)
        # IPv4 first: many hosts have broken IPv6 routes that only fail after a full timeout.
        ips = sorted(ips, key=lambda ip: ":" in ip)
        # Split the connect budget across a few addresses instead of burning it all on the first.
        per_ip = timeout
        if timeout and len(ips) > 1:
            per_ip = max(2.0, timeout / min(len(ips), 3))
        last_exc: Exception | None = None
        for ip in ips:
            try:
                return await self.inner.connect_tcp(
                    ip, port, timeout=per_ip, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        raise last_exc or httpcore.ConnectError(f"could not connect to {host}")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):  # pragma: no cover
        raise httpcore.ConnectError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)
