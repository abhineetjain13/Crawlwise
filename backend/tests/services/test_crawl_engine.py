from __future__ import annotations

import pytest

from app.services import crawl_fetch_runtime
from app.services.acquisition.host_protection_memory import HostProtectionPolicy
from app.services import detail_extractor
from app.services.adapters.belk import BelkAdapter
from app.services.extract.detail_identity import (
    detail_identity_codes_from_url,
    detail_title_from_url,
    detail_url_is_utility,
    listing_detail_like_path,
)
from app.services.extract.detail_price_extractor import backfill_detail_price_from_html
from app.services.extract.variant_record_normalization import normalize_variant_record
from app.services.extraction_runtime import extract_records
from app.services.listing_extractor import extract_listing_records
from tests.fixtures.loader import read_optional_artifact_text


def test_listing_raw_json_max_records_does_not_trim_page_overshoot() -> None:
    html = (
        "["
        + ",".join(
            f'{{"title":"Product {index}","url":"https://example.com/p/{index}","price":"${index}.00"}}'
            for index in range(1, 6)
        )
        + "]"
    )

    rows = extract_records(
        html,
        "https://example.com/collections/all",
        "ecommerce_listing",
        max_records=3,
        content_type="application/json",
    )

    assert [row["title"] for row in rows] == [
        "Product 1",
        "Product 2",
        "Product 3",
        "Product 4",
        "Product 5",
    ]


def test_detail_product_url_with_support_slug_is_not_utility() -> None:
    assert (
        detail_url_is_utility(
            "https://example.com/products/123-hormone-healthy-eats-support?source=search"
        )
        is False
    )


def test_detail_price_backfill_replaces_visible_outlier_price() -> None:
    record = {
        "url": "https://www.thomann.co.uk/akg_k702.htm",
        "price": "3.95",
        "currency": "GBP",
        "_field_sources": {"price": ["dom_selector"]},
    }
    html = """
    <html>
      <head>
        <meta itemprop="priceCurrency" content="GBP">
        <meta itemprop="price" content="154">
      </head>
      <body>
        <main>
          <h1>AKG K-702</h1>
          <div class="shipping-price">Shipping GBP 3.95</div>
          <div class="product-price">GBP 154</div>
        </main>
      </body>
    </html>
    """

    backfill_detail_price_from_html(record, html=html)

    assert record["price"] == "154"
    assert "dom_text" in record["_field_sources"]["price"]


def test_extract_detail_keeps_encoded_cdn_image_url() -> None:
    image_url = (
        "https://i.example-cdn.com/rs:fit/g:sm/q:90/h:600/w:600/"
        "czM6Ly9pbWFnZXM/LmpwZWc.jpeg"
    )
    rows = extract_records(
        f"""
        <html>
          <head>
            <meta property="og:title" content="Never Gonna Give You Up">
            <meta property="og:image" content="{image_url}">
            <meta property="og:url" content="https://www.discogs.com/release/249504">
            <script type="application/ld+json">{{
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Never Gonna Give You Up",
              "image": "{image_url}",
              "url": "https://www.discogs.com/release/249504",
              "offers": {{"@type": "Offer", "price": "0.68", "priceCurrency": "USD"}}
            }}</script>
          </head>
          <body><h1>Never Gonna Give You Up</h1></body>
        </html>
        """,
        "https://www.discogs.com/release/249504",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://www.discogs.com/release/249504",
    )

    assert rows[0]["image_url"] == image_url


def _js_shell_html() -> str:
    return """
    <html>
      <body>
        <div id="__next"></div>
        <script>window.__INITIAL_STATE__ = {};</script>
        <script>window.__APP_DATA__ = {};</script>
        <script src="/static/app.js"></script>
      </body>
    </html>
    """


def _rendered_listing_fragment(
    *,
    title: str,
    url: str,
    price: str = "",
    image_url: str = "",
    brand: str = "",
) -> str:
    return f"""
    <article class="product-card">
      <a href="{url}">
        {f'<img src="{image_url}" alt="{title}" />' if image_url else ""}
        <h2 class="product-title">{title}</h2>
      </a>
      {f'<div class="product-brand">{brand}</div>' if brand else ""}
      {f'<div class="price">{price}</div>' if price else ""}
    </article>
    """


def test_extract_records_recovers_flattened_listing_cards_from_visual_artifacts() -> None:
    html = """
    <html>
      <body>
        <div class="grid-shell">
          <a href="/products/widget-prime"></a>
          <img src="/images/widget-prime.jpg" alt="Widget Prime">
          <h2>Widget Prime</h2>
          <div>$19.99</div>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "/products/widget-prime",
                    "x": 20,
                    "y": 40,
                    "width": 180,
                    "height": 180,
                    "text": "",
                },
                {
                    "tag": "img",
                    "src": "/images/widget-prime.jpg",
                    "alt": "Widget Prime",
                    "x": 20,
                    "y": 40,
                    "width": 180,
                    "height": 140,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Widget Prime",
                    "x": 24,
                    "y": 190,
                    "width": 170,
                    "height": 24,
                },
                {
                    "tag": "div",
                    "text": "$19.99",
                    "x": 24,
                    "y": 220,
                    "width": 80,
                    "height": 24,
                },
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "visual_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "image_url": "https://example.com/images/widget-prime.jpg",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_extract_records_visual_listing_backfills_brand_from_brand_node_and_url() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/shoes/womens-shoes/sandals/flat/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "/p/northside-dogwood-footbed-sandals/290092111811620.html",
                    "x": 20,
                    "y": 40,
                    "width": 180,
                    "height": 180,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Dogwood Footbed Sandals",
                    "x": 24,
                    "y": 190,
                    "width": 170,
                    "height": 24,
                },
                {
                    "tag": "div",
                    "text": "Northside",
                    "ariaLabel": "brand",
                    "x": 24,
                    "y": 216,
                    "width": 170,
                    "height": 20,
                },
                {
                    "tag": "div",
                    "text": "$24.99",
                    "x": 24,
                    "y": 240,
                    "width": 80,
                    "height": 24,
                },
                {
                    "tag": "a",
                    "href": "/p/dv-dolce-vita-ubar-sandals/2900965UBAR.html",
                    "x": 220,
                    "y": 40,
                    "width": 180,
                    "height": 180,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Ubar Sandals",
                    "x": 224,
                    "y": 190,
                    "width": 170,
                    "height": 24,
                },
                {
                    "tag": "div",
                    "text": "$20.00",
                    "x": 224,
                    "y": 220,
                    "width": 80,
                    "height": 24,
                },
            ]
        },
    )

    assert rows[0]["brand"] == "Northside"
    assert rows[1]["brand"] == "Dv Dolce Vita"


def test_extract_records_visual_listing_rejects_numeric_product_id_brand_prefix() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.desertcart.in/category/fashion/men/accessories",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "/products/492216804-black-leather-belts-for-men?source=category",
                    "x": 20,
                    "y": 40,
                    "width": 180,
                    "height": 180,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Black Leather Belts for Men",
                    "x": 24,
                    "y": 190,
                    "width": 170,
                    "height": 24,
                },
                {
                    "tag": "div",
                    "text": "Rs. 2,791",
                    "x": 24,
                    "y": 220,
                    "width": 80,
                    "height": 24,
                },
            ]
        },
    )

    assert rows[0]["title"] == "Black Leather Belts for Men"
    assert "brand" not in rows[0]


def test_extract_records_reads_desertcart_style_product_anchor_cards() -> None:
    rows = extract_records(
        """
        <html><body>
          <a class="SearchResultsContainer_cardWrapper__0mkW_"
             href="/products/492216804-black-leather-belts-for-men?source=category">
            <div class="ProductCard_productCardContainer__svsD_">
              <img src="/belt.jpg" alt="Black Leather Belts for Men">
              <h3 class="ProductCoreDetails_title__m_0uZ">Black Leather Belts for Men</h3>
              <span>Rs. 2,791</span>
            </div>
          </a>
        </body></html>
        """,
        "https://www.desertcart.in/category/fashion/men/accessories",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows[0]["title"] == "Black Leather Belts for Men"
    assert rows[0]["url"] == (
        "https://www.desertcart.in/products/"
        "492216804-black-leather-belts-for-men?source=category"
    )
    assert "brand" not in rows[0]


def test_extract_records_honors_listing_max_records_above_fragment_default() -> None:
    cards = "\n".join(
        f"""
        <a class="SearchResultsContainer_cardWrapper__0mkW_"
           href="/products/{index}-widget-{index}?source=category">
          <div class="ProductCard_productCardContainer__svsD_">
            <h3 class="ProductCoreDetails_title__m_0uZ">Widget {index}</h3>
            <span>Rs. {1000 + index}</span>
          </div>
        </a>
        """
        for index in range(1, 206)
    )

    rows = extract_records(
        f"<html><body>{cards}</body></html>",
        "https://www.desertcart.in/category/fashion/men/accessories",
        "ecommerce_listing",
        max_records=205,
    )

    assert len(rows) == 205


def test_extract_records_visual_listing_orders_top_grid_before_lower_recommendations() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/men/mens-clothing/sport-coats-blazers/",
        "ecommerce_listing",
        max_records=2,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "img",
                    "href": "/p/crown-ivy-men-s-chambray-sport-coat/3203855BL1962J.html",
                    "src": "/images/sport-coat.jpg",
                    "alt": "Men's Chambray Sport Coat",
                    "x": 907,
                    "y": 582,
                    "width": 349,
                    "height": 499,
                    "score": 30,
                },
                {
                    "tag": "div",
                    "text": "$99.99",
                    "x": 907,
                    "y": 1098,
                    "width": 120,
                    "height": 24,
                    "score": 18,
                },
                {
                    "tag": "img",
                    "href": "/p/izod-advantage-performance-polo-shirt-classic-fit/3203960IZAGB24R.html",
                    "src": "/images/polo.jpg",
                    "alt": "Men's Advantage Performance Polo Shirt Classic Fit",
                    "x": 395,
                    "y": 13129,
                    "width": 160,
                    "height": 228,
                    "score": 4,
                },
                {
                    "tag": "a",
                    "href": "/p/izod-advantage-performance-polo-shirt-classic-fit/3203960IZAGB24R.html",
                    "text": "Quick Add IZOD Men's Advantage Performance Polo Shirt Classic Fit $20.00 after coupon $50.00",
                    "x": 395,
                    "y": 13129,
                    "width": 160,
                    "height": 343,
                    "score": 4,
                },
            ]
        },
    )

    assert rows[0] == {
        "source_url": "https://www.belk.com/men/mens-clothing/sport-coats-blazers/",
        "_source": "visual_listing",
        "title": "Men's Chambray Sport Coat",
        "brand": "Crown Ivy",
        "price": "99.99",
        "currency": "USD",
        "image_url": "https://www.belk.com/images/sport-coat.jpg",
        "url": "https://www.belk.com/p/crown-ivy-men-s-chambray-sport-coat/3203855BL1962J.html",
    }
    assert [row["title"] for row in rows] == [
        "Men's Chambray Sport Coat",
        "Men's Advantage Performance Polo Shirt Classic Fit",
    ]


def test_detail_identity_codes_require_exact_match() -> None:
    assert (
        detail_extractor.detail_identity_codes_match(
            {"ABC12345"},
            {"ABC123456"},
        )
        is False
    )
    assert (
        detail_extractor.detail_identity_codes_match(
            {"ABC12345"},
            {"ABC12345"},
        )
        is True
    )


def test_detail_identity_allows_canonical_product_url_with_variant_sku_suffix() -> None:
    requested_url = (
        "https://savannahs.com/collections/all-boots/products/"
        "shadow-ban-30-soft-leather-black-boots-hl28112s"
    )
    record = {
        "title": "Shadow Ban 30 soft leather black boots - 36",
        "url": (
            "https://savannahs.com/products/"
            "shadow-ban-30-soft-leather-black-boots-hl28112s?variant=43633735827522"
        ),
        "sku": "HL28112S360",
        "description": "Black leather ankle boots from Herbert Levine.",
    }

    assert (
        detail_extractor.detail_record_rejection_reason(
            record,
            page_url=requested_url,
            requested_page_url=requested_url,
        )
        is None
    )


def test_detail_identity_extracts_numeric_hm_product_codes_from_url() -> None:
    url = "https://www2.hm.com/en_in/productpage.1317259001.html"

    assert detail_identity_codes_from_url(url) == {"1317259001"}
    assert detail_title_from_url(url) is None


def test_extract_records_rejects_visual_artifact_cta_and_footer_clusters() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.dyson.in/hair-care/hair-stylers",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "/airwrap-id-multi-styler-dryer-vinca-blue-topaz",
                    "x": 557,
                    "y": 3347,
                    "width": 142,
                    "height": 22,
                    "text": "",
                },
                {
                    "tag": "a",
                    "href": "/airwrap-id-multi-styler-dryer-vinca-blue-topaz",
                    "x": 510,
                    "y": 4026,
                    "width": 236,
                    "height": 68,
                    "text": "Shop now",
                },
                {
                    "tag": "img",
                    "src": "https://dyson-h.assetsadobe2.com/is/image/content/dam/dyson/images/back-up/tick-outline-green.png?scl=1&fmt=png-alpha",
                    "x": 520,
                    "y": 3958,
                    "width": 24,
                    "height": 24,
                    "text": "",
                },
                {
                    "tag": "a",
                    "href": "/products/hair-care/hair-care-accessories",
                    "x": 115,
                    "y": 8048,
                    "width": 478,
                    "height": 40,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Talking to us is easy.",
                    "x": 115,
                    "y": 7969,
                    "width": 478,
                    "height": 68,
                },
                {
                    "tag": "img",
                    "src": "https://dyson-h.assetsadobe2.com/is/image/content/dam/dyson/icons/owner-footer/mydyson/haircare-icon.png?scl=1&fmt=png-alpha",
                    "x": 120,
                    "y": 7890,
                    "width": 48,
                    "height": 48,
                    "text": "",
                },
                {
                    "tag": "a",
                    "href": "https://www.dyson.in/select-your-location",
                    "x": 1281,
                    "y": 8586,
                    "width": 74,
                    "height": 22,
                    "text": "India",
                    "ariaLabel": "select language and region: India",
                },
            ]
        },
    )

    assert rows == []


def test_extract_records_keeps_visual_artifact_product_without_price_when_title_matches_url() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.dyson.in/hair-care/hair-stylers",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "/airwrap-id-multi-styler-dryer-vinca-blue-topaz",
                    "x": 557,
                    "y": 3347,
                    "width": 142,
                    "height": 22,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Airwrap i.d. multi-styler and dryer Vinca Blue/Topaz",
                    "x": 510,
                    "y": 3440,
                    "width": 236,
                    "height": 68,
                },
                {
                    "tag": "img",
                    "src": "https://example.com/images/airwrap-id.jpg",
                    "alt": "Airwrap i.d. multi-styler and dryer Vinca Blue/Topaz",
                    "x": 510,
                    "y": 3508,
                    "width": 236,
                    "height": 236,
                    "text": "",
                },
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www.dyson.in/hair-care/hair-stylers",
            "_source": "visual_listing",
            "title": "Airwrap i.d. multi-styler and dryer Vinca Blue/Topaz",
            "image_url": "https://example.com/images/airwrap-id.jpg",
            "url": "https://www.dyson.in/airwrap-id-multi-styler-dryer-vinca-blue-topaz",
        }
    ]


def test_extract_records_reads_listing_card_data_url_and_rejects_chrome_rows() -> None:
    rows = extract_records(
        """
        <html><body>
          <div class="promos__item promos_title_content">
            <a href="/products/hair-care/hair-care-accessories">Explore accessories</a>
          </div>
          <ul class="products-grid">
            <li class="item product product-item">
              <div class="product-item-link" data-url="/hair-care/hair-straighteners/airstrait-blue-copper">
                <img src="/airstrait-blue.png" alt="">
                <h3 class="card_product_name">
                  <a class="product name product-item-name">Dyson Airstrait dryer and straightener Blue Copper</a>
                </h3>
                <span class="price">₹34,900.00</span>
                <a href="javascript:void(0)">Add to cart</a>
              </div>
            </li>
            <li class="item product product-item">
              <div class="product-item-link" data-url="/hair-care/hair-straighteners/corrale-copper-nickel">
                <img src="/corrale.png" alt="">
                <h3 class="card_product_name">
                  <a class="product name product-item-name">Dyson Corrale straightener Copper Nickel</a>
                </h3>
                <span class="price">₹29,900.00</span>
                <a href="javascript:void(0)">Add to cart</a>
              </div>
            </li>
          </ul>
        </body></html>
        """,
        "https://www.dyson.in/hair-care/hair-straighteners",
        "ecommerce_listing",
        max_records=10,
    )

    assert [row["title"] for row in rows] == [
        "Dyson Airstrait dryer and straightener Blue Copper",
        "Dyson Corrale straightener Copper Nickel",
    ]
    assert rows[0]["url"] == (
        "https://www.dyson.in/hair-care/hair-straighteners/airstrait-blue-copper"
    )
    assert rows[0]["price"] == "34900.00"


def test_extract_records_keeps_adjacent_visual_product_cards_separate() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/beauty/makeup/face-makeup/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "img",
                    "href": "/p/brand-alpha-foundation/111.html",
                    "src": "/images/alpha-a.jpg",
                    "alt": "Alpha Foundation",
                    "x": 204,
                    "y": 582,
                    "width": 349,
                    "height": 499,
                    "text": "",
                },
                {
                    "tag": "img",
                    "href": "/p/brand-alpha-foundation/111.html",
                    "src": "/images/alpha-b.jpg",
                    "alt": "Alpha Foundation",
                    "x": 204,
                    "y": 582,
                    "width": 349,
                    "height": 499,
                    "text": "",
                },
                {
                    "tag": "img",
                    "href": "/p/brand-beta-concealer/222.html",
                    "src": "/images/beta-a.jpg",
                    "alt": "Beta Concealer",
                    "x": 587,
                    "y": 582,
                    "width": 349,
                    "height": 499,
                    "text": "",
                },
                {
                    "tag": "img",
                    "href": "/p/brand-gamma-powder/333.html",
                    "src": "/images/gamma-a.jpg",
                    "alt": "Gamma Powder",
                    "x": 970,
                    "y": 582,
                    "width": 349,
                    "height": 499,
                    "text": "",
                },
            ]
        },
    )

    assert [row["title"] for row in rows] == [
        "Alpha Foundation",
        "Beta Concealer",
        "Gamma Powder",
    ]
    assert [row["url"] for row in rows] == [
        "https://www.belk.com/p/brand-alpha-foundation/111.html",
        "https://www.belk.com/p/brand-beta-concealer/222.html",
        "https://www.belk.com/p/brand-gamma-powder/333.html",
    ]


def test_extract_records_rejects_visual_artifact_auth_links_without_dropping_product() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.customink.com/products/sweatshirts/hoodies/71",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "href": "https://www.customink.com/profiles/users/sign_in",
                    "x": 24,
                    "y": 120,
                    "width": 160,
                    "height": 24,
                    "text": "Sign In",
                },
                {
                    "tag": "h2",
                    "text": "Sign In Sign In",
                    "x": 24,
                    "y": 148,
                    "width": 180,
                    "height": 28,
                },
                {
                    "tag": "a",
                    "href": "https://www.customink.com/products/hoodies/independent-trading-midweight-hooded-sweatshirt/827800",
                    "x": 24,
                    "y": 220,
                    "width": 220,
                    "height": 32,
                    "text": "",
                },
                {
                    "tag": "img",
                    "src": "https://www.customink.com/images/hoodie-1.jpg",
                    "x": 24,
                    "y": 220,
                    "width": 160,
                    "height": 160,
                    "text": "",
                },
                {
                    "tag": "h2",
                    "text": "Independent Trading Midweight Hooded Sweatshirt",
                    "x": 24,
                    "y": 388,
                    "width": 340,
                    "height": 28,
                },
                {
                    "tag": "div",
                    "text": "$39.99",
                    "x": 24,
                    "y": 420,
                    "width": 80,
                    "height": 24,
                },
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www.customink.com/products/sweatshirts/hoodies/71",
            "_source": "visual_listing",
            "title": "Independent Trading Midweight Hooded Sweatshirt",
            "price": "39.99",
            "currency": "USD",
            "image_url": "https://www.customink.com/images/hoodie-1.jpg",
            "url": "https://www.customink.com/products/hoodies/independent-trading-midweight-hooded-sweatshirt/827800",
        }
    ]


def test_extract_records_prefers_image_hint_over_brand_or_review_title_noise() -> None:
    html = """
    <html>
      <body>
        <article class="product-tile">
          <a href="/p/laila-small-satchel/260083130S5S9IS1V.html">
            <img src="/images/laila.jpg" alt="Laila Small Satchel">
          </a>
          <div class="tile-copy">
            <a href="/p/laila-small-satchel/260083130S5S9IS1V.html">
              <div class="font-bold">MICHAEL Michael Kors</div>
            </a>
            <a href="/p/laila-small-satchel/260083130S5S9IS1V.html">
              <div class="line-clamp-2">Laila Small Satchel</div>
            </a>
          </div>
          <a href="/p/laila-small-satchel/260083130S5S9IS1V.html">428 reviews</a>
          <div class="price">$118.80</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.belk.com/handbags",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/handbags",
            "_source": "dom_listing",
            "title": "Laila Small Satchel",
            "price": "118.80",
            "currency": "USD",
            "review_count": 428,
            "image_url": "https://www.belk.com/images/laila.jpg",
            "url": "https://www.belk.com/p/laila-small-satchel/260083130S5S9IS1V.html",
        }
    ]


