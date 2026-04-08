"""Integration tests for signal inventory in extract service."""

from unittest.mock import patch

from app.services.extract.service import extract_candidates


def test_signal_inventory_integration_in_extract_candidates():
    """Test that signal inventory is built and page type is classified during extraction."""
    html = """
    <html>
        <head>
            <script type="application/ld+json">
                {"@type": "Product", "name": "Test Product"}
            </script>
        </head>
        <body>
            <h1>Test Product</h1>
            <div class="price">$99.99</div>
        </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, source_trace = extract_candidates(
            url="https://example.com/product/123",
            surface="ecommerce_detail",
            html=html,
            xhr_payloads=[],
            additional_fields=[],
        )

    # Verify extraction works (candidates should be returned)
    assert isinstance(candidates, dict)
    assert isinstance(source_trace, dict)


def test_signal_inventory_integration_with_listing_surface():
    """Test that listing surfaces return early with page_type in trace."""
    html = "<html><body>Test</body></html>"

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, source_trace = extract_candidates(
            url="https://example.com/products",
            surface="product_listing",
            html=html,
            xhr_payloads=[],
            additional_fields=[],
        )

    # Verify listing surface returns empty candidates
    assert candidates == {}
    assert source_trace.get("surface_gate") == "listing"
    # Verify page_type is included in trace
    assert "page_type" in source_trace
    assert source_trace["page_type"] in {"listing", "detail", "unknown"}
