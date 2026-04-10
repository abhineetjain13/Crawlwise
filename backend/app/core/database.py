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
_engine_kwargs = {
    "future": True,
    "echo": False,
}
if not _database_url.drivername.startswith("sqlite"):
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
