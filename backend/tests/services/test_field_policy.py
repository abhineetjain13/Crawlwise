from __future__ import annotations

from app.services.field_policy import (
    browser_retry_target_fields_for_surface,
    canonical_requested_fields,
    exact_requested_field_key,
    field_allowed_for_surface,
    normalize_field_key,
    normalize_requested_field,
    preserve_requested_fields,
    repair_target_fields_for_surface,
)


def test_normalize_requested_field_strips_common_prefixes_before_alias_lookup() -> None:
    assert normalize_requested_field("product measurements") == "dimensions"
    assert normalize_requested_field("job qualifications") == "qualifications"


def test_normalize_requested_field_uses_token_subset_alias_match() -> None:
    assert normalize_requested_field("item_measurements_notes") == "dimensions"
    assert normalize_requested_field("size") == "size"
    assert normalize_requested_field("vendor") == "vendor"


def test_exact_requested_field_key_keeps_non_alias_composite_labels_stable() -> None:
    assert exact_requested_field_key("Features & Benefits") == "features_benefits"
    assert exact_requested_field_key("care instructions") == "care"


def test_normalize_field_key_splits_camel_and_pascal_case_before_lowercasing() -> None:
    assert normalize_field_key("ProductName") == "product_name"
    assert normalize_field_key("DetailURL") == "detail_url"
    assert normalize_field_key("FieldValues") == "field_values"


def test_preserve_requested_fields_keeps_user_input_raw() -> None:
    assert preserve_requested_fields(
        [" product measurements ", "Dimensions", "product measurements", ""]
    ) == ["product measurements", "Dimensions"]


def test_canonical_requested_fields_normalizes_aliases_for_runtime_matching() -> None:
    assert canonical_requested_fields(["product measurements", "care instructions"]) == [
        "dimensions",
        "care",
    ]


def test_field_allowed_for_surface_rejects_unknown_fields() -> None:
    assert field_allowed_for_surface("ecommerce_detail", "title") is True
    assert field_allowed_for_surface("ecommerce_detail", "gender") is True
    assert field_allowed_for_surface("job_detail", "gender") is False
    assert field_allowed_for_surface("ecommerce_detail", "random_garbage_key") is False


def test_normalize_requested_field_accepts_ecommerce_gender_aliases() -> None:
    assert normalize_requested_field("target gender") == "gender"
    assert normalize_requested_field("gender") == "gender"


def test_ecommerce_repair_targets_union_user_fields_with_limited_defaults() -> None:
    assert repair_target_fields_for_surface("ecommerce_detail", ["sku", "price"]) == [
        "sku",
        "price",
        "title",
        "image_url",
    ]


def test_ecommerce_browser_retry_targets_do_not_force_deep_variant_fields() -> None:
    assert browser_retry_target_fields_for_surface("ecommerce_detail", []) == [
        "price",
        "title",
        "image_url",
    ]


def test_ecommerce_repair_targets_include_deep_fields_only_when_requested() -> None:
    assert repair_target_fields_for_surface(
        "ecommerce_detail",
        ["brand", "sku", "availability", "variants", "selected_variant", "variant_axes"],
    ) == [
        "brand",
        "sku",
        "availability",
        "variants",
        "selected_variant",
        "variant_axes",
        "price",
        "title",
        "image_url",
    ]
