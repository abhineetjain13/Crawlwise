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


def test_extract_title_ignores_breadcrumb_home_when_product_name_exists():
    html = "<html><body><h1>Sequential Prophet Rev2 16-voice Analog Synthesizer</h1></body></html>"
    manifest = _manifest(json_ld=[
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home"},
            ],
        },
        {
            "@type": "Product",
            "name": "Sequential Prophet Rev2 16-voice Analog Synthesizer",
        },
    ])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["title"][0]["value"] == "Sequential Prophet Rev2 16-voice Analog Synthesizer"


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
    assert adapter_sources[0]["value"] == "Adapter Title"


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


def test_extract_dom_patterns_prioritize_h1_before_document_title():
    html = """
    <html>
      <head>
        <title>Chrome</title>
        <meta property="og:title" content="OG Title">
      </head>
      <body>
        <h1>Correct Product Title</h1>
      </body>
    </html>
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
    dom_title = next((candidate for candidate in candidates["title"] if candidate["source"] == "dom"), None)
    assert dom_title is not None, "Expected a DOM title candidate"
    assert dom_title["value"] == "Correct Product Title"


def test_extract_does_not_use_broad_section_for_specifications_dom_fallback():
    html = """
    <html><body>
      <section>
        <div>Related Products</div>
        <div>Widget A $10 Details</div>
        <div>Widget B $20 Details</div>
      </section>
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
    assert "specifications" not in candidates


def test_extract_rejects_hidden_state_brand_for_strict_brand_field():
    html = "<html><body><span itemprop='brand'>Alpha Wire</span></body></html>"
    manifest = _manifest(_hydrated_states=[{"browser": {"manufacturer": "Apple"}}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "brand" in candidates
    assert candidates["brand"][0]["value"] == "Alpha Wire"
    assert all(candidate["value"] != "Apple" for candidate in candidates["brand"])


def test_extract_rejects_generic_hidden_category_value():
    html = "<html><body><div itemprop='category'>Audio Cables</div></body></html>"
    manifest = _manifest(_hydrated_states=[{"page": {"type": "detail-page"}}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "category" in candidates
    assert candidates["category"][0]["value"] == "Audio Cables"


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


def test_extract_semantic_requested_field_responsibilities():
    html = """
    <html><body>
    <h2>Responsibilities</h2>
    <p>Build the product experience.</p>
    <p>Ship improvements weekly.</p>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job",
            "job_detail",
            html,
            manifest,
            ["responsibilities"],
        )
    assert "responsibilities" in candidates
    assert candidates["responsibilities"][0]["source"] == "semantic_section"
    assert "Build the product experience." in candidates["responsibilities"][0]["value"]


def test_extract_semantic_requested_field_from_accordion():
    html = """
    <html><body>
    <button aria-controls="resp-panel">Responsibilities</button>
    <div id="resp-panel">
      <p>Build internal tools.</p>
      <p>Support platform migrations.</p>
    </div>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job",
            "job_detail",
            html,
            manifest,
            ["responsibilities"],
        )
    assert "responsibilities" in candidates
    assert "Build internal tools." in candidates["responsibilities"][0]["value"]


def test_extract_hydrated_state_source():
    html = "<html><body><h1>Fallback</h1></body></html>"
    manifest = _manifest(_hydrated_states=[{"props": {"pageProps": {"product": {"title": "Hydrated Title"}}}}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    assert any(item["source"] == "hydrated_state" for item in candidates["title"])
    assert candidates["title"][0]["value"] == "Hydrated Title"


def test_extract_embedded_json_source():
    html = "<html><body><h1>Fallback</h1></body></html>"
    manifest = _manifest(embedded_json=[{"product": {"title": "Embedded Title", "brand": "EmbedCo"}}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "title" in candidates
    embedded_title = next((item for item in candidates["title"] if item["source"] == "embedded_json"), None)
    assert embedded_title is not None, "Expected an embedded_json title candidate"
    assert embedded_title["value"] == "Embedded Title"


def test_extract_semantic_specifications_from_inline_list_pairs():
    html = """
    <html><body>
    <h2>Tech Specs</h2>
    <ul>
      <li>Number of Keys: 61</li>
      <li>Polyphony: 16 Voice</li>
    </ul>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, trace = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            ["number_of_keys", "polyphony"],
        )
    assert candidates["number_of_keys"][0]["value"] == "61"
    assert candidates["polyphony"][0]["value"] == "16 Voice"
    semantic = trace["semantic"]
    assert semantic["specifications"]["number_of_keys"] == "61"
    assert semantic["specifications"]["polyphony"] == "16 Voice"


def test_extract_semantic_specifications_filters_obvious_noise_rows():
    html = """
    <html><body>
    <table>
      <tr><th>Qty</th><td>Discount</td></tr>
      <tr><th>Play Video</th><td>Watch the demo</td></tr>
      <tr><th>Product Weight</th><td>2.2g</td></tr>
    </table>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        _, trace = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    semantic = trace["semantic"]
    assert "qty" not in semantic["specifications"]
    assert "play_video" not in semantic["specifications"]
    assert semantic["specifications"]["product_weight"] == "2.2g"


def test_extract_specifications_from_structured_specification_groups():
    html = """
    <html><body>
      <div id="specifications">Check the details Product summary General Specifications Technical Specifications</div>
    </body></html>
    """
    manifest = _manifest(next_data={
        "props": {
            "pageProps": {
                "specificationGroups": [
                    {
                        "label": "General Specifications",
                        "specifications": [
                            {"title": "Prop 65", "content": "CA"},
                        ],
                    },
                    {
                        "label": "Technical Specifications",
                        "specifications": [
                            {"title": "Depth", "content": "9-21/32 in"},
                            {"title": "Height", "content": "15 in"},
                        ],
                    },
                ],
            },
        },
    })
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "specifications" in candidates
    assert candidates["specifications"][0]["source"] == "next_data"
    assert "Technical Specifications: Depth: 9-21/32 in; Height: 15 in" in candidates["specifications"][0]["value"]
    assert candidates["specifications"][0]["value"].startswith("General Specifications: Prop 65: CA")


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


def test_extract_network_payload_coerces_nested_dict_to_scalar():
    html = "<html><body>test</body></html>"
    manifest = _manifest(network_payloads=[
        {
            "url": "https://api.example.com",
            "body": {"product": {"dimensions": {"name": "size", "sentence": "Runs true to size"}}},
        }
    ])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            ["dimensions"],
        )
    assert "dimensions" in candidates
    assert candidates["dimensions"][0]["value"] == "Runs true to size"


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


def test_extract_prefers_saved_xpath_selector_defaults():
    html = "<html><body><h1>Saved XPath Title</h1></body></html>"
    manifest = _manifest()
    with patch(
        "app.services.extract.service.get_selector_defaults",
        return_value=[{"xpath": "//h1/text()", "status": "validated"}],
    ):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    selector_rows = [row for row in candidates["title"] if row["source"] == "selector"]
    assert selector_rows
    assert selector_rows[0]["value"] == "Saved XPath Title"
    assert selector_rows[0]["xpath"] == "//h1/text()"
