# Shared test fixtures.
from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.core.database import Base
from app.models.user import User


_TMP_COUNTER = itertools.count()
_WORKSPACE_TMP_ROOT = Path(__file__).resolve().parents[1] / ".pytest-tmp"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_path() -> Path:
    path = _WORKSPACE_TMP_ROOT / f"case-{next(_TMP_COUNTER)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _redirect_tempfile_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    yield
    monkeypatch.setattr(tempfile, "tempdir", None)


@pytest.fixture(autouse=True)
def _stub_public_dns_resolution(monkeypatch: pytest.MonkeyPatch):
    async def _resolve(_hostname, _port):
        return ["93.184.216.34"]

    monkeypatch.setattr(
        "app.services.url_safety._resolve_host_ips",
        _resolve,
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
