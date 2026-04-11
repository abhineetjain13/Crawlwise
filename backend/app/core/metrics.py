from __future__ import annotations

try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
except ImportError:  # pragma: no cover - optional dependency fallback
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    CollectorRegistry = None
    Counter = None
    Gauge = None
    Histogram = None
    generate_latest = None
from sqlalchemy import func, select, text

from app.core.database import SessionLocal, engine
from app.core.redis import get_redis, redis_failure_total, redis_is_enabled
from app.models.crawl import CrawlRun
from app.services.acquisition import browser_pool_snapshot

class _NoopMetric:
    def labels(self, **_: object) -> "_NoopMetric":
        return self

    def set(self, _: object) -> None:
        return None

    def clear(self) -> None:
        return None

    def observe(self, _: float) -> None:
        return None

    def inc(self, _: float = 1.0) -> None:
        return None


_registry = CollectorRegistry() if CollectorRegistry is not None else None

crawl_runs_total = (Gauge(
    "crawl_runs_total",
    "Crawl runs grouped by status.",
    labelnames=("status",),
    registry=_registry,
) if Gauge is not None else _NoopMetric())
browser_pool_size = (Gauge(
    "browser_pool_size",
    "Current pooled browser count.",
    registry=_registry,
) if Gauge is not None else _NoopMetric())
database_connections_active = (Gauge(
    "database_connections_active",
    "Currently checked-out database connections.",
    registry=_registry,
) if Gauge is not None else _NoopMetric())
redis_failures_total_metric = (Gauge(
    "redis_failures_total",
    "Redis fail-open incidents.",
    registry=_registry,
) if Gauge is not None else _NoopMetric())
acquisition_duration_seconds = (Histogram(
    "acquisition_duration_seconds",
    "Acquisition duration in seconds.",
    registry=_registry,
) if Histogram is not None else _NoopMetric())
llm_task_duration_seconds = (Histogram(
    "llm_task_duration_seconds",
    "LLM task duration in seconds.",
    labelnames=("task_type", "provider", "outcome"),
    registry=_registry,
) if Histogram is not None else _NoopMetric())
llm_task_outcomes_total = (Counter(
    "llm_task_outcomes_total",
    "LLM task outcomes grouped by task, provider, and error category.",
    labelnames=("task_type", "provider", "outcome", "error_category"),
    registry=_registry,
) if Counter is not None else _NoopMetric())


def observe_acquisition_duration(seconds: float) -> None:
    if seconds < 0:
        return
    acquisition_duration_seconds.observe(seconds)


def observe_llm_task_duration(
    *,
    task_type: str,
    provider: str,
    outcome: str,
    seconds: float,
) -> None:
    if seconds < 0:
        return
    llm_task_duration_seconds.labels(
        task_type=str(task_type or "unknown"),
        provider=str(provider or "unknown"),
        outcome=str(outcome or "unknown"),
    ).observe(seconds)


def record_llm_task_outcome(
    *,
    task_type: str,
    provider: str,
    outcome: str,
    error_category: str,
) -> None:
    llm_task_outcomes_total.labels(
        task_type=str(task_type or "unknown"),
        provider=str(provider or "unknown"),
        outcome=str(outcome or "unknown"),
        error_category=str(error_category or "none"),
    ).inc()


def _database_connections_checked_out() -> int:
    pool = getattr(engine.sync_engine, "pool", None)
    checked_out = getattr(pool, "checkedout", None)
    if callable(checked_out):
        try:
            return int(checked_out())
        except Exception:
            return 0
    return 0


async def check_database() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_redis() -> bool:
    if not redis_is_enabled():
        return True
    try:
        await get_redis().get("__healthcheck__")
        return True
    except Exception:
        return False


def check_browser_pool() -> bool:
    snapshot = browser_pool_snapshot()
    return bool(snapshot["size"] <= snapshot["max_size"])


async def render_prometheus_metrics() -> tuple[bytes, str]:
    if _registry is None or generate_latest is None:
        lines = [
            f"browser_pool_size {int(browser_pool_snapshot()['size'])}",
            f"database_connections_active {_database_connections_checked_out()}",
            f"redis_failures_total {redis_failure_total()}",
        ]
        return ("\n".join(lines) + "\n").encode("utf-8"), CONTENT_TYPE_LATEST

    async with SessionLocal() as session:
        rows = await session.execute(
            select(CrawlRun.status, func.count(CrawlRun.id)).group_by(CrawlRun.status)
        )
        crawl_runs_total.clear()
        for status, count in rows.all():
            crawl_runs_total.labels(status=str(status or "unknown")).set(int(count or 0))

    browser_pool_size.set(int(browser_pool_snapshot()["size"]))
    database_connections_active.set(_database_connections_checked_out())
    redis_failures_total_metric.set(redis_failure_total())
    return generate_latest(_registry), CONTENT_TYPE_LATEST
