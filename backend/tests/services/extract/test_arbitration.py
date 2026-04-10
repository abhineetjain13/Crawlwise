from app.services.extract.service import extract_candidates


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

def test_should_prefer_secondary_field_logic():
    """Tests the merge logic ensuring short noise doesn't overwrite short facts."""
    from app.services.pipeline.field_normalization import _should_prefer_secondary_field

    # Existing valid short string, candidate is a noisy long string
    existing = "Nike"
    candidate = "Click here to accept cookie policy and agree to terms"
    assert _should_prefer_secondary_field("brand", existing, candidate) is False

    # Existing is noisy, candidate is clean
    existing_noisy = "Home > Brands"
    candidate_clean = "Adidas"
    assert _should_prefer_secondary_field("brand", existing_noisy, candidate_clean) is True


def test_field_decision_engine_parity():
    """Same candidate set resolves identically via _finalize_candidates and
    _reconcile_detail_candidate_values — both now delegate to FieldDecisionEngine."""
    from app.services.extract.field_decision import FieldDecisionEngine
    from app.services.pipeline.core import _reconcile_detail_candidate_values

    url = "https://www.example.com/product/test-widget"

    # Build a candidate set with multiple sources per field, including
    # a noisy high-rank source and a clean lower-rank source.
    candidates: dict[str, list[dict]] = {
        "title": [
            {"value": "Test Widget Pro", "source": "json_ld"},
            {"value": "Test Widget", "source": "dom"},
        ],
        "price": [
            {"value": "49.99", "source": "datalayer"},
            {"value": "$49.99", "source": "selector"},
        ],
        "brand": [
            # Noisy datalayer value should be rejected by sanitiser
            {"value": "Home > Privacy Policy > Acme", "source": "datalayer"},
            {"value": "Acme", "source": "selector"},
        ],
        "description": [
            {"value": "A great widget for testing.", "source": "json_ld"},
        ],
    }

    allowed_fields = {"title", "price", "brand", "description"}

    # Path A: _reconcile_detail_candidate_values (used by core.py pipeline)
    reconciled_a, _ = _reconcile_detail_candidate_values(
        candidates, allowed_fields=allowed_fields, url=url
    )

    # Path B: FieldDecisionEngine directly (used by _finalize_candidates)
    engine = FieldDecisionEngine(base_url=url)
    reconciled_b: dict[str, object] = {}
    for field_name in sorted(allowed_fields):
        rows = list(candidates.get(field_name) or [])
        if not rows:
            continue
        decision = engine.decide_from_rows(field_name, rows)
        if decision.accepted:
            reconciled_b[field_name] = decision.value

    # Both paths must produce identical winners
    assert reconciled_a == reconciled_b, (
        f"Parity violation:\n  path A: {reconciled_a}\n  path B: {reconciled_b}"
    )
