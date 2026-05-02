from __future__ import annotations

import pytest

from app.services.adapters.adp import ADPAdapter
from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.belk import BelkAdapter
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.nike import NikeAdapter
from app.services.detail_extractor import build_detail_record, extract_detail_records
from app.services.extraction_html_helpers import extract_job_sections
from app.services.listing_extractor import extract_listing_records
from app.services.xpath_service import extract_selector_value
from tests.fixtures.loader import read_optional_artifact_text


def test_detail_extractor_preserves_css_dom_field_output() -> None:
    html = """
    <html>
      <head>
        <title>Noise Title</title>
      </head>
      <body>
        <aside>
          <h1>Ignore This Title</h1>
          <div>$999.99</div>
        </aside>
        <main>
          <h1>Widget Prime</h1>
          <div class="price">$19.99</div>
          <p>Rated 4.8 out of 5 stars with 128 reviews</p>
        </main>
      </body>
    </html>
    """

    record = build_detail_record(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        ["title", "price", "rating", "review_count"],
    )

    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"
    assert record["rating"] == 4.8
    assert record["review_count"] == 128


def test_listing_extractor_preserves_css_card_field_output() -> None:
    html = """
    <html>
      <body>
        <nav>
          <article class="product-card">
            <a href="/products/ignore-me">
              <h2>Ignore Me</h2>
            </a>
            <div class="price">$999.99</div>
          </article>
        </nav>
        <section>
          <article class="product-card">
            <a href="/products/widget-prime">
              <img src="/images/widget-prime.jpg" alt="Widget Prime">
              <h2 class="product-title">Widget Prime</h2>
            </a>
            <div class="price">$19.99</div>
            <div>4.7 out of 5 stars 128 reviews</div>
          </article>
        </section>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Widget Prime"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[0]["price"] == "19.99"
    assert rows[0]["image_url"] == "https://example.com/images/widget-prime.jpg"
    assert rows[0]["rating"] == 4.7
    assert rows[0]["review_count"] == 128


def test_listing_extractor_prefers_row_detail_link_and_name_over_breadcrumb_links() -> None:
    html = """
    <html>
      <body>
        <table class="catalog-list__body-main">
          <tr class="catalog-list__body-header">
            <td>Image</td>
            <td>Item No.</td>
            <td>Description</td>
          </tr>
          <tr>
            <td align="center">
              <span class="blCatalogImagePopup">
                <img
                  src="https://img.bricklink.com/ItemImage/ST/0/1428-1.t1.png"
                  alt="Set No: 1428 Name: Small Soccer Set 1 {Kabaya Version}"
                />
              </span>
            </td>
            <td nowrap>
              <a href="/v2/catalog/catalogitem.page?S=1428-1">1428-1</a>
              (<a href="catalogItemInv.asp?S=1428-1">Inv</a>)
            </td>
            <td>
              <strong>Small Soccer Set 1 {Kabaya Version}</strong>
              <br />
              20 Parts, 1 Minifigure, 2002
              <br />
              <a href="catalog.asp">Catalog</a>:
              <a href="catalogTree.asp?itemType=S">Sets</a>:
              <a href="/catalogList.asp?catType=S&catString=473">Sports</a>:
              <a href="/catalogList.asp?catType=S&catString=473.224">Soccer</a>
            </td>
          </tr>
          <tr>
            <td align="center">
              <span class="blCatalogImagePopup">
                <img
                  src="https://img.bricklink.com/ItemImage/ST/0/1428-2.t1.png"
                  alt="Set No: 1428 Name: Small Soccer Set 1 polybag"
                />
              </span>
            </td>
            <td nowrap>
              <a href="/v2/catalog/catalogitem.page?S=1428-2">1428-2</a>
              (<a href="catalogItemInv.asp?S=1428-2">Inv</a>)
            </td>
            <td>
              <strong>Small Soccer Set 1 polybag</strong>
              <br />
              20 Parts, 1 Minifigure, 2002
              <br />
              <a href="catalog.asp">Catalog</a>:
              <a href="catalogTree.asp?itemType=S">Sets</a>:
              <a href="/catalogList.asp?catType=S&catString=473">Sports</a>:
              <a href="/catalogList.asp?catType=S&catString=473.224">Soccer</a>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://www.bricklink.com/catalogList.asp?catType=S&catString=473",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://www.bricklink.com/catalogList.asp?catType=S&catString=473",
            "_source": "dom_listing",
            "title": "Small Soccer Set 1 {Kabaya Version}",
            "image_url": "https://img.bricklink.com/ItemImage/ST/0/1428-1.t1.png",
            "url": "https://www.bricklink.com/v2/catalog/catalogitem.page?S=1428-1",
        },
        {
            "source_url": "https://www.bricklink.com/catalogList.asp?catType=S&catString=473",
            "_source": "dom_listing",
            "title": "Small Soccer Set 1 polybag",
            "image_url": "https://img.bricklink.com/ItemImage/ST/0/1428-2.t1.png",
            "url": "https://www.bricklink.com/v2/catalog/catalogitem.page?S=1428-2",
        },
    ]


