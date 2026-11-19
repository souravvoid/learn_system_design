"""Key/value cache interface and an in-memory Redis-compatible implementation.

The production HLDs use Redis. This implementation exposes only the subset of
Redis commands the case studies need, so it can be replaced by a `redis-py`
client without changing the services.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Cache(Protocol):
    """Minimal cache contract used by the services."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: float | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, amount: int = 1) -> int: ...


class InMemoryRedis:
    """Async, process-local cache with the Redis `get/set/delete/incr` surface.

    It is intentionally small: no eviction policies, persistence, or cluster
    behaviour. Those belong to the real Redis deployment described in the HLDs.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._expires_at: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    def _drop_if_expired(self, key: str) -> None:
        expiry = self._expires_at.get(key)
        if expiry is not None and expiry <= time.monotonic():
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    async def get(self, key: str) -> str | None:
        async with self._lock:
            self._drop_if_expired(key)
            if key in self._values:
                self.hits += 1
                return self._values[key]
            self.misses += 1
            return None

    async def set(self, key: str, value: str, *, ttl_seconds: float | None = None) -> None:
        async with self._lock:
            self._values[key] = value
            if ttl_seconds is None:
                self._expires_at.pop(key, None)
            else:
                self._expires_at[key] = time.monotonic() + ttl_seconds

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    async def incr(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            self._drop_if_expired(key)
            current = int(self._values.get(key, "0")) + amount
            self._values[key] = str(current)
            return current
