# Shared test fixtures.
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.core.database import Base
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun, ReviewPromotion
from app.models.llm import LLMConfig, LLMCostLog
from app.models.selector import Selector
from app.models.user import User


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _stub_public_dns_resolution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.url_safety._resolve_host_ips",
        lambda _hostname, _port: ["93.184.216.34"],
    )


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user with a deterministic password hash."""
    user = User(
        email="test@example.com",
        hashed_password=hash_password("password123"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
