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


def test_normalize_decimal_price_rejects_negative_values() -> None:
    # Regression: gemini audit DQ-4 — Gucci/Sony emitted -1 / -9 default
    # fallbacks that leaked into exports. Negative prices must become None.
    assert normalize_decimal_price("-1") is None
    assert normalize_decimal_price("-9.99") is None
    assert normalize_decimal_price("$-1") is None
    assert normalize_decimal_price("-$1") is None
    assert normalize_decimal_price("-USD100") is None


def test_repair_ecommerce_detail_reconciles_parent_price_against_unanimous_variants() -> None:
    # Regression: gemini audit DQ-7 (Selfridges) — parent price 190 with both
    # variants reporting 310 is a stale/unrelated DOM scrape. The reconciler
    # should adopt the unanimous variant price as the parent.
    record: dict[str, object] = {
        "price": "190.00",
        "currency": "GBP",
        "variants": [
            {"price": "310.00", "currency": "GBP", "size": "50ml"},
            {"price": "310.00", "currency": "GBP", "size": "100ml"},
        ],
    }
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://www.selfridges.com/GB/en/cat/example/",
        requested_page_url="https://www.selfridges.com/GB/en/cat/example/",
    )
    assert record["price"] == "310.00"


def test_repair_ecommerce_detail_skips_variant_range_reconcile_when_magnitudes_differ() -> None:
    # Guard: when parent and variant prices differ by >~2x, the mismatch is
    # more likely a cents/units magnitude issue handled by the dedicated
    # magnitude reconciler. The variant-range reconciler must not overwrite
    # the parent in that case.
    record: dict[str, object] = {
        "price": "282.00",
        "currency": "USD",
        "variants": [
            {"price": "28200", "currency": "USD"},
        ],
    }
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://example.com/p",
        requested_page_url="https://example.com/p",
    )
    assert record["price"] == "282.00"


def test_coerce_field_value_category_rejects_url_path_strings() -> None:
    # Regression: gemini audit DQ-8 — Vans exposed a joined URL path
    # ("https: > www.vans.com > en-us > c > shoes > icons > old-skool-5205")
    # as the category field. URL-looking strings must be rejected so the
    # breadcrumb fallback can provide a real category label.
    assert (
        coerce_field_value(
            "category",
            "https: > www.vans.com > en-us > c > shoes > icons > old-skool-5205",
            "",
        )
        is None
    )
    assert (
        coerce_field_value("category", "https://example.com/c/shoes", "")
        is None
    )
    # But a real breadcrumb path must still pass through.
    assert (
        coerce_field_value("category", "Shoes > Icons > Old Skool", "")
        == "Shoes > Icons > Old Skool"
    )


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
        == "Leather upper with perforated toe box; Rubber outsole"
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

    assert record["variants"] == [
        {"size": "Small", "scent": "Lavender", "sku": "LAV-S"},
        {"size": "Large", "scent": "Lavender", "sku": "LAV-L"},
    ]
    assert record["variant_count"] == 2


def test_normalize_variant_record_drops_axisless_rows_and_rejects_foreign_currency() -> None:
    record = {
        "currency": "GBP",
        "variants": [
            {"sku": "SKU-ONLY", "price": "10.00", "currency": "GBP"},
            {"color": "Black", "sku": "BLACK-1", "price": "10.00", "currency": "GBP"},
            {"size": "M", "sku": "RED-M", "price": "12.00", "currency": "EUR"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Black", "sku": "BLACK-1", "price": "10.00", "currency": "GBP"}
    ]
    assert record["variant_count"] == 1


def test_normalize_variant_record_drops_ui_control_variant_values() -> None:
    record = {
        "variants": [
            {"url": "javascript:void(0)", "size": "Your Cookie Settings"},
            {"size": "Show Reviews with 5 stars"},
            {"color": "Previous"},
            {"color": "Show image 1"},
            {"color": "Enable Keyboard Shortcuts:"},
            {"color": "Now & Every 15 Days"},
            {"size": "Shipping Restrictions : Sales and Export of this item"},
        ],
    }

    normalize_variant_record(record)

    assert "variants" not in record
    assert "variant_count" not in record


def test_normalize_variant_record_preserves_real_short_axes_after_ui_noise_prune() -> None:
    record = {
        "variants": [
            {"url": "https://example.com/products/shirt?variant=1", "size": "M"},
            {"url": "https://example.com/products/shirt?variant=2", "color": "Navy"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "M", "url": "https://example.com/products/shirt?variant=1"},
        {"color": "Navy", "url": "https://example.com/products/shirt?variant=2"},
    ]
    assert record["variant_count"] == 2


def test_normalize_variant_record_collapses_backmarket_carousel_compare_rows() -> None:
    record = {
        "variants": [
            {"color": "Previous", "storage": "128 GB", "condition": "Compare"},
            {"color": "Show image 1", "storage": "128 GB", "condition": "Compare"},
            {"color": "Next", "storage": "128 GB", "condition": "Compare"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"storage": "128 GB"}]
    assert record["variant_count"] == 1


def test_normalize_variant_record_promotes_color_values_misfiled_as_size() -> None:
    record = {
        "variants": [
            {"size": "Smoke Green (sold out)"},
            {"size": "Matte Black sold out"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Smoke Green"},
        {"color": "Matte Black"},
    ]
    assert record["variant_count"] == 2



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

    assert record["variant_count"] == 2


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

    assert record["variants"][0]["size"] == "12.5"


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

    assert record["variant_count"] == 3


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
    assert all("original_price" not in variant for variant in record["variants"])