def test_extract_records_filters_blocked_detail_artifact_html() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/20/pages/41f3046f3de7bf0e.html",
        fixture_subdir="artifact_html",
    )

    rows = extract_records(
        html,
        "https://www.belk.com/p/michael-michael-kors-scarlett-medium-satchel-/260083130F4GETS2B.html",
        "ecommerce_detail",
        max_records=5,
    )

    assert rows == []


def test_extract_records_cleans_titles_from_belk_listing_artifact() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/19/pages/a0c2607fa750138d.html",
        fixture_subdir="artifact_html",
    )

    rows = extract_records(
        html,
        "https://www.belk.com/shop-by-brand",
        "ecommerce_listing",
        max_records=12,
    )

    assert rows
    titles = {str(row.get("title") or "") for row in rows[:12]}
    assert "Laila Small Satchel" in titles
    assert "Lucca Leather Hobo Bag" in titles
    assert all("review" not in str(row.get("title") or "").lower() for row in rows[:12])
    assert "Dooney & Bourke" not in titles


def test_extract_records_belk_listing_artifact_does_not_emit_currency_without_price() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/22/pages/5e2f27bc09df481d.html",
        fixture_subdir="artifact_html",
    )

    rows = extract_records(
        html,
        "https://www.belk.com/men/mens-clothing/pants/",
        "ecommerce_listing",
        max_records=100,
    )

    assert rows
    assert all(row.get("price") or not row.get("currency") for row in rows)


