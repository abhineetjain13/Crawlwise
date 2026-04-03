# Review and promotion service.
from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.models.selector import Selector
from app.services.knowledge_base.store import (
    get_canonical_fields,
    get_domain_mapping,
    save_canonical_fields,
    save_domain_mapping,
)


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    selector_result = await session.execute(select(Selector).where(Selector.domain == _domain(run.url)))
    selectors = list(selector_result.scalars().all())
    canonical_fields = get_canonical_fields(run.surface)
    domain_mapping = get_domain_mapping(_domain(run.url), run.surface)
    normalized_fields = sorted({key for record in records for key in _safe_dict(record.data).keys()})
    discovered_fields = sorted({
        key
        for record in records
        for key in {
            **_safe_dict(record.discovered_data),
            **_safe_dict(record.raw_data),
            **_safe_dict(record.data),
        }.keys()
        if not str(key).startswith("_")
    })
    suggested_mapping = {field: domain_mapping.get(field, field) for field in discovered_fields}
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "canonical_fields": canonical_fields,
        "domain_mapping": domain_mapping,
        "suggested_mapping": suggested_mapping,
        "selector_memory": [
            {"field_name": row.field_name, "selector": row.selector, "selector_type": row.selector_type}
            for row in selectors
        ],
    }


async def save_review(session: AsyncSession, run: CrawlRun, selections: list[dict]) -> dict:
    selected_rows = [
        row
        for row in selections
        if bool(row.get("selected", True))
        and str(row.get("source_field") or "").strip()
        and str(row.get("output_field") or "").strip()
    ]
    mapping = {
        str(row["source_field"]).strip(): str(row["output_field"]).strip()
        for row in selected_rows
    }
    domain = _domain(run.url)
    save_domain_mapping(domain, run.surface, mapping)
    canonical_fields = save_canonical_fields(run.surface, list(mapping.values()))
    promotion = ReviewPromotion(
        run_id=run.id,
        domain=domain,
        surface=run.surface,
        approved_schema={"fields": canonical_fields},
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
        "canonical_fields": canonical_fields,
        "field_mapping": mapping,
    }


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()


def _safe_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}
