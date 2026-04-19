from __future__ import annotations

import json

import pytest

from app.models.crawl import CrawlRecord
from app.services.crawl_crud import create_crawl_run
from app.services import record_export_service
from app.services.record_export_service import (
    stream_export_artifacts_json,
    stream_export_csv,
    stream_export_json,
)
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


@pytest.mark.asyncio
async def test_export_streamers_preserve_order_across_paged_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        CrawlRecord(
            id=1,
            run_id=7,
            source_url="https://example.com/a",
            data={"title": "A"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
        CrawlRecord(
            id=2,
            run_id=7,
            source_url="https://example.com/b",
            data={"title": "B"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
        CrawlRecord(
            id=3,
            run_id=7,
            source_url="https://example.com/c",
            data={"title": "C"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
    ]

    async def _fake_get_run_records(session, run_id, page, page_size):
        del session, page_size
        assert run_id == 7
        pages = {
            1: (rows[:2], 3),
            2: (rows[2:], 3),
        }
        return pages.get(page, ([], 3))

    monkeypatch.setattr(record_export_service, "get_run_records", _fake_get_run_records)
    monkeypatch.setattr(record_export_service, "MAX_RECORD_PAGE_SIZE", 2)

    exported_json = await _collect_chunks(stream_export_json(None, 7))
    exported_csv = await _collect_chunks(stream_export_csv(None, 7))
    exported_artifacts = await _collect_chunks(stream_export_artifacts_json(None, 7))

    json_rows = json.loads(exported_json)
    artifact_rows = json.loads(exported_artifacts)

    assert [row["title"] for row in json_rows] == ["A", "B", "C"]
    assert exported_csv.index("A") < exported_csv.index("B") < exported_csv.index("C")
    assert [row["source_url"] for row in artifact_rows] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
