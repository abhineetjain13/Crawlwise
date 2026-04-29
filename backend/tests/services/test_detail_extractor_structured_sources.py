from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.services.adapters.myntra import MyntraAdapter
from app.services.detail_extractor import (
    _detail_image_matches_primary_family,
    _sanitize_variant_row,
    build_detail_record,
    variant_option_availability,
)
from app.services.extract.detail_price_extractor import (
    detail_currency_hint_is_host_level,
    reconcile_detail_currency_with_url,
)
from app.services.extraction_runtime import extract_records
from tests.fixtures.loader import read_optional_artifact_text


def test_detail_currency_hint_host_matching_avoids_partial_word_false_positive() -> None:
    assert (
        detail_currency_hint_is_host_level(
            "https://www.notarget.com/products/widget",
            expected_currency="USD",
        )
        is False
    )
    assert (
        detail_currency_hint_is_host_level(
            "https://www.target.com/products/widget",
            expected_currency="USD",
        )
        is True
    )


def test_reconcile_detail_currency_with_url_tracks_nested_currency_sources() -> None:
    record = {
        "selected_variant": {"price": "10.00"},
        "variants": [{"price": "10.00"}],
    }

    reconcile_detail_currency_with_url(
        record,
        page_url="https://www.target.com/p/widget",
    )

    assert record["selected_variant"]["currency"] == "USD"
    assert record["variants"][0]["currency"] == "USD"
    assert "url_currency_hint" in record["_field_sources"]["selected_variant.currency"]
    assert "url_currency_hint" in record["_field_sources"]["variants[0].currency"]


def test_extract_ecommerce_detail_from_microdata() -> None:
    html = """
    <html>
      <body>
        <main itemscope itemtype="https://schema.org/Product">
          <h1 itemprop="name">Microdata Widget</h1>
          <div itemprop="brand" itemscope itemtype="https://schema.org/Brand">
            <span itemprop="name">Acme</span>
          </div>
          <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <meta itemprop="priceCurrency" content="USD">
            <span itemprop="price">29.99</span>
            <link itemprop="availability" href="https://schema.org/InStock">
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/microdata-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Microdata Widget"
    assert record["brand"] == "Acme"
    assert record["price"] == "29.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["_source"] == "microdata"


def test_sanitize_variant_row_keeps_option_label_titles_with_variant_signals() -> None:
    variant = {"title": "Large", "sku": "TRAIL-L", "price": "8.99"}

    assert _sanitize_variant_row(
        variant,
        identity_url="https://example.com/products/trail-mix",
    )
    assert variant["title"] == "Large"


def test_detail_image_family_requires_full_media_code_match() -> None:
    assert not _detail_image_matches_primary_family(
        "https://cdn.example.com/a999999/image.jpg",
        primary_image="https://cdn.example.com/a123456/image.jpg",
        title="",
    )


def test_extract_ecommerce_detail_from_opengraph() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="OG Widget">
        <meta property="og:type" content="product">
        <meta property="og:image" content="https://example.com/images/og-widget.jpg">
        <meta property="og:url" content="https://example.com/products/og-widget">
        <meta property="product:price:amount" content="19.99">
        <meta property="product:price:currency" content="USD">
        <meta property="product:availability" content="in stock">
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/og-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "OG Widget"
    assert record["price"] == "19.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["image_url"] == "https://example.com/images/og-widget.jpg"
    assert record["url"] == "https://example.com/products/og-widget"
    assert record["_source"] == "opengraph"


def test_extract_ecommerce_detail_keeps_page_url_when_opengraph_url_is_site_root() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Personal Blender">
        <meta property="og:type" content="product">
        <meta property="og:image" content="https://demo.spreecommerce.org/images/personal-blender.jpg">
        <meta property="og:url" content="https://demo.spreecommerce.org">
        <meta property="product:price:amount" content="149.99">
        <meta property="product:price:currency" content="USD">
        <meta property="product:availability" content="in stock">
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://demo.spreecommerce.org/us/en/products/personal-blender",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Personal Blender"
    assert record["url"] == "https://demo.spreecommerce.org/us/en/products/personal-blender"
    assert record["_source"] == "opengraph"


def test_extract_ecommerce_detail_ignores_placeholder_same_site_json_ld_url() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Biltmore Egyptian Collection Medium/Firm Support Pillow, White, King, Cotton",
          "url": "https://www.joinhoney.com/shop/undefined/p/undefined/",
          "priceCurrency": "USD"
        }
        </script>
      </head>
      <body>
        <h1>Biltmore Egyptian Collection Medium/Firm Support Pillow, White, King, Cotton</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.joinhoney.com/it/shop/belk/p/7367171691114074156_8bce8b8cc8892988fb42b26670ceaa09_7121c9215dcc3274f45b6a172cf8e8a8",
        "ecommerce_detail",
        max_records=1,
        requested_page_url="https://www.joinhoney.com/it/shop/belk/p/7367171691114074156_8bce8b8cc8892988fb42b26670ceaa09_7121c9215dcc3274f45b6a172cf8e8a8",
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Biltmore Egyptian Collection Medium/Firm Support Pillow, White, King, Cotton"
    assert rows[0]["url"] == "https://www.joinhoney.com/it/shop/belk/p/7367171691114074156_8bce8b8cc8892988fb42b26670ceaa09_7121c9215dcc3274f45b6a172cf8e8a8"


def test_extract_ecommerce_detail_ignores_review_json_ld_title_description_and_images() -> None:
    html = """
    <html>
      <head>
        <meta property="og:description" content="Weather resistant pack for daily commuting.">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Commuter Backpack",
          "image": "https://example.com/images/product.jpg",
          "sku": "CB-001"
        }
        </script>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Review",
          "name": "Best choice I ever made",
          "description": "normal",
          "image": "https://example.com/images/review-photo.jpg"
        }
        </script>
      </head>
      <body>
        <h1>Commuter Backpack</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/commuter-backpack",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["description"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Commuter Backpack"
    assert record["description"] == "Weather resistant pack for daily commuting."
    assert record["image_url"] == "https://example.com/images/product.jpg"


