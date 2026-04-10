# Async database engine and session factory.
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import settings
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_database_url = make_url(settings.database_url)
_engine_kwargs: dict[str, object] = {
    "future": True,
    "echo": False,
}
if not _database_url.drivername.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow
    _engine_kwargs["pool_pre_ping"] = settings.db_pool_pre_ping
    _engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds
    _engine_kwargs["pool_timeout"] = settings.db_pool_timeout_seconds

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
)


async def dispose_engine() -> None:
    """Dispose the connection pool. Call during application shutdown."""
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
