from __future__ import annotations

from collections import defaultdict

from app.services.config.field_mappings import FIELD_ALIASES


def test_field_aliases_only_share_intentionally_duplicated_aliases():
    alias_to_canonical: dict[str, list[str]] = defaultdict(list)
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_to_canonical[alias].append(canonical)

    collisions = {
        alias: canonicals
        for alias, canonicals in alias_to_canonical.items()
        if len(canonicals) > 1
    }

    assert collisions == {
        "image": ["image_url", "additional_images"],
    }


def test_color_variants_aliases_stay_color_specific():
    assert "variants" not in FIELD_ALIASES["color_variants"]
    assert "color_swatch" in FIELD_ALIASES["color_variants"]
