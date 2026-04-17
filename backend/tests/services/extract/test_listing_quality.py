from __future__ import annotations

from app.services.extract.listing_quality import (
    assess_listing_record_quality,
    looks_like_editorial_or_taxonomy_title,
    looks_like_transactional_url_for_listing,
)
from app.services.config.extraction_rules import LISTING_WEAK_TITLES


def test_assess_listing_record_quality_rejects_merchandising_weak_titles():
    weak_title = next(iter(LISTING_WEAK_TITLES), "sale")

    assessment = assess_listing_record_quality(
        {
            "title": weak_title,
            "url": "https://example.com/products/widget",
            "price": "$19.99",
        },
        surface="ecommerce_listing",
    )

    assert "merchandising_noise" in assessment.reasons


def test_looks_like_editorial_or_taxonomy_title_rejects_empty_title():
    assert looks_like_editorial_or_taxonomy_title("") is False


def test_assess_listing_record_quality_rejects_transactional_cart_urls():
    assessment = assess_listing_record_quality(
        {
            "title": "Ultra Omega 3 Fish Oil",
            "url": "https://www.vitacost.com/CheckOut/CartUpdate.aspx?SKUNumber=733739070746&action=add",
            "price": "$24.99",
        },
        surface="ecommerce_listing",
    )

    assert assessment.quality == "invalid"
    assert assessment.reasons == ("transactional_url",)


def test_looks_like_transactional_url_for_listing_detects_add_to_cart_endpoints():
    assert looks_like_transactional_url_for_listing(
        "https://www.vitacost.com/CheckOut/CartUpdate.aspx?SKUNumber=733739070746&action=add"
    )


def test_looks_like_transactional_url_for_listing_allows_detail_like_bag_product_paths():
    assert not looks_like_transactional_url_for_listing(
        "https://www.ganni.com/en-gb/mini-hobo-bag-studs-in-black-B2070100.html"
    )
