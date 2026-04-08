# Tests for the extraction service.
from __future__ import annotations

import json
from unittest.mock import patch

from app.services.extract.service import (
    _dispatch_string_field_coercer,
    _extract_image_urls,
    _label_value_pattern,
    _normalize_html_rich_text,
    _normalize_color_candidate,
    _normalize_size_candidate,
    _resolve_candidate_url,
    _should_skip_jsonld_block,
    coerce_field_candidate_value,
    extract_candidates as _extract_candidates_impl,
)


def _manifest(**kwargs) -> dict:
    return kwargs


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    manifest: dict | None,
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
):
    sources = dict(manifest or {})
    page_sources = {
        "next_data": sources.get("next_data"),
        "hydrated_states": sources.get("_hydrated_states") or sources.get("hydrated_states") or [],
        "embedded_json": sources.get("embedded_json") or [],
        "open_graph": sources.get("open_graph") or {},
        "json_ld": sources.get("json_ld") or [],
        "microdata": sources.get("microdata") or [],
        "tables": sources.get("tables") or [],
        "datalayer": sources.get("datalayer") or {},
    }
    if any(page_sources.values()):
        with patch("app.services.extract.service.parse_page_sources", return_value=page_sources):
            return _extract_candidates_impl(
                url,
                surface,
                html,
                sources.get("network_payloads") or [],
                additional_fields,
                extraction_contract,
                resolved_fields,
                sources.get("adapter_data") or [],
            )
    return _extract_candidates_impl(
        url,
        surface,
        html,
        sources.get("network_payloads") or [],
        additional_fields,
        extraction_contract,
        resolved_fields,
        sources.get("adapter_data") or [],
    )


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
    manifest = _manifest()
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


def test_extract_prefers_hydrated_brand_before_dom_brand():
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
    assert candidates["brand"][0]["source"] == "hydrated_state"
    assert candidates["brand"][0]["value"] == "Apple"


def test_extract_label_value_fallback_uses_full_description_sources():
    html = "<html><head></head><body><h1>Widget</h1></body></html>"
    manifest = _manifest(open_graph={"description": "Brand: Acme Corp"})
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["brand"][0]["source"] == "text_pattern"
    assert candidates["brand"][0]["value"] == "Acme Corp"


def test_label_value_pattern_cache_reuses_compiled_regex_for_same_variant():
    _label_value_pattern.cache_clear()
    before = _label_value_pattern.cache_info()
    first = _label_value_pattern("Brand")
    second = _label_value_pattern("Brand")
    after = _label_value_pattern.cache_info()

    assert first is second
    assert after.hits == before.hits + 1
    assert after.misses == before.misses + 1


def test_extract_job_company_from_open_graph_site_name():
    html = "<html><body><h1>Supervisor Food and Beverage</h1></body></html>"
    manifest = _manifest(open_graph={"og:site_name": "Woodbine Entertainment"})
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://woodbine.com/corporate/job/?id=abc",
            "job_detail",
            html,
            manifest,
            ["company"],
        )
    assert candidates["company"][0]["source"] == "open_graph"
    assert candidates["company"][0]["value"] == "Woodbine Entertainment"


def test_extract_label_value_fallback_uses_salary_alias_labels():
    html = "<html><body><h1>Widget</h1></body></html>"
    manifest = _manifest(
        open_graph={
            "description": (
                "Salary range: The target hiring salary range for this position is "
                "$82,000 - $92,000."
            )
        }
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job",
            "job_detail",
            html,
            manifest,
            ["salary"],
        )
    assert candidates["salary"][0]["source"] == "text_pattern"
    assert "$82,000 - $92,000" in str(candidates["salary"][0]["value"])


def test_coerce_field_candidate_value_joins_description_lists():
    value = ["Paragraph one.", "Paragraph two.", "Final details."]

    coerced = coerce_field_candidate_value(
        "description",
        value,
        base_url="https://example.com/product",
    )

    assert coerced == "Paragraph one. Paragraph two. Final details."


def test_dispatch_string_field_coercer_prefers_image_collection_over_url_suffix_match():
    coerced = _dispatch_string_field_coercer(
        "product_images_url",
        "/img/a.jpg, /img/b.jpg",
        base_url="https://example.com/product/1",
    )
    assert (
        coerced
        == "https://example.com/img/a.jpg, https://example.com/img/b.jpg"
    )


def test_coerce_field_candidate_value_rejects_asset_font_urls_for_url_fields():
    assert (
        coerce_field_candidate_value(
            "url",
            "https://cdn.example.com/fonts/inter.woff2",
            base_url="https://example.com/product",
        )
        is None
    )
    assert _resolve_candidate_url("https://cdn.example.com/fonts/inter.woff2", "https://example.com") == ""


