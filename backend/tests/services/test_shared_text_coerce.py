from __future__ import annotations

from app.services.shared.text_coerce import (
    clean_text,
    coerce_long_text,
    coerce_text,
    is_title_noise,
    slug_tokens,
    strip_html_tags,
    text_or_none,
)


def test_clean_text_normalizes_entities_whitespace_and_css_noise() -> None:
    assert clean_text("  A&nbsp;\n B  ") == "A B"
    assert clean_text(".x{display:none} Product") == "Product"


def test_strip_and_coerce_html_text() -> None:
    assert strip_html_tags("<p>Hello <b>world</b></p>") == "Hello world"
    assert coerce_text("<p>Hello&nbsp;world</p>") == "Hello world"
    assert coerce_long_text("<p>One</p><p>Two</p>") == "One Two"


def test_literal_text_lists_and_empty_values() -> None:
    assert coerce_text("['Small', 'Large']") == "Small; Large"
    assert text_or_none(" \n ") is None


def test_title_noise_and_slug_tokens() -> None:
    assert is_title_noise("undefined")
    assert is_title_noise("12345")
    assert not is_title_noise("Cotton Shirt")
    assert slug_tokens("Cotton-Shirt / Blue") == ["cotton", "shirt", "blue"]