def test_extract_records_drops_orphan_listing_currency_without_price() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "ItemList",
              "itemListElement": [
                {
                  "@type": "ListItem",
                  "position": 1,
                  "item": {
                    "@type": "Product",
                    "name": "Widget Prime",
                    "url": "https://example.com/products/widget-prime",
                    "offers": {
                      "@type": "Offer",
                      "priceCurrency": "USD"
                    }
                  }
                }
              ]
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
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "structured_listing",
            "title": "Widget Prime",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_extract_records_rejects_redirected_belk_detail_artifact_identity_mismatch() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/23/pages/ee049a2bdeed124a.html",
        fixture_subdir="artifact_html",
    )
    requested_url = (
        "https://www.belk.com/p/haggar-premium-stretch-no-iron-khaki-classic-fit-hidden-expandable-"
        "waistband-flat-front-pants/3200645HC10884.html?dwvar_3200645HC10884_color=251278239931"
    )
    canonical_url = "https://www.belk.com/p/kenneth-cole-mens-reaction-urban-heather-dress-pants-/3200898KD00379.html"

    rows = extract_records(
        html,
        canonical_url,
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert rows == []


def test_extract_records_recovers_variants_and_cleans_color_from_belk_detail_artifact() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/23/pages/ee049a2bdeed124a.html",
        fixture_subdir="artifact_html",
    )
    canonical_url = "https://www.belk.com/p/kenneth-cole-mens-reaction-urban-heather-dress-pants-/3200898KD00379.html"

    rows = extract_records(
        html,
        canonical_url,
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["color"] == "HTR GREY"
    assert record["variant_count"] == 6


def test_extract_records_normalizes_belk_run_26_detail_variants_without_duplicate_axes() -> None:
    html = read_optional_artifact_text(
        "artifacts/runs/26/pages/612cf7570cdbf8e1.html",
        fixture_subdir="artifact_html",
    )
    canonical_url = (
        "https://www.belk.com/p/kim-rogers-womens-denim-capri-pants/180430334287262.html"
        "?dwvar_180430334287262_color=460475611850"
    )

    rows = extract_records(
        html,
        canonical_url,
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Women's Denim Capri Pants"
    assert record["availability"] == "in_stock"
    assert len(record["variants"]) == 21
    assert all("price" not in variant for variant in record["variants"])
    assert all("currency" not in variant for variant in record["variants"])
    assert all("availability" not in variant for variant in record["variants"])

    def _has_axis(variant: dict) -> bool:
        if variant.get("color") or variant.get("size"):
            return True
        option_values = variant.get("option_values")
        return isinstance(option_values, dict) and any(
            option_values.get(axis) for axis in ("color", "size")
        )

    assert all(_has_axis(variant) for variant in record["variants"])


def test_extract_records_normalizes_boolean_availability_and_shared_variant_price_from_json() -> None:
    html = """
    {
      "title": "Trail Runner",
      "price": "26.99",
      "currency": "USD",
      "availability": true,
      "variant_axes": {
        "size": ["6", "8"],
        "color": ["Blue", "Black"]
      },
      "variants": [
        {"option_values": {"size": "6", "color": "Blue"}},
        {"option_values": {"size": "8", "color": "Blue"}}
      ],
      "selected_variant": {
        "option_values": {"size": "6", "color": "Blue"}
      }
    }
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
        content_type="application/json",
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["availability"] == "in_stock"
    assert record["price"] == "26.99"
    assert record["currency"] == "USD"


def test_extract_records_prefers_rendered_listing_fragments_over_thin_structured_records() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "Product",
              "name": "Widget Prime",
              "url": "/products/widget-prime"
            },
            {
              "@type": "Product",
              "name": "Widget Pro",
              "url": "/products/widget-pro"
            }
          ]
        }
        </script>
      </head>
      <body><div id="__next"></div></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Widget Prime",
                    url="https://example.com/products/widget-prime",
                    price="$19.99",
                    image_url="https://example.com/images/widget-prime.jpg",
                    brand="Acme",
                ),
                _rendered_listing_fragment(
                    title="Widget Pro",
                    url="https://example.com/products/widget-pro",
                    price="$29.99",
                    image_url="https://example.com/images/widget-pro.jpg",
                    brand="Acme",
                ),
            ]
        },
    )

    assert len(rows) == 2
    assert rows[0]["_source"] == "dom_listing"
    assert rows[0]["price"] == "19.99"
    assert rows[0]["image_url"] == "https://example.com/images/widget-prime.jpg"


def test_extract_records_prefers_browser_visual_rows_over_weak_promo_dom_rows() -> None:
    html = """
    <html><body>
      <section>
        <a href="/handbags/">Sunnies Sunglasses Shop</a>
        <span>$50</span>
      </section>
      <section>
        <a href="/mothers-day/">Designer Handbags & Accessories</a>
        <span>$25</span>
      </section>
    </body></html>
    """

    rows = extract_records(
        html,
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "listing_visual_elements": [
                {
                    "tag": "a",
                    "text": "Super Soft Solid Microfiber Sheet Set",
                    "href": "https://www.belk.com/p/modern-southern-home--super-soft-solid-microfiber-sheet-set-/92007011175487.html",
                    "x": 10,
                    "y": 20,
                    "width": 220,
                    "height": 40,
                },
                {
                    "tag": "span",
                    "text": "$22.50",
                    "x": 10,
                    "y": 70,
                    "width": 80,
                    "height": 20,
                },
                {
                    "tag": "a",
                    "text": "Signature Bath Rug",
                    "href": "https://www.belk.com/p/modern-southern-home---signature-bath-rug/920089711724242.html",
                    "x": 10,
                    "y": 140,
                    "width": 220,
                    "height": 40,
                },
                {
                    "tag": "span",
                    "text": "$18.00",
                    "x": 10,
                    "y": 190,
                    "width": 80,
                    "height": 20,
                },
                {
                    "tag": "a",
                    "text": "Basic Bath Bundle",
                    "href": "https://www.belk.com/p/modern-southern-home--basic-bath-bundle-/920071211789570.html",
                    "x": 10,
                    "y": 260,
                    "width": 220,
                    "height": 40,
                },
                {
                    "tag": "span",
                    "text": "$34.00",
                    "x": 10,
                    "y": 310,
                    "width": 80,
                    "height": 20,
                },
            ]
        },
    )

    assert len(rows) == 3
    assert {row["_source"] for row in rows} == {"visual_listing"}
    assert {row["title"] for row in rows} == {
        "Super Soft Solid Microfiber Sheet Set",
        "Signature Bath Rug",
        "Basic Bath Bundle",
    }


def test_extract_records_enriches_generic_listing_rows_from_matching_adapter_rows() -> None:
    html = """
    <html><body>
      <article class="product-card">
        <a href="/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html">Checkerboard Quilt Set</a>
        <span>$22.50</span>
      </article>
    </body></html>
    """

    rows = extract_records(
        html,
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        adapter_records=[
            {
                "title": "Checkerboard Quilt Set",
                "brand": "Modern Southern Home",
                "url": "https://www.belk.com/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html",
                "_source": "belk_adapter",
            }
        ],
    )

    assert rows[0]["_source"] == "dom_listing"
    assert rows[0]["brand"] == "Modern Southern Home"
    assert rows[0]["price"] == "22.50"


@pytest.mark.asyncio
async def test_belk_adapter_extracts_listing_brand_from_state_and_tiles() -> None:
    html = """
    <html>
      <body>
        <script>
          window.__INITIAL_STATE__ = {
            "search": {
              "products": [
                {
                  "productName": "Slim Straight Jeans",
                  "brandName": "Polo Ralph Lauren",
                  "productUrl": "/p/polo-ralph-lauren-slim-straight-jeans/123.html",
                  "salePrice": "$89.50",
                  "imageUrl": "https://belk.scene7.com/is/image/Belk/123"
                }
              ]
            }
          };
        </script>
        <article class="product-tile">
          <a href="/p/polo-ralph-lauren-slim-straight-jeans/123.html">
            <img src="https://belk.scene7.com/is/image/Belk/123" alt="Slim Straight Jeans">
            <span class="product-name">Slim Straight Jeans</span>
          </a>
          <span class="product-brand">Polo Ralph Lauren</span>
          <span class="price">$89.50</span>
        </article>
      </body>
    </html>
    """

    result = await BelkAdapter().extract(
        "https://www.belk.com/c/men-jeans/",
        html,
        "ecommerce_listing",
    )

    assert result.records[0]["brand"] == "Polo Ralph Lauren"
    assert result.records[0]["title"] == "Slim Straight Jeans"
    assert result.records[0]["price"] == "89.50"


@pytest.mark.asyncio
async def test_belk_adapter_extracts_title_brand_from_rendered_card_attrs() -> None:
    html = """
    <html><body>
      <article class="product-tile" data-cnstrc-item-name="Cuddlebed 2.0 Mattress Pad" data-cnstrc-item-id="92002171202220">
        <a href="/p/cuddlebed-cuddlebed-2-0-mattress-pad/92002171202220.html">
          <img alt="Cuddlebed 2.0 Mattress Pad" src="https://belk.scene7.com/is/image/Belk/9200217">
        </a>
        <span>$22.50</span>
      </article>
      <article class="product-tile" data-cnstrc-item-name="Crown &amp; Ivy™ Hydrangea Vase">
        <a href="/p/crown-ivy-hydrangea-vase/760161676226SPH0073IJ.html">
          <img alt="Crown &amp; Ivy™ Hydrangea Vase" src="https://belk.scene7.com/is/image/Belk/7601616">
        </a>
      </article>
    </body></html>
    """

    result = await BelkAdapter().extract(
        "https://www.belk.com/home/",
        html,
        "ecommerce_listing",
    )

    assert result.records[0]["title"] == "Cuddlebed 2.0 Mattress Pad"
    assert result.records[0]["brand"] == "Cuddlebed"
    assert result.records[0]["price"] == "22.50"
    assert result.records[0]["product_id"] == "92002171202220"
    assert result.records[1]["brand"] == "Crown & Ivy™"


@pytest.mark.asyncio
async def test_belk_adapter_infers_brand_from_url_when_title_is_truncated() -> None:
    html = """
    <html><body>
      <article class="product-tile" data-cnstrc-item-name="500 Thread Count Damask Strip US Grown Cotton Softy-Around 95/5 Goose Feather/Down Pillow (2...">
        <a href="/p/beautyrest-500-thread-count-damask-stripe-us-grown-cotton-softy-around-95-5-goose-feather-down-pillow/92002171202220.html">
          <img alt="500 Thread Count Damask Strip US Grown Cotton Softy-Around 95/5 Goose Feather/Down Pillow (2..." src="https://belk.scene7.com/is/image/Belk/9200217">
        </a>
        <span>$75.50 - $95.50</span>
      </article>
    </body></html>
    """

    result = await BelkAdapter().extract(
        "https://www.belk.com/home/",
        html,
        "ecommerce_listing",
    )

    assert result.records[0]["brand"] == "Beautyrest"
    assert result.records[0]["price"] == "75.50"


def test_listing_extractor_extracts_brand_from_product_tile() -> None:
    rows = extract_records(
        """
        <html><body>
          <article class="product-tile">
            <a href="/p/polo-ralph-lauren-slim-straight-jeans/123.html">
              <img src="/images/123.jpg" alt="Slim Straight Jeans">
              <span class="product-name">Slim Straight Jeans</span>
            </a>
            <span class="product-brand">Polo Ralph Lauren</span>
            <span class="price">$89.50</span>
          </article>
        </body></html>
        """,
        "https://www.belk.com/c/men-jeans/",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows[0]["brand"] == "Polo Ralph Lauren"


def test_listing_extractor_does_not_infer_belk_brand_from_pdp_slug_when_fragment_lacks_brand() -> None:
    rows = extract_records(
        """
        <html><body>
          <article>
            <a href="/p/polo-ralph-lauren-6-inch-polo-prepster-stretch-twill-shorts/320160211731376.html?dwvar_320160211731376_color=250312822425">
              <img src="/images/123.jpg" alt="6 Inch Polo Prepster Stretch Twill Shorts">
              <span>6 Inch Polo Prepster Stretch Twill Shorts</span>
            </a>
            <span class="price">$225.00</span>
          </article>
        </body></html>
        """,
        "https://www.belk.com/men/mens-clothing/shorts/",
        "ecommerce_listing",
        max_records=10,
    )

    assert "brand" not in rows[0]


def test_extract_records_prefers_generic_listing_rows_over_thin_adapter_rows() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.myntra.com/hand-towels",
        "ecommerce_listing",
        max_records=10,
        adapter_records=[
            {
                "title": "Microfiber Face Towel",
                "url": "https://www.myntra.com/products/microfiber-face-towel",
                "brand": "Personal Touch Skincare",
                "_source": "myntra_adapter",
            }
        ],
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Microfiber Face Towel",
                    url="https://www.myntra.com/products/microfiber-face-towel",
                    price="Rs. 499",
                    image_url="https://assets.myntassets.com/assets/images/towel.jpg",
                    brand="Personal Touch Skincare",
                )
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www.myntra.com/hand-towels",
            "_source": "dom_listing",
            "title": "Microfiber Face Towel",
            "url": "https://www.myntra.com/products/microfiber-face-towel",
            "price": "499",
            "currency": "INR",
            "image_url": "https://assets.myntassets.com/assets/images/towel.jpg",
            "brand": "Personal Touch Skincare",
        }
    ]


def test_extract_records_drops_rendered_listing_utility_rows_when_real_products_exist() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Product Help",
                    url="https://example.com/help/product-help",
                ),
                _rendered_listing_fragment(
                    title="Widget Prime",
                    url="https://example.com/products/widget-prime",
                    price="$19.99",
                    image_url="https://example.com/images/widget-prime.jpg",
                ),
                _rendered_listing_fragment(
                    title="Widget Pro",
                    url="https://example.com/products/widget-pro",
                    price="$29.99",
                    image_url="https://example.com/images/widget-pro.jpg",
                ),
            ]
        },
    )

    assert [row["title"] for row in rows] == ["Widget Prime", "Widget Pro"]
    assert all("/products/" in row["url"] for row in rows)


def test_extract_records_drops_detail_like_category_links_without_product_signals() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.customink.com/products/sweatshirts/hoodies/71",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Short Sleeve T-shirts",
                    url="https://www.customink.com/products/t-shirts/short-sleeve-t-shirts/16",
                ),
                _rendered_listing_fragment(
                    title="Women's T-shirts",
                    url="https://www.customink.com/products/t-shirts/womens-t-shirts/104",
                ),
                _rendered_listing_fragment(
                    title="Independent Trading Midweight Hooded Sweatshirt",
                    url="https://www.customink.com/products/hoodies/independent-trading-midweight-hooded-sweatshirt/827800",
                    price="$39.99",
                    image_url="https://www.customink.com/images/hoodie-1.jpg",
                ),
                _rendered_listing_fragment(
                    title="Gildan Heavy Blend Hooded Sweatshirt",
                    url="https://www.customink.com/products/hoodies/gildan-heavy-blend-hooded-sweatshirt/836000",
                    price="$29.99",
                    image_url="https://www.customink.com/images/hoodie-2.jpg",
                ),
            ]
        },
    )

    assert [row["title"] for row in rows] == [
        "Independent Trading Midweight Hooded Sweatshirt",
        "Gildan Heavy Blend Hooded Sweatshirt",
    ]


def test_extract_records_rejects_concatenated_resource_menu_listing_titles() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.customink.com/products/sweatshirts/hoodies/71",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Tools & Resources Group Ordering Fundraising Online Stores Pro Services Tips & Advice T-shirt Maker",
                    url="https://www.customink.com/fundraising",
                ),
                _rendered_listing_fragment(
                    title="Independent Trading Midweight Hooded Sweatshirt",
                    url="https://www.customink.com/products/hoodies/independent-trading-midweight-hooded-sweatshirt/827800",
                    price="$39.99",
                    image_url="https://www.customink.com/images/hoodie-1.jpg",
                ),
            ]
        },
    )

    assert [row["title"] for row in rows] == [
        "Independent Trading Midweight Hooded Sweatshirt",
    ]


def test_extract_records_drops_shallow_editorial_listing_links_without_product_signals() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.customink.com/products/sweatshirts/hoodies/71",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Diversity & Belonging",
                    url="https://www.customink.com/equity-for-all",
                ),
                _rendered_listing_fragment(
                    title="Customer Reviews",
                    url="https://www.customink.com/reviews",
                ),
                _rendered_listing_fragment(
                    title="Customer Photos",
                    url="https://www.customink.com/photos",
                ),
                _rendered_listing_fragment(
                    title="T-shirt Maker",
                    url="https://www.customink.com/services/t-shirt-maker-creator",
                ),
                _rendered_listing_fragment(
                    title="Corporate Swag",
                    url="https://www.customink.com/ink/business/corporate-swag-branded-merchandise",
                ),
                _rendered_listing_fragment(
                    title="Content Guidelines",
                    url="https://www.customink.com/help_center/content-guidelines",
                ),
                _rendered_listing_fragment(
                    title="Custom Products",
                    url="https://www.customink.com/ink/custom-products",
                ),
                _rendered_listing_fragment(
                    title="Sign In Sign In",
                    url="https://www.customink.com/profiles/users/sign_in",
                ),
                _rendered_listing_fragment(
                    title="Independent Trading Midweight Hooded Sweatshirt",
                    url="https://www.customink.com/products/hoodies/independent-trading-midweight-hooded-sweatshirt/827800",
                    price="$39.99",
                    image_url="https://www.customink.com/images/hoodie-1.jpg",
                ),
            ]
        },
    )

    assert [row["title"] for row in rows] == [
        "Independent Trading Midweight Hooded Sweatshirt",
    ]


def test_extract_records_drops_rendered_listing_download_app_cta_rows() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.reverb.com/marketplace?product_type=electric-guitars",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Download the Reverb App",
                    url="https://reverb.com/featured/reverb-app",
                )
            ]
        },
    )

    assert rows == []


def test_extract_records_drops_rendered_listing_category_hub_rows_without_supporting_signals() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.karenmillen.com/eu/categories/womens-trousers",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Womens Clothing",
                    url="https://www.karenmillen.com/eu/categories/womens-clothing",
                )
            ]
        },
    )

    assert rows == []


def test_extract_records_rejects_footer_policy_links_on_skeleton_plp() -> None:
    html = """
    <html>
      <body>
        <main>
          <div class="PLP_placeholderWrap">
            <div class="ProductCardSkeleton productSkeleton"></div>
          </div>
        </main>
        <footer>
          <div class="Footer_uspIcons">
            <a href="https://content.abfrl.in/shipping-policy">
              <img src="https://imagescdn.reebok.in/uploads/micrositmedia/production/alteration_Copy_2alteration-.png" alt="FREE SHIPPING" />
              <span>FREE SHIPPING</span>
            </a>
          </div>
          <div class="Footer_uspIcons">
            <a href="https://content.abfrl.in/returns-cancel-policy">
              <img src="https://imagescdn.reebok.in/uploads/micrositmedia/production/alteration_Copyreturn-1.png" alt="RETURN WITHIN 15 DAYS" />
              <span>RETURN WITHIN 15 DAYS</span>
            </a>
          </div>
        </footer>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://reebok.abfrl.in/c/leggings-and-tights",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == []
    assert (
        extract_listing_records(
            html,
            "https://reebok.abfrl.in/c/leggings-and-tights",
            "ecommerce_listing",
            max_records=10,
        )
        == []
    )


def test_extract_records_recovers_rendered_listing_price_from_fragment_text() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.uniqlo.com/in/en/men/shirts-and-polo-shirts",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Cotton Linen Shirt Jacket Long Sleeve",
                    url="https://www.uniqlo.com/in/en/products/E482443-000/00?colorDisplayCode=38",
                    image_url="https://image.uniqlo.com/UQ/ST3/in/imagesgoods/482443/item/ingoods_69_482443_3x4.jpg?width=300",
                    price="Rs. 3,990.00",
                )
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www.uniqlo.com/in/en/men/shirts-and-polo-shirts",
            "_source": "dom_listing",
            "title": "Cotton Linen Shirt Jacket Long Sleeve",
            "price": "3990.00",
            "currency": "INR",
            "image_url": "https://image.uniqlo.com/UQ/ST3/in/imagesgoods/482443/item/ingoods_69_482443_3x4.jpg?width=300",
            "url": "https://www.uniqlo.com/in/en/products/E482443-000/00?colorDisplayCode=38",
        }
    ]


def test_extract_records_backfills_listing_price_from_network_payload_candidates() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.uniqlo.com/in/en/men/shirts-and-polo-shirts",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Cotton Linen Shirt Jacket Long Sleeve",
                    url="https://www.uniqlo.com/in/en/products/E482443-000/00?colorDisplayCode=38",
                    image_url="https://image.uniqlo.com/UQ/ST3/in/imagesgoods/482443/item/ingoods_38_482443_3x4.jpg",
                )
            ]
        },
        network_payloads=[
            {
                "body": {
                    "result": {
                        "items": [
                            {
                                "productId": "E482443-000",
                                "name": "Cotton Linen Shirt Jacket Long Sleeve",
                                "prices": {
                                    "base": {
                                        "value": 3990,
                                        "currency": {"code": "INR"},
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.uniqlo.com/in/en/men/shirts-and-polo-shirts",
            "_source": "dom_listing",
            "title": "Cotton Linen Shirt Jacket Long Sleeve",
            "url": "https://www.uniqlo.com/in/en/products/E482443-000/00?colorDisplayCode=38",
            "price": "3990",
            "currency": "INR",
            "image_url": "https://image.uniqlo.com/UQ/ST3/in/imagesgoods/482443/item/ingoods_38_482443_3x4.jpg",
        }
    ]


def test_extract_records_backfills_listing_brand_and_range_price_from_network_payload_candidates() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Beyond Down Bed Pillow",
                    url="https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
                    image_url="https://belk.scene7.com/is/image/Belk/9200217",
                )
            ]
        },
        network_payloads=[
            {
                "body": {
                    "result": {
                        "items": [
                            {
                                "productId": "92002171202220",
                                "name": "Beyond Down Bed Pillow",
                                "brandName": "Beyond Down",
                                "offers": {
                                    "lowPrice": "21.00",
                                    "highPrice": "26.00",
                                    "priceCurrency": "USD",
                                },
                            }
                        ]
                    }
                }
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/home/",
            "_source": "dom_listing",
            "title": "Beyond Down Bed Pillow",
            "url": "https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
            "image_url": "https://belk.scene7.com/is/image/Belk/9200217",
            "price": "21.00",
            "currency": "USD",
            "brand": "Beyond Down",
        }
    ]


def test_extract_records_backfills_listing_brand_from_network_when_dom_price_exists() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Beyond Down Bed Pillow",
                    url="https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
                    price="$21.00",
                )
            ]
        },
        network_payloads=[
            {
                "body": {
                    "result": {
                        "items": [
                            {
                                "productId": "92002171202220",
                                "name": "Beyond Down Bed Pillow",
                                "brandName": "Beyond Down",
                                "offers": {
                                    "lowPrice": "21.00",
                                    "highPrice": "26.00",
                                    "priceCurrency": "USD",
                                },
                            }
                        ]
                    }
                }
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/home/",
            "_source": "dom_listing",
            "title": "Beyond Down Bed Pillow",
            "url": "https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
            "price": "21.00",
            "currency": "USD",
            "brand": "Beyond Down",
        }
    ]


def test_extract_records_backfills_listing_brand_from_network_candidate_without_price() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Elite Airflow Jumbo Pillow",
                    url="https://www.belk.com/p/sealy-elite-airflow-jumbo-pillow/92002171202220.html",
                    price="$15.00",
                )
            ]
        },
        network_payloads=[
            {
                "body": {
                    "result": {
                        "items": [
                            {
                                "productId": "92002171202220",
                                "productName": "Elite Airflow Jumbo Pillow",
                                "brandName": "Sealy",
                            }
                        ]
                    }
                }
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/home/",
            "_source": "dom_listing",
            "title": "Elite Airflow Jumbo Pillow",
            "price": "15.00",
            "currency": "USD",
            "url": "https://www.belk.com/p/sealy-elite-airflow-jumbo-pillow/92002171202220.html",
            "brand": "Sealy",
        }
    ]


