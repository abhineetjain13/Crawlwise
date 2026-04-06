# Tests for listing page extraction.
from __future__ import annotations

import app.services.extract.listing_extractor as listing_extractor
from unittest.mock import patch

from app.services.extract.listing_extractor import extract_listing_records as _extract_listing_records_impl


def _sources(**kwargs) -> dict:
    return kwargs


def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    manifest: dict | None = None,
) -> list[dict]:
    sources = dict(manifest or {})
    page_sources = {
        "next_data": sources.get("next_data"),
        "hydrated_states": sources.get("_hydrated_states") or sources.get("hydrated_states") or [],
        "embedded_json": sources.get("embedded_json") or [],
        "open_graph": sources.get("open_graph") or {},
        "json_ld": sources.get("json_ld") or [],
        "microdata": sources.get("microdata") or [],
        "tables": sources.get("tables") or [],
    }
    if any(page_sources.values()):
        with patch(
            "app.services.extract.listing_extractor.parse_page_sources",
            return_value=page_sources,
        ):
            return _extract_listing_records_impl(
                html,
                surface,
                target_fields,
                page_url=page_url,
                max_records=max_records,
                xhr_payloads=sources.get("network_payloads") or [],
                adapter_records=sources.get("adapter_data") or [],
            )
    return _extract_listing_records_impl(
        html,
        surface,
        target_fields,
        page_url=page_url,
        max_records=max_records,
        xhr_payloads=sources.get("network_payloads") or [],
        adapter_records=sources.get("adapter_data") or [],
    )


def test_extract_product_cards():
    html = """
    <html><body>
    <div class="product-card">
        <h3><a href="/product/1">Widget A</a></h3>
        <span class="price">$10.00</span>
        <img src="https://img.example.com/a.jpg" />
    </div>
    <div class="product-card">
        <h3><a href="/product/2">Widget B</a></h3>
        <span class="price">$20.00</span>
        <img src="https://img.example.com/b.jpg" />
    </div>
    <div class="product-card">
        <h3><a href="/product/3">Widget C</a></h3>
        <span class="price">$30.00</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=100)
    assert len(records) == 3
    assert records[0]["title"] == "Widget A"
    assert records[1]["title"] == "Widget B"
    assert "price" in records[0]


def test_extract_listing_records_merges_structured_and_dom_card_fields_for_same_item():
    html = """
    <html><body>
    <div class="product-card">
        <h3><a href="/product/1">Widget A</a></h3>
        <span class="price">$10.00</span>
        <img src="https://img.example.com/a.jpg" />
    </div>
    <div class="product-card">
        <h3><a href="/product/2">Widget B</a></h3>
        <span class="price">$20.00</span>
        <img src="https://img.example.com/b.jpg" />
    </div>
    </body></html>
    """
    manifest = _sources(
        json_ld=[
            {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "item": {
                            "@type": "Product",
                            "name": "Widget A",
                            "url": "https://example.com/product/1",
                            "brand": {"name": "Acme"},
                            "description": "A richer structured description for widget A.",
                        },
                    },
                    {
                        "@type": "ListItem",
                        "item": {
                            "@type": "Product",
                            "name": "Widget B",
                            "url": "https://example.com/product/2",
                            "brand": {"name": "Acme"},
                            "description": "A richer structured description for widget B.",
                        },
                    },
                ],
            }
        ]
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/products",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["brand"] == "Acme"
    assert records[0]["price"] == "$10.00"
    assert records[0]["description"] == "A richer structured description for widget A."


def test_extract_listing_records_merges_adapter_rows_with_dom_job_cards():
    html = """
    <html><body>
      <div class="job-card">
        <a href="https://example.com/jobs/164066">
          <h3>Medical Surgical Registered Nurse / RN</h3>
          <div class="company">Emory Univ Hosp-Midtown</div>
          <div class="location">Atlanta, GA, 30308</div>
          <div class="salary">$52/hr</div>
        </a>
      </div>
      <div class="job-card">
        <a href="https://example.com/jobs/164065">
          <h3>Cardiovascular Step Down Registered Nurse / RN</h3>
          <div class="company">Emory Univ Hosp-Midtown</div>
          <div class="location">Atlanta, GA, 30308</div>
        </a>
      </div>
    </body></html>
    """
    manifest = _sources(
        adapter_data=[
            {
                "title": "Medical Surgical Registered Nurse / RN",
                "url": "https://example.com/jobs/164066",
                "job_id": "164066",
                "department": "Nursing",
            },
            {
                "title": "Cardiovascular Step Down Registered Nurse / RN",
                "url": "https://example.com/jobs/164065",
                "job_id": "164065",
                "department": "Nursing",
            },
        ]
    )

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://example.com/jobs",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["job_id"] == "164066"
    assert records[0]["department"] == "Nursing"
    assert records[0]["company"] == "Emory Univ Hosp-Midtown"
    assert records[0]["location"] == "Atlanta, GA, 30308"
    assert records[0]["salary"] == "$52/hr"
    assert "adapter" in records[0]["_source"]
    assert "listing_card" in records[0]["_source"]


def test_extract_listing_records_maps_generic_job_ids_without_emitting_sku():
    manifest = _sources(
        next_data={
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "items": [
                                            {
                                                "id": "f73230ff-586f-4775-9628-9a88bcde18b9",
                                                "name": "Chemical Operator",
                                                "url": "https://ats.rippling.com/inhance-technologies/jobs/f73230ff-586f-4775-9628-9a88bcde18b9",
                                                "department": {"name": "Operations"},
                                                "locations": [{"name": "Catoosa"}],
                                                "language": "en-US",
                                            },
                                            {
                                                "id": "1b410123-0089-4bde-9ab1-9acbe62ecf1b",
                                                "name": "Production Supervisor",
                                                "url": "https://ats.rippling.com/inhance-technologies/jobs/1b410123-0089-4bde-9ab1-9acbe62ecf1b",
                                                "department": {"name": "Operations"},
                                                "locations": [{"name": "Catoosa"}],
                                                "language": "en-US",
                                            },
                                        ]
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
    )

    records = extract_listing_records(
        "<html><body></body></html>",
        "job_listing",
        set(),
        page_url="https://ats.rippling.com/en-GB/inhance-technologies/jobs",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Chemical Operator"
    assert records[0]["job_id"] == "f73230ff-586f-4775-9628-9a88bcde18b9"
    assert records[0]["location"] == "Catoosa"
    assert records[0]["category"] == "Operations"
    assert "sku" not in records[0]


def test_normalize_generic_item_synthesizes_ultipro_job_links_from_payload_ids():
    record = listing_extractor._normalize_generic_item(
        {
            "Id": "06e69bb8-218d-449d-8864-5105c3f9960d",
            "Title": "Material Handler - WKND shift",
            "RequisitionNumber": "MATER002986",
            "PostedDate": "2026-03-26T21:54:52.59Z",
            "Locations": [
                {
                    "Address": {
                        "City": "Grafton",
                        "State": {"Code": "WI", "Name": "Wisconsin"},
                    }
                }
            ],
        },
        "job_listing",
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc",
    )

    assert record is not None
    assert record["job_id"] == "06e69bb8-218d-449d-8864-5105c3f9960d"
    assert record["url"] == (
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/OpportunityDetail"
        "?opportunityId=06e69bb8-218d-449d-8864-5105c3f9960d"
    )
    assert record["apply_url"] == record["url"]


def test_extract_listing_records_handles_main_entity_itemlist_manifest():
    manifest = _sources(
        json_ld=[
            {
                "@type": "WebPage",
                    "mainEntity": {
                        "@type": "ItemList",
                        "itemListElement": [
                            {"item": {"@type": "Product", "name": "Filter A", "url": "/p/filter-a", "image": "/img/a.jpg"}},
                            {"item": {"@type": "Product", "name": "Filter B", "url": "/p/filter-b", "image": "/img/b.jpg"}},
                        ],
                    },
                }
            ]
    )

    records = extract_listing_records(
        "<html><body></body></html>",
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=10,
        manifest=manifest,
    )

    assert [record["title"] for record in records] == ["Filter A", "Filter B"]
    assert records[0]["url"] == "https://example.com/p/filter-a"


def test_extract_listing_records_handles_graph_wrapped_json_ld_without_manifest():
    html = """
    <html><body>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "ItemList",
              "itemListElement": [
                {"item": {"@type": "Product", "name": "Mirror", "url": "/p/mirror", "image": "/img/mirror.jpg"}},
                {"item": {"@type": "Product", "name": "Lamp", "url": "/p/lamp", "image": "/img/lamp.jpg"}}
              ]
            }
          ]
        }
    </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=10,
    )

    assert [record["title"] for record in records] == ["Mirror", "Lamp"]
    assert records[1]["url"] == "https://example.com/p/lamp"