def test_listing_extractor_does_not_remove_body_for_sidebar_layouts() -> None:
    html = """
    <html>
      <body class="right-sidebar woocommerce-active">
        <main>
          <ul class="products columns-4">
            <li class="product">
              <a href="https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/" class="woocommerce-LoopProduct-link woocommerce-loop-product__link">
                <img src="https://www.scrapingcourse.com/ecommerce/wp-content/uploads/2024/03/mh09-blue_main.jpg" alt="">
                <h2 class="woocommerce-loop-product__title">Abominable Hoodie</h2>
                <span class="price">$69.00</span>
              </a>
            </li>
          </ul>
        </main>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://www.scrapingcourse.com/ecommerce/",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://www.scrapingcourse.com/ecommerce/",
            "_source": "dom_listing",
            "title": "Abominable Hoodie",
            "price": "69.00",
            "currency": "USD",
            "image_url": "https://www.scrapingcourse.com/ecommerce/wp-content/uploads/2024/03/mh09-blue_main.jpg",
            "url": "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
        }
    ]


def test_listing_extractor_preserves_faceted_grid_results() -> None:
    html = """
    <html>
      <body>
        <div class="faceted-grid">
          <ul class="rc-listing-grid">
            <li class="rc-listing-grid__item">
              <article class="product-card">
                <a href="/item/alpha-strat">
                  <h2 class="product-title">Alpha Strat</h2>
                </a>
                <div class="price">$1,299.00</div>
              </article>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://reverb.com/marketplace?product_type=electric-guitars",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://reverb.com/marketplace?product_type=electric-guitars",
            "_source": "dom_listing",
            "title": "Alpha Strat",
            "price": "1299.00",
            "currency": "USD",
            "url": "https://reverb.com/item/alpha-strat",
        }
    ]


def test_listing_extractor_accepts_image_link_cards_with_separate_title_text() -> None:
    html = """
    <html>
      <body>
        <div class="product-card">
          <a href="/p/connect-in-colour-eyeshadow-palette-rose-lens?sku=2640287" aria-label="View product image">
            <img src="/images/rose-lens.jpg" alt="Connect In Colour Eyeshadow Palette Rose Lens">
          </a>
          <div class="product-brand">MAC</div>
          <div class="product-name">Connect In Colour Eyeshadow Palette Rose Lens</div>
          <div class="price">$35.00</div>
          <a href="/bag/add?sku=2640287">Add to bag</a>
        </div>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://www.ulta.com/shop/makeup/makeup-palettes",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://www.ulta.com/shop/makeup/makeup-palettes",
            "_source": "dom_listing",
            "title": "Connect In Colour Eyeshadow Palette Rose Lens",
            "brand": "MAC",
            "price": "35.00",
            "currency": "USD",
            "image_url": "https://www.ulta.com/images/rose-lens.jpg",
            "url": "https://www.ulta.com/p/connect-in-colour-eyeshadow-palette-rose-lens?sku=2640287",
        }
    ]


def test_listing_extractor_does_not_emit_additional_images() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/products/widget-prime">
            <img src="/images/widget-prime-main.jpg" alt="Widget Prime">
            <img src="/images/widget-prime-alt.jpg" alt="Widget Prime alternate">
            <h2 class="product-title">Widget Prime</h2>
          </a>
          <div class="price">$19.99</div>
        </article>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "dom_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "image_url": "https://example.com/images/widget-prime-main.jpg",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_listing_extractor_prefers_explicit_price_node_over_description_mentions_and_keeps_currency() -> None:
    html = """
    <html>
      <body>
        <article class="product-card">
          <a href="/products/remastered">
            <img src="/images/remastered.jpg" alt="The Last of Us Remastered">
            <h2 class="product-title">The Last of Us Remastered</h2>
          </a>
          <p class="description">
            Includes additional game content: over $30 in value.
          </p>
          <div class="price-wrapper">92,99 €</div>
        </article>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://sandbox.oxylabs.io/products",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://sandbox.oxylabs.io/products",
            "_source": "dom_listing",
            "title": "The Last of Us Remastered",
            "price": "92.99",
            "currency": "EUR",
            "image_url": "https://sandbox.oxylabs.io/images/remastered.jpg",
            "url": "https://sandbox.oxylabs.io/products/remastered",
        }
    ]


def test_listing_extractor_avoids_numeric_title_nodes_when_real_title_exists() -> None:
    html = """
    <html>
      <body>
        <div class="product-card">
          <a href="/products/widget-prime" aria-label="Widget Prime">
            <img src="/images/widget-prime.jpg" alt="Widget Prime">
          </a>
          <div class="product-title">1</div>
          <div class="product-name">Widget Prime</div>
          <div class="price">$19.99</div>
        </div>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "dom_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "image_url": "https://example.com/images/widget-prime.jpg",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_listing_extractor_filters_category_cloud_links_when_supported_product_tiles_exist() -> None:
    product_rows = "\n".join(
        f"""
        <li class="product-grid-product">
          <a href="/in/en/regular-fit-shirt-p44{i:02d}.html">
            <img src="/images/p{i}.jpg" alt="Regular Fit Shirt {i}">
            <span>Regular Fit Shirt {i}</span>
          </a>
          <span>₹ 3,950.00</span>
        </li>
        """
        for i in range(1, 13)
    )
    category_links = "\n".join(
        f'<li><a href="/in/en/man-shirts-l{index}.html">Men Shirts {index}</a></li>'
        for index in range(1, 10)
    )
    html = f"""
    <html>
      <body>
        <nav><ul>{category_links}</ul></nav>
        <main><ul class="product-grid">{product_rows}</ul></main>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://www.zara.com/in/en/man-shirts-l737.html",
        "ecommerce_listing",
        max_records=20,
    )

    assert len(rows) == 12
    assert all("/regular-fit-shirt-p44" in row["url"] for row in rows)
    assert all("Men Shirts" not in row["title"] for row in rows)


