from __future__ import annotations

from app.services.confidence import score_record_confidence
from app.services.detail_extractor import build_detail_record


def test_score_record_confidence_distinguishes_authoritative_sources() -> None:
    record = {
        "title": "Widget Prime",
        "price": "19.99",
        "brand": "Acme",
        "image_url": "https://example.com/widget.jpg",
        "description": "A deterministic widget with enough descriptive detail to be trustworthy.",
        "availability": "in_stock",
        "variants": [{"sku": "W-1-BLK", "size": "M"}],
        "selected_variant": {"sku": "W-1-BLK", "size": "M"},
        "_field_sources": {
            "title": ["network_payload"],
            "price": ["network_payload"],
            "brand": ["adapter"],
            "image_url": ["network_payload"],
            "description": ["js_state"],
            "availability": ["network_payload"],
            "variants": ["network_payload"],
            "selected_variant": ["network_payload"],
        },
        "_source": "network_payload",
    }

    confidence = score_record_confidence(record, surface="ecommerce_detail")

    assert confidence["score"] >= 0.8
    assert confidence["source_tier"]["dominant"] == "authoritative"
    assert "network" in confidence["source_tier"]["reason"]


def test_score_record_confidence_penalizes_broken_detail_page() -> None:
    html = """
    <html>
      <head>
        <title>Product</title>
      </head>
      <body>
        <h1>Product</h1>
        <div>Price available now</div>
      </body>
    </html>
    """

    record = build_detail_record(
        html,
        "https://example.com/products/broken-widget",
        "ecommerce_detail",
        requested_fields=["description", "specifications"],
    )

    assert record["_confidence"]["score"] < 0.55
    assert record["_confidence"]["level"] == "low"
    assert record["_confidence"]["source_tier"]["dominant"] in {"dom", "text"}
    assert any(
        penalty["kind"] == "generic_title"
        for penalty in record["_confidence"]["penalties"]
    )


def test_score_record_confidence_marks_thin_job_sections_low() -> None:
    record = {
        "title": "Data Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "Short blurb",
        "responsibilities": "Build things",
        "qualifications": "Python",
        "apply_url": "https://example.com/apply",
        "_field_sources": {
            "title": ["dom_h1"],
            "company": ["dom_text"],
            "location": ["dom_text"],
            "description": ["dom_text"],
            "responsibilities": ["dom_text"],
            "qualifications": ["dom_text"],
            "apply_url": ["dom_selector"],
        },
        "_source": "dom_text",
    }

    confidence = score_record_confidence(
        record,
        surface="job_detail",
        requested_fields=["responsibilities", "qualifications"],
    )

    assert confidence["score"] < 0.55
    assert confidence["source_tier"]["dominant"] == "text"
    assert {
        penalty["field"]
        for penalty in confidence["penalties"]
        if penalty["kind"] == "thin_content"
    } >= {"description", "responsibilities", "qualifications"}
