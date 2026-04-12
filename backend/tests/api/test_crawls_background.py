from __future__ import annotations

import io
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from app.api.crawls import (
    _mark_run_failed_with_retry,
    crawls_cancel,
    crawls_create,
    crawls_create_csv,
    crawls_delete,
    crawls_kill,
    crawls_logs_ws,
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

    monkeypatch.setattr(
        "app.api.crawls.create_crawl_run_from_payload", _raise_value_error
    )

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

    monkeypatch.setattr(
        "app.api.crawls.create_crawl_run_from_csv", _raise_value_error
    )
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


@pytest.mark.asyncio
async def test_crawls_logs_ws_releases_db_session_between_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered_sessions: list[object] = []

    @asynccontextmanager
    async def _session_factory():
        session = object()
        entered_sessions.append(session)
        yield session

    async def _resolve_user(_websocket):
        return User(id=1, email="ws@example.com", hashed_password="x", role="admin")

    async def _require_accessible_run(session, *, run_id: int, user: User):
        assert session is entered_sessions[0]
        assert run_id == 42
        assert user.id == 1
        return SimpleNamespace(id=run_id, status_value="running")

    log_batches = [
        [SimpleNamespace(id=10)],
        [],
    ]
    run_states = iter(
        [
            SimpleNamespace(id=42, status_value="running"),
            SimpleNamespace(id=42, status_value="completed"),
        ]
    )

    async def _get_run_logs(session, run_id: int, *, after_id=None, limit=None):
        assert session in entered_sessions[1:]
        assert run_id == 42
        return log_batches.pop(0)

    async def _get_run(session, run_id: int):
        assert session in entered_sessions[1:]
        assert run_id == 42
        return next(run_states)

    monkeypatch.setattr("app.api.crawls.SessionLocal", _session_factory)
    monkeypatch.setattr("app.api.crawls._resolve_websocket_user", _resolve_user)
    monkeypatch.setattr(
        "app.api.crawls._require_accessible_run",
        _require_accessible_run,
    )
    monkeypatch.setattr("app.api.crawls.get_run_logs", _get_run_logs)
    monkeypatch.setattr("app.api.crawls.get_run", _get_run)
    monkeypatch.setattr(
        "app.api.crawls.serialize_log_event",
        lambda row: {"id": row.id},
    )

    class _FakeWebSocket:
        def __init__(self) -> None:
            self.accepted = False
            self.messages: list[dict[str, int]] = []
            self.closed: tuple[int, str] | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, payload: dict[str, int]) -> None:
            self.messages.append(payload)

        async def close(self, code: int, reason: str) -> None:
            self.closed = (code, reason)

    websocket = _FakeWebSocket()

    await crawls_logs_ws(websocket=websocket, run_id=42)

    assert websocket.accepted is True
    assert websocket.messages == [{"id": 10}]
    assert websocket.closed == (1000, "Run completed")
    assert len(entered_sessions) == 3
    assert len({id(session) for session in entered_sessions}) == 3

