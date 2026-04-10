# Tests for paged record exports.
from __future__ import annotations

import json

import pytest
from app.api.records import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
    RUN_NOT_FOUND_DETAIL,
    _artifact_table_rows,
    _clean_export_data,
    _collect_export_rows,
    _legacy_fallback_markdown_rows,
    _stream_export_csv,
    export_artifacts_json,
    export_csv,
    export_json,
    export_markdown,
    export_tables_csv,
    record_provenance,
    router,
)
from app.core.security import hash_password
from app.models.crawl import CrawlRecord, CrawlRun
from app.models.user import User
from fastapi import HTTPException
from fastapi.routing import APIRoute


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
async def test_export_markdown_includes_clean_sections_fields_and_headers(db_session, test_user):
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

    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url="https://example.com/item-1",
            data={
                "title": "Sylan 2 Shoe Men's",
                "description": "Built for speed.\n- Stable ride\n- Fast toe-off",
                "price": "$180",
            },
            raw_data={},
            discovered_data={},
            source_trace={
                "semantic": {
                    "sections": {"materials_and_care": "Spot clean only."},
                    "specifications": {"weight": "310 g", "drop": "6 mm"},
                }
            },
            raw_html_path=None,
        )
    )
    await db_session.commit()

    response = await export_markdown(run.id, session=db_session, _=test_user)
    payload = await _read_streaming_body(response)

    assert "# Sylan 2 Shoe Men's" in payload
    assert "Source: <https://example.com/item-1>" in payload
    assert "## Description" in payload
    assert "- Stable ride" in payload
    assert "## Materials and care" in payload
    assert "## Fields" in payload
    assert "- **Price:** $180" in payload
    assert "## Specifications" in payload
    assert "- **Weight:** 310 g" in payload
    assert response.headers[EXPORT_PAGING_HEADER] == "1"
    assert response.headers[EXPORT_TOTAL_HEADER] == "1"
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
    assert page_calls == [1, 2]


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
async def test_export_csv_does_not_fall_back_to_typed_table_rows(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/specs",
        surface="tabular",
        status="completed",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url="https://example.com/specs",
            data={"page_markdown": "# Specs"},
            raw_data={},
            discovered_data={},
            source_trace={
                "manifest_trace": {
                    "tables": [
                        {
                            "table_index": 1,
                            "caption": "Specifications",
                            "headers": [{"text": "Name"}, {"text": "Value"}],
                            "rows": [{"row_index": 1, "cells": [{"text": "Voltage"}, {"text": "220V"}]}],
                        }
                    ]
                }
            },
            raw_html_path=None,
        )
    )
    await db_session.commit()

    response = await export_csv(run.id, session=db_session, _=test_user)
    payload = await _read_streaming_body(response)

    assert payload == ""


@pytest.mark.asyncio
async def test_export_tables_csv_returns_flattened_rows(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/specs",
        surface="tabular",
        status="completed",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/specs",
        data={},
        raw_data={},
        discovered_data={},
        source_trace={
            "manifest_trace": {
                "tables": [
                    {
                        "table_index": 2,
                        "section_title": "Specs",
                        "headers": [{"text": "Field"}, {"text": "Reading"}],
                        "rows": [{"row_index": 3, "cells": [{"text": "Current"}, {"text": "5A"}]}],
                    }
                ]
            }
        },
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    response = await export_tables_csv(run.id, session=db_session, _=test_user)
    payload = await _read_streaming_body(response)

    assert "Current" in payload
    assert "5A" in payload


@pytest.mark.asyncio
async def test_export_artifacts_json_includes_typed_bundles(db_session, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/item",
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
        data={"title": "Widget", "page_markdown": "# Widget"},
        raw_data={},
        discovered_data={},
        source_trace={
            "type": "detail",
            "manifest_trace": {
                "json_ld": [{"name": "Widget"}],
                "tables": [],
            },
        },
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    response = await export_artifacts_json(run.id, session=db_session, _=test_user)
    payload = json.loads(await _read_streaming_body(response))

    assert payload[0]["structured_record"]["title"] == "Widget"
    assert payload[0]["evidence_refs"]["json_ld_count"] == 1


def test_artifact_table_rows_flattens_manifest_tables():
    row = CrawlRecord(
        id=7,
        run_id=1,
        source_url="https://example.com/table",
        data={},
        raw_data={},
        discovered_data={},
        source_trace={
            "manifest_trace": {
                "tables": [
                    {
                        "table_index": 1,
                        "headers": [{"text": "Key"}, {"text": "Value"}],
                        "rows": [{"row_index": 1, "cells": [{"text": "Weight"}, {"text": "10kg"}]}],
                    }
                ]
            }
        },
        raw_html_path=None,
    )

    flattened = _artifact_table_rows(row)

    assert flattened[0]["Key"] == "Weight"
    assert flattened[0]["Value"] == "10kg"


def test_legacy_fallback_markdown_rows_extracts_structured_rows():
    row = CrawlRecord(
        id=8,
        run_id=1,
        source_url="https://example.com/jobs",
        data={
            "page_markdown": "# Jobs\n\n## [Executive Assistant](https://example.com/jobs/executive-assistant)\nHigh-level support role.\n## [Recruiter](https://example.com/jobs/recruiter)\nSources talent.",
        },
        raw_data={},
        discovered_data={},
        source_trace={"type": "listing_fallback"},
        raw_html_path=None,
    )

    rows = _legacy_fallback_markdown_rows(row)

    assert rows[0]["title"] == "Executive Assistant"
    assert rows[0]["url"] == "https://example.com/jobs/executive-assistant"
    assert rows[0]["description"] == "High-level support role."


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
