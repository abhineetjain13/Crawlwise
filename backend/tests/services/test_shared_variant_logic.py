from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.shared_variant_logic import (
    resolve_variant_group_name,
    resolve_variants,
    variant_axis_name_is_semantic,
)


def test_resolve_variants_pairs_color_with_size_cartesian() -> None:
    """Two-axis matrix: every color×size combo that exists is emitted
    in deterministic Cartesian order."""
    axes = {"color": ["Red", "Blue"], "size": ["S", "M"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Blue", "size": "M"}},
        {"variant_id": "2", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "3", "option_values": {"color": "Red", "size": "M"}},
        {"variant_id": "4", "option_values": {"color": "Blue", "size": "S"}},
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 4
    # Cartesian order: (Red,S), (Red,M), (Blue,S), (Blue,M)
    assert resolved[0]["variant_id"] == "2"
    assert resolved[1]["variant_id"] == "3"
    assert resolved[2]["variant_id"] == "4"
    assert resolved[3]["variant_id"] == "1"


def test_resolve_variants_skips_missing_combinations() -> None:
    """If a Cartesian cell has no matching variant it is omitted rather
    than synthesised, preventing phantom variants."""
    axes = {"color": ["Red", "Blue"], "size": ["S", "M", "L"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "2", "option_values": {"color": "Red", "size": "M"}},
        {"variant_id": "3", "option_values": {"color": "Blue", "size": "S"}},
        # Blue/M and Blue/L and Red/L are missing
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 3
    ids = [v["variant_id"] for v in resolved]
    assert ids == ["1", "2", "3"]


def test_resolve_variants_dedupes_by_combo() -> None:
    """Duplicate variants mapping to the same option_values combo are
    collapsed; the richer row wins."""
    axes = {"color": ["Red"], "size": ["S"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {
            "variant_id": "1",
            "option_values": {"color": "Red", "size": "S"},
            "price": "9.99",
        },
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 1
    assert resolved[0].get("price") == "9.99"


def test_resolve_variants_appends_variants_without_option_values() -> None:
    """Variants that lack option_values are not lost; they are appended
    after the Cartesian-resolved rows."""
    axes = {"color": ["Red"], "size": ["S"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "2", "sku": "LONE-SKU"},  # no option_values
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 2
    assert resolved[0]["variant_id"] == "1"
    assert resolved[1]["variant_id"] == "2"


def test_resolve_variants_appends_partial_option_values() -> None:
    """Variants with incomplete option_values (missing an axis) are
    appended rather than dropped."""
    axes = {"color": ["Red", "Blue"], "size": ["S"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "2", "option_values": {"color": "Blue"}},  # missing size
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 2
    assert resolved[0]["variant_id"] == "1"
    assert resolved[1]["variant_id"] == "2"


def test_resolve_variants_returns_original_when_no_axes() -> None:
    """Empty options_matrix → fall back to original variant list."""
    resolved = resolve_variants({}, [{"variant_id": "1"}])
    assert resolved == [{"variant_id": "1"}]


def test_resolve_variants_returns_original_when_no_variants() -> None:
    """Empty variant list → return empty list."""
    assert resolve_variants({"color": ["Red"]}, []) == []


def test_resolve_variants_single_axis() -> None:
    """Single-axis products still get Cartesian (trivial) ordering."""
    axes = {"size": ["S", "M", "L"]}
    variants = [
        {"variant_id": "3", "option_values": {"size": "L"}},
        {"variant_id": "1", "option_values": {"size": "S"}},
        {"variant_id": "2", "option_values": {"size": "M"}},
    ]

    resolved = resolve_variants(axes, variants)

    ids = [v["variant_id"] for v in resolved]
    assert ids == ["1", "2", "3"]


def test_resolve_variants_three_axis_cartesian() -> None:
    """Three-axis matrix (color × size × material) is resolved
    correctly in Cartesian order."""
    axes = {
        "color": ["Red", "Blue"],
        "size": ["S", "M"],
        "material": ["Cotton", "Poly"],
    }
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S", "material": "Cotton"}},
        {"variant_id": "2", "option_values": {"color": "Red", "size": "S", "material": "Poly"}},
        {"variant_id": "3", "option_values": {"color": "Red", "size": "M", "material": "Cotton"}},
        {"variant_id": "4", "option_values": {"color": "Blue", "size": "S", "material": "Cotton"}},
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 4
    # Cartesian order: (Red,S,Cotton), (Red,S,Poly), (Red,M,Cotton), ...
    assert resolved[0]["variant_id"] == "1"
    assert resolved[1]["variant_id"] == "2"
    assert resolved[2]["variant_id"] == "3"
    assert resolved[3]["variant_id"] == "4"


def test_resolve_variants_dedupes_no_option_values_by_id() -> None:
    """When a variant without option_values shares a variant_id with
    a resolved variant, it is not duplicated."""
    axes = {"color": ["Red"], "size": ["S"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "1", "sku": "ABC"},  # same id, no option_values
    ]

    resolved = resolve_variants(axes, variants)

    assert len(resolved) == 1
    assert resolved[0]["variant_id"] == "1"


def test_resolve_variants_dedupes_no_option_values_against_each_other() -> None:
    axes = {"color": ["Red"], "size": ["S"]}
    variants = [
        {"variant_id": "1", "option_values": {"color": "Red", "size": "S"}},
        {"variant_id": "2"},
        {"variant_id": "2", "sku": "SKU-2"},
        {"sku": "SKU-3"},
        {"sku": "SKU-3"},
    ]

    resolved = resolve_variants(axes, variants)

    assert [variant.get("variant_id") or variant.get("sku") for variant in resolved] == [
        "1",
        "2",
        "SKU-3",
    ]


def test_variant_axis_name_is_semantic_accepts_non_generic_axis_labels() -> None:
    assert variant_axis_name_is_semantic("shoe width") is True
    assert variant_axis_name_is_semantic("variant option") is False
    assert variant_axis_name_is_semantic("Language Translate Widget") is False


def test_resolve_variant_group_name_infers_unlabeled_select_size_axis_from_values() -> None:
    soup = BeautifulSoup(
        """
        <select>
          <option>-- Click to choose size --</option>
          <option>EU-36</option>
          <option>EU-37</option>
          <option>EU-38</option>
        </select>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("select")) == "size"