@pytest.mark.parametrize(
    ("artifact_path", "url", "surface", "blocked_terms"),
    [
        (
            "artifacts/runs/8/pages/169dea1b9aaaa49e.html",
            "https://www.usajobs.gov/search/results/?k=software+engineer&p=1",
            "job_listing",
            ("sort by", "career explorer"),
        ),
        (
            "artifacts/runs/9/pages/4eabd73fbea7fd19.html",
            "https://startup.jobs/",
            "job_listing",
            ("bookmark apply",),
        ),
        (
            "artifacts/runs/19/pages/b1c15ef21f4b7b2d.html",
            "https://www.karenmillen.com/eu/categories/womens-trousers",
            "ecommerce_listing",
            ("flash promo", "code:"),
        ),
    ],
)
def test_listing_extractor_filters_acceptance_artifact_noise(
    artifact_path: str,
    url: str,
    surface: str,
    blocked_terms: tuple[str, ...],
) -> None:
    html = read_optional_artifact_text(artifact_path)

    rows = extract_listing_records(
        html,
        url,
        surface,
        max_records=10,
    )

    for row in rows:
        lowered_title = str(row.get("title") or "").lower()
        lowered_url = str(row.get("url") or "").lower()
        assert all(term not in lowered_title for term in blocked_terms)
        assert all(term not in lowered_url for term in blocked_terms)


def test_job_listing_extractor_accepts_careerdetail_id_cards() -> None:
    html = """
    <html>
      <body>
        <ul>
          <li data-testid="careers-search-result-listing">
            <article class="mb-2">
              <a href="/careerdetail/?id=100901" class="listings__link bg-white rounded-lg p-4 md:p-6 text-left block">
                <div>
                  <img src="https://cdn.example.com/logo.png" alt="">
                  <h2 data-testid="careers-search-result-listing-job-title">
                    1st Shift Inbound Assistant Manager
                  </h2>
                  <span data-testid="careers-search-result-listing-company-name">
                    WebstaurantStore
                  </span>
                  <span data-testid="careers-search-result-listing-job-location">
                    <img src="https://cdn.example.com/vectorlocation.svg" alt="location:">
                    Dayton, NV
                  </span>
                </div>
              </a>
            </article>
          </li>
        </ul>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://careers.clarkassociatesinc.biz/",
        "job_listing",
        max_records=10,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "1st Shift Inbound Assistant Manager"
    assert (
        rows[0]["url"]
        == "https://careers.clarkassociatesinc.biz/careerdetail/?id=100901"
    )


def test_job_listing_extractor_rejects_footer_document_asset_rows() -> None:
    html = """
    <html>
      <body>
        <footer>
          <div>
            <p>
              © 2025 Lewis & Clark Behavioral Health
              <a href="https://lcbhs.net/privacy-policy/" title="Privacy Policy">Privacy Policy</a>
              <a href="https://lcbhs.net/wp-content/uploads/990-Posted-on-Website-2023.pdf"
                 title="LCBHS 990">LCBHS 990</a>
              <a href="https://productionmonkeys.com/" title="Production Monkeys">
                Website Design by Production Monkeys
              </a>
            </p>
          </div>
        </footer>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://lcbhs.net/careers/",
        "job_listing",
        max_records=10,
    )

    assert rows == []


def test_listing_extractor_ignores_none_embedded_json_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = """
    <html>
      <body>
        <section>
          <article class="product-card">
            <a href="/products/widget-prime">
              <h2>Widget Prime</h2>
            </a>
            <div>$19.99</div>
          </article>
        </section>
      </body>
    </html>
    """

    def _fake_structured_payloads(*args, **kwargs):
        del args, kwargs
        return (
            ("json_ld", []),
            ("microdata", []),
            ("opengraph", []),
            ("embedded_json", [None, {"@type": "ItemList", "itemListElement": []}]),
            ("js_state", []),
        )

    monkeypatch.setattr(
        "app.services.listing_extractor.collect_structured_source_payloads",
        _fake_structured_payloads,
    )

    rows = extract_listing_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "dom_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_detail_extractor_ignores_js_state_inside_removed_noise_containers() -> None:
    html = """
    <html>
      <body>
        <aside>
          <script type="application/json" id="__NEXT_DATA__">
          {
            "props": {
              "pageProps": {
                "product": {
                  "title": "Noise Widget",
                  "price": "999.99",
                  "description": "Sidebar state that should be ignored."
                }
              }
            }
          }
          </script>
        </aside>
        <main>
          <h1>Widget Prime</h1>
          <div class="price">$19.99</div>
          <p>Built from the primary content area.</p>
        </main>
      </body>
    </html>
    """

    record = build_detail_record(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        ["title", "price", "description"],
    )

    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"
    assert record["_source"] != "js_state"


