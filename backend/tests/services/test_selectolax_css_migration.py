from __future__ import annotations

from pathlib import Path

import pytest

from app.services.adapters.adp import ADPAdapter
from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.detail_extractor import build_detail_record
from app.services.extraction_html_helpers import extract_job_sections
from app.services.listing_extractor import extract_listing_records
from app.services.xpath_service import extract_selector_value


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
    assert record["rating"] == "4.8"
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
    assert rows[0]["rating"] == "4.7"
    assert rows[0]["review_count"] == 128


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
            "image_url": "https://www.ulta.com/images/rose-lens.jpg",
            "url": "https://www.ulta.com/p/connect-in-colour-eyeshadow-palette-rose-lens?sku=2640287",
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
    html = Path(__file__).resolve().parents[2].joinpath(artifact_path).read_text(
        encoding="utf-8",
        errors="ignore",
    )

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
