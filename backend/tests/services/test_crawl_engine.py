from __future__ import annotations

import pytest

from app.services import crawl_fetch_runtime
from app.services.extraction_runtime import extract_records


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


def test_extract_records_prefers_rendered_listing_cards_over_thin_structured_records() -> None:
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
            "rendered_listing_cards": [
                {
                    "title": "Widget Prime",
                    "url": "https://example.com/products/widget-prime",
                    "price": "$19.99",
                    "image_url": "https://example.com/images/widget-prime.jpg",
                    "brand": "Acme",
                },
                {
                    "title": "Widget Pro",
                    "url": "https://example.com/products/widget-pro",
                    "price": "$29.99",
                    "image_url": "https://example.com/images/widget-pro.jpg",
                    "brand": "Acme",
                },
            ]
        },
    )

    assert len(rows) == 2
    assert rows[0]["_source"] == "rendered_listing"
    assert rows[0]["price"] == "19.99"
    assert rows[0]["image_url"] == "https://example.com/images/widget-prime.jpg"


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
        raise AssertionError(f"http fallback should not run for {url} {timeout_seconds}")

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
        raise AssertionError(f"browser fallback should not run for {url} {timeout_seconds} {kwargs}")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", unexpected_browser)

    result = await crawl_fetch_runtime.fetch_page("https://example.com/products/hatch-jean")

    assert result.method == "curl_cffi"


@pytest.mark.asyncio
async def test_fetch_page_uses_browser_first_for_requires_browser_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    async def unexpected_curl(url: str, timeout_seconds: float):
        raise AssertionError(f"curl fetch should not run for browser-first platform {url} {timeout_seconds}")

    async def unexpected_http(url: str, timeout_seconds: float):
        raise AssertionError(f"http fallback should not run for browser-first platform {url} {timeout_seconds}")

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

    result = await crawl_fetch_runtime.fetch_page("https://workforcenow.adp.com/recruitment/recruitment.html?jobId=12345")

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
            "barcode": "1234567890",
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
    assert record["barcode"] == "1234567890"
    assert record["product_type"] == "Gadget"
    assert record["category"] == "Widgets"
    assert record["image_url"] == "https://example.com/images/widget-1.jpg"
    assert any("widget-2.jpg" in value for value in record["additional_images"])
    assert record["rating"] == "4.7"
    assert record["review_count"] == 128
    assert record["features"] == "Lightweight body Long battery life"
    assert record["materials"] == "Cotton blend"
    assert record["care"] == "Machine wash"
    assert record["handle"] == "widget-prime"
    assert record["available_sizes"] == "S, M, L"
    assert record["variant_axes"] == {"size": ["S", "M", "L"]}
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
        requested_fields=["title", "price", "image_url", "description", "category", "brand"],
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
    assert record["apply_url"] == "https://example.com/jobs/senior-data-engineer?jobId=42"
    assert record["source_url"] == "https://example.com/jobs/senior-data-engineer?jobId=42"


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
    assert record["apply_url"] == "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
    assert "Lead and mentor engineers." in record["responsibilities"]
    assert "5+ years of engineering experience." in record["qualifications"]
    assert "Remote-first and health cover." in record["benefits"]
    assert record["_source"] == "js_state"


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
    assert record["variant_axes"] == {"color": ["Black"], "size": ["One size"]}
    assert record["selected_variant"]["sku"] == "LWBA04310011UNI"
    assert record["description"] == "Soft grained leather bag adorned with a chain and rhinestone wing."
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
    assert rows[0]["source_url"] == "https://example.com/collections/widgets?sort=featured"


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
    assert record["title"] == "Vitamagic Pro 192L 3 Star Radiant Steel Auto Defrost Single Door Refrigerator - Radiant Steel-Y"
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


def test_extract_detail_allows_safe_early_exit_before_dom_when_structured_record_is_complete() -> None:
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
    assert record["_extraction_tiers"]["early_exit"] == "structured_data"
    assert record["_extraction_tiers"]["current"] == "structured_data"


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
    assert record["original_price"] == "1565"


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
    assert record["additional_images"] == ["https://example.com/images/trail-runner-2.jpg"]