def test_extract_ecommerce_detail_ignores_nested_person_name_inside_product_json_ld() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Skechers Max Cushioning Elite",
          "brand": {
            "@type": "Brand",
            "name": "Skechers"
          },
          "manufacturer": {
            "@type": "Organization",
            "name": "Skechers",
            "founder": {
              "@type": "Person",
              "name": "Robert Greenberg"
            }
          },
          "offers": {
            "@type": "Offer",
            "priceCurrency": "USD",
            "price": "130.00",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <h1>Skechers Max Cushioning Elite</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.skechers.com/max-cushioning-elite/220000.html",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Skechers Max Cushioning Elite"
    assert record["brand"] == "Skechers"
    assert "Robert Greenberg" not in record.values()


def test_extract_ecommerce_detail_ignores_noisy_h1_and_uses_page_title() -> None:
    html = """
    <html>
      <head>
        <title>Widget Prime</title>
      </head>
      <body>
        <main>
          <h1>Save 20% With Code SPRING</h1>
          <div class="price">$19.99</div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"


def test_extract_ecommerce_detail_from_array_style_nuxt_payload() -> None:
    html = """
    <html>
      <head>
        <script id="__NUXT_DATA__" type="application/json">
          [
            {"data":1},
            ["Reactive",2],
            {"product":3},
            {"title":4,"vendor":5,"handle":6,"id":7,"product_type":8},
            "Nuxt Payload Widget",
            "Acme",
            "nuxt-payload-widget",
            4242,
            "Gadgets"
          ]
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/nuxt-payload-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Nuxt Payload Widget"
    assert record["brand"] == "Acme"
    assert record["vendor"] == "Acme"
    assert record["product_id"] == "4242"
    assert record["category"] == "Gadgets"
    assert record["_source"] == "js_state"


def test_extract_ecommerce_detail_from_nuxt_payload_with_self_referential_wrapper() -> None:
    html = """
    <html>
      <head>
        <script id="__NUXT_DATA__" type="application/json">
          [
            {"data":1,"meta":2},
            {"product":3},
            ["Reactive",2],
            {"title":4,"vendor":5,"handle":6,"id":7,"product_type":8},
            "Nuxt Payload Widget",
            "Acme",
            "nuxt-payload-widget",
            4242,
            "Gadgets"
          ]
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/nuxt-payload-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Nuxt Payload Widget"
    assert record["brand"] == "Acme"
    assert record["_source"] == "js_state"


def test_extract_ecommerce_detail_resolves_json_ld_graph_node_references() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@id": "#brand",
              "@type": "Brand",
              "name": "Acme"
            },
            {
              "@id": "#offer",
              "@type": "Offer",
              "price": "29.99",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            },
            {
              "@id": "#product",
              "@type": "Product",
              "name": "Graph Widget",
              "brand": {"@id": "#brand"},
              "offers": {"@id": "#offer"}
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/graph-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Graph Widget"
    assert record["brand"] == "Acme"
    assert record["price"] == "29.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["_source"] == "json_ld"


def test_extract_ecommerce_detail_prefers_json_ld_title_over_noisy_dom_h1() -> None:
    html = """
    <html>
      <head>
        <title>Products</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Graph Widget",
          "offers": {
            "@type": "Offer",
            "price": "29.99",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Products</h1>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/graph-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Graph Widget"
    assert record["_source"] == "json_ld"


def test_extract_ecommerce_detail_keeps_adapter_title_over_longer_dom_h1() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime Deluxe Mega SEO Edition With Free Shipping And Bonus Copy</h1>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=5,
        adapter_records=[{"title": "Widget Prime", "url": "https://example.com/products/widget-prime"}],
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Widget Prime"
    assert "SEO Edition" not in rows[0]["title"]


def test_extract_ecommerce_detail_resolves_top_level_json_ld_array_references() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        [
          {
            "@context": "https://schema.org",
            "@id": "#brand",
            "@type": "Brand",
            "name": "Acme"
          },
          {
            "@context": "https://schema.org",
            "@id": "#offer",
            "@type": "Offer",
            "price": "39.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          },
          {
            "@context": "https://schema.org",
            "@id": "#product",
            "@type": "Product",
            "name": "Array Widget",
            "brand": {"@id": "#brand"},
            "offers": [{"@id": "#offer"}]
          }
        ]
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/array-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Array Widget"
    assert record["brand"] == "Acme"
    assert record["price"] == "39.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["_source"] == "json_ld"


def test_extract_ecommerce_detail_flattens_json_ld_size_specifications() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Size Spec Widget",
          "size": {
            "@type": "SizeSpecification",
            "name": "XS",
            "sizeSystem": "https://schema.org/WearableSizeSystemUS",
            "sizeGroup": "https://schema.org/WearableSizeGroupRegular"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "name": "Size Spec Widget",
              "sku": "W-XS",
              "size": {
                "@type": "SizeSpecification",
                "name": "XS",
                "sizeSystem": "https://schema.org/WearableSizeSystemUS",
                "sizeGroup": "https://schema.org/WearableSizeGroupRegular"
              },
              "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "name": "Size Spec Widget",
              "sku": "W-XL",
              "size": {
                "@type": "SizeSpecification",
                "name": "XL",
                "sizeSystem": "https://schema.org/WearableSizeSystemUS",
                "sizeGroup": "https://schema.org/WearableSizeGroupRegular"
              },
              "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/OutOfStock"
              }
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/size-spec-widget",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["size"] == "XS"
    assert record["variant_axes"] == {"size": ["XS", "XL"]}
    assert record["selected_variant"]["size"] == "XS"
    assert record["selected_variant"]["availability"] == "in_stock"
    assert record["variants"][0]["size"] == "XS"
    assert record["variants"][1]["size"] == "XL"
    assert record["variants"][1]["availability"] == "out_of_stock"


def test_extract_ecommerce_detail_backfills_visible_display_price() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Men's Flex Pants | 327 | 34 | 30",
          "brand": {"@type": "Brand", "name": "Columbia"},
          "image": "https://example.com/flex-pants.jpg",
          "description": "Trail pants with stretch fabric."
        }
        </script>
      </head>
      <body>
        <h1>Men's Flex Pants | 327 | 34 | 30</h1>
        <div data-component-id="display-price">
          <span aria-label="current price $42.00">$42.00</span>
          <s aria-label="original price $60.00">$60.00</s>
        </div>
        <p>Trail pants with stretch fabric.</p>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/flex-pants",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["price"] == "42.00"
    assert rows[0]["original_price"] == "60.00"


def test_extract_ecommerce_detail_drops_low_signal_zero_display_price() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Classic Straight Jeans",
          "brand": {"@type": "Brand", "name": "Acme Denim"},
          "image": "https://example.com/jeans.jpg",
          "description": "Everyday jeans."
        }
        </script>
      </head>
      <body>
        <h1>Classic Straight Jeans</h1>
        <div data-component-id="display-price">
          <span aria-label="current price $0.00">$0.00</span>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/classic-straight-jeans",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert "price" not in record


def test_extract_ecommerce_detail_keeps_structured_zero_price_with_authoritative_offer() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Starter Guide Download",
          "sku": "GUIDE-001",
          "brand": {"@type": "Brand", "name": "Acme"},
          "offers": {
            "@type": "Offer",
            "priceCurrency": "USD",
            "price": "0.00",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <h1>Starter Guide Download</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/starter-guide-download",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "0.00"
    assert record["currency"] == "USD"
    assert record["_source"] == "json_ld"


def test_extract_ecommerce_detail_keeps_raw_json_zero_price() -> None:
    rows = extract_records(
        '{"title":"Free Sample","price":"0.00","currency":"USD","url":"https://example.com/products/free-sample"}',
        "https://example.com/products/free-sample",
        "ecommerce_detail",
        max_records=5,
        content_type="application/json",
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "0.00"
    assert record["currency"] == "USD"
    assert record["_source"] == "raw_json"


def test_extract_ecommerce_detail_rejects_collection_url_with_visible_tile_prices() -> None:
    html = """
    <html>
      <body>
        <h1>Short Sleeve</h1>
        <div data-component-id="product-tile">
          <a href="/p/trail-shirt-123.html">Trail Shirt</a>
          <div data-component-id="display-price">
            <span aria-label="current price $27.00">$27.00</span>
          </div>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/c/mens-short-sleeve-shirts/",
        "ecommerce_detail",
        max_records=5,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_myntra_adapter_extracts_detail_media_and_variants() -> None:
    html = """
    <html>
      <head>
        <title>Myntra</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Myntra",
          "image": "https://constant.myntassets.com/web/assets/img/logo_2021.png"
        }
        </script>
        <script>
          window.__myx = {
            "pdpData": {
              "id": 30721580,
              "name": "KALINI Floral Embroidered Kurta",
              "brand": "KALINI",
              "baseColour": "pink and white",
              "mrp": 3196,
              "selectedSeller": {"discountedPrice": 735},
              "media": {
                "albums": [
                  {
                    "name": "default",
                    "images": [
                      {"secureSrc": "https://assets.myntassets.com/assets/images/30721580/image-1.jpg"},
                      {"secureSrc": "https://assets.myntassets.com/assets/images/30721580/image-2.jpg"},
                      {"secureSrc": "https://assets.myntassets.com/assets/images/30721580/image-3.jpg"}
                    ]
                  }
                ]
              },
              "colours": [
                {"label": "pink and white", "url": "/products/30721580"},
                {"label": "peach", "url": "/products/29861551"}
              ],
              "sizes": [
                {
                  "skuId": 98872105,
                  "label": "S",
                  "available": true,
                  "selectedSeller": {"discountedPrice": 735, "availableCount": 8}
                },
                {
                  "skuId": 98872106,
                  "label": "M",
                  "available": false,
                  "selectedSeller": {"discountedPrice": 735, "availableCount": 0}
                }
              ]
            }
          };
        </script>
      </head>
      <body>
        <h1>KALINI Floral Embroidered Kurta</h1>
      </body>
    </html>
    """

    adapter = MyntraAdapter()
    result = await adapter.extract(
        "https://www.myntra.com/kurtas/kalini/example/30721580/buy",
        html,
        "ecommerce_detail",
    )

    rows = extract_records(
        html,
        "https://www.myntra.com/kurtas/kalini/example/30721580/buy",
        "ecommerce_detail",
        max_records=5,
        adapter_records=result.records,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "KALINI Floral Embroidered Kurta"
    assert record["image_url"] == "https://assets.myntassets.com/assets/images/30721580/image-1.jpg"
    assert record["additional_images"] == [
        "https://assets.myntassets.com/assets/images/30721580/image-2.jpg",
        "https://assets.myntassets.com/assets/images/30721580/image-3.jpg",
    ]
    assert record["available_sizes"] == "S, M"
    assert record["variant_count"] == 2
    assert record["selected_variant"]["size"] == "S"
    assert record["selected_variant"]["availability"] == "in_stock"


@pytest.mark.asyncio
async def test_myntra_adapter_allows_dom_description_fill_when_detail_payload_is_sparse() -> None:
    html = """
    <html>
      <head>
        <script>
          window.__myx = {
            "pdpData": {
              "id": 30721580,
              "name": "KALINI Floral Embroidered Kurta",
              "brand": "KALINI",
              "mrp": 3196,
              "selectedSeller": {"discountedPrice": 735},
              "media": {"albums": []},
              "sizes": []
            }
          };
        </script>
      </head>
      <body>
        <h1>KALINI Floral Embroidered Kurta</h1>
        <h2>Description</h2>
        <p>Soft cotton fabric with embroidered floral detailing.</p>
      </body>
    </html>
    """

    adapter = MyntraAdapter()
    result = await adapter.extract(
        "https://www.myntra.com/kurtas/kalini/example/30721580/buy",
        html,
        "ecommerce_detail",
    )

    rows = extract_records(
        html,
        "https://www.myntra.com/kurtas/kalini/example/30721580/buy",
        "ecommerce_detail",
        max_records=5,
        adapter_records=result.records,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "KALINI Floral Embroidered Kurta"
    assert (
        record["description"]
        == "Soft cotton fabric with embroidered floral detailing."
    )


def test_extract_ecommerce_detail_recovers_variant_axes_from_dom_controls_when_js_state_is_absent() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <label>
          Size
          <select name="size">
            <option value="">Choose size</option>
            <option value="s">S</option>
            <option value="m">M</option>
            <option value="l">L</option>
          </select>
        </label>
        <div class="color-swatch-group" aria-label="Color">
          <button type="button" aria-label="Black"></button>
          <button type="button" aria-label="Olive"></button>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["option1_name"] == "Color"
    assert record["option1_values"] == "Black, Olive"
    assert "option2_name" not in record
    assert "option2_values" not in record
    assert record["available_sizes"] == "S, M, L"
    assert record["variant_axes"] == {"size": ["S", "M", "L"], "color": ["Black", "Olive"]}
    assert record["variant_count"] == 6
    assert isinstance(record["variants"], list)
    assert len(record["variants"]) == 6
    assert record["variants"][0]["option_values"] == {"size": "S", "color": "Black"}
    assert "size" not in record["variants"][0]
    assert "color" not in record["variants"][0]


def test_extract_ecommerce_detail_recovers_radio_size_variants_with_stock_availability() -> None:
    html = """
    <html>
      <body>
        <h1>Bear Minimum Oversized T-Shirt</h1>
        <div class="product-varient-section">
          <p>Please select a size.</p>
          <ul class="sizelist">
            <li class="oval outstock">
              <input id="size_0_0" disabled type="radio" name="sub_prod_0" />
              <label for="size_0_0"><span>XXS</span></label>
              <section class="total-stock">0 Left</section>
            </li>
            <li class="oval selected">
              <input id="size_0_1" checked type="radio" name="sub_prod_0" />
              <label for="size_0_1"><span>XS</span></label>
              <section class="total-stock">17 Left</section>
            </li>
            <li class="oval">
              <input id="size_0_2" type="radio" name="sub_prod_0" />
              <label for="size_0_2"><span>S</span></label>
              <section class="total-stock">75 Left</section>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {"size": ["XXS", "XS", "S"]}
    assert record["available_sizes"] == "XXS, XS, S"
    assert record["availability"] == "in_stock"
    assert record["selected_variant"]["option_values"] == {"size": "XS"}
    assert record["selected_variant"]["availability"] == "in_stock"
    assert record["variants"][0]["availability"] == "out_of_stock"
    assert record["variants"][0]["stock_quantity"] == 0
    assert record["variants"][1]["availability"] == "in_stock"
    assert record["variants"][1]["stock_quantity"] == 17


def test_extract_ecommerce_detail_recovers_generic_dom_variant_axes_without_site_hardcoding() -> None:
    html = """
    <html>
      <body>
        <h1>MuscleBlaze Biozyme Performance Whey</h1>
        <fieldset class="weight-options">
          <legend>Weight</legend>
          <label><input checked type="radio" name="weight" value="4.4 Lb" />4.4 Lb</label>
          <label><input type="radio" name="weight" value="0.4 Lb" />0.4 Lb</label>
        </fieldset>
        <fieldset class="flavour-options">
          <legend>Flavour</legend>
          <label><input checked type="radio" name="flavour" value="Rich Chocolate" />Rich Chocolate</label>
          <label><input type="radio" name="flavour" value="Blue Tokai Coffee" />Blue Tokai Coffee</label>
        </fieldset>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/whey",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["option1_name"] == "Weight"
    assert record["option1_values"] == "4.4 Lb, 0.4 Lb"
    assert record["option2_name"] == "Flavour"
    assert record["option2_values"] == "Rich Chocolate, Blue Tokai Coffee"
    assert record["variant_axes"] == {
        "weight": ["4.4 Lb", "0.4 Lb"],
        "flavor": ["Rich Chocolate", "Blue Tokai Coffee"],
    }
    assert record["selected_variant"]["option_values"] == {
        "weight": "4.4 Lb",
        "flavor": "Rich Chocolate",
    }
    assert record["variant_count"] == 4


def test_extract_ecommerce_detail_recovers_variant_urls_from_dom_choice_links() -> None:
    html = """
    <html>
      <body>
        <h1>Norton Velvet Recliner</h1>
        <div class="color-selector" role="radiogroup" aria-label="Colour">
          <a href="/product/norton-velvet-recliner-in-grey-2207513.html">
            <button type="button" aria-label="Grey" class="selected"></button>
          </a>
          <a href="/product/norton-velvet-recliner-in-beige-2207512.html">
            <button type="button" aria-label="Beige"></button>
          </a>
          <a href="/product/norton-velvet-recliner-in-brown-2268528.html">
            <button type="button" aria-label="Brown"></button>
          </a>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.pepperfry.com/product/norton-velvet-recliner-in-grey-2207513.html",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {"color": ["Grey", "Beige", "Brown"]}
    assert record["variant_count"] == 3
    assert record["variants"][0]["url"] == (
        "https://www.pepperfry.com/product/norton-velvet-recliner-in-grey-2207513.html"
    )
    assert record["variants"][1]["url"] == (
        "https://www.pepperfry.com/product/norton-velvet-recliner-in-beige-2207512.html"
    )
    assert record["variants"][2]["url"] == (
        "https://www.pepperfry.com/product/norton-velvet-recliner-in-brown-2268528.html"
    )
    assert record["selected_variant"]["option_values"] == {"color": "Grey"}
    assert record["selected_variant"]["url"] == (
        "https://www.pepperfry.com/product/norton-velvet-recliner-in-grey-2207513.html"
    )


def test_extract_ecommerce_detail_recovers_variant_urls_from_js_state_option_mapping() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "data": {
                "productDetailData": {
                  "result": [
                    {
                      "data": {
                        "id": "140632",
                        "options": [
                          {
                            "id": "color",
                            "label": "Frame Color",
                            "optionList": [
                              {
                                "id": "14417_27737_23249_26121_23251",
                                "title": "Transparent Grey"
                              },
                              {
                                "id": "14417_27663_23245_26121_23252",
                                "title": "Transparent Pink"
                              }
                            ]
                          }
                        ],
                        "clarityOptionsMapping": [
                          {
                            "color": "14417_27737_23249_26121_23251",
                            "productId": "140632"
                          },
                          {
                            "color": "14417_27663_23245_26121_23252",
                            "productId": "208303"
                          }
                        ]
                      }
                    }
                  ]
                }
              }
            }
          }
        }
        </script>
      </head>
      <body>
        <h1>John Jacobs JJ S13313</h1>
        <div class="color-selector" role="radiogroup" aria-label="Frame Color">
          <button
            id="14417_27737_23249_26121_23251"
            type="button"
            aria-label="Transparent Grey"
            class="selected"
          ></button>
          <button
            id="14417_27663_23245_26121_23252"
            type="button"
            aria-label="Transparent Pink"
          ></button>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.lenskart.com/john-jacobs-jj-s13313-c1-sunglasses.html?productId=140632",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {
        "color": ["Transparent Grey", "Transparent Pink"]
    }
    assert record["variant_count"] == 2
    assert record["variants"][0]["variant_id"] == "140632"
    assert record["variants"][0]["url"] == (
        "https://www.lenskart.com/john-jacobs-jj-s13313-c1-sunglasses.html?productId=140632"
    )
    assert record["variants"][1]["variant_id"] == "208303"
    assert record["variants"][1]["url"] == (
        "https://www.lenskart.com/john-jacobs-jj-s13313-c1-sunglasses.html?productId=208303"
    )
    assert record["selected_variant"]["option_values"] == {"color": "Transparent Grey"}
    assert record["selected_variant"]["variant_id"] == "140632"


