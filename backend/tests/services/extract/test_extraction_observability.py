from __future__ import annotations

from unittest.mock import patch

from app.services.extract.service import extract_candidates
from tests.support import manifest as _manifest
from tests.support import run_extract_candidates


def _extract(
    *,
    url: str,
    surface: str,
    html: str,
    manifest: dict | None = None,
    additional_fields: list[str] | None = None,
    resolved_fields: list[str] | None = None,
):
    return run_extract_candidates(
        extract_candidates,
        url=url,
        surface=surface,
        html=html,
        manifest_data=manifest,
        additional_fields=additional_fields or [],
        resolved_fields=resolved_fields,
    )


def test_extraction_audit_records_empty_and_populated_source_attempts() -> None:
    html = "<html><body><h1>DOM Title</h1></body></html>"

    with patch("app.services.extract.service.get_selector_defaults", return_value=[]):
        _, source_trace = _extract(
            url="https://example.com/product/widget",
            surface="ecommerce_detail",
            html=html,
            resolved_fields=["title"],
        )

    title_audit = source_trace["extraction_audit"]["title"]
    source_statuses = {
        entry["source"]: entry["status"] for entry in title_audit["sources"]
    }

    assert title_audit["winner"]["source"] == "dom"
    assert title_audit["final_output"]["value_preview"] == "DOM Title"
    assert source_statuses["adapter"] == "empty"
    assert source_statuses["json_ld"] == "empty"
    assert source_statuses["dom_meta"] == "produced_candidates"
