# Dashboard aggregation service.
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import PROJECT_ROOT, settings
from app.models.crawl import (
    CrawlLog,
    CrawlRecord,
    CrawlRun,
    DomainMemory,
    ReviewPromotion,
)
from app.models.llm import LLMCostLog
from app.services.acquisition.browser_client import reset_browser_pool_state
from app.services.acquisition.pacing import reset_pacing_state
from app.services.crawl_state import ACTIVE_STATUSES
from app.services.robots_policy import reset_robots_policy_cache
from app.services.config.crawl_runtime import (
    LONG_RUN_THRESHOLD_SECONDS,
    MAX_DURATION_SAMPLE_SIZE,
    STALLED_RUN_THRESHOLD_SECONDS,
)
from app.services.domain_utils import normalize_domain
from app.services.runtime_metrics import snapshot as runtime_metrics_snapshot
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def build_dashboard(session: AsyncSession, *, user_id: int | None = None) -> dict:
    run_scope = select(CrawlRun)
    if user_id is not None:
        run_scope = run_scope.where(CrawlRun.user_id == user_id)

    total_runs = int(
        (
            await session.execute(
                select(func.count()).select_from(run_scope.subquery())
            )
        ).scalar()
        or 0
    )
    active_runs = int(
        (
            await session.execute(
                select(func.count()).select_from(
                    run_scope.where(
                        CrawlRun.status.in_(
                            [status.value for status in ACTIVE_STATUSES]
                        )
                    ).subquery()
                )
            )
        ).scalar()
        or 0
    )
    if user_id is None:
        total_records = int(
            (
                await session.execute(select(func.count()).select_from(CrawlRecord))
            ).scalar()
            or 0
        )
    else:
        total_records = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(CrawlRecord)
                    .join(CrawlRun, CrawlRun.id == CrawlRecord.run_id)
                    .where(CrawlRun.user_id == user_id)
                )
            ).scalar()
            or 0
        )
    recent_result = await session.execute(
        run_scope.order_by(CrawlRun.created_at.desc()).limit(10)
    )
    recent_runs = list(recent_result.scalars().all())
    domain_rows = await session.execute(
        select(CrawlRun.url)
        if user_id is None
        else select(CrawlRun.url).where(CrawlRun.user_id == user_id)
    )
    counts: dict[str, int] = {}
    for url in domain_rows.scalars().all():
        domain = normalize_domain(url or "") or "unknown"
        counts[domain] = counts.get(domain, 0) + 1
    top_domains = [
        {"domain": key, "count": value}
        for key, value in sorted(
            counts.items(), key=lambda item: item[1], reverse=True
        )[:5]
    ]
    return {
        "total_runs": total_runs,
        "active_runs": active_runs,
        "total_records": total_records,
        "recent_runs": recent_runs,
        "top_domains": top_domains,
    }


async def reset_application_data(session: AsyncSession) -> dict:
    counts = {
        "crawl_runs_deleted": await _count_rows(session, CrawlRun),
        "crawl_records_deleted": await _count_rows(session, CrawlRecord),
        "crawl_logs_deleted": await _count_rows(session, CrawlLog),
        "review_promotions_deleted": await _count_rows(session, ReviewPromotion),
        "llm_cost_logs_deleted": await _count_rows(session, LLMCostLog),
        "domain_memory_deleted": await _count_rows(session, DomainMemory),
    }
    try:
        await _reset_database_tables(session)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await reset_browser_pool_state()
    await reset_pacing_state()
    reset_robots_policy_cache()

    artifacts_removed = _reset_directory(settings.artifacts_dir)
    cookies_removed = _reset_directory(settings.cookie_store_dir)
    legacy_artifacts_removed = sum(
        _reset_directory(path, create_if_missing=False)
        for path in _legacy_artifact_paths()
    )
    return {
        **counts,
        "artifacts_removed": artifacts_removed,
        "legacy_artifacts_removed": legacy_artifacts_removed,
        "cookies_removed": cookies_removed,
        "knowledge_base_reset": False,
    }


async def _count_rows(session: AsyncSession, model: type) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar() or 0
    )


async def _reset_database_tables(session: AsyncSession) -> None:
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    if dialect_name == "postgresql":
        await session.execute(
            text(
                "TRUNCATE TABLE "
                "crawl_logs, crawl_records, review_promotions, "
                "llm_cost_log, domain_memory, crawl_runs "
                "RESTART IDENTITY CASCADE"
            )
        )
        return

    await session.execute(delete(CrawlLog))
    await session.execute(delete(CrawlRecord))
    await session.execute(delete(ReviewPromotion))
    await session.execute(delete(LLMCostLog))
    await session.execute(delete(DomainMemory))
    await session.execute(delete(CrawlRun))
    if dialect_name == "sqlite":
        sqlite_sequence_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'sqlite_sequence'"
                )
            )
        ).scalar()
        if sqlite_sequence_exists:
            await session.execute(
                text(
                    "DELETE FROM sqlite_sequence "
                    "WHERE name IN ("
                    "'crawl_logs', 'crawl_records', 'review_promotions', "
                    "'llm_cost_log', 'domain_memory', 'crawl_runs'"
                    ")"
                )
            )