def test_extract_listing_records_merges_inline_object_arrays_with_dom_records_by_position():
    html = """
    <html><body>
    <script>
    window.__STATE__ = {
      "listListingDetails": [
        {"id": 1511949734, "name": "Clearance", "price": 150, "location": "Peterborough, Cambridgeshire"},
        {"id": 1511835211, "name": "Philips lumea prestige", "price": 110, "location": "Sandwell, West Midlands"}
      ]
    };
    </script>
    <div class="product-card">
        <a href="https://www.gumtree.com/p/other-home-appliances/clearance-/1511949734">
            <img src="https://img.example.com/a.jpg" />
        </a>
    </div>
    <div class="product-card">
        <a href="https://www.gumtree.com/p/ipl-hair-removal-appliances/philips-lumea-prestige/1511835211">
            <img src="https://img.example.com/b.jpg" />
        </a>
    </div>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.gumtree.com/for-sale/kitchen-appliances",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Clearance"
    assert records[0]["price"] == 150
    assert records[0]["location"] == "Peterborough, Cambridgeshire"
    assert records[0]["url"].endswith("/1511949734")
    assert records[1]["title"] == "Philips lumea prestige"


def test_extract_listing_records_handles_react_hydrate_props_payloads():
    html = """
    <html><body>
    <script>
    ReactDOM.hydrate(
      React.createElement(DesktopBrowse.Index, {
        "searchStore": {
          "works": [
            {
              "title": "Breath: The New Science of a Lost Art",
              "workUrl": "breath-the-new-science-of-a-lost-art_james-nestor",
              "buyNowPrice": 5.39,
              "listPrice": 28.0,
              "imageUrl": "https://img.example.com/a.jpg",
              "numberOfReviews": 12
            },
            {
              "title": "The Food Lab",
              "workUrl": "the-food-lab_j-kenji-lopez-alt",
              "buyNowPrice": 36.98,
              "imageUrl": "https://img.example.com/b.jpg",
              "numberOfReviews": 7
            }
          ]
        }
      }),
      document.getElementById("react_root")
    );
    </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.thriftbooks.com/browse/?b.search=science",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Breath: The New Science of a Lost Art"
    assert records[0]["url"] == "https://www.thriftbooks.com/breath-the-new-science-of-a-lost-art_james-nestor"
    assert records[0]["price"] == 5.39
    assert records[0]["original_price"] == 28.0
    assert records[0]["review_count"] == 12


def test_extract_listing_records_splits_paginated_html_and_dedupes_urls():
    html = """
    <!-- PAGE BREAK:1:https://example.com/products?page=1 -->
    <html><body>
    <div class="product-card">
        <h3><a href="/product/1">Widget A</a></h3>
        <span class="price">$10.00</span>
    </div>
    <div class="product-card">
        <h3><a href="/product/2">Widget B</a></h3>
        <span class="price">$20.00</span>
    </div>
    </body></html>
    <!-- PAGE BREAK:2:https://example.com/products?page=2 -->
    <html><body>
    <div class="product-card">
        <h3><a href="/product/2">Widget B</a></h3>
        <span class="price">$20.00</span>
    </div>
    <div class="product-card">
        <h3><a href="/product/3">Widget C</a></h3>
        <span class="price">$30.00</span>
    </div>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/products",
        max_records=10,
    )

    assert len(records) == 3
    assert [record["url"] for record in records] == [
        "https://example.com/product/1",
        "https://example.com/product/2",
        "https://example.com/product/3",
    ]


def test_extract_job_cards():
    html = """
    <html><body>
    <div class="job-card">
        <h3>Software Engineer</h3>
        <span class="company">Acme Corp</span>
        <span class="location">Remote</span>
    </div>
    <div class="job-card">
        <h3>Product Manager</h3>
        <span class="company">Widget Inc</span>
        <span class="location">NYC</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "job_listing", set(), max_records=100)
    assert len(records) == 2
    assert records[0]["title"] == "Software Engineer"
    assert records[0]["company"] == "Acme Corp"


def test_auto_detect_repeating_cards():
    """When no known selector matches, auto-detect repeating siblings."""
    html = """
    <html><body>
        <div class="results-grid">
            <div class="item-xyz">
                <h4><a href="/p/1"><img src="/img/1.jpg" />Item One</a></h4>
            </div>
            <div class="item-xyz">
                <h4><a href="/p/2"><img src="/img/2.jpg" />Item Two</a></h4>
            </div>
            <div class="item-xyz">
                <h4><a href="/p/3"><img src="/img/3.jpg" />Item Three</a></h4>
            </div>
        </div>
        </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=100)
    assert len(records) >= 3


def test_max_records_limit():
    cards = "".join(
        f'<div class="product-card"><h3>Product {i}</h3></div>'
        for i in range(50)
    )
    html = f"<html><body>{cards}</body></html>"
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=10)
    assert len(records) == 10


def test_empty_page():
    html = "<html><body><p>No products found</p></body></html>"
    records = extract_listing_records(html, "ecommerce_listing", set())
    assert records == []


def test_amazon_style_listing():
    html = """
    <html><body>
    <div data-component-type="s-search-result">
        <h2><a><span>Amazon Product 1</span></a></h2>
        <span class="a-price"><span class="a-offscreen">$19.99</span></span>
    </div>
    <div data-component-type="s-search-result">
        <h2><a><span>Amazon Product 2</span></a></h2>
        <span class="a-price"><span class="a-offscreen">$29.99</span></span>
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set())
    assert len(records) == 2
    assert records[0]["title"] == "Amazon Product 1"