def test_extract_ecommerce_detail_skips_unnamed_dom_variant_groups() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <div class="swatch-group">
          <button type="button" aria-label="Black"></button>
          <button type="button" aria-label="Olive"></button>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert "option1_name" not in record
    assert "variant_axes" not in record
    assert "variants" not in record


def test_extract_ecommerce_detail_ignores_review_qa_controls_and_payment_icons() -> None:
    html = """
    <html>
      <body>
        <section class="secure-payment">
          <img src="https://cdn.example.com/assets/amex.svg" alt="American Express" />
          <img src="https://cdn.example.com/assets/paypal.svg" alt="PayPal" />
        </section>
        <main>
          <h1>7 Cup Food Processor</h1>
          <section class="product-gallery">
            <img src="https://cdn.example.com/products/food-processor.jpg?width=1200" alt="7 Cup Food Processor front view" />
          </section>
          <button aria-controls="specifications-panel">Specifications</button>
          <section id="specifications-panel">
            <p>7 cup work bowl with high, low, and pulse speed controls.</p>
          </section>
          <section class="product-questions">
            <div role="radiogroup" aria-label="1 Answers to Question: Will this shred cooked pork?">
              <button type="button">See KASA Review profile.</button>
              <button type="button">Content helpfulness</button>
              <button type="button">Report this answer by KASA Review as inappropriate.</button>
            </div>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/food-processor",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["specifications"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["image_url"] == "https://cdn.example.com/products/food-processor.jpg?width=1200"
    assert record["specifications"] == "7 cup work bowl with high, low, and pulse speed controls."
    assert "additional_images" not in record
    assert "option1_name" not in record
    assert "variant_axes" not in record
    assert "variants" not in record


def test_extract_ecommerce_detail_ignores_sort_filter_and_availability_controls_as_variants() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Performance Crew Socks</h1>
          <div class="price">$18.00</div>
          <label for="sort-by">Sort By</label>
          <select id="sort-by">
            <option>Featured</option>
            <option>Newest</option>
          </select>
          <label for="filter-by">Filter By</label>
          <select id="filter-by">
            <option>All Reviews</option>
            <option>Most Helpful</option>
          </select>
          <fieldset>
            <legend>Availability</legend>
            <label><input type="checkbox" checked> In Stock</label>
            <label><input type="checkbox"> Out of Stock</label>
          </fieldset>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/performance-crew-socks",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert "variant_axes" not in record
    assert "variants" not in record
    assert "selected_variant" not in record


def test_extract_ecommerce_detail_does_not_treat_etsy_report_radios_as_variants() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Black Popular And In Demand Unisex T-Shirt</h1>
          <div class="price">INR 2476.00</div>
          <div class="listing-report-modal">
            <ul>
              <li>
                <input id="flag_1" type="radio" name="flag_type_mnemonic" value="LISTING_GRT_T1" />
                <label for="flag_1">It's not handmade, vintage, or craft supplies</label>
              </li>
              <li>
                <input id="flag_2" type="radio" name="flag_type_mnemonic" value="OC_PORNOGRAPHY" />
                <label for="flag_2">It's pornographic</label>
              </li>
              <li>
                <input id="flag_3" type="radio" name="flag_type_mnemonic" value="LISTING_MINOR_SAFETY" />
                <label for="flag_3">It's a threat to minor safety</label>
              </li>
            </ul>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.etsy.com/listing/1210769675/example",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Black Popular And In Demand Unisex T-Shirt"
    assert record["price"] == "2476.00"
    assert "option1_name" not in record
    assert "variant_axes" not in record
    assert "selected_variant" not in record
    assert "variants" not in record


def test_extract_ecommerce_detail_does_not_treat_shipping_country_selector_as_variant_axis() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Custom Embroidered Mom Picture Sweatshirt</h1>
          <div class="price">INR 3121.00</div>
          <label for="variation-selector-1">Color</label>
          <select id="variation-selector-1">
            <option>Select an option</option>
            <option>Heather Dark Green</option>
            <option>White</option>
          </select>
          <label for="estimated-shipping-country">Country</label>
          <select
            id="estimated-shipping-country"
            name="estimated-shipping-country"
            aria-label="Choose country"
          >
            <option>----------</option>
            <option>Australia</option>
            <option>Canada</option>
            <option>France</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.etsy.com/listing/1210769675/example",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Custom Embroidered Mom Picture Sweatshirt"
    assert record["variant_axes"] == {"color": ["Heather Dark Green", "White"]}
    assert record["variant_count"] == 2
    assert "choose_country" not in record.get("variant_axes", {})
    assert "option2_name" not in record


def test_extract_ecommerce_detail_splits_style_and_size_from_compound_select_before_color() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Custom Sweatshirt</h1>
          <div class="price">$10.00</div>
          <label for="variation-selector-0">Style &amp; Size</label>
          <select id="variation-selector-0">
            <option value="">Select an option</option>
            <option value="1">Sweatshirt S ($10.00)</option>
            <option value="2">Sweatshirt M ($10.00)</option>
            <option value="3">Hoodie S ($12.00)</option>
            <option value="4">Hoodie M ($12.00)</option>
          </select>
          <label for="variation-selector-1">Colors</label>
          <select id="variation-selector-1">
            <option value="">Select an option</option>
            <option value="10">Black</option>
            <option value="11">White</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.etsy.com/listing/1210769675/example",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {
        "style": ["Sweatshirt", "Hoodie"],
        "size": ["S", "M"],
        "color": ["Black", "White"],
    }
    assert record["variant_count"] == 8
    assert record["option1_name"] == "Style"
    assert record["option1_values"] == "Sweatshirt, Hoodie"
    assert record["available_sizes"] == "S, M"
    assert record["selected_variant"]["option_values"] == {
        "style": "Sweatshirt",
        "size": "S",
        "color": "Black",
    }


def test_extract_ecommerce_detail_does_not_treat_question_radiogroup_as_size_variants() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>7 Cup Food Processor</h1>
          <section class="product-questions">
            <div role="radiogroup" aria-label="Will the 7 cup model chop cooked pork into a small size">
              <button type="button">Yes</button>
              <button type="button">No</button>
            </div>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/food-processor",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert "option1_name" not in record
    assert "variant_axes" not in record
    assert "variants" not in record


def test_extract_ecommerce_detail_keeps_stronger_js_state_variants_over_dom_fallback() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <label>
          Size
          <select name="size">
            <option value="">Choose size</option>
            <option value="s">S</option>
            <option value="m">M</option>
          </select>
        </label>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
        adapter_records=[
            {
                "variant_axes": {"size": ["S", "M", "L"]},
                "selected_variant": {"sku": "TRAIL-S", "option_values": {"size": "S"}},
            }
        ],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {"size": ["S", "M", "L"]}
    assert record["selected_variant"] == {
        "sku": "TRAIL-S",
        "size": "S",
        "option_values": {"size": "S"},
    }


def test_extract_ecommerce_detail_backfills_selected_variant_price_from_record_when_dom_variants_are_sparse() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Trail Runner</h1>
          <div class="price">$99.00</div>
          <label>
            Size
            <select name="size">
              <option value="s" selected>S</option>
              <option value="m">M</option>
            </select>
          </label>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "99.00"
    assert record["selected_variant"]["option_values"] == {"size": "S"}
    assert record["selected_variant"]["price"] == "99.00"


def test_extract_ecommerce_detail_prunes_single_value_marketing_axes_from_final_variant_record() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "id": "leggings-1",
                "title": "Everyday Seamless Leggings",
                "price": "58.00",
                "currency": "USD",
                "variants": [
                  {
                    "id": "leggings-s",
                    "available": true,
                    "selectedOptions": [
                      {"name": "Size", "value": "S"},
                      {"name": "Soft Fabric", "value": "Second-skin feel"},
                      {"name": "High Waisted", "value": "Snatched waist"}
                    ]
                  },
                  {
                    "id": "leggings-m",
                    "available": true,
                    "selectedOptions": [
                      {"name": "Size", "value": "M"},
                      {"name": "Soft Fabric", "value": "Second-skin feel"},
                      {"name": "High Waisted", "value": "Snatched waist"}
                    ]
                  }
                ]
              }
            }
          }
        }
        </script>
      </head>
      <body><main><h1>Everyday Seamless Leggings</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/everyday-seamless-leggings?variant=leggings-s",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {"size": ["S", "M"]}
    assert record["selected_variant"]["option_values"] == {"size": "S"}
    assert record["selected_variant"]["price"] == "58.00"


def test_extract_ecommerce_detail_backfills_missing_variant_price_from_ld_json_price() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Tree Runner",
          "offers": {
            "@type": "Offer",
            "price": "100",
            "priceCurrency": "USD"
          }
        }
        </script>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "id": "tree-runner-1",
                "title": "Tree Runner",
                "currency": "USD",
                "variants": [
                  {
                    "id": "tree-runner-8",
                    "available": true,
                    "selectedOptions": [
                      {"name": "Size", "value": "8"}
                    ]
                  },
                  {
                    "id": "tree-runner-9",
                    "available": true,
                    "selectedOptions": [
                      {"name": "Size", "value": "9"}
                    ]
                  }
                ]
              }
            }
          }
        }
        </script>
      </head>
      <body><main><h1>Tree Runner</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/tree-runner?variant=tree-runner-8",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "100.00"
    assert record["selected_variant"]["price"] == "100.00"
    assert record["variants"][0]["price"] == "100.00"


def test_extract_ecommerce_detail_ignores_generic_selector_axis_names_without_semantic_labels() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Camera Lens</h1>
          <div class="price">$399.00</div>
          <select id="variation_selector_0">
            <option value="">Choose</option>
            <option value="1">Leica L</option>
            <option value="2">Sony E</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/camera-lens",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert "variant_axes" not in record
    assert "selected_variant" not in record


def test_extract_ecommerce_detail_infers_unlabeled_select_variants_and_ignores_translate_widget() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>JARIX 1.5 ดีไซน์ใหม่ (จาริกซ์) VEPRO Foam</h1>
          <div class="price">฿1997.00</div>
          <select>
            <option>-- คลิกเพื่อเลือก สี --</option>
            <option>Sand Beige</option>
            <option>Sirrocco Nude</option>
            <option>Machine Grey</option>
            <option>1.5 Pearl White</option>
          </select>
          <select>
            <option>-- คลิกเพื่อเลือก ขนาด --</option>
            <option>EU-36</option>
            <option>EU-37</option>
            <option>EU-38</option>
          </select>
          <select aria-label="Language Translate Widget">
            <option>English</option>
            <option>Thai</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.shop.ving.run/product/jarix-1-5-vepro-foam/11000742818002471",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {
        "color": ["Sand Beige", "Sirrocco Nude", "Machine Grey", "1.5 Pearl White"],
        "size": ["EU-36", "EU-37", "EU-38"],
    }
    assert record["selected_variant"]["option_values"] == {
        "color": "Sand Beige",
        "size": "EU-36",
    }
    assert "language_translate_widget" not in str(record.get("variant_axes") or "")


def test_extract_ecommerce_detail_keeps_size_axis_when_bad_dom_label_says_color() -> None:
    html = """
    <html>
      <head>
        <script type="application/json">
        {
          "@type": "Product",
          "name": "Montecito 2.0 Hard Side Graphite Carry On Suitcase",
          "brand": "Ricardo Beverly Hills",
          "attributes": {
            "GTIN14": {"Id": "GTIN14", "Values": [{"Value": "00018982111874"}]},
            "AVAILABILITY": {"Id": "AVAILABILITY", "Values": [{"Value": "True"}]}
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Montecito 2.0 Hard Side Graphite Carry On Suitcase</h1>
          <div class="price">$136.00</div>
          <select aria-label="Color">
            <option>Graphite</option>
            <option>Hunter</option>
          </select>
          <select aria-label="Color">
            <option>21 in.</option>
            <option>25 in.</option>
            <option>29 in.</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.belk.com/p/ricardo-beverly-hills-montecito-2.0-hard-side-graphite-carry-on-suitcase/620017811756553.html",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record.get("sku") != "AVAILABILITY"
    assert record["variant_axes"] == {
        "color": ["Graphite", "Hunter"],
        "size": ["21 in.", "25 in.", "29 in."],
    }
    assert record["available_sizes"] == "21 in., 25 in., 29 in."
    assert record["selected_variant"]["option_values"] == {
        "color": "Graphite",
        "size": "21 in.",
    }
    assert "GTIN14" not in record.get("product_attributes", {})
    assert "AVAILABILITY" not in record.get("product_attributes", {})


def test_variant_option_availability_does_not_treat_disabled_control_as_out_of_stock() -> None:
    soup = BeautifulSoup(
        """
        <li class="size disabled selected">
          <input checked disabled type="radio" name="size" value="2" />
          <label>2</label>
        </li>
        """,
        "html.parser",
    )

    node = soup.select_one("input")
    label = soup.select_one("label")

    assert node is not None
    availability, stock_quantity = variant_option_availability(
        node=node,
        label_node=label,
    )

    assert availability is None
    assert stock_quantity is None


def test_extract_automobile_detail_ignores_irrelevant_video_json_ld_when_dom_title_exists() -> None:
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://www.autotrader.co.uk/cars/leasing/product/202402287036788" />
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "VideoObject",
          "name": "NEW Abarth 500E: The LOUDEST Electric Car! 4K",
          "description": "Promo video copy that is not the vehicle detail.",
          "thumbnailUrl": "https://m.atcdn.co.uk/a/media/w800/b75b88d781b647dcb7f8a802e7b6fa8e.jpg",
          "publisher": {
            "@type": "Organization",
            "name": "Auto Trader",
            "logo": {
              "@type": "ImageObject",
              "url": "https://m.atcdn.co.uk/static/media/logos/autotrader-logo.png"
            }
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Abarth 500e 42kWh Turismo Auto 3dr</h1>
          <p>Lease deal available now.</p>
          <img src="https://m.atcdn.co.uk/a/media/w800/b75b88d781b647dcb7f8a802e7b6fa8e.jpg" alt="Abarth 500e 42kWh Turismo Auto 3dr" />
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.autotrader.co.uk/cars/leasing/product/202402287036788",
        "automobile_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Abarth 500e 42kWh Turismo Auto 3dr"
    assert record["url"] == "https://www.autotrader.co.uk/cars/leasing/product/202402287036788"
    assert record["_source"] == "dom_h1"


def test_extract_automobile_detail_accepts_vehicle_json_ld_title_and_image() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Vehicle",
          "name": "Roadster GT",
          "image": "https://example.com/roadster.jpg",
          "url": "https://example.com/cars/roadster-gt"
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/cars/roadster-gt",
        "automobile_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Roadster GT"
    assert record["image_url"] == "https://example.com/roadster.jpg"
    assert record["url"] == "https://example.com/cars/roadster-gt"
    assert record["_source"] == "json_ld"


def test_extract_ecommerce_detail_allows_dom_variants_to_fill_weak_js_state_variants() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "id": 9001,
                "title": "Trail Runner",
                "variants": [
                  {
                    "id": "weak-1",
                    "sku": "TRAIL-WEAK"
                  }
                ]
              }
            }
          }
        }
        </script>
      </head>
      <body>
        <h1>Trail Runner</h1>
        <label>
          Size
          <select name="size">
            <option value="">Choose size</option>
            <option value="s">S</option>
            <option value="m">M</option>
          </select>
        </label>
        <div class="color-swatch-group" aria-label="Color">
          <button type="button" aria-label="Black"></button>
          <button type="button" aria-label="Olive"></button>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["variant_axes"] == {"size": ["S", "M"], "color": ["Black", "Olive"]}
    assert len(record["variants"]) == 4
    assert record["selected_variant"]["option_values"] == {"size": "S", "color": "Black"}


