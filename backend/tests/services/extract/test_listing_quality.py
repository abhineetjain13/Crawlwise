from __future__ import annotations

from app.services.extract.listing_quality import (
    assess_listing_record_quality,
)
from app.services.config.extraction_rules import LISTING_WEAK_TITLES


def test_assess_listing_record_quality_records_weak_title_reason():
    weak_title = next(iter(LISTING_WEAK_TITLES), "sale")

    assessment = assess_listing_record_quality(
        {
            "title": weak_title,
            "url": "https://example.com/products/widget",
            "price": "$19.99",
        },
        surface="ecommerce_listing",
    )

    assert "weak_title" in assessment.reasons
    assert "merchandising_noise" not in assessment.reasons