def test_extract_hydrated_state_listing_records():
    html = "<html><body><h1>Fallback</h1></body></html>"
    manifest = _sources(
        json_ld=[],
        next_data=None,
        _hydrated_states=[
            {"products": [
                {"title": "Hydrated A", "url": "/p/a", "image_url": "/img/a.jpg"},
                {"title": "Hydrated B", "url": "/p/b", "image_url": "/img/b.jpg"},
            ]}
        ],
        network_payloads=[],
    )
    records = extract_listing_records(html, "ecommerce_listing", set(), page_url="https://example.com", manifest=manifest)
    assert len(records) == 2
    assert records[0]["title"] == "Hydrated A"
    assert records[1]["url"] == "https://example.com/p/b"


def test_extract_items_from_json_uses_configured_max_depth():
    payload = {"level1": {"level2": {"level3": {"level4": {"products": [
        {"title": "Deep A", "url": "/product/a", "price": "19.99"},
        {"title": "Deep B", "url": "/product/b", "price": "29.99"},
    ]}}}}}

    records = listing_extractor._extract_items_from_json(
        payload,
        "ecommerce_listing",
        "https://example.com",
        max_depth=5,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Deep A"


def test_extract_product_cards_captures_listing_metadata():
    html = """
    <html><body>
    <div class="product-card">
        <img src="https://img.example.com/a-1.jpg" />
        <img src="https://img.example.com/a-2.jpg" />
        <div>6 Colors, 4 Sizes</div>
        <h3><a href="/product/1">Accent Mirror</a></h3>
        <div>By Acme Home</div>
        <div>39&quot; H x 25.58&quot; W x 0.7&quot; D</div>
        <div class="rating" aria-label="Rated 4.8 out of 5 stars"></div>
        <div class="review-count">(891)</div>
        <span class="price">$61.99</span>
        <s>$79.99</s>
    </div>
    <div class="product-card">
        <img src="https://img.example.com/b-1.jpg" />
        <h3><a href="/product/2">Second Mirror</a></h3>
        <span class="price">$45.00</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), page_url="https://example.com", max_records=10)

    assert len(records) == 2
    assert records[0]["image_url"] == "https://img.example.com/a-1.jpg"
    assert records[0]["additional_images"] == "https://img.example.com/a-2.jpg"
    assert records[0]["color"] == "6 Colors, 4 Sizes"
    assert records[0]["size"] == "6 Colors, 4 Sizes"
    assert records[0]["dimensions"] == '39" H x 25.58" W x 0.7" D'
    assert records[0]["review_count"] == "(891)"
    assert records[0]["original_price"] == "$79.99"


def test_extract_product_cards_infers_currency_from_locale_and_reads_swatch_color():
    html = """
    <html><body>
    <div class="product-card">
        <button class="swatch" aria-label="Color: Black / White"></button>
        <h3><a href="/product/ua-1">UA Runner</a></h3>
        <span class="price">59.99</span>
    </div>
    <div class="product-card">
        <button class="swatch" data-color-name="Midnight Navy"></button>
        <h3><a href="/product/ua-2">UA Hoodie</a></h3>
        <span class="price">79.99</span>
    </div>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.underarmour.com/en-us/c/mens/",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["color"] == "Black / White"
    assert records[0]["currency"] == "USD"
    assert records[1]["color"] == "Midnight Navy"
    assert records[1]["currency"] == "USD"


def test_extract_listing_prefers_next_flight_records_over_breadcrumb_json_ld():
    html = """
    <html><body>
      <script type="application/ld+json">
      {"@type":"ItemList","itemListElement":[
        {"item":{"@id":"https://example.com/category/decor","name":"Decor"}},
        {"item":{"@id":"https://example.com/category/mirrors","name":"Mirrors"}}
      ]}
      </script>
      <script>
      self.__next_f.push([1,"1:{\\"displayName\\":\\"Arnott Arch Decorative Wall Mirror\\",\\"listingUrl\\":\\"https://example.com/pdp/arnott\\",\\"priceVariation\\":\\"SALE\\",\\"amount\\":\\"109.99\\",\\"averageRating\\":4.76,\\"totalCount\\":648,\\"name\\":\\"Charlton Home®\\",\\"__typename\\":\\"ManufacturerCuratedBrand\\"}"]);
      self.__next_f.push([1,"2:{\\"displayName\\":\\"Sabine Metal Rounded Rectangle Wall Mirror\\",\\"listingUrl\\":\\"https://example.com/pdp/sabine\\",\\"priceVariation\\":\\"SALE\\",\\"amount\\":\\"89.99\\",\\"averageRating\\":4.55,\\"totalCount\\":312,\\"name\\":\\"Refine\\",\\"__typename\\":\\"ManufacturerCuratedBrand\\"}"]);
      </script>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), page_url="https://example.com", max_records=10)
    records_by_url = {record["url"]: record for record in records}

    assert len(records) == 2
    assert records_by_url["https://example.com/pdp/arnott"]["title"] == "Arnott Arch Decorative Wall Mirror"
    assert records_by_url["https://example.com/pdp/arnott"]["brand"] == "Charlton Home®"
    assert records_by_url["https://example.com/pdp/arnott"]["price"] == "109.99"
    assert records_by_url["https://example.com/pdp/arnott"]["rating"] == "4.76"
    assert records_by_url["https://example.com/pdp/arnott"]["review_count"] == "648"


def test_extract_listing_rejects_weak_collection_json_ld_without_item_fields():
    html = """
    <html><body>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
        {"item":{"@id":"https://example.com/","name":"Home"}},
        {"item":{"@id":"https://example.com/hardware","name":"Hardware"}}
      ]}
      </script>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"CollectionPage","mainEntity":{
        "@type":"ItemList",
        "itemListElement":[
          {"@type":"ListItem","position":1,"url":"https://example.com/p/one"},
          {"@type":"ListItem","position":2,"url":"https://example.com/p/two"}
        ]
      }}
      </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=10,
    )

    assert records == []