def test_listing_extractor_ignores_structured_payloads_inside_removed_noise_containers() -> None:
    html = """
    <html>
      <body>
        <aside>
          <script type="application/json">
          {
            "@type": "Product",
            "name": "Noise Widget",
            "url": "/products/noise-widget",
            "offers": {
              "price": "999.99"
            }
          }
          </script>
        </aside>
        <main>
          <article class="product-card">
            <a href="/products/widget-prime">
              <h2>Widget Prime</h2>
            </a>
            <div class="price">$19.99</div>
          </article>
        </main>
      </body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://example.com/collections/widgets",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://example.com/collections/widgets",
            "_source": "dom_listing",
            "title": "Widget Prime",
            "price": "19.99",
            "currency": "USD",
            "url": "https://example.com/products/widget-prime",
        }
    ]


def test_detail_extractor_normalizes_category_objects_from_network_payloads() -> None:
    record = build_detail_record(
        "<html><body><h1>Combination Pliers</h1></body></html>",
        "https://practicesoftwaretesting.com/product/01KPJ56NBS8K3WVA5E9F7GX94R",
        "ecommerce_detail",
        ["title", "category"],
        network_payloads=[
            {
                "body": {
                    "product": {
                        "title": "Combination Pliers",
                        "price": "14.15",
                        "category": {
                            "id": "01KPJ56NAAWFTC0M9X80YZJ3F5",
                            "name": "Pliers",
                            "slug": "pliers",
                        },
                    }
                }
            }
        ],
    )

    assert record["title"] == "Combination Pliers"
    assert record["category"] == "Pliers"


def test_detail_extractor_reads_category_from_dom_breadcrumbs() -> None:
    record = build_detail_record(
        """
        <html>
          <body>
            <ol aria-label="breadcrumb">
              <li><a href="/">Home</a></li>
              <li><a href="/women">Women</a></li>
              <li><a href="/women/dresses">Dresses</a></li>
              <li>Linen Midi Dress</li>
            </ol>
            <main><h1>Linen Midi Dress</h1></main>
          </body>
        </html>
        """,
        "https://example.com/products/linen-midi-dress",
        "ecommerce_detail",
        ["title", "category", "gender"],
    )

    assert record["title"] == "Linen Midi Dress"
    assert record["category"] == "Women > Dresses"
    assert record["gender"] == "women"


def test_detail_extractor_prefers_visible_breadcrumb_category_over_structured_category() -> None:
    record = build_detail_record(
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Just Vibes Strapless Pant Set - Yellow",
              "category": "Furniture Sets",
              "image": "https://example.com/pant-set.jpg",
              "offers": {"@type": "Offer", "price": "18.00", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body>
            <nav class="MuiBreadcrumbs-root">
              <ol>
                <li><a href="/women">Women</a></li>
                <li aria-hidden="true">›</li>
                <li><a href="/matching-sets">Shop All Matching Sets</a></li>
                <li aria-hidden="true">›</li>
                <li><span>Just Vibes Strapless Pant Set - Yellow</span></li>
              </ol>
            </nav>
            <main><h1>Just Vibes Strapless Pant Set - Yellow</h1></main>
          </body>
        </html>
        """,
        "https://example.com/products/just-vibes-strapless-pant-set-yellow",
        "ecommerce_detail",
        None,
    )

    assert record["category"] == "Women > Matching Sets"
    assert record["gender"] == "women"