def test_extract_ecommerce_detail_merges_deduped_additional_images_across_js_state_and_dom() -> None:
    html = """
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "id": 9001,
                "title": "Trail Runner",
                "images": [
                  {"src": "https://cdn.example.com/products/trail-runner-1.jpg?width=400"},
                  {"src": "https://cdn.example.com/products/trail-runner-2.jpg?width=400"},
                  {"src": "https://cdn.example.com/assets/payment-badge.svg"}
                ],
                "variants": []
              }
            }
          }
        }
        </script>
      </head>
      <body>
        <main class="pdp-main">
          <h1>Trail Runner</h1>
          <section class="hero-media">
            <img src="https://cdn.example.com/products/trail-runner-1.jpg?width=1200" alt="Trail Runner front view" />
            <img src="https://cdn.example.com/products/trail-runner-2.jpg?width=1200" alt="Trail Runner side view" />
            <img src="https://cdn.example.com/products/trail-runner-3.jpg?width=1200" alt="Trail Runner outsole" />
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["image_url"] == "https://cdn.example.com/products/trail-runner-1.jpg?width=1200"
    assert record["additional_images"] == [
        "https://cdn.example.com/products/trail-runner-2.jpg?width=1200",
        "https://cdn.example.com/products/trail-runner-3.jpg?width=1200",
    ]


def test_extract_detail_keeps_dom_images_live_when_structured_data_only_has_primary_image() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trail Runner",
          "image": "https://cdn.example.com/products/trail-runner-1.jpg",
          "offers": {
            "price": "99.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Trail Runner</h1>
          <section class="gallery">
            <img src="https://cdn.example.com/products/trail-runner-1.jpg" alt="Trail Runner front view" />
            <a href="https://cdn.example.com/products/trail-runner-2.jpg">
              <img src="https://cdn.example.com/products/trail-runner-2-thumb.jpg" alt="Trail Runner side view" />
            </a>
            <a href="https://cdn.example.com/products/trail-runner-3.jpg">
              <img src="https://cdn.example.com/products/trail-runner-3-thumb.jpg" alt="Trail Runner outsole" />
            </a>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["_extraction_tiers"]["current"] == "dom"
    assert record["_extraction_tiers"]["early_exit"] is None
    assert record["additional_images"] == [
        "https://cdn.example.com/products/trail-runner-2-thumb.jpg",
        "https://cdn.example.com/products/trail-runner-3-thumb.jpg",
    ]


def test_extract_ecommerce_detail_prefers_full_dom_description_and_keeps_product_details_separate() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Headless + Omnichannel in a pill">
        <meta property="og:description" content="Launch new markets fast">
        <meta property="og:image" content="https://storefront1.saleor.cloud/media/thumbnails/products/saleor-headless-omnichannel-book_thumbnail_1024.webp">
      </head>
      <body>
        <main>
          <h1>Headless + Omnichannel in a pill</h1>
          <section>
            <h2>Description</h2>
            <p><strong>Launch new markets fast</strong></p>
            <p>Compact, actionable insights for modern retail.</p>
            <p>Headless + Omnichannel in a Pill explains how businesses can:</p>
            <ul>
              <li>Rapidly launch new markets</li>
              <li>Localize content efficiently</li>
              <li>Deliver seamless omnichannel experiences</li>
            </ul>
            <p>It also covers:</p>
            <ul>
              <li>Mobile, web, and in-store integration</li>
              <li>Emerging channels and technologies</li>
              <li>Headless architecture benefits</li>
            </ul>
          </section>
          <section>
            <button aria-controls="product-details-panel">Product Details</button>
            <section id="product-details-panel">
              <dl>
                <div><dt>Publisher</dt><dd>Digital Audio</dd></div>
                <div><dt>Description Summary</dt><dd>A fast-paced guide to launching new markets with headless and omnichannel strategies.</dd></div>
                <div><dt>Lector</dt><dd>Sophia Keller</dd></div>
                <div><dt>Release Date</dt><dd>2022-06-15</dd></div>
              </dl>
            </section>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://demo.saleor.io/default-channel/products/headless-omnichannel-commerce",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["description", "product_details"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["description"].startswith("Launch new markets fast Compact, actionable insights for modern retail.")
    assert "Rapidly launch new markets" in record["description"]
    assert "Headless architecture benefits" in record["description"]
    assert record["product_details"] == (
        "Publisher Digital Audio Description Summary A fast-paced guide to launching new markets "
        "with headless and omnichannel strategies. Lector Sophia Keller Release Date 2022-06-15"
    )
    assert "specifications" not in record


def test_extract_ecommerce_detail_keeps_dom_tier_live_for_product_details_without_requested_fields() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Headless + Omnichannel in a pill",
          "brand": {"name": "Audiobooks"},
          "description": "Launch new markets fast",
          "image": "https://storefront1.saleor.cloud/media/thumbnails/products/saleor-headless-omnichannel-book_thumbnail_1024.webp",
          "offers": {
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Headless + Omnichannel in a pill</h1>
          <section>
            <h2>Description</h2>
            <p><strong>Launch new markets fast</strong></p>
            <p>Compact, actionable insights for modern retail.</p>
            <p>Headless architecture benefits.</p>
          </section>
          <section>
            <button aria-controls="product-details-panel">Product Details</button>
            <section id="product-details-panel">
              <dl>
                <div><dt>Publisher</dt><dd>Digital Audio</dd></div>
                <div><dt>Description Summary</dt><dd>A fast-paced guide to launching new markets with headless and omnichannel strategies.</dd></div>
              </dl>
            </section>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://demo.saleor.io/default-channel/products/headless-omnichannel-commerce",
        "ecommerce_detail",
        max_records=5,
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert "Headless architecture benefits" in record["description"]
    assert record["product_details"] == (
        "Publisher Digital Audio Description Summary A fast-paced guide to launching new markets "
        "with headless and omnichannel strategies."
    )
    assert record["_extraction_tiers"]["current"] == "dom"
    assert record["_extraction_tiers"]["early_exit"] is None


def test_extract_ecommerce_detail_dedupes_next_image_proxy_duplicates() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Headless + Omnichannel in a pill">
        <meta property="og:image" content="https://storefront1.saleor.cloud/media/thumbnails/products/saleor-headless-omnichannel-book_thumbnail_1024.webp">
      </head>
      <body>
        <main>
          <h1>Headless + Omnichannel in a pill</h1>
          <section class="gallery">
            <img src="https://storefront1.saleor.cloud/media/thumbnails/products/saleor-headless-omnichannel-book_thumbnail_1024.webp" alt="Book cover">
            <img src="https://demo.saleor.io/_next/image?url=https%3A%2F%2Fstorefront1.saleor.cloud%2Fmedia%2Fthumbnails%2Fproducts%2Fsaleor-headless-omnichannel-book_thumbnail_1024.webp&w=1080&q=75" alt="Book cover transformed">
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://demo.saleor.io/default-channel/products/headless-omnichannel-commerce",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["image_url"] == (
        "https://storefront1.saleor.cloud/media/thumbnails/products/saleor-headless-omnichannel-book_thumbnail_1024.webp"
    )
    assert "additional_images" not in record


def test_extract_ecommerce_detail_keeps_real_description_when_dom_sections_only_see_tabs() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Airdopes Supreme Long Playback Earbuds">
        <meta property="og:description" content="Experience superior sound with boAt Airdopes Supreme — 50H playback, AI ENx, Cinematic Spatial Audio and BEAST Mode.">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Airdopes Supreme Long Playback Earbuds",
          "brand": {"name": "boAt"},
          "offers": {
            "price": "1399",
            "priceCurrency": "INR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Airdopes Supreme Long Playback Earbuds</h1>
          <div class="product-description">
            Experience superior sound with boAt Airdopes Supreme — 50H playback, AI ENx, Cinematic Spatial Audio and BEAST Mode.
          </div>
          <section>
            <h2>Description</h2>
            <div>
              <button>Description</button>
              <button>specifications</button>
              <button>Reviews (192)</button>
            </div>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.boat-lifestyle.com/products/airdopes-supreme-long-playback-earbuds",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["description"] == (
        "Experience superior sound with boAt Airdopes Supreme — 50H playback, AI ENx, "
        "Cinematic Spatial Audio and BEAST Mode."
    )
    assert "handle" not in record


def test_extract_ecommerce_detail_maps_anchor_hash_product_description_upstream() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Superman: Krypto The Superdog Oversized T-Shirts By DC Comics™",
          "description": "Shop for Superman: Crypto Men Oversized Fit T-shirts Online",
          "brand": {"name": "DC Comics™"},
          "offers": {
            "price": "899",
            "priceCurrency": "INR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Superman: Krypto The Superdog</h1>
          <div id="accordion">
            <div class="card">
              <div role="tab" id="headingOne" class="card-header">
                <h5 class="mb-0 accordianheading">
                  <a data-toggle="collapse" data-parent="#accordion" href="#collapseOne" aria-expanded="true" aria-controls="collapseOne">
                    Product Details
                  </a>
                </h5>
              </div>
              <div id="collapseOne" role="tabpanel" aria-labelledby="headingOne" class="collapse show">
                <div class="card-block">
                  <p><b>Material &amp; Care:</b><br>Premium Heavy Gauge Fabric<br>100% Cotton<br>Machine Wash</p>
                </div>
              </div>
            </div>
            <div class="card">
              <div role="tab" id="headingTwo" class="card-header">
                <h5 class="mb-0 accordianheading">
                  <a data-toggle="collapse" data-parent="#accordion" href="#collapseTwo" aria-expanded="false" aria-controls="collapseTwo">
                    Product Description
                  </a>
                </h5>
              </div>
              <div id="collapseTwo" role="tabpanel" aria-labelledby="headingTwo" class="collapse">
                <div class="card-block">
                  <p><b>Official Licensed Superman Oversized T-Shirt.</b></p>
                  <p>Shop for Superman: Krypto The Superdog Oversized T-Shirts at The Souled Store.</p>
                </div>
              </div>
            </div>
            <div class="card">
              <div role="tab" id="headingArtist" class="card-header">
                <h5 class="mb-0 accordianheading">
                  <a data-toggle="collapse" data-parent="#accordion" href="#collapseArtist" aria-expanded="false" aria-controls="collapseArtist">
                    Artist's Details
                  </a>
                </h5>
              </div>
              <div id="collapseArtist" role="tabpanel" aria-labelledby="headingArtist" class="collapse">
                <div class="card-block">
                  <p>Suit up with Justice League merchandise.</p>
                </div>
              </div>
            </div>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.thesouledstore.com/product/men-oversized-fit-superman-crypto?gte=1",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["description"] == (
        "Official Licensed Superman Oversized T-Shirt. "
        "Shop for Superman: Krypto The Superdog Oversized T-Shirts at The Souled Store."
    )
    assert record["product_details"] == (
        "Material & Care: Premium Heavy Gauge Fabric 100% Cotton Machine Wash"
    )
    assert record["_field_sources"]["description"] == ["json_ld", "dom_sections"]
    assert "dom_sections" in record["_field_sources"]["product_details"]


def test_extract_ecommerce_detail_filters_zara_copy_code_from_dom_variants() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Regular Fit Shirt</h1>
          <fieldset>
            <legend>Color</legend>
            <div class="product-detail-color-selector">
              <button type="button" aria-label="Black"></button>
              <button type="button" aria-label="Blue/White"></button>
              <button type="button" aria-label="White"></button>
              <button type="button" aria-label="Sky blue"></button>
              <button type="button" aria-label="Ecru / Blue"></button>
              <button type="button" aria-label="White / Sky blue"></button>
              <button type="button" aria-label="4493/144/800"></button>
            </div>
          </fieldset>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.zara.com/in/en/regular-fit-shirt-p04493144.html",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert str(record["option1_name"]).lower() == "color"
    assert "option2_name" not in record
    assert "4493/144/800" not in str(record.get("option1_values") or "")
    assert record["variant_axes"] == {
        "color": [
            "Black",
            "Blue/White",
            "White",
            "Sky blue",
            "Ecru / Blue",
            "White / Sky blue",
        ]
    }
    assert record["variant_count"] == 6
    assert record["selected_variant"]["option_values"]["color"] == "Black"


def test_extract_ecommerce_detail_maps_zara_composition_block_to_materials() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>CONTRAST RIBBED T-SHIRT WITH RUFFLES</h1>
          <div class="product-detail-description">
            <p>SLIM FIT - ROUND NECK - REGULAR LENGTH - SHORT SLEEVES</p>
          </div>
          <ul class="product-detail-actions product-detail-info__product-actions">
            <li class="product-detail-actions__action">
              <button class="product-detail-size-guide-action product-detail-actions__action-button">
                <span>Product Measurements</span>
              </button>
            </li>
            <li class="product-detail-actions__action product-detail-actions__clevercare">
              <button class="product-detail-actions__action-button">
                Composition, care &amp; origin
              </button>
            </li>
          </ul>
        </main>
        <div class="product-detail-view__secondary-content">
          <div class="product-detail-composition product-detail-view__detailed-composition">
            <ul>
              <li class="product-detail-composition__item product-detail-composition__part">
                <span class="product-detail-composition__part-name">OUTER SHELL</span>
                <ul>
                  <li class="product-detail-composition__item product-detail-composition__area">
                    <span class="product-detail-composition__part-name">MAIN FABRIC</span>
                    <ul><li>96% cotton</li><li>4% elastane</li></ul>
                  </li>
                  <li class="product-detail-composition__item product-detail-composition__area">
                    <span class="product-detail-composition__part-name">SECONDARY FABRIC</span>
                    <ul><li>100% cotton</li></ul>
                  </li>
                </ul>
              </li>
            </ul>
          </div>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.zara.com/in/en/contrast-ribbed-t-shirt-with-ruffles-p01044154.html",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["materials", "dimensions"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["materials"] == (
        "OUTER SHELL: MAIN FABRIC: 96% cotton; 4% elastane "
        "SECONDARY FABRIC: 100% cotton"
    )
    assert record["_field_sources"]["materials"] == ["dom_sections"]
    assert "dimensions" not in record


def test_extract_detail_keeps_requested_custom_dom_sections_live_past_structured_early_exit() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Darter Pro",
          "description": "Instant cushioning for everyday road runs.",
          "brand": {"name": "PUMA"},
          "image": "https://example.com/darter-pro.jpg",
          "offers": {
            "price": "99.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Darter Pro</h1>
          <section>
            <h2>Product Story</h2>
            <p>
              Hit new strides in the Darter Pro with a lightweight mesh upper and
              responsive cushioning built for daily miles.
            </p>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/darter-pro",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["product story"],
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert "lightweight mesh upper" in record["product_story"]
    assert record["_field_sources"]["product_story"] == ["dom_sections"]
    assert record["_extraction_tiers"]["current"] == "dom"
    assert record["_extraction_tiers"]["early_exit"] is None


def test_extract_detail_matches_exact_requested_section_label_without_collapsing_it() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Deviate Nitro Elite 4",
          "description": "Race-ready road running shoes.",
          "brand": {"name": "PUMA"},
          "offers": {
            "price": "230.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Deviate Nitro Elite 4</h1>
          <section>
            <h2>FEATURES &amp; BENEFITS</h2>
            <ul>
              <li>NITROFOAM Elite delivers lightweight responsiveness.</li>
              <li>PWRPLATE drives energy transfer through toe-off.</li>
            </ul>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://in.puma.com/in/en/pd/deviate-nitro-elite-4-run-club-mens-road-running-shoes/312907?swatch=01",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["Features & Benefits"],
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert "NITROFOAM Elite" in record["features_benefits"]
    assert "PWRPLATE drives energy transfer" in record["features_benefits"]
    assert record["_field_sources"]["features_benefits"] == ["dom_sections"]
    assert record["_extraction_tiers"]["current"] == "dom"
    assert record["_extraction_tiers"]["early_exit"] is None
    assert "benefits" not in record


def test_extract_detail_keeps_company_details_body_for_requested_custom_field() -> None:
    html = read_optional_artifact_text("artifacts/runs/8/pages/dc80e38b20c25b9b.html")

    rows = extract_records(
        html,
        "https://www.tradeindia.com/products/calcium-carbonate-powder-c10587655.html",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["company_details"],
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["company_details"].startswith(
        "Lyotex Lifesciences Private Limited is a reliable name in the manufacturing"
    )
    assert "Business Type Manufacturer, Supplier, Trading Company" in record["company_details"]
    assert "GST NO 27AAECL9071B1ZK" in record["company_details"]
    assert record["_field_sources"]["company_details"] == ["dom_sections"]


def test_extract_detail_keeps_slug_match_when_identity_codes_disagree() -> None:
    requested_url = "https://example.com/products/widget-premium?dwvar_ABCD1234_color=red"
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://example.com/products/widget-premium?dwvar_EFGH5678_color=red" />
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Premium",
          "description": "Widget Premium for everyday use.",
          "offers": {
            "price": "19.99",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <main><h1>Widget Premium</h1></main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/widget-premium?dwvar_EFGH5678_color=red",
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Widget Premium"


def test_extract_detail_rejects_same_url_identity_mismatch_from_carousel_product() -> None:
    requested_url = "https://www.target.com/p/apple-airpods-pro-2nd-generation-with-magsafe-case-usb-c/-/A-89791402"
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://www.target.com/p/apple-airpods-pro-2nd-generation-with-magsafe-case-usb-c/-/A-89791402">
        <meta property="og:title" content="Monster Jam Grave Digger Monster Truck">
        <meta property="og:image" content="https://target.scene7.com/truck.jpg">
      </head>
      <body><main><h1>Monster Jam Grave Digger Monster Truck</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        requested_url,
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert rows == []


def test_extract_detail_keeps_nike_record_when_canonical_drops_style_code() -> None:
    requested_url = "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111"
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr">
        <meta property="og:title" content="Nike Air Force 1 '07 Men's Shoes">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Nike Air Force 1 '07 Men's Shoes",
          "brand": {"@type": "Brand", "name": "Nike"},
          "sku": "CW2288-111",
          "mpn": "CW2288-111",
          "image": "https://static.nike.com/af1.png",
          "description": "Comfortable, durable and timeless.",
          "offers": {
            "@type": "Offer",
            "price": "115",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body><main><h1>Nike Air Force 1 '07 Men's Shoes</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        requested_url,
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Nike Air Force 1 '07 Men's Shoes"
    assert rows[0]["part_number"] == "CW2288-111"


def test_extract_detail_keeps_shopify_collection_detail_when_canonical_collapses_path() -> None:
    requested_url = "https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000"
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://kith.com/products/st40002-02000">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "SATISFY TheROCKER - Jet Black",
          "brand": {"@type": "Brand", "name": "SATISFY"},
          "sku": "13876003",
          "image": "https://kith.com/files/therocker.jpg",
          "description": "TheROCKER silhouette.",
          "offers": {
            "@type": "Offer",
            "price": "28200",
            "priceCurrency": "INR",
            "availability": "https://schema.org/OutOfStock"
          }
        }
        </script>
      </head>
      <body><main><h1>SATISFY TheROCKER - Jet Black</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        requested_url,
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "SATISFY TheROCKER - Jet Black"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["price"] == "282.00"


def test_extract_detail_corrects_host_currency_hint_integer_cent_price() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "SATISFY TheROCKER - Jet Black",
          "offers": {"price": "28200", "priceCurrency": "INR"}
        }
        </script>
      </head>
      <body><main><h1>SATISFY TheROCKER - Jet Black</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["currency"] == "USD"
    assert rows[0]["price"] == "282.00"


def test_extract_detail_drops_decimal_price_when_currency_conflicts_with_host_hint() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "EVGA GeForce RTX 3090",
          "offers": {"price": "260650.21", "priceCurrency": "INR"}
        }
        </script>
      </head>
      <body><main><h1>EVGA GeForce RTX 3090</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.amazon.com/dp/B08J5F3G18",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert "currency" not in rows[0]
    assert "price" not in rows[0]


def test_extract_detail_cleans_tracking_pixels_and_video_thumbs_from_images() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Yellow Pebbles Tile</h1>
          <section class="product-gallery">
            <img src="/images/yellow-pebbles.jpg" alt="Yellow Pebbles Tile">
            <img src="https://securemetrics.apple.com/b/ss/pixel.gif">
            <img src="https://www.facebook.com/tr?id=123">
            <img src="https://players.boltdns.net/thumb.jpg">
            <img src="https://site.qualtrics.com/intercept/pixel.png">
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.homedepot.com/p/yellow-pebbles/202515091",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["image_url"] == "https://www.homedepot.com/images/yellow-pebbles.jpg"
    assert "additional_images" not in rows[0]


def test_build_detail_record_runs_dom_tier_when_authoritative_record_has_no_images() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Cozyla 32&quot; 4K Calendar+ 2 (White)</h1>
          <img src="https://cdn.example.com/products/cozyla-calendar-main.jpg" />
        </main>
      </body>
    </html>
    """

    record = build_detail_record(
        html,
        "https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": 'Cozyla 32" 4K Calendar+ 2 (White)',
                "price": "989.99",
                "currency": "USD",
                "sku": "COCD8V543F0W",
            }
        ],
    )

    assert record["image_url"] == "https://cdn.example.com/products/cozyla-calendar-main.jpg"


