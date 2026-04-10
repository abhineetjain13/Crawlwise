from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.pipeline.core import _reconcile_detail_candidate_values
from app.services.extract.service import _finalize_candidates


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

