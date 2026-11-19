"""Write path, read path, key generation and asynchronous click analytics."""

from __future__ import annotations

from typing import Protocol

from src.shared.cache import Cache
from src.shared.database import Database
from src.shared.message_queue import MessageBroker
from src.url_shortener import base62
from src.url_shortener.models import UrlKey
from src.url_shortener.repository import ShortCodeCollision, UrlRepository

CLICK_TOPIC = "url.clicks"
_CACHE_PREFIX = "url:"


def cache_key(short_code: str) -> str:
    return f"{_CACHE_PREFIX}{short_code}"


class KeyGenerator(Protocol):
    async def next_code(self) -> str: ...


class KeyGenerationService:
    """Reserves a unique integer from the database sequence, then Base62-encodes it.

    In the HLD this is a distributed key-generation service (or a distributed
    counter). SQLite's autoincrement sequence is the local equivalent.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def next_code(self) -> str:
        async with self._database.session() as session:
            key = UrlKey()
            session.add(key)
            await session.flush()
            value = key.id
            await session.commit()
        return base62.encode(value)


class UrlShortenerService:
    def __init__(
        self,
        database: Database,
        cache: Cache,
        key_generator: KeyGenerator | None = None,
        max_key_attempts: int = 3,
    ) -> None:
        self._repository = UrlRepository(database)
        self._cache = cache
        self._key_generator: KeyGenerator = key_generator or KeyGenerationService(database)
        self._max_key_attempts = max_key_attempts

    async def shorten(self, long_url: str) -> str:
        """Write path: reserve a key, persist the mapping, then warm the cache."""
        for _ in range(self._max_key_attempts):
            short_code = await self._key_generator.next_code()
            try:
                await self._repository.insert(long_url, short_code)
            except ShortCodeCollision:
                continue
            await self._cache.set(cache_key(short_code), long_url)
            return short_code
        raise RuntimeError("Could not generate a collision-free short code")

    async def resolve(self, short_code: str) -> str | None:
        """Read path: cache-aside lookup; never touches analytics."""
        cached = await self._cache.get(cache_key(short_code))
        if cached is not None:
            return cached

        mapping = await self._repository.get_by_code(short_code)
        if mapping is None:
            return None

        await self._cache.set(cache_key(short_code), mapping.long_url)
        return mapping.long_url


class AnalyticsService:
    """Publishes clicks to a queue and consumes them off the redirect path."""

    def __init__(self, database: Database, broker: MessageBroker) -> None:
        self._repository = UrlRepository(database)
        self._broker = broker

    async def record_click(self, short_code: str) -> None:
        await self._broker.publish(CLICK_TOPIC, {"short_code": short_code})

    async def consume_forever(self) -> None:
        async with self._broker.subscribe(CLICK_TOPIC) as messages:
            async for message in messages:
                await self._repository.increment_clicks(message.body["short_code"])