def test_extract_ecommerce_detail_prunes_irrelevant_nested_related_products_from_structured_data() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Going Coconuts",
          "description": "Neutral coconut shades only.",
          "image": [
            "https://cdn.shopify.com/s/files/1/1338/0845/files/EyePalette-GoingCoconuts-Closed-PDP.jpg",
            "https://cdn.shopify.com/s/files/1/1338/0845/files/EyePalette-GoingCoconuts-MacroCrush.jpg"
          ],
          "offers": {"price": "14.00", "priceCurrency": "USD"},
          "relatedProducts": [
            {
              "@type": "Product",
              "name": "Pink Dreams",
              "url": "https://colourpop.com/products/pink-dreams-shadow-palette",
              "description": "Pink Dreams should not leak into the parent PDP.",
              "image": [
                "https://cdn.shopify.com/s/files/1/1338/0845/files/PPBlushCompact-ForeverYours-editorial-square_4980.jpg"
              ]
            }
          ]
        }
        </script>
      </head>
      <body><main><h1>Going Coconuts</h1></main></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://colourpop.com/products/going-coconuts-eyeshadow-palette",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["description"] == "Neutral coconut shades only."
    assert record["image_url"].endswith("EyePalette-GoingCoconuts-Closed-PDP.jpg")
    assert all("ForeverYours" not in image for image in record.get("additional_images", []))


