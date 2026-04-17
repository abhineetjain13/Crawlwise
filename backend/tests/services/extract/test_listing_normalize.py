from __future__ import annotations

from app.services.normalizers import canonical_listing_fields, normalize_listing_record


def test_canonical_listing_fields_handles_job_surface_prefix() -> None:
    fields = canonical_listing_fields("job_listing", set())
    assert "company" in fields
    assert "salary" in fields
    assert "job_id" in fields


def test_canonical_listing_fields_handles_non_job_surface() -> None:
    fields = canonical_listing_fields("ecommerce_listing", {"custom_field"})
    assert "price" in fields
    assert "image_url" in fields
    assert "custom_field" in fields


def test_normalize_listing_record_interprets_shopify_integer_money_under_normalize_owner() -> None:
    normalized = normalize_listing_record(
        {
            "title": "Widget",
            "price": "12999",
            "original_price": "15999",
            "_source": "next_data",
            "_raw_item": {
                "handle": "widget",
                "compare_at_price": "15999",
                "variants": [{"price": "12999"}],
            },
        },
        surface="ecommerce_listing",
        page_url="https://shop.example.com/products/widget",
        target_fields=set(),
    )

    assert normalized["price"] == "129.99"
    assert normalized["original_price"] == "159.99"

