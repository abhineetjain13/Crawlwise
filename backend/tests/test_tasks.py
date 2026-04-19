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
