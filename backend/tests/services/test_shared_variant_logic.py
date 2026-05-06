from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.shared_variant_logic import (
    iter_variant_choice_groups,
    iter_variant_select_groups,
    normalized_variant_axis_key,
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
        {
            "variant_id": "1",
            "option_values": {"color": "Red", "size": "S", "material": "Cotton"},
        },
        {
            "variant_id": "2",
            "option_values": {"color": "Red", "size": "S", "material": "Poly"},
        },
        {
            "variant_id": "3",
            "option_values": {"color": "Red", "size": "M", "material": "Cotton"},
        },
        {
            "variant_id": "4",
            "option_values": {"color": "Blue", "size": "S", "material": "Cotton"},
        },
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

    assert [
        variant.get("variant_id") or variant.get("sku") for variant in resolved
    ] == [
        "1",
        "2",
        "SKU-3",
    ]


def test_variant_axis_name_is_semantic_accepts_non_generic_axis_labels() -> None:
    assert variant_axis_name_is_semantic("shoe width") is True
    assert variant_axis_name_is_semantic("variant option") is False
    assert variant_axis_name_is_semantic("Language Translate Widget") is False
    assert variant_axis_name_is_semantic("Sort By") is False
    assert variant_axis_name_is_semantic("Filter By") is False
    assert variant_axis_name_is_semantic("Availability") is False


def test_resolve_variant_group_name_infers_unlabeled_select_size_axis_from_values() -> (
    None
):
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


def test_resolve_variant_group_name_rejects_shipping_country_select() -> None:
    soup = BeautifulSoup(
        """
        <label for="estimated-shipping-country">Country</label>
        <select
          id="estimated-shipping-country"
          name="estimated-shipping-country"
          aria-label="Choose country"
        >
          <option>Australia</option>
          <option>Canada</option>
        </select>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("select")) == ""


def test_resolve_variant_group_name_rejects_size_chart_controls() -> None:
    soup = BeautifulSoup(
        """
        <button id="size-chart-button" aria-label="Size Chart">Size Chart</button>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("button")) == ""


def test_resolve_variant_group_name_rejects_report_reason_select() -> None:
    soup = BeautifulSoup(
        """
        <label for="report-item-choices" class="wt-screen-reader-only">Choose a reason…</label>
        <select id="report-item-choices">
          <option value="default">Choose a reason…</option>
          <option value="order-problem">There’s a problem with my order</option>
        </select>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("select")) == ""


def test_variant_select_groups_reject_cookie_consent_token_selects() -> None:
    soup = BeautifulSoup(
        """
        <select id="privacy-type" name="type">
          <option>OptOut</option>
          <option>RemoveMe</option>
          <option>MyInfo</option>
        </select>
        <label for="size">Size</label>
        <select id="size">
          <option>100 Softgels</option>
          <option>200 Softgels</option>
        </select>
        """,
        "html.parser",
    )

    groups = list(iter_variant_select_groups(soup))

    assert [
        normalized_variant_axis_key(resolve_variant_group_name(group))
        for group in groups
    ] == ["size"]


def test_variant_select_groups_reject_style_control_selects() -> None:
    """Reject non-product style controls that happen to use select elements."""
    soup = BeautifulSoup(
        """
        <form>
          <label>Text
            <select>
              <option>White</option>
              <option>Black</option>
              <option>Red</option>
            </select>
          </label>
          <label>Background
            <select>
              <option>Opaque</option>
              <option>Semi-Transparent</option>
            </select>
          </label>
        </form>
        """,
        "html.parser",
    )

    assert list(iter_variant_select_groups(soup)) == []


def test_resolve_variant_group_name_reads_external_label_for_select() -> None:
    soup = BeautifulSoup(
        """
        <label for="variation-selector-0">Style &amp; Size</label>
        <select id="variation-selector-0">
          <option>Sweatshirt S</option>
          <option>Sweatshirt M</option>
        </select>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("select")) == "Style & Size"


def test_resolve_variant_group_name_ignores_external_option_label_for_radio() -> None:
    soup = BeautifulSoup(
        """
        <ul class="sizelist">
          <li class="oval outstock">
            <input id="size_0_0" disabled type="radio" name="sub_prod_0" />
            <label for="size_0_0"><span>XXS</span><span>0 Left</span></label>
          </li>
          <li class="oval selected">
            <input id="size_0_1" checked type="radio" name="sub_prod_0" />
            <label for="size_0_1"><span>XS</span><span>17 Left</span></label>
          </li>
        </ul>
        """,
        "html.parser",
    )

    assert resolve_variant_group_name(soup.select_one("input")) == "size"


def test_variant_choice_groups_ignore_single_image_swatches_and_keep_button_grid() -> (
    None
):
    soup = BeautifulSoup(
        """
        <div class="image-viewer-swatch-col hmf-span-3">
          <button
            id="alt-image-viewer-wrapper-123"
            class="image-wrapper-padding image-wrapper-height image-viewer-swatch-wrapper"
            aria-label="View Image in Full Screen"
            type="button"
          ></button>
        </div>
        <section id="pdp-selector-attributes" class="selector-attributes-container">
          <p><span>Shoe Size:</span></p>
          <div class="hmf-grid selector-attribute-outer overflow-scroll">
            <hmf-selectable>
              <div class="hmf-selectable-container hmf-display-flex hmf-body-m hmf-flex-wrap">
                <div class="hmf-option-container">
                  <button class="hmf-selectable-base hmf-selectable-unselected" aria-label="5.0/5.5 US (36 EU)" type="button">
                    <span>5.0/5.5 US (36 EU)</span>
                  </button>
                </div>
                <div class="hmf-option-container">
                  <button class="hmf-selectable-base hmf-selectable-unselected" aria-label="6.0/6.5 US (37 EU)" type="button">
                    <span>6.0/6.5 US (37 EU)</span>
                  </button>
                </div>
              </div>
            </hmf-selectable>
          </div>
        </section>
        """,
        "html.parser",
    )

    groups = list(iter_variant_choice_groups(soup))

    assert len(groups) == 1
    assert "5.0/5.5 US (36 EU)" in groups[0].get_text(" ", strip=True)


def test_variant_choice_groups_skip_overbroad_parent_and_keep_fieldsets() -> None:
    soup = BeautifulSoup(
        """
        <div class="page">
          <div id="attribute-accordion" class="accordion">
            <div class="card-body">
              <div class="attr-group-body">
                <fieldset class="attr-group-items">
                  <input
                    type="radio"
                    id="size-size_a_small"
                    name="size"
                    data-attr-displayvalue="Size A - Small"
                  />
                  <label for="size-size_a_small">
                    <span class="sr-only">View this product in: Size</span>
                    <span>Size A - Small</span>
                  </label>
                  <input
                    type="radio"
                    id="size-size_b_medium"
                    name="size"
                    data-attr-displayvalue="Size B - Medium"
                  />
                  <label for="size-size_b_medium">
                    <span class="sr-only">View this product in: Size</span>
                    <span>Size B - Medium</span>
                  </label>
                </fieldset>
              </div>
            </div>
            <div class="card-body">
              <div class="attr-group-body">
                <fieldset class="attr-group-items">
                  <input
                    type="radio"
                    id="backSupport-basic_back_support"
                    name="backSupport"
                    data-attr-displayvalue="Basic Back Support"
                  />
                  <label for="backSupport-basic_back_support">
                    <span class="sr-only">View this product in: Back Support</span>
                    <span>Basic Back Support</span>
                  </label>
                  <input
                    type="radio"
                    id="backSupport-adjustable_lumbar_support"
                    name="backSupport"
                    data-attr-displayvalue="Adjustable Lumbar Support"
                  />
                  <label for="backSupport-adjustable_lumbar_support">
                    <span class="sr-only">View this product in: Back Support</span>
                    <span>Adjustable Lumbar Support</span>
                  </label>
                </fieldset>
              </div>
            </div>
          </div>
        </div>
        """,
        "html.parser",
    )

    groups = list(iter_variant_choice_groups(soup))

    assert [
        normalized_variant_axis_key(resolve_variant_group_name(group))
        for group in groups
    ] == [
        "size",
        "back_support",
    ]
    assert not any(group.get("id") == "attribute-accordion" for group in groups)