def test_extract_listing_prefers_rich_product_array_over_category_links():
    html = "<html><body></body></html>"
    manifest = _sources(
        json_ld=[],
        next_data={
            "topCategories": [
                {"name": "lipstick", "link": "/makeup/lips/lipstick/c/249"},
                {"name": "highlighter", "link": "/makeup/face/face-illuminator/c/237"},
                {"name": "hair serum", "link": "/hair-care/hair/hair-serum/c/320"},
            ],
            "products": [
                {
                    "name": "Nykaa Cosmetics X Naagin Hot Sauce Plumping Lip Gloss",
                    "brandName": "Nykaa Cosmetics",
                    "price": 509,
                    "mrp": 599,
                    "imageUrl": "https://images.example.com/a.jpg",
                    "slug": "nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112",
                    "productId": "22062112",
                    "rating": 4.1,
                    "inStock": True,
                    "newTags": [{"title": "FEATURED"}],
                },
                {
                    "name": "Kay Beauty Hydra Creme Lipstick",
                    "brandName": "Kay Beauty",
                    "price": 989,
                    "mrp": 1099,
                    "imageUrl": "https://images.example.com/b.jpg",
                    "slug": "kay-beauty-signature-creme-lipstick-panache/p/16439255",
                    "productId": "16439255",
                    "rating": 4.5,
                    "inStock": True,
                    "newTags": [{"title": "FEATURED"}],
                },
            ],
        },
        _hydrated_states=[],
        network_payloads=[],
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.nykaa.com/makeup/c/12",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Nykaa Cosmetics X Naagin Hot Sauce Plumping Lip Gloss"
    assert records[0]["slug"] == "nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112"
    assert records[0]["url"] == "https://www.nykaa.com/nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112"
    assert records[0]["price"] == 509
    assert records[0]["brand"] == "Nykaa Cosmetics"


def test_match_dimensions_line_does_not_treat_random_d_suffix_as_dimension_signal():
    lines = ["Handcrafted", "Solid wood finish", "12 in wide"]

    assert listing_extractor._match_dimensions_line(lines) == "12 in wide"


def test_normalize_listing_value_only_promotes_true_product_short_paths():
    assert (
        listing_extractor._normalize_listing_value(
            "url",
            "p/22062112",
            page_url="https://www.nykaa.com/makeup/c/12",
        )
        == "https://www.nykaa.com/p/22062112"
    )
    assert (
        listing_extractor._normalize_listing_value(
            "url",
            "page/item",
            page_url="https://example.com/category/list",
        )
        == "https://example.com/category/page/item"
    )


def test_extract_listing_from_query_state_product_cards_and_drops_content_cards():
    html = "<html><body></body></html>"
    manifest = _sources(
        json_ld=[],
        next_data={
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "queryKey": ["KA_CUSTOM_PRODUCT_LISTING"],
                                "state": {
                                    "data": {
                                        "items": [
                                            {
                                                "__typename": "ProductCard",
                                                "name": "13-Cup Food Processor",
                                                "detailPageLink": {"href": "/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html"},
                                                "assets": [{"src": "https://images.example.com/p1.jpg", "type": "IMAGE"}],
                                                "price": {"currentValue": 179.99, "currency": "USD"},
                                            },
                                            {
                                                "__typename": "ProductCard",
                                                "name": "9 Cup Food Processor Plus",
                                                "detailPageLink": {"href": "/countertop-appliances/food-processors/processors/p.9-cup-food-processor-plus.KFP0919CU.html"},
                                                "assets": [{"src": "https://images.example.com/p2.jpg", "type": "IMAGE"}],
                                                "price": {"currentValue": 179.99, "currency": "USD"},
                                            },
                                            {
                                                "__typename": "ContentCard",
                                                "title": "<p>Promo banner</p>",
                                                "image": {"src": "https://images.example.com/promo.jpg", "type": "IMAGE"},
                                                "tooltip": {"content": "<p>Ends soon</p>"},
                                            },
                                        ]
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        },
        _hydrated_states=[],
        network_payloads=[],
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "13-Cup Food Processor"
    assert records[0]["url"] == "https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html"
    assert records[0]["price"] == "179.99"
    assert records[0]["currency"] == "USD"


def test_extract_listing_ignores_kitchenaid_style_variant_option_rows():
    html = "<html><body></body></html>"
    manifest = _sources(
        json_ld=[],
        next_data={
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "queryKey": ["KA_CUSTOM_PRODUCT_LISTING"],
                                "state": {
                                    "data": {
                                        "items": [
                                            {
                                                "__typename": "ProductCard",
                                                "name": "7 Quart Bowl-Lift Stand Mixer",
                                                "detailPageLink": {"href": "/countertop-appliances/stand-mixers/bowl-lift-stand-mixers/p.7-quart-bowl-lift-stand-mixer.KSM70SKXXBK.html"},
                                                "assets": [{"src": "https://images.example.com/mixer-main.jpg", "type": "IMAGE"}],
                                                "price": {"specialValue": 549.99, "currency": "USD"},
                                            },
                                            {
                                                "__typename": "ProductCard",
                                                "name": "5.5 Quart Bowl-Lift Stand Mixer",
                                                "detailPageLink": {"href": "/countertop-appliances/stand-mixers/bowl-lift-stand-mixers/p.5.5-quart-bowl-lift-stand-mixer.KSM55SXXXER.html"},
                                                "assets": [{"src": "https://images.example.com/mixer-two-main.jpg", "type": "IMAGE"}],
                                                "price": {"specialValue": 449.99, "currency": "USD"},
                                            },
                                            {
                                                "availability": "IN_STOCK",
                                                "skuId": "550",
                                                "commercialCode": "KSM70SKXXBK",
                                                "twelvenc": "KSM70SKXXBK",
                                                "label": "Cast Iron Black",
                                                "labelEn": "Cast Iron Black",
                                                "image": {"src": "https://www.kitchenaid.com/is/image/content/dam/business-unit/global-assets/color-swatches/Images/K2.png?wid=150&hei=150", "alt": "Cast Iron Black", "type": "IMAGE"},
                                                "detailPageLink": {"label": "7 Quart Bowl-Lift Stand Mixer", "href": "/countertop-appliances/stand-mixers/bowl-lift-stand-mixers/p.7-quart-bowl-lift-stand-mixer.KSM70SKXXBK.html"},
                                                "assets": [{"src": "https://images.example.com/mixer-gallery.jpg", "type": "IMAGE"}],
                                                "price": {"currentValue": 649.99, "specialValue": 549.99, "currency": "USD"},
                                            },
                                            {
                                                "availability": "IN_STOCK",
                                                "skuId": "551",
                                                "commercialCode": "KSM55SXXXER",
                                                "twelvenc": "KSM55SXXXER",
                                                "label": "Empire Red",
                                                "labelEn": "Empire Red",
                                                "image": {"src": "https://www.kitchenaid.com/is/image/content/dam/business-unit/global-assets/color-swatches/Images/ER.png?wid=150&hei=150", "alt": "Empire Red", "type": "IMAGE"},
                                                "detailPageLink": {"label": "5.5 Quart Bowl-Lift Stand Mixer", "href": "/countertop-appliances/stand-mixers/bowl-lift-stand-mixers/p.5.5-quart-bowl-lift-stand-mixer.KSM55SXXXER.html"},
                                                "assets": [{"src": "https://images.example.com/mixer-two-gallery.jpg", "type": "IMAGE"}],
                                                "price": {"currentValue": 499.99, "specialValue": 449.99, "currency": "USD"},
                                            },
                                        ]
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        },
        _hydrated_states=[],
        network_payloads=[],
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.kitchenaid.com/countertop-appliances/stand-mixers/bowl-lift-stand-mixers",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "7 Quart Bowl-Lift Stand Mixer"
    assert records[0]["image_url"] == "https://images.example.com/mixer-main.jpg"
    assert "color-swatches" not in records[0]["image_url"]


def test_extract_listing_prefers_sigma_product_search_results_over_nav_links():
    html = """
    <html><body>
      <nav>
        <ul>
          <li><a href="/products">Products</a></li>
          <li><a href="/applications">Applications</a></li>
          <li><a href="/support">Support</a></li>
        </ul>
      </nav>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "apolloState": {
            "ROOT_QUERY": {
              "getProductSearchResults({\\"input\\":{\\"group\\":\\"product\\"}})": {
                "__typename": "ProductSearchResults",
                "metadata": {"itemCount": 2, "page": 1, "perPage": 20, "numPages": 1},
                "items": [
                  {
                    "__typename": "Product",
                    "name": "Magnetic Screw Cap for Headspace Vials, 18 mm thread",
                    "productNumber": "SU860101",
                    "productKey": "SU860101",
                    "description": "PTFE/silicone septum, pkg of 100 ea",
                    "brand": {"name": "Supelco", "key": "SUPELCO"},
                    "images": [{"largeUrl": "/deepweb/assets/sigmaaldrich/product/images/a.jpg"}],
                    "attributes": [
                      {"label": "material", "values": ["PTFE/silicone"]},
                      {"label": "O.D. × H", "values": ["18 mm × 11 mm"]},
                      {"label": "fitting", "values": ["thread for 18 mm"]}
                    ]
                  },
                  {
                    "__typename": "Product",
                    "name": "Headspace vial, screw top, rounded bottom (vial only)",
                    "productNumber": "SU860097",
                    "productKey": "SU860097",
                    "description": "volume 20 mL, clear glass vial",
                    "brand": {"name": "Supelco", "key": "SUPELCO"},
                    "images": [{"largeUrl": "/deepweb/assets/sigmaaldrich/product/images/b.jpg"}],
                    "attributes": [
                      {"label": "material", "values": ["clear glass"]},
                      {"label": "O.D. × H", "values": ["22.5 mm × 75.5 mm"]}
                    ]
                  }
                ]
              }
            }
          }
        }
      }
      </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.sigmaaldrich.com/IN/en/products/analytical-chemistry/analytical-chromatography/analytical-vials",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Magnetic Screw Cap for Headspace Vials, 18 mm thread"
    assert records[0]["sku"] == "SU860101"
    assert records[0]["brand"] == "Supelco"
    assert records[0]["url"] == "https://www.sigmaaldrich.com/IN/en/product/supelco/su860101"
    assert records[0]["materials"] == "PTFE/silicone"
    assert "O.D. × H: 18 mm × 11 mm" in records[0]["dimensions"]


def test_is_meaningful_listing_record_keeps_priced_record_without_url():
    record = {
        "title": "Trail Runner",
        "image_url": "https://cdn.example.com/shoe.jpg",
        "price": "$89.99",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is True


def test_is_meaningful_listing_record_drops_title_and_image_only_record_without_url():
    record = {
        "title": "Promo banner",
        "image_url": "https://cdn.example.com/promo.jpg",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is False


def test_is_meaningful_listing_record_drops_job_like_nav_link_without_title_or_salary():
    record = {
        "url": "https://www.higheredjobs.com/search/",
        "company": "Job Seekers",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is False


def test_extract_card_images_skips_swatch_and_icon_images():
    html = """
    <div class="product-card">
        <div class="swatch-list">
            <button aria-label="Color Blue">
                <img src="/images/swatch-blue.jpg" />
            </button>
        </div>
        <img src="/images/logo-badge.png" />
        <img src="/images/product-main.jpg" />
        <img src="/images/product-alt.jpg" />
    </div>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    images = listing_extractor._extract_card_images(
        soup.select_one(".product-card"),
        "https://example.com/category",
    )

    assert images == [
        "https://example.com/images/product-main.jpg",
        "https://example.com/images/product-alt.jpg",
    ]


def test_extract_color_label_from_node_skips_action_buttons():
    html = '<button aria-label="Add to cart"></button>'
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    assert listing_extractor._extract_color_label_from_node(soup.button) == ""


def test_extract_color_label_from_node_skips_fitment_copy():
    html = '<button><span>Check</span> if this fits your vehicle.</button>'
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    assert listing_extractor._extract_color_label_from_node(soup.button) == ""


def test_extract_product_cards_read_identifiers_and_skip_fitment_icons():
    html = """
    <html><body>
    <ul>
      <li class="product-card">
        <img src="https://images.example.com/filter-main.jpg" />
        <div data-testid="product-part-number"><span>Part #</span><span> S6607XL</span></div>
        <div data-testid="product-sku-number"><span>SKU #</span><span> 663653</span></div>
        <button><img src="/images/vehicle-new.svg" />Check if this fits your vehicle.</button>
        <h3><a href="/p/filter-1">STP Extended Life Engine Oil Filter S6607XL</a></h3>
        <span class="price">$10.49</span>
      </li>
      <li class="product-card">
        <img src="https://images.example.com/filter-two.jpg" />
        <div data-testid="product-part-number"><span>Part #</span><span> S9972XL</span></div>
        <div data-testid="product-sku-number"><span>SKU #</span><span> 663650</span></div>
        <h3><a href="/p/filter-2">STP Extended Life Engine Oil Filter S9972XL</a></h3>
        <span class="price">$16.99</span>
      </li>
    </ul>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.autozone.com/filters-and-pcv/oil-filter",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["part_number"] == "S6607XL"
    assert records[0]["sku"] == "663653"
    assert "color" not in records[0]
    assert "additional_images" not in records[0]


def test_extract_listing_ignores_stringified_url_lists_from_inline_arrays():
    html = """
    <html><body>
      <script>
      window.__STATE__ = {
        "productResults": [
          {
            "title": "Electrical & Lighting",
            "href": [
              {"title": "Electrical & Lighting", "href": "/parts/electrical-and-lighting"},
              {"title": "Brakes & Traction Control", "href": "/parts/brakes-and-traction-control"}
            ]
          },
          {
            "title": "Collision, Body Parts and Hardware",
            "href": [
              {"title": "Collision, Body Parts and Hardware", "href": "/parts/collision-body-parts-and-hardware"},
              {"title": "Filters and PCV", "href": "/parts/filters-and-pcv"}
            ]
          }
        ]
      };
      </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.autozone.com/filters-and-pcv/oil-filter",
        max_records=10,
    )

    assert records == []


def test_extract_listing_records_ignores_filter_option_inline_arrays():
    html = """
    <html><body>
    <script>
    window.__FILTERS__ = {
      "securityClearance": [
        {"Name": "Not Required", "Value": "0", "Selected": false, "Tooltip": "", "Count": 0, "Sort": null, "ShowIcon": false, "Description": null, "DisplayName": null, "FilterType": null},
        {"Name": "Confidential", "Value": "1", "Selected": false, "Tooltip": "", "Count": 0, "Sort": null, "ShowIcon": false, "Description": null, "DisplayName": null, "FilterType": null}
      ]
    };
    </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://www.usajobs.gov/search/results/?k=software%20engineer&p=1",
        max_records=10,
    )

    assert records == []


def test_is_meaningful_listing_record_rejects_numeric_titles_and_filter_counts():
    assert listing_extractor._is_meaningful_listing_record({"title": 1, "price": 0}) is False
    assert listing_extractor._is_meaningful_listing_record({"title": "(1353)", "url": ""}) is False


def test_is_meaningful_listing_record_keeps_numeric_title_with_price_or_image():
    assert listing_extractor._is_meaningful_listing_record({"title": "2024", "price": "$199"}) is True
    assert (
        listing_extractor._is_meaningful_listing_record(
            {
                "title": "911",
                "image_url": "https://cdn.example.com/911.jpg",
                "url": "https://example.com/product/911",
            }
        )
        is True
    )


def test_is_meaningful_listing_record_rejects_title_only_job_fragment():
    assert (
        listing_extractor._is_meaningful_listing_record(
            {
                "title": "FeaturedOpportunities",
            }
        )
        is False
    )


def test_is_meaningful_listing_record_rejects_category_hub_url_with_only_visual_fields():
    record = {
        "title": "Air Filters",
        "image_url": "https://cdn.example.com/filter.jpg",
        "url": "https://example.com/collections/air-filters",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is False


def test_is_meaningful_listing_record_rejects_weak_hub_row_with_publication_date_only():
    record = {
        "title": "Default PLP",
        "url": "https://example.com/deals/",
        "publication_date": "2024-07-10T15:43:06.029Z",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is False


def test_is_meaningful_listing_record_keeps_detail_like_url_with_only_visual_fields():
    record = {
        "title": "Cabin Air Filter",
        "image_url": "https://cdn.example.com/filter.jpg",
        "url": "https://example.com/product/cabin-air-filter-123",
    }

    assert listing_extractor._is_meaningful_listing_record(record) is True


def test_extract_listing_records_handles_article_cards_inside_testid_grid():
    html = """
    <html><body>
      <div data-testid="grid-view-products">
        <article>
          <img src="https://cdn.example.com/a.jpg" />
          <div>Genuine Steam Deck Part</div>
          <a href="/products/steam-deck-ac-adapter-us"><h3>Steam Deck AC Adapter</h3></a>
          <span>221</span>
          <span>$34.99</span>
        </article>
        <article>
          <img src="https://cdn.example.com/b.jpg" />
          <div>Nintendo Part</div>
          <a href="/products/nintendo-switch-console-battery"><h3>Nintendo Switch Console Battery</h3></a>
          <span>413</span>
          <span>$39.99</span>
        </article>
      </div>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.ifixit.com/Parts",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Steam Deck AC Adapter"
    assert records[0]["url"] == "https://www.ifixit.com/products/steam-deck-ac-adapter-us"


def test_extract_listing_records_uses_usajobs_network_payload_aliases():
    html = "<html><body></body></html>"
    manifest = _sources(
        network_payloads=[
            {
                "url": "https://www.usajobs.gov/Search/ExecuteSearch",
                "body": {
                    "Jobs": [
                        {
                            "Title": "Software Engineer II",
                            "Agency": "House of Representatives",
                            "Department": "Legislative Branch",
                            "SalaryDisplay": "Starting at $108,763 Per year (HS )",
                            "Location": "Washington, District of Columbia",
                            "PositionURI": "https://www.usajobs.gov/job/863502700",
                        },
                        {
                            "Title": "Computer Engineer",
                            "Agency": "Air Force Materiel Command",
                            "Department": "Department of the Air Force",
                            "SalaryDisplay": "Starting at $89,508 Per year (NH 3)",
                            "Location": "Multiple Locations",
                            "PositionURI": "https://www.usajobs.gov/job/863855200",
                        },
                    ]
                },
            }
        ]
    )

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://www.usajobs.gov/search/results/?k=software%20engineer&p=1",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Software Engineer II"
    assert records[0]["company"] == "House of Representatives"
    assert records[0]["category"] == "Legislative Branch"
    assert records[0]["salary"] == "Starting at $108,763 Per year (HS )"
    assert records[0]["url"] == "https://www.usajobs.gov/job/863502700"


def test_extract_from_card_infers_dice_job_fields():
    html = """
    <div data-testid="job-card">
      <a data-testid="job-search-job-card-link" href="https://www.dice.com/job-detail/abc123"></a>
      <div class="header">
        <span class="logo">
          <a href="/company-profile/example-company"><p>Example Company</p></a>
        </span>
      </div>
      <div class="content" aria-label="Details for Data Engineer position" role="main">
        <div class="self-stretch">
          <a data-testid="job-search-job-detail-link" aria-label="Data Engineer" href="https://www.dice.com/job-detail/abc123">Data Engineer</a>
          <span>
            <div>
              <p>Des Moines, Iowa</p>
            </div>
            <div><p>Yesterday</p></div>
          </span>
          <p>USD 80,001.00 - 120,000.00 per year</p>
          <div><p>Full-Time</p></div>
        </div>
      </div>
    </div>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    record = listing_extractor._extract_from_card(
        soup.select_one("[data-testid='job-card']"),
        set(),
        "job_listing",
        "https://www.dice.com/jobs",
    )

    assert record["title"] == "Data Engineer"
    assert record["company"] == "Example Company"
    assert record["location"] == "Des Moines, Iowa"
    assert record["salary"] == "USD 80,001.00 - 120,000.00 per year"
    assert record["job_type"] == "Full-Time"
    assert record["posted_date"] == "Yesterday"
    assert record["apply_url"] == "https://www.dice.com/job-detail/abc123"


def test_extract_from_card_handles_idealist_job_card():
    html = """
    <div data-qa-id="search-result">
      <div>
        <a href="/en/nonprofit-job/123-example-role">
          <div>
            <h3><span data-qa-id="search-result-link">Executive Operations</span></h3>
            <h4><div>Ground Zero</div></h4>
          </div>
          <div>
            <span><span>On-site</span></span>
            <span><span>Rajasthan, India</span></span>
            <span><span>Full Time</span></span>
            <span><span>INR 500,000 - 600,000 / year</span></span>
          </div>
          <div><span>Posted 16 days ago</span></div>
        </a>
      </div>
    </div>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    record = listing_extractor._extract_from_card(
        soup.select_one("[data-qa-id='search-result']"),
        set(),
        "job_listing",
        "https://www.idealist.org/en/jobs",
    )

    assert record["title"] == "Executive Operations"
    assert record["company"] == "Ground Zero"
    assert record["location"] == "On-site"
    assert record["job_type"] == "Full Time"
    assert record["salary"] == "INR 500,000 - 600,000 / year"
    assert record["posted_date"] == "Posted 16 days ago"
    assert record["url"] == "https://www.idealist.org/en/nonprofit-job/123-example-role"


def test_extract_listing_records_ignores_informational_inline_arrays_on_loading_shell_pages():
    html = """
    <html><body>
      <script type="application/json">
        {
          "items": [
            {
              "name": "Premier Delivery",
              "url": "/pages/informational/premier-delivery",
              "sku": "46448",
              "publication_date": "2025-05-13T14:11:30.453Z"
            },
            {
              "name": "Karen Millen App",
              "url": "/pages/informational/download-the-app",
              "sku": "55444",
              "publication_date": "2025-07-07T09:26:04.690Z"
            }
          ]
        }
      </script>
      <section data-test-id="content-grid">
        <div data-test-id="product-card-skeleton"></div>
        <div data-test-id="product-card-skeleton"></div>
        <div data-test-id="product-card-skeleton"></div>
        <div data-test-id="product-card-skeleton"></div>
      </section>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.karenmillen.com/categories/womens-coats-jackets",
        max_records=10,
    )

    assert records == []


def test_extract_from_card_handles_clark_job_card_metadata_selectors():
    html = """
    <li data-testid="careers-search-result-listing">
      <article class="mb-2">
        <a class="listings__link" href="/careerdetail/?id=100709">
          <h2 data-testid="careers-search-result-listing-job-title">1st Shift Outbound Material Handler-$20.00/Hr. (4 weeks PTO)</h2>
          <span data-testid="careers-search-result-listing-company-name">WebstaurantStore</span>
          <span data-testid="careers-search-result-listing-job-location">Savannah, GA</span>
        </a>
      </article>
    </li>
    <li data-testid="careers-search-result-listing">
      <article class="mb-2">
        <a class="listings__link" href="/careerdetail/?id=100710">
          <h2 data-testid="careers-search-result-listing-job-title">2nd Shift Picker</h2>
          <span data-testid="careers-search-result-listing-company-name">Clark Food Service Equipment</span>
          <span data-testid="careers-search-result-listing-job-location">Lancaster, PA</span>
        </a>
      </article>
    </li>
    """

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://careers.clarkassociatesinc.biz/",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "1st Shift Outbound Material Handler-$20.00/Hr. (4 weeks PTO)"
    assert records[0]["company"] == "WebstaurantStore"
    assert records[0]["location"] == "Savannah, GA"
    assert records[0]["url"] == "https://careers.clarkassociatesinc.biz/careerdetail/?id=100709"


def test_extract_from_card_handles_atlas_job_card_metadata_rows():
    html = """
    <div class="pp-content-post pp-content-grid-post job_listing">
      <div itemprop="publisher" itemscope itemtype="https://schema.org/Organization">
        <meta itemprop="name" content="Atlas Medstaff" />
      </div>
      <a class="atlas_js_job_title" href="https://atlasmedstaff.com/job/1475834-rn-telemetry-prescott-arizona/">
        <span class="title_js_left">RN:</span>
        <span class="title_js_right">Telemetry</span>
        <span class="title_js_second_specialty">, Med/Surg</span>
      </a>
      <div class="atlas_js_job_more_info_div">
        <p class="atlas_js_job_more_info"><img src="/wp-content/uploads/2024/11/Icon-Location.svg"/><span>Prescott, Arizona</span></p>
        <p class="atlas_js_job_more_info"><img src="/wp-content/uploads/2024/11/Icon-Pay.svg"/><span>$1,886/wk est</span></p>
        <p class="atlas_js_job_more_info"><img src="/wp-content/uploads/2025/03/Job-Number-Icon.svg"/><span>1475834</span></p>
      </div>
    </div>
    <div class="pp-content-post pp-content-grid-post job_listing">
      <div itemprop="publisher" itemscope itemtype="https://schema.org/Organization">
        <meta itemprop="name" content="Atlas Medstaff" />
      </div>
      <a class="atlas_js_job_title" href="https://atlasmedstaff.com/job/1475835-rn-icu-prescott-arizona/">
        <span class="title_js_left">RN:</span>
        <span class="title_js_right">ICU</span>
      </a>
      <div class="atlas_js_job_more_info_div">
        <p class="atlas_js_job_more_info"><img src="/wp-content/uploads/2024/11/Icon-Location.svg"/><span>Prescott, Arizona</span></p>
        <p class="atlas_js_job_more_info"><img src="/wp-content/uploads/2024/11/Icon-Pay.svg"/><span>$2,001/wk est</span></p>
      </div>
    </div>
    """

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://atlasmedstaff.com/job-search/",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["title"] == "RN: Telemetry, Med/Surg"
    assert records[0]["company"] == "Atlas Medstaff"
    assert records[0]["location"] == "Prescott, Arizona"
    assert records[0]["salary"] == "$1,886/wk est"
    assert records[0]["url"] == "https://atlasmedstaff.com/job/1475834-rn-telemetry-prescott-arizona/"
    assert "image_url" not in records[0]
    assert "additional_images" not in records[0]


def test_lookup_next_flight_window_index_returns_none_when_url_cannot_be_found():
    combined = '"displayName":"Ghost Product","listingUrl":"https://cdn.example.com/other-item"'

    lookup_index = listing_extractor._lookup_next_flight_window_index(
        combined,
        "/products/missing-item",
        "https://shop.example.com/category",
    )

    assert lookup_index is None


def test_extract_structured_sources_merges_records_from_multiple_sources():
    html = "<html><body></body></html>"
    manifest = _sources(
        json_ld=[
            {
                "@type": "ItemList",
                "itemListElement": [
                    {"item": {"@type": "Product", "name": "Mirror", "url": "/p/mirror", "sku": "SKU-1"}},
                ],
            }
        ],
        next_data={
            "products": [
                {"title": "Mirror", "url": "/p/mirror", "sku": "SKU-1", "price": "99.00", "brand": "Acme"},
                {"title": "Lamp", "url": "/p/lamp", "sku": "SKU-2", "price": "49.00", "brand": "Glow"},
            ]
        },
        _hydrated_states=[],
        network_payloads=[],
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com",
        max_records=10,
        manifest=manifest,
    )

    mirror = next(record for record in records if record["url"] == "https://example.com/p/mirror")
    assert mirror["sku"] == "SKU-1"
    assert mirror["price"] == "99.00"
    assert mirror["brand"] == "Acme"
    assert "json_ld_item_list" in mirror["_source"]
    assert "next_data" in mirror["_source"]


def test_extract_structured_sources_reads_deep_hydrated_state_records(monkeypatch):
    monkeypatch.setattr(listing_extractor, "MAX_JSON_RECURSION_DEPTH", 1)
    manifest = _sources(
        _hydrated_states=[
            {
                "props": {
                    "pageProps": {
                        "initialState": {
                            "search": {
                                "results": {
                                    "products": [
                                        {"title": "Deep Product A", "url": "/p/a", "price": "10.00"},
                                        {"title": "Deep Product B", "url": "/p/b", "price": "20.00"},
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        ]
    )

    records = extract_listing_records(
        "<html><body></body></html>",
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=10,
        manifest=manifest,
    )

    assert [record["title"] for record in records] == ["Deep Product A", "Deep Product B"]


def test_structured_join_key_does_not_merge_title_only_records():
    first = {"title": "Accent Mirror", "brand": "Acme"}
    second = {"title": "Accent Mirror", "brand": "Other"}

    merged = listing_extractor._merge_structured_record_sets([[first], [second]])

    assert merged == []


def test_normalize_ld_item_preserves_zero_price():
    record = listing_extractor._normalize_ld_item(
        {
            "@type": "Product",
            "name": "Free Sample",
            "offers": {"price": 0},
        },
        "ecommerce_listing",
        "https://example.com/category",
    )

    assert record is not None
    assert record["price"] == 0


def test_auto_detect_cards_ignores_sidebar_filter_groups_for_commerce():
    html = """
    <html><body>
      <aside class="filters">
        <ul>
          <li class="choice"><a href="/filters?brand=a">Brand A (1353)</a></li>
          <li class="choice"><a href="/filters?brand=b">Brand B (42)</a></li>
          <li class="choice"><a href="/filters?brand=c">Brand C (8)</a></li>
        </ul>
      </aside>
      <section class="results-grid">
        <div class="entry"><a href="/p/1"><img src="/1.jpg" /></a><h3>Widget A</h3><span class="price">$10</span></div>
        <div class="entry"><a href="/p/2"><img src="/2.jpg" /></a><h3>Widget B</h3><span class="price">$20</span></div>
        <div class="entry"><a href="/p/3"><img src="/3.jpg" /></a><h3>Widget C</h3><span class="price">$30</span></div>
      </section>
    </body></html>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    cards, _selector = listing_extractor._auto_detect_cards(soup, surface="ecommerce_listing")

    assert [card.get_text(" ", strip=True) for card in cards] == [
        "Widget A $10",
        "Widget B $20",
        "Widget C $30",
    ]


# -----------------------------------------------------------------------
# Card title extraction: skip price-like headings
# -----------------------------------------------------------------------

def test_card_title_skips_price_heading():
    """When the first heading contains a price, title should come from the next heading."""
    html = """
    <html><body>
    <div class="product-card">
        <h4 class="price">$295.99</h4>
        <h4><a class="title" href="/product/1">Asus VivoBook 15</a></h4>
        <img src="/img/laptop.png" />
    </div>
    <div class="product-card">
        <h4 class="price">$399.00</h4>
        <h4><a class="title" href="/product/2">Lenovo IdeaPad</a></h4>
        <img src="/img/laptop2.png" />
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=10)
    assert len(records) == 2
    assert records[0]["title"] == "Asus VivoBook 15"
    assert records[1]["title"] == "Lenovo IdeaPad"
    assert records[0]["price"] == "$295.99"


def test_card_title_uses_itemprop_name():
    """itemprop='name' should be preferred for title."""
    html = """
    <html><body>
    <div class="product-card">
        <span itemprop="name">Correct Product Name</span>
        <h3>Wrong Heading Text</h3>
        <span class="price">$50</span>
    </div>
    <div class="product-card">
        <span itemprop="name">Another Product</span>
        <h3>Also Wrong</h3>
        <span class="price">$60</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=10)
    assert len(records) == 2
    assert records[0]["title"] == "Correct Product Name"


def test_card_itemprop_image():
    """itemprop='image' should be used for image_url."""
    html = """
    <html><body>
    <div class="product-card">
        <img itemprop="image" src="/img/product.jpg" />
        <h3><a href="/p/1">Product A</a></h3>
        <span class="price">$25</span>
    </div>
    <div class="product-card">
        <img itemprop="image" src="/img/product2.jpg" />
        <h3><a href="/p/2">Product B</a></h3>
        <span class="price">$35</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(
        html, "ecommerce_listing", set(),
        page_url="https://example.com", max_records=10,
    )
    assert len(records) == 2
    assert records[0]["image_url"] == "https://example.com/img/product.jpg"


# -----------------------------------------------------------------------
# Price text cleanup
# -----------------------------------------------------------------------

def test_clean_price_text_strips_surrounding_text():
    """Price extraction should strip non-price text like 'In stock Add to basket'."""
    assert listing_extractor._clean_price_text("$51.77 In stock Add to basket") == "$51.77"
    assert listing_extractor._clean_price_text("£29.99") == "£29.99"
    assert listing_extractor._clean_price_text("€1,299.00 Free shipping") == "€1,299.00"
    assert listing_extractor._clean_price_text("$0.99") == "$0.99"


# -----------------------------------------------------------------------
# Auto-detect cards: product signals over nav links
# -----------------------------------------------------------------------

def test_auto_detect_prefers_product_cards_over_nav_links():
    """Auto-detect should prefer elements with links+images over plain nav lists."""
    nav_items = "\n".join(
        f'<li class="nav-item"><a href="/cat/{i}">Category {i}</a></li>'
        for i in range(20)
    )
    product_items = "\n".join(
        f'''<div class="item-card">
            <a href="/product/{i}"><img src="/img/{i}.jpg" />Product {i}</a>
            <span class="price">${i*10}.00</span>
        </div>'''
        for i in range(10)
    )
    html = f"""
    <html><body>
    <nav><ul>{nav_items}</ul></nav>
    <div class="results-grid">{product_items}</div>
    </body></html>
    """
    records = extract_listing_records(html, "ecommerce_listing", set(), max_records=50)
    assert len(records) >= 5
    assert records[0].get("price") is not None
    assert "product" in records[0].get("url", "").lower() or records[0].get("image_url")


# -----------------------------------------------------------------------
# Microdata product card selector
# -----------------------------------------------------------------------

def test_itemscope_product_selector():
    """Cards with [itemscope][itemtype*='Product'] should be matched."""
    html = """
    <html><body>
    <div itemscope itemtype="https://schema.org/Product">
        <span itemprop="name">Microdata Widget</span>
        <span itemprop="price">$15.00</span>
        <a href="/product/md1">Link</a>
    </div>
    <div itemscope itemtype="https://schema.org/Product">
        <span itemprop="name">Microdata Gadget</span>
        <span itemprop="price">$25.00</span>
        <a href="/product/md2">Link</a>
    </div>
    </body></html>
    """
    records = extract_listing_records(
        html, "ecommerce_listing", set(),
        page_url="https://example.com", max_records=10,
    )
    assert len(records) == 2
    assert records[0]["title"] == "Microdata Widget"
    assert records[0]["price"] == "$15.00"
