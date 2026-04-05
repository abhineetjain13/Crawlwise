# Tests for the extraction service.
from __future__ import annotations

from unittest.mock import patch

from app.services.discover.service import DiscoveryManifest
from app.services.discover.service import discover_sources
from app.services.extract.service import _extract_image_urls, _resolve_candidate_url, extract_candidates


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


def test_extract_title_drops_generic_breadcrumb_candidates_and_keeps_product_name():
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
    values = [candidate["value"] for candidate in candidates["title"]]
    assert "Sequential Prophet Rev2 16-voice Analog Synthesizer" in values
    assert "Home" not in values
    assert 1 not in values


def test_extract_prefers_specific_product_title_over_website_and_nav_titles():
    html = """
    <html>
      <head>
        <meta property="og:title" content="39''H Metal Wavy Wall Mirror" />
      </head>
      <body></body>
    </html>
    """
    manifest = _manifest(
        json_ld=[{"@type": "WebSite", "name": "Wayfair"}],
        microdata=[{"name": "Department Navigation"}],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["title"][0]["source"] == "dom"
    assert candidates["title"][0]["value"] == "39''H Metal Wavy Wall Mirror"


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


def test_extract_recovers_nested_offer_fields_from_json_ld_with_trailing_semicolon():
    html = """
    <html><body>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Product","name":"Lib Tech Skate Banana BTX Snowboard 2026","brand":{"name":"Lib Tech"},"offers":[{"price":405.99,"priceCurrency":"USD","sku":"EB-268000-1001","availability":"InStock"}]};
      </script>
    </body></html>
    """
    manifest = discover_sources(html)
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.evo.com/snowboards/lib-tech-skate-banana-btx-snowboard",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["brand"][0]["value"] == "Lib Tech"
    assert candidates["price"][0]["value"] == 405.99
    assert candidates["currency"][0]["value"] == "USD"
    assert candidates["sku"][0]["value"] == "EB-268000-1001"
    assert candidates["availability"][0]["value"] == "InStock"


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


def test_extract_preserves_hidden_state_brand_candidates_without_dropping_dom_brand():
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
    brand_values = [candidate["value"] for candidate in candidates["brand"]]
    assert "Alpha Wire" in brand_values
    assert "Apple" in brand_values


def test_extract_drops_generic_hidden_category_candidates_but_preserves_dom_category():
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
    category_values = [candidate["value"] for candidate in candidates["category"]]
    assert "Audio Cables" in category_values
    assert "detail-page" not in category_values


def test_extract_filters_non_image_additional_images_and_resolves_relative_image_paths():
    html = "<html><body></body></html>"
    manifest = _manifest(
        _hydrated_states=[{
            "media": "Photo is meant to be representative of packaging you will receive if ordered."
        }],
        json_ld=[{
            "@type": "Product",
            "image": "/deepweb/assets/example/product/main-image.jpg",
        }],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.sigmaaldrich.com/IN/en/product/avanti/793074c",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["image_url"][0]["value"] == "https://www.sigmaaldrich.com/deepweb/assets/example/product/main-image.jpg"
    assert candidates["additional_images"][0]["value"] == "https://www.sigmaaldrich.com/deepweb/assets/example/product/main-image.jpg"


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


def test_extract_requested_unknown_image_field_uses_pattern_cleanup():
    html = "<html><body></body></html>"
    manifest = _manifest(embedded_json=[{"hero_image_url": "/media/catalog/product/main.jpg"}])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product/123",
            "ecommerce_detail",
            html,
            manifest,
            ["hero_image_url"],
        )
    assert "hero_image_url" in candidates
    assert candidates["hero_image_url"][0]["value"] == "https://example.com/media/catalog/product/main.jpg"


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


def test_extract_semantic_specifications_are_exposed_as_candidate_rows_without_requesting_them():
    html = """
    <html><body>
    <ul>
      <li>Wire Gauge: 26 AWG</li>
      <li>Impedance: 50 Ohms</li>
    </ul>
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
    assert "wire_gauge" in candidates
    assert candidates["wire_gauge"][0]["value"] == "26 AWG"
    assert "impedance" in candidates
    assert candidates["impedance"][0]["value"] == "50 Ohms"
    assert "specifications" in candidates
    assert "wire_gauge: 26 AWG" in candidates["specifications"][0]["value"]


def test_extract_semantic_specifications_allow_additional_colons_in_value():
    html = """
    <html><body>
    <ul>
      <li>Office Hours: 09:00 to 17:30 UTC+05:30</li>
    </ul>
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
    assert semantic["specifications"]["office_hours"] == "09:00 to 17:30 UTC+05:30"


def test_extract_semantic_specifications_filters_obvious_noise_rows():
    html = """
    <html><body>
    <table>
      <tr><th>Qty</th><td>Discount</td></tr>
      <tr><th>Play Video</th><td>Watch the demo</td></tr>
      <tr><th>Total</th><td>$9.99</td></tr>
      <tr><th>Pack 1</th><td>1.00 kg</td></tr>
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
    assert "total" not in semantic["specifications"]
    assert "pack_1" not in semantic["specifications"]
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
    assert "prop_65: CA" in candidates["specifications"][0]["value"]
    assert "depth: 9-21/32 in" in candidates["specifications"][0]["value"]
    assert "height: 15 in" in candidates["specifications"][0]["value"]
    assert "depth" in candidates
    assert candidates["depth"][0]["value"] == "9-21/32 in"
    assert "height" in candidates
    assert candidates["height"][0]["value"] == "15 in"


def test_extract_semantic_tables_preserve_grouping_links_and_visible_placeholders():
    html = """
    <html><body>
      <h2>Documents & Media</h2>
      <table>
        <tr><th>Resource Type</th><th>Link</th></tr>
        <tr><td>Datasheets</td><td><a href="https://example.com/c1156.pdf">C1156</a></td></tr>
      </table>
      <h2>Environmental & Export Classifications</h2>
      <table>
        <tr><th>Attribute</th><th>Description</th></tr>
        <tr><td>Operating Temperature</td><td>-</td></tr>
        <tr><td>ECCN</td><td>EAR99</td></tr>
      </table>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, trace = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    semantic = trace["semantic"]
    assert semantic["table_groups"][0]["title"] == "Documents & Media"
    assert semantic["table_groups"][0]["rows"][0]["href"] == "https://example.com/c1156.pdf"
    assert semantic["table_groups"][1]["title"] == "Environmental & Export Classifications"
    assert semantic["specifications"]["operating_temperature"] == "-"
    # Placeholder value "-" is preserved in semantic trace but filtered from
    # intelligence candidates (zero quality score for dynamic fields).
    assert "operating_temperature" not in candidates


def test_extract_filters_schema_type_category_noise_and_keeps_real_category():
    html = "<html><body><h1>Widget</h1></body></html>"
    manifest = _manifest(json_ld=[
        {"@type": "ProductGroup", "category": "ProductGroup"},
        {"@type": "Review", "category": "Review"},
        {"category": "Men > Shirts & Tops"},
    ])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert "category" in candidates
    assert [row["value"] for row in candidates["category"]] == ["Men > Shirts & Tops"]


def test_extract_filters_noisy_dynamic_semantic_field_names():
    html = """
    <html><body>
      <h2>Specifications</h2>
      <table>
        <tr><td>5.0 Recommended</td><td>100% 5 Ratings</td></tr>
        <tr><td>Compression</td><td>Ultra-tight, second-skin fit.</td></tr>
        <tr><td>Featured New Arrivals Now Trending</td><td>Capris</td></tr>
        <tr><td>HeatGear Elite Men's Compression Mock Short Sleeve 50 Price</td><td>$50</td></tr>
      </table>
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
    assert "compression" in candidates
    assert "5.0_recommended" not in candidates
    assert "featured_new_arrivals_now_trending" not in candidates
    assert "heatgear_elite_men_s_compression_mock_short_sleeve_50_price" not in candidates


def test_extract_prefers_real_title_and_cleans_size_color_option_text():
    html = """
    <html><body>
      <div class="summary"><h1 class="product_title">Chaz Kangeroo Hoodie</h1></div>
      <table>
        <tr><td>Size</td><td>Choose an option XS S M L XL</td></tr>
        <tr><td>Color</td><td>Choose an option Black Gray Orange Clear</td></tr>
      </table>
    </body></html>
    """
    manifest = _manifest(
        embedded_json=[{"title": "mh01- .jpg", "size": "(max-width: 416px) 100vw, 416px"}],
        json_ld=[{"title": "Chaz Kangeroo Hoodie"}],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["title"][0]["value"] == "Chaz Kangeroo Hoodie"
    assert candidates["size"][0]["value"] == "XS, S, M, L, XL"
    assert candidates["color"][0]["value"] == "Black Gray Orange"


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


def test_extract_preserves_all_values_found_at_different_depths():
    html = "<html><body>test</body></html>"
    manifest = _manifest(json_ld=[{
        "title": "Top Level Title",
        "offers": {
            "title": "Offer Title",
            "details": [{"title": "Nested Offer Title"}],
        },
    }])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    json_ld_values = [row["value"] for row in candidates["title"] if row["source"] == "json_ld"]
    assert json_ld_values == ["Top Level Title", "Offer Title", "Nested Offer Title"]


def test_extract_preserves_all_matches_from_multiple_hydrated_states_and_embedded_json_payloads():
    html = "<html><body>test</body></html>"
    manifest = _manifest(
        _hydrated_states=[
            {"product": {"title": "Hydrated Title A"}},
            {"page": {"title": "Hydrated Title B"}},
        ],
        embedded_json=[
            {"product": {"title": "Embedded Title A"}},
            {"product": {"title": "Embedded Title B"}},
        ],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    hydrated_values = [row["value"] for row in candidates["title"] if row["source"] == "hydrated_state"]
    embedded_values = [row["value"] for row in candidates["title"] if row["source"] == "embedded_json"]
    assert hydrated_values == ["Hydrated Title A", "Hydrated Title B"]
    assert embedded_values == ["Embedded Title A", "Embedded Title B"]


def test_extract_dedupes_exact_duplicate_rows_but_preserves_distinct_same_source_values():
    html = "<html><body>test</body></html>"
    manifest = _manifest(json_ld=[
        {"title": "Repeated Title"},
        {"title": "Repeated Title"},
        {"title": "Different Title"},
    ])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    json_ld_values = [row["value"] for row in candidates["title"] if row["source"] == "json_ld"]
    assert json_ld_values == ["Repeated Title", "Different Title"]


def test_extract_dedupes_same_value_across_sources_and_preserves_supporting_sources():
    html = "<html><body>test</body></html>"
    manifest = _manifest(
        adapter_data=[{"title": "Shared Title"}],
        json_ld=[{"title": "Shared Title"}],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert len(candidates["title"]) == 1
    assert candidates["title"][0]["value"] == "Shared Title"
    assert candidates["title"][0]["source"] == "adapter, json_ld"
    assert candidates["title"][0]["sources"] == ["adapter", "json_ld"]


def test_extract_dedupes_case_only_variants_and_keeps_best_display_value():
    html = "<html><body></body></html>"
    manifest = _manifest(
        adapter_data=[{"brand": "Supelco"}],
        json_ld=[{"brand": "SUPELCO"}],
        _hydrated_states=[{"product": {"brand": "supelco"}}],
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert [row["value"] for row in candidates["brand"]] == ["Supelco"]
    assert candidates["brand"][0]["sources"] == ["adapter", "hydrated_state", "json_ld"]


def test_extract_sigma_product_detail_and_buy_box_candidates():
    html = """
    <html><body>
      <div class="buy-box">
        <h3>Select a Size</h3>
        <div>Pack Size</div>
        <div>100 ea</div>
        <div>SKU</div>
        <div>SU860101</div>
        <div>Availability</div>
        <div>Available to ship TODAY from Bangalore Non-Bonded Warehouse</div>
        <div>Price</div>
        <div>₹16,484.75</div>
      </div>
    </body></html>
    """
    manifest = _manifest(next_data={
        "props": {
            "pageProps": {
                "data": {
                    "getProductDetail": {
                        "name": "Magnetic Screw Cap for Headspace Vials, 18 mm thread",
                        "productNumber": "SU860101",
                        "productKey": "SU860101",
                        "description": "PTFE/silicone septum, pkg of 100 ea",
                        "brand": {"name": "Supelco"},
                        "synonyms": ["18 mm magnetic screw cap for vials"],
                        "images": [{"largeUrl": "/deepweb/assets/sigmaaldrich/product/images/a.jpg"}],
                        "attributes": [
                            {"label": "material", "values": ["PTFE/silicone"]},
                            {"label": "packaging", "values": ["pkg of 100 ea"]},
                            {"label": "O.D. × H", "values": ["18 mm × 11 mm"]},
                            {"label": "fitting", "values": ["thread for 18 mm"]},
                        ],
                    }
                }
            }
        }
    })
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.sigmaaldrich.com/IN/en/product/supelco/su860101",
            "ecommerce_detail",
            html,
            manifest,
            ["synonyms", "pack_size"],
        )
    assert candidates["brand"][0]["value"] == "Supelco"
    assert candidates["sku"][0]["value"] == "SU860101"
    assert candidates["synonyms"][0]["value"] == "18 mm magnetic screw cap for vials"
    assert candidates["size"][0]["value"] == "100 ea"
    assert candidates["pack_size"][0]["value"] == "100 ea"
    assert candidates["availability"][0]["value"] == "Available to ship TODAY from Bangalore Non-Bonded Warehouse"
    assert candidates["price"][0]["value"] == "₹16,484.75"
    assert candidates["currency"][0]["value"] == "INR"


def test_extract_returns_empty_candidates_for_listing_surfaces():
    candidates, trace = extract_candidates(
        "https://example.com/category",
        "ecommerce_listing",
        "<html></html>",
        _manifest(),
        [],
    )
    assert candidates == {}
    assert trace["surface_gate"] == "listing"


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
    assert "contract_xpath" in candidates["title"][0]["sources"]
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
    selector_rows = [row for row in candidates["title"] if "selector" in row.get("sources", [])]
    assert selector_rows
    assert selector_rows[0]["value"] == "Saved XPath Title"
    assert selector_rows[0]["xpath"] == "//h1/text()"


def test_resolve_candidate_url_joins_relative_path_against_base_url():
    assert (
        _resolve_candidate_url("products/shoe-123", "https://example.com/category")
        == "https://example.com/products/shoe-123"
    )


def test_extract_image_urls_keeps_cdn_images_with_query_strings():
    assert _extract_image_urls(
        "https://cdn.example.com/product.jpg?v=1234&width=800",
        base_url="https://example.com/product",
    ) == ["https://cdn.example.com/product.jpg?v=1234&width=800"]
