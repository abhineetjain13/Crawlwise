from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import serialize_crawl_record_response


def test_serialize_crawl_record_response_preserves_display_payload_shape() -> None:
    record = serialize_crawl_record_response(
        {
            "id": 1,
            "run_id": 2,
            "source_url": "https://example.com/jobs/1",
            "data": {
                "title": "Senior Engineer",
                "_debug": "hidden",
                "page_markdown": "hidden",
                "record_type": "job_detail",
                "description": "",
            },
            "raw_data": {"raw": True},
            "discovered_data": {
                "discovered_fields": {"skills": "Python"},
                "json_ld": {"title": "Senior Engineer"},
                "empty_field": "",
                "review_bucket": [],
            },
            "source_trace": {
                "manifest_trace": {"json_ld": {"title": "Senior Engineer"}},
                "adapter": "greenhouse",
                "empty": "",
            },
            "raw_html_path": None,
            "created_at": datetime.now(UTC),
        }
    )

    assert record.data == {"title": "Senior Engineer"}
    assert [item.model_dump() for item in record.review_bucket] == [
        {"key": "skills", "value": "Python", "source": "discovered_fields"}
    ]
    assert record.discovered_data == {}
    assert record.source_trace == {"adapter": "greenhouse"}
    assert record.provenance_available is True
