from __future__ import annotations

from app.services.field_value_core import (
    absolute_url,
    clean_text,
    extract_currency_code,
    extract_urls,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
    is_title_noise,
    strip_tracking_query_params,
    validate_and_clean,
    validate_record_for_surface,
)
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
    }
    assert rejected == {
        "image_count": "default_public_field_excluded",
        "variant_count": "default_public_field_excluded",
        "option1_name": "default_public_field_excluded",
        "option1_values": "default_public_field_excluded",
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


def test_extract_urls_splits_concatenated_absolute_urls() -> None:
    urls = extract_urls(
        "https://www.asos.com/us/foo/prd/1https://www.asos.com/us/bar/prd/2",
        "https://www.asos.com/us/foo/prd/1",
    )

    assert urls == [
        "https://www.asos.com/us/foo/prd/1",
        "https://www.asos.com/us/bar/prd/2",
    ]


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
