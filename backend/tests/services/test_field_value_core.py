from __future__ import annotations

import pytest

from app.services.field_value_core import (
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    extract_urls,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
    is_title_noise,
    strip_tracking_query_params,
    surface_alias_lookup,
    validate_and_clean,
    validate_record_for_surface,
)
from app.services.extract.shared_variant_logic import merge_variant_rows
from app.services.public_record_firewall import public_record_data_for_surface


def test_absolute_url_promotes_bare_host_candidates_to_https() -> None:
    assert absolute_url(
        "https://www.asos.com/us/prd/210817202",
        "images.asos-media.com/products/widget/image-1.jpg",
    ) == "https://images.asos-media.com/products/widget/image-1.jpg"


def test_absolute_url_does_not_promote_hosts_with_edge_hyphen_labels() -> None:
    assert absolute_url("https://example.com/base/", "-bad.example/path") == (
        "https://example.com/base/-bad.example/path"
    )
    assert absolute_url("https://example.com/base/", "bad-.example/path") == (
        "https://example.com/base/bad-.example/path"
    )


def test_coerce_brand_rejects_url_like_values() -> None:
    assert (
        coerce_field_value(
            "brand",
            "https://www.vitacost.com/brand",
            "https://www.vitacost.com/p/x",
        )
        is None
    )
    assert (
        coerce_field_value(
            "brand",
            {"@type": "Brand", "name": "https://www.example.com/brand/acme"},
            "https://www.example.com/p/x",
        )
        is None
    )
    assert (
        coerce_field_value("brand", {"name": "Acme"}, "https://example.com/p/x")
        == "Acme"
    )


def test_coerce_brand_keeps_non_url_scheme_text_but_rejects_full_bare_host() -> None:
    assert coerce_field_value("brand", "foo:bar", "https://example.com/p/x") == "foo:bar"
    assert coerce_field_value("brand", "shop.example.com", "https://example.com/p/x") is None


def test_frequently_bought_together_is_title_noise() -> None:
    assert is_title_noise("Frequently Bought Together") is True


def test_validate_and_clean_drops_fields_outside_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "price": "19.99",
            "internal_score": 0.91,
            "title": "Widget",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"price": "19.99"}
    assert errors == []


def test_validate_and_clean_nulls_schema_type_mismatches() -> None:
    cleaned, errors = validate_and_clean(
        {
            "price": {"amount": "19.99"},
            "variants": "not-a-list",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"price": None, "variants": None}
    assert len(errors) == 2


def test_validate_and_clean_applies_listing_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "title": ["Widget"],
            "url": "https://example.com/products/widget",
            "image_url": {"src": "https://cdn.example.com/widget.jpg"},
        },
        "ecommerce_listing",
    )

    assert cleaned == {
        "title": None,
        "url": "https://example.com/products/widget",
        "image_url": None,
    }
    assert len(errors) == 2


def test_validate_and_clean_applies_job_listing_surface_schema() -> None:
    cleaned, errors = validate_and_clean(
        {
            "title": "Platform Engineer",
            "company": {"name": "Acme"},
            "apply_url": "https://jobs.example.com/apply/123",
        },
        "job_listing",
    )

    assert cleaned == {
        "title": "Platform Engineer",
        "company": None,
        "apply_url": "https://jobs.example.com/apply/123",
    }
    assert len(errors) == 1


def test_validate_record_for_surface_drops_unknown_fields_but_keeps_canonical_fields() -> None:
    cleaned, errors = validate_record_for_surface(
        {
            "title": "Widget Prime",
            "price": {"amount": "19.99"},
            "random_garbage_key": "keep me out",
        },
        "ecommerce_detail",
    )

    assert cleaned == {"title": "Widget Prime"}
    assert len(errors) == 1


def test_ecommerce_aliases_keep_product_id_distinct_from_sku() -> None:
    aliases = surface_alias_lookup("ecommerce_detail", None)

    assert aliases["product_id"] == "product_id"
    assert aliases["sku"] == "sku"


