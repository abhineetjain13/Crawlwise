from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.acquisition.acquirer import AcquisitionResult, PageEvidence
from app.services.config.extraction_rules import DETAIL_CURRENT_PRICE_SELECTORS, PRICE_FIELDS
from app.services.field_value_dom import requested_content_extractability
from app.services.pipeline.runtime_helpers import effective_blocked


def empty_extraction_browser_retry_decision(
    acquisition_result: AcquisitionResult,
    records: list[dict[str, object]],
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if records:
        return {"should_retry": False, "reason": "records_present"}
    evidence = PageEvidence.from_acquisition_result(acquisition_result)
    if evidence.browser_attempted:
        return {
            "should_retry": False,
            "reason": "browser_already_attempted",
            "browser_outcome": evidence.browser_outcome or None,
        }
    if effective_blocked(acquisition_result):
        return {"should_retry": False, "reason": "blocked"}
    content_type = str(getattr(acquisition_result, "content_type", "") or "").lower()
    if "json" in content_type:
        return {"should_retry": False, "reason": "json_response"}
    if _empty_detail_extraction_has_static_evidence(
        acquisition_result,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    ):
        return {"should_retry": False, "reason": "static_detail_extractable"}
    return {"should_retry": True, "reason": "empty_non_browser_html"}


def _empty_detail_extraction_has_static_evidence(
    acquisition_result: AcquisitionResult,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None,
) -> bool:
    if "detail" not in str(surface or "").strip().lower():
        return False
    html = str(getattr(acquisition_result, "html", "") or "")
    if not html.strip():
        return False
    soup = BeautifulSoup(html, "html.parser")
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    )
    raw_extractable_fields = extractability.get("extractable_fields")
    extractable_field_values = (
        raw_extractable_fields if isinstance(raw_extractable_fields, list) else []
    )
    extractable_fields = {
        str(field_name).strip()
        for field_name in extractable_field_values
        if str(field_name).strip()
    }
    raw_matched_requested_fields = extractability.get("matched_requested_fields")
    matched_requested_values = (
        raw_matched_requested_fields
        if isinstance(raw_matched_requested_fields, list)
        else []
    )
    matched_requested_fields = {
        str(field_name).strip()
        for field_name in matched_requested_values
        if str(field_name).strip()
    }
    return bool(
        matched_requested_fields
        or extractable_fields & set(PRICE_FIELDS)
        or _html_has_configured_detail_price(soup)
    )


def _html_has_configured_detail_price(soup: BeautifulSoup) -> bool:
    for selector in DETAIL_CURRENT_PRICE_SELECTORS:
        for node in soup.select(str(selector or "")):
            aria_label = node.get("aria-label") if hasattr(node, "get") else ""
            if str(aria_label or "").strip():
                return True
            if str(node.get_text(" ", strip=True) or "").strip():
                return True
    return False
