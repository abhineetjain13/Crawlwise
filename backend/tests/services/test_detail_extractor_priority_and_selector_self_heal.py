from __future__ import annotations

from pathlib import Path

from app.services.config._export_data import load_export_data
from app.services.extraction_runtime import extract_records
from app.services.selector_self_heal import (
    _validated_xpath_rules,
    _selector_heal_improved_record,
    reduce_html_for_selector_synthesis,
    selector_self_heal_targets,
)


def test_extract_records_prefers_higher_priority_adapter_value_even_when_dom_value_exists() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <span class="price">$999.99</span>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price"],
        adapter_records=[{"price": "19.99", "_source": "adapter"}],
    )[0]

    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"
    assert "adapter" in str(record["_field_sources"]["price"])
    assert "dom_selector" in str(record["_field_sources"]["price"])
    assert record["_source"] == "adapter"


def test_extract_records_does_not_fabricate_discount_percentage_from_unrelated_body_text() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Elowen Wide Leg Jumpsuit</h1>
          <p>Composition: 100% cotton. Care at 30 degrees. Free shipping over 50.</p>
          <span class="price">£149.00</span>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://www.phase-eight.com/product/elowen-wide-leg-jumpsuit-10022060230.html",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price", "discount_percentage"],
    )[0]

    assert "discount_percentage" not in record
    assert "discount_percentage" not in record.get("_field_sources", {})


def test_extract_records_applies_selector_rules_and_tracks_selector_source() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="product-description">Built for long mileage.</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
        selector_rules=[
            {
                "field_name": "description",
                "css_selector": ".product-description",
                "is_active": True,
            }
        ],
    )[0]

    assert record["description"] == "Built for long mileage."
    assert record["_field_sources"]["description"] == ["dom_selector"]


def test_extract_records_keeps_first_match_for_long_text_fields() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="product-description">DOM fallback description.</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
        adapter_records=[{"description": "Adapter description."}],
        selector_rules=[
            {
                "field_name": "description",
                "css_selector": ".product-description",
                "is_active": True,
            }
        ],
    )[0]

    assert record["description"] == "Adapter description."
    assert "adapter" in str(record["_field_sources"]["description"])
    assert "dom_selector" in str(record["_field_sources"]["description"])
    assert record["_source"] == "adapter"


def test_extract_records_uses_accordion_dom_sections_for_long_text_fields() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <button aria-controls="description-panel">Description</button>
          <section id="description-panel">
            Built for long mileage with a reinforced toe cap.
          </section>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
    )[0]

    assert record["description"] == "Built for long mileage with a reinforced toe cap."
    assert record["_field_sources"]["description"] == ["dom_sections"]


def test_extract_records_uses_nested_wrapped_dom_sections_for_long_text_fields() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="accordion-item">
            <button>Specifications</button>
            <div class="accordion-item__body">
              <div class="rich-content">
                Rubber outsole with a reinforced toe cap.
              </div>
            </div>
          </div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["specifications"],
    )[0]

    assert record["specifications"] == "Rubber outsole with a reinforced toe cap."
    assert record["_field_sources"]["specifications"] == ["dom_sections"]