def test_ecommerce_price_original_aliases_to_original_price() -> None:
    aliases = surface_alias_lookup("ecommerce_detail", None)

    assert aliases["price_original"] == "original_price"


def test_persistence_schema_firewall_drops_unknown_and_internal_fields() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget Prime",
            "price": "19.99",
            "_source": "llm_direct_record_extraction",
            "debug_payload": {"raw": True},
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget-prime",
    )

    assert data == {"title": "Widget Prime", "price": "19.99"}
    assert rejected == {"debug_payload": "field_not_allowed_for_surface"}


def test_persistence_schema_firewall_keeps_ecommerce_gender() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Linen Dress",
            "gender": "women",
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/linen-dress",
    )

    assert data == {"title": "Linen Dress", "gender": "Women"}
    assert rejected == {}


def test_public_record_firewall_validates_identity_shapes() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "barcode": "COPY-ABC123",
            "gender": "default",
            "brand": "Acme | US",
            "product_id": "specifications",
            "product_type": "BRIGHTCOVE VIDEO PLAYER",
            "sku": "tmp-ABC-123",
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget",
    )

    assert data == {"sku": "ABC-123", "brand": "Acme"}
    assert rejected == {
        "barcode": "empty_after_coercion",
        "gender": "empty_after_coercion",
        "product_id": "empty_after_coercion",
        "product_type": "empty_after_coercion",
    }


def test_coerce_sku_drops_draft_prefixed_numeric_artifacts() -> None:
    assert (
        coerce_field_value(
            "sku",
            "COPY-1720644688978",
            "https://example.com/products/widget",
        )
        is None
    )


def test_public_record_firewall_flattens_variants_to_public_shape() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget",
            "variants": [
                {
                    "variant_id": "1",
                    "title": "Widget Red Small",
                    "option_values": {"Colour": "Red", "Size": "S"},
                    "sku": "W-S",
                    "barcode": "ABC123",
                    "price": "$19.99",
                    "currency": "USD",
                    "url": "/products/widget?variant=1",
                }
            ],
            "variant_count": 1,
            "selected_variant": {"sku": "legacy"},
            "variant_axes": {"size": ["S"]},
            "available_sizes": ["S"],
            "option1_name": "size",
            "option1_values": ["S"],
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget",
    )

    assert data == {
        "title": "Widget",
        "variants": [
            {
                "color": "Red",
                "size": "S",
                "sku": "W-S",
                "price": "19.99",
                "currency": "USD",
                "url": "https://example.com/products/widget?variant=1",
            }
        ],
        "variant_count": 1,
    }
    assert rejected == {
        "selected_variant": "public_contract_excluded",
        "variant_axes": "public_contract_excluded",
        "available_sizes": "public_contract_excluded",
        "option1_name": "public_contract_excluded",
        "option1_values": "public_contract_excluded",
    }


def test_public_record_firewall_drops_ecommerce_tags_even_when_allowed() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget",
            "tags": ["size_10", "stock_in-stock", "featured"],
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget",
        requested_fields=["tags"],
    )

    assert data == {"title": "Widget"}
    assert rejected == {"tags": "public_contract_excluded"}


def test_persistence_schema_firewall_drops_default_ecommerce_schema_pollution() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget Prime",
            "brand": "Acme",
            "vendor": "Acme",
            "product_type": "CriteoProductRail",
            "image_count": 12,
            "variant_count": 4,
            "option1_name": "Size",
            "option1_values": ["4 lb", "12 lb"],
            "canonical_url": "https://example.com/products/widget-prime",
            "created_at": "2026-04-28T10:00:00Z",
            "published_at": "2026-04-28T10:00:00Z",
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget-prime",
    )

    assert data == {
        "title": "Widget Prime",
        "brand": "Acme",
        "vendor": "Acme",
        "product_type": "CriteoProductRail",
        "variant_count": 4,
    }
    assert rejected == {
        "image_count": "default_public_field_excluded",
        "option1_name": "public_contract_excluded",
        "option1_values": "public_contract_excluded",
        "canonical_url": "default_public_field_excluded",
        "created_at": "default_public_field_excluded",
        "published_at": "default_public_field_excluded",
    }


