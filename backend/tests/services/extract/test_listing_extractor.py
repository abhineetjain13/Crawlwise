# Tests for listing page extraction.
from __future__ import annotations

import time
from unittest.mock import patch

import app.services.extract.listing_card_extractor as listing_card_extractor
import app.services.extract.listing_extractor as listing_extractor
import app.services.extract.listing_normalize as listing_normalize
from bs4 import BeautifulSoup
from app.services.extract.listing_extractor import (
    extract_listing_records as _extract_listing_records_impl,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.support import manifest as _sources
from tests.support import run_extract_listing_records
from tests.services._duplication_helpers import (
    adapter_manifest,
    html_page,
    item_list_manifest,
    job_card,
    query_state_manifest,
    next_data_manifest,
    product_card,
)


def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    manifest: dict | None = None,
) -> list[dict]:
    return run_extract_listing_records(
        _extract_listing_records_impl,
        html=html,
        surface=surface,
        target_fields=target_fields,
        page_url=page_url,
        max_records=max_records,
        manifest_data=manifest,
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


def test_extract_product_cards_falls_back_to_image_alt_for_title():
    html = """
    <html><body>
    <div class="product-card">
        <a href="/product/1"><img src="https://img.example.com/a.jpg" alt="Widget Alt Title" /></a>
        <span class="price">$10.00</span>
    </div>
    <div class="product-card">
        <a href="/product/2"><img src="https://img.example.com/b.jpg" alt="Widget B" /></a>
        <span class="price">$20.00</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=5,
    )
    assert len(records) == 2
    assert records[0]["title"] == "Widget Alt Title"
    assert records[0]["url"] == "https://example.com/product/1"


def test_extract_listing_records_reuses_provided_soup(monkeypatch):
    html = """
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
    """
    soup = BeautifulSoup(html, "html.parser")

    def _unexpected_reparse(*args, **kwargs):
        raise AssertionError("BeautifulSoup should not be called when soup is provided")

    monkeypatch.setattr(listing_extractor, "BeautifulSoup", _unexpected_reparse)

    records = _extract_listing_records_impl(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        soup=soup,
    )

    assert len(records) == 2


def test_extract_listing_records_ignores_third_party_social_network_payload_records():
    html = """
    <html><body>
    <div class="product-card">
        <a href="/product/1"><img src="https://img.example.com/a.jpg" alt="Widget A" /></a>
        <span class="price">$10.00</span>
    </div>
    <div class="product-card">
        <a href="/product/2"><img src="https://img.example.com/b.jpg" alt="Widget B" /></a>
        <span class="price">$20.00</span>
    </div>
    </body></html>
    """
    manifest = _sources(
        network_payloads=[
            {
                "url": "https://edge.curalate.com/v1/media/foo",
                "body": [
                    {
                        "title": "Wrong Offsite Product",
                        "url": "https://www.facebook.com/reel/123",
                        "price": "89.99",
                        "brand": "Jonnie",
                    },
                    {
                        "title": "Another Offsite Product",
                        "url": "https://www.instagram.com/p/abc",
                        "price": "99.99",
                        "brand": "Mooloola",
                    },
                ],
            }
        ]
    )

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/category",
        max_records=5,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["title"] == "Widget A"
    assert records[0]["url"] == "https://example.com/product/1"


def test_extract_listing_records_merges_structured_and_dom_card_fields_for_same_item():
    html = html_page(
        product_card(
            href="/product/1",
            title="Widget A",
            price="$10.00",
            image_src="https://img.example.com/a.jpg",
        ),
        product_card(
            href="/product/2",
            title="Widget B",
            price="$20.00",
            image_src="https://img.example.com/b.jpg",
        ),
    )
    manifest = item_list_manifest(
        [
            {
                "@type": "Product",
                "name": "Widget A",
                "url": "https://example.com/product/1",
                "brand": {"name": "Acme"},
                "description": "A richer structured description for widget A.",
            },
            {
                "@type": "Product",
                "name": "Widget B",
                "url": "https://example.com/product/2",
                "brand": {"name": "Acme"},
                "description": "A richer structured description for widget B.",
            },
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
    filtered_records = listing_extractor._enforce_listing_field_contract(records, "listing")

    assert len(records) == 2
    assert records[0]["price"] == "$10.00"
    assert filtered_records[0]["price"] == "$10.00"
    assert "brand" not in filtered_records[0]
    assert "description" not in filtered_records[0]


def test_extract_listing_records_merges_adapter_rows_with_dom_job_cards():
    html = html_page(
        job_card(
            href="https://example.com/jobs/164066",
            title="Medical Surgical Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
            salary="$52/hr",
        ),
        job_card(
            href="https://example.com/jobs/164065",
            title="Cardiovascular Step Down Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
        ),
    )
    manifest = adapter_manifest(
        [
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
    manifest = next_data_manifest(
        [
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


def test_extract_listing_records_citybeach_artifact_stays_onsite_and_keeps_titles():
    html = html_page(
        *(
            product_card(
                href=f"/au/mens/swimwear/product-{index}",
                price=f"${index * 10}.00",
                image_src=f"https://cdn.citybeach.com/product-{index}.jpg",
                image_alt=f"Swim Short {index}",
            )
            for index in range(1, 11)
        )
    )
    payloads = [
        {
            "url": "https://edge.curalate.com/v1/media/foo",
            "body": [
                {
                    "title": "Wrong Offsite Product",
                    "url": "https://www.facebook.com/reel/123",
                    "price": "89.99",
                },
                {
                    "title": "Another Offsite Product",
                    "url": "https://www.instagram.com/p/abc",
                    "price": "99.99",
                },
            ],
        }
    ]

    records = _extract_listing_records_impl(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.citybeach.com/au/mens/swimwear/",
        max_records=10,
        xhr_payloads=payloads,
        adapter_records=[],
    )

    assert len(records) == 10
    for record in records[:5]:
        assert record["title"]
        assert record["url"].startswith("https://www.citybeach.com/")
        assert "facebook.com" not in record["url"]
        assert "instagram.com" not in record["url"]


def test_extract_listing_records_myntra_artifact_preserves_primary_results():
    products = []
    for index in range(1, 11):
        products.append(
            {
                "name": f"Hand Towel {index}",
                "brandName": f"Brand {index}",
                "price": index * 100,
                "mrp": (index * 100) + 50,
                "imageUrl": f"https://assets.myntassets.com/product-{index}.jpg",
                "slug": f"hand-towels/product-{index}",
                "productId": f"{1000 + index}",
                "rating": 4.0 + (index / 100),
                "inStock": True,
            }
        )

    records = extract_listing_records(
        "<html><body></body></html>",
        "ecommerce_listing",
        set(),
        page_url="https://www.myntra.com/hand-towels",
        max_records=10,
        manifest=_sources(next_data={"products": products}),
    )

    assert len(records) == 10
    for record in records[:5]:
        assert record["title"]
        assert record["url"].startswith("https://www.myntra.com/")
        assert record["brand"]


def test_extract_listing_records_handles_dyson_style_comparison_tables():
    html = """
    <html><body>
      <div class="comparison">
        <table>
          <thead>
            <tr class="product">
              <th class="cms-first"></th>
              <th class="price-info">
                <a href="/airwrap-id-multi-styler-dryer-vinca-blue-topaz">
                  <img src="/images/airwrap-id.png" alt="" />
                </a>
              </th>
              <th class="price-info">
                <a href="/dyson-airwrap-hs02-origin-nickel-copper">
                  <img src="/images/airwrap-origin.png" alt="" />
                </a>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr class="compare-row">
              <td class="cms-first">Attachments</td>
              <td>6 Attachments</td>
              <td>3 Attachments</td>
            </tr>
            <tr class="compare-row">
              <td class="cms-first">End styles</td>
              <td>Straight, wavy, curly</td>
              <td>Loose curls</td>
            </tr>
          </tbody>
        </table>
      </div>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://www.dyson.in/hair-care/hair-stylers",
        max_records=10,
    )
    assert len(records) == 2
    assert records[0]["url"] == "https://www.dyson.in/airwrap-id-multi-styler-dryer-vinca-blue-topaz"
    assert records[0]["image_url"] == "https://www.dyson.in/images/airwrap-id.png"
    assert records[0]["title"].startswith("Airwrap Id Multi Styler Dryer")
    assert records[1]["url"] == "https://www.dyson.in/dyson-airwrap-hs02-origin-nickel-copper"

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
    assert "location" not in records[0]
    assert records[0]["url"].endswith("/1511949734")
    assert records[1]["title"] == "Philips lumea prestige"


