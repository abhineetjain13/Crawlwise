"""Tests for database utility functions."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.db_utils import with_retry


@pytest.mark.asyncio
async def test_with_retry_retries_full_unit_of_work_after_commit_lock():
    session = AsyncMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    session.commit = AsyncMock(
        side_effect=[
            OperationalError("statement", {}, "database is locked"),
            None,
        ]
    )
    attempts = 0

    async def _operation(_session: AsyncSession) -> str:
        nonlocal attempts
        attempts += 1
        return f"attempt-{attempts}"

    result = await with_retry(session, _operation, base_delay_ms=1, max_delay_ms=10)

    assert result == "attempt-2"
    assert attempts == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_with_retry_retries_when_operation_hits_lock_before_commit():
    session = AsyncMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    attempts = 0

    async def _operation(_session: AsyncSession) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError("statement", {}, "database is locked")
        return "ok"

    result = await with_retry(session, _operation, base_delay_ms=1, max_delay_ms=10)

    assert result == "ok"
    assert attempts == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lock_message",
    [
        "database table is locked",
        "database schema is locked",
        "SQLITE_BUSY: database is locked",
    ],
)
async def test_with_retry_retries_known_sqlite_lock_message_variants(lock_message: str):
    session = AsyncMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    session.commit = AsyncMock(
        side_effect=[
            OperationalError("statement", {}, lock_message),
            None,
        ]
    )
    attempts = 0

    async def _operation(_session: AsyncSession) -> str:
        nonlocal attempts
        attempts += 1
        return f"attempt-{attempts}"

    result = await with_retry(session, _operation, base_delay_ms=1, max_delay_ms=10)

    assert result == "attempt-2"
    assert attempts == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_with_retry_handles_real_sqlite_write_lock_with_two_sessions(tmp_path: Path):
    db_path = tmp_path / "lock_retry_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"timeout": 0.01},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT)"))

    attempts = 0
    async with session_factory() as holder, session_factory() as writer:
        await holder.execute(text("BEGIN IMMEDIATE"))
        await holder.execute(text("INSERT INTO items (value) VALUES ('holder')"))

        async def _operation(_session: AsyncSession) -> str:
            nonlocal attempts
            attempts += 1
            await _session.execute(text("INSERT INTO items (value) VALUES ('writer')"))
            return "ok"

        task = asyncio.create_task(
            with_retry(writer, _operation, max_retries=5, base_delay_ms=10, max_delay_ms=30)
        )
        for _ in range(20):
            if attempts > 0:
                break
            await asyncio.sleep(0.01)
        # Keep the write lock briefly after the first attempt starts so at least
        # one commit path encounters a real SQLite lock before release.
        await asyncio.sleep(0.08)
        await holder.commit()
        result = await task

        count = (
            await writer.execute(
                text("SELECT COUNT(*) FROM items WHERE value = 'writer'")
            )
        ).scalar_one()

    await engine.dispose()

    assert result == "ok"
    assert attempts >= 2
    assert count == 1
