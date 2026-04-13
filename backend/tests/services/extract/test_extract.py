# Tests for the extraction service.
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from app.services.exceptions import ExtractionParseError
from app.services.extract.source_parsers import parse_page_sources
from app.services.extract.candidate_processing import (
    candidate_source_rank,
    finalize_candidate_row,
    coerce_field_candidate_value,
)
from app.services.extract.service import (
    extract_candidates as _extract_candidates_impl,
)
from tests.support import manifest as _manifest
from tests.support import run_extract_candidates


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    manifest: dict | None,
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
):
    return run_extract_candidates(
        _extract_candidates_impl,
        url=url,
        surface=surface,
        html=html,
        manifest_data=manifest,
        additional_fields=additional_fields,
        extraction_contract=extraction_contract,
        resolved_fields=resolved_fields,
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


def test_extract_candidates_raises_typed_parse_error_with_cause():
    parse_exc = ValueError("broken source payload")

    with patch(
        "app.services.extract.service.parse_page_sources",
        side_effect=parse_exc,
    ):
        with pytest.raises(ExtractionParseError) as exc_info:
            _extract_candidates_impl(
                "https://example.com/product",
                "ecommerce_detail",
                "<html></html>",
                [],
                [],
            )

    assert exc_info.value.__cause__ is parse_exc


def test_parse_page_sources_raises_typed_parse_error_with_cause():
    parse_exc = ValueError("broken embedded JSON payload")

    with patch(
        "app.services.extract.source_parsers.extract_hydrated_states",
        side_effect=parse_exc,
    ):
        with pytest.raises(ExtractionParseError) as exc_info:
            parse_page_sources("<html></html>")

    assert exc_info.value.__cause__ is parse_exc


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


def test_extract_candidates_prefers_saashr_job_detail_payload_over_generic_network_title_matches():
    html = """
    <html>
      <body>
        <div class="c-career-search-header-bar__comp-name">
          LEWIS &amp; CLARK BEHAVIORAL HEALTH SERVICES INC.
        </div>
        <div class="c-career-search-details-view__title-heading-text">Case Manager</div>
      </body>
    </html>
    """
    manifest = _manifest(
        network_payloads=[
            {
                "url": "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/%7C6208610/job-search/config?ein_id=118959061&career_portal_id=6062087&lang=en-US",
                "body": {
                    "comp_name": "LEWIS & CLARK BEHAVIORAL HEALTH SERVICES INC.",
                },
            },
            {
                "url": "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/%7C6208610/job-requisitions/570929092?showMap=1&lang=en-US",
                "body": {
                    "id": 570929092,
                    "job_title": "Case Manager",
                    "location": {
                        "address_line_1": "3111 Shirley Bridge Ave",
                        "city": "Yankton",
                        "state": "SD",
                        "zip": "57078",
                        "country": "USA",
                    },
                    "employee_type": {"name": "Full-Time"},
                    "job_description": "<p>Community-based case management.</p>",
                    "job_requirement": "<ul><li>High school diploma</li></ul>",
                    "job_preview": "<p>Three weeks paid vacation.</p>",
                    "is_remote_job": False,
                },
            },
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://secure7.saashr.com/ta/6208610.careers?offset=1&size=20&sort=desc&ein_id=118959061&lang=en-US&career_portal_id=6062087&ShowJob=570929092",
            "job_detail",
            html,
            manifest,
            [],
        )

    assert candidates["title"][0]["source"] == "saashr_detail"
    assert candidates["title"][0]["value"] == "Case Manager"
    assert candidates["company"][0]["value"] == "LEWIS & CLARK BEHAVIORAL HEALTH SERVICES INC."
    assert candidates["location"][0]["value"] == "3111 Shirley Bridge Ave, Yankton, SD, 57078, USA"
    assert candidates["job_type"][0]["value"] == "Full-Time"
    assert candidates["description"][0]["value"] == "Community-based case management."
    assert candidates["requirements"][0]["value"].startswith("High")
    assert "diploma" in candidates["requirements"][0]["value"]
    assert candidates["benefits"][0]["value"] == "Three weeks paid vacation."
    assert candidates["apply_url"][0]["value"].endswith("ShowJob=570929092")


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


def test_coerce_field_candidate_value_rejects_asset_font_urls_for_url_fields():
    assert (
        coerce_field_candidate_value(
            "url",
            "https://cdn.example.com/fonts/inter.woff2",
            base_url="https://example.com/product",
        )
        is None
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
    html = "<html><body></body></html>"
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


def test_extract_embedded_json_candidate_keeps_blob_family_trace():
    html = """
    <html><body>
    <script id="product-json">
    {"product":{"title":"Embedded Title","brand":"EmbedCo","price":"19.99"}}
    </script>
    </body></html>
    """
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            None,
            [],
        )
    embedded_title = next(
        (item for item in candidates["title"] if item["source"] == "embedded_json"),
        None,
    )
    assert embedded_title is not None
    assert embedded_title["blob_family"] == "product_json"
    assert embedded_title["blob_origin"] == "script"


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
    assert "number_of_keys" not in candidates
    assert "polyphony" not in candidates
    assert trace["discovered_data"]["discovered_fields"]["number_of_keys"] == "61"
    assert trace["discovered_data"]["discovered_fields"]["polyphony"] == "16 Voice"
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
    assert "wire_gauge" not in candidates
    assert "impedance" not in candidates
    assert "specifications" in candidates
    assert "wire_gauge: 26 AWG" in candidates["specifications"][0]["value"]
    assert candidates["product_attributes"][0]["value"]["wire_gauge"] == "26 AWG"
    assert candidates["product_attributes"][0]["value"]["impedance"] == "50 Ohms"


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
    assert "requisition_id" not in candidates
    assert candidates["product_attributes"][0]["value"]["requisition_id"] == "1393"
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
    assert candidates["specifications"][0]["source"] == "structured_spec"
    assert "prop_65: CA" in candidates["specifications"][0]["value"]
    assert "depth: 9-21/32 in" in candidates["specifications"][0]["value"]
    assert "height: 15 in" in candidates["specifications"][0]["value"]
    assert candidates["product_attributes"][0]["value"]["prop_65"] == "CA"
    assert "depth" not in candidates
    assert "height" not in candidates


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
    assert "compression" not in candidates

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        _, trace = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert trace["discovered_data"]["discovered_fields"]["compression"] == "Ultra-tight, second-skin fit."
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
        "title": "Extremely Long Top Level Title",
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
    assert candidates["title"][0]["value"] == "Extremely Long Top Level Title"


def test_coerce_availability_normalizes_known_states_and_drops_ui_noise():
    assert coerce_field_candidate_value("availability", "In stock") == "In stock"
    assert coerce_field_candidate_value("availability", "Sold out") == "Sold out"
    assert coerce_field_candidate_value("availability", "Pre-order now") == "Pre-order now"
    assert coerce_field_candidate_value("availability", "Only 2 left in stock") == "Only 2 left in stock"
    assert coerce_field_candidate_value("availability", "Add to cart") is None


def test_coerce_category_rejects_nav_breadcrumb_noise():
    assert coerce_field_candidate_value("category", "Home > Men > Shirts > Tops") == "Men > Shirts > Tops"
    assert coerce_field_candidate_value("category", "Men > Shirts") == "Men > Shirts"
    assert coerce_field_candidate_value("category", "object") is None


def test_coerce_price_rejects_boolean_values():
    assert coerce_field_candidate_value("price", False) is None
    assert coerce_field_candidate_value("price", "2") is None
    assert coerce_field_candidate_value("price", "9.99") == "9.99"
    assert coerce_field_candidate_value("price", "0.99") == "0.99"
    assert coerce_field_candidate_value("price", "2500") == "2500"


def test_coerce_salary_returns_none_for_overlong_input():
    assert coerce_field_candidate_value("salary", "9" * 10_000) is None


def test_extract_category_falls_back_to_breadcrumb_and_ignores_network_sentinel_values():
    html = """
    <html>
      <body>
        <nav aria-label="Breadcrumb">
          <a href="/">Home</a>
          <a href="/women">Women</a>
          <a href="/women/shoes">Shoes</a>
        </nav>
      </body>
    </html>
    """
    manifest = _manifest(
        network_payloads=[
            {
                "url": "https://api.example.com/product",
                "body": {"category": "object", "price": False},
            }
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product/123",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["category"][0]["value"] == "Women > Shoes"
    assert "price" not in candidates


def test_coerce_title_rejects_account_and_cookie_noise():
    assert coerce_field_candidate_value("title", "Cookie preferences and privacy policy") is None
    assert coerce_field_candidate_value("title", "Sign in to your account") is None
    assert coerce_field_candidate_value("title", "Select a Size") is None
    assert coerce_field_candidate_value("title", "Trail Running Shoe") == "Trail Running Shoe"


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
        {"title": "Repeated Title (Primary)"},
        {"title": "Repeated Title (Primary)"},
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
    assert candidates["title"][0]["value"] == "Repeated Title (Primary)"


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
        candidates, trace = extract_candidates(
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
    assert "pack_size" not in candidates
    assert trace["discovered_data"]["discovered_fields"]["pack_size"] == "pkg of 100 ea"
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
        candidates, trace = extract_candidates(
            "https://arcteryx.com/us/en/shop/mens/sylan-2-shoe-0155",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )
    assert candidates["image_url"][0]["value"].endswith("Profile.jpg")
    assert "Hover.jpg" in candidates["additional_images"][0]["value"]
    assert "fit_and_sizing" not in candidates
    assert "Choose the size equal to your measured foot length." in trace["discovered_data"]["discovered_fields"]["fit_and_sizing"]
    assert "Product tip: This shoe is designed for a Precision Fit." in trace["discovered_data"]["discovered_fields"]["fit_and_sizing"]
    assert "Lining: Textile" in trace["discovered_data"]["discovered_fields"]["materials_and_care"]
    assert "Surface clean only" in trace["discovered_data"]["discovered_fields"]["materials_and_care"]
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
def test_extract_prefers_json_ld_when_datalayer_category_and_availability_are_polluted():
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "item_category": "page",
                    "availability": "Add to cart"
                }
            ]
        }
    });
    </script>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "category": "Mirrorless Cameras",
        "offers": {
            "availability": "https://schema.org/InStock"
        }
    }
    </script>
    </body></html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["category"][0]["source"] == "json_ld"
    assert candidates["category"][0]["value"] == "Mirrorless Cameras"
    assert candidates["availability"][0]["source"] == "json_ld"
    assert candidates["availability"][0]["value"] == "in_stock"


