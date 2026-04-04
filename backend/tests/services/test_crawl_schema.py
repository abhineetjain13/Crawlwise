# Tests for crawl response schemas.
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import CrawlRecordResponse


def test_crawl_record_response_preserves_source_trace_candidates_while_stripping_manifest_noise():
    payload = CrawlRecordResponse.model_validate({
        "id": 1,
        "run_id": 7,
        "source_url": "https://example.com/product",
        "data": {"title": "Example Product", "_raw_item": {"ignore": True}, "empty": ""},
        "raw_data": {},
        "discovered_data": {
            "json_ld": [{"title": "Example Product"}],
            "semantic": {"sections": {"details": "Kept"}},
            "requested_field_coverage": {"requested": 1, "found": 1, "missing": []},
        },
        "source_trace": {
            "candidates": {
                "title": [
                    {"value": "Example Product", "source": "json_ld"},
                    {"value": "Backup Product", "source": "dom"},
                ],
            },
        },
        "raw_html_path": None,
        "created_at": datetime.now(UTC),
    })

    assert payload.data == {"title": "Example Product"}
    assert "json_ld" not in payload.discovered_data
    assert payload.discovered_data["semantic"] == {"sections": {"details": "Kept"}}
    assert payload.source_trace["candidates"]["title"][0]["value"] == "Example Product"
    assert payload.source_trace["candidates"]["title"][1]["value"] == "Backup Product"
