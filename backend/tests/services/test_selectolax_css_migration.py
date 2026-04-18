from __future__ import annotations

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