def test_extract_ignores_generic_config_blob_pollution_from_data_attributes():
    html = """
    <html>
      <body>
        <div data-config='{"title":"Cookie Banner","category":"page","availability":"Add to cart"}'></div>
        <h1>Canon EOS R8</h1>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/product",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["title"][0]["source"] == "dom"
    assert candidates["title"][0]["value"] == "Canon EOS R8"
    assert "category" not in candidates
    assert "availability" not in candidates


def test_extract_demandware_network_payload_builds_variants_and_syncs_root_scalars():
    html = "<html><body><button data-url=\"/ignored\"></button></body></html>"
    manifest = _manifest(
        network_payloads=[
            {
                "url": (
                    "https://www.giro.com/on/demandware.store/Sites-giro-us-Site/en_US/"
                    "Product-Variation?pid=GR-7115071&dwvar_GR-7115071_color=Black&dwvar_GR-7115071_size=28"
                ),
                "body": {
                    "product": {
                        "id": "GR-7115071-BLK-28",
                        "readyToOrder": True,
                        "selectedProductUrl": (
                            "https://www.giro.com/product/ga-m-venture-pant-blk-28/GR-7115071.html"
                            "?dwvar_GR-7115071_color=Black&dwvar_GR-7115071_size=28"
                        ),
                        "price": {
                            "sales": {"formatted": "89.00"},
                            "list": {"formatted": "99.00"},
                        },
                        "images": {
                            "large": [{"url": "https://cdn.example.com/blk-28.jpg"}]
                        },
                        "variationAttributes": [
                            {
                                "id": "color",
                                "values": [
                                    {"id": "BLACK", "displayValue": "Black", "selected": True},
                                    {"id": "CHARCOAL", "displayValue": "Charcoal"},
                                ],
                            },
                            {
                                "id": "size",
                                "values": [
                                    {"id": "28", "displayValue": "28", "selected": True},
                                    {"id": "30", "displayValue": "30"},
                                ],
                            },
                            {
                                "id": "style",
                                "values": [
                                    {
                                        "id": "KN4991300",
                                        "displayValue": "KN4991300",
                                        "selected": True,
                                    }
                                ],
                            },
                        ],
                    }
                },
            }
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.giro.com/product/ga-m-venture-pant-blk-28/GR-7115071.html",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert candidates["selected_variant"][0]["value"]["sku"] == "GR-7115071-BLK-28"
    assert candidates["variant_axes"][0]["value"]["color"] == ["Black", "Charcoal"]
    assert candidates["variant_axes"][0]["value"]["size"] == ["28", "30"]
    assert "style" not in candidates["variant_axes"][0]["value"]
    assert candidates["product_attributes"][0]["value"] == {"style": "KN4991300"}
    assert candidates["price"][0]["value"] == "89.00"
    assert candidates["original_price"][0]["value"] == "99.00"
    assert candidates["availability"][0]["value"] == "in_stock"
    assert candidates["image_url"][0]["value"] == "https://cdn.example.com/blk-28.jpg"
    assert candidates["color"][0]["value"] == "Black"
    assert candidates["size"][0]["value"] == "28"


def test_extract_selected_variant_overwrites_root_scalars_and_cleans_product_attributes():
    html = "<html><body><h1>Adapter Variant Product</h1></body></html>"
    manifest = _manifest(
        adapter_data=[
            {
                "_source": "adapter",
                "title": "Adapter Variant Product",
                "price": "10.00",
                "color": "Blue",
                "variants": [
                    {
                        "variant_id": "sku-red-s",
                        "sku": "sku-red-s",
                        "price": "12.00",
                        "original_price": "15.00",
                        "availability": "in_stock",
                        "image_url": "https://cdn.example.com/red-s.jpg",
                        "color": "Red",
                        "size": "S",
                        "option_values": {"color": "Red", "size": "S", "style": "KN4991300"},
                    }
                ],
                "variant_axes": {
                    "color": ["Red", "Blue"],
                    "size": ["S"],
                    "style": ["KN4991300"],
                },
                "selected_variant": {
                    "variant_id": "sku-red-s",
                    "sku": "sku-red-s",
                    "price": "12.00",
                    "original_price": "15.00",
                    "availability": "in_stock",
                    "image_url": "https://cdn.example.com/red-s.jpg",
                    "color": "Red",
                    "size": "S",
                    "option_values": {"color": "Red", "size": "S", "style": "KN4991300"},
                },
                "product_attributes": {
                    "fit": "Slim",
                    "color": "Should disappear",
                    "size": "Should disappear",
                    "materials": "Should disappear",
                    "style": "KN4991300",
                },
            }
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/adapter-variant",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert candidates["price"][0]["value"] == "12.00"
    assert candidates["original_price"][0]["value"] == "15.00"
    assert candidates["sku"][0]["value"] == "sku-red-s"
    assert candidates["color"][0]["value"] == "Red"
    assert candidates["size"][0]["value"] == "S"
    assert candidates["availability"][0]["value"] == "in_stock"
    assert candidates["image_url"][0]["value"] == "https://cdn.example.com/red-s.jpg"
    assert candidates["variant_axes"][0]["value"] == {"color": ["Red", "Blue"], "size": ["S"]}
    assert candidates["product_attributes"][0]["value"] == {
        "fit": "Slim",
        "style": "KN4991300",
    }


def test_extract_myntra_style_dom_size_variants_preserve_axes_without_fabricating_variants():
    html = """
    <html>
      <body>
        <h1>Myntra Test Kurti</h1>
        <div class="size-buttons-container">
          <div class="size-buttons-size-header">Select Size</div>
          <button class="size-buttons-size-button size-buttons-size-button-default">S</button>
          <button class="size-buttons-size-button size-buttons-size-button-selected">M</button>
          <button class="size-buttons-size-button size-buttons-size-button-default">L</button>
        </div>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.myntra.com/kurtis/example/test-kurti/123/buy",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["variant_axes"][0]["source"] == "dom_variant"
    assert candidates["variant_axes"][0]["value"] == {"size": ["S", "M", "L"]}
    assert candidates["selected_variant"][0]["value"]["size"] == "M"
    assert candidates["size"][0]["value"] == "M"
    assert "variants" not in candidates


