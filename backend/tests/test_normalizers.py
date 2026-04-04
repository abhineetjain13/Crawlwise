# Tests for field normalizers.
from __future__ import annotations

from app.services.normalizers.field_normalizers import extract_currency_hint, normalize_value


def test_normalize_price():
    assert normalize_value("price", "$19.99") == "19.99"
    assert normalize_value("price", "USD 1,299.00") == "1,299.00"
    assert normalize_value("price", "Free") == "Free"


def test_normalize_sale_price():
    assert normalize_value("sale_price", "$9.99") == "9.99"


def test_normalize_whitespace():
    assert normalize_value("title", "  Hello   World  ") == "Hello World"


def test_normalize_non_string():
    assert normalize_value("rating", 4.5) == 4.5
    assert normalize_value("review_count", 100) == 100
    assert normalize_value("tags", ["a", "b"]) == ["a", "b"]


def test_normalize_empty_string():
    assert normalize_value("title", "") == ""


def test_normalize_description_strips_html():
    assert normalize_value("description", "<p>Hello <strong>World</strong></p>") == "Hello World"


def test_normalize_availability_schema_url():
    assert normalize_value("availability", "https://schema.org/InStock") == "in_stock"


def test_normalize_placeholder_and_generic_noise_values():
    assert normalize_value("features", "-") == ""
    assert normalize_value("category", "detail-page") == ""
    assert normalize_value("title", "Chrome") == ""


def test_normalize_currency_uses_iso_code_whitelist():
    assert normalize_value("currency", "The color RED is popular") == "The color RED is popular"
    assert normalize_value("currency", "Price: 19.99 usd") == "USD"


def test_normalize_currency_prefers_code_adjacent_to_amount():
    assert normalize_value("currency", "CAD was mentioned, final price 12.50 USD today") == "USD"


def test_extract_currency_hint_prefers_adjacent_code_over_symbol():
    assert extract_currency_hint("100 CAD $") == "CAD"
