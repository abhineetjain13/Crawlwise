from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import CrawlRunResponse, serialize_crawl_record_response


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


def test_serialize_crawl_record_response_tolerates_non_dict_payloads() -> None:
    record = serialize_crawl_record_response(
        {
            "id": 1,
            "run_id": 2,
            "source_url": "https://example.com/products/1",
            "data": ["bad"],
            "raw_data": "bad",
            "discovered_data": None,
            "source_trace": 7,
            "raw_html_path": None,
            "created_at": datetime.now(UTC),
        }
    )

    assert record.data == {}
    assert record.raw_data == {}
    assert record.discovered_data == {}
    assert record.source_trace == {}


def test_crawl_run_response_sanitizes_nested_sensitive_settings() -> None:
    run = CrawlRunResponse(
        id=1,
        user_id=2,
        run_type="crawl",
        url="https://example.com",
        status="completed",
        surface="ecommerce_detail",
        settings={
            "api_key": "top-secret",
            "nested": {"token": "hidden", "keep": "visible"},
            "items": [{"secret": "hidden", "name": "kept"}],
        },
        requested_fields=[],
        result_summary={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert run.settings == {
        "nested": {"keep": "visible"},
        "items": [{"name": "kept"}],
    }