def test_extract_structured_specifications_normalize_html_content():
    html = "<html><body><h1>Myntra Test Kurti</h1></body></html>"
    manifest = _manifest(
        embedded_json=[
            {
                "product": {
                    "specificationGroups": [
                        {
                            "label": "Product Details",
                            "specifications": [
                                {
                                    "title": "material",
                                    "content": "<p>Viscose rayon</p><ul><li>Soft finish</li></ul>",
                                },
                                {
                                    "title": "wash_care",
                                    "content": "<div>Machine wash<br/>Warm iron</div>",
                                },
                            ],
                        }
                    ]
                }
            }
        ]
    )

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.myntra.com/kurtis/example/test-kurti/123/buy",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    spec_text = candidates["specifications"][0]["value"]
    assert "<" not in spec_text
    assert "material: Viscose rayon" in spec_text
    assert "Soft finish" in spec_text
    assert "wash_care: Machine wash" in spec_text
    assert "Warm iron" in spec_text


def test_extract_structured_template_placeholders_do_not_surface_as_discount_percentage():
    html = "<html><body><h1>Structured Discount Template Product</h1></body></html>"
    manifest = _manifest(
        _hydrated_states=[
            {
                "props": {
                    "pageProps": {
                        "product": {
                            "specificationGroups": [
                                {
                                    "label": "Pricing",
                                    "specifications": [
                                        {
                                            "title": "discount_percentage",
                                            "content": "-{amount}%",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        ]
    )

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert "discount_percentage" not in candidates


def test_extract_reconciles_variant_bundle_and_drops_duplicate_or_empty_rows():
    html = "<html><body><h1>Variant Reconcile Product</h1></body></html>"
    manifest = _manifest(
        adapter_data=[
            {
                "_source": "adapter",
                "title": "Variant Reconcile Product",
                "variants": [
                    {"url": "https://example.com/products/widget"},
                    {
                        "variant_id": "sku-red-s",
                        "sku": "sku-red-s",
                        "price": "12.00",
                        "availability": "in_stock",
                        "color": "Red",
                        "size": "S",
                        "option_values": {"color": "Red", "size": "S", "style": "KN4991300"},
                    },
                    {
                        "variant_id": "sku-red-s",
                        "sku": "sku-red-s",
                        "price": "12.00",
                        "availability": "in_stock",
                        "color": "Red",
                        "size": "S",
                        "option_values": {"color": "Red", "size": "S", "style": "KN4991300"},
                    },
                    {
                        "variant_id": "sku-blue-s",
                        "sku": "sku-blue-s",
                        "price": "13.00",
                        "availability": "out_of_stock",
                        "color": "Blue",
                        "size": "S",
                        "option_values": {"color": "Blue", "size": "S", "style": "KN4991300"},
                    },
                ],
                "variant_axes": {
                    "color": ["Red", "Blue", "Blue"],
                    "size": ["S"],
                    "style": ["KN4991300"],
                    "phantom": ["Should disappear"],
                },
                "selected_variant": {
                    "variant_id": "sku-red-s",
                    "sku": "sku-red-s",
                    "price": "12.00",
                    "availability": "in_stock",
                    "color": "Red",
                    "size": "S",
                    "option_values": {"color": "Red", "size": "S", "style": "KN4991300"},
                },
            }
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    variants = candidates["variants"][0]["value"]
    assert len(variants) == 2
    assert [row["variant_id"] for row in variants] == ["sku-red-s", "sku-blue-s"]
    assert candidates["variant_axes"][0]["value"] == {"color": ["Red", "Blue"], "size": ["S"]}
    assert candidates["product_attributes"][0]["value"] == {"style": "KN4991300"}
    assert candidates["selected_variant"][0]["value"]["variant_id"] == "sku-red-s"


def test_extract_dom_variant_rows_do_not_create_multi_axis_cartesian_variants():
    html = """
    <html>
      <body>
        <h1>Cartesian Guard Product</h1>
        <div class="color-swatches">
          <button class="color-swatch selected">Red</button>
          <button class="color-swatch">Blue</button>
        </div>
        <div class="size-buttons-container">
          <button class="size-buttons-size-button size-buttons-size-button-selected">S</button>
          <button class="size-buttons-size-button">M</button>
        </div>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["variant_axes"][0]["value"] == {"color": ["Red", "Blue"], "size": ["S", "M"]}
    assert "variants" not in candidates
    assert candidates["selected_variant"][0]["value"]["color"] == "Red"
    assert candidates["selected_variant"][0]["value"]["size"] == "S"


def test_extract_dom_variant_rows_build_real_variants_from_combination_urls_and_availability():
    html = """
    <html>
      <body>
        <h1>Combination Variant Product</h1>
        <a
          class="btn b-product-attributes__color-btn selected js-variation-button js-variation--color"
          data-attr="color"
          data-attr-display-value="Black"
          data-variation-url="https://example.com/productvariation?dwvar_W0905_color=Black&pid=W0905"
          href="https://example.com/products/widget?dwvar_W0905_color=Black"
        >
          <span id="variation-color-Black">Black</span>
        </a>
        <label
          class="btn b-product-attributes__size-btn selected js-variation-button js-variation--size js-variation--size-32 available"
          data-attr="size"
          data-attr-display-value="4"
          data-url="https://example.com/productvariation?dwvar_W0905_color=Black&dwvar_W0905_size=32&pid=W0905"
        >
          <input aria-label="size 4" name="size" type="radio" value="32" />
          <span aria-hidden="true">4</span>
        </label>
        <label
          class="btn b-product-attributes__size-btn js-variation-button js-variation--size js-variation--size-34 sold"
          data-attr="size"
          data-attr-display-value="6"
          data-url="https://example.com/productvariation?dwvar_W0905_color=Black&dwvar_W0905_size=34&pid=W0905"
        >
          <input aria-label="size 6" name="size" type="radio" value="34" />
          <span aria-hidden="true">6</span>
        </label>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            None,
            [],
        )
    assert candidates["variant_axes"][0]["value"] == {"color": ["Black"], "size": ["4", "6"]}
    assert candidates["variants"][0]["source"] == "dom_variant"
    assert candidates["variants"][0]["value"] == [
        {
            "option_values": {"color": "Black", "size": "4"},
            "url": "https://example.com/productvariation?dwvar_W0905_color=Black&dwvar_W0905_size=32&pid=W0905",
            "color": "Black",
            "size": "4",
            "availability": "in_stock",
        },
        {
            "option_values": {"color": "Black", "size": "6"},
            "url": "https://example.com/productvariation?dwvar_W0905_color=Black&dwvar_W0905_size=34&pid=W0905",
            "color": "Black",
            "size": "6",
            "availability": "out_of_stock",
        },
    ]
    assert candidates["selected_variant"][0]["value"]["size"] == "4"
    assert candidates["selected_variant"][0]["value"]["availability"] == "in_stock"


def test_candidate_source_rank_prefers_saashr_detail_source():
    assert candidate_source_rank("title", "saashr_detail") > candidate_source_rank(
        "title", "open_graph"
    )


def test_extract_dom_variant_rows_do_not_infer_unknown_axis_selection():
    html = """
    <html>
      <body>
        <h1>Unknown Selection Product</h1>
        <div class="color-swatches">
          <button class="color-swatch selected">Red</button>
          <button class="color-swatch">Blue</button>
        </div>
        <div class="size-buttons-container">
          <button class="size-buttons-size-button">S</button>
          <button class="size-buttons-size-button">M</button>
        </div>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["variant_axes"][0]["value"] == {"color": ["Red", "Blue"], "size": ["S", "M"]}
    assert candidates["selected_variant"][0]["value"]["color"] == "Red"
    assert "size" not in candidates["selected_variant"][0]["value"]


def test_extract_dom_variant_rows_ignore_ui_cta_values():
    html = """
    <html>
      <body>
        <fieldset>
          <legend>Color</legend>
          <button class="variant-option" aria-label="color Black" type="button">Black</button>
          <button class="variant-option" aria-label="color Share" type="button">Share</button>
        </fieldset>
        <fieldset>
          <legend>Size</legend>
          <button class="variant-option" aria-label="size 6" type="button">6</button>
          <button class="variant-option" aria-label="size 8" type="button">8</button>
          <button class="variant-option" aria-label="size See more" type="button">See more</button>
          <button class="variant-option" aria-label="size Size Guide" type="button">Size Guide</button>
        </fieldset>
      </body>
    </html>
    """

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["variant_axes"][0]["value"] == {"color": ["Black"], "size": ["6", "8"]}


def test_extract_structured_state_variants_are_discovered_without_site_hardcode():
    html = "<html><body><h1>Structured Variant Product</h1></body></html>"
    manifest = _manifest(
        _hydrated_states=[
            {
                "props": {
                    "urqlState": {
                        "2259305856": {
                            "data": json.dumps(
                                {
                                    "product": {
                                        "id": "529704",
                                        "name": "Performance Woven Men's Side Pocket Gym Shorts",
                                        "colors": [
                                            {"name": "PUMA Black", "value": "01"},
                                            {"name": "PUMA Navy", "value": "06"},
                                        ],
                                        "variations": [
                                            {
                                                "id": "529704_01",
                                                "variantId": "4070032421827",
                                                "price": 1799,
                                                "colorValue": "01",
                                                "colorName": "PUMA Black",
                                                "orderable": True,
                                                "preview": "https://images.puma.com/529704/01.png",
                                            },
                                            {
                                                "id": "529704_06",
                                                "variantId": "4070032421828",
                                                "price": 1799,
                                                "colorValue": "06",
                                                "colorName": "PUMA Navy",
                                                "orderable": True,
                                                "preview": "https://images.puma.com/529704/06.png",
                                            },
                                        ],
                                    }
                                }
                            )
                        }
                    }
                },
                "query": {"swatch": "06"},
            }
        ]
    )

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://in.puma.com/in/en/pd/performance-woven-mens-side-pocket-gym-shorts/529704?swatch=06",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert candidates["variants"][0]["source"] == "structured_variant"
    assert [row["variant_id"] for row in candidates["variants"][0]["value"]] == [
        "4070032421827",
        "4070032421828",
    ]
    assert candidates["variant_axes"][0]["value"] == {
        "color": ["PUMA Black", "PUMA Navy"]
    }
    assert candidates["selected_variant"][0]["value"]["variant_id"] == "4070032421828"
    assert candidates["selected_variant"][0]["value"]["color"] == "PUMA Navy"


def test_extract_shopify_footer_sections_do_not_pollute_product_attributes():
    html = """
    <html><body>
      <h1>Portuguese Terry Quarter-Zip Sweatshirt</h1>
      <h2>Customer Service</h2>
      <ul>
        <li>Account Login</li>
        <li>Shipping Policy</li>
        <li>Return Policy</li>
        <li>Gift Cards</li>
      </ul>
      <h2>Contact</h2>
      <p>Join Our Team Contact Us Press Inquiries</p>
      <h2>Reviews</h2>
      <p>Love it Loading... Read more</p>
    </body></html>
    """
    manifest = _manifest(
        adapter_data=[
            {
                "_source": "adapter",
                "title": "Portuguese Terry Quarter-Zip Sweatshirt",
                "product_attributes": {"style": "KN4991300-429", "color": "Light Grey Mix"},
                "color": "Light Grey Mix",
            }
        ]
    )
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.toddsnyder.com/products/zip-mocklight-grey-mix",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert candidates["product_attributes"][0]["value"] == {"style": "KN4991300-429"}


def test_extract_text_pattern_does_not_promote_long_form_fields_from_raw_html_fallback():
    html = """
    <html><body>
      <h1>Portuguese Terry Quarter-Zip Sweatshirt</h1>
      <script type="application/json">
        {
          "related_copy": "Materials: This cotton-cashmere yarn is breathable and luxuriously soft. Specifications: an extra tab closure at the hem."
        }
      </script>
    </body></html>
    """
    manifest = _manifest()
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://www.toddsnyder.com/products/zip-mocklight-grey-mix",
            "ecommerce_detail",
            html,
            manifest,
            [],
        )

    assert "materials" not in candidates
    assert "specifications" not in candidates


def test_extract_semantic_sections_skip_related_product_blocks_on_detail_pages():
    html = """
    <html><body>
      <main>
        <h1>iPhone 14 Battery</h1>
        <h2>Description</h2>
        <p>Main battery description.</p>
        <h2>Compatibility</h2>
        <p>iPhone 14 A2649 US A2881 Canada</p>
        <h2>Featured Products</h2>
        <a href="/products/other-part">Other Part</a>
        <p>$3.99 Add to cart</p>
        <h2>Frequently Bought Together</h2>
        <a href="/products/accessory">Accessory</a>
        <p>$24.95 Add to cart</p>
      </main>
    </body></html>
    """
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/battery",
            "ecommerce_detail",
            html,
            None,
            ["rating", "review_count"],
        )

    assert candidates["description"][0]["value"] == "Main battery description."
    assert candidates["product_attributes"][0]["value"] == {
        "compatibility": "iPhone 14 A2649 US A2881 Canada"
    }
    assert "features" not in candidates


def test_extract_text_pattern_captures_visible_rating_and_review_count():
    html = """
    <html><body>
      <main>
        <h1>iPhone 14 Battery</h1>
        <div>5 25 reviews</div>
        <h2>Description</h2>
        <p>Main battery description.</p>
      </main>
    </body></html>
    """
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/battery",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["rating"][0]["value"] == "5"
    assert candidates["review_count"][0]["value"] == "25"


def test_extract_text_pattern_prefers_labeled_rating_and_accepts_ratings_wording():
    html = """
    <html><body>
      <main>
        <div>Rating: 4.2</div>
        <div>128 ratings</div>
      </main>
    </body></html>
    """
    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        candidates, _ = extract_candidates(
            "https://example.com/products/widget",
            "ecommerce_detail",
            html,
            None,
            [],
        )

    assert candidates["rating"][0]["value"] == "4.2"
    assert candidates["review_count"][0]["value"] == "128"


def test_finalize_candidate_row_normalizes_product_json_cents_values():
    value, reason = finalize_candidate_row(
        "original_price",
        {
            "value": 15800,
            "source": "embedded_json",
            "blob_family": "product_json",
        },
    )

    assert reason is None
    assert value == "158.00"