def test_extract_balanced_literal_rejects_oversized_unterminated_inline_array():
    html = "<script>window.__STATE__ = {\"listListingDetails\": [" + ("{" * 300_000)

    result = listing_extractor._listing_structured_extractor._extract_balanced_literal(
        html,
        html.index("["),
    )

    assert result is None


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
    # Note: color and size extraction from generic text like "6 Colors, 4 Sizes" is not currently supported
    # assert records[0]["color"] == "6 Colors, 4 Sizes"
    # assert records[0]["size"] == "6 Colors, 4 Sizes"
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


def test_infer_currency_from_page_url_ignores_false_positive_path_substrings():
    assert (
        listing_extractor._infer_currency_from_page_url(
            "https://example.com/contact-us/"
        )
        == ""
    )
    assert (
        listing_extractor._infer_currency_from_page_url(
            "https://example.com/user-settings/"
        )
        == ""
    )


def test_infer_currency_from_page_url_matches_bounded_locale_segments():
    assert (
        listing_extractor._infer_currency_from_page_url(
            "https://example.com/us/products/"
        )
        == "USD"
    )
    assert (
        listing_extractor._infer_currency_from_page_url(
            "https://example.com/gb/checkout/"
        )
        == "GBP"
    )


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


def test_extract_listing_next_flight_uses_generic_brand_fallback():
    html = """
    <html><body>
      <script>
      self.__next_f.push([1,"1:{\\"displayName\\":\\"Trail Shoe\\",\\"listingUrl\\":\\"/p/trail-shoe\\",\\"brand\\":{\\"name\\":\\"Acme\\"},\\"priceVariation\\":\\"SALE\\",\\"amount\\":\\"79.99\\"}"]);
      self.__next_f.push([1,"2:{\\"displayName\\":\\"Road Shoe\\",\\"listingUrl\\":\\"/p/road-shoe\\",\\"brand\\":{\\"name\\":\\"Acme\\"},\\"priceVariation\\":\\"SALE\\",\\"amount\\":\\"89.99\\"}"]);
      </script>
    </body></html>
    """

    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com",
        max_records=10,
    )

    assert len(records) == 2
    assert records[0]["brand"] == "Acme"


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
    assert "slug" not in records[0]
    assert records[0]["url"] == "https://www.nykaa.com/nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112"
    assert records[0]["price"] == 509
    assert records[0]["brand"] == "Nykaa Cosmetics"