def test_extract_records_applies_regex_as_post_filter_to_xpath_result() -> None:
    html = """
    <html>
      <body>
        <script>window.badSku = "SKU: 99999";</script>
        <main>
          <div class="sku">SKU: 12345</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["sku"],
        selector_rules=[
            {
                "field_name": "sku",
                "xpath": "//div[@class='sku']/text()",
                "regex": r"SKU:\s*(\d+)",
                "is_active": True,
            }
        ],
    )[0]

    assert record["sku"] == "12345"
    assert record["_field_sources"]["sku"] == ["dom_selector"]


def test_selector_self_heal_config_falls_back_to_runtime_enabled_when_missing(
    patch_settings,
) -> None:
    patch_settings(
        selector_self_heal_enabled=True,
        selector_self_heal_min_confidence=0.77,
    )
    record = extract_records(
        "<html><body><h1>Widget Prime</h1></body></html>",
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": None, "min_confidence": None}
        },
    )[0]

    assert record["_self_heal"] == {
        "enabled": True,
        "triggered": False,
        "threshold": 0.77,
    }


def test_selector_self_heal_targets_default_ecommerce_fields_when_requested_empty() -> (
    None
):
    class _Run:
        surface = "ecommerce_detail"
        requested_fields: list[str] = []

    targets = selector_self_heal_targets(
        run=_Run(),  # type: ignore[arg-type]
        record={"title": "Widget Prime", "price": ""},
    )

    assert "price" in targets
    assert "image_url" in targets
    assert "variants" not in targets


def test_reduce_html_for_selector_synthesis_keeps_valid_content_focused_html() -> None:
    nav_noise = "".join(
        f"<a href='/collections/widgets/{index}'>Noise {index}</a>"
        for index in range(9_000)
    )
    html = f"""
    <html>
      <body>
        <nav>{nav_noise}</nav>
        <main id="product-detail">
          <article class="product">
            <h1>Widget Prime</h1>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </article>
        </main>
        <script>window.__NOISE__ = true;</script>
      </body>
    </html>
    """

    reduced = reduce_html_for_selector_synthesis(html)
    from bs4 import BeautifulSoup

    parsed = BeautifulSoup(reduced, "html.parser")
    main = parsed.find("main", attrs={"id": "product-detail"})

    assert len(reduced) <= 200_000
    assert parsed.find("nav") is None
    assert parsed.find("script") is None
    assert main is not None
    assert main.find("article", attrs={"class": "product"}) is not None
    assert "Widget Prime" in main.get_text(" ", strip=True)
    assert "Rubber outsole, reinforced toe cap." in main.get_text(" ", strip=True)


def test_reduce_html_for_selector_synthesis_preserves_shadow_root_boundaries() -> None:
    reduced = reduce_html_for_selector_synthesis(
        """
        <html>
          <body>
            <product-shell>
              <template shadowrootmode="open">
                <section class="details">
                  <h2>Specs</h2>
                  <div slot="content">Waterproof membrane</div>
                </section>
              </template>
            </product-shell>
          </body>
        </html>
        """
    )

    assert "template" in reduced
    assert 'shadowrootmode="open"' in reduced
    assert "Waterproof membrane" in reduced


def test_reduce_html_for_selector_synthesis_preserves_price_and_buy_box_controls() -> (
    None
):
    reduced = reduce_html_for_selector_synthesis(
        """
        <html><body>
          <main>
            <form class="buy-box" data-product-id="sku-1">
              <span class="price" data-price="229.99" itemprop="price">$229.99</span>
              <button type="button" aria-label="Size 9" data-variant-id="v9">9</button>
              <input name="sku" data-sku="sku-1" value="sku-1" />
            </form>
          </main>
        </body></html>
        """
    )

    assert 'data-price="229.99"' in reduced
    assert 'itemprop="price"' in reduced
    assert 'aria-label="Size 9"' in reduced
    assert 'data-variant-id="v9"' in reduced
    assert 'data-sku="sku-1"' in reduced
    assert 'value="sku-1"' in reduced


def test_selector_synthesis_keep_worthy_tags_round_trip_through_export() -> None:
    from app.services.config.selectors import SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS

    exports = load_export_data(
        str(
            Path(__file__).parents[2]
            / "app"
            / "services"
            / "config"
            / "selectors.exports.json"
        )
    )

    assert exports["SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS"] == (
        SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS
    )


def test_extract_records_deep_merges_structured_variant_fields_across_tiers() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <label>
          Color
          <select name="color">
            <option value="">Choose color</option>
            <option value="black">Black</option>
            <option value="olive">Olive</option>
          </select>
        </label>
      </body>
    </html>
    """

    extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["variant_axes", "selected_variant"],
        adapter_records=[
            {
                "variant_axes": {"size": ["S", "M"]},
                "selected_variant": {
                    "sku": "TRAIL-S",
                    "option_values": {"size": "S"},
                },
            }
        ],
    )[0]


def test_selector_self_heal_requires_field_level_improvement_before_persisting() -> (
    None
):
    assert (
        _selector_heal_improved_record(
            before_record={"title": "Widget Prime", "price": ""},
            after_record={"title": "Widget Prime", "price": "19.99"},
            target_fields=["price"],
        )
        is True
    )
    assert (
        _selector_heal_improved_record(
            before_record={"title": "Widget Prime", "price": ""},
            after_record={"title": "Widget Prime", "price": ""},
            target_fields=["price"],
        )
        is False
    )


def test_selector_self_heal_converts_css_candidates_before_persisting_xpath() -> None:
    rules = _validated_xpath_rules(
        html="""
        <html>
          <body>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </body>
        </html>
        """,
        candidates=[
            {
                "field_name": "specifications",
                "xpath": "div.custom-specs",
            }
        ],
        target_fields=["specifications"],
    )

    assert len(rules) == 1
    assert rules[0]["sample_value"] == "Rubber outsole, reinforced toe cap."
    assert str(rules[0]["xpath"]).startswith("//div")
