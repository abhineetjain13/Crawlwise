from __future__ import annotations

import pytest

from app.services.adapters.myntra import MyntraAdapter
from app.services.extraction_runtime import extract_records


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
    assert record["handle"] == "nuxt-payload-widget"
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
    assert record["handle"] == "nuxt-payload-widget"
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
    assert record["option1_name"] == "size"
    assert record["option1_values"] == "S, M, L"
    assert record["option2_name"] == "Color"
    assert record["option2_values"] == "Black, Olive"
    assert record["available_sizes"] == "S, M, L"
    assert record["variant_axes"] == {"size": ["S", "M", "L"], "color": ["Black", "Olive"]}
    assert record["variant_count"] == 6
    assert isinstance(record["variants"], list)
    assert len(record["variants"]) == 6
    assert record["variants"][0]["option_values"] == {"size": "S", "color": "Black"}


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
        "option_values": {"size": "S"},
    }