def test_extract_records_backfills_listing_from_network_by_belk_product_id_when_title_differs() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Promo Copy That Does Not Match Payload Title",
                    url="https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
                    price="$21.00",
                    image_url="https://belk.scene7.com/is/image/Belk/9200217",
                )
            ]
        },
        network_payloads=[
            {
                "body": {
                    "result": {
                        "items": [
                            {
                                "productId": "92002171202220",
                                "name": "Beyond Down Bed Pillow",
                                "brandName": "Beyond Down",
                                "offers": {
                                    "lowPrice": "21.00",
                                    "priceCurrency": "USD",
                                },
                            }
                        ]
                    }
                }
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/home/",
            "_source": "dom_listing",
            "title": "Promo Copy That Does Not Match Payload Title",
            "url": "https://www.belk.com/p/beyond-down-bed-pillow/92002171202220.html",
            "price": "21.00",
            "currency": "USD",
            "brand": "Beyond Down",
        }
    ]


def test_extract_records_backfills_adapter_brand_by_belk_product_identity_when_urls_differ() -> None:
    rows = extract_records(
        """
        <html><body>
          <article>
            <a href="/p/sealy-elite-airflow-jumbo-pillow/92002171202220.html?dwvar_color=White">
              <img src="/images/9200217.jpg" alt="Elite Airflow Jumbo Pillow">
              <span>Elite Airflow Jumbo Pillow</span>
            </a>
            <span class="price">$15.00</span>
          </article>
        </body></html>
        """,
        "https://www.belk.com/home/",
        "ecommerce_listing",
        max_records=10,
        adapter_records=[
            {
                "title": "Elite Airflow Jumbo Pillow",
                "brand": "Sealy",
                "url": "https://www.belk.com/p/sealy-elite-airflow-jumbo-pillow/92002171202220.html",
                "_source": "belk_adapter",
            }
        ],
    )

    assert rows == [
        {
            "source_url": "https://www.belk.com/home/",
            "_source": "dom_listing",
            "title": "Elite Airflow Jumbo Pillow",
            "price": "15.00",
            "currency": "USD",
            "image_url": "https://www.belk.com/images/9200217.jpg",
            "url": "https://www.belk.com/p/sealy-elite-airflow-jumbo-pillow/92002171202220.html?dwvar_color=White",
            "brand": "Sealy",
        }
    ]


def test_extract_records_rejects_external_rendered_listing_utility_links() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www2.hm.com/en_in/men/shoes/view-all.html",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Canvas trainers",
                    url="https://www2.hm.com/en_in/productpage.1309854002.html",
                    price="Rs. 2,799.00",
                ),
                _rendered_listing_fragment(
                    title="Customer Service",
                    url="https://www2.hm.com/en_in/customer-service.html",
                ),
                _rendered_listing_fragment(
                    title="Follow us on Instagram",
                    url="https://www.instagram.com/hm",
                ),
                _rendered_listing_fragment(
                    title="Sustainability",
                    url="https://hmgroup.com/sustainability/",
                ),
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www2.hm.com/en_in/men/shoes/view-all.html",
            "_source": "dom_listing",
            "title": "Canvas trainers",
            "price": "2799.00",
            "currency": "INR",
            "url": "https://www2.hm.com/en_in/productpage.1309854002.html",
        }
    ]


def test_extract_records_prefers_rich_dom_listing_rows_when_structured_rows_fill_limit() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "Product", "name": "widget-one", "url": "/products/widget-one"},
            {"@type": "Product", "name": "widget-two", "url": "/products/widget-two"},
            {"@type": "Product", "name": "widget-three", "url": "/products/widget-three"},
            {"@type": "Product", "name": "widget-four", "url": "/products/widget-four"},
            {"@type": "Product", "name": "widget-five", "url": "/products/widget-five"}
          ]
        }
        </script>
      </head>
      <body>
        <main>
          <section class="product-grid">
            <article class="product-card">
              <a href="/products/widget-one"><img src="/images/widget-one.jpg" alt="Widget One" /><h2>Widget One</h2></a>
              <span class="price">$19.99</span>
            </article>
            <article class="product-card">
              <a href="/products/widget-two"><img src="/images/widget-two.jpg" alt="Widget Two" /><h2>Widget Two</h2></a>
              <span class="price">$29.99</span>
            </article>
            <article class="product-card">
              <a href="/products/widget-three"><img src="/images/widget-three.jpg" alt="Widget Three" /><h2>Widget Three</h2></a>
              <span class="price">$39.99</span>
            </article>
            <article class="product-card">
              <a href="/products/widget-four"><img src="/images/widget-four.jpg" alt="Widget Four" /><h2>Widget Four</h2></a>
              <span class="price">$49.99</span>
            </article>
            <article class="product-card">
              <a href="/products/widget-five"><img src="/images/widget-five.jpg" alt="Widget Five" /><h2>Widget Five</h2></a>
              <span class="price">$59.99</span>
            </article>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=5,
    )

    assert len(rows) == 5
    assert all(row["_source"] == "dom_listing" for row in rows)
    assert all(row["price"] for row in rows)


def test_extract_records_prefers_firstcry_style_dom_cards_over_menu_chrome() -> None:
    html = """
    <html>
      <body>
        <main>
          <ul class="optionav lft">
            <li class="categry inactive">
              <a href="https://www.firstcry.com/club?ref2=menu_dd_catlanding" class="M13_75">
                <img src="https://cdn.fcglcdn.com/brainbees/images/n/club_logo_small.png" alt="FirstCry Club" title="FirstCry Club" />
              </a>
            </li>
            <li class="categry inactive">
              <a href="https://www.firstcry.com/featuredoffer?cpid=7639&ref2=menu_dd_catlanding" class="M13_75">
                <img src="https://cdn.fcglcdn.com/brainbees/images/n/DM-2.gif" alt="Disney Marvel" title="Disney Marvel" />
              </a>
            </li>
          </ul>
          <div class="list_sec fw lft">
            <div class="list_block lft fasnlist">
              <div class="li_inner_block" role="button" tabindex="0" aria-label="Mark &amp; Mia Half Raglan Sleeves Legged Swimsuit - Pink">
                <div class="lblock lft">
                  <div class="list_img wifi">
                    <a href="//www.firstcry.com/mark-and-mia/mark-and-mia-half-raglan-sleeves-legged-swimsuit-pink/21807023/product-detail" target="_blank">
                      <img src="//cdn.fcglcdn.com/brainbees/images/products/300x364/21807023a.webp" alt="Mark &amp; Mia Half Raglan Sleeves Legged Swimsuit - Pink" />
                    </a>
                  </div>
                  <div class="li_txt1 wifi lft">
                    <a href="//www.firstcry.com/mark-and-mia/mark-and-mia-half-raglan-sleeves-legged-swimsuit-pink/21807023/product-detail" target="_blank">
                      Mark &amp; Mia Half Raglan Sleeves Legged Swimsuit - Pink
                    </a>
                  </div>
                  <div class="rupee fw lft" aria-label="Sale price RS 959.2 and Regular price RS 1199">
                    <span class="r1 B14_42">
                      <a aria-label="Sale price RS 959.2" href="//www.firstcry.com/mark-and-mia/mark-and-mia-half-raglan-sleeves-legged-swimsuit-pink/21807023/product-detail" target="_blank">959.2</a>
                    </span>
                    <span class="r2 R12_42">
                      <a aria-label="Regular price RS 1199" href="//www.firstcry.com/mark-and-mia/mark-and-mia-half-raglan-sleeves-legged-swimsuit-pink/21807023/product-detail" target="_blank">
                        <del class="regular-price">1199</del>
                      </a>
                    </span>
                  </div>
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
        "https://www.firstcry.com/topoffers?moid=50920&gender=girl,unisex&ref2=menu_dd_girl-fashion_swimming-essentials_H",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://www.firstcry.com/topoffers?moid=50920&gender=girl,unisex&ref2=menu_dd_girl-fashion_swimming-essentials_H",
            "_source": "dom_listing",
            "title": "Mark & Mia Half Raglan Sleeves Legged Swimsuit - Pink",
            "url": "https://www.firstcry.com/mark-and-mia/mark-and-mia-half-raglan-sleeves-legged-swimsuit-pink/21807023/product-detail",
            "price": "959.2",
            "currency": "INR",
            "image_url": "https://cdn.fcglcdn.com/brainbees/images/products/300x364/21807023a.webp",
        }
    ]


def test_extract_records_prefers_sigma_style_product_rows_over_editorial_links() -> None:
    html = """
    <html>
      <body>
        <main>
          <section class="resource-list">
            <article>
              <a class="css-by2t45-title" href="/IN/en/technical-documents/technical-article/cell-culture-and-cell-culture-analysis/mammalian-cell-culture/antibiotics-in-cell-culture">
                Article: Why Use Antibiotics in Cell Culture?
              </a>
            </article>
            <article>
              <a class="css-by2t45-title" href="/deepweb/assets/sigmaaldrich/marketing/global/documents/749/633/68966-anti-cancer-antibiotics-flyer-030926-ms.pdf">
                Flyer: Anti-Cancer Antibiotics and Inhibitors in Cancer Research
              </a>
            </article>
          </section>
          <div class="css-a4qnmt-resultsWrapper">
            <div class="css-1vkrqo7-tBodyRow">
              <div class="css-1nu0m23-productNumber">
                <a href="/IN/en/product/sigma/a5955">A5955</a>
              </div>
              <div class="css-13uu5bz-productName">
                <a href="/IN/en/product/sigma/a5955"><b><span>Antibiotic Antimycotic Solution (100×), Stabilized</span></b></a>
              </div>
              <div class="css-18jhhth-description">
                <a href="/IN/en/product/sigma/a5955"><span>suspension, suitable for cell culture, BioReagent</span></a>
              </div>
              <div class="css-26xuj3-pricingColumn">
                <button type="button">View Pricing</button>
              </div>
            </div>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.sigmaaldrich.com/IN/en/products/chemistry-and-biochemicals/biochemicals/antibiotics",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://www.sigmaaldrich.com/IN/en/products/chemistry-and-biochemicals/biochemicals/antibiotics",
            "_source": "dom_listing",
            "title": "Antibiotic Antimycotic Solution (100×), Stabilized",
            "description": "suspension, suitable for cell culture, BioReagent",
            "url": "https://www.sigmaaldrich.com/IN/en/product/sigma/a5955",
        }
    ]


def test_extract_records_recovers_listing_price_when_card_uses_currency_code_text() -> None:
    html = """
    <html>
      <body>
        <main>
          <article class="product-card">
            <a href="/products/teddy-tshirt">
              <h2>Teddy T-shirt</h2>
            </a>
            <div class="price-copy">GBP 90</div>
            <img src="https://cdn.example.com/teddy.jpg" alt="Teddy T-shirt" />
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/tees",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/tees",
            "_source": "dom_listing",
            "title": "Teddy T-shirt",
            "url": "https://example.com/products/teddy-tshirt",
            "price": "90",
            "currency": "GBP",
            "image_url": "https://cdn.example.com/teddy.jpg",
        }
    ]


def test_extract_records_replaces_generic_item_listing_title_with_product_text() -> None:
    html = """
    <html>
      <body>
        <div class="thumbnail">
          <h4 class="title">item</h4>
          <a href="/test-sites/e-commerce/allinone/product/1">
            Lenovo ThinkPad X1 Carbon
          </a>
          <p class="description">Lenovo ThinkPad X1 Carbon business laptop</p>
          <h4 class="price">$1,299.00</h4>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Lenovo ThinkPad X1 Carbon"


def test_extract_records_infers_listing_currency_from_locale_path_for_bare_price() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/gb/products/widget"><h2>Widget Prime</h2></a>
          <span class="price">24.99</span>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/gb/products",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["price"] == "24.99"
    assert rows[0]["currency"] == "GBP"


def test_extract_records_ignores_discount_badge_images_inside_listing_cards() -> None:
    html = """
    <html>
      <body>
        <main>
          <div class="category-product">
            <div class="image-wrapper grow">
              <img class="offer-tag" src="/media/catalog/category/flat50_tag.png" alt="discount info" />
              <a href="/zivame-satin-pyjama-set-samba.html?productId=874218">
                <img
                  class="prd-grid-image"
                  src="https://cdn.example.com/media/mimages/rb/solid-loader.gif"
                  data-original="https://cdn.example.com/zivame-satin-pyjama-set-samba.jpg"
                  alt="Buy Zivame Satin Pyjama Set - Samba"
                  title="Zivame Satin Pyjama Set - Samba"
                />
              </a>
            </div>
            <div class="product-name">Buy Zivame Satin Pyjama Set - Samba</div>
            <div class="price">₹1148</div>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
            "_source": "dom_listing",
            "title": "Zivame Satin Pyjama Set - Samba",
            "url": "https://www.zivame.com/zivame-satin-pyjama-set-samba.html?productId=874218",
            "price": "1148",
            "currency": "INR",
            "image_url": "https://cdn.example.com/zivame-satin-pyjama-set-samba.jpg",
        }
    ]


def test_extract_records_replaces_review_only_listing_titles_with_product_image_title() -> None:
    html = """
    <html>
      <body>
        <main>
          <div class="category-product">
            <div class="image-wrapper grow">
              <a href="/zivame-cup-cake-knit-poly-pyjama-set-1.html?productId=858985">
                <img
                  class="prd-grid-image"
                  src="https://cdn.example.com/zivame-cup-cake-knit-poly-pyjama-set.jpg"
                  alt="Buy Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint"
                  title="Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint"
                />
              </a>
            </div>
            <h3 class="product-name">1 reviews given by verified buyers</h3>
            <div class="price">₹775</div>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
            "_source": "dom_listing",
            "title": "Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint",
            "url": "https://www.zivame.com/zivame-cup-cake-knit-poly-pyjama-set-1.html?productId=858985",
            "price": "775",
            "currency": "INR",
            "image_url": "https://cdn.example.com/zivame-cup-cake-knit-poly-pyjama-set.jpg",
            "review_count": 1,
        }
    ]


def test_extract_records_replaces_review_only_titles_from_lazy_loaded_product_images() -> None:
    html = """
    <html>
      <body>
        <main>
          <div class="category-product">
            <div class="image-wrapper grow">
              <a href="/zivame-cup-cake-knit-poly-pyjama-set-1.html?productId=858985">
                <img
                  class="prd-grid-image"
                  src="https://cdn.example.com/media/mimages/rb/solid-loader.gif"
                  data-original="https://cdn.example.com/zivame-cup-cake-knit-poly-pyjama-set.jpg"
                  alt="Buy Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint"
                  title="Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint"
                />
              </a>
            </div>
            <h3 class="product-name">1 reviews given by verified buyers</h3>
            <div class="price">₹775</div>
          </div>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
        "ecommerce_listing",
        max_records=5,
    )

    assert rows == [
        {
            "source_url": "https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html",
            "_source": "dom_listing",
            "title": "Zivame Cup Cake Knit Poly Pyjama Set - Orchid Tint",
            "url": "https://www.zivame.com/zivame-cup-cake-knit-poly-pyjama-set-1.html?productId=858985",
            "price": "775",
            "currency": "INR",
            "image_url": "https://cdn.example.com/zivame-cup-cake-knit-poly-pyjama-set.jpg",
            "review_count": 1,
        }
    ]


def test_extract_records_rejects_dom_listing_rows_that_only_have_doc_titles_and_urls() -> None:
    html = """
    <html>
      <body>
        <main>
          <article class="category-product">
            <a href="/IN/en/technical-documents/technical-article/cell-culture-and-cell-culture-analysis/mammalian-cell-culture/antibiotics-in-cell-culture">
              Article: Why Use Antibiotics in Cell Culture?
            </a>
          </article>
          <article class="category-product">
            <a href="/deepweb/assets/sigmaaldrich/marketing/global/documents/749/633/68966-anti-cancer-antibiotics-flyer-030926-ms.pdf">
              Flyer: Anti-Cancer Antibiotics and Inhibitors in Cancer Research
            </a>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.sigmaaldrich.com/IN/en/products/chemistry-and-biochemicals/biochemicals/antibiotics",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == []


