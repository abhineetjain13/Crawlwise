from __future__ import annotations

from app.services.extract.variant_record_normalization import normalize_variant_record
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
    assert normalize_decimal_price("Rs. 499") == "499"
    assert normalize_decimal_price("INR 499") == "499"


def test_normalize_decimal_price_accepts_price_keyword_context_for_integer_text() -> None:
    assert normalize_decimal_price("price 126") == "126"


def test_normalize_decimal_price_preserves_decimal_strings_without_currency_symbol() -> None:
    assert normalize_decimal_price("59.99") == "59.99"


def test_normalize_decimal_price_supports_suffix_currency_and_decimal_comma() -> None:
    assert normalize_decimal_price("62,99 €") == "62.99"


def test_normalize_value_price_preserves_semantic_integer_price_fields() -> None:
    assert normalize_value("price", "126") == "126"


def test_normalize_value_price_normalizes_clean_decimal_strings() -> None:
    assert normalize_value("price", "0012.50") == "12.50"


def test_normalize_value_unwraps_singleton_barcode_list_and_rounds_rating() -> None:
    assert normalize_value("barcode", "['0840424803104']") == "0840424803104"
    assert normalize_value("rating", "2.399113082039911") == "2.4"


def test_normalize_variant_record_preserves_referenced_single_value_axes() -> None:
    record = {
        "variant_axes": {"size": ["Small", "Large"], "scent": ["Lavender"]},
        "variants": [
            {"option_values": {"size": "Small", "scent": "Lavender"}, "sku": "LAV-S"},
            {"option_values": {"size": "Large", "scent": "Lavender"}, "sku": "LAV-L"},
        ],
    }

    normalize_variant_record(record)

    assert record["variant_axes"] == {
        "size": ["Small", "Large"],
        "scent": ["Lavender"],
    }
    assert all("scent" in variant["option_values"] for variant in record["variants"])


def test_normalize_variant_record_prunes_global_axes_and_collapses_permutations() -> None:
    variants = []
    for size in ("8 US", "9 US"):
        for site in ("Kith.com", "Kith.eu"):
            for currency in ("AL / L", "AD / EUR"):
                variants.append(
                    {
                        "price": "282",
                        "currency": "USD",
                        "option_values": {
                            "size": size,
                            "select_site": site,
                            "select_currency": currency,
                        },
                    }
                )
    record = {
        "variant_axes": {
            "size": ["8 US", "9 US"],
            "select_site": ["Kith.com", "Kith.eu"],
            "select_currency": ["AL / L", "AD / EUR"],
        },
        "variants": variants,
    }

    normalize_variant_record(record)

    assert record["variant_axes"] == {"size": ["8 US", "9 US"]}
    assert record["variant_count"] == 2
    assert [
        variant["option_values"] for variant in record["variants"]
    ] == [{"size": "8 US"}, {"size": "9 US"}]


def test_normalize_variant_record_strips_currently_unavailable_suffixes() -> None:
    record = {
        "variant_axes": {"size": ["12.5 is currently unavailable.", "13"]},
        "variants": [
            {
                "size": "12.5 is currently unavailable.",
                "availability": "out_of_stock",
                "option_values": {"size": "12.5 is currently unavailable."},
            },
            {
                "size": "13",
                "option_values": {"size": "13"},
            },
        ],
    }

    normalize_variant_record(record)

    assert record["variant_axes"] == {"size": ["12.5", "13"]}
    assert record["variants"][0]["size"] == "12.5"
    assert record["variants"][0]["option_values"] == {"size": "12.5"}


def test_normalize_variant_record_preserves_identity_less_selected_variant() -> None:
    record = {
        "selected_variant": {
            "title": "Selected from adapter",
            "option_values": {"size": "Large"},
        },
        "variants": [
            {"sku": "sku-1", "option_values": {"size": "Large"}},
            {"sku": "sku-2", "option_values": {"size": "XL"}},
        ],
    }

    normalize_variant_record(record)

    assert record["selected_variant"]["title"] == "Selected from adapter"
    assert record["selected_variant"]["option_values"] == {"size": "Large"}
