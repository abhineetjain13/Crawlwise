from __future__ import annotations

from app.services.extract.service import _finalize_candidates
from app.services.pipeline.core import _reconcile_detail_candidate_values
from bs4 import BeautifulSoup


def test_finalize_candidates_prefers_higher_trust_source_over_first_row_bias() -> None:
    candidates = {
        "title": [
            {"value": "Cookie Manager Banner", "source": "selector"},
            {"value": "Arc'teryx Beta LT Jacket", "source": "json_ld"},
        ]
    }

    final_candidates, _trace = _finalize_candidates(
        candidates=candidates,
        surface="ecommerce_detail",
        url="https://example.com/products/beta-lt",
        semantic={},
        target_fields={"title"},
        canonical_target_fields={"title"},
        next_data=None,
        hydrated_states=[],
        embedded_json=[],
        network_payloads=[],
        soup=BeautifulSoup("<html><body></body></html>", "html.parser"),
    )

    # json_ld (rank 9) should win over selector (rank 4).
    assert final_candidates["title"][0]["value"] == "Arc'teryx Beta LT Jacket"


def test_reconcile_detail_candidate_values_prefers_better_downstream_brand() -> None:
    candidates = {
        "brand": [
            {"value": "House Brand", "source": "selector"},
            {"value": "Nike", "source": "json_ld"},
        ]
    }

    reconciled, _reconciliation = _reconcile_detail_candidate_values(
        candidates,
        allowed_fields={"brand"},
        url="https://example.com/products/shoe-1",
    )

    # json_ld (rank 9) should win over selector (rank 4).
    assert reconciled["brand"] == "Nike"


def test_finalize_candidates_prefers_json_ld_over_datalayer_for_risky_fields() -> None:
    candidates = {
        "category": [
            {"value": "page", "source": "datalayer"},
            {"value": "Mirrorless Cameras", "source": "json_ld"},
        ],
        "availability": [
            {"value": "Add to cart", "source": "datalayer"},
            {"value": "InStock", "source": "json_ld"},
        ],
    }

    final_candidates, _trace = _finalize_candidates(
        candidates=candidates,
        surface="ecommerce_detail",
        url="https://example.com/products/camera-1",
        semantic={},
        target_fields={"category", "availability"},
        canonical_target_fields={"category", "availability"},
        next_data=None,
        hydrated_states=[],
        embedded_json=[],
        network_payloads=[],
        soup=BeautifulSoup("<html><body></body></html>", "html.parser"),
    )

    assert final_candidates["category"][0]["value"] == "Mirrorless Cameras"
    assert final_candidates["availability"][0]["value"] == "InStock"


def test_reconcile_detail_candidate_values_applies_final_detail_sanitizer() -> None:
    candidates = {
        "brand": [
            {"value": "Home > Privacy Policy > Nike", "source": "dom"},
            {"value": "Nike", "source": "selector"},
        ],
        "title": [
            {"value": "Cookie Preferences", "source": "embedded_json"},
            {"value": "Arc'teryx Beta LT Jacket", "source": "json_ld"},
        ],
    }

    reconciled, reconciliation = _reconcile_detail_candidate_values(
        candidates,
        allowed_fields={"brand", "title"},
        url="https://example.com/products/jacket-1",
    )

    assert reconciled["brand"] == "Nike"
    assert reconciled["title"] == "Arc'teryx Beta LT Jacket"
    assert reconciliation["brand"]["rejected"][0]["reason"] in {
        "validation_rejected",
        "field_pollution_rule",
        "breadcrumb_like_brand",
        "empty_after_normalization",
    }
    assert reconciliation["title"]["rejected"][0]["reason"] in {
        "empty_after_normalization",
        "field_pollution_rule",
        "detail_field_noise",
    }