def test_resolve_candidate_url_strips_tracking_query_params():
    assert (
        _resolve_candidate_url(
            "https://example.com/product/widget?utm_source=newsletter&ref=home&id=9",
            "https://example.com",
        )
        == "https://example.com/product/widget?id=9"
    )


def test_resolve_candidate_url_preserves_fragment_and_non_tracking_ref_prefix_keys():
    assert (
        _resolve_candidate_url(
            "https://example.com/product/widget?referrer=home&ref=nav&id=9#details",
            "https://example.com",
        )
        == "https://example.com/product/widget?referrer=home&id=9#details"
    )


def test_extract_rejects_noise_title_and_placeholder_image_candidates():
    html = "<html><body></body></html>"
    manifest = _manifest(
        json_ld=[{
            "@type": "Product",
            "name": "Cart",
            "image": "https://example.com/assets/logo-placeholder.png",
        }]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert "title" not in candidates
    assert "image_url" not in candidates


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


def test_extract_product_detail_prefers_material_id_for_sku():
    html = "<html><body><h1>Widget</h1></body></html>"
    manifest = _manifest(
        next_data={
            "props": {
                "pageProps": {
                    "data": {
                        "getProductDetail": {
                            "name": "Widget",
                            "productNumber": "NUC101",
                            "productKey": "NUC101",
                            "materialIds": ["NUC101-1KT"],
                        }
                    }
                }
            }
        }
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.sigmaaldrich.com/IN/en/product/sigma/nuc101",
            "ecommerce_detail",
            html,
            manifest,
            ["sku"],
        )
    assert "sku" in candidates
    assert candidates["sku"][0]["value"] == "NUC101-1KT"
    assert candidates["sku"][0]["source"] == "product_detail"


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


def test_extract_semantic_requested_field_from_emphasized_paragraph_heading():
    html = """
    <html><body>
    <p><b><u>Key Responsibilities:</u></b></p>
    <ul>
      <li>Build the product experience.</li>
      <li>Ship improvements weekly.</li>
    </ul>
    <p><b><u>Skills:</u></b></p>
    <ul>
      <li>Strong stakeholder communication.</li>
    </ul>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job",
            "job_detail",
            html,
            manifest,
            ["responsibilities", "skills"],
        )
    assert "responsibilities" in candidates
    assert "Build the product experience." in candidates["responsibilities"][0]["value"]
    assert "Strong stakeholder communication." not in candidates["responsibilities"][0]["value"]
    assert "skills" in candidates
    assert "Strong stakeholder communication." in candidates["skills"][0]["value"]


def test_extract_semantic_requested_field_matches_prefixed_responsibilities_heading():
    html = """
    <html><body>
    <p><b><u>Some Key Responsibilities:</u></b></p>
    <ul>
      <li>Deliver high energy pre-shift meetings.</li>
      <li>Engage guests throughout the shift.</li>
    </ul>
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
    assert "Deliver high energy pre-shift meetings." in candidates["responsibilities"][0]["value"]
    assert "Engage guests throughout the shift." in candidates["responsibilities"][0]["value"]


def test_extract_job_qualifications_strip_html_from_json_ld():
    html = "<html><body><h1>Foreign Affairs Officer</h1></body></html>"
    manifest = _manifest(json_ld=[{
        "@type": "JobPosting",
        "qualifications": (
            "<p><strong>Note:</strong> Submit transcripts.</p>"
            "<ul><li>Experience analyzing policy.</li><li>Experience with Congress.</li></ul>"
        ),
    }])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job/1",
            "job_detail",
            html,
            manifest,
            ["qualifications"],
        )
    assert "qualifications" in candidates
    value = candidates["qualifications"][0]["value"]
    assert "<p>" not in value
    assert "<li>" not in value
    assert "Submit transcripts." in value
    assert "Experience analyzing policy." in value
    assert "Experience with Congress." in value


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


