# Tests for listing page extraction.
from __future__ import annotations

import app.services.extract.listing_extractor as listing_extractor

from app.services.extract.listing_extractor import extract_listing_records


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
            <h4><a href="/p/1">Item One</a></h4>
        </div>
        <div class="item-xyz">
            <h4><a href="/p/2">Item Two</a></h4>
        </div>
        <div class="item-xyz">
            <h4><a href="/p/3">Item Three</a></h4>
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
    manifest = type("Manifest", (), {
        "json_ld": [],
        "next_data": None,
        "_hydrated_states": [
            {"products": [
                {"title": "Hydrated A", "url": "/p/a"},
                {"title": "Hydrated B", "url": "/p/b"},
            ]}
        ],
        "network_payloads": [],
    })()
    records = extract_listing_records(html, "ecommerce_listing", set(), page_url="https://example.com", manifest=manifest)
    assert len(records) == 2
    assert records[0]["title"] == "Hydrated A"
    assert records[1]["url"] == "https://example.com/p/b"


def test_extract_items_from_json_uses_configured_max_depth(monkeypatch):
    monkeypatch.setattr(listing_extractor, "MAX_JSON_RECURSION_DEPTH", 5)
    payload = {"level1": {"level2": {"level3": {"level4": {"products": [
        {"title": "Deep A", "url": "/a"},
        {"title": "Deep B", "url": "/b"},
    ]}}}}}

    records = listing_extractor._extract_items_from_json(
        payload,
        "ecommerce_listing",
        "https://example.com",
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


def test_extract_listing_prefers_rich_product_array_over_category_links():
    html = "<html><body></body></html>"
    manifest = type("Manifest", (), {
        "json_ld": [],
        "next_data": {
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
        "_hydrated_states": [],
        "network_payloads": [],
    })()

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
    manifest = type("Manifest", (), {
        "json_ld": [],
        "next_data": {
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
        "_hydrated_states": [],
        "network_payloads": [],
    })()

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
    manifest = type("Manifest", (), {
        "json_ld": [
            {
                "@type": "ItemList",
                "itemListElement": [
                    {"item": {"@type": "Product", "name": "Mirror", "url": "/p/mirror", "sku": "SKU-1"}},
                ],
            }
        ],
        "next_data": {
            "products": [
                {"title": "Mirror", "url": "/p/mirror", "sku": "SKU-1", "price": "99.00", "brand": "Acme"},
                {"title": "Lamp", "url": "/p/lamp", "sku": "SKU-2", "price": "49.00", "brand": "Glow"},
            ]
        },
        "_hydrated_states": [],
        "network_payloads": [],
    })()

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


def test_structured_join_key_does_not_merge_title_only_records():
    first = {"title": "Accent Mirror", "brand": "Acme"}
    second = {"title": "Accent Mirror", "brand": "Other"}

    merged = listing_extractor._merge_structured_record_sets([[first], [second]])

    assert merged == []


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
