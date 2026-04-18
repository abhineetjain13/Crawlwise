from __future__ import annotations

import json

import pytest

from app.models.crawl import CrawlRecord
from app.services.crawl_crud import create_crawl_run
from app.services.record_export_service import stream_export_csv, stream_export_json
from sqlalchemy.ext.asyncio import AsyncSession


async def _collect_chunks(stream) -> str:
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_export_streams_serialize_clean_record_data(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={
                "title": "Widget Prime",
                "price": "19.99",
                "_source": "dom",
                "page_markdown": "# internal",
                "empty_field": "",
            },
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    await db_session.commit()

    exported_json = await _collect_chunks(stream_export_json(db_session, run.id))
    exported_csv = await _collect_chunks(stream_export_csv(db_session, run.id))
    json_rows = json.loads(exported_json)

    assert json_rows == [{"price": "19.99", "title": "Widget Prime"}]
    assert "_source" not in exported_csv
    assert "page_markdown" not in exported_csv
    assert "Widget Prime" in exported_csv
