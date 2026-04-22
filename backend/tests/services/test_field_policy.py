from __future__ import annotations

from app.services.field_policy import (
    canonical_requested_fields,
    exact_requested_field_key,
    normalize_field_key,
    normalize_requested_field,
    preserve_requested_fields,
)


def test_normalize_requested_field_strips_common_prefixes_before_alias_lookup() -> None:
    assert normalize_requested_field("product measurements") == "dimensions"
    assert normalize_requested_field("job qualifications") == "qualifications"


def test_normalize_requested_field_uses_token_subset_alias_match() -> None:
    assert normalize_requested_field("item_measurements_notes") == "dimensions"


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
