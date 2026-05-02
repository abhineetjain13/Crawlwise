from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.detail_record_finalizer import (
    repair_ecommerce_detail_record_quality,
)
from app.services.extract.variant_record_normalization import normalize_variant_record
from app.services.field_value_core import coerce_field_value
from app.services.field_value_dom import extract_node_value
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
    assert normalize_value("rating", "2.399113082039911") == 2.4


def test_coerce_text_fields_join_literal_list_strings() -> None:
    assert (
        coerce_field_value(
            "product_details",
            "['Leather upper with perforated toe box', 'Rubber outsole']",
            "",
        )
        == "Leather upper with perforated toe box Rubber outsole"
    )


def test_normalize_availability_schema_url() -> None:
    assert (
        normalize_value("availability", "https://schema.org/LimitedAvailability")
        == "limited_stock"
    )


def test_field_coercion_repairs_source_quality_before_enrichment() -> None:
    assert coerce_field_value("brand", {"0": "Apple"}, "") == "Apple"
    assert (
        coerce_field_value("availability", "https://schema.org/LimitedAvailability", "")
        == "limited_stock"
    )
    assert coerce_field_value("rating", {"ratingValue": "4.5"}, "") == 4.5
    assert coerce_field_value("product_type", {"variationGroup": True}, "") is None


def test_variant_option_dom_text_drops_child_price_badges() -> None:
    soup = BeautifulSoup(
        """
        <button role="radio" class="color-option">
          <span>Black</span><span>$382.00</span>
        </button>
        """,
        "html.parser",
    )

    assert extract_node_value(soup.button, "color", "https://example.com") == "Black"


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
    assert [variant["option_values"] for variant in record["variants"]] == [
        {"size": "8 US"},
        {"size": "9 US"},
    ]


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


def test_normalize_variant_record_merges_semantic_duplicate_rows_and_size_aliases() -> None:
    record = {
        "variant_axes": {"size": ["3", "4", "8", "8 US"]},
        "variants": [
            {
                "sku": "13875993",
                "variant_id": "45140428423360",
                "size": "3",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "3"},
            },
            {
                "sku": "13875994",
                "variant_id": "45140428456128",
                "size": "4",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4"},
            },
            {
                "size": "3",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "3"},
            },
            {
                "size": "4",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "4"},
            },
            {
                "sku": "13876003",
                "variant_id": "45140428619904",
                "size": "8",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "8"},
            },
            {
                "size": "8 US",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "8 US"},
            },
        ],
        "selected_variant": {
            "size": "4",
            "price": "284.00",
            "currency": "USD",
            "availability": "in_stock",
            "option_values": {"size": "4"},
        },
    }

    normalize_variant_record(record)

    assert record["variant_axes"] == {"size": ["3", "4", "8"]}
    assert [variant["option_values"]["size"] for variant in record["variants"]] == [
        "3",
        "4",
        "8",
    ]
    assert record["variant_count"] == 3
    assert record["selected_variant"]["option_values"] == {"size": "4"}
    assert record["selected_variant"]["availability"] == "out_of_stock"


def test_detail_record_quality_repairs_invalid_original_prices_and_selected_variant_availability() -> None:
    record = {
        "sku": "M20324",
        "url": "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
        "size": "4",
        "price": "100.00",
        "currency": "USD",
        "availability": "out_of_stock",
        "original_price": "1.00",
        "title": "Stan Smith Shoes",
        "variants": [
            {
                "size": "4",
                "price": "100.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4"},
                "original_price": "1.00",
            },
            {
                "size": "4.5",
                "price": "100.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4.5"},
                "original_price": "1.00",
            },
        ],
        "selected_variant": {
            "sku": "M20324",
            "size": "4",
            "price": "100.00",
            "currency": "USD",
            "availability": "in_stock",
            "option_values": {"size": "4"},
            "original_price": "1.00",
        },
    }

    normalize_variant_record(record)
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    )

    assert record["original_price"] == "100.00"
    assert record["selected_variant"]["option_values"] == {"size": "4"}
    assert record["selected_variant"]["availability"] == "out_of_stock"
    assert record["selected_variant"]["original_price"] == "100.00"
    assert all(variant["original_price"] == "100.00" for variant in record["variants"])