def test_build_detail_record_sanitizes_cross_sell_images_placeholder_variants_and_legal_tail() -> None:
    html = "<html><body><main><h1>Black Seascape Stretch Bracelet</h1></main></body></html>"

    record = build_detail_record(
        html,
        "https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Black Seascape Stretch Bracelet",
                "description": (
                    "These sleek joggers feature our ABC technology. "
                    "Black Seascape Stretch Bracelet - Black - One Size. "
                    "These sleek joggers feature our ABC technology."
                ),
                "specifications": (
                    "Main material rubber. "
                    "EU product safety contact. "
                    "Customer service DECATHLON SE 4, boulevard de Mons 59665."
                ),
                "materials": "DECATHLON SE",
                "image_url": "http://www.puravidabracelets.com/cdn/shop/files/50907BLCK_1-min.jpg?v=1717477241",
                "additional_images": [
                    "https://cdn.shopify.com/s/files/1/0297/6313/files/50907BLCK_3-min.jpg?v=1717609172",
                    "https://www.puravidabracelets.com/cdn/shop/files/square-image_3_1.jpg?crop=center&height=600&v=1774914906&width=600",
                    "https://www.puravidabracelets.com/cdn/shop/products/Solid_Black_ed35d7f8-dc76-4e8a-9e2b-821126dbb895.jpg?v=1718918266&width=1200",
                    "https://www.macys.com/shop/product/1&fmt=webp",
                    "https://www.fashionnova.com/products/R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
                ],
                "variants": [
                    {
                        "price": "8.00",
                        "currency": "USD",
                        "option_values": {"size": "Please select"},
                    },
                    {
                        "price": "8.00",
                        "currency": "USD",
                        "option_values": {"toggle_color_swatches": "Swatch", "color": "Black"},
                    },
                ],
                "selected_variant": {
                    "price": "8.00",
                    "currency": "USD",
                    "option_values": {"size": "Please select"},
                },
                "product_attributes": {"title": "Default Title"},
            }
        ],
    )

    assert record["description"] == "These sleek joggers feature our ABC technology."
    assert record["specifications"] == "Main material rubber."
    assert "materials" not in record
    assert "product_attributes" not in record
    assert "50907BLCK" in record["image_url"]
    assert all(
        bad_token not in " ".join(record.get("additional_images", []))
        for bad_token in ("square-image", "Solid_Black", "macys.com/shop/product", "R0lGODlhAQAB")
    )
    assert record["variants"] == [
        {
            "price": "8.00",
            "currency": "USD",
            "color": "Black",
            "image_url": "http://www.puravidabracelets.com/cdn/shop/files/50907BLCK_1-min.jpg?v=1717477241",
            "option_values": {"color": "Black"},
        }
    ]
    assert record["selected_variant"] == {
        "price": "8.00",
        "currency": "USD",
        "color": "Black",
        "option_values": {"color": "Black"},
    }


