# Tests for listing extractor URL normalization.
from __future__ import annotations

from app.services.extract.listing_extractor import extract_listing_records


def test_extract_listing_records_resolves_relative_urls():
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
    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/collections/chairs",
    )
    assert records[0]["url"] == "https://example.com/product/1"
    assert records[1]["url"] == "https://example.com/product/2"


def test_extract_listing_records_prefers_detail_links_over_first_card_anchor():
    html = """
    <html><body>
    <div class="product-card">
        <a href="/collections/chairs?color=oak">Oak filter</a>
        <h3><a href="/product/oak-chair">Oak Chair</a></h3>
        <span class="price">$10.00</span>
    </div>
    <div class="product-card">
        <a href="#swatch-blue">Blue swatch</a>
        <h3><a href="/product/blue-chair">Blue Chair</a></h3>
        <span class="price">$20.00</span>
    </div>
    </body></html>
    """
    records = extract_listing_records(
        html,
        "ecommerce_listing",
        set(),
        page_url="https://example.com/collections/chairs",
    )
    assert records[0]["url"] == "https://example.com/product/oak-chair"
    assert records[1]["url"] == "https://example.com/product/blue-chair"


def test_extract_listing_records_uses_usajobs_card_selector():
    # USAJobs search pages render job cards as direct #search-results children with
    # these utility classes, which keeps pagination/filter chrome out of the card set.
    html = """
    <html><body>
      <div id="search-results">
        <div class="border border-gray-lighter bg-white p-4">
          <div class="flex justify-between items-start">
            <h2><a href="/job/863502700">Software Engineer II</a></h2>
          </div>
          <div>
            <p><strong>House of Representatives</strong></p>
            <p>Legislative Branch</p>
            <p>Washington, District of Columbia</p>
          </div>
        </div>
        <div class="border border-gray-lighter bg-white p-4">
          <div class="flex justify-between items-start">
            <h2><a href="/job/863855200">Computer Engineer</a></h2>
          </div>
          <div>
            <p><strong>Air Force Materiel Command</strong></p>
            <p>Department of the Air Force</p>
            <p>Multiple Locations</p>
          </div>
        </div>
      </div>
    </body></html>
    """
    records = extract_listing_records(
        html,
        "job_listing",
        set(),
        page_url="https://www.usajobs.gov/search/results/?k=software%20engineer&p=1",
    )
    assert len(records) == 2
    assert records[0]["url"] == "https://www.usajobs.gov/job/863502700"
    assert records[1]["url"] == "https://www.usajobs.gov/job/863855200"