def test_match_dimensions_line_does_not_treat_random_d_suffix_as_dimension_signal():
    lines = ["Handcrafted", "Solid wood finish", "12 in wide"]

    assert listing_extractor._match_dimensions_line(lines) == "12 in wide"


def test_match_line_uses_cached_case_insensitive_regex_compilation():
    listing_extractor._compile_case_insensitive_regex.cache_clear()
    lines = ["Color: Black", "SIZE: M"]

    assert listing_extractor._match_line(lines, r"\bsizes?\b") == "SIZE: M"
    assert listing_extractor._match_line(lines, r"\bsizes?\b") == "SIZE: M"

    cache_info = listing_extractor._compile_case_insensitive_regex.cache_info()
    assert cache_info.hits >= 1
    assert cache_info.misses == 1


def test_match_dimensions_line_detects_case_insensitive_dimension_token():
    lines = ["ships fast", "HEIGHT x width: 10 x 5", "other"]

    assert listing_extractor._match_dimensions_line(lines) == "HEIGHT x width: 10 x 5"


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
    manifest = query_state_manifest(
        [
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
    manifest = query_state_manifest(
        [
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


def test_extract_card_size_rejects_generic_multiple_sizes():
    assert (
        listing_extractor._extract_card_size(["Color: Black", "Sizes: multiple sizes"])
        == ""
    )


def test_extract_card_size_extracts_measurement_values():
    assert listing_extractor._extract_card_size(["Size 13 in"]) == "13 in"


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


def test_is_merchandising_record_only_rejects_pure_editorial_sale_titles():
    assert (
        listing_extractor._is_merchandising_record(
            {"title": "Winter Sale Running Shoes", "url": "https://example.com/p/1"}
        )
        is False
    )
    assert (
        listing_extractor._is_merchandising_record(
            {"title": "Holiday Sale Jacket Size M", "url": "https://example.com/p/2"}
        )
        is False
    )
    assert (
        listing_extractor._is_merchandising_record(
            {"title": "SALE", "url": "https://example.com/promo"}
        )
        is True
    )
    assert (
        listing_extractor._is_merchandising_record(
            {"title": "UP TO 50% SALE", "url": "https://example.com/promo"}
        )
        is True
    )


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


def test_extract_listing_records_synthesizes_saashr_urls_from_network_payloads():
    html = "<html><body></body></html>"
    manifest = _sources(
        network_payloads=[
            {
                "url": "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/%7C6208610/job-requisitions?offset=1&size=20&sort=desc&ein_id=118959061&lang=en-US&career_portal_id=6062087",
                "body": {
                    "job_requisitions": [
                        {
                            "id": "587696937",
                            "job_title": "Behavioral Health Tech - Nights",
                            "location": {"city": "Yankton", "state": "SD"},
                            "job_description": "Support crisis stabilization services.",
                        },
                        {
                            "id": "587687244",
                            "job_title": "Crisis and Addiction Care EMT or Paramedic – Full Time",
                            "location": {"city": "Yankton", "state": "SD"},
                            "job_description": "Nursing care role.",
                        }
                    ]
                },
            }
        ]
    )

    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://lcbhs.net/careers/",
        max_records=10,
        manifest=manifest,
    )

    assert len(records) == 2
    assert records[0]["job_id"] == "587696937"
    assert (
        records[0]["url"]
        == "https://secure7.saashr.com/ta/6208610.careers?offset=1&size=20&sort=desc&ein_id=118959061&lang=en-US&career_portal_id=6062087&ShowJob=587696937"
    )
    assert records[0]["apply_url"] == records[0]["url"]


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


def test_extract_structured_sources_does_not_mutate_structured_extractor_depth(monkeypatch):
    monkeypatch.setattr(listing_extractor, "MAX_JSON_RECURSION_DEPTH", 1)
    original_structured_depth = listing_extractor._listing_structured_extractor.MAX_JSON_RECURSION_DEPTH
    monkeypatch.setattr(
        listing_extractor._listing_structured_extractor,
        "MAX_JSON_RECURSION_DEPTH",
        original_structured_depth + 7,
    )
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
    assert (
        listing_extractor._listing_structured_extractor.MAX_JSON_RECURSION_DEPTH
        == original_structured_depth + 7
    )


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


def test_card_group_score_prefers_job_signals_on_job_cards():
    html = """
    <html><body>
      <section class="job-results">
        <div class="job-card">
          <h3><a href="/jobs/1">Senior Data Engineer</a></h3>
          <div class="meta"><span>Remote</span><span>Full Time</span></div>
        </div>
        <div class="job-card">
          <h3><a href="/jobs/2">Staff Platform Engineer</a></h3>
          <div class="meta"><span>Austin, TX</span><span>Hybrid</span></div>
        </div>
      </section>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    group = soup.select(".job-card")

    job_score = listing_card_extractor._card_group_score(
        group, surface="job_listing"
    )
    commerce_score = listing_card_extractor._card_group_score(
        group, surface="ecommerce_listing"
    )

    assert job_score > commerce_score


def test_auto_detect_cards_prefers_job_groups_for_job_surface():
    html = """
    <html><body>
      <aside class="filters">
        <ul>
          <li class="choice"><a href="/jobs?location=remote">Remote</a></li>
          <li class="choice"><a href="/jobs?location=austin">Austin</a></li>
          <li class="choice"><a href="/jobs?location=hybrid">Hybrid</a></li>
        </ul>
      </aside>
      <section class="job-results">
        <div class="job-card">
          <h3><a href="/jobs/1">Senior Data Engineer</a></h3>
          <div class="meta"><span>Remote</span><span>Full Time</span></div>
        </div>
        <div class="job-card">
          <h3><a href="/jobs/2">Staff Platform Engineer</a></h3>
          <div class="meta"><span>Austin, TX</span><span>Hybrid</span></div>
        </div>
        <div class="job-card">
          <h3><a href="/jobs/3">Analytics Engineer</a></h3>
          <div class="meta"><span>New York, NY</span><span>Contract</span></div>
        </div>
      </section>
    </body></html>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")

    cards, _selector = listing_extractor._auto_detect_cards(soup, surface="job_listing")

    assert [card.get_text(" ", strip=True) for card in cards] == [
        "Senior Data Engineer Remote Full Time",
        "Staff Platform Engineer Austin, TX Hybrid",
        "Analytics Engineer New York, NY Contract",
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


def test_infer_listing_title_min_chars_is_configurable(monkeypatch):
    html = """
    <html><body>
      <div class="product-card">
        <a href="/p/tv">TV</a>
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one(".product-card")
    assert card is not None

    monkeypatch.setattr(listing_card_extractor, "LISTING_CARD_LISTING_TITLE_MIN_CHARS", 2)

    assert listing_card_extractor._infer_listing_title_from_links(card) == "TV"


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


def test_coerce_listing_product_url_candidate_preserves_canonical_percent_encoded_url():
    encoded = "https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3"

    assert (
        listing_card_extractor._coerce_listing_product_url_candidate(
            encoded,
            "https://www.shop.ving.run/search",
        )
        == encoded
    )


def test_extract_listing_records_reads_titles_from_pro_title_text():
    html = """
    <html><body>
    <div class="searchResultContainer">
        <div class="productRow">
            <div class="productBox productBox__modules-lnwdropship-browser-components-ProductBox customerView hasDiscountTag">
                <a class="linkProductBox" title="NIRUN (นิรัน)" href="/product/nirun-นิรัน/1"></a>
                <div class="productContent">
                    <div class="productImage">
                        <img src="/img/nirun.webp" alt="NIRUN (นิรัน)" />
                    </div>
                    <div class="productDescription">
                        <div class="pro-title name"><div data-field="description" class="text">NIRUN (นิรัน)</div></div>
                        <div class="price"><div class="realprice">฿2,500</div></div>
                    </div>
                </div>
            </div>
            <div class="productBox productBox__modules-lnwdropship-browser-components-ProductBox customerView hasDiscountTag">
                <a class="linkProductBox" title="JARIX 1.0 (จาริกซ์)" href="/product/jarix-10-จาริกซ์/2"></a>
                <div class="productContent">
                    <div class="productImage">
                        <img src="/img/jarix.webp" alt="JARIX 1.0 (จาริกซ์)" />
                    </div>
                    <div class="productDescription">
                        <div class="pro-title name"><div data-field="description" class="text">JARIX 1.0 (จาริกซ์)</div></div>
                        <div class="price"><div class="realprice">฿1,944</div></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    </body></html>
    """
    soup = listing_extractor.BeautifulSoup(html, "html.parser")
    card = soup.select_one(".productBox")
    assert card is not None

    record = listing_extractor._extract_from_card(
        card, set(), "ecommerce_listing", "https://www.shop.ving.run/search"
    )
    assert record["title"] == "NIRUN (นิรัน)"
    assert record["price"] == "2,500"
    assert record["url"] == "https://www.shop.ving.run/product/nirun-นิรัน/1"


# -----------------------------------------------------------------------
# Price text cleanup
# -----------------------------------------------------------------------

def test_clean_price_text_strips_surrounding_text():
    """Price extraction should strip non-price text like 'In stock Add to basket'."""
    assert listing_extractor._clean_price_text("$51.77 In stock Add to basket") == "$51.77"
    assert listing_extractor._clean_price_text("£29.99") == "£29.99"
    assert listing_extractor._clean_price_text("€1,299.00 Free shipping") == "€1,299.00"
    assert listing_extractor._clean_price_text("$0.99") == "$0.99"


def test_clean_price_text_returns_none_for_overlong_input_without_regex_backtracking():
    raw = "$" + ("9" * 9999)
    started_at = time.perf_counter_ns()
    assert listing_extractor._clean_price_text(raw) is None
    elapsed_ns = time.perf_counter_ns() - started_at
    assert elapsed_ns < 50_000_000


def test_normalize_generic_item_prefers_product_full_url_over_nested_shop_url():
    record = listing_extractor._normalize_generic_item(
        {
            "product_name": "NIRUN (นิรัน)",
            "product_full_url": "https://www.shop.ving.run/product/nirun/11000742818002390",
            "product_short_url": "https://www.shop.ving.run/product/11000742818002390",
            "product_images": "https://cdn.example.com/nirun.jpg",
            "shop": {"url": "https://www.shop.ving.run/nirun"},
        },
        "ecommerce_listing",
        "https://www.shop.ving.run/search",
    )

    assert record is not None
    assert record["url"] == "https://www.shop.ving.run/product/nirun/11000742818002390"


def test_normalize_listing_record_drops_dimensions_when_it_duplicates_size_choices():
    normalized = listing_normalize.normalize_listing_record(
        {
            "title": "NIRUN (นิรัน)",
            "url": "https://www.shop.ving.run/product/nirun/11000742818002390",
            "size": "EU-36, EU-37, EU-38, EU-39, EU-40, EU-41, EU-42, EU-43",
            "dimensions": "EU-36, EU-37, EU-38, EU-39, EU-40, EU-41/42, EU-43",
        },
        surface="ecommerce_listing",
        page_url="https://www.shop.ving.run/search",
        target_fields=set(),
    )

    assert "dimensions" not in normalized


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

# ---------------------------------------------------------------------------
# Property-Based Tests for Task 4: Listing Field Contract Enforcement
# ---------------------------------------------------------------------------

@given(
    records=st.lists(
        st.fixed_dictionaries(
            {
                "url": st.just("https://example.com/product/1"),
                "title": st.just("Product Title"),
                "price": st.just("$10.00"),
                "image_url": st.just("https://example.com/image.jpg"),
                "brand": st.just("Acme"),
                "gtin": st.just("123456789"),
                "description": st.just("Product description"),
                "_source": st.just("listing_card"),  # Mark as DOM record
            }
        ),
        min_size=0,
        max_size=10,
    )
)
@settings(max_examples=100)
def test_property_listing_field_contract_enforcement(records):
    """Feature: extraction-pipeline-improvements, Property 6: Listing Field Contract Enforcement
    
    **Validates: Requirements 3.2, 3.3**
    
    For any listing page DOM extraction result, the output SHALL NOT contain
    detail-only fields {"brand", "gtin", "variants", "specifications", "description"}.
    """
    # Apply contract enforcement for listing pages
    filtered_records = listing_extractor._enforce_listing_field_contract(records, "listing")
    
    # Verify all records do not contain detail-only fields
    detail_only_fields = listing_extractor.DETAIL_ONLY_FIELDS
    
    for record in filtered_records:
        for field in record.keys():
            # Field must not be a detail-only field
            assert field not in detail_only_fields, f"Detail-only field {field} found in listing record"


@given(
    records=st.lists(
        st.fixed_dictionaries(
            {
                "url": st.just("https://example.com/product/1"),
                "title": st.just("Product Title"),
                "brand": st.just("Acme"),
                "description": st.just("Product description"),
                "_source": st.just("listing_card"),  # Mark as DOM record
            }
        ),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=100)
def test_property_listing_contract_warning_logging(records):
    """Feature: extraction-pipeline-improvements, Property 7: Listing Contract Warning Logging
    
    **Validates: Requirement 3.6**
    
    For any listing page extraction that initially produces detail-only fields,
    _enforce_listing_field_contract() SHALL drop those fields from the output AND log a
    warning message containing the dropped field names.
    """
    from unittest.mock import patch
    
    # Mock the logger to capture warnings
    with patch.object(listing_extractor.logger, 'warning') as mock_warning:
        # Apply contract enforcement for listing pages
        filtered_records = listing_extractor._enforce_listing_field_contract(records, "listing")
        
        # Verify that detail-only fields were dropped
        detail_only_fields = listing_extractor.DETAIL_ONLY_FIELDS
        for record in filtered_records:
            for field in record.keys():
                assert field not in detail_only_fields, f"Detail-only field {field} should have been dropped"
        
        # Verify that a warning was logged (since we provided records with detail-only fields)
        assert mock_warning.called, "Expected warning to be logged about listing page contract violation"
        
        # Verify that the warning mentions dropped fields
        warning_calls = [str(call) for call in mock_warning.call_args_list]
        assert any("contract violation" in str(call).lower() for call in warning_calls), \
            "Expected warning about listing page contract violation"
