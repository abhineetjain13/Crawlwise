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