def test_persistence_schema_firewall_keeps_explicitly_requested_pollution_field() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget Prime",
            "product_type": "Dog Food",
            "vendor": "Acme",
        },
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget-prime",
        requested_fields=["product_type"],
    )

    assert data == {
        "title": "Widget Prime",
        "product_type": "Dog Food",
        "vendor": "Acme",
    }
    assert rejected == {}


def test_persistence_schema_firewall_canonicalizes_detail_url_query_params() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Shape Tape Concealer",
            "url": (
                "https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035"
                "?sku=2501218&size=0.33oz&utm_source=ad"
            ),
        },
        surface="ecommerce_detail",
        page_url="https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035",
    )

    assert data == {
        "title": "Shape Tape Concealer",
        "url": "https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035",
    }
    assert rejected == {}


def test_persistence_schema_firewall_normalizes_availability_enum_values() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Apple AirPods",
            "availability": "OUT_OF_STOCK",
        },
        surface="ecommerce_detail",
        page_url="https://www.walmart.com/ip/Apple-AirPods/604342441",
    )

    assert data["availability"] == "out_of_stock"
    assert rejected == {}


def test_persistence_schema_firewall_strips_size_cta_suffixes() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Shape Tape Concealer",
            "size": "0.33 oz Find your shade",
        },
        surface="ecommerce_detail",
        page_url="https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035",
    )

    assert data["size"] == "0.33 oz"
    assert rejected == {}


def test_listing_url_firewall_preserves_functional_variant_query_params() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Widget Prime",
            "url": "https://example.com/products/widget-prime?variant=blue",
        },
        surface="ecommerce_listing",
        page_url="https://example.com/collections/widgets",
    )

    assert data == {
        "title": "Widget Prime",
        "url": "https://example.com/products/widget-prime?variant=blue",
    }
    assert rejected == {}


def test_listing_url_firewall_rejects_api_event_click_urls() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "title": "Tracked card",
            "url": "https://www.chewy.com/api/event/p/sar/click?adsOrigin=aspen1&id=opaque",
            "price": "$12.50",
        },
        surface="ecommerce_listing",
        page_url="https://www.chewy.com/b/dog-leashes-and-collars-344",
    )

    assert data == {"title": "Tracked card", "price": "12.50"}
    assert rejected == {"url": "unsafe_navigation_url"}


def test_llm_outputs_pass_same_schema_firewall() -> None:
    data, rejected = public_record_data_for_surface(
        {
            "_source": "llm_missing_field_extraction",
            "title": "LLM Widget",
            "url": "javascript:alert(1)",
            "unknown_llm_field": "do not persist",
        },
        surface="ecommerce_listing",
        page_url="https://example.com/category/widgets",
    )

    assert data == {"title": "LLM Widget"}
    assert rejected == {
        "url": "unsafe_navigation_url",
        "unknown_llm_field": "field_not_allowed_for_surface",
    }


def test_strip_tracking_query_params_removes_etsy_style_click_tracking_but_keeps_functional_values() -> None:
    cleaned = strip_tracking_query_params(
        "https://example.com/products/widget-prime"
        "?click_key=opaque"
        "&click_sum=12345"
        "&ls=r"
        "&external=1"
        "&sr_prefetch=0"
        "&pf_from=rlp"
        "&pro=1"
        "&frs=1"
        "&sts=1"
        "&content_source=opaque_source"
        "&variant=blue"
    )

    assert cleaned == "https://example.com/products/widget-prime?variant=blue"


def test_strip_tracking_query_params_keeps_short_flags_without_detail_context_tracking() -> None:
    cleaned = strip_tracking_query_params(
        "https://example.com/products/widget-prime"
        "?gclid=opaque"
        "&ls=r"
        "&variant=blue"
    )

    assert cleaned == "https://example.com/products/widget-prime?ls=r&variant=blue"


