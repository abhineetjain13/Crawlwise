from __future__ import annotations

import io
from contextlib import asynccontextmanager

import pytest
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
from app.models.crawl import CrawlRun
from app.models.user import User
from app.schemas.crawl import CrawlCreate
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_mark_run_failed_with_retry_sets_failed_status_and_error(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        status="running",
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    @asynccontextmanager
    async def _session_factory():
        yield db_session

    await _mark_run_failed_with_retry(
        run_id=run.id,
        error_message="boom",
        session_factory=_session_factory,
    )

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("error") == "boom"
    assert run.result_summary.get("extraction_verdict") == "error"


@pytest.mark.asyncio
async def test_mark_run_failed_with_retry_keeps_terminal_status_unchanged(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        status="completed",
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={"existing": "value"},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    @asynccontextmanager
    async def _session_factory():
        yield db_session

    await _mark_run_failed_with_retry(
        run_id=run.id,
        error_message="should-not-apply",
        session_factory=_session_factory,
    )

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("existing") == "value"
    assert "error" not in run.result_summary


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

