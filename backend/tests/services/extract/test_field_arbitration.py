from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.pipeline.core import _reconcile_detail_candidate_values
from app.services.extract.service import _finalize_candidates


def test_finalize_candidates_prefers_higher_trust_source_over_first_row_bias() -> None:
    candidates = {
        "title": [
            {"value": "Cookie Manager Banner", "source": "datalayer"},
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

    # Phase-0 expectation: json_ld value should win over noisy datalayer candidate.
    assert final_candidates["title"][0]["value"] == "Arc'teryx Beta LT Jacket"


def test_reconcile_detail_candidate_values_prefers_better_downstream_brand() -> None:
    candidates = {
        "brand": [
            {"value": "House Brand", "source": "datalayer"},
            {"value": "Nike", "source": "json_ld"},
        ]
    }

    reconciled, _reconciliation = _reconcile_detail_candidate_values(
        candidates,
        allowed_fields={"brand"},
        url="https://example.com/products/shoe-1",
    )

    # Phase-0 expectation: downstream higher-quality candidate should override sticky early source.
    assert reconciled["brand"] == "Nike"

