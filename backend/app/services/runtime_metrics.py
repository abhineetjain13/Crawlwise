from __future__ import annotations

from collections import Counter
from threading import Lock

_COUNTERS: Counter[str] = Counter()
_LOCK = Lock()


def incr(metric_name: str, amount: int = 1) -> None:
    if not metric_name:
        return
    with _LOCK:
        _COUNTERS[metric_name] += int(amount)


def snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTERS)
