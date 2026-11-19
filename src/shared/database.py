"""SQLAlchemy database session helpers shared by the case studies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project."""


@dataclass
class Database:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, url: str = DEFAULT_DATABASE_URL) -> Database:
        if url.endswith(":memory:"):
            engine = create_async_engine(
                url,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            engine = create_async_engine(url)
        return cls(engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False))

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()