def _reset_directory(path, *, create_if_missing: bool = True) -> int:
    if not path.exists():
        if create_if_missing:
            path.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            if not child.exists():
                removed += 1
            else:
                logger.warning("Failed to remove path during reset: %s", child)
        except FileNotFoundError:
            removed += 1
        except OSError:
            logger.exception("Failed to remove path during reset: %s", child)
    if create_if_missing:
        path.mkdir(parents=True, exist_ok=True)
    return removed


def _legacy_artifact_paths() -> list[Path]:
    candidates = [
        PROJECT_ROOT / "backend" / "backend" / "artifacts",
    ]
    normalized_current = Path(settings.artifacts_dir).resolve()
    results: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved == normalized_current:
            continue
        if resolved not in results:
            results.append(resolved)
    return results


async def build_operational_metrics(session: AsyncSession) -> dict:
    """Build lightweight runtime + DB-backed operational metrics."""
    runtime = await runtime_metrics_snapshot()
    long_run_threshold_seconds = LONG_RUN_THRESHOLD_SECONDS
    stalled_run_threshold_seconds = STALLED_RUN_THRESHOLD_SECONDS
    run_duration_rows = await session.execute(
        select(
            CrawlRun.created_at,
            CrawlRun.completed_at,
        )
        .where(CrawlRun.created_at.is_not(None))
        .order_by(CrawlRun.created_at.desc())
        .limit(MAX_DURATION_SAMPLE_SIZE)
    )
    durations_seconds: list[float] = []
    long_running_count = 0
    active_without_stage_count = 0
    active_stalled_no_progress_count = 0
    active_status_values = {status.value for status in ACTIVE_STATUSES}
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for created_at, completed_at in run_duration_rows:
        created_ts = (
            created_at.replace(tzinfo=UTC)
            if getattr(created_at, "tzinfo", None) is None
            else created_at.astimezone(UTC)
        )
        completed_ts = (
            completed_at.replace(tzinfo=UTC)
            if completed_at is not None
            and getattr(completed_at, "tzinfo", None) is None
            else completed_at.astimezone(UTC)
            if completed_at is not None
            else None
        )
        end_time = completed_ts or now
        duration = max(0.0, (end_time - created_ts).total_seconds())
        durations_seconds.append(duration)
    active_rows = await session.execute(
        select(CrawlRun.created_at, CrawlRun.updated_at, CrawlRun.result_summary).where(
            CrawlRun.status.in_(list(active_status_values))
        )
    )
    for created_at, updated_at, result_summary in active_rows:
        if not created_at:
            continue
        summary = result_summary if isinstance(result_summary, dict) else {}
        current_stage = str(summary.get("current_stage") or "").strip()
        created_ts = (
            created_at.replace(tzinfo=UTC)
            if getattr(created_at, "tzinfo", None) is None
            else created_at.astimezone(UTC)
        )
        active_duration = max(0.0, (now - created_ts).total_seconds())
        if active_duration >= long_run_threshold_seconds:
            long_running_count += 1
        if not current_stage:
            active_without_stage_count += 1
            if updated_at is not None:
                updated_ts = (
                    updated_at.replace(tzinfo=UTC)
                    if getattr(updated_at, "tzinfo", None) is None
                    else updated_at.astimezone(UTC)
                )
                seconds_since_update = max(0.0, (now - updated_ts).total_seconds())
                if seconds_since_update >= stalled_run_threshold_seconds:
                    active_stalled_no_progress_count += 1
    avg_duration = (
        round(sum(durations_seconds) / len(durations_seconds), 2)
        if durations_seconds
        else 0.0
    )
    return {
        "runtime_counters": {
            "db_lock_errors_total": int(runtime.get("db_lock_errors_total", 0)),
            "db_lock_retries_total": int(runtime.get("db_lock_retries_total", 0)),
            "browser_launch_failures_total": int(
                runtime.get("browser_launch_failures_total", 0)
            ),
            "proxy_exhaustion_total": int(runtime.get("proxy_exhaustion_total", 0)),
        },
        "run_duration": {
            "active_long_running_threshold_seconds": long_run_threshold_seconds,
            "active_long_running_count": long_running_count,
            "average_duration_seconds": avg_duration,
        },
        "active_health": {
            "stalled_run_threshold_seconds": stalled_run_threshold_seconds,
            "active_without_stage_count": active_without_stage_count,
            "active_stalled_no_progress_count": active_stalled_no_progress_count,
        },
    }