def test_extract_records_rejects_product_name_placeholder_listing_rows() -> None:
    html = """
    <html>
      <body>
        <main>
          <article class="product-card">
            <a href="/termsofuse">Product Name</a>
            <span class="price">₹0</span>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.firstcry.com/sets-and--suits/6/166?scat=166&gender=girl,unisex&ref2=menu_dd_girl-fashion_sets-and-suits_H",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == []


def test_extract_records_rejects_shipping_only_rendered_listing_rows() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="+CHF16.75 shipping",
                    url="https://example.com/shipping",
                )
            ]
        },
    )

    assert rows == []


def test_extract_records_rejects_rendered_listing_cta_only_titles() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.discogs.com/sell/list",
        "ecommerce_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Make Offer / Details",
                    url="https://www.discogs.com/sell/item/3970919917?ev=bp_det",
                ),
                _rendered_listing_fragment(
                    title="Widget Prime",
                    url="https://www.discogs.com/products/widget-prime",
                    price="$19.99",
                    image_url="https://www.discogs.com/images/widget-prime.jpg",
                ),
            ]
        },
    )

    assert rows == [
        {
            "source_url": "https://www.discogs.com/sell/list",
            "_source": "dom_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "image_url": "https://www.discogs.com/images/widget-prime.jpg",
            "url": "https://www.discogs.com/products/widget-prime",
        }
    ]


def test_extract_records_rejects_job_listing_hub_links_when_structured_job_rows_exist() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "JobPosting",
              "title": "Backend Engineer",
              "url": "/job-123-backend-engineer-at-example-bangalore/"
            },
            {
              "@type": "JobPosting",
              "title": "Data Engineer",
              "url": "/job-456-data-engineer-at-example-remote/"
            }
          ]
        }
        </script>
      </head>
      <body><div id="app"></div></body>
    </html>
    """

    rows = extract_records(
        html,
        "https://jobs.example.com/search-jobs",
        "job_listing",
        max_records=10,
        artifacts={
            "rendered_listing_fragments": [
                _rendered_listing_fragment(
                    title="Jobs in Bangalore",
                    url="https://jobs.example.com/jobs-in-bangalore/",
                ),
                _rendered_listing_fragment(
                    title="Product Academy",
                    url="https://academy.example.com/product/",
                ),
            ]
        },
    )

    assert len(rows) == 2
    assert all(row["_source"] == "structured_listing" for row in rows)
    assert rows[0]["title"] == "Backend Engineer"
    assert (
        rows[0]["url"]
        == "https://jobs.example.com/job-123-backend-engineer-at-example-bangalore/"
    )
    assert rows[1]["title"] == "Data Engineer"
    assert (
        rows[1]["url"]
        == "https://jobs.example.com/job-456-data-engineer-at-example-remote/"
    )


def test_extract_records_keeps_job_detail_like_titles_even_when_they_start_with_hub_text() -> None:
    html = """
    <html>
      <body>
        <article class="job-card">
          <a href="/jobs/backend-engineer-123456">Jobs in Bangalore - Backend Engineer</a>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://jobs.example.com/search",
        "job_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://jobs.example.com/search",
            "_source": "dom_listing",
            "title": "Jobs in Bangalore - Backend Engineer",
            "url": "https://jobs.example.com/jobs/backend-engineer-123456",
        }
    ]


def test_extract_records_keeps_job_listing_slug_records_with_numeric_terminal_ids() -> None:
    html = """
    <html>
      <body>
        <div class="job-listing">
          <a href="/lead-ai-engineer-sherlockdefi-6650681">Lead AI Engineer</a>
        </div>
        <div class="job-listing">
          <a href="/founding-engineer-with-equity-miru-technology-inc-7933051">
            Founding Engineer (with equity)
          </a>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://startup.jobs/",
        "job_listing",
        max_records=10,
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Lead AI Engineer"
    assert (
        rows[0]["url"] == "https://startup.jobs/lead-ai-engineer-sherlockdefi-6650681"
    )
    assert rows[1]["title"] == "Founding Engineer (with equity)"
    assert (
        rows[1]["url"]
        == "https://startup.jobs/founding-engineer-with-equity-miru-technology-inc-7933051"
    )


def test_extract_records_rejects_numeric_non_job_links_on_careers_hosts() -> None:
    html = """
    <html>
      <body>
        <article>
          <a href="https://www.clarkassociatesinc.biz/public-relations/2025-ceo-letter/">
            2025 CEO Letter
          </a>
        </article>
        <article>
          <a href="https://www.clarkassociatesinc.biz/companies/11400/">
            WebstaurantStore
          </a>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://careers.clarkassociatesinc.biz/",
        "job_listing",
        max_records=10,
    )

    assert rows == []


def test_extract_records_ignores_single_page_level_product_payload_on_listing_pages() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "MuscleBlaze",
          "description": "Brand page summary that should not be attached to a single listing row.",
          "brand": {"name": "MuscleBlaze"},
          "image": "https://example.com/brand.png",
          "aggregateRating": {"ratingValue": "4.5", "reviewCount": "132217"},
          "offers": {"priceCurrency": "INR"},
          "url": "/sv/muscleblaze-biozyme-gold-100-whey/SP-129175?navKey=VRNT-250297"
        }
        </script>
      </head>
      <body>
        <article class="product-card">
          <a href="/sv/muscleblaze-pre-workout-wrathx/SP-95398?navKey=VRNT-210726">
            <img src="/w1.png">
            <h2>MuscleBlaze Pre Workout WrathX - 1.12 lb Cola Frost</h2>
          </a>
          <div class="price">Rs. 1999</div>
          <div>235 reviews</div>
        </article>
        <article class="product-card">
          <a href="/sv/muscleblaze-biozyme-gold-100-whey/SP-129175?navKey=VRNT-250297">
            <img src="/w2.png">
            <h2>MuscleBlaze Biozyme Gold 100% Whey</h2>
          </a>
          <div class="price">Rs. 8399</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.healthkart.com/brand/muscleblaze?navKey=BR-539",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 2
    assert all(row["_source"] == "dom_listing" for row in rows)
    assert rows[0]["title"] == "MuscleBlaze Pre Workout WrathX - 1.12 lb Cola Frost"
    assert rows[0]["price"] == "1999"
    assert "brand" not in rows[0]
    assert "description" not in rows[0]
    assert rows[1]["title"] == "MuscleBlaze Biozyme Gold 100% Whey"
    assert rows[1]["price"] == "8399"


def test_extract_records_does_not_leak_standalone_product_payloads_when_itemlist_exists() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "ItemList",
              "itemListElement": [
                {
                  "@type": "ListItem",
                  "position": 1,
                  "item": {
                    "@type": "Product",
                    "name": "Widget One",
                    "url": "/products/widget-one"
                  }
                },
                {
                  "@type": "ListItem",
                  "position": 2,
                  "item": {
                    "@type": "Product",
                    "name": "Widget Two",
                    "url": "/products/widget-two"
                  }
                }
              ]
            },
            {
              "@type": "Product",
              "name": "Category Hero Product",
              "url": "/products/category-hero"
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
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert [row["title"] for row in rows] == ["Widget One", "Widget Two"]
    assert [row["url"] for row in rows] == [
        "https://example.com/products/widget-one",
        "https://example.com/products/widget-two",
    ]


@pytest.mark.asyncio
async def test_fetch_page_uses_browser_after_js_shell_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    async def fake_curl(url: str, timeout_seconds: float):
        return crawl_fetch_runtime.PageFetchResult(
            url=url,
            final_url=url,
            html=_js_shell_html(),
            status_code=200,
            method="curl_cffi",
        )

    async def unexpected_http(url: str, timeout_seconds: float):
        raise AssertionError(
            f"http fallback should not run for {url} {timeout_seconds}"
        )

    browser_calls: list[str] = []

    async def fake_browser(url: str, timeout_seconds: float, **kwargs):
        del timeout_seconds, kwargs
        browser_calls.append(url)
        return crawl_fetch_runtime.PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", fake_browser)

    first = await crawl_fetch_runtime.fetch_page("https://example.com/listing")
    second = await crawl_fetch_runtime.fetch_page("https://example.com/detail")

    assert first.method == "browser"
    assert second.method == "browser"
    assert browser_calls == [
        "https://example.com/listing",
        "https://example.com/detail",
    ]


@pytest.mark.asyncio
async def test_fetch_page_keeps_http_for_structured_shopify_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"The Relaxed Wide Leg Maternity Jean"}
        </script>
        <script>
          ShopifyAnalytics.meta = {"product":{"id":8199133855921,"title":"The Relaxed Wide Leg Maternity Jean"}};
        </script>
      </head>
      <body>
        <div id="__next"></div>
        <h1>The Relaxed Wide Leg Maternity Jean</h1>
      </body>
    </html>
    """

    async def fake_curl(url: str, timeout_seconds: float):
        return crawl_fetch_runtime.PageFetchResult(
            url=url,
            final_url=url,
            html=html,
            status_code=200,
            method="curl_cffi",
        )

    async def unexpected_browser(url: str, timeout_seconds: float, **kwargs):
        raise AssertionError(
            f"browser fallback should not run for {url} {timeout_seconds} {kwargs}"
        )

    async def fake_load_host_protection_policy(url: str) -> HostProtectionPolicy:
        return HostProtectionPolicy(host=url)

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", unexpected_browser)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        fake_load_host_protection_policy,
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/hatch-jean"
    )

    assert result.method == "curl_cffi"


@pytest.mark.asyncio
async def test_fetch_page_uses_browser_first_for_requires_browser_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    async def unexpected_curl(url: str, timeout_seconds: float):
        raise AssertionError(
            f"curl fetch should not run for browser-first platform {url} {timeout_seconds}"
        )

    async def unexpected_http(url: str, timeout_seconds: float):
        raise AssertionError(
            f"http fallback should not run for browser-first platform {url} {timeout_seconds}"
        )

    async def fake_browser(url: str, timeout_seconds: float, **kwargs):
        del timeout_seconds, kwargs
        return crawl_fetch_runtime.PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered ADP</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", unexpected_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://workforcenow.adp.com/recruitment/recruitment.html?jobId=12345"
    )

    assert result.method == "browser"


def test_browser_runtime_snapshot_exposes_capacity_shape() -> None:
    snapshot = crawl_fetch_runtime.browser_runtime_snapshot()

    assert {"ready", "size", "max_size", "active", "queued", "capacity"} <= set(
        snapshot
    )
    assert int(snapshot["max_size"]) >= 1


def test_extract_ecommerce_detail_returns_normalized_record() -> None:
    html = """
    <html>
      <head>
        <title>Widget Prime</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "description": "A deterministic widget",
          "sku": "W-100",
          "mpn": "MP-9",
          "brand": {"name": "Acme"},
          "category": "Widgets",
          "image": [
            "https://example.com/images/widget-1.jpg",
            "https://example.com/images/widget-2.jpg"
          ],
          "offers": {
            "price": "19.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          },
          "aggregateRating": {
            "ratingValue": "4.7",
            "reviewCount": "128"
          }
        }
        </script>
        <script type="application/json">
        {
          "product": {
            "vendor": "Acme Retail",
            "product_type": "Gadget",
            "handle": "widget-prime",
            "barcode": "1234567890123",
            "tags": ["featured", "new"],
            "available_sizes": ["S", "M", "L"],
            "variant_axes": {"size": ["S", "M", "L"]},
            "variants": [{"sku": "W-100-S", "size": "S"}]
          }
        }
        </script>
      </head>
      <body>
        <h1>Widget Prime</h1>
        <section class="product-features">
          Lightweight body
          Long battery life
        </section>
        <p>Materials: Cotton blend</p>
        <p>Care: Machine wash</p>
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
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["brand"] == "Acme"
    assert record["vendor"] == "Acme Retail"
    assert record["sku"] == "W-100"
    assert record["part_number"] == "MP-9"
    assert record["barcode"] == "1234567890123"
    assert record["product_type"] == "Gadget"
    assert record["category"] == "Widgets"
    assert record["image_url"] == "https://example.com/images/widget-1.jpg"
    assert any("widget-2.jpg" in value for value in record["additional_images"])
    assert record["rating"] == 4.7
    assert record["review_count"] == 128
    assert record["features"] == ["Lightweight body", "Long battery life"]
    assert record["materials"] == "Cotton blend"
    assert record["care"] == "Machine wash"
    assert sorted(v.get("size") for v in record["variants"] if v.get("size")) == ["S"]
    assert isinstance(record["_confidence"], dict)
    assert record["_confidence"]["level"] in {"medium", "high"}


def test_extract_ecommerce_detail_rejects_site_shell_with_listing_payload_pollution() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Practice Software Testing">
        <meta property="og:image" content="https://practicesoftwaretesting.com/assets/img/barn-2400x1600.avif">
        <meta property="og:description" content="Modern application used to learn software testing or test automation.">
        <title>Practice Software Testing</title>
      </head>
      <body>
        <main>
          <article class="product-card">
            <a href="/product/01KPSB7HREA049EFVP5SV8Z46Y">
              <img class="card-img-top" alt="Combination Pliers" src="assets/img/products/pliers01.avif">
              <span class="price">$14.15</span>
            </a>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://practicesoftwaretesting.com/#/product/01HB",
        "ecommerce_detail",
        max_records=5,
        requested_fields=[
            "title",
            "price",
            "image_url",
            "description",
            "category",
            "brand",
        ],
        network_payloads=[
            {
                "url": "https://api.practicesoftwaretesting.com/products?page=1",
                "endpoint_type": "generic_json",
                "body": {
                    "current_page": 1,
                    "data": [
                        {
                            "id": "01KPSB7HREA049EFVP5SV8Z46Y",
                            "name": "Combination Pliers",
                            "description": "Listing summary for pliers.",
                            "price": "14.15",
                            "brand": "ForgeFlex Tools",
                            "image": "https://practicesoftwaretesting.com/assets/img/products/pliers01.avif",
                            "url": "https://practicesoftwaretesting.com/#/product/01KPSB7HREA049EFVP5SV8Z46Y",
                        },
                        {
                            "id": "01KPSB7HREA049EFVP5SV8Z470",
                            "name": "Bolt Cutters",
                            "description": "Listing summary for cutters.",
                            "price": "24.99",
                            "brand": "ForgeFlex Tools",
                            "image": "https://practicesoftwaretesting.com/assets/img/products/pliers03.avif",
                            "url": "https://practicesoftwaretesting.com/#/product/01KPSB7HREA049EFVP5SV8Z470",
                        },
                    ],
                },
            }
        ],
    )

    assert rows == []


def test_extract_ecommerce_detail_rejects_brand_shell_with_app_prompt_copy() -> None:
    html = """
    <html>
      <head>
        <title>UNIQLO - LifeWear</title>
        <meta property="og:title" content="UNIQLO - LifeWear" />
        <meta property="og:description" content="Shop on our app for the best experience" />
        <meta property="og:url" content="https://www.uniqlo.com/in/en/products/E474244-000/01" />
        <meta property="og:image" content="https://image.uniqlo.com/UQ/ST3/in/imagesgoods/474244/item/ingoods_57_474244_3x4.jpg" />
      </head>
      <body>
        <main>
          <h1>UNIQLO - LifeWear</h1>
          <div role="radiogroup" aria-label="Color">
            <button aria-label="57 OLIVE">57 OLIVE</button>
          </div>
          <img src="https://image.uniqlo.com/UQ/ST3/in/imagesgoods/474244/item/ingoods_57_474244_3x4.jpg" alt="57 OLIVE" />
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.uniqlo.com/in/en/products/E474244-000/01?colorDisplayCode=57&sizeDisplayCode=005",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://www.uniqlo.com/in/en/products/E474244-000/01",
    )

    assert rows == []


