from __future__ import annotations

from app.services.extract.variant_group_validator import (
    VariantCandidateGroup,
    VariantGroupValidator,
)


def _group(**overrides: object) -> VariantCandidateGroup:
    values = list(overrides.pop("values", ["Black", "White"]))
    entries = list(
        overrides.pop(
            "entries",
            [{"value": value, "url": f"https://example.com/products/item-{value.lower()}"} for value in values],
        )
    )
    defaults = {
        "name": "Color",
        "axis_key": "color",
        "values": values,
        "entries": entries,
        "container_tag": "fieldset",
        "container_classes": ["color-selector"],
        "container_id": None,
        "container_role": None,
        "ancestor_class_tokens": ["product-detail"],
        "extractor_path": "choice_radio",
        "scope_source": "trusted_scope",
        "option_node_types": ["input_radio"],
    }
    defaults.update(overrides)
    return VariantCandidateGroup(**defaults)


def test_variant_group_validator_accepts_structural_product_group() -> None:
    group = _group()

    assert VariantGroupValidator().validate(group, page_url="https://example.com/products/item") is True
    assert group.confidence >= 0.35


def test_variant_group_validator_rejects_navigation_context() -> None:
    group = _group(
        container_tag="nav",
        container_classes=["tab-list", "reviews"],
        ancestor_class_tokens=["product-detail"],
        entries=[{"value": "Overview", "url": "https://example.com/overview"}],
        option_node_types=["a"],
        scope_source="soft_scope",
    )

    assert VariantGroupValidator().validate(group, page_url="https://example.com/products/item") is False
    assert "chrome_container:nav" in group.rejection_reasons


def test_variant_group_validator_rejects_identical_listing_urls() -> None:
    group = _group(
        entries=[
            {"value": "Black", "url": "https://www.lowes.com/pl/ceiling-lights"},
            {"value": "White", "url": "https://www.lowes.com/pl/ceiling-lights"},
        ],
        option_node_types=["a"],
        scope_source="soft_scope",
    )

    assert VariantGroupValidator().validate(group, page_url="https://www.lowes.com/pd/light/123") is False
    assert "all_urls_identical_non_product" in group.rejection_reasons


def test_variant_group_validator_accepts_collection_scoped_product_urls() -> None:
    group = _group(
        entries=[
            {
                "value": "Black",
                "url": "https://savannahs.com/collections/all-boots/products/trompette-100-suede-boots-rv27109s",
            },
            {
                "value": "Brown",
                "url": "https://savannahs.com/collections/all-boots/products/phoenix-dark-brown-leather-boots-ch28105s",
            },
        ],
        option_node_types=["a"],
        scope_source="soft_scope",
    )

    assert (
        VariantGroupValidator().validate(
            group,
            page_url="https://savannahs.com/collections/all-boots/products/trompette-100-suede-boots-rv27109s",
        )
        is True
    )
