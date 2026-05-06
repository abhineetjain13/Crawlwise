"""Regression tests for the 2026-05-03 extraction quality audit.

Each test targets one audit finding that was verified as a real bug against
the current code (not just the audit text). Sources live in
``docs/audits/extraction_quality_audit_2026-05-03.md``.
"""
from __future__ import annotations

import pytest

from app.services.extract.detail_text_sanitizer import (
    sanitize_detail_features,
    sanitize_detail_long_text,
)


class TestBracketArtifactNoise:
    """Audit 1.1 — Vans Old Skool nested bracket pollution."""

    def test_bracket_artifact_is_stripped_and_prose_recovered(self) -> None:
        value = (
            "[ [ [ [[[Style ]][[ [[VN000E9TBPG]] ]][[]]] "
            "[The Old Skool was our first footwear design with the iconic side stripe]"
        )
        assert sanitize_detail_long_text(value, title="Vans Old Skool") == (
            "The Old Skool was our first footwear design with the iconic side stripe"
        )

    def test_legitimate_description_with_no_bracket_runs_is_untouched(self) -> None:
        value = "Crafted from premium leather with reinforced stitching."
        assert sanitize_detail_long_text(value, title="Premium Shoe") == value

    def test_double_bracket_only_artifacts_fall_back_to_stripped_text(self) -> None:
        # Fewer than 5 prose words per chunk => fallback to bracket-stripped form.
        value = "[[Style]] [[SKU-ABC]] [[Color]]"
        result = sanitize_detail_long_text(value, title="Something")
        # Falls back to bracket-stripped text; prose is short but brackets are gone.
        assert "[" not in result and "]" not in result


class TestShippingFulfillmentDisclaimers:
    """Audit 3.2 — Jordan 5 tracking/shipping boilerplate."""

    def test_tracking_status_sentence_is_rejected(self) -> None:
        value = (
            "Once the order is shipped you will be emailed a tracking number. "
            "If you notice the tracking status reads Label Created please allow "
            "48 hours for the carrier to update."
        )
        assert sanitize_detail_long_text(value, title="Air Jordan 5") == ""

    def test_legitimate_description_mentioning_tracking_in_other_context_survives(
        self,
    ) -> None:
        # "Tracking device" is a product feature, not a shipping-status blurb.
        # Our pattern requires "tracking status reads" or "order is shipped ... tracking"
        # co-occurrence, so this should pass through.
        value = "This smart watch ships with a built-in GPS tracking device."
        result = sanitize_detail_long_text(value, title="Smart Watch")
        assert result == value


class TestMarketingBannerAndSeoDescriptions:
    """Audit 3.3 / 3.4 — '47 promo banner and Anthropologie SEO blurb."""

    def test_region_banner_with_only_price_and_fast_shipping_is_rejected(self) -> None:
        value = "(US) - only $35. Fast shipping on latest 47 merchandise."
        result = sanitize_detail_long_text(value, title="NY Yankees Cap")
        # The marketing banner sentence must be stripped.
        assert "(US)" not in result
        assert "only $35" not in result

    def test_seo_meta_shop_the_x_at_brand_today_is_rejected(self) -> None:
        value = (
            "Shop the Boho Bangle Bracelets, Set of 3 and more at Anthropologie "
            "today. Read customer reviews, and discover more."
        )
        assert sanitize_detail_long_text(value, title="Boho Bangle Bracelets") == ""

    def test_legit_prose_starting_with_the_word_shop_is_not_rejected(self) -> None:
        # Pattern requires "shop the ... at <brand> today" co-occurrence.
        value = "Shop this timeless piece daily. Crafted from silver for durable wear."
        result = sanitize_detail_long_text(value, title="Silver Bracelet")
        assert "Crafted from silver" in result


@pytest.mark.parametrize(
    "value",
    [
        # Existing disclaimer tokens must still reject.
        "Buy now with free shipping on every order.",
        "We aim to show you accurate product information here.",
    ],
)
def test_existing_disclaimer_patterns_still_work(value: str) -> None:
    assert sanitize_detail_long_text(value, title="Generic") == ""


def test_sanitize_detail_features_drops_accordion_button_labels() -> None:
    value = [
        "Features",
        "AMD Ryzen 3 Processor",
        "See more Features",
        "Full HD display",
    ]

    assert sanitize_detail_features(value, title="HP Laptop 15") == [
        "AMD Ryzen 3 Processor",
        "Full HD display",
    ]
