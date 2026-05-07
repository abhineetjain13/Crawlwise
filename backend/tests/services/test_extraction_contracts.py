from __future__ import annotations

from app.services.domain_selector_health import (
    CRITICAL_FIELDS_BY_SURFACE,
    SelectorHealthSnapshot,
)
from app.services.extract.contracts import (
    CandidateSet,
    ExtractionResult,
    ExtractionWarning,
    RawCandidate,
    RuntimeMetrics,
)


def test_extraction_contracts_serialize_cleanly() -> None:
    candidate = RawCandidate(
        field_name="title",
        value="Cotton Shirt",
        source="dom",
        confidence=0.9,
    )
    result = ExtractionResult(
        surface="ecommerce_detail",
        page_url="https://example.com/p",
        record={"title": "Cotton Shirt"},
        candidates=CandidateSet(
            surface="ecommerce_detail",
            page_url="https://example.com/p",
            candidates=[candidate],
        ),
        warnings=[ExtractionWarning(code="missing_price", message="price missing")],
    )

    payload = result.model_dump(mode="json")

    assert payload["record"]["title"] == "Cotton Shirt"
    assert payload["candidates"]["candidates"][0]["source"] == "dom"


def test_selector_health_and_runtime_metrics_serialize_cleanly() -> None:
    snapshot = SelectorHealthSnapshot(
        domain="example.com",
        surface="ecommerce_detail",
        field_name="price",
        selector="[itemprop=price]",
        critical=True,
    )
    metrics = RuntimeMetrics(counters={"browser_fetch": 2})

    assert "price" in CRITICAL_FIELDS_BY_SURFACE["ecommerce_detail"]
    assert snapshot.model_dump(mode="json")["critical"] is True
    assert metrics.model_dump(mode="json") == {"counters": {"browser_fetch": 2}}
