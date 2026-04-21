from __future__ import annotations

from app.services.field_policy import normalize_requested_field


def test_normalize_requested_field_strips_common_prefixes_before_alias_lookup() -> None:
    assert normalize_requested_field("product measurements") == "dimensions"
    assert normalize_requested_field("job qualifications") == "qualifications"


def test_normalize_requested_field_uses_token_subset_alias_match() -> None:
    assert normalize_requested_field("item_measurements_notes") == "dimensions"
