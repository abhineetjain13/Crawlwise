from __future__ import annotations

from app.services.field_value_core import (
    strip_tracking_query_params,
    validate_and_clean,
    validate_record_for_surface,
)


def test_validate_and_clean_drops_fields_outside_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "price": "19.99",
            "internal_score": 0.91,
            "title": "Widget",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"price": "19.99"}
    assert errors == []


def test_validate_and_clean_nulls_schema_type_mismatches() -> None:
    cleaned, errors = validate_and_clean(
        {
            "price": {"amount": "19.99"},
            "variants": "not-a-list",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"price": None, "variants": None}
    assert len(errors) == 2


def test_validate_and_clean_applies_listing_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "title": ["Widget"],
            "url": "https://example.com/products/widget",
            "image_url": {"src": "https://cdn.example.com/widget.jpg"},
        },
        "ecommerce_listing",
    )

    assert cleaned == {
        "title": None,
        "url": "https://example.com/products/widget",
        "image_url": None,
    }
    assert len(errors) == 2


def test_validate_and_clean_applies_job_listing_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "title": "Platform Engineer",
            "company": {"name": "Acme"},
            "apply_url": "https://jobs.example.com/apply/123",
        },
        "job_listing",
    )

    assert cleaned == {
        "title": "Platform Engineer",
        "company": None,
        "apply_url": "https://jobs.example.com/apply/123",
    }
    assert len(errors) == 1


def test_validate_record_for_surface_drops_unknown_fields_but_keeps_canonical_fields() -> None:
    cleaned, errors = validate_record_for_surface(
        {
            "title": "Widget Prime",
            "price": {"amount": "19.99"},
            "random_garbage_key": "keep me out",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"title": "Widget Prime"}
    assert len(errors) == 1


def test_strip_tracking_query_params_removes_etsy_style_click_tracking_but_keeps_functional_values() -> None:
    cleaned = strip_tracking_query_params(
        "https://example.com/products/widget-prime"
        "?click_key=opaque"
        "&click_sum=12345"
        "&ls=r"
        "&external=1"
        "&sr_prefetch=0"
        "&pf_from=rlp"
        "&pro=1"
        "&frs=1"
        "&sts=1"
        "&content_source=opaque_source"
        "&variant=blue"
    )

    assert cleaned == "https://example.com/products/widget-prime?variant=blue"


def test_strip_tracking_query_params_keeps_short_flags_without_detail_context_tracking() -> None:
    cleaned = strip_tracking_query_params(
        "https://example.com/products/widget-prime"
        "?gclid=opaque"
        "&ls=r"
        "&variant=blue"
    )

    assert cleaned == "https://example.com/products/widget-prime?ls=r&variant=blue"
