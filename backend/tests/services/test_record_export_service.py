from __future__ import annotations

import json

import pytest
from app.models.crawl import CrawlRecord
from app.services.record_export_service import (
    _artifact_table_rows,
    _clean_export_data,
    _legacy_fallback_markdown_rows,
    _record_to_markdown,
    stream_export_json,
)


def test_clean_export_data_preserves_duplicate_alias_fields() -> None:
    cleaned = _clean_export_data(
        {
            "price": "50",
            "50_price": "50",
            "title": "HeatGear Elite",
            "product_title": "HeatGear Elite",
            "_private": "ignore",
        }
    )

    assert cleaned == {
        "price": "50",
        "50_price": "50",
        "title": "HeatGear Elite",
        "product_title": "HeatGear Elite",
    }


def test_artifact_table_rows_flattens_manifest_tables() -> None:
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
                        "rows": [
                            {"row_index": 1, "cells": [{"text": "Weight"}, {"text": "10kg"}]}
                        ],
                    }
                ]
            }
        },
        raw_html_path=None,
    )

    flattened = _artifact_table_rows(row)

    assert flattened[0]["Key"] == "Weight"
    assert flattened[0]["Value"] == "10kg"


def test_record_to_markdown_does_not_repeat_source_url_in_fields() -> None:
    row = CrawlRecord(
        id=1,
        source_url="https://example.com/jobs",
        data={
            "title": "Medical Assistant",
            "source_url": "https://example.com/jobs",
            "url": "https://example.com/jobs#9202644178148_1",
            "job_id": "9202644178148_1",
        },
        source_trace={},
    )

    markdown = _record_to_markdown(row)

    assert "Source: <https://example.com/jobs>" in markdown
    assert "Record URL: <https://example.com/jobs#9202644178148_1>" in markdown
    assert "- **Source url:**" not in markdown


def test_legacy_fallback_markdown_rows_extracts_structured_rows() -> None:
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
async def test_stream_export_json_tolerates_non_dict_row_data(monkeypatch) -> None:
    row = CrawlRecord(id=9, run_id=1, source_url="https://example.com/item", data=None)

    async def _fake_stream(_session, _run_id):
        yield row

    monkeypatch.setattr(
        "app.services.record_export_service._stream_export_rows",
        _fake_stream,
    )

    chunks = []
    async for chunk in stream_export_json(object(), 1):
        chunks.append(chunk)

    assert json.loads("".join(chunks)) == [{}]
