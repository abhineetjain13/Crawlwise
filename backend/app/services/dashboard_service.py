# Dashboard aggregation service.
from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun


async def build_dashboard(session: AsyncSession) -> dict:
    total_runs = int((await session.execute(select(func.count()).select_from(CrawlRun))).scalar() or 0)
    active_runs = int(
        (
            await session.execute(
                select(func.count()).select_from(CrawlRun).where(CrawlRun.status.in_(["pending", "running"]))
            )
        ).scalar()
        or 0
    )
    total_records = int((await session.execute(select(func.count()).select_from(CrawlRecord))).scalar() or 0)
    recent_result = await session.execute(select(CrawlRun).order_by(CrawlRun.created_at.desc()).limit(5))
    recent_runs = list(recent_result.scalars().all())
    success_count = int(
        (
            await session.execute(select(func.count()).select_from(CrawlRun).where(CrawlRun.status == "completed"))
        ).scalar()
        or 0
    )
    domain_rows = await session.execute(select(CrawlRun.url))
    counts: dict[str, int] = {}
    for url in domain_rows.scalars().all():
        domain = urlparse(url or "").netloc or "unknown"
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
