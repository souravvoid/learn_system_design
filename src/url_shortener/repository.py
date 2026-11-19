"""Database access for URL mappings and click analytics."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.shared.database import Database
from src.url_shortener.models import UrlMapping


class ShortCodeCollision(Exception):
    """Raised when a generated code is already in use."""


class UrlRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def insert(self, long_url: str, short_code: str) -> UrlMapping:
        async with self._database.session() as session:
            mapping = UrlMapping(long_url=long_url, short_code=short_code)
            session.add(mapping)
            try:
                await session.commit()
            except IntegrityError as exc:
                raise ShortCodeCollision(short_code) from exc
            return mapping

    async def get_by_code(self, short_code: str) -> UrlMapping | None:
        async with self._database.session() as session:
            result = await session.execute(
                select(UrlMapping).where(UrlMapping.short_code == short_code)
            )
            return result.scalar_one_or_none()

    async def increment_clicks(self, short_code: str) -> None:
        async with self._database.session() as session:
            await session.execute(
                update(UrlMapping)
                .where(UrlMapping.short_code == short_code)
                .values(clicks=UrlMapping.clicks + 1)
            )
            await session.commit()

    async def click_count(self, short_code: str) -> int:
        mapping = await self.get_by_code(short_code)
        return mapping.clicks if mapping is not None else 0
