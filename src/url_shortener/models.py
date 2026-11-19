"""Persistence and API models for the URL shortener."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, HttpUrl
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class UrlKey(Base):
    """Monotonic key pool: the local stand-in for a Key Generation Service."""

    __tablename__ = "url_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class UrlMapping(Base):
    __tablename__ = "url_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    short_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    long_url: Mapped[str] = mapped_column(Text, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )


class ShortenRequest(BaseModel):
    long_url: HttpUrl


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