def test_build_detail_record_drops_v6_widget_fulfillment_and_variant_scalar_noise() -> None:
    record = build_detail_record(
        "<html><body><main><h1>V6 Test Sneaker</h1></main></body></html>",
        "https://www.example.com/products/v6-test-sneaker",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "V6 Test Sneaker",
                "features": "1 2 3 4 5 6 7 8 9 10",
                "description": "Shipping, pickup, and delivery options available at checkout.",
                "size": "Size Guide Please select a size",
                "color": "Black",
            }
        ],
    )

    assert "features" not in record
    assert "description" not in record
    assert "size" not in record
    assert record["color"] == "Black"


def test_build_detail_record_drops_v6_generic_title_cross_product_text_and_ad_product_type() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Calvin Klein Bernard Lace-Up Oxfords</h1></main></body></html>",
        "https://www.macys.com/shop/product/calvin-klein-mens-bernard-lace-up-oxfords?ID=12345",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "MENS SHOES",
                "description": (
                    "The Hiser men's lace up oxford. "
                    "Calvin Klein Adeso dress shoe. "
                    "Club Room casual dress shoes. "
                    "Calvin Klein Bernard lace-up oxford."
                ),
                "product_type": "CriteoProductRail",
            }
        ],
    )

    assert record["title"] == "calvin klein mens bernard lace up oxfords"
    assert record["description"] == "Calvin Klein Bernard lace-up oxford."
    assert "product_type" not in record


def test_build_detail_record_drops_v6_target_fulfillment_description() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Apple AirPods Pro 2nd Generation</h1></main></body></html>",
        "https://www.target.com/p/apple-airpods-pro-2nd-generation-with-magsafe-case-usb-c/-/A-89791402",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Apple AirPods Pro 2nd Generation",
                "description": "Get it today with Target delivery, pickup, or shipping options available at checkout.",
            }
        ],
    )

    assert "description" not in record


def test_build_detail_record_normalizes_v6_cent_integer_prices_by_host_context() -> None:
    cases = [
        (
            "https://in.puma.com/in/en/pd/deviate-nitro-elite-4-run-club-mens-road-running-shoes/312907",
            "9999",
            "99.99",
            "INR",
        ),
        (
            "https://www.farfetch.com/shopping/men/designer-sneakers-item-123.aspx",
            "13880",
            "138.80",
            "USD",
        ),
        (
            "https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301",
            "3890",
            "38.90",
            "USD",
        ),
    ]

    for url, raw_price, expected_price, currency in cases:
        record = build_detail_record(
            "<html><body><main><h1>V6 Price Product</h1></main></body></html>",
            url,
            "ecommerce_detail",
            None,
            adapter_records=[
                {
                    "title": "V6 Price Product",
                    "price": raw_price,
                    "currency": currency,
                    "variants": [{"price": raw_price, "currency": currency, "option_values": {"size": "M"}}],
                }
            ],
        )

        assert record["price"] == expected_price
        assert record["variants"][0]["price"] == expected_price


def test_build_detail_record_rejects_broken_extensionless_transformed_image_urls() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Adidas Samba OG Shoes</h1></main></body></html>",
        "https://www.zappos.com/p/adidas-samba-og/product/12345",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Adidas Samba OG Shoes",
                "image_url": "https://m.media-amazon.com/images/I/adidas-samba-og-shoes._AC_UL1500_.jpg",
                "additional_images": [
                    "https://m.media-amazon.com/images/I/adidas-samba-og-shoes._AC_SR1224",
                    "https://m.media-amazon.com/images/I/adidas-samba-og-shoes-alt._AC_UL1500_.jpg",
                ],
            }
        ],
    )

    images = " ".join([record["image_url"], *record.get("additional_images", [])])
    assert "_AC_SR1224" not in images
    assert record["additional_images"] == [
        "https://m.media-amazon.com/images/I/adidas-samba-og-shoes-alt._AC_UL1500_.jpg"
    ]


def test_build_detail_record_rejects_cross_sell_images_by_filename_identity() -> None:
    html = "<html><body><main><h1>Nike Dunk Low Retro White Black Panda</h1></main></body></html>"

    record = build_detail_record(
        html,
        "https://stockx.com/nike-dunk-low-retro-white-black-2021",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Nike Dunk Low Retro White Black Panda",
                "image_url": "https://images.stockx.com/images/Nike-Dunk-Low-Retro-White-Black-2021-Product.jpg",
                "additional_images": [
                    "https://images.stockx.com/360/Nike-Dunk-Low-Retro-White-Black-2021/Images/Nike-Dunk-Low-Retro-White-Black-2021/Lv2/img01.jpg",
                    "https://images.stockx.com/images/Nike-Dunk-Low-Grey-Fog-Product.jpg",
                    "https://images.stockx.com/images/Nike-Dunk-Low-Court-Purple-Product.jpg",
                ],
            }
        ],
    )

    assert record["image_url"].endswith("Nike-Dunk-Low-Retro-White-Black-2021-Product.jpg")
    assert record["additional_images"] == [
        "https://images.stockx.com/360/Nike-Dunk-Low-Retro-White-Black-2021/Images/Nike-Dunk-Low-Retro-White-Black-2021/Lv2/img01.jpg"
    ]


def test_build_detail_record_rejects_same_cdn_different_product_image() -> None:
    record = build_detail_record(
        "<html><body><main><h1>RUSTIC COTTON T-SHIRT</h1></main></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "RUSTIC COTTON T-SHIRT",
                "image_url": "https://static.zara.net/assets/public/5326/04424306104-p/04424306104-p.jpg",
                "additional_images": [
                    "https://static.zara.net/assets/public/c95f/04424306104-a1/04424306104-a1.jpg",
                    "https://static.zara.net/assets/public/db43/07223038250-f1/07223038250-f1.jpg",
                ],
            }
        ],
    )

    assert record["additional_images"] == [
        "https://static.zara.net/assets/public/c95f/04424306104-a1/04424306104-a1.jpg"
    ]


def test_build_detail_record_formats_currency_prices_and_drops_bad_discounts() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Jogger</h1></main></body></html>",
        "https://shop.lululemon.com/p/men-joggers/Abc-Jogger/_/prod8530240",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Jogger",
                "price": "128.000000",
                "original_price": "128.000000",
                "currency": "USD",
                "discount_amount": "223",
                "discount_percentage": "225",
            }
        ],
    )

    assert record["price"] == "128.00"
    assert record["original_price"] == "128.00"
    assert "discount_amount" not in record
    assert "discount_percentage" not in record


def test_build_detail_record_backfills_low_signal_one_dollar_prices_from_dom() -> None:
    html = """
    <html><body><main>
      <h1>Stan Smith Shoes</h1>
      <div data-testid="price">$100.00</div>
    </main></body></html>
    """

    record = build_detail_record(
        html,
        "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Stan Smith Shoes",
                "price": "1",
                "currency": "USD",
                "variants": [
                    {
                        "variant_id": "M20324-9",
                        "sku": "M20324-9",
                        "price": "1",
                        "currency": "USD",
                        "option_values": {"size": "9"},
                    }
                ],
                "selected_variant": {
                    "variant_id": "M20324-9",
                    "sku": "M20324-9",
                    "price": "1",
                    "currency": "USD",
                    "option_values": {"size": "9"},
                },
            }
        ],
    )

    assert record["price"] == "100.00"
    assert record["variants"][0]["price"] == "100.00"
    assert record["selected_variant"]["price"] == "100.00"