def test_extract_ecommerce_detail_prefers_requested_identity_on_same_site_utility_redirect() -> None:
    html = """
    <html>
      <head>
        <title>Online Shopping for Men &amp; Women Clothing, Accessories at The Souled Store</title>
        <meta property="og:title" content="Buy Oversized T-Shirt: Bear Minimum Oversized T-Shirts Online" />
        <meta property="og:description" content="Shop for Oversized T-Shirt: Bear Minimum Oversized T-Shirts Online" />
        <meta property="og:url" content="https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum?gte=1" />
        <meta property="og:image" content="https://prod-img.thesouledstore.com/public/theSoul/uploads/catalog/product/1749147636_7690605.jpg" />
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Oversized T-Shirt: Bear Minimum Oversized T-Shirts By The Souled Store",
          "image": "https://prod-img.thesouledstore.com/public/theSoul/uploads/catalog/product/1749147636_7690605.jpg",
          "sku": "305537",
          "description": "Shop for Oversized T-Shirt: Bear Minimum Oversized T-Shirts Online",
          "offers": {
            "@type": "Offer",
            "priceCurrency": "INR",
            "availability": "InStock",
            "price": "1199",
            "url": "https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum?gte=1"
          },
          "brand": {
            "@type": "Thing",
            "name": "The Souled Store"
          }
        }
        </script>
      </head>
      <body>
        <div class="wishlistDiv">Wishlist shell</div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.thesouledstore.com/mywishlist",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum?gte=1",
    )

    assert len(rows) == 1
    record = rows[0]
    assert (
        record["url"]
        == "https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum?gte=1"
    )
    assert (
        record["source_url"]
        == "https://www.thesouledstore.com/product/oversized-tshirts-bear-minimum?gte=1"
    )
    assert (
        record["title"]
        == "Oversized T-Shirt: Bear Minimum Oversized T-Shirts By The Souled Store"
    )
    assert record["sku"] == "305537"


def test_extract_ecommerce_detail_rejects_same_site_utility_redirect_with_mismatched_product_payload() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Avatar: Fire Bender Oversized T-Shirts By Avatar: The Last Airbender" />
        <meta property="og:description" content="Shop for Avatar: Fire Bender Oversized T-Shirts Online" />
        <meta property="og:image" content="https://prod-img.thesouledstore.com/public/theSoul/uploads/catalog/product/1753379330_3880870.jpg" />
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Avatar: Fire Bender Oversized T-Shirts By Avatar: The Last Airbender",
          "image": "https://prod-img.thesouledstore.com/public/theSoul/uploads/catalog/product/1753379330_3880870.jpg",
          "sku": "309454",
          "description": "Shop for Avatar: Fire Bender Oversized T-Shirts Online",
          "offers": {
            "@type": "Offer",
            "priceCurrency": "INR",
            "availability": "InStock",
            "price": "1199",
            "url": "https://www.thesouledstore.com/product/avatar-fire-bender-menoversized-tshirt?gte=1"
          }
        }
        </script>
      </head>
      <body>
        <section class="faq-wrapper">
          <h2>Returns, Exchange &amp; Refund</h2>
        </section>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.thesouledstore.com/faqs",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://www.thesouledstore.com/product/marvel-spider-x-venom-oversized-tshirt?gte=1",
    )

    assert rows == []


def test_extract_ecommerce_detail_rejects_same_site_wrong_product_payload_without_utility_redirect() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Hanes Authentic T-shirt",
          "url": "https://www.customink.com/products/t-shirts/4",
          "image": "https://www.customink.com/images/hanes-shirt.jpg",
          "description": "A basic t-shirt product."
        }
        </script>
      </head>
      <body>
        <h1>Medic Shirts</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.customink.com/t-shirts/medic-shirts",
        "ecommerce_detail",
        max_records=10,
        requested_page_url="https://www.customink.com/t-shirts/medic-shirts",
    )

    assert rows == []


def test_extract_ecommerce_detail_keeps_same_url_color_variant_product_path() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Bondi 9",
          "brand": {
            "@type": "Brand",
            "name": "Hoka"
          },
          "color": "Berry Jam/Berry Patch",
          "description": "Women's Hoka Bondi 9 by Hoka at Zappos.com.",
          "image": "https://m.media-amazon.com/images/I/71tLsSyLUZL._SX700_.jpg",
          "offers": {
            "@type": "Offer",
            "price": "175.00",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Bondi 9</h1>
          <div class="price">$175.00</div>
        </main>
      </body>
    </html>
    """

    requested_url = (
        "https://www.zappos.com/kratos/p/"
        "womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988"
        "?zlfid=191"
    )

    rows = extract_records(
        html,
        requested_url,
        "ecommerce_detail",
        max_records=5,
        requested_page_url=requested_url,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Bondi 9"


def test_extract_ecommerce_detail_rejects_fragment_backed_shell_payload_from_spa_root() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Practice Software Testing" />
        <meta property="og:description" content="Modern application used to learn software testing or test automation." />
        <meta property="og:url" content="https://www.practicesoftwaretesting.com/" />
      </head>
      <body>
        <main>
          <h1>Practice Software Testing</h1>
          <label for="sort">Sort</label>
          <select id="sort">
            <option>Name (A - Z)</option>
            <option>Name (Z - A)</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://practicesoftwaretesting.com/#/product/01HB",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://practicesoftwaretesting.com/#/product/01HB",
    )

    assert rows == []


def test_detail_rejection_does_not_claim_identity_mismatch_when_same_url_never_redirected() -> None:
    requested_url = (
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html?v1=527078510"
    )
    record = {
        "title": "United States",
        "url": requested_url,
    }

    assert (
        detail_extractor.detail_record_rejection_reason(
            record,
            page_url=requested_url,
            requested_page_url=requested_url,
        )
        is None
    )


def test_extract_ecommerce_detail_rejects_search_results_shell_with_sort_filter_controls() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Trail Shoes" />
      </head>
      <body>
        <main>
          <h1>Trail Shoes</h1>
          <label for="sort-by">Sort By</label>
          <select id="sort-by">
            <option>Featured</option>
            <option>Price: Low to High</option>
          </select>
          <label for="filter-by">Filter By</label>
          <select id="filter-by">
            <option>All</option>
            <option>Men</option>
          </select>
          <article class="product-card">
            <a href="/dp/B0TRAIL123">
              <img src="https://cdn.example.com/trail-shoe.jpg" alt="Trail Runner GTX" />
              <h2>Trail Runner GTX</h2>
            </a>
            <div class="price">$129.99</div>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.example.com/s?k=trail+shoes",
        "ecommerce_detail",
        max_records=1,
    )

    assert rows == []


def test_extract_ecommerce_detail_rejects_placeholder_not_found_title_without_product_signals() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Oops! The page you're looking for can't be found.</h1>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.vitacost.com/now-foods-ultra-omega-3-fish-oil-500-epa-250-dha-180-softgels",
        "ecommerce_detail",
        max_records=1,
    )

    assert rows == []


def test_extract_ecommerce_detail_recovers_firstcry_static_js_state_price() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Buy Babyhug Denim Woven Sleeveless Top &amp; Pant Set With Floral Print - Blue for Girls (3-4 Years) Online in India, Shop at FirstCry.com - 22346676" />
        <meta property="og:image" content="https://cdn.fcglcdn.com/brainbees/images/products/438x531/22346676a.webp" />
        <meta property="og:url" content="https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail" />
        <script>
          var CurrentProductID=22346676,CurrentProductDetailJSON={
            "22346676":{
              "pid":22346676,
              "pn":"Babyhug Denim Woven Sleeveless Top & Pant Set With Floral Print - Blue",
              "pd":"Babyhug Sets & Suits Female 3-4Y BLUE/BLUE",
              "mrp":1099,
              "Dis":21,
              "Img":"22346676a.jpg;22346676b.jpg;"
            }
          };
        </script>
      </head>
      <body>
        <h1>product detail</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
        "ecommerce_detail",
        max_records=1,
        requested_page_url="https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
        requested_fields=["title", "price", "image_url"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert (
        record["title"]
        == "Babyhug Denim Woven Sleeveless Top & Pant Set With Floral Print - Blue"
    )
    assert record["price"] == "868.21"
    assert (
        record["image_url"]
        == "https://cdn.fcglcdn.com/brainbees/images/products/438x531/22346676a.webp"
    )


def test_extract_ecommerce_detail_rejects_brand_shell_with_tracking_pixel_image() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Rockler Woodworking and Hardware" />
        <meta property="og:image" content="https://www.facebook.com/tr?id=244606169432534&ev=PageView&noscript=1" />
      </head>
      <body>
        <main>
          <h1>Rockler Woodworking and Hardware</h1>
          <p>Family-owned since 1954 Rockler is your go to source for high quality and innovative woodworking tools, hardware, lumber and expert advice.</p>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift",
        "ecommerce_detail",
        max_records=1,
    )

    assert rows == []


def test_extract_ecommerce_detail_keeps_structured_product_when_title_still_needs_promotion() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Buy Widget Prime | Example",
          "description": "A real widget with structured content.",
          "image": "https://example.com/widget.jpg",
          "offers": {
            "price": "19.99",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <main>
          <h1>Buy Widget Prime | Example</h1>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/12345",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Buy Widget Prime | Example"
    assert record["price"] == "19.99"
    assert record["image_url"] == "https://example.com/widget.jpg"


def test_extract_job_detail_returns_requested_sections() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Senior Data Engineer",
          "datePosted": "2026-04-18",
          "employmentType": "Full-time",
          "description": "Build deterministic data pipelines.",
          "jobLocationType": "TELECOMMUTE",
          "hiringOrganization": {"name": "Data Corp"},
          "jobLocation": {
            "address": {
              "addressLocality": "Bengaluru",
              "addressRegion": "KA",
              "addressCountry": "IN"
            }
          },
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "INR",
            "value": {
              "@type": "QuantitativeValue",
              "minValue": "2500000",
              "maxValue": "3500000",
              "unitText": "YEAR"
            }
          },
          "url": "https://example.com/jobs/senior-data-engineer"
        }
        </script>
      </head>
      <body>
        <h1>Senior Data Engineer</h1>
        <h2>Responsibilities</h2>
        <div>Build pipelines and maintain ingestion services.</div>
        <h2>Qualifications</h2>
        <div>5+ years of Python and SQL.</div>
        <h2>Benefits</h2>
        <div>Remote-first, health cover.</div>
        <h2>Skills</h2>
        <div>Python, SQL, Airflow.</div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/jobs/senior-data-engineer",
        "job_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Senior Data Engineer"
    assert record["company"] == "Data Corp"
    assert record["location"] == "Bengaluru, KA, IN"
    assert record["job_type"] == "Full-time"
    assert record["posted_date"] == "2026-04-18"
    assert record["salary"] == "INR 2500000 - 3500000 YEAR"
    assert record["remote"] is True
    assert "Build pipelines" in record["responsibilities"]
    assert "5+ years" in record["qualifications"]
    assert "health cover" in record["benefits"]
    assert "Python, SQL, Airflow." in record["skills"]


def test_extract_job_detail_strips_tracking_params_from_output_urls() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Senior Data Engineer",
          "hiringOrganization": {"name": "Data Corp"},
          "url": "https://example.com/jobs/senior-data-engineer?utm_source=linkedin&fbclid=abc123&jobId=42"
        }
        </script>
      </head>
      <body>
        <h1>Senior Data Engineer</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/jobs/senior-data-engineer?utm_medium=email&sid=session-1&jobId=42",
        "job_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["url"] == "https://example.com/jobs/senior-data-engineer?jobId=42"
    assert (
        record["apply_url"] == "https://example.com/jobs/senior-data-engineer?jobId=42"
    )
    assert (
        record["source_url"] == "https://example.com/jobs/senior-data-engineer?jobId=42"
    )


