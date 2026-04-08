from __future__ import annotations

import io
import tempfile

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.crawls import (
    _mark_run_failed_with_retry,
    crawls_cancel,
    crawls_create,
    crawls_create_csv,
    crawls_delete,
    crawls_kill,
    crawls_pause,
    crawls_resume,
)
from app.core.database import Base
from app.core.security import hash_password
from app.models.crawl import CrawlRun
from app.models.user import User
from app.schemas.crawl import CrawlCreate


@pytest.mark.asyncio
async def test_mark_run_failed_with_retry_sets_failed_status_and_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_crawls_background_1.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                user = User(
                    email="bg-mark-failed@example.com",
                    hashed_password=hash_password("password123"),
                    role="admin",
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

                run = CrawlRun(
                    user_id=user.id,
                    run_type="crawl",
                    url="https://example.com",
                    status="running",
                    surface="ecommerce_detail",
                    settings={},
                    requested_fields=[],
                    result_summary={},
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                run_id = run.id

            await _mark_run_failed_with_retry(
                run_id=run_id,
                error_message="boom",
                session_factory=session_factory,
            )

            async with session_factory() as verify:
                refreshed = await verify.get(CrawlRun, run_id)
                assert refreshed is not None
                assert refreshed.status == "failed"
                assert refreshed.result_summary.get("error") == "boom"
                assert refreshed.result_summary.get("extraction_verdict") == "error"
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_mark_run_failed_with_retry_keeps_terminal_status_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_crawls_background_2.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                user = User(
                    email="bg-mark-terminal@example.com",
                    hashed_password=hash_password("password123"),
                    role="admin",
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

                run = CrawlRun(
                    user_id=user.id,
                    run_type="crawl",
                    url="https://example.com",
                    status="completed",
                    surface="ecommerce_detail",
                    settings={},
                    requested_fields=[],
                    result_summary={"existing": "value"},
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                run_id = run.id

            await _mark_run_failed_with_retry(
                run_id=run_id,
                error_message="should-not-apply",
                session_factory=session_factory,
            )

            async with session_factory() as verify:
                refreshed = await verify.get(CrawlRun, run_id)
                assert refreshed is not None
                assert refreshed.status == "completed"
                assert refreshed.result_summary.get("existing") == "value"
                assert "error" not in refreshed.result_summary
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_crawls_create_preserves_value_error_as_http_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_error = ValueError("surface must be one of supported values")

    async def _raise_value_error(*_args, **_kwargs):
        raise source_error

    monkeypatch.setattr("app.api.crawls.create_crawl_run", _raise_value_error)

    payload = CrawlCreate(
        run_type="crawl",
        url="https://example.com",
        surface="invalid_surface",
        settings={},
        additional_fields=[],
    )
    user = User(id=1, email="cause-check@example.com", hashed_password="x", role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await crawls_create(payload=payload, session=object(), user=user)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "surface must be one of supported values"
    # Keep traceback chain so logs/handlers can inspect original failure.
    assert exc_info.value.__cause__ is source_error


@pytest.mark.asyncio
async def test_crawls_create_csv_preserves_parse_error_as_http_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_error = ValueError("csv batch request requires a valid surface")

    async def _raise_value_error(*_args, **_kwargs):
        raise source_error

    monkeypatch.setattr("app.api.crawls.create_crawl_run", _raise_value_error)
    upload = UploadFile(filename="urls.csv", file=io.BytesIO(b"https://example.com\n"))
    user = User(id=1, email="csv-cause-check@example.com", hashed_password="x", role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await crawls_create_csv(
            file=upload,
            surface="invalid_surface",
            session=object(),
            user=user,
            additional_fields="",
            settings_json="{}",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "csv batch request requires a valid surface"
    assert exc_info.value.__cause__ is source_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_name", "endpoint_callable", "service_patch_target"),
    [
        ("delete", crawls_delete, "app.api.crawls.delete_run"),
        ("pause", crawls_pause, "app.api.crawls.pause_run"),
        ("resume", crawls_resume, "app.api.crawls.resume_run"),
        ("kill", crawls_kill, "app.api.crawls.kill_run"),
        ("cancel", crawls_cancel, "app.api.crawls.kill_run"),
    ],
)
async def test_conflict_endpoints_preserve_value_error_as_http_cause(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_name: str,
    endpoint_callable,
    service_patch_target: str,
) -> None:
    source_error = ValueError(f"{endpoint_name} rejected current run state")

    class _DummyRun:
        id = 99
        user_id = 1
        status = "running"

    async def _return_run(*_args, **_kwargs):
        return _DummyRun()

    async def _raise_value_error(*_args, **_kwargs):
        raise source_error

    monkeypatch.setattr("app.api.crawls.get_run", _return_run)
    monkeypatch.setattr(service_patch_target, _raise_value_error)

    user = User(id=1, email="conflict-cause-check@example.com", hashed_password="x", role="admin")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint_callable(run_id=99, session=object(), user=user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == str(source_error)
    assert exc_info.value.__cause__ is source_error

