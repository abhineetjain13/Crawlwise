# Tests for the discovery service.
from __future__ import annotations

from app.services.discover.service import DiscoveryManifest, discover_sources


def test_discover_json_ld():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "price": "19.99"}
    </script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest.json_ld) == 1
    assert manifest.json_ld[0]["name"] == "Widget"


def test_discover_json_ld_array():
    html = """
    <html><body>
    <script type="application/ld+json">
    [{"@type": "Product", "name": "A"}, {"@type": "Product", "name": "B"}]
    </script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest.json_ld) == 2


def test_discover_json_ld_invalid_json():
    html = """
    <html><body>
    <script type="application/ld+json">not valid json{</script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert manifest.json_ld == []


def test_discover_next_data():
    html = """
    <html><body>
    <script id="__NEXT_DATA__">{"props":{"pageProps":{"product":{"name":"NextWidget"}}}}</script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert manifest.next_data is not None
    assert manifest.next_data["props"]["pageProps"]["product"]["name"] == "NextWidget"


def test_discover_next_data_missing():
    html = """
    <html><body>
    <script>window.__INITIAL_STATE__ = {"props":{"pageProps":{"product":{"name":"HydratedWidget"}}}}</script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert manifest.next_data is not None
    assert len(manifest._hydrated_states) == 1
    assert manifest._hydrated_states[0]["props"]["pageProps"]["product"]["name"] == "HydratedWidget"
    assert manifest.next_data["_hydrated_states"] == manifest._hydrated_states


def test_discover_hydrated_assignment_preserves_semicolon_in_string():
    html = """
    <html><body>
    <script>
    window.__INITIAL_STATE__ = {"props":{"message":"Hydrated;Widget","items":[1,2,3]}};
    window.__OTHER_STATE__ = {"ok": true};
    </script>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest._hydrated_states) == 1
    assert manifest._hydrated_states[0]["props"]["message"] == "Hydrated;Widget"


def test_discover_microdata():
    html = """
    <html><body>
    <div itemscope itemtype="http://schema.org/Product">
        <span itemprop="name">Micro Product</span>
        <span itemprop="price" content="29.99">$29.99</span>
    </div>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest.microdata) >= 1
    item = manifest.microdata[0]
    assert item["name"] == "Micro Product"
    assert item["price"] == "29.99"


def test_discover_rdfa():
    html = """
    <html><body>
    <div typeof="Product">
        <span property="schema:name">RDFa Product</span>
        <span property="schema:price" content="39.99">$39.99</span>
    </div>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest.microdata) >= 1
    item = manifest.microdata[0]
    assert item["name"] == "RDFa Product"
    assert item["price"] == "39.99"


def test_discover_tables():
    html = """
    <html><body>
    <table>
        <tr><th>Name</th><th>Price</th></tr>
        <tr><td>Widget A</td><td>$10</td></tr>
        <tr><td>Widget B</td><td>$20</td></tr>
    </table>
    </body></html>
    """
    manifest = discover_sources(html)
    assert len(manifest.tables) == 1
    assert len(manifest.tables[0]) == 3  # header + 2 data rows


def test_discover_adapter_data_passthrough():
    html = "<html><body>test</body></html>"
    adapter_records = [{"title": "From Adapter", "price": "9.99"}]
    manifest = discover_sources(html, adapter_records=adapter_records)
    assert manifest.adapter_data == adapter_records


def test_discover_network_payloads_passthrough():
    html = "<html><body>test</body></html>"
    payloads = [{"url": "https://api.example.com/data", "body": {"items": []}}]
    manifest = discover_sources(html, network_payloads=payloads)
    assert manifest.network_payloads == payloads


def test_discover_empty_html():
    manifest = discover_sources("")
    assert manifest.json_ld == []
    assert manifest.next_data is None
    assert manifest.microdata == []
    assert manifest.tables == []
