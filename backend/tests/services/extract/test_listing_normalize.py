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


def test_normalize_listing_record_keeps_detail_like_html_product_urls() -> None:
    normalized = normalize_listing_record(
        {
            "title": "Mini Hobo Bag Studs in Black, Black",
            "url": "https://www.ganni.com/en-gb/mini-hobo-bag-studs-in-black-B2070100.html",
            "price": 530,
            "image_url": "https://cdn.example.com/model.jpg",
        },
        surface="ecommerce_listing",
        page_url="https://www.ganni.com/en-gb/bags/",
        target_fields=set(),
    )

    assert normalized["url"] == "https://www.ganni.com/en-gb/mini-hobo-bag-studs-in-black-B2070100.html"


def test_normalize_listing_record_strips_tracking_query_params_from_product_urls() -> None:
    normalized = normalize_listing_record(
        {
            "title": "Men's Dasher NZ",
            "url": (
                "https://www.allbirds.com/products/mens-dasher-nz-anthracite"
                "?a_ajs_event=Product+Clicked&utm_source=test&keep=1"
            ),
            "image_url": "https://cdn.example.com/dasher.png",
        },
        surface="ecommerce_listing",
        page_url="https://www.allbirds.com/collections/mens",
        target_fields=set(),
    )

    assert (
        normalized["url"]
        == "https://www.allbirds.com/products/mens-dasher-nz-anthracite?keep=1"
    )

