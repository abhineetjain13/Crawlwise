# Tests for crawl response schemas.
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.crawl import CrawlRecordResponse
from app.services.pipeline.field_normalization import (
    _normalize_record_fields,
    _sanitize_persisted_record_payload,
    _surface_public_record_fields,
    _surface_raw_record_payload,
)


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


def test_sanitize_persisted_record_payload_preserves_discovered_payload_values():
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
        "support_email": "support@example.com",
        "notes": "Call +91 98765 43210 or email sales@example.com",
    }
    assert discovered["review_bucket"] == [
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
    ]


def test_normalize_record_fields_preserves_canonical_payload_values():
    normalized = _normalize_record_fields(
        {
            "title": "Call sales@example.com",
            "description": "Reach us at (415) 555-2671 ext 9 for details.",
            "specs": {
                "support": "support@example.com",
                "phone": "+91 98765 43210",
            },
        }
    )

    assert normalized == {
        "title": "Call sales@example.com",
        "description": "Reach us at (415) 555-2671 ext 9 for details.",
        "specs": {
            "support": "support@example.com",
            "phone": "+91 98765 43210",
        },
    }


def test_surface_record_filters_drop_cross_surface_listing_fields_at_boundary():
    record = {
        "title": "Platform Engineer",
        "salary": "$120k",
        "price": "$9.99",
        "sku": "SKU-1",
        "_source": "listing_card",
        "_raw_item": {
            "title": "Platform Engineer",
            "salary": "$120k",
            "price": "$9.99",
            "sku": "SKU-1",
        },
    }

    assert _surface_public_record_fields(record, surface="job_listing") == {
        "title": "Platform Engineer",
        "salary": "$120k",
    }
    assert _surface_raw_record_payload(record, surface="job_listing") == {
        "title": "Platform Engineer",
        "salary": "$120k",
    }
