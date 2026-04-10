from __future__ import annotations

from app.core.redis import redis_fail_open, schedule_fail_open

_RUNTIME_METRICS_KEY = "crawl:runtime:metrics"


def incr(metric_name: str, amount: int = 1) -> None:
    if not metric_name:
        return
    schedule_fail_open(
        lambda redis: redis.hincrby(_RUNTIME_METRICS_KEY, metric_name, int(amount)),
        operation_name=f"runtime_metrics.incr:{metric_name}",
    )


async def snapshot() -> dict[str, int]:
    async def _snapshot(redis) -> dict[str, int]:
        raw = await redis.hgetall(_RUNTIME_METRICS_KEY)
        snapshot: dict[str, int] = {}
        for key, value in raw.items():
            try:
                snapshot[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return snapshot

    return await redis_fail_open(
        _snapshot,
        default={},
        operation_name="runtime_metrics.snapshot",
    )
