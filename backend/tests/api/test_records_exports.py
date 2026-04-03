# Tests for paged record exports.
from __future__ import annotations

import json

import pytest

from app.api.records import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
    _collect_export_rows,
    export_csv,
    export_json,
)
from app.models.crawl import CrawlRecord, CrawlRun


async def _read_streaming_body(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


@pytest.mark.asyncio
async def test_collect_export_rows_pages_until_total(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status="completed",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    total_records = MAX_RECORD_PAGE_SIZE + 5
    for idx in range(total_records):
        db_session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=f"https://example.com/{idx}",
                data={"title": f"Item {idx}", "description": f"Desc {idx}"},
                raw_data={},
                discovered_data={},
                source_trace={},
                raw_html_path=None,
            )
        )
    await db_session.commit()

    rows, metadata = await _collect_export_rows(db_session, run.id)

    assert len(rows) == total_records
    assert metadata["pages_used"] == 2
    assert metadata["total"] == total_records
    assert metadata["truncated"] is False


@pytest.mark.asyncio
async def test_export_json_includes_all_rows_and_paging_headers(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status="completed",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    total_records = MAX_RECORD_PAGE_SIZE + 3
    for idx in range(total_records):
        db_session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=f"https://example.com/{idx}",
                data={"title": f"Item {idx}"},
                raw_data={},
                discovered_data={},
                source_trace={},
                raw_html_path=None,
            )
        )
    await db_session.commit()

    response = await export_json(run.id, session=db_session, _=test_user)
    payload = json.loads(await _read_streaming_body(response))

    assert len(payload) == total_records
    assert response.headers[EXPORT_PAGING_HEADER] == "2"
    assert response.headers[EXPORT_TOTAL_HEADER] == str(total_records)
    assert response.headers[EXPORT_PARTIAL_HEADER] == "false"


@pytest.mark.asyncio
async def test_export_csv_includes_all_rows_and_paging_headers(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status="completed",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    total_records = MAX_RECORD_PAGE_SIZE + 2
    for idx in range(total_records):
        db_session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=f"https://example.com/{idx}",
                data={"title": f"Item {idx}", "description": f"Desc {idx}"},
                raw_data={},
                discovered_data={},
                source_trace={},
                raw_html_path=None,
            )
        )
    await db_session.commit()

    response = await export_csv(run.id, session=db_session, _=test_user)
    payload = await _read_streaming_body(response)

    assert payload.count("\n") == total_records + 1
    assert response.headers[EXPORT_PAGING_HEADER] == "2"
    assert response.headers[EXPORT_TOTAL_HEADER] == str(total_records)
    assert response.headers[EXPORT_PARTIAL_HEADER] == "false"
