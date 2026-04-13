from app.services.extract.field_decision import FieldDecisionEngine
from app.services.pipeline.detail_flow import merge_detail_reconciliation
from app.services.pipeline.field_normalization import _merge_record_fields
from app.services.extract.service import extract_candidates
import app.services.extract.service as extract_service


def test_schema_arbitration_rejects_datalayer_pollution():
    """
    Tests that a noisy/garbage string in a high-priority source (datalayer)
    is correctly rejected by the validator, allowing a clean lower-priority
    source (DOM) to win arbitration.
    """
    url = "https://www.example-store.com/product/nike-shoes"
    surface = "ecommerce_detail"

    # Mock HTML containing both a polluted datalayer and a clean DOM
    html = """
    <html>
        <head>
            <script>
                dataLayer.push({
                    "ecommerce": {
                        "detail": {
                            "products": [{
                                "brand": "Home > Privacy Policy > Nike",
                                "category": "Sign in to view categories",
                                "price": "120.00"
                            }]
                        }
                    }
                });
            </script>
        </head>
        <body>
            <h1 class="product-title">Nike Air Max 90</h1>
            <span itemprop="brand">Nike</span>
            <div itemprop="category">Sneakers</div>
        </body>
    </html>
    """

    # Execute the extraction pipeline
    candidates, source_trace = extract_candidates(
        url=url,
        surface=surface,
        html=html,
        xhr_payloads=[],
        additional_fields=[],
        extraction_contract=[],
        resolved_fields=["title", "brand", "category", "price"]
    )
    
    final_candidates = source_trace.get("candidates", {})
    
    # Assertions
    # 1. Price should be extracted from datalayer (clean scalar)
    assert final_candidates["price"][0]["value"] == "120.00"
    assert "datalayer" in final_candidates["price"][0]["source"]
    
    # 2. Brand should REJECT the datalayer noise and fallback to DOM
    assert final_candidates["brand"][0]["value"] == "Nike"
    assert "dom" in final_candidates["brand"][0]["source"] or "selector" in final_candidates["brand"][0]["source"]
    
    # 3. Category should REJECT the datalayer noise and fallback to DOM
    assert final_candidates["category"][0]["value"] == "Sneakers"
    assert "dom" in final_candidates["category"][0]["source"] or "selector" in final_candidates["category"][0]["source"]


def test_field_decision_merge_keeps_existing_when_candidate_is_noisy_or_too_long():
    engine = FieldDecisionEngine()

    noisy = engine.decide_merge(
        "brand",
        "Nike",
        "Home account privacy policy sign in",
    )
    assert noisy.value == "Nike"
    assert noisy.used_candidate is False
    assert noisy.rejection_reason == "field_pollution_rule"

    shorter = engine.decide_merge(
        "brand",
        "Brand",
        "privacy center",
    )
    assert shorter.value == "Brand"
    assert shorter.used_candidate is False
    assert shorter.rejection_reason == "field_pollution_rule"

    too_long = engine.decide_merge(
        "brand",
        "Nike",
        "Nike " * 80,
    )
    assert too_long.value == "Nike"
    assert too_long.used_candidate is False
    assert too_long.rejection_reason == "candidate_too_long"


def test_merge_record_fields_returns_reconciliation_for_kept_existing_candidates():
    merged, reconciliation = _merge_record_fields(
        {"brand": "Nike"},
        {"brand": "privacy center"},
        return_reconciliation=True,
    )

    assert merged["brand"] == "Nike"
    assert reconciliation["brand"]["status"] == "kept_existing"
    assert reconciliation["brand"]["reason"] == "field_pollution_rule"
    assert reconciliation["brand"]["candidate_value"] == "privacy center"


def test_merge_detail_reconciliation_preserves_candidate_rejections_and_merge_reason():
    combined = merge_detail_reconciliation(
        {
            "brand": {
                "status": "accepted_with_rejections",
                "accepted_source": "dom",
                "rejected": [{"value": "privacy center", "reason": "field_pollution_rule"}],
            }
        },
        {
            "brand": {
                "status": "kept_existing",
                "reason": "existing_preferred",
            }
        },
    )

    assert combined["brand"]["status"] == "accepted_with_rejections"
    assert combined["brand"]["merge"]["status"] == "kept_existing"
    assert combined["brand"]["merge"]["reason"] == "existing_preferred"


def test_field_decision_keeps_first_highest_rank_across_different_sources():
    engine = FieldDecisionEngine()

    decision = engine.decide_from_rows(
        "title",
        [
            {"value": "Structured Winner", "source": "embedded_json"},
            {"value": "Structured Winner With Extra Promo Copy", "source": "open_graph"},
        ],
    )

    assert decision.value == "Structured Winner"
    assert decision.source == "embedded_json"


def test_extract_candidates_skips_dom_when_jsonld_winner_is_decisive(monkeypatch):
    html = """
    <html>
        <head>
            <script type="application/ld+json">
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": "Structured Winner"
                }
            </script>
        </head>
        <body>
            <h1>DOM Fallback</h1>
        </body>
    </html>
    """

    def _unexpected_dom_collection(*args, **kwargs):
        raise AssertionError("DOM fallback should not run for a decisive JSON-LD winner")

    monkeypatch.setattr(
        extract_service,
        "_collect_dom_and_meta_candidates",
        _unexpected_dom_collection,
    )

    candidates, source_trace = extract_candidates(
        url="https://example.com/product/structured-winner",
        surface="ecommerce_detail",
        html=html,
        xhr_payloads=[],
        additional_fields=[],
        resolved_fields=["title"],
    )

    assert candidates["title"][0]["value"] == "Structured Winner"
    title_audit = source_trace["extraction_audit"]["title"]["sources"]
    skipped_sources = {
        entry["source"]
        for entry in title_audit
        if entry.get("status") == "skipped"
    }
    assert {"datalayer", "network_intercept", "structured_state", "dom_meta"} <= skipped_sources
