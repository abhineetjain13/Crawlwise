from __future__ import annotations

from app.services.normalizers import normalize_decimal_price, normalize_value


def test_normalize_additional_images_preserves_url_lists_with_commas() -> None:
    value = normalize_value(
        "additional_images",
        [
            "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
            "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
        ],
    )

    assert value == [
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
    ]


def test_normalize_decimal_price_rejects_ambiguous_integer_text_without_price_context() -> None:
    assert normalize_decimal_price("126") is None


def test_normalize_decimal_price_accepts_currency_context_for_integer_text() -> None:
    assert normalize_decimal_price("$126") == "126"


def test_normalize_decimal_price_accepts_price_keyword_context_for_integer_text() -> None:
    assert normalize_decimal_price("price 126") == "126"


def test_normalize_decimal_price_preserves_decimal_strings_without_currency_symbol() -> None:
    assert normalize_decimal_price("59.99") == "59.99"


def test_normalize_decimal_price_supports_suffix_currency_and_decimal_comma() -> None:
    assert normalize_decimal_price("62,99 €") == "62.99"