def test_extract_currency_code_supports_rs_price_prefixes() -> None:
    assert extract_currency_code("Rs. 3,990.00") == "INR"
    assert extract_currency_code("INR 499") == "INR"


def test_extract_currency_code_ignores_non_currency_uppercase_acronyms() -> None:
    assert extract_currency_code("SKU 499") is None


def test_literal_list_text_uses_readable_delimiters() -> None:
    assert coerce_field_value(
        "description",
        "['Digital max resolution', 'Real boost clock: 1800 MHz']",
        "https://example.com/p/card",
    ) == "Digital max resolution; Real boost clock: 1800 MHz"


def test_option_scalars_reject_raw_objects_and_null_tokens() -> None:
    assert coerce_field_value(
        "color",
        "{'id': 'black-onyx', 'title': 'black onyx'}",
        "https://example.com/p/socks",
    ) is None
    assert coerce_field_value("color", "None", "https://example.com/p/wash") is None
    assert coerce_field_value("size", "- / null", "https://example.com/p/bag") is None
    assert coerce_field_value(
        "size",
        "Please select US EU",
        "https://example.com/p/sandal",
    ) is None


def test_color_scalar_extracts_value_from_prefixed_product_copy() -> None:
    assert coerce_field_value(
        "color",
        "for Sony WH-1000XM5 Wireless Noise-canceling Headphones - Black: Black",
        "https://example.com/p/headphones",
    ) == "Black"
    assert coerce_field_value(
        "color",
        "Black/Red Style: HJ0139-045",
        "https://example.com/p/shirt",
    ) == "Black/Red"


def test_clean_text_strips_leading_css_in_js_noise() -> None:
    assert (
        clean_text(".css-7u5e79{margin:0.5rem 0rem;} The Legend of Zelda")
        == "The Legend of Zelda"
    )


def test_is_title_noise_keeps_short_non_numeric_product_titles() -> None:
    assert is_title_noise("Hat") is False
    assert is_title_noise("UGG") is False
    assert is_title_noise("Tie") is False


def test_extract_urls_trims_trailing_punctuation_from_embedded_urls() -> None:
    urls = extract_urls(
        "Docs: https://example.com/alpha), https://example.com/beta.",
        "https://base.example",
    )

    assert urls == [
        "https://example.com/alpha",
        "https://example.com/beta",
    ]


def test_extract_urls_rejects_concatenated_absolute_urls() -> None:
    # Concatenated URLs are corrupted data (two products merged into one string),
    # not two valid products. Reject entirely.
    urls = extract_urls(
        "https://www.asos.com/us/foo/prd/1https://www.asos.com/us/bar/prd/2",
        "https://www.asos.com/us/foo/prd/1",
    )

    assert urls == []


def test_extract_urls_preserves_balanced_parentheses_and_brackets() -> None:
    urls = extract_urls(
        "Docs: https://example.com/release_(2026), https://example.com/archive/[spring].",
        "https://base.example",
    )

    assert urls == [
        "https://example.com/release_(2026)",
        "https://example.com/archive/[spring]",
    ]