def test_extract_greenhouse_job_detail_from_remix_state() -> None:
    html = """
    <html>
      <head>
        <title>Job Application for Manager, Engineering at Greenhouse</title>
        <script>
          window.__remixContext = {
            "state": {
              "loaderData": {
                "routes/$url_token_.jobs_.$job_post_id": {
                  "jobPost": {
                    "title": "Manager, Engineering",
                    "company_name": "Greenhouse",
                    "job_post_location": "Ontario",
                    "public_url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
                    "published_at": "2026-04-09T10:05:53-04:00",
                    "content": "<p>Lead the reporting and analytics engineering domain.</p><h2>What you’ll do</h2><ul><li>Lead and mentor engineers.</li></ul><h2>You should have</h2><ul><li>5+ years of engineering experience.</li></ul><h2>Benefits</h2><p>Remote-first and health cover.</p>"
                  }
                }
              }
            }
          };
        </script>
      </head>
      <body>
        <h1>Manager, Engineering</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
        "job_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Manager, Engineering"
    assert record["company"] == "Greenhouse"
    assert record["location"] == "Ontario"
    assert (
        record["apply_url"]
        == "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
    )
    assert "Lead and mentor engineers." in record["responsibilities"]
    assert "5+ years of engineering experience." in record["qualifications"]
    assert "Remote-first and health cover." in record["benefits"]
    assert record["_source"] == "js_state"


def test_extract_job_detail_ignores_cross_surface_requested_image_fields() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Senior Data Engineer",
          "description": "Build deterministic data pipelines.",
          "hiringOrganization": {
            "name": "Data Corp",
            "logo": "https://example.com/images/company-logo.jpg"
          },
          "image": [
            "https://example.com/images/company-logo.jpg",
            "https://example.com/images/office.jpg"
          ],
          "jobLocation": {
            "address": {
              "addressLocality": "Bengaluru",
              "addressRegion": "KA",
              "addressCountry": "IN"
            }
          },
          "url": "https://example.com/jobs/senior-data-engineer"
        }
        </script>
      </head>
      <body>
        <h1>Senior Data Engineer</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/jobs/senior-data-engineer",
        "job_detail",
        max_records=5,
        requested_fields=["image_url", "additional_images", "description"],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Senior Data Engineer"
    assert record["company"] == "Data Corp"
    assert record["description"] == "Build deterministic data pipelines."
    assert "image_url" not in record
    assert "additional_images" not in record


def test_extract_product_group_variants_without_schema_pollution() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [{
            "@type": "ProductGroup",
            "name": "Jim Bag",
            "description": "Soft grained leather bag adorned with a chain and rhinestone wing.",
            "material": "Material: 100% Cow leather",
            "brand": {"name": "Zadig&Voltaire"},
            "image": [
              "https://example.com/jim-1.jpg",
              "https://example.com/jim-2.jpg"
            ],
            "additionalProperty": [
              {"@type": "PropertyValue", "name": "Composition", "value": "Material: 100% Cow leather"},
              {"@type": "PropertyValue", "name": "Care", "value": "Protect from humidity"}
            ],
            "hasVariant": [
              {
                "@type": "Product",
                "sku": "LWBA04310011UNI",
                "name": "Jim Bag - One size",
                "size": "One size",
                "color": "Black",
                "gtin13": "3607624735775",
                "image": "https://example.com/jim-1.jpg",
                "offers": {
                  "@type": "Offer",
                  "url": "https://example.com/jim-bag?filter=size-One%20size",
                  "priceCurrency": "GBP",
                  "price": 470,
                  "availability": "https://schema.org/InStock"
                }
              }
            ]
          }]
        }
        </script>
        <script>window.__NUXT__ = {"config":{"public":{"env":"production"}}};</script>
      </head>
      <body>
        <h1>Jim Bag</h1>
        <footer>Download our app type: marketing shell</footer>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/p/jim-bag",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Jim Bag"
    assert record["brand"] == "Zadig&Voltaire"
    assert record["materials"] == "Material: 100% Cow leather"
    assert record["care"] == "Protect from humidity"
    assert isinstance(record["variants"], list)
    assert record["variant_count"] == 1
    assert (
        record["description"]
        == "Soft grained leather bag adorned with a chain and rhinestone wing."
    )
    assert "marketing shell" not in record.get("description", "")


def test_extract_ecommerce_listing_returns_card_records() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/products/widget-prime">
            <img src="/images/widget-prime.jpg" alt="Widget Prime">
            <h2 class="product-title">Widget Prime</h2>
          </a>
          <div class="price">$19.99</div>
        </article>
        <article class="product-card">
          <a href="/products/widget-pro">
            <img src="/images/widget-pro.jpg" alt="Widget Pro">
            <h2 class="product-title">Widget Pro</h2>
          </a>
          <div class="price">$29.99</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Widget Prime"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[0]["price"] == "19.99"
    assert rows[0]["image_url"] == "https://example.com/images/widget-prime.jpg"
    assert "additional_images" not in rows[0]
    assert rows[1]["title"] == "Widget Pro"


def test_extract_ecommerce_listing_preserves_functional_query_params() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/products/widget-prime?utm_source=newsletter&variant=blue&ref=campaign">
            <img src="/images/widget-prime.jpg" alt="Widget Prime">
            <h2 class="product-title">Widget Prime</h2>
          </a>
          <div class="price">$19.99</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets?utm_campaign=spring&sort=featured",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/products/widget-prime?variant=blue"
    assert (
        rows[0]["source_url"] == "https://example.com/collections/widgets?sort=featured"
    )


def test_extract_ecommerce_listing_keeps_title_only_detail_candidates_without_detail_markers() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/browse/widget-prime">
            <h2 class="product-title">Widget Prime Ultra</h2>
          </a>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/catalog",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/catalog",
            "_source": "dom_listing",
            "title": "Widget Prime Ultra",
            "url": "https://example.com/browse/widget-prime",
        }
    ]


def test_extract_ecommerce_listing_does_not_treat_supportive_product_paths_as_utility_urls() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/products/supportive-chair">
            <h2 class="product-title">Supportive Chair</h2>
          </a>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/catalog",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/catalog",
            "_source": "dom_listing",
            "title": "Supportive Chair",
            "url": "https://example.com/products/supportive-chair",
        }
    ]


def test_extract_ecommerce_listing_keeps_same_site_cross_subdomain_detail_links() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="https://www.indiamart.com/proddetail/widget-prime-123.html">
            <img src="https://img.indiamart.com/widget-prime.jpg" alt="Widget Prime" />
            <h2 class="product-title">Widget Prime</h2>
          </a>
          <div class="price">₹71</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://dir.indiamart.com/impcat/widgets.html",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert (
        rows[0]["url"] == "https://www.indiamart.com/proddetail/widget-prime-123.html"
    )
    assert rows[0]["title"] == "Widget Prime"
    assert rows[0]["price"] == "71"


def test_extract_ecommerce_listing_treats_proddetail_paths_as_detail_links() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="https://www.indiamart.com/proddetail/widget-prime-123.html">
            <h2 class="product-title">Widget Prime</h2>
          </a>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://dir.indiamart.com/impcat/widgets.html",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert (
        rows[0]["url"] == "https://www.indiamart.com/proddetail/widget-prime-123.html"
    )
    assert rows[0]["title"] == "Widget Prime"


def test_extract_ecommerce_listing_keeps_id_product_links_over_productlist_facets() -> None:
    html = """
    <html>
      <body>
        <aside>
          <article class="product-card">
            <a href="/store/c/productlist/N=361945">
              <h2 class="product-title">Acne & Blemish Treatments</h2>
            </a>
          </article>
          <article class="product-card">
            <a href="/store/c/productlist/N=360500">
              <h2 class="product-title">Allergy Medications</h2>
            </a>
          </article>
        </aside>
        <main>
          <article class="product-card">
            <a href="/store/c/binaxnow-covid-19-antigen-rapid-self-test-at-home-kit/ID=300414527-product">
              <img src="/images/binax.jpg" alt="BinaxNOW COVID-19 Antigen Rapid Self-Test at Home Kit" />
              <h2 class="product-title">BinaxNOW COVID-19 Antigen Rapid Self-Test at Home Kit - 2 ea</h2>
            </a>
            <div class="price">$23.99</div>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.walgreens.com/store/c/productlist/N=20007318",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["url"] == (
        "https://www.walgreens.com/store/c/"
        "binaxnow-covid-19-antigen-rapid-self-test-at-home-kit/"
        "ID=300414527-product"
    )
    assert (
        rows[0]["title"]
        == "BinaxNOW COVID-19 Antigen Rapid Self-Test at Home Kit - 2 ea"
    )
    assert rows[0]["price"] == "23.99"


def test_listing_identity_rejects_productlist_as_detail_marker() -> None:
    listing_url = "https://www.walgreens.com/store/c/productlist/N=20007318"
    product_url = (
        "https://www.walgreens.com/store/c/"
        "binaxnow-covid-19-antigen-rapid-self-test-at-home-kit/"
        "ID%3D300414527-product"
    )

    assert listing_detail_like_path(listing_url, is_job=False) is False
    assert listing_detail_like_path(product_url, is_job=False) is True


def test_extract_ecommerce_listing_falls_back_to_original_dom_when_cleaned_dom_strips_card_headers() -> None:
    html = """
    <html>
      <body>
        <ul>
          <li>
            <article class="product-card">
              <header>
                <a href="https://www.indiamart.com/proddetail/widget-prime-123.html">
                  <img src="https://img.indiamart.com/widget-prime.jpg" alt="Widget Prime" />
                  <h2 class="product-title">Widget Prime</h2>
                </a>
              </header>
              <section class="product-info">
                <div class="price">₹71</div>
              </section>
            </article>
          </li>
        </ul>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://dir.indiamart.com/impcat/widgets.html",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert (
        rows[0]["url"] == "https://www.indiamart.com/proddetail/widget-prime-123.html"
    )
    assert rows[0]["title"] == "Widget Prime"
    assert rows[0]["price"] == "71"
    assert rows[0]["image_url"] == "https://img.indiamart.com/widget-prime.jpg"


def test_extract_ecommerce_listing_does_not_treat_repeated_testimonials_as_products() -> None:
    html = """
    <html>
      <body>
        <div class="quote">
          <span class="text">“The world as we have created it is a process of our thinking.”</span>
          <span>by <small class="author">Albert Einstein</small></span>
        </div>
        <div class="quote">
          <span class="text">“It is our choices that show what we truly are.”</span>
          <span>by <small class="author">J.K. Rowling</small></span>
        </div>
        <div class="quote">
          <span class="text">“There are only two ways to live your life.”</span>
          <span>by <small class="author">Albert Einstein</small></span>
        </div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/testimonials",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == []


def test_extract_ecommerce_listing_from_embedded_js_assignment_products() -> None:
    html = """
    <html>
      <body>
        <script>
          var products = [
            {
              "title": "Trail Runner",
              "url": "/products/trail-runner",
              "price": "109.95"
            },
            {
              "title": "Commuter Backpack",
              "url": "/products/commuter-backpack",
              "price": "89.50"
            }
          ];
        </script>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://store.example.com/collections/featured",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Trail Runner"
    assert rows[0]["url"] == "https://store.example.com/products/trail-runner"
    assert rows[0]["_source"] == "structured_listing"


def test_extract_records_emits_raw_json_array_items() -> None:
    raw_json = """
    [
      {"id": 1, "title": "Fjallraven Backpack", "price": 109.95, "description": "Travel pack"},
      {"id": 2, "title": "Mens Casual Tee", "price": 22.3, "description": "Cotton tee"}
    ]
    """

    rows = extract_records(
        raw_json,
        "https://fakestoreapi.com/products",
        "ecommerce_listing",
        max_records=10,
        content_type="application/json; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Fjallraven Backpack"
    assert rows[0]["price"] == "109.95"
    assert rows[0]["_source"] == "raw_json"


def test_extract_records_emits_nested_raw_json_list_items() -> None:
    raw_json = """
    {
      "products": [
        {"id": 1, "title": "Essence Mascara Lash Princess", "description": "Popular mascara", "price": 9.99, "brand": "Essence"},
        {"id": 2, "title": "Eyeshadow Palette", "description": "Neutral tones", "price": 19.99, "brand": "Glamour"}
      ],
      "total": 2
    }
    """

    rows = extract_records(
        raw_json,
        "https://dummyjson.com/products",
        "ecommerce_listing",
        max_records=10,
        content_type="application/json; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Essence Mascara Lash Princess"
    assert rows[0]["description"] == "Popular mascara"
    assert rows[0]["brand"] == "Essence"


def test_extract_records_emits_nested_graphql_listing_items() -> None:
    raw_json = """
    {
      "data": {
        "search": {
          "edges": [
            {
              "node": {
                "id": "sku-1",
                "title": "Trail Runner",
                "url": "/products/trail-runner",
                "price": "109.95"
              }
            },
            {
              "node": {
                "id": "sku-2",
                "title": "Commuter Backpack",
                "url": "/products/commuter-backpack",
                "price": "89.50"
              }
            }
          ]
        }
      }
    }
    """

    rows = extract_records(
        raw_json,
        "https://store.example.com/api/search",
        "ecommerce_listing",
        max_records=10,
        content_type="application/json; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["title"] == "Trail Runner"
    assert rows[1]["url"] == "https://store.example.com/products/commuter-backpack"


def test_extract_records_does_not_synthesize_listing_from_nested_json_without_items() -> None:
    raw_json = """
    {
      "data": {
        "search": {
          "summary": {
            "title": "Featured products",
            "description": "Top picks for spring"
          }
        }
      }
    }
    """

    rows = extract_records(
        raw_json,
        "https://store.example.com/api/search",
        "ecommerce_listing",
        max_records=10,
        content_type="application/json; charset=utf-8",
    )

    assert rows == []


def test_extract_records_emits_xml_sitemap_listing_records() -> None:
    xml = """
    <?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.com/products/widget-prime</loc>
      </url>
      <url>
        <loc>https://example.com/products/widget-pro</loc>
      </url>
    </urlset>
    """

    rows = extract_records(
        xml,
        "https://example.com/media/sitemap-products.xml",
        "ecommerce_listing",
        max_records=10,
        content_type="application/xml; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["_source"] == "xml_sitemap"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[0]["title"] == "widget prime"


def test_extract_records_emits_rss_listing_records_from_link_nodes() -> None:
    rss = """
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Widget Prime</title>
          <link>https://example.com/products/widget-prime</link>
        </item>
        <item>
          <title>Widget Pro</title>
          <link>https://example.com/products/widget-pro</link>
        </item>
      </channel>
    </rss>
    """

    rows = extract_records(
        rss,
        "https://example.com/feed.xml",
        "ecommerce_listing",
        max_records=10,
        content_type="application/rss+xml; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["_source"] == "xml_sitemap"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[1]["title"] == "widget pro"


def test_extract_records_emits_atom_listing_records_from_link_href() -> None:
    atom = """
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Widget Prime</title>
        <link href="https://example.com/products/widget-prime" />
      </entry>
      <entry>
        <title>Widget Pro</title>
        <link href="https://example.com/products/widget-pro" />
      </entry>
    </feed>
    """

    rows = extract_records(
        atom,
        "https://example.com/atom.xml",
        "ecommerce_listing",
        max_records=10,
        content_type="application/atom+xml; charset=utf-8",
    )

    assert len(rows) == 2
    assert rows[0]["_source"] == "xml_sitemap"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[1]["title"] == "widget pro"


def test_extract_detail_keeps_dom_stage_for_high_scoring_js_state_when_long_text_missing() -> None:
    html = """
    <html>
      <body>
        <script type="application/json" id="__NEXT_DATA__">
        {
          "props": {
            "pageProps": {
              "product": {
                "title": "Trail Runner",
                "vendor": "Acme Outdoors",
                "handle": "trail-runner",
                "price": "119.00",
                "availability": "In Stock",
                "images": [{"src": "https://cdn.example.com/trail.jpg"}],
                "variants": [{"id": "v1", "sku": "TRAIL-1", "available": true}]
              }
            }
          }
        }
        </script>
        <h2>Description</h2>
        <div>Stable all-terrain shoe for long trail runs.</div>
        <h2>Specifications</h2>
        <div>Rubber outsole, reinforced toe cap.</div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["description", "specifications"],
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert "Stable all-terrain shoe" in record["description"]
    assert "Rubber outsole" in record["specifications"]
    assert record["_extraction_tiers"]["current"] == "dom"
    assert record["_extraction_tiers"]["early_exit"] is None


def test_extract_detail_uses_requested_custom_fields_from_network_payloads() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Whirlpool">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Whirlpool",
          "brand": {"name": "Whirlpool"},
          "offers": {
            "price": "16690",
            "priceCurrency": "INR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <h1>Whirlpool</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://india.whirlpool.in/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p?sc=1",
        "ecommerce_detail",
        max_records=5,
        requested_fields=["capacity", "energy_rating"],
        network_payloads=[
            {
                "url": "https://india.whirlpool.in/productBySKU/1506",
                "endpoint_type": "generic_json",
                "body": {
                    "ProductName": "Vitamagic Pro 192L 3 Star Radiant Steel Auto Defrost Single Door Refrigerator - Radiant Steel-Y",
                    "BrandName": "Whirlpool",
                    "DetailUrl": "/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p",
                    "ProductSpecifications": [
                        {"FieldName": "Capacity(L)", "FieldValues": ["192 L"]},
                        {"FieldName": "Energy Rating", "FieldValues": ["3 Star"]},
                    ],
                },
            }
        ],
    )

    assert len(rows) == 1
    record = rows[0]
    assert (
        record["title"]
        == "Vitamagic Pro 192L 3 Star Radiant Steel Auto Defrost Single Door Refrigerator - Radiant Steel-Y"
    )
    assert record["capacity"] == "192 L"
    assert record["energy_rating"] == "3 Star"
    assert record["_field_sources"]["title"][0] == "network_payload"


