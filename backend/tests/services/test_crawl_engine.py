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

    async def fake_browser(url: str, timeout_seconds: float):
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

    async def unexpected_browser(url: str, timeout_seconds: float):
        raise AssertionError(f"browser fallback should not run for {url} {timeout_seconds}")

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

    async def fake_browser(url: str, timeout_seconds: float):
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
    assert "widget-2.jpg" in record["additional_images"]
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
    assert record["additional_images"] == "https://example.com/images/trail-runner-2.jpg"
