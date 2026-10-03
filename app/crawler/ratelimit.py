"""Per-host politeness: enforce a minimum delay between requests to the same host.

`RedisRateLimiter` coordinates across all workers; `MemoryRateLimiter` is per-process.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class RateLimiter(Protocol):
    async def wait(self, host: str, min_delay: float) -> None: ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}

    async def wait(self, host: str, min_delay: float) -> None:
        if min_delay <= 0:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            ready_at = self._next.get(host, 0.0)
            if ready_at > now:
                await asyncio.sleep(ready_at - now)
            self._next[host] = time.monotonic() + min_delay


class RedisRateLimiter:
    """Uses `SET key NX PX delay` as a distributed per-host token."""

    def __init__(self, redis, prefix: str = "ratelimit:", max_wait: float = 300.0):
        self.redis = redis
        self.prefix = prefix
        self.max_wait = max_wait

    async def wait(self, host: str, min_delay: float) -> None:
        if min_delay <= 0:
            return
        key = self.prefix + host
        ms = max(1, int(min_delay * 1000))
        deadline = time.monotonic() + self.max_wait
        while True:
            if await self.redis.set(key, "1", nx=True, px=ms):
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"rate limiter wait exceeded for {host}")
            ttl = await self.redis.pttl(key)
            await asyncio.sleep(max(ttl, 10) / 1000)
