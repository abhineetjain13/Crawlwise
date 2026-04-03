# Tests for field normalizers.
from __future__ import annotations

from app.services.normalizers.field_normalizers import normalize_value


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
