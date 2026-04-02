# Review and promotion service.
from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.models.selector import Selector
from app.services.knowledge_base.store import save_domain_mapping


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    selector_result = await session.execute(select(Selector).where(Selector.domain == _domain(run.url)))
    selectors = list(selector_result.scalars().all())
    normalized_fields = sorted({key for record in records for key in record.data.keys()})
    discovered_fields = sorted({key for record in records for key in {**record.raw_data, **record.data}.keys()})
    suggested_mapping = {field: field for field in discovered_fields}
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "suggested_mapping": suggested_mapping,
        "selector_memory": [
            {"field_name": row.field_name, "selector": row.selector, "selector_type": row.selector_type}
            for row in selectors
        ],
    }


async def save_review(session: AsyncSession, run: CrawlRun, selections: list[dict]) -> dict:
    mapping = {row["source_field"]: row["output_field"] for row in selections}
    domain = _domain(run.url)
    save_domain_mapping(domain, run.surface, mapping)
    promotion = ReviewPromotion(
        run_id=run.id,
        domain=domain,
        surface=run.surface,
        approved_schema={"fields": list(dict.fromkeys(mapping.values()))},
        field_mapping=mapping,
        selector_memory={},
    )
    session.add(promotion)
    await session.commit()
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "selected_fields": list(dict.fromkeys(mapping.values())),
        "field_mapping": mapping,
    }


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()
