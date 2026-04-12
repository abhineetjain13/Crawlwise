from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app import tasks


def test_process_run_task_exits_cleanly_after_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: dict[int, object] = {}
    shutdown_calls: list[str] = []

    def _fake_getsignal(signum: int) -> object:
        return handlers.get(signum, 0)

    def _fake_signal(signum: int, handler: object) -> object:
        previous = handlers.get(signum, 0)
        handlers[signum] = handler
        return previous

    @asynccontextmanager
    async def _session_factory():
        yield object()

    async def _fake_process_run(_session, _run_id: int) -> None:
        handler = handlers[tasks.signal.SIGTERM]
        handler(tasks.signal.SIGTERM, None)
        await tasks.asyncio.sleep(0)

    monkeypatch.setattr(tasks.signal, "getsignal", _fake_getsignal)
    monkeypatch.setattr(tasks.signal, "signal", _fake_signal)
    monkeypatch.setattr(tasks, "SessionLocal", _session_factory)
    monkeypatch.setattr(tasks, "process_run_async", _fake_process_run)
    monkeypatch.setattr(
        tasks,
        "shutdown_browser_pool_sync",
        lambda: shutdown_calls.append("shutdown"),
    )

    with pytest.raises(SystemExit) as exc_info:
        tasks.process_run_task(123)

    assert exc_info.value.code == 0
    assert shutdown_calls == ["shutdown"]
