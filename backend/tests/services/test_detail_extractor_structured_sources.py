from __future__ import annotations

from pathlib import Path

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
    assert record["price"] == "100"
    assert record["selected_variant"]["price"] == "100"
    assert record["variants"][0]["price"] == "100"


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
    html = Path(
        "artifacts/runs/8/pages/dc80e38b20c25b9b.html"
    ).read_text(encoding="utf-8", errors="ignore")

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