def test_extract_urls_rejects_malformed_relative_image_fragments() -> None:
    assert extract_urls(
        "g_auto/69721f2e7c934d909168a80e00818569_9366/Stan_Smith_Shoes_White_M20324_01_standard.jpg",
        "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    ) == []
    assert extract_urls(
        "R0lGODlhAQABAIAAAP/wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
        "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    ) == []


def test_infer_brand_from_title_marker_keeps_leading_trademark_brand_token() -> None:
    assert infer_brand_from_title_marker("®Nike Court Vision Low") == "®Nike"


def test_infer_brand_from_product_url_skips_overlong_slug_and_keeps_valid_match() -> None:
    assert (
        infer_brand_from_product_url(
            url=(
                "https://example.com/acme-widget-prime/"
                "one-two-three-four-five-six-seven-eight-nine-widget-prime"
            ),
            title="Widget Prime",
        )
        == "Acme"
    )


def test_infer_brand_from_product_url_rejects_numeric_product_id_prefix() -> None:
    assert (
        infer_brand_from_product_url(
            url="https://example.com/products/492216804-black-leather-belts-for-men",
            title="Black Leather Belts for Men",
        )
        is None
    )


# --- Slice A: Field-value validation tests ---


def test_coerce_color_rejects_single_digit_from_quantity_input() -> None:
    assert coerce_field_value("color", "1", "https://example.com/p") is None
    assert coerce_field_value("color", "2", "https://example.com/p") is None
    assert coerce_field_value("color", "99", "https://example.com/p") is None


def test_coerce_color_keeps_valid_color_names() -> None:
    assert coerce_field_value("color", "Black Onyx", "https://example.com/p") == "Black Onyx"
    assert coerce_field_value("color", "Navy Blue", "https://example.com/p") == "Navy Blue"


def test_coerce_color_rejects_tracking_pixel_classes() -> None:
    assert coerce_field_value("color", "_clck", "https://example.com/p") is None
    assert coerce_field_value("color", "_fbp", "https://example.com/p") is None


@pytest.mark.parametrize(
    "label",
    ["Photos", "Verified Purchases", "Reviews", "Description", "Specifications"],
)
def test_coerce_size_rejects_ui_tab_labels(label: str) -> None:
    assert coerce_field_value("size", label, "https://example.com/p") is None


def test_coerce_size_keeps_valid_sizes() -> None:
    assert coerce_field_value("size", "M", "https://example.com/p") == "M"
    assert coerce_field_value("size", "10", "https://example.com/p") == "10"
    assert coerce_field_value("size", "XL", "https://example.com/p") == "XL"


def test_extract_urls_filters_placeholder_images() -> None:
    assert extract_urls(
        "https://via.placeholder.com/600", "https://example.com/p"
    ) == []
    assert extract_urls(
        "https://cdn.example.com/pixel.gif", "https://example.com/p"
    ) == []


def test_extract_urls_filters_concatenated_urls() -> None:
    assert extract_urls(
        "https://www.selfridges.com/p/123/https:/www.mytheresa.com/p/456",
        "https://example.com/p",
    ) == []


def test_extract_urls_keeps_normal_urls() -> None:
    urls = extract_urls(
        "https://cdn.example.com/product/image.jpg", "https://example.com/p"
    )
    assert len(urls) == 1
    assert "product/image.jpg" in urls[0]


def test_public_firewall_rejects_concatenated_url() -> None:
    record = {
        "url": "https://www.selfridges.com/p/123/https:/www.mytheresa.com/p/456",
        "title": "Test Product",
    }
    data, rejected = public_record_data_for_surface(
        record, surface="ecommerce_detail", page_url="https://www.selfridges.com/p/123"
    )
    assert "url" not in data
    assert rejected.get("url") == "empty_after_coercion"


def test_integer_fields_reject_embedded_numeric_junk() -> None:
    assert coerce_field_value("stock_quantity", "abc123", "https://example.com/p") is None
    assert coerce_field_value("stock_quantity", "1,234", "https://example.com/p") == 1234


def test_public_firewall_does_not_route_invalid_barcode_to_sku() -> None:
    data, rejected = public_record_data_for_surface(
        {"barcode": {"bad": "shape"}},
        surface="ecommerce_detail",
        page_url="https://example.com/p",
    )

    assert "sku" not in data
    assert rejected["barcode"] == "empty_after_coercion"


def test_merge_variant_rows_keeps_axis_only_rows_without_url_identity() -> None:
    rows = merge_variant_rows(
        [
            {"size": "8", "price": "100"},
            {"size": "9", "price": "100"},
        ]
    )

    assert [row["size"] for row in rows] == ["8", "9"]
    assert [row["price"] for row in rows] == ["100", "100"]
