# Tests for the extraction service.
from __future__ import annotations

from unittest.mock import patch

from app.services.discover.service import DiscoveryManifest
from app.services.extract.service import extract_candidates


def _manifest(**kwargs) -> DiscoveryManifest:
    return DiscoveryManifest(**kwargs)


def test_extract_from_json_ld():
    html = "<html><body><h1>Fallback Title</h1></body></html>"
    manifest = _manifest(json_ld=[{"title": "JSON-LD Title", "price": "19.99"}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, trace = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    # JSON-LD should be present in candidates
    json_ld_sources = [c for c in candidates["title"] if c["source"] == "json_ld"]
    assert len(json_ld_sources) >= 1
    assert json_ld_sources[0]["value"] == "JSON-LD Title"


def test_extract_from_microdata():
    html = """
    <html><body>
    <div itemscope itemtype="http://schema.org/Product">
        <span itemprop="name">Micro Title</span>
    </div>
    </body></html>
    """
    manifest = _manifest(microdata=[{"name": "Micro Title", "price": "29.99"}])
    # "name" is not a canonical field but "price" is
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "price" in candidates
    micro_sources = [c for c in candidates["price"] if c["source"] == "microdata"]
    assert len(micro_sources) >= 1


def test_extract_from_adapter_data():
    html = "<html><body>test</body></html>"
    manifest = _manifest(adapter_data=[{"title": "Adapter Title", "price": "9.99", "brand": "TestBrand"}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    adapter_sources = [c for c in candidates["title"] if c["source"] == "adapter"]
    assert len(adapter_sources) >= 1
    assert adapter_sources[0]["confidence"] == 0.95


def test_extract_dom_patterns():
    html = """
    <html><body>
    <h1>DOM Title</h1>
    <span itemprop="price" content="49.99">$49.99</span>
    <meta name="description" content="A nice product">
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    assert any(c["source"] == "dom" for c in candidates["title"])
    assert "description" in candidates
    assert candidates["description"][0]["value"] == "A nice product"


def test_extract_additional_fields():
    html = """
    <html><body>
    <h1>Test</h1>
    </body></html>
    """
    manifest = _manifest(json_ld=[{"custom_field": "custom_value"}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            ["custom_field"],
        )
    assert "custom_field" in candidates
    assert candidates["custom_field"][0]["value"] == "custom_value"


def test_extract_network_payloads():
    html = "<html><body>test</body></html>"
    manifest = _manifest(network_payloads=[
        {"url": "https://api.example.com", "body": {"product": {"title": "API Title"}}}
    ])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    net_sources = [c for c in candidates["title"] if c["source"] == "network_intercept"]
    assert len(net_sources) >= 1


def test_extract_priority_order():
    """Adapter data should appear before JSON-LD in candidate list."""
    html = "<html><body><h1>DOM</h1></body></html>"
    manifest = _manifest(
        adapter_data=[{"title": "Adapter"}],
        json_ld=[{"title": "JSON-LD"}],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    sources = [c["source"] for c in candidates["title"]]
    # adapter should come before json_ld
    assert sources.index("adapter") < sources.index("json_ld")


def test_extract_respects_xpath_contract():
    html = "<html><body><h1>XPath Title</h1></body></html>"
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
            [{"field_name": "title", "xpath": "//h1/text()", "regex": ""}],
        )
    assert candidates["title"][0]["source"] == "contract_xpath"
    assert candidates["title"][0]["value"] == "XPath Title"


def test_extract_respects_regex_contract_for_additional_field():
    html = "<html><body>sku: ABC-123</body></html>"
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            ["sku_code"],
            [{"field_name": "sku_code", "xpath": "", "regex": r"sku:\s*([A-Z0-9-]+)"}],
        )
    assert candidates["sku_code"][0]["source"] == "contract_regex"
    assert candidates["sku_code"][0]["value"] == "ABC-123"
