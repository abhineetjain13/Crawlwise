# Dashboard aggregation service.
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PROJECT_ROOT, settings
from app.core.database import is_sqlite
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun, ReviewPromotion
from app.models.llm import LLMCostLog
from app.models.selector import Selector
from app.services.crawl_state import ACTIVE_STATUSES
from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import reset_learned_state

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
                    run_scope.where(CrawlRun.status.in_([status.value for status in ACTIVE_STATUSES])).subquery()
                )
            )
        ).scalar()
        or 0
    )
    if user_id is None:
        total_records = int((await session.execute(select(func.count()).select_from(CrawlRecord))).scalar() or 0)
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
    recent_result = await session.execute(run_scope.order_by(CrawlRun.created_at.desc()).limit(10))
    recent_runs = list(recent_result.scalars().all())
    domain_rows = await session.execute(select(CrawlRun.url) if user_id is None else select(CrawlRun.url).where(CrawlRun.user_id == user_id))
    counts: dict[str, int] = {}
    for url in domain_rows.scalars().all():
        domain = normalize_domain(url or "") or "unknown"
        counts[domain] = counts.get(domain, 0) + 1
    top_domains = [
        {"domain": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    return {
        "total_runs": total_runs,
        "active_runs": active_runs,
        "total_records": total_records,
        "recent_runs": recent_runs,
        "top_domains": top_domains,
    }


async def reset_application_data(session: AsyncSession) -> dict:
    try:
        crawl_logs_deleted = await session.execute(delete(CrawlLog))
        crawl_records_deleted = await session.execute(delete(CrawlRecord))
        promotions_deleted = await session.execute(delete(ReviewPromotion))
        llm_cost_deleted = await session.execute(delete(LLMCostLog))
        selectors_deleted = await session.execute(delete(Selector))
        crawl_runs_deleted = await session.execute(delete(CrawlRun))
        if is_sqlite:
            await _reset_sqlite_sequences(session)
        await session.commit()
        if is_sqlite:
            try:
                async with session.bind.connect() as connection:
                    connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
                    await connection.execute(text("VACUUM"))
            except Exception:
                logger.exception("SQLite VACUUM failed after application data reset")
    except Exception:
        await session.rollback()
        raise

    artifacts_removed = _reset_directory(settings.artifacts_dir)
    cookies_removed = _reset_directory(settings.cookie_store_dir)
    legacy_artifacts_removed = sum(_reset_directory(path) for path in _legacy_artifact_paths())
    await reset_learned_state()

    return {
        "crawl_runs_deleted": crawl_runs_deleted.rowcount or 0,
        "crawl_records_deleted": crawl_records_deleted.rowcount or 0,
        "crawl_logs_deleted": crawl_logs_deleted.rowcount or 0,
        "review_promotions_deleted": promotions_deleted.rowcount or 0,
        "llm_cost_logs_deleted": llm_cost_deleted.rowcount or 0,
        "selectors_deleted": selectors_deleted.rowcount or 0,
        "artifacts_removed": artifacts_removed,
        "legacy_artifacts_removed": legacy_artifacts_removed,
        "cookies_removed": cookies_removed,
        "knowledge_base_reset": True,
    }


def _reset_directory(path) -> int:
    if not path.exists():
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
        except Exception:
            logger.exception("Failed to remove path during reset: %s", child)
    path.mkdir(parents=True, exist_ok=True)
    return removed


async def _reset_sqlite_sequences(session: AsyncSession) -> None:
    sequence_table = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
    )
    if not sequence_table.scalar():
        return
    await session.execute(
        text(
            """
            DELETE FROM sqlite_sequence
            WHERE name IN ('crawl_runs', 'crawl_records', 'crawl_logs', 'review_promotions', 'selectors', 'llm_cost_log')
            """
        )
    )


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
