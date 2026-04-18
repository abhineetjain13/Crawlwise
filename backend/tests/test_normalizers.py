# Tests for field normalizers.
from __future__ import annotations

from app.services.normalizers import (
    extract_currency_hint,
    normalize_and_validate_value,
    normalize_decimal_price,
    normalize_value,
    validate_value,
)


def test_normalize_price():
    assert normalize_value("price", "$19.99") == "19.99"
    assert normalize_value("price", "USD 1,299.00") == "1,299.00"
    assert normalize_value("price", "Free") == "Free"


def test_normalize_sale_price():
    assert normalize_value("sale_price", "$9.99") == "9.99"


def test_normalize_decimal_price_supports_cents_style_inputs():
    assert normalize_decimal_price(1299, interpret_integral_as_cents=True) == "12.99"
    assert normalize_decimal_price("1299", interpret_integral_as_cents=True) == "12.99"
    assert normalize_decimal_price("19.5", interpret_integral_as_cents=True) == "19.50"


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


def test_normalize_description_uses_shared_noise_policy_and_preserves_newlines():
    assert (
        normalize_value(
            "description",
            "<div>add to cart</div><p>Feature one</p><p>Feature two</p>",
        )
        == "Feature one\nFeature two"
    )


def test_normalize_availability_schema_url():
    assert normalize_value("availability", "https://schema.org/InStock") == "in_stock"


def test_normalize_availability_field_label_returns_empty_string():
    assert normalize_value("availability", "Availability") == ""
    assert normalize_and_validate_value("availability", "Availability") is None


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


def test_normalize_size_and_color_option_text():
    assert normalize_value("size", "Choose an option XS S M L XL") == "XS, S, M, L, XL"
    assert normalize_value("size", "(max-width: 416px) 100vw, 416px") == ""
    assert normalize_value("title", "Select a Size") == ""
    assert normalize_value("color", "Choose an option Black Gray Orange Clear") == "Black Gray Orange"
    assert normalize_value("color", "Size S, .") == ""


def test_validate_image_collection_filters_each_url_individually():
    assert (
        validate_value(
            "additional_images",
            "https://cdn.example.com/a.jpg?utm_source=x, https://cdn.example.com/logo-placeholder.png, https://cdn.example.com/b.jpg",
        )
        == "https://cdn.example.com/a.jpg, https://cdn.example.com/b.jpg"
    )


def test_validate_http_url_accepts_valid_http_urls_without_site_hacks():
    assert validate_value("url", "https://www.shopify.com/pricing") == "https://www.shopify.com/pricing"
    assert validate_value("url", "https://www.linkedin.com/jobs/view/123") == "https://www.linkedin.com/jobs/view/123"


def test_validate_brand_allows_single_slash_brand_names_but_rejects_breadcrumb_paths():
    assert validate_value("brand", "3M/Scotch") == "3M/Scotch"
    assert validate_value("brand", "Home / Brands / 3M") is None


def test_validate_color_hex_accepts_only_valid_css_hex_lengths():
    assert validate_value("color", "#abc") == "#abc"
    assert validate_value("color", "#abcd") == "#abcd"
    assert validate_value("color", "#abcdef") == "#abcdef"
    assert validate_value("color", "#abcdef12") == "#abcdef12"
    assert validate_value("color", "Select a Size") is None
    assert validate_value("color", "Size S, .") is None
    assert validate_value("color", "#abcde") is None
    assert validate_value("color", "#abcdefg") is None


def test_normalize_variant_axes_drops_waitlist_ctas_and_size_guide_headers():
    assert normalize_and_validate_value(
        "variant_axes",
        {
            "size": ["1", "2", "UK", "US", "EU", "Jeans", "Join the waitlist"],
            "color": ["Black", "color Black", "Check availability in store"],
        },
    ) == {"size": ["1", "2"], "color": ["Black"]}


def test_normalize_product_attributes_drops_variant_axis_metadata_payload():
    assert (
        normalize_and_validate_value(
            "product_attributes",
            {
                "key": "AT5",
                "name": "สี",
            },
        )
        is None
    )


def test_normalize_product_attributes_drops_selector_and_promo_noise():
    assert normalize_and_validate_value(
        "product_attributes",
        {
            "colour": "Chocolate Select a Size : Size Guide XS S M L",
            "select_a_size": "Size Guide XS S M L",
            "extra_15_off_everything_code": "KMEXTRA15",
            "brand": "KarenMillen",
        },
    ) == {"colour": "Chocolate", "brand": "KarenMillen"}
