# Tests for crawl response schemas.
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import CrawlRecordResponse
from app.services.pipeline.field_normalization import _sanitize_persisted_record_payload


def test_crawl_record_response_exposes_review_bucket_and_hides_manifest_trace():
    payload = CrawlRecordResponse.model_validate({
        "id": 1,
        "run_id": 7,
        "source_url": "https://example.com/product",
        "data": {"title": "Example Product", "_raw_item": {"ignore": True}, "empty": ""},
        "raw_data": {},
        "discovered_data": {
            "review_bucket": [
                {
                    "key": "wire_gauge",
                    "value": "26 AWG",
                    "source": "semantic_spec",
                }
            ],
            "requested_field_coverage": {"requested": 1, "found": 1, "missing": []},
        },
        "source_trace": {
            "manifest_trace": {
                "json_ld": [{"title": "Example Product"}],
            },
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
    assert payload.review_bucket[0].key == "wire_gauge"
    assert payload.provenance_available is True
    assert "manifest_trace" not in payload.source_trace
    assert payload.source_trace["candidates"]["title"][0]["value"] == "Example Product"
    assert payload.source_trace["candidates"]["title"][1]["value"] == "Backup Product"


def test_crawl_record_response_dedupes_review_bucket_case_only_variants():
    payload = CrawlRecordResponse.model_validate({
        "id": 1,
        "run_id": 7,
        "source_url": "https://example.com/product",
        "data": {"title": "Example Product"},
        "raw_data": {},
        "discovered_data": {
            "review_bucket": [
                {"key": "brand_family", "value": "Supelco", "source": "next_data"},
                {"key": "brand_family", "value": "SUPELCO", "source": "json_ld"},
            ],
        },
        "source_trace": {},
        "raw_html_path": None,
        "created_at": datetime.now(UTC),
    })

    assert len(payload.review_bucket) == 1
    assert payload.review_bucket[0].value == "Supelco"


def test_sanitize_persisted_record_payload_strips_raw_item_and_schema_keys():
    data, discovered = _sanitize_persisted_record_payload(
        {
            "title": "Example Product",
            "_raw_item": {"token": "secret"},
            "_source": "next_data",
        },
        discovered_data={
            "review_bucket": [{"key": "brand", "value": "Acme", "source": "json_ld"}],
            "_raw_item": {"token": "secret"},
            "__typename": "ProductCard",
            "@context": "https://schema.org",
        },
    )

    assert "_raw_item" not in data
    assert "_source" not in data
    assert discovered == {
        "review_bucket": [{"key": "brand", "value": "Acme", "source": "json_ld"}]
    }


def test_sanitize_persisted_record_payload_redacts_pii_from_discovered_payloads():
    _, discovered = _sanitize_persisted_record_payload(
        {"title": "Example Product"},
        discovered_data={
            "discovered_fields": {
                "support_email": "support@example.com",
                "notes": "Call +91 98765 43210 or email sales@example.com",
            },
            "review_bucket": [
                {
                    "key": "contact_email",
                    "value": "sales@example.com",
                    "source": "llm_cleanup",
                },
                {
                    "key": "contact_notes",
                    "value": "Reach us on (415) 555-2671 ext 9",
                    "source": "regex",
                },
            ],
        },
    )

    assert discovered["discovered_fields"] == {
        "support_email": "[REDACTED]",
        "notes": "Call [REDACTED] or email [REDACTED]",
    }
    assert discovered["review_bucket"] == [
        {
            "key": "contact_email",
            "value": "[REDACTED]",
            "source": "llm_cleanup",
        },
        {
            "key": "contact_notes",
            "value": "Reach us on [REDACTED]",
            "source": "regex",
        },
    ]
