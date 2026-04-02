# Tests for listing page extraction.
from __future__ import annotations

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