def test_extract_job_detail_semantic_specs_do_not_emit_specifications_aggregate():
    html = """
    <html><body>
    <table>
      <tr><th>Salary Range</th><td>$82,000 - $92,000</td></tr>
      <tr><th>Requisition ID</th><td>1393</td></tr>
    </table>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job",
            "job_detail",
            html,
            manifest,
            [],
        )
    assert "salary" in candidates
    assert candidates["salary"][0]["value"] == "$82,000 - $92,000"
    assert "requisition_id" in candidates
    assert candidates["requisition_id"][0]["value"] == "1393"
    assert "specifications" not in candidates


def test_extract_job_detail_ignores_polluted_resolved_fields():
    html = "<html><body><h1>Engineer</h1></body></html>"
    manifest = _manifest(json_ld=[{
        "@type": "JobPosting",
        "title": "Engineer",
        "salaryCurrency": "USD",
        "employmentType": "FULL_TIME",
        "color": "Blue",
        "sku": "ABC-123",
        "image": "https://example.com/job.jpg",
    }])
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/job/1",
            "job_detail",
            html,
            manifest,
            [],
            resolved_fields=["title", "category", "color", "currency", "image_url", "additional_images", "sku"],
        )
    assert "title" in candidates
    assert "category" not in candidates
    assert "color" not in candidates
    assert "currency" not in candidates
    assert "image_url" not in candidates
    assert "additional_images" not in candidates
    assert "sku" not in candidates


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
    # discovered-field candidates (zero quality score for dynamic fields).
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


def test_should_skip_jsonld_block_handles_type_lists():
    assert _should_skip_jsonld_block({"@type": ["Organization", "Thing"]}, "title") is True
    assert _should_skip_jsonld_block({"@type": ["Product", "SoftwareApplication"]}, "title") is False


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
    assert candidates["size"][0]["value"] == "XS/S/M/L/XL"
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
    assert candidates["title"][0]["source"] == "json_ld"
    assert candidates["title"][0]["value"] == "Top Level Title"


def test_coerce_availability_normalizes_known_states_and_drops_ui_noise():
    assert coerce_field_candidate_value("availability", "In stock") == "In stock"
    assert coerce_field_candidate_value("availability", "Sold out") == "Sold out"
    assert coerce_field_candidate_value("availability", "Pre-order now") == "Pre-order now"
    assert coerce_field_candidate_value("availability", "Only 2 left in stock") == "Only 2 left in stock"
    assert coerce_field_candidate_value("availability", "Add to cart") is None


def test_coerce_category_rejects_nav_breadcrumb_noise():
    assert coerce_field_candidate_value("category", "Home > Men > Shirts > Tops") is None
    assert coerce_field_candidate_value("category", "Men > Shirts") == "Men > Shirts"


def test_coerce_title_rejects_account_and_cookie_noise():
    assert coerce_field_candidate_value("title", "Cookie preferences and privacy policy") is None
    assert coerce_field_candidate_value("title", "Sign in to your account") is None
    assert coerce_field_candidate_value("title", "Trail Running Shoe") == "Trail Running Shoe"


def test_normalize_color_candidate_rejects_overlong_or_ui_phrases():
    assert _normalize_color_candidate("Choose options") is None
    assert _normalize_color_candidate("Black Gray Orange") == "Black Gray Orange"
    assert _normalize_color_candidate("Super extra premium metallic reflective carbon black and silver") is None


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
    assert candidates["title"][0]["source"] == "embedded_json"
    assert candidates["title"][0]["value"] == "Embedded Title A"


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
    assert candidates["title"][0]["source"] == "json_ld"
    assert candidates["title"][0]["value"] == "Repeated Title"


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
    assert candidates["title"][0]["source"] == "adapter"
    assert candidates["title"][0]["sources"] == ["adapter"]


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
    assert candidates["brand"][0]["sources"] == ["adapter"]


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
    assert candidates["size"][0]["value"] == "pkg of 100 ea"
    assert candidates["pack_size"][0]["value"] == "pkg of 100 ea"
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


def test_extract_product_string_payload_surfaces_fit_materials_and_carousel_text():
    html = "<html><body><h1>Sylan 2 Shoe Men's</h1></body></html>"
    manifest = _manifest(next_data={
        "props": {
            "pageProps": {
                "product": json.dumps({
                    "name": "Sylan 2 Shoe Men's",
                    "description": "<p>Built for confident speed.</p>",
                    "detailedImages": [
                        {"url": "https://images.arcteryx.com/details/1350x1710/S26-X000010155-Sylan-2-Shoe-Mantis-Mantis-Profile.jpg"},
                        {"url": "https://images.arcteryx.com/details/1350x1710/S26-X000010155-Sylan-2-Shoe-Mantis-Mantis-Hover.jpg"},
                    ],
                    "bigWidgets": [
                        {
                            "label": "Footwear Fit",
                            "type": "generic",
                            "html": "<p>Choose the size equal to your measured foot length.</p>",
                        }
                    ],
                    "customerTips": {
                        "value": "This shoe is designed for a Precision Fit.",
                    },
                    "materials": ["Lining: Textile", "Outsole: Rubber"],
                    "careInstructions": ["Surface clean only"],
                    "features": [
                        {
                            "label": "Technical features",
                            "value": [
                                "Responsive for efficiency and reduced fatigue",
                                "Propulsive yet stable",
                            ],
                        }
                    ],
                    "centreSectionTemplate": {
                        "featureTiles": [
                            {
                                "title": "Speedy construction",
                                "description": "The rockered shape maximizes energy return.",
                            }
                        ]
                    },
                })
            }
        }
    })
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://arcteryx.com/us/en/shop/mens/sylan-2-shoe-0155",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["image_url"][0]["value"].endswith("Profile.jpg")
    assert "Hover.jpg" in candidates["additional_images"][0]["value"]
    assert "Choose the size equal to your measured foot length." in candidates["fit_and_sizing"][0]["value"]
    assert "Product tip: This shoe is designed for a Precision Fit." in candidates["fit_and_sizing"][0]["value"]
    assert "Lining: Textile" in candidates["materials_and_care"][0]["value"]
    assert "Surface clean only" in candidates["materials_and_care"][0]["value"]
    assert "Technical features:" in candidates["features"][0]["value"]
    assert "Speedy construction: The rockered shape maximizes energy return." in candidates["features"][0]["value"]


def test_extract_priority_order():
    """Adapter data should short-circuit JSON-LD collection."""
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
    assert [c["source"] for c in candidates["title"]] == ["adapter"]


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


def test_normalize_color_candidate_rejects_css_noise():
    assert _normalize_color_candidate(
        "#0d475c;padding:8px 0;position:relative;padding:0;}.css-hazhdp-nav-bar .side-men"
    ) is None


def test_normalize_color_candidate_rejects_variant_count_labels():
    assert _normalize_color_candidate("12 colors") is None


def test_normalize_size_candidate_rejects_css_noise():
    assert _normalize_size_candidate(
        "12px;font-weight:330;-webkit-transition:0.1s ease;transition:0.1s ease;}"
    ) is None


def test_normalize_html_rich_text_handles_block_tags_without_crashing():
    assert _normalize_html_rich_text("<div>Alpha</div><p>Beta</p><br><li>Gamma</li>") == "Alpha\nBeta\nGamma"



# Property 3: Extraction Hierarchy Order Preservation
def test_extraction_hierarchy_order_preservation_datalayer_before_network():
    """Feature: extraction-pipeline-improvements, Property 3: Extraction Hierarchy Order Preservation
    
    **Validates: Requirements 1.6, 2.3, 2.5**
    
    For any HTML containing the same field value in multiple sources (adapter, dataLayer, 
    JSON-LD, DOM), the extraction pipeline SHALL resolve the field using the first source 
    in hierarchy order, and SHALL NOT consult subsequent sources once a valid value is found.
    
    This test verifies that dataLayer (step 2) is consulted before Network Intercept (step 3).
    """
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 29.99,
                    "currency": "USD"
                }
            ]
        }
    });
    </script>
    </body></html>
    """
    
    # Network payload has different price
    manifest = _manifest(
        network_payloads=[
            {
                "url": "https://api.example.com/product",
                "body": {"price": "39.99", "currency": "EUR"}
            }
        ]
    )
    
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    
    # Should use dataLayer price (29.99), not network payload price (39.99)
    assert "price" in candidates
    assert len(candidates["price"]) == 1
    assert candidates["price"][0]["source"] == "datalayer"
    assert candidates["price"][0]["value"] == 29.99


