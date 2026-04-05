# Tests for paged record exports.
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.api.records import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
    RUN_NOT_FOUND_DETAIL,
    _collect_export_rows,
    _clean_export_data,
    _stream_export_csv,
    export_csv,
    export_json,
    record_provenance,
    router,
)
from app.models.crawl import CrawlRecord, CrawlRun
from app.models.user import User
from app.core.security import hash_password


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


@pytest.mark.asyncio
async def test_stream_export_csv_consumes_row_stream_once(monkeypatch):
    class DummyRow:
        def __init__(self, data):
            self.data = data

    monkeypatch.setattr("app.api.records.MAX_RECORD_PAGE_SIZE", 1)
    page_calls: list[int] = []

    async def _fake_get_run_records(_session, _run_id, page, limit):
        assert limit == 1
        page_calls.append(page)
        if page == 1:
            return ([DummyRow({"title": "Item 1"})], 2)
        if page == 2:
            return ([DummyRow({"title": "Item 2", "description": "Desc 2"})], 2)
        return ([], 2)

    monkeypatch.setattr("app.api.records.get_run_records", _fake_get_run_records)

    chunks: list[str] = []
    async for chunk in _stream_export_csv(session=None, run_id=123):
        chunks.append(chunk)

    payload = "".join(chunks)
    assert "title" in payload
    assert "description" in payload
    assert "Item 1" in payload
    assert "Item 2" in payload
    assert page_calls == [1, 2, 1, 2]


def test_clean_export_data_preserves_duplicate_alias_fields():
    cleaned = _clean_export_data({
        "price": "50",
        "50_price": "50",
        "title": "HeatGear Elite",
        "product_title": "HeatGear Elite",
        "_private": "ignore",
    })

    assert cleaned == {
        "price": "50",
        "50_price": "50",
        "title": "HeatGear Elite",
        "product_title": "HeatGear Elite",
    }


@pytest.mark.asyncio
async def test_export_csv_discovers_fields_beyond_first_page(db_session, test_user):
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

    for idx in range(MAX_RECORD_PAGE_SIZE + 1):
        payload = {"title": f"Item {idx}"}
        if idx == MAX_RECORD_PAGE_SIZE:
            payload["rare_field"] = "late value"
        db_session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=f"https://example.com/{idx}",
                data=payload,
                raw_data={},
                discovered_data={},
                source_trace={},
                raw_html_path=None,
            )
        )
    await db_session.commit()

    response = await export_csv(run.id, session=db_session, _=test_user)
    payload = await _read_streaming_body(response)
    header = payload.splitlines()[0]

    assert "rare_field" in header


@pytest.mark.asyncio
async def test_record_provenance_returns_manifest_trace(db_session, test_user):
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

    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/item",
        data={"title": "Item"},
        raw_data={},
        discovered_data={},
        source_trace={
            "type": "detail",
            "manifest_trace": {"json_ld": [{"name": "Item"}]},
        },
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    payload = await record_provenance(record.id, session=db_session, current_user=test_user)

    assert payload.manifest_trace["json_ld"][0]["name"] == "Item"
    assert "manifest_trace" not in payload.source_trace


@pytest.mark.asyncio
async def test_record_provenance_masks_unauthorized_run_access(db_session):
    owner = User(
        email="owner@example.com",
        hashed_password=hash_password("password123"),
        role="user",
    )
    viewer = User(
        email="viewer@example.com",
        hashed_password=hash_password("password123"),
        role="user",
    )
    db_session.add_all([owner, viewer])
    await db_session.flush()

    run = CrawlRun(
        user_id=owner.id,
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

    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/item",
        data={"title": "Item"},
        raw_data={},
        discovered_data={},
        source_trace={},
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await record_provenance(record.id, session=db_session, current_user=viewer)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == RUN_NOT_FOUND_DETAIL


def test_record_provenance_route_documents_combined_404_description():
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/records/{record_id}/provenance"
    )

    assert route.responses[404]["description"] == "Record not found or Run not found"
