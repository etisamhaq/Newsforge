"""robots.txt parsing (RFC 9309, incl. `*` / `$` wildcards) and a TTL cache."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from app.crawler.urls import origin_of

MAX_ROBOTS_BYTES = 500 * 1024


@dataclass
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def specificity(self) -> int:
        return len(self.pattern)


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile(regex + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, groups: list[_Group], sitemaps: list[str], *, allow_all: bool = False, disallow_all: bool = False):
        self.groups = groups
        self.sitemaps = sitemaps
        self.allow_all = allow_all
        self.disallow_all = disallow_all

    @classmethod
    def allow_everything(cls) -> RobotsRules:
        return cls([], [], allow_all=True)

    @classmethod
    def disallow_everything(cls) -> RobotsRules:
        return cls([], [], disallow_all=True)

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[_Group] = []
        sitemaps: list[str] = []
        current: _Group | None = None
        last_was_agent = False
        for raw in text[:MAX_ROBOTS_BYTES].splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            if key == "sitemap":
                if value:
                    sitemaps.append(value)
                continue
            last_was_agent = False
            if current is None:
                continue
            if key in ("allow", "disallow"):
                if not value:
                    continue  # empty disallow == allow everything
                path = value if value.startswith(("/", "*")) else "/" + value
                current.rules.append(_Rule(key == "allow", path, _compile(path)))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
        return cls(groups, sitemaps)

    def _group_for(self, agent: str) -> _Group | None:
        agent = product_token(agent)
        best: _Group | None = None
        best_len = -1
        for g in self.groups:
            for a in g.agents:
                if a != "*" and a == agent and len(a) > best_len:
                    best, best_len = g, len(a)
        if best is not None:
            return best
        merged = [g for g in self.groups if "*" in g.agents]
        if not merged:
            return None
        return _Group(["*"], [r for g in merged for r in g.rules], merged[0].crawl_delay)

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        group = self._group_for(agent)
        if group is None:
            return True
        best: _Rule | None = None
        for rule in group.rules:
            if rule.regex.match(path) and (
                best is None
                or rule.specificity > best.specificity
                or (rule.specificity == best.specificity and rule.allow)
            ):
                best = rule
        return True if best is None else best.allow

    def crawl_delay(self, agent: str) -> float | None:
        if self.allow_all or self.disallow_all:
            return None
        g = self._group_for(agent)
        return g.crawl_delay if g else None


def product_token(user_agent: str) -> str:
    """'NewsforgeBot/0.1 (+url)' -> 'newsforgebot'."""
    token = user_agent.strip().split("/", 1)[0].split(" ", 1)[0]
    return token.lower()


RobotsFetcher = Callable[[str], Awaitable[tuple[int, str]]]


class RobotsCache:
    """Per-origin robots.txt cache. `fetch_robots(url)` returns (status, text) and
    raises on network errors."""

    def __init__(self, fetch_robots: RobotsFetcher, agent: str, ttl: int = 3600, max_entries: int = 10_000):
        self._fetch = fetch_robots
        self.agent = agent
        self.ttl = ttl
        self.max_entries = max_entries
        self._cache: dict[str, tuple[float, RobotsRules]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def rules_for(self, url: str) -> RobotsRules:
        origin = origin_of(url)
        hit = self._cache.get(origin)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        # One robots.txt fetch per origin even when many pages ask concurrently.
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            hit = self._cache.get(origin)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            return await self._load(origin)

    async def _load(self, origin: str) -> RobotsRules:
        now = time.monotonic()
        ttl = self.ttl
        try:
            status, text = await self._fetch(origin + "/robots.txt")
            if 200 <= status < 300:
                rules = RobotsRules.parse(text)
            elif 400 <= status < 500 and status != 429:
                rules = RobotsRules.allow_everything()  # RFC 9309: unavailable -> allowed
            else:
                rules = RobotsRules.disallow_everything()  # unreachable -> assume complete disallow
                ttl = min(ttl, 300)
        except Exception:  # noqa: BLE001 - network failure -> be conservative, retry soon
            rules = RobotsRules.disallow_everything()
            ttl = min(ttl, 300)
        if len(self._cache) >= self.max_entries:
            self._cache.pop(next(iter(self._cache)))
        self._cache[origin] = (now + ttl, rules)
        return rules

    async def allowed(self, url: str) -> bool:
        return (await self.rules_for(url)).can_fetch(self.agent, url)

    async def crawl_delay(self, url: str) -> float | None:
        return (await self.rules_for(url)).crawl_delay(self.agent)
