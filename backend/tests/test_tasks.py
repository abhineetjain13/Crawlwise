from __future__ import annotations

import signal

from app import tasks


def test_install_task_signal_handlers_restores_sig_dfl_for_none(
    monkeypatch,
) -> None:
    recorded: list[tuple[int, object]] = []

    def _fake_getsignal(signum: int):
        return None

    def _fake_signal(signum: int, handler):
        recorded.append((signum, handler))
        return handler

    monkeypatch.setattr(tasks.signal, "getsignal", _fake_getsignal)
    monkeypatch.setattr(tasks.signal, "signal", _fake_signal)

    with tasks._install_task_signal_handlers():
        pass

    assert recorded[-2:] == [
        (int(signal.SIGTERM), signal.SIG_DFL),
        (int(signal.SIGINT), signal.SIG_DFL),
    ]


def test_run_task_in_worker_loop_installs_asyncio_exception_filter(
    monkeypatch,
) -> None:
    class FakeTask:
        def done(self) -> bool:
            return False

    class FakeLoop:
        def __init__(self) -> None:
            self.closed = False

        def create_task(self, coro, name=None):
            if hasattr(coro, "close"):
                coro.close()
            return FakeTask()

        def run_until_complete(self, awaitable):
            if hasattr(awaitable, "close"):
                awaitable.close()
            return None

        async def shutdown_asyncgens(self):
            return None

        async def shutdown_default_executor(self):
            return None

        def close(self) -> None:
            self.closed = True

    loop = FakeLoop()
    installed_loops: list[object] = []
    event_loops: list[object] = []

    monkeypatch.setattr(tasks.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(tasks.asyncio, "set_event_loop", event_loops.append)
    monkeypatch.setattr(tasks, "install_asyncio_exception_filter", installed_loops.append)

    tasks._run_task_in_worker_loop(42)

    assert installed_loops == [loop]
    assert event_loops == [loop, None]
    assert loop.closed is True
