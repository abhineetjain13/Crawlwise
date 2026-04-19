from __future__ import annotations

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
