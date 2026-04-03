# Dashboard aggregation service.
from __future__ import annotations

import logging
import shutil

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun, ReviewPromotion
from app.models.selector import Selector
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
                    run_scope.where(CrawlRun.status.in_(["pending", "running", "paused"])).subquery()
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
    success_count = int(
        (
            await session.execute(
                select(func.count()).select_from(run_scope.where(CrawlRun.status == "completed").subquery())
            )
        ).scalar()
        or 0
    )
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
        "success_rate": round((success_count / total_runs) * 100, 2) if total_runs else 0.0,
    }


async def reset_application_data(session: AsyncSession) -> dict:
    try:
        crawl_logs_deleted = await session.execute(delete(CrawlLog))
        crawl_records_deleted = await session.execute(delete(CrawlRecord))
        promotions_deleted = await session.execute(delete(ReviewPromotion))
        selectors_deleted = await session.execute(delete(Selector))
        crawl_runs_deleted = await session.execute(delete(CrawlRun))
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    artifacts_removed = _reset_directory(settings.artifacts_dir)
    cookies_removed = _reset_directory(settings.cookie_store_dir)
    reset_learned_state()

    return {
        "crawl_runs_deleted": crawl_runs_deleted.rowcount or 0,
        "crawl_records_deleted": crawl_records_deleted.rowcount or 0,
        "crawl_logs_deleted": crawl_logs_deleted.rowcount or 0,
        "review_promotions_deleted": promotions_deleted.rowcount or 0,
        "selectors_deleted": selectors_deleted.rowcount or 0,
        "artifacts_removed": artifacts_removed,
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
