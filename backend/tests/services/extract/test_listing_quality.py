from __future__ import annotations

from app.services.extract.listing_quality import (
    assess_listing_record_quality,
    looks_like_editorial_or_taxonomy_title,
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
