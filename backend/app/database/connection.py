"""Database engine. Created lazily so the app can start (and report not-ready) without Postgres."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": max(1, int(settings.dependency_timeout_seconds))},
    )


async def check_database() -> None:
    """Raise if the database cannot answer a trivial query."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
