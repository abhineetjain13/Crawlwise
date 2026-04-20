from __future__ import annotations

from app.services.field_value_core import validate_and_clean


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
