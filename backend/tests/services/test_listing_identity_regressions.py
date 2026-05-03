"""Regression tests for listing URL / merchandise-hint fixes applied 2026-05-03.

These guard two real failures observed in the DB crawl history:
- Tire Rack category pages (run #8 and #10) yielded `listing_detection_failed`
  because every 2-segment product URL was rejected by `listing_url_is_structural`.
- Dell listing (run #19) persisted 33 navigation/landing anchors as products
  because `_unsupported_non_detail_ecommerce_merchandise_hint` accepted paths
  like `/en-us/lp/dt/energy-efficient-data-center`.
"""
from __future__ import annotations

from app.services.extract.detail_identity import listing_url_is_structural
from app.services.extract.listing_candidate_ranking import (
    _unsupported_non_detail_ecommerce_merchandise_hint,
)


def test_tirerack_product_url_is_not_structural() -> None:
    """Product URLs like `/accessories/<product-slug>` must survive the filter."""
    page = "https://www.tirerack.com/accessories/category.jsp?category=Batteries"
    product = "https://www.tirerack.com/accessories/ctek-nxt-5-battery-charger-maintainer"
    assert listing_url_is_structural(product, page) is False


def test_tirerack_category_root_url_still_structural() -> None:
    """The `/accessories/` root itself must still be treated as structural."""
    page = "https://www.tirerack.com/accessories/category.jsp?category=Batteries"
    root = "https://www.tirerack.com/accessories/"
    assert listing_url_is_structural(root, page) is True


def test_product_slug_in_utility_prefix_path_is_not_structural() -> None:
    """Long product slugs should override a structural leading segment."""
    assert (
        listing_url_is_structural(
            "https://shop.example.com/shop/nike-air-force-1-low-retro-white",
            "https://shop.example.com/shop/",
        )
        is False
    )


def test_dell_landing_page_not_rescued_as_merchandise() -> None:
    """`/en-us/lp/dt/<slug>` is a Dell landing page, not a product."""
    assert (
        _unsupported_non_detail_ecommerce_merchandise_hint(
            title="Sustainable Data Center",
            url="https://www.dell.com/en-us/lp/dt/energy-efficient-data-center",
        )
        is False
    )


def test_dell_industry_landing_page_not_rescued_as_merchandise() -> None:
    assert (
        _unsupported_non_detail_ecommerce_merchandise_hint(
            title="State & Local Government",
            url="https://www.dell.com/en-us/lp/dt/industry-state-and-local-government",
        )
        is False
    )


def test_short_slug_product_can_still_be_rescued() -> None:
    """The existing 2-token rescue path for `/browse/widget-prime` is preserved."""
    assert (
        _unsupported_non_detail_ecommerce_merchandise_hint(
            title="Widget Prime Ultra",
            url="https://example.com/browse/widget-prime",
        )
        is True
    )


def test_year_led_slug_is_not_product_slug() -> None:
    """`/public-relations/2025-ceo-letter/` must remain structural."""
    assert (
        listing_url_is_structural(
            "https://example.com/public-relations/2025-ceo-letter/",
            "https://example.com/",
        )
        is True
    )


def test_looks_like_utility_url_exempts_product_slug_under_utility_segment() -> None:
    """Tire Rack mounts products under /accessories/; must not be utility."""
    from app.services.extract.listing_candidate_ranking import looks_like_utility_url

    assert (
        looks_like_utility_url(
            "https://www.tirerack.com/accessories/ctek-nxt-5-battery-charger-maintainer"
        )
        is False
    )


def test_looks_like_utility_url_still_rejects_bare_utility_segment() -> None:
    from app.services.extract.listing_candidate_ranking import looks_like_utility_url

    assert looks_like_utility_url("https://example.com/accessories/") is True
    assert looks_like_utility_url("https://example.com/help/faq") is True


def test_dell_spd_product_url_is_not_utility() -> None:
    from app.services.extract.listing_candidate_ranking import looks_like_utility_url

    assert (
        looks_like_utility_url(
            "https://www.dell.com/en-us/shop/dell-laptops/new-xps-16-laptop/spd/xps-da16260-laptop/useda16260wcto01"
        )
        is False
    )


def test_dell_financing_url_is_utility() -> None:
    from app.services.extract.listing_candidate_ranking import looks_like_utility_record

    assert (
        looks_like_utility_record(
            title="Learn More about financing offers",
            url="https://www.dell.com/financing/comm/mfe/us/en/learn-more",
        )
        is True
    )


def test_shop_path_is_not_detail_marker() -> None:
    """Category/listing pages mounted under /shop/... must not be treated as detail.
    Regression for Dell (/en-us/shop/computer-monitors/ar/...) and Ulta
    (/shop/makeup/makeup-palettes) which both use /shop/ for listings.
    """
    from app.services.extract.detail_identity import listing_detail_like_path

    assert (
        listing_detail_like_path(
            "https://www.dell.com/en-us/shop/computer-monitors/ar/8605/ultrawide",
            is_job=False,
        )
        is False
    )
    assert (
        listing_detail_like_path(
            "https://www.ulta.com/shop/makeup/makeup-palettes",
            is_job=False,
        )
        is False
    )


def test_explicit_detail_markers_still_recognized() -> None:
    """/p/, /product/, /dp/, /spd/ equivalents remain detail markers."""
    from app.services.extract.detail_identity import listing_detail_like_path

    for url in (
        "https://example.com/products/foo",
        "https://example.com/p/abc-123",
        "https://example.com/dp/XYZ",
        "https://example.com/shop/laptops/spd/xps-da16260-laptop/useda16260wcto01",
        "https://example.com/detail/item-42",
    ):
        assert listing_detail_like_path(url, is_job=False) is True, url