def test_extract_detail_keeps_long_product_titles_that_include_star_ratings() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Whirlpool">
      </head>
      <body>
        <h1>Whirlpool</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://india.whirlpool.in/example/p?sc=1",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["energy_rating"],
        network_payloads=[
            {
                "url": "https://india.whirlpool.in/productBySKU/1506",
                "endpoint_type": "generic_json",
                "body": {
                    "ProductName": "Vitamagic Pro 192L 3 Star Radiant Steel Refrigerator",
                    "BrandName": "Whirlpool",
                    "DetailUrl": "/example/p",
                    "ProductSpecifications": [
                        {"FieldName": "Energy Rating", "FieldValues": ["3 Star"]},
                    ],
                },
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Vitamagic Pro 192L 3 Star Radiant Steel Refrigerator"


def test_extract_detail_allows_safe_early_exit_before_dom_when_pre_dom_record_is_complete() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "description": "A deterministic widget with enough detail to avoid DOM fallback.",
          "brand": {"name": "Acme"},
          "image": "https://example.com/images/widget-1.jpg",
          "offers": {
            "price": "19.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body>
        <div class="noise">No useful DOM selectors required</div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=5,
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": True, "min_confidence": 0.55}
        },
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["_extraction_tiers"]["early_exit"] == "js_state"
    assert record["_extraction_tiers"]["current"] == "js_state"


def test_extract_detail_records_preserves_selector_trace_for_selected_rule() -> None:
    html = """
    <html>
      <body>
        <div class="selector-title">Selector Widget</div>
        <div class="selector-price">$19.99</div>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/selector-widget",
        "ecommerce_detail",
        max_records=1,
        selector_rules=[
            {
                "id": 11,
                "field_name": "title",
                "css_selector": ".selector-title",
                "source": "domain_memory",
                "source_run_id": 55,
            },
            {
                "id": 12,
                "field_name": "price",
                "css_selector": ".selector-price",
                "source": "domain_memory",
                "source_run_id": 55,
            },
        ],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["_selector_traces"]["title"] == {
        "selector_kind": "css_selector",
        "selector_value": ".selector-title",
        "selector_source": "domain_memory",
        "selector_record_id": 11,
        "source_run_id": 55,
        "sample_value": "Selector Widget",
        "page_url": "https://example.com/products/selector-widget",
    }
    assert record["_selector_traces"]["price"] == {
        "selector_kind": "css_selector",
        "selector_value": ".selector-price",
        "selector_source": "domain_memory",
        "selector_record_id": 12,
        "source_run_id": 55,
        "sample_value": "$19.99",
        "page_url": "https://example.com/products/selector-widget",
    }


def test_extract_listing_records_preserves_selector_trace_for_selected_rule() -> None:
    html = """
    <html>
      <body>
        <article class="card">
          <a href="/products/selector-widget">Selector Widget</a>
          <div class="selector-price">$19.99</div>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=5,
        selector_rules=[
            {
                "id": 21,
                "field_name": "price",
                "css_selector": ".selector-price",
                "source": "domain_memory",
                "source_run_id": 66,
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0]["_selector_traces"]["price"] == {
        "selector_kind": "css_selector",
        "selector_value": ".selector-price",
        "selector_source": "domain_memory",
        "selector_record_id": 21,
        "source_run_id": 66,
        "sample_value": "$19.99",
        "page_url": "https://example.com/collections/widgets",
    }


def test_extract_detail_rejects_non_variant_options_object_from_structured_payload() -> None:
    html = """
    <html>
      <head>
        <script type="application/json">
        {
          "@type": "Product",
          "name": "Duracell Ultra AA Alkaline Batteries (Pack of 8)",
          "sku": "OFF.MIS.25278554",
          "brand": "Duracell",
          "material": "Alkaline",
          "options": {
            "renderableComponents": [
              {"url": "/user/account", "title": "My Profile"},
              {"url": "/user/orders", "title": "My Orders"},
              {"title": "Logout", "action": {"type": "LOGOUT"}}
            ]
          }
        }
        </script>
      </head>
      <body>
        <h1>Duracell Ultra AA Alkaline Batteries (Pack of 8)</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.industrybuying.com/battery-cell-duracell-OFF.MIS.25278554",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Duracell Ultra AA Alkaline Batteries (Pack of 8)"
    assert record["sku"] == "OFF.MIS.25278554"
    assert (
        record["url"]
        == "https://www.industrybuying.com/battery-cell-duracell-OFF.MIS.25278554"
    )
    assert "availability" not in record


def test_extract_detail_keeps_valid_variant_axes_from_structured_options_alias() -> None:
    html = """
    <html>
      <head>
        <script type="application/json">
        {
          "@type": "Product",
          "name": "MuscleBlaze Biozyme Performance Whey",
          "options": {
            "weight": ["4.4 Lb", "0.4 Lb"],
            "flavour": ["Rich Chocolate", "Blue Tokai Coffee"]
          }
        }
        </script>
      </head>
      <body>
        <h1>MuscleBlaze Biozyme Performance Whey</h1>
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


def test_normalize_variant_record_drops_scalar_legacy_variant_axes() -> None:
    record = {
        "variant_axes": {
            "size": ["M"],
            "stock": 5,
        }
    }

    normalize_variant_record(record)

    assert "size" not in record
    assert "stock" not in record
    assert "variant_axes" not in record


def test_normalize_variant_record_strips_legacy_option_summaries_and_selected_variant() -> None:
    record = {
        "option1_name": "Flavour",
        "option1_values": "Rich Chocolate, Blue Tokai Coffee",
        "option2_name": "pr type",
        "option2_values": "OptOut, RemoveMe, MyInfo",
        "variant_axes": {
            "flavor": ["Rich Chocolate", "Blue Tokai Coffee"],
            "type": ["OptOut", "RemoveMe", "MyInfo"],
        },
        "variants": [
            {
                "option_values": {
                    "flavor": "Rich Chocolate",
                    "type": "OptOut",
                }
            }
        ],
        "selected_variant": {
            "option_values": {
                "flavor": "Rich Chocolate",
                "type": "OptOut",
            }
        },
    }

    normalize_variant_record(record)

    # Legacy scaffolding fields are always stripped; only the canonical
    # ``variants`` list (carrying public axes like ``flavor``)
    # may survive. The option-summary / selected_variant / variant_axes
    # dicts must not leak into the public record.
    assert "selected_variant" not in record
    assert "variant_axes" not in record
    assert "option1_name" not in record
    assert "option2_name" not in record
    assert "option1_values" not in record
    assert "option2_values" not in record
    assert record["variants"] == [{"flavor": "Rich Chocolate"}]


def test_variant_axis_headers_do_not_pollute_size_or_available_sizes() -> None:
    record = {
        "size": "100",
        "available_sizes": ["Sizes", "Sizes: Standard", "XS", "M"],
        "variant_axes": {
            "size": ["Sizes", "Sizes: Standard", "Sizes: Tall", "XS", "M"],
        },
        "variants": [
            {"size": "Sizes", "option_values": {"size": "Sizes"}},
            {"size": "Sizes: Standard", "option_values": {"size": "Sizes: Standard"}},
            {"size": "XS", "option_values": {"size": "XS"}},
            {"size": "M", "option_values": {"size": "M"}},
        ],
        "selected_variant": {
            "size": "Sizes: Standard",
            "option_values": {"size": "Sizes: Standard"},
        },
    }

    normalize_variant_record(record)

    assert record["size"] == "100"
    assert record["variant_count"] == 2
    assert [variant["size"] for variant in record["variants"]] == ["XS", "M"]
    assert "available_sizes" not in record
    assert "selected_variant" not in record


def test_normalize_variant_record_infers_size_from_variant_titles() -> None:
    record = {
        "title": "Chicken Recipe Dry Dog Food",
        "original_price": "64.99",
        "variants": [
            {
                "title": "Chicken Recipe Dry Dog Food, 4-lb bag",
                "url": "https://www.chewy.com/acme-food/dp/123?size=4-lb",
                "price": "18.99",
            },
            {
                "title": "Chicken Recipe Dry Dog Food, 12-lb bag",
                "url": "https://www.chewy.com/acme-food/dp/123?size=12-lb",
                "price": "42.99",
            },
        ],
    }

    normalize_variant_record(record)

    assert "original_price" not in record["variants"][0]
    assert "original_price" not in record["variants"][1]


def test_extract_detail_infers_chewy_style_offer_variant_sizes() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Chicken Recipe Dry Dog Food",
        "brand": {"@type": "Brand", "name": "Acme"},
        "offers": [
          {
            "@type": "Offer",
            "name": "Chicken Recipe Dry Dog Food, 4-lb bag",
            "url": "https://www.chewy.com/acme-food/dp/123?size=4-lb",
            "price": "18.99",
            "priceCurrency": "USD"
          },
          {
            "@type": "Offer",
            "name": "Chicken Recipe Dry Dog Food, 12-lb bag",
            "url": "https://www.chewy.com/acme-food/dp/123?size=12-lb",
            "price": "42.99",
            "priceCurrency": "USD"
          }
        ]
      }
      </script>
    </head><body><h1>Chicken Recipe Dry Dog Food</h1></body></html>
    """

    rows = extract_records(
        html,
        "https://www.chewy.com/acme-food/dp/123",
        "ecommerce_detail",
        max_records=1,
    )

    assert len(rows) == 1
    record = rows[0]
    assert [row["price"] for row in record["variants"]] == ["18.99", "42.99"]


def test_extract_ecommerce_detail_does_not_infer_price_from_shell_chrome_text() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="iPhone">
      </head>
      <body>
        <aside>
          <p>Trade-in</p>
          <p>Get up to $20 for your old device</p>
        </aside>
        <main>
          <h2>Category navigation</h2>
          <a href="/en-us/l/iphone/example">See all iPhone deals</a>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.backmarket.com/en-us/p/iphone-14-128-gb-midnight/dba71a89-1e8e-4278-967e-0ef1c0d05f31",
        "ecommerce_detail",
        max_records=1,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "iPhone"
    assert "price" not in record
    assert "currency" not in record


def test_extract_ecommerce_detail_does_not_infer_price_from_404_body_text() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="MacBook Pro 15-inch Retina Display Mid 2015 Battery">
      </head>
      <body>
        <main>
          <h1>404</h1>
          <p>Page not found</p>
          <p>Repair kits from $1.99 ship fast.</p>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.ifixit.com/products/macbook-pro-15-inch-retina-display-mid-2015-battery",
        "ecommerce_detail",
        max_records=1,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "MacBook Pro 15-inch Retina Display Mid 2015 Battery"
    assert "price" not in record
    assert "currency" not in record


def test_extract_ecommerce_detail_rejects_404_record_with_filter_variants() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Error 404 .</h1>
          <label for="search-type">Type</label>
          <select id="search-type" name="type">
            <option>all</option>
            <option>release</option>
            <option>artist</option>
            <option>label</option>
          </select>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://www.discogs.com/release/stale",
        "ecommerce_detail",
        max_records=1,
    )

    assert rows == []


def test_extract_ecommerce_detail_reads_books_table_price_currency() -> None:
    html = """
    <html>
      <body>
        <article class="product_page">
          <h1>A Light in the Attic</h1>
          <table>
            <tr><th>Price (excl. tax)</th><td>£51.77</td></tr>
            <tr><th>Availability</th><td>In stock</td></tr>
          </table>
          <p class="price_color">£51.77</p>
        </article>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "ecommerce_detail",
        max_records=1,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "51.77"
    assert record["currency"] == "GBP"


def test_extract_detail_normalizes_shopify_embedded_compare_at_price_from_cents() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trompette 100 suede boots",
          "offers": {
            "price": "939.00",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        <script>
          ShopifyAnalytics.meta = {
            "product": {
              "id": 8214341320770,
              "title": "Trompette 100 suede boots",
              "handle": "trompette-100-suede-boots-rv27109s",
              "vendor": "Roger Vivier",
              "product_type": "Boots",
              "compare_at_price": 156500,
              "variants": [
                {
                  "id": 43633663574082,
                  "price": 93900,
                  "compare_at_price": 156500,
                  "option1": "36",
                  "inventory_quantity": 1
                }
              ]
            }
          };
        </script>
      </head>
      <body>
        <h1>Trompette 100 suede boots</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://savannahs.com/collections/all-boots/products/trompette-100-suede-boots-rv27109s",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["price"] == "939.00"
    assert record["original_price"] == "1565.00"


def test_extract_detail_keeps_shopify_variant_record_when_requested_url_has_product_code_prefix() -> None:
    html = """
    <html>
      <head>
        <script>
          ShopifyAnalytics.meta = {
            "product": {
              "id": 8214341320770,
              "title": "Phoenix dark brown leather boots",
              "vendor": "Chloe",
              "product_type": "Boots",
              "variants": [
                {
                  "id": 43633711644738,
                  "sku": "CH28105S360",
                  "price": 126500,
                  "option1": "36"
                }
              ]
            }
          };
        </script>
      </head>
      <body>
        <h1>Phoenix dark brown leather boots</h1>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://savannahs.com/collections/all-boots/products/phoenix-dark-brown-leather-boots-ch28105s",
        "ecommerce_detail",
        max_records=5,
        requested_page_url="https://savannahs.com/collections/all-boots/products/phoenix-dark-brown-leather-boots-ch28105s",
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Phoenix dark brown leather boots"


def test_extract_detail_strips_variant_availability_suffix_from_option_values() -> None:
    html = """
    <html>
      <body>
        <h1>Phoenix dark brown leather boots</h1>
        <fieldset>
          <legend>Size</legend>
          <input id="size-36" type="radio" name="size" checked>
          <label for="size-36">36 Variant sold out or unavailable</label>
          <input id="size-37" type="radio" name="size">
          <label for="size-37">37 Variant sold out or unavailable</label>
        </fieldset>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://savannahs.com/collections/all-boots/products/phoenix-dark-brown-leather-boots-ch28105s",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1


def test_extract_detail_dom_images_excludes_related_product_cards() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <section class="product-gallery">
          <img src="/images/trail-runner-1.jpg" alt="Trail Runner front">
          <img src="/images/trail-runner-2.jpg" alt="Trail Runner side">
        </section>
        <section class="related-products">
          <a href="/products/city-runner">
            <img src="/images/city-runner.jpg" alt="City Runner">
          </a>
          <a href="/products/mountain-runner">
            <img src="/images/mountain-runner.jpg" alt="Mountain Runner">
          </a>
        </section>
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
    assert record["image_url"] == "https://example.com/images/trail-runner-1.jpg"
    assert record["additional_images"] == [
        "https://example.com/images/trail-runner-2.jpg"
    ]


def test_extract_detail_dom_images_excludes_compare_model_assets() -> None:
    html = """
    <html>
      <body>
        <h1>iPhone 16</h1>
        <main>
          <section class="product-gallery">
            <img src="/images/iphone-16-front.jpg" alt="iPhone 16 front">
            <img src="/images/iphone-16-side.jpg" alt="iPhone 16 side">
          </section>
          <section class="compare-models">
            <img src="/images/iphone-17-pro.jpg" alt="iPhone 17 Pro">
            <img src="/images/iphone-air.jpg" alt="iPhone Air">
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/iphone-16",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["image_url"] == "https://example.com/images/iphone-16-front.jpg"
    assert record["additional_images"] == [
        "https://example.com/images/iphone-16-side.jpg"
    ]


def test_extract_detail_scopes_text_away_from_customers_also_viewed_products() -> None:
    html = """
    <html>
      <body>
        <main class="pdp-main">
          <h1>Alfani Theo Cap Toe Oxford</h1>
          <section class="product-description">
            <h2>Description</h2>
            <p>Polished cap toe oxford with cushioned comfort for formal wear.</p>
          </section>
          <section class="customers-also-viewed">
            <a href="/products/tommy-hilfiger-hiday">Tommy Hilfiger Mens Hiday Casualized Hybrid Oxfords</a>
            <p>Hybrid oxford with sneaker outsole.</p>
            <a href="/products/cole-haan-grand-remix">Cole Haan Grand Remix</a>
            <p>Leather shoe with brogue detail.</p>
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/alfani-theo-cap-toe-oxford",
        "ecommerce_detail",
        max_records=5,
    )

    record = rows[0]
    assert record["title"] == "Alfani Theo Cap Toe Oxford"
    assert "Polished cap toe oxford" in record["description"]
    assert "Tommy Hilfiger" not in record["description"]
    assert "Cole Haan" not in record["description"]


def test_extract_detail_rejects_placeholder_and_ui_asset_images() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Vans Old Skool</h1>
          <section class="product-gallery">
            <img src="https://via.placeholder.com/600" alt="placeholder">
            <img src="/assets/white.svg" alt="white icon">
            <img src="/images/vans-old-skool.jpg" alt="Vans Old Skool">
          </section>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/vans-old-skool",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["image_url"] == "https://example.com/images/vans-old-skool.jpg"


def test_extract_detail_generic_original_price_from_del_or_was_price() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Sale Jacket</h1>
          <span class="price-current">$79.99</span>
          <del>$129.99</del>
        </main>
      </body>
    </html>
    """

    rows = extract_records(
        html,
        "https://example.com/products/sale-jacket",
        "ecommerce_detail",
        max_records=5,
    )

    assert rows[0]["price"] == "79.99"
    assert rows[0]["original_price"] == "129.99"
