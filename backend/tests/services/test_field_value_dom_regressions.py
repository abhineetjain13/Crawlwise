"""Regression tests for output-quality fixes applied 2026-05-03."""
from __future__ import annotations

import html

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.services.field_value_core import coerce_field_value
from app.services.field_value_dom import _is_garbage_image_candidate, extract_feature_rows


def _img(src: str) -> Tag | None:
    soup = BeautifulSoup(
        f"<main class='pdp product-gallery'><picture><img src='{html.escape(src)}'></picture></main>",
        "html.parser",
    )
    return soup.find("img")


def test_unresolved_template_image_url_is_garbage() -> None:
    node = _img("https://cdn.example.com/shop/p/foo/URL_TO_THE_PRODUCT_IMAGE")
    assert _is_garbage_image_candidate(node, node.get("src")) is True


def test_handlebars_template_image_url_is_garbage() -> None:
    node = _img("https://cdn.example.com/{{image}}.jpg")
    assert _is_garbage_image_candidate(node, node.get("src")) is True


def test_bracket_placeholder_image_url_is_garbage() -> None:
    node = _img("https://cdn.example.com/[[image]]/hero.jpg")
    assert _is_garbage_image_candidate(node, node.get("src")) is True


def test_resolved_image_url_is_not_garbage() -> None:
    node = _img("https://cdn.example.com/product/hero-image.jpg")
    # Not garbage on its own (URL has no template tokens).
    assert _is_garbage_image_candidate(node, node.get("src")) is False


def test_dash_separated_feature_text_splits_into_rows() -> None:
    soup = BeautifulSoup(
        """
        <main class="pdp">
          <section class="product-features">
            - Precision Pour Spout - To-the-degree temperature control - Quick Heat Time
          </section>
        </main>
        """,
        "html.parser",
    )

    assert extract_feature_rows(soup) == [
        "Precision Pour Spout",
        "To-the-degree temperature control",
        "Quick Heat Time",
    ]


def test_dict_value_is_rejected_for_description_field() -> None:
    """Regression: Sony headphones `description` leaked a Python dict repr."""
    assert (
        coerce_field_value(
            "description",
            {"useOnlyPreMadeBundles": False},
            "https://example.com/product/123",
        )
        is None
    )


def test_dict_value_is_rejected_for_specifications_field() -> None:
    assert (
        coerce_field_value(
            "specifications",
            {"internal": True, "flag": "x"},
            "https://example.com/product/123",
        )
        is None
    )