def test_listing_extractor_prefers_structured_name_over_item_position_for_title() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ItemList",
          "itemListElement": [
            {
              "@type": "ListItem",
              "position": 1,
              "item": {
                "@type": "Product",
                "name": "Dyson V12 Detect Slim",
                "url": "/vacuum-cleaners/cord-free/dyson-v12-detect-slim",
                "offers": {
                  "@type": "Offer",
                  "price": "55900",
                  "availability": "https://schema.org/InStock"
                }
              }
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    rows = extract_listing_records(
        html,
        "https://www.dyson.in/vacuum-cleaners/cord-free",
        "ecommerce_listing",
        max_records=10,
    )

    assert rows == [
        {
            "source_url": "https://www.dyson.in/vacuum-cleaners/cord-free",
            "_source": "structured_listing",
            "title": "Dyson V12 Detect Slim",
            "price": "55900",
            "availability": "in_stock",
            "url": "https://www.dyson.in/vacuum-cleaners/cord-free/dyson-v12-detect-slim",
        }
    ]


def test_xpath_selector_extraction_remains_unchanged() -> None:
    html = """
    <html>
      <body>
        <div class="details">
          <span data-testid="salary">$150,000</span>
        </div>
      </body>
    </html>
    """

    value, count, selector_used = extract_selector_value(
        html,
        xpath="//span[@data-testid='salary']/text()",
    )

    assert value == "$150,000"
    assert count == 1
    assert selector_used == "//span[@data-testid='salary']/text()"


def test_xpath_selector_extraction_applies_regex_to_xpath_result() -> None:
    html = """
    <html>
      <body>
        <span class="rating">star-rating Three</span>
        <script>var unrelated = "star-rating Five";</script>
      </body>
    </html>
    """

    value, count, selector_used = extract_selector_value(
        html,
        xpath="//span[@class='rating']/text()",
        regex=r"star-rating\s+(\w+)",
    )

    assert value == "Three"
    assert count == 1
    assert selector_used == "//span[@class='rating']/text()"


@pytest.mark.asyncio
async def test_amazon_adapter_preserves_css_field_output() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/dp/example",
        """
        <html>
          <body>
            <span id="productTitle">Widget Prime</span>
            <span class="a-price"><span class="a-offscreen">$19.99</span></span>
            <a id="bylineInfo">Brand: Orion</a>
            <span id="acrCustomerReviewText">128 ratings</span>
            <span id="acrPopover"><span class="a-icon-alt">4.8 out of 5 stars</span></span>
            <img id="landingImage" src="https://example.com/widget.jpg">
            <div id="feature-bullets">Fast shipping and long battery life.</div>
            <div id="availability"><span>In Stock.</span></div>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record["title"] == "Widget Prime"
    assert record["price"] == "$19.99"
    assert record["brand"] == "Orion"
    assert record["rating"] == 4.8
    assert record["review_count"] == 128
    assert record["image_url"] == "https://example.com/widget.jpg"


@pytest.mark.asyncio
async def test_amazon_adapter_preserves_currency_code_in_price_text() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/dp/example",
        """
        <html>
          <body>
            <span id="productTitle">Widget Prime</span>
            <span class="a-price"><span class="a-offscreen">USD 19.99</span></span>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["price"] == "USD 19.99"
    assert record["currency"] == "USD"


@pytest.mark.asyncio
async def test_amazon_adapter_preserves_store_brand_suffix() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/dp/example",
        """
        <html>
          <body>
            <span id="productTitle">Mesh Shorts</span>
            <a id="bylineInfo">Visit the Under Armour Store</a>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    assert result.records[0]["brand"] == "Under Armour"


@pytest.mark.asyncio
async def test_amazon_adapter_extracts_inline_twister_variants() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/Under-Armour-Mens-Tech-Shorts/dp/B016APPQ4S",
        """
        <html>
          <body>
            <span id="productTitle">Under Armour Men's Tech Mesh Shorts</span>
            <a id="bylineInfo">Visit the Under Armour Store</a>
            <div id="inline-twister-row-color_name"></div>
            <div id="inline-twister-row-size_name"></div>
            <script type="a-state" data-a-state='{"key":"desktop-twister-sort-filter-data"}'>
            {
              "sortedVariations": [[0,1],[0,2],[1,3],[1,0]],
              "sortedDimValuesForAllDims": {
                "size_name": [
                  {"indexInDimList":0,"defaultAsin":"B07D7TVW4Y","dimensionValueState":"UNAVAILABLE","dimensionValueDisplayText":"X-Small","pageLoadURL":"/dp/B07D7TVW4Y/ref=twister_B016APPQ4S"},
                  {"indexInDimList":1,"defaultAsin":"B095SJ18YH","dimensionValueState":"SELECTED","dimensionValueDisplayText":"Large"},
                  {"indexInDimList":2,"defaultAsin":"B095SGXBJ2","dimensionValueState":"AVAILABLE","dimensionValueDisplayText":"X-Large","pageLoadURL":"/dp/B095SGXBJ2/ref=twister_B016APPQ4S"},
                  {"indexInDimList":3,"defaultAsin":"B095SL1G2D","dimensionValueState":"UNAVAILABLE","dimensionValueDisplayText":"4X-Large Big","pageLoadURL":"/dp/B095SL1G2D/ref=twister_B016APPQ4S"}
                ],
                "color_name": [
                  {"indexInDimList":0,"defaultAsin":"B095SJ18YH","dimensionValueState":"SELECTED","dimensionValueDisplayText":"Pitch Gray-black"},
                  {"indexInDimList":1,"defaultAsin":"B095SL1G2D","dimensionValueState":"UNAVAILABLE","dimensionValueDisplayText":"Pitch Gray/Black","pageLoadURL":"/dp/B095SL1G2D/ref=twister_B016APPQ4S"}
                ]
              }
            }
            </script>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["brand"] == "Under Armour"
    assert record["color"] == "Pitch Gray-black"
    assert record["size"] == "Large"
    assert record["variant_axes"] == {
        "color": ["Pitch Gray-black", "Pitch Gray/Black"],
        "size": ["X-Small", "Large", "X-Large", "4X-Large Big"],
    }
    assert record["variant_count"] == 4
    assert record["selected_variant"]["option_values"] == {
        "color": "Pitch Gray-black",
        "size": "Large",
    }


@pytest.mark.asyncio
async def test_amazon_adapter_extracts_detail_completeness_fields() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/dp/B08J5F3G18",
        """
        <html>
          <body>
            <span id="productTitle">EVGA GeForce RTX 3090</span>
            <span class="a-price"><span class="a-offscreen">$1,499.99</span></span>
            <a id="bylineInfo">Visit the EVGA Store</a>
            <div id="availability"><span>In Stock.</span></div>
            <div id="wayfinding-breadcrumbs_feature_div"><ul><li>Computer Graphics Cards</li></ul></div>
            <img id="landingImage" data-old-hires="https://m.media-amazon.com/images/I/71tLsSyLUZL._SX700_.jpg">
            <div id="altImages">
              <img src="https://m.media-amazon.com/images/I/71tLsSyLUZL._SX700_.jpg">
              <img src="https://m.media-amazon.com/images/I/71tLsSyLUZL._SX900_.jpg">
            </div>
            <div id="feature-bullets">
              <ul>
                <li><span class="a-list-item">24GB GDDR6X memory</span></li>
                <li><span class="a-list-item">Triple-fan cooling</span></li>
              </ul>
            </div>
            <div id="productDescription"><p>Flagship graphics card for 4K gaming.</p></div>
            <table id="productDetails_techSpec_section_1">
              <tr><th>ASIN</th><td>B08J5F3G18</td></tr>
              <tr><th>Item model number</th><td>24G-P5-3987-KR</td></tr>
              <tr><th>UPC</th><td>843368067763</td></tr>
            </table>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["sku"] == "B08J5F3G18"
    assert record["product_id"] == "B08J5F3G18"
    assert record["part_number"] == "24G-P5-3987-KR"
    assert record["barcode"] == "843368067763"
    assert record["currency"] == "USD"
    assert record["availability"] == "In Stock."
    assert record["product_type"] == "Computer Graphics Cards"
    assert record["features"] == ["24GB GDDR6X memory", "Triple-fan cooling"]
    assert record["additional_images"] == [
        "https://m.media-amazon.com/images/I/71tLsSyLUZL._SX900_.jpg"
    ]


@pytest.mark.asyncio
async def test_belk_adapter_extracts_nested_state_brand_price_and_currency() -> None:
    result = await BelkAdapter().extract(
        "https://www.belk.com/home/",
        """
        <html>
          <body>
            <script>
              window.__INITIAL_STATE__ = {
                "search": {
                  "products": [
                    {
                      "productName": "Checkerboard Quilt Set",
                      "brand": {"name": "Modern Southern Home"},
                      "salePrice": {"amount": "22.50", "currencyCode": "USD"},
                      "image": {"url": "https://belk.scene7.com/is/image/Belk/7100974"},
                      "productUrl": "/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html"
                    }
                  ]
                }
              };
            </script>
          </body>
        </html>
        """,
        "ecommerce_listing",
    )

    assert result.records == [
        {
            "title": "Checkerboard Quilt Set",
            "brand": "Modern Southern Home",
            "price": "22.50",
            "currency": "USD",
            "image_url": "https://belk.scene7.com/is/image/Belk/7100974",
            "url": "https://www.belk.com/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html",
            "_source": "belk_adapter",
        }
    ]


@pytest.mark.asyncio
async def test_belk_adapter_prefers_real_currency_fields_over_scalar_price_text() -> None:
    result = await BelkAdapter().extract(
        "https://www.belk.com/home/",
        """
        <html>
          <body>
            <script>
              window.__INITIAL_STATE__ = {
                "search": {
                  "products": [
                    {
                      "productName": "Free Sample",
                      "brand": {"name": "Acme"},
                      "price": "0.00",
                      "currencyCode": "USD",
                      "image": {"url": "https://belk.scene7.com/is/image/Belk/free-sample"},
                      "productUrl": "/p/free-sample/000.html"
                    }
                  ]
                }
              };
            </script>
          </body>
        </html>
        """,
        "ecommerce_listing",
    )

    assert result.records == [
        {
            "title": "Free Sample",
            "brand": "Acme",
            "price": "0.00",
            "currency": "USD",
            "image_url": "https://belk.scene7.com/is/image/Belk/free-sample",
            "url": "https://www.belk.com/p/free-sample/000.html",
            "_source": "belk_adapter",
        }
    ]


@pytest.mark.asyncio
async def test_belk_adapter_ignores_aggregate_range_prices_in_state_payload() -> None:
    result = await BelkAdapter().extract(
        "https://www.belk.com/home/",
        """
        <html>
          <body>
            <script>
              window.__INITIAL_STATE__ = {
                "search": {
                  "products": [
                    {
                      "productName": "Plus Size Ruffle Back Cropped Pants",
                      "brand": {"name": "Crown & Ivy"},
                      "maxPrice": 225,
                      "image": {"url": "https://belk.scene7.com/is/image/Belk/35512462"},
                      "productUrl": "/p/crown-ivy-plus-size-ruffle-back-cropped-pants/180415535512462.html"
                    }
                  ]
                }
              };
            </script>
          </body>
        </html>
        """,
        "ecommerce_listing",
    )

    assert result.records == [
        {
            "title": "Plus Size Ruffle Back Cropped Pants",
            "brand": "Crown & Ivy",
            "image_url": "https://belk.scene7.com/is/image/Belk/35512462",
            "url": "https://www.belk.com/p/crown-ivy-plus-size-ruffle-back-cropped-pants/180415535512462.html",
            "_source": "belk_adapter",
        }
    ]


@pytest.mark.asyncio
async def test_amazon_adapter_does_not_fabricate_multi_axis_twister_product() -> None:
    result = await AmazonAdapter().extract(
        "https://www.amazon.com/Under-Armour-Mens-Tech-Shorts/dp/B016APPQ4S",
        """
        <html>
          <body>
            <span id="productTitle">Under Armour Men's Tech Mesh Shorts</span>
            <div id="inline-twister-row-color_name"></div>
            <div id="inline-twister-row-size_name"></div>
            <script type="a-state" data-a-state='{"key":"desktop-twister-sort-filter-data"}'>
            {
              "sortedDimValuesForAllDims": {
                "size_name": [
                  {"dimensionValueState":"SELECTED","dimensionValueDisplayText":"Large"},
                  {"dimensionValueState":"AVAILABLE","dimensionValueDisplayText":"X-Large"}
                ],
                "color_name": [
                  {"dimensionValueState":"SELECTED","dimensionValueDisplayText":"Black"},
                  {"dimensionValueState":"AVAILABLE","dimensionValueDisplayText":"Blue"}
                ]
              }
            }
            </script>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert "variants" not in record
    assert record["variant_axes"] == {
        "color": ["Black", "Blue"],
        "size": ["Large", "X-Large"],
    }


@pytest.mark.asyncio
async def test_nike_adapter_maps_preloaded_state_product() -> None:
    result = await NikeAdapter().extract(
        "https://www.nike.in/nike-pro-training-men-s-dri-fit-short-sleeve-top/p/24829693",
        """
        <html>
          <body>
            <script id="__PRELOADED_STATE__" type="application/json">
            {
              "details": {
                "skuData": {
                  "product": {
                    "id": "24829693",
                    "sku": "NIKEX00027953",
                    "discountedPrice": 1996,
                    "price": 2495,
                    "imageUrl": "https://example.com/nike-1.jpg",
                    "color": {"name": "Green"},
                    "action_url": "/nike-pro-training-men-s-dri-fit-short-sleeve-top/p/24829693",
                    "title": "Nike Pro Training",
                    "subTitle": "Men's Dri-FIT Short-Sleeve Top",
                    "isOutOfStock": 0,
                    "product_summary": {"description": "Train with ease."},
                    "productMedia": [
                      {"mediaType": "image", "url": "https://example.com/nike-1.jpg"},
                      {"mediaType": "image", "url": "https://example.com/nike-2.jpg"}
                    ],
                    "sizeOptions": {
                      "title": "Select Size",
                      "options": [
                        {"id": "24828378", "sku": "NIKEX00026638", "sizeName": "XXS", "discountedPrice": 1996, "price": 2495, "isOutOfStock": 1},
                        {"id": "24828336", "sku": "NIKEX00026596", "sizeName": "S", "discountedPrice": 1996, "price": 2495, "isOutOfStock": 0}
                      ]
                    }
                  }
                }
              }
            }
            </script>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["title"] == "Nike Pro Training Men's Dri-FIT Short-Sleeve Top"
    assert record["brand"] == "Nike"
    assert record["price"] == "1996"
    assert record["original_price"] == "2495"
    assert record["color"] == "Green"
    assert record["size"] == "S"
    assert record["variant_axes"] == {"size": ["XXS", "S"]}
    assert record["available_sizes"] == ["XXS", "S"]
    assert record["selected_variant"]["option_values"] == {
        "size": "S",
        "color": "Green",
    }
    assert record["selected_variant"]["availability"] == "in_stock"


@pytest.mark.asyncio
async def test_nike_detail_extraction_uses_adapter_and_rejects_shell_json_ld() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Corporation","name":"Nike","founders":[{"@type":"Person","name":"Bill Bowerman"}]}
        </script>
      </head>
      <body>
        <label>Text
          <select><option>White</option><option>Black</option><option>Red</option></select>
        </label>
        <label>Background
          <select><option>Opaque</option><option>Semi-Transparent</option></select>
        </label>
        <script id="__PRELOADED_STATE__" type="application/json">
        {
          "details": {
            "skuData": {
              "product": {
                "id": "24809354",
                "sku": "NIKEX00021288",
                "discountedPrice": 1495,
                "price": 1495,
                "imageUrl": "https://example.com/nike.jpg",
                "color": {"name": "Black"},
                "action_url": "/nike-pro-men-s-dri-fit-tight-sleeveless-fitness-top/p/24809354",
                "title": "Nike Pro",
                "subTitle": "Men's Dri-FIT Tight Sleeveless Fitness Top",
                "isOutOfStock": 0,
                "sizeOptions": {
                  "title": "Select Size",
                  "options": [
                    {"id": "24809169", "sku": "NIKEX00021103", "sizeName": "XS", "discountedPrice": 1495, "price": 1495, "isOutOfStock": 1},
                    {"id": "24809174", "sku": "NIKEX00021108", "sizeName": "S", "discountedPrice": 1495, "price": 1495, "isOutOfStock": 0}
                  ]
                }
              }
            }
          }
        }
        </script>
      </body>
    </html>
    """
    url = "https://www.nike.in/nike-pro-men-s-dri-fit-tight-sleeveless-fitness-top/p/24809354"
    adapter_records = (
        await NikeAdapter().extract(url, html, "ecommerce_detail")
    ).records
    records = extract_detail_records(
        html,
        url,
        "ecommerce_detail",
        None,
        adapter_records=adapter_records,
    )

    record = records[0]
    assert record["title"] == "Nike Pro Men's Dri-FIT Tight Sleeveless Fitness Top"
    assert record["brand"] == "Nike"
    assert record["variant_axes"] == {"size": ["XS", "S"]}
    assert record["variant_count"] == 2
    assert record["size"] == "S"
    assert "Bill Bowerman" not in record.values()
    assert "background" not in record["variant_axes"]
    assert "text" not in record["variant_axes"]


@pytest.mark.asyncio
async def test_nike_adapter_maps_next_data_selected_product_payload() -> None:
    result = await NikeAdapter().extract(
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        """
        <html>
          <body>
            <script id="__NEXT_DATA__" type="application/json">
            {
              "props": {
                "pageProps": {
                  "colorwayImages": [
                    {
                      "portraitImg": "https://static.nike.com/af1-main.jpg",
                      "squarishImg": "https://static.nike.com/af1-alt.jpg"
                    }
                  ],
                  "selectedProduct": {
                    "id": "13071857",
                    "styleCode": "CW2288",
                    "styleColor": "CW2288-111",
                    "colorDescription": "White/White",
                    "prices": {
                      "currency": "USD",
                      "currentPrice": 115,
                      "initialPrice": 115
                    },
                    "productInfo": {
                      "title": "Nike Air Force 1 '07",
                      "subtitle": "Men's Shoes",
                      "productDescription": "Comfortable, durable and timeless.",
                      "path": "/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
                      "featuresAndBenefits": [
                        {"body": "<ul><li>Padded collar</li></ul>"}
                      ]
                    },
                    "sizes": [
                      {
                        "label": "6",
                        "status": "ACTIVE",
                        "merchSkuId": "sku-6",
                        "gtins": [{"gtin": "00194500874886"}]
                      },
                      {
                        "label": "7",
                        "status": "OOS",
                        "merchSkuId": "sku-7",
                        "gtins": [{"gtin": "00194500874909"}]
                      }
                    ]
                  }
                }
              }
            }
            </script>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["title"] == "Nike Air Force 1 '07 Men's Shoes"
    assert record["sku"] == "CW2288-111"
    assert record["price"] == "115"
    assert record["currency"] == "USD"
    assert record["image_url"] == "https://static.nike.com/af1-main.jpg"
    assert record["additional_images"] == ["https://static.nike.com/af1-alt.jpg"]
    assert record["variant_axes"] == {"size": ["6", "7"]}
    assert record["variants"][0]["barcode"] == "00194500874886"
    assert record["variants"][0]["price"] == "115"
    assert record["variants"][1]["availability"] == "out_of_stock"


@pytest.mark.asyncio
async def test_nike_adapter_maps_nested_next_data_price_objects() -> None:
    result = await NikeAdapter().extract(
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        """
        <html>
          <body>
            <script id="__NEXT_DATA__" type="application/json">
            {
              "props": {
                "pageProps": {
                  "selectedProduct": {
                    "id": "13071857",
                    "styleColor": "CW2288-111",
                    "colorDescription": "White/White",
                    "prices": {
                      "currentPrice": {"value": 115},
                      "initialPrice": {"value": 130}
                    },
                    "productInfo": {
                      "title": "Nike Air Force 1 '07",
                      "subtitle": "Men's Shoes",
                      "path": "/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111"
                    },
                    "sizes": [
                      {
                        "label": "6",
                        "status": "ACTIVE",
                        "merchSkuId": "sku-6"
                      }
                    ]
                  }
                }
              }
            }
            </script>
          </body>
        </html>
        """,
        "ecommerce_detail",
    )

    record = result.records[0]
    assert record["price"] == "115"
    assert record["original_price"] == "130"
    assert record["variants"][0]["price"] == "115"
    assert record["variants"][0]["original_price"] == "130"


@pytest.mark.asyncio
async def test_ebay_adapter_preserves_css_listing_output() -> None:
    result = await EbayAdapter().extract(
        "https://www.ebay.com/sch/i.html?_nkw=widget",
        """
        <html>
          <body>
            <div class="s-item">
              <a class="s-item__link" href="https://www.ebay.com/itm/123">
                <div class="s-item__title">Widget Prime</div>
              </a>
              <div class="s-item__price">$29.99</div>
              <div class="s-item__image-wrapper">
                <img src="https://example.com/ebay-widget.jpg">
              </div>
            </div>
          </body>
        </html>
        """,
        "ecommerce_listing",
    )

    assert result.records == [
        {
            "title": "Widget Prime",
            "price": "$29.99",
            "image_url": "https://example.com/ebay-widget.jpg",
            "url": "https://www.ebay.com/itm/123",
        }
    ]


@pytest.mark.asyncio
async def test_indeed_adapter_preserves_css_listing_output() -> None:
    result = await IndeedAdapter().extract(
        "https://www.indeed.com/jobs?q=engineer",
        """
        <html>
          <body>
            <div class="job_seen_beacon">
              <h2><a href="/viewjob?jk=123"><span>Data Engineer</span></a></h2>
              <div data-testid="company-name">Data Corp</div>
              <div data-testid="text-location">Bengaluru</div>
              <div class="salary-snippet-container">₹30,00,000 a year</div>
            </div>
          </body>
        </html>
        """,
        "job_listing",
    )

    assert result.records == [
        {
            "title": "Data Engineer",
            "company": "Data Corp",
            "location": "Bengaluru",
            "salary": "₹30,00,000 a year",
            "apply_url": "https://www.indeed.com/viewjob?jk=123",
        }
    ]


@pytest.mark.asyncio
async def test_indeed_adapter_uses_source_origin_for_relative_listing_urls() -> None:
    result = await IndeedAdapter().extract(
        "https://ca.indeed.com/jobs?q=engineer",
        """
        <html>
          <body>
            <div class="job_seen_beacon">
              <h2><a href="/viewjob?jk=123"><span>Data Engineer</span></a></h2>
              <div data-testid="company-name">Data Corp</div>
            </div>
          </body>
        </html>
        """,
        "job_listing",
    )

    assert result.records[0]["apply_url"] == "https://ca.indeed.com/viewjob?jk=123"


def test_extract_job_sections_stops_collecting_at_strong_headings() -> None:
    sections = extract_job_sections(
        """
        <div>
          <strong>Benefits</strong>
          <p>Remote-first.</p>
          <strong>Skills</strong>
          <p>Python.</p>
        </div>
        """
    )

    assert sections["benefits"] == "Remote-first."
    assert sections["skills"] == "Python."


@pytest.mark.asyncio
async def test_linkedin_adapter_preserves_css_detail_output() -> None:
    result = await LinkedInAdapter().extract(
        "https://www.linkedin.com/jobs/view/123",
        """
        <html>
          <body>
            <h1 class="top-card-layout__title">Senior Data Engineer</h1>
            <div class="top-card-layout__company-name">Data Corp</div>
            <div class="top-card-layout__bullet">Bengaluru</div>
            <div class="description__job-criteria-item">
              <h3 class="description__job-criteria-subheader">Employment type</h3>
              <span class="description__job-criteria-text">Full-time</span>
            </div>
            <div class="description__text">Build deterministic pipelines.</div>
          </body>
        </html>
        """,
        "job_detail",
    )

    assert result.records == [
        {
            "title": "Senior Data Engineer",
            "company": "Data Corp",
            "location": "Bengaluru",
            "job_type": "Full-time",
            "description": "Build deterministic pipelines.",
            "apply_url": "https://www.linkedin.com/jobs/view/123",
            "url": "https://www.linkedin.com/jobs/view/123",
        }
    ]


@pytest.mark.asyncio
async def test_adp_adapter_preserves_css_listing_output() -> None:
    result = await ADPAdapter().extract(
        "https://example.wd5.myworkforcenow.com/recruitment/recruitment.html",
        """
        <html>
          <body>
            <div class="current-openings-item" id="job_123456">
              <a id="lblTitle_123456">Senior Data Engineer</a>
              <div class="current-opening-location-item"><span>Bengaluru</span></div>
              <div class="current-opening-post-date">2 days ago</div>
            </div>
          </body>
        </html>
        """,
        "job_listing",
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record["title"] == "Senior Data Engineer"
    assert record["job_id"] == "123456"
    assert record["location"] == "Bengaluru"
    assert record["posted_date"] == "2 days ago"
    assert record["apply_url"].endswith("jobId=123456#123456")