def test_build_detail_record_replaces_uuid_sku_with_merch_code() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Nike Dunk Low Retro White Black Panda</h1></main></body></html>",
        "https://stockx.com/nike-dunk-low-retro-white-black-2021",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "sku": "5e6a1e57-1c7d-435a-82bd-5666a13560fe",
                "title": "Nike Dunk Low Retro White Black Panda",
                "product_details": "Style DD1391-100 Colorway White/Black Retail Price $115",
            }
        ],
    )

    assert record["sku"] == "DD1391-100"
    assert record["part_number"] == "DD1391-100"


def test_build_detail_record_drops_costco_shell_long_text_labels() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Sleep Number Ultimate 12&quot; Mattress</h1></main></body></html>",
        "https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": 'Sleep Number Ultimate 12" Mattress',
                "description": "Product Label",
                "specifications": "Specifications",
                "product_details": (
                    "Product Label Powered by Product details have been supplied by the manufacturer "
                    "and are hosted by a third party. View More"
                ),
            }
        ],
    )

    assert "description" not in record
    assert "specifications" not in record
    assert "product_details" not in record


def test_raw_json_detail_postprocess_drops_costco_shell_long_text_labels() -> None:
    rows = extract_records(
        """
        {
          "title": "Sleep Number Ultimate 12\\" Mattress",
          "description": "Product Label",
          "specifications": "Specifications",
          "product_details": "Product Label Powered by Product details have been supplied by the manufacturer View More",
          "price": "2299.99"
        }
        """,
        "https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1",
        "ecommerce_detail",
        max_records=5,
        content_type="application/json",
    )

    assert rows[0]["title"] == 'Sleep Number Ultimate 12" Mattress'
    assert "description" not in rows[0]
    assert "specifications" not in rows[0]
    assert "product_details" not in rows[0]


def test_extract_detail_infers_costco_textual_variant_sizes_from_titles() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Sleep Number Ultimate 12&quot; Mattress</h1></main></body></html>",
        "https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": 'Sleep Number Ultimate 12" Mattress',
                "variants": [
                    {
                        "sku": "1981348",
                        "title": 'Sleep Number Ultimate 12" Mattress Only, Queen',
                        "price": "2299.99",
                        "currency": "USD",
                        "availability": "in_stock",
                    },
                    {
                        "sku": "1981349",
                        "title": 'Sleep Number Ultimate 12" Mattress Only, King',
                        "price": "2299.99",
                        "currency": "USD",
                        "availability": "in_stock",
                    },
                ],
                "selected_variant": {
                    "sku": "1981348",
                    "title": 'Sleep Number Ultimate 12" Mattress Only, Queen',
                    "price": "2299.99",
                    "currency": "USD",
                    "availability": "in_stock",
                },
            }
        ],
    )

    assert record["variant_axes"] == {"size": ["Queen", "King"]}
    assert record["variants"][0]["option_values"] == {"size": "Queen"}
    assert record["variants"][1]["option_values"] == {"size": "King"}
    assert record["selected_variant"]["option_values"] == {"size": "Queen"}


def test_build_detail_record_strips_review_copy_from_color_scalar() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Blouson Twill Utility Jacket</h1></main></body></html>",
        "https://www.nordstrom.com/s/treasure-and-bond-blouson-twill-utility-jacket/8045019",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Blouson Twill Utility Jacket",
                "color": "Ivory Dove Customers say the fit runs true to size",
            }
        ],
    )

    assert record["color"] == "Ivory Dove"


def test_build_detail_record_drops_document_link_only_description() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Lansdale Sand Black Transitional Opal Glass Lantern Pendant Light</h1></main></body></html>",
        "https://www.lowes.com/pd/Minka-Lavery-Lansdale-Sand-Black-Transitional-Opal-Glass-Lantern-Pendant-Light/1001420790",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Lansdale Sand Black Transitional Opal Glass Lantern Pendant Light",
                "description": "Warranty Guide Prop65 Warning Label Use and Care Manual Installation Manual Dimensions Guide",
            }
        ],
    )

    assert "description" not in record


def test_build_detail_record_backfills_shared_variant_image_and_availability() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Brown Ruff Rider Leather Jacket</h1></main></body></html>",
        "https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Brown Ruff Rider Leather Jacket",
                "image_url": "https://res.cloudinary.com/ssenseweb/image/upload/item.jpg",
                "availability": "out_of_stock",
                "variants": [
                    {"size": "S", "price": "3890", "currency": "USD", "option_values": {"size": "S"}},
                    {"size": "M", "price": "3890", "currency": "USD", "option_values": {"size": "M"}},
                ],
            }
        ],
    )

    assert record["variants"][0]["image_url"] == "https://res.cloudinary.com/ssenseweb/image/upload/item.jpg"
    assert record["variants"][1]["availability"] == "out_of_stock"


def test_build_detail_record_repairs_nike_uuid_variant_skus_and_empty_prices() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Nike Air Force 1 '07 Men's Shoes</h1></main></body></html>",
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "sku": "CW2288-111",
                "title": "Nike Air Force 1 '07 Men's Shoes",
                "price": "115.00",
                "currency": "USD",
                "variants": [
                    {
                        "sku": "3c95b6cf-42e7-567c-8bf2-2ee9c9398f9d",
                        "variant_id": "3c95b6cf-42e7-567c-8bf2-2ee9c9398f9d",
                        "size": "6",
                        "price": "",
                        "currency": "USD",
                        "availability": "in_stock",
                        "option_values": {"size": "6"},
                    }
                ],
            }
        ],
    )

    assert record["variants"][0]["price"] == "115.00"
    assert "sku" not in record["variants"][0]
    assert record["sku"] == "CW2288-111"


def test_build_detail_record_repairs_shopify_cent_variant_prices_and_numeric_titles() -> None:
    record = build_detail_record(
        "<html><body><main><h1>SATISFY TheROCKER - Jet Black</h1></main></body></html>",
        "https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "SATISFY TheROCKER - Jet Black",
                "price": "282.00",
                "currency": "USD",
                "variants": [
                    {
                        "sku": "13875993",
                        "price": "28200",
                        "title": "3",
                        "currency": "USD",
                        "availability": "in_stock",
                        "option_values": {"size": "3"},
                    }
                ],
                "selected_variant": {
                    "sku": "13875993",
                    "price": "28200",
                    "title": "3",
                    "currency": "USD",
                    "availability": "in_stock",
                    "option_values": {"size": "3"},
                },
            }
        ],
    )

    assert record["variants"][0]["price"] == "282.00"
    assert record["variants"][0]["title"] == "SATISFY TheROCKER - Jet Black - 3"
    assert record["selected_variant"]["price"] == "282.00"
    assert record["selected_variant"]["title"] == "SATISFY TheROCKER - Jet Black"


def test_build_detail_record_replaces_ai_outfit_title_from_url() -> None:
    record = build_detail_record(
        "<html><body><main><h1>Your AI-Generated Outfit</h1></main></body></html>",
        "https://www.nordstrom.com/s/treasure-and-bond-blouson-twill-utility-jacket/8045019",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": "Your AI-Generated Outfit",
                "sku": "9656609",
                "price": "59.99",
            }
        ],
    )

    assert record["title"] == "Treasure And Bond Blouson Twill Utility Jacket"


def test_build_detail_record_drops_low_signal_numeric_only_variants() -> None:
    html = "<html><body><main><h1>Cozyla 32&quot; 4K Calendar+ 2 (White)</h1></main></body></html>"

    record = build_detail_record(
        html,
        "https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html",
        "ecommerce_detail",
        None,
        adapter_records=[
            {
                "title": 'Cozyla 32" 4K Calendar+ 2 (White)',
                "price": "989.99",
                "currency": "USD",
                "variants": [
                    {"price": "989.99", "currency": "USD", "option_values": {"size": "1"}},
                    {"price": "989.99", "currency": "USD", "option_values": {"size": "2"}},
                    {"price": "989.99", "currency": "USD", "option_values": {"size": "3"}},
                ],
                "selected_variant": {
                    "price": "989.99",
                    "currency": "USD",
                    "option_values": {"size": "1"},
                },
            }
        ],
    )

    assert "variants" not in record
    assert "variant_axes" not in record
    assert "selected_variant" not in record
    assert "size" not in record


def test_extract_detail_backfills_current_price_variants_and_strips_unavailable_suffixes() -> None:
    html = """
    <html>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "id": "stan-smith-1",
                "title": "Stan Smith Shoes",
                "brand": "adidas",
                "prices": {
                  "currency": "USD",
                  "currentPrice": 100
                },
                "options": [{"name": "Size"}],
                "variants": [
                  {
                    "id": "size-12.5",
                    "availability": "out_of_stock",
                    "selectedOptions": [
                      {"name": "Size", "value": "12.5 is currently unavailable."}
                    ]
                  },
                  {
                    "id": "size-13",
                    "availability": "in_stock",
                    "selectedOptions": [
                      {"name": "Size", "value": "13"}
                    ]
                  }
                ]
              }
            }
          }
        }
        </script>
      </body>
    </html>
    """

    record = extract_records(
        html,
        "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
        "ecommerce_detail",
        max_records=5,
    )[0]

    assert record["price"] == "100.00"
    assert record["variant_axes"] == {"size": ["12.5", "13"]}
    assert record["variants"][0]["price"] == "100.00"
    assert record["variants"][0]["option_values"] == {"size": "12.5"}


def test_extract_detail_rejects_asos_mixed_product_identity_record() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="ASOS DESIGN Curve lightweight pull on barrel pants in darkwash">
        <meta property="og:description" content="Shop the latest ASOS DESIGN Curve lightweight pull on barrel pants in darkwash trends with ASOS!">
      </head>
      <body>
        <main>
          <h1>ASOS DESIGN oversized t-shirt with lace hem in light blue</h1>
          <img src="https://images.asos-media.com/products/asos-design-oversized-t-shirt-with-lace-hem-in-light-blue/210817202-1-lightblue">
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.asos.com/us/prd/210397084/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210817202",
        "ecommerce_detail",
        max_records=5,
    )

    assert rows == []


def test_extract_detail_rejects_known_error_page_titles() -> None:
    html = """
    <html>
      <body>
        <main><h1>Oops, Something Went Wrong.</h1></main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.dickssportinggoods.com/p/birkenstock-womens-arizona-big-buckle-soft-footbed-sandals-25birwcasuwrznbgbcegp/25birwcasuwrznbgbcegp",
        "ecommerce_detail",
        max_records=5,
    )

    assert rows == []
