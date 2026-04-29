# Shared test fixtures.
# ruff: noqa: E402
from __future__ import annotations

import itertools
import os
import re
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pytest
import pytest_asyncio
import app.core.redis as app_redis
from app.core import database as app_database
from app.core.database import Base
from app.core.security import hash_password
from app.models.user import User
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl_crud import create_crawl_run
from app.services.crawl_fetch_runtime import reset_fetch_runtime_state
from app.services.acquisition.pacing import reset_pacing_state
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TMP_COUNTER = itertools.count()
_WORKSPACE_TMP_ROOT = _BACKEND_ROOT / ".pytest-tmp"
_UNSET = object()
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
)


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._ttl: dict[str, int] = {}

    async def aclose(self) -> None:
        return None

    async def set(
        self,
        key: str,
        value: object,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and (key in self._values or key in self._hashes):
            return False
        self._values[key] = str(value)
        if ex is not None:
            self._ttl[key] = int(ex)
        return True

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            existed = False
            if key in self._values:
                existed = True
                self._values.pop(key, None)
            if key in self._hashes:
                existed = True
                self._hashes.pop(key, None)
            self._ttl.pop(key, None)
            deleted += int(existed)
        return deleted

    async def exists(self, key: str) -> int:
        return int(key in self._values or key in self._hashes)

    async def hset(self, key: str, mapping: dict[str, object]) -> int:
        current = self._hashes.setdefault(key, {})
        added = 0
        for field, value in mapping.items():
            if field not in current:
                added += 1
            current[str(field)] = str(value)
        return added

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self._values and key not in self._hashes:
            return False
        self._ttl[key] = int(seconds)
        return True

    async def incr(self, key: str) -> int:
        next_value = int(self._values.get(key, "0")) + 1
        self._values[key] = str(next_value)
        return next_value

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        current = self._hashes.setdefault(key, {})
        next_value = int(current.get(field, "0")) + int(amount)
        current[field] = str(next_value)
        return next_value

    async def scan(
        self,
        *,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]:
        del cursor, count
        keys = sorted(set(self._values) | set(self._hashes))
        if match:
            keys = [key for key in keys if fnmatch(key, match)]
        return 0, keys

    async def scan_iter(self, *, match: str | None = None):
        _, keys = await self.scan(match=match)
        for key in keys:
            yield key

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        if "redis.call('get'" in script and numkeys == 1 and len(args) >= 2:
            key, token = args[0], args[1]
            if self._values.get(key) == token:
                await self.delete(key)
                return 1
        return 0

    def clear(self) -> None:
        self._values.clear()
        self._hashes.clear()
        self._ttl.clear()


@pytest.fixture
def workspace_tmp_path() -> Path:
    path = _WORKSPACE_TMP_ROOT / f"case-{next(_TMP_COUNTER)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _redirect_tempfile_root(monkeypatch: pytest.MonkeyPatch, workspace_tmp_path: Path):
    monkeypatch.setattr(tempfile, "tempdir", str(workspace_tmp_path))
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


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    client = FakeRedis()
    monkeypatch.setattr(app_redis, "_client", client)
    monkeypatch.setattr(app_redis, "_pool", None)
    monkeypatch.setattr(app_redis, "_redis_disabled_until", 0.0)
    monkeypatch.setattr(app_redis, "_last_disable_log_at", 0.0)
    monkeypatch.setattr(app_redis.settings, "redis_state_enabled", True)
    return client


@pytest_asyncio.fixture(autouse=True)
async def _reset_async_acquisition_state():
    yield
    await reset_fetch_runtime_state()
    await reset_pacing_state()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_app_engine():
    yield
    await app_database.engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    """Create a PostgreSQL database schema for each test."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    schema_suffix = re.sub(r"[^a-zA-Z0-9_]", "_", f"{worker_id}_{next(_TMP_COUNTER)}")
    schema_name = f"test_{schema_suffix}"
    quoted_schema_name = f'"{schema_name}"'
    engine = create_async_engine(TEST_DATABASE_URL, future=True, echo=False)
    scoped_engine = engine.execution_options(schema_translate_map={None: schema_name})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema_name}"))
    async with scoped_engine.begin() as conn:
        await conn.execute(text(f"SET search_path TO {quoted_schema_name}"))
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        scoped_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session
    async with scoped_engine.begin() as conn:
        await conn.execute(text(f"SET search_path TO {quoted_schema_name}"))
        await conn.run_sync(Base.metadata.drop_all)
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema_name} CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user with a deterministic password hash."""
    user = User(
        email=f"test-{next(_TMP_COUNTER)}@example.com",
        hashed_password=hash_password("password123"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def patch_settings(monkeypatch: pytest.MonkeyPatch):
    def _patch(target=None, **kwargs):
        settings = crawler_runtime_settings if target is None else target
        for key, value in kwargs.items():
            monkeypatch.setattr(settings, key, value)

    return _patch


@pytest.fixture
def create_test_run(db_session: AsyncSession, test_user: User):
    async def _create_test_run(
        *,
        url: str,
        surface: str,
        run_type: str = "crawl",
        settings: object = _UNSET,
        **payload_overrides,
    ):
        payload = {
            "run_type": run_type,
            "url": url,
            "surface": surface,
            **payload_overrides,
        }
        if settings is _UNSET:
            payload["settings"] = {"respect_robots_txt": False}
        else:
            payload["settings"] = settings
        return await create_crawl_run(db_session, test_user.id, payload)

    return _create_test_run
