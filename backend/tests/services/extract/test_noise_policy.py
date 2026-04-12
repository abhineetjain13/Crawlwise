from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_WEAK_TITLES,
)
from app.services.extract.noise_policy import (
    is_inside_site_chrome,
    is_noise_title,
    is_noisy_product_attribute_entry,
    is_social_url,
    strip_ui_noise,
)


def test_strip_ui_noise_removes_generic_ui_copy() -> None:
    cleaned = strip_ui_noise("add_to_cart add to cart imageloader fallback-image")

    assert cleaned == ""


def test_is_noise_title_rejects_generic_navigation_copy() -> None:
    assert is_noise_title(
        "Contact us",
        navigation_hints=LISTING_NAVIGATION_TITLE_HINTS,
        merchandising_prefixes=LISTING_MERCHANDISING_TITLE_PREFIXES,
        editorial_patterns=LISTING_EDITORIAL_TITLE_PATTERNS,
        alt_text_pattern=LISTING_ALT_TEXT_TITLE_PATTERN,
        weak_titles=LISTING_WEAK_TITLES,
    )


def test_is_noisy_product_attribute_entry_rejects_footer_copy() -> None:
    assert is_noisy_product_attribute_entry(
        "shipping_policy",
        "Download our app and review our shipping policy.",
    )


def test_is_social_url_detects_social_hosts() -> None:
    assert is_social_url("https://www.instagram.com/example/")


def test_is_inside_site_chrome_detects_footer_ancestor() -> None:
    soup = BeautifulSoup(
        "<footer><section><h2>Contact</h2><p>Footer copy</p></section></footer>",
        "html.parser",
    )

    heading = soup.find("h2")

    assert is_inside_site_chrome(heading)
