"""Veritabanı bağlantısı (SQLAlchemy 2, async, psycopg3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def async_url(url: str) -> str:
    """``postgresql://`` adreslerini SQLAlchemy psycopg sürücüsüne çevirir."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Database:
    def __init__(self, url: str, *, pool_size: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            async_url(url), pool_size=pool_size, max_overflow=5, pool_pre_ping=True
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """İşlem kapsamlı oturum: hata yoksa commit, varsa rollback."""
        async with self.sessions() as session, session.begin():
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