def test_extraction_hierarchy_order_preservation_adapter_before_datalayer():
    """Feature: extraction-pipeline-improvements, Property 3: Extraction Hierarchy Order Preservation
    
    **Validates: Requirements 1.6, 2.3, 2.5**
    
    This test verifies that Adapter (step 1) is consulted before dataLayer (step 2).
    """
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 29.99,
                    "currency": "USD"
                }
            ]
        }
    });
    </script>
    </body></html>
    """
    
    # Adapter has different price
    manifest = _manifest(
        adapter_data=[{"price": "19.99", "currency": "GBP"}]
    )
    
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    
    # Should use adapter price (19.99), not dataLayer price (29.99)
    assert "price" in candidates
    assert len(candidates["price"]) == 1
    assert candidates["price"][0]["source"] == "adapter"
    assert candidates["price"][0]["value"] == "19.99"


def test_extraction_hierarchy_order_preservation_datalayer_before_jsonld():
    """Feature: extraction-pipeline-improvements, Property 3: Extraction Hierarchy Order Preservation
    
    **Validates: Requirements 1.6, 2.3, 2.5**
    
    This test verifies that dataLayer (step 2) is consulted before JSON-LD (step 4).
    """
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 29.99,
                    "currency": "USD"
                }
            ]
        }
    });
    </script>
    <script type="application/ld+json">
    {"@type": "Product", "price": "39.99", "priceCurrency": "EUR"}
    </script>
    </body></html>
    """
    
    # Don't use manifest - let parse_page_sources extract both dataLayer and JSON-LD from HTML
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            None,  # No manifest - parse from HTML
            [],
        )
    
    # Should use dataLayer price (29.99), not JSON-LD price (39.99)
    assert "price" in candidates
    assert len(candidates["price"]) == 1
    assert candidates["price"][0]["source"] == "datalayer"
    assert candidates["price"][0]["value"] == 29.99
