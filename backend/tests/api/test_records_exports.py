# Tests for paged record exports.
from __future__ import annotations

import json

import pytest
from app.api.records import (
    export_artifacts_json,
    export_csv,
    export_json,
    export_markdown,
    export_tables_csv,
    record_provenance,
    router,
)
from app.services.record_export_service import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
    RUN_NOT_FOUND_DETAIL,
)
from app.core.security import hash_password
from app.models.user import User
from fastapi import HTTPException
from fastapi.routing import APIRoute
from tests.support import make_crawl_record, make_crawl_run


async def _read_streaming_body(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


async def _seed_export_run(
    db_session,
    *,
    user_id,
    records: list[dict[str, object]] | None = None,
    run_kwargs: dict[str, object] | None = None,
):
    run = make_crawl_run(user_id=user_id, **(run_kwargs or {}))
    db_session.add(run)
    await db_session.flush()

    created_records = []
    for record_kwargs in records or []:
        record = make_crawl_record(run_id=run.id, **record_kwargs)
        db_session.add(record)
        created_records.append(record)

    await db_session.commit()
    return run, created_records


def _assert_export_headers(response, *, total_records: int, pages_used: int) -> None:
    assert response.headers[EXPORT_PAGING_HEADER] == str(pages_used)
    assert response.headers[EXPORT_TOTAL_HEADER] == str(total_records)
    assert response.headers[EXPORT_PARTIAL_HEADER] == "false"


@pytest.mark.asyncio
async def test_export_json_includes_all_rows_and_paging_headers(db_session, test_user):
    total_records = MAX_RECORD_PAGE_SIZE + 3
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        records=[
            {
                "source_url": f"https://example.com/{idx}",
                "data": {"title": f"Item {idx}"},
            }
            for idx in range(total_records)
        ],
    )

    response = await export_json(run.id, session=db_session, current_user=test_user)
    payload = json.loads(await _read_streaming_body(response))

    assert len(payload) == total_records
    _assert_export_headers(response, total_records=total_records, pages_used=2)


@pytest.mark.asyncio
async def test_export_csv_includes_all_rows_and_paging_headers(db_session, test_user):
    total_records = MAX_RECORD_PAGE_SIZE + 2
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        records=[
            {
                "source_url": f"https://example.com/{idx}",
                "data": {"title": f"Item {idx}", "description": f"Desc {idx}"},
            }
            for idx in range(total_records)
        ],
    )

    response = await export_csv(run.id, session=db_session, current_user=test_user)
    payload = await _read_streaming_body(response)

    assert payload.count("\n") == total_records + 1
    _assert_export_headers(response, total_records=total_records, pages_used=2)


@pytest.mark.asyncio
async def test_export_markdown_includes_clean_sections_fields_and_headers(db_session, test_user):
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        records=[
            {
                "source_url": "https://example.com/item-1",
                "data": {
                    "title": "Sylan 2 Shoe Men's",
                    "description": "Built for speed.\n- Stable ride\n- Fast toe-off",
                    "price": "$180",
                },
                "raw_data": {},
                "discovered_data": {},
                "source_trace": {
                    "semantic": {
                        "sections": {"materials_and_care": "Spot clean only."},
                        "specifications": {"weight": "310 g", "drop": "6 mm"},
                    }
                },
            }
        ],
    )

    response = await export_markdown(run.id, session=db_session, current_user=test_user)
    payload = await _read_streaming_body(response)

    assert "# Sylan 2 Shoe Men's" in payload
    assert "Source: <https://example.com/item-1>" in payload
    assert "## Description" in payload
    assert "- Stable ride" in payload
    assert "## Materials and care" in payload
    assert "## Core Fields" in payload
    assert "- **Price:** $180" in payload
    assert "## Specifications" in payload
    assert "- **Weight:** 310 g" in payload
    _assert_export_headers(response, total_records=1, pages_used=1)


@pytest.mark.asyncio
async def test_export_csv_discovers_fields_beyond_first_page(db_session, test_user):
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        records=[
            {
                "source_url": f"https://example.com/{idx}",
                "data": {
                    "title": f"Item {idx}",
                    **({"rare_field": "late value"} if idx == MAX_RECORD_PAGE_SIZE else {}),
                },
            }
            for idx in range(MAX_RECORD_PAGE_SIZE + 1)
        ],
    )

    response = await export_csv(run.id, session=db_session, current_user=test_user)
    payload = await _read_streaming_body(response)
    header = payload.splitlines()[0]

    assert "rare_field" in header


@pytest.mark.asyncio
async def test_export_csv_does_not_fall_back_to_typed_table_rows(db_session, test_user):
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        run_kwargs={"url": "https://example.com/specs", "surface": "tabular"},
        records=[
            {
                "source_url": "https://example.com/specs",
                "data": {"page_markdown": "# Specs"},
                "source_trace": {
                    "manifest_trace": {
                        "tables": [
                            {
                                "table_index": 1,
                                "caption": "Specifications",
                                "headers": [{"text": "Name"}, {"text": "Value"}],
                                "rows": [
                                    {"row_index": 1, "cells": [{"text": "Voltage"}, {"text": "220V"}]}
                                ],
                            }
                        ]
                    }
                },
            }
        ],
    )

    response = await export_csv(run.id, session=db_session, current_user=test_user)
    payload = await _read_streaming_body(response)

    assert payload == ""


@pytest.mark.asyncio
async def test_export_tables_csv_returns_flattened_rows(db_session, test_user):
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        run_kwargs={"url": "https://example.com/specs", "surface": "tabular"},
        records=[
            {
                "source_url": "https://example.com/specs",
                "source_trace": {
                    "manifest_trace": {
                        "tables": [
                            {
                                "table_index": 2,
                                "section_title": "Specs",
                                "headers": [{"text": "Field"}, {"text": "Reading"}],
                                "rows": [
                                    {"row_index": 3, "cells": [{"text": "Current"}, {"text": "5A"}]}
                                ],
                            }
                        ]
                    }
                },
            }
        ],
    )

    response = await export_tables_csv(run.id, session=db_session, current_user=test_user)
    payload = await _read_streaming_body(response)

    assert "Current" in payload
    assert "5A" in payload


@pytest.mark.asyncio
async def test_export_artifacts_json_includes_typed_bundles(db_session, test_user):
    run, _ = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        run_kwargs={"url": "https://example.com/item"},
        records=[
            {
                "source_url": "https://example.com/item",
                "data": {"title": "Widget", "page_markdown": "# Widget"},
                "source_trace": {
                    "type": "detail",
                    "manifest_trace": {
                        "json_ld": [{"name": "Widget"}],
                        "tables": [],
                    },
                },
            }
        ],
    )

    response = await export_artifacts_json(run.id, session=db_session, current_user=test_user)
    payload = json.loads(await _read_streaming_body(response))

    assert payload[0]["structured_record"]["title"] == "Widget"
    assert payload[0]["evidence_refs"]["json_ld_count"] == 1

@pytest.mark.asyncio
async def test_record_provenance_returns_manifest_trace(db_session, test_user):
    _run, records = await _seed_export_run(
        db_session,
        user_id=test_user.id,
        records=[
            {
                "source_url": "https://example.com/item",
                "data": {"title": "Item"},
                "source_trace": {
                    "type": "detail",
                    "manifest_trace": {"json_ld": [{"name": "Item"}]},
                },
            }
        ],
    )
    record = records[0]

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

    _run, records = await _seed_export_run(
        db_session,
        user_id=owner.id,
        records=[
            {
                "source_url": "https://example.com/item",
                "data": {"title": "Item"},
            }
        ],
    )
    record = records[0]

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
