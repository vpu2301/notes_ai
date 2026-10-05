"""SQLAlchemy async engine factory and shared declarative base (asyncpg via ``tenant_connection`` is the hot path)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all service models."""


def make_engine(database_url: str, **kwargs: object) -> AsyncEngine:
    """Create an async SQLAlchemy engine from an asyncpg-compatible URL."""
    return create_async_engine(database_url, **kwargs)
