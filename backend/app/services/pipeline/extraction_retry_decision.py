from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.acquisition.acquirer import AcquisitionResult, PageEvidence
from app.services.acquisition.browser_readiness import analyze_html
from app.services.config.extraction_rules import (
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_IDENTITY_FIELDS,
    DETAIL_SHELL_FRAMEWORK_TOKENS,
    DETAIL_SHELL_PRODUCT_DATA_TOKENS,
    DETAIL_SHELL_STATE_TOKENS,
    JS_REQUIRED_PLACEHOLDER_PHRASES,
    PRICE_FIELDS,
    VARIANT_FIELDS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.shared_variant_logic import variant_dom_cues_present
from app.services.field_policy import (
    browser_retry_target_fields_for_surface,
    repair_target_fields_for_surface,
)
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
        # Even if we see static evidence, if we got 0 records, we might still want to try browser
        # but only if the static evidence is "weak" (e.g. just a title or just generic price markers)
        # For now, we keep this as is but ensure _empty_detail_extraction_has_static_evidence is strict.
        return {"should_retry": False, "reason": "static_detail_extractable"}
    return {"should_retry": True, "reason": "empty_non_browser_html"}


def records_missing_repair_fields(
    *,
    surface: str,
    requested_fields: list[str] | None,
    records: list[dict[str, object]],
) -> list[str]:
    targets = repair_target_fields_for_surface(surface, requested_fields or [])
    missing: list[str] = []
    for field_name in targets:
        if records and all(
            isinstance(record, dict)
            and record.get(field_name) not in (None, "", [], {})
            for record in records
        ):
            continue
        missing.append(field_name)
    return missing


def low_quality_extraction_browser_retry_decision(
    acquisition_result: AcquisitionResult,
    records: list[dict[str, object]],
    *,
    surface: str,
    requested_fields: list[str] | None,
) -> dict[str, object]:
    if "detail" not in str(surface or "").strip().lower():
        return {"should_retry": False, "reason": "not_detail_surface"}
    method = str(getattr(acquisition_result, "method", "") or "").strip().lower()
    if method == "browser":
        return {"should_retry": False, "reason": "browser_already_attempted"}
    if method not in set(crawler_runtime_settings.low_quality_browser_retry_methods):
        return {"should_retry": False, "reason": "method_not_retryable"}
    if not records:
        return {"should_retry": False, "reason": "no_records"}
    if effective_blocked(acquisition_result):
        return {"should_retry": False, "reason": "blocked"}
    missing_fields = records_missing_repair_fields(
        surface=surface,
        requested_fields=requested_fields,
        records=records,
    )
    if not missing_fields:
        return {"should_retry": False, "reason": "repair_fields_complete"}
    retry_targets = set(
        browser_retry_target_fields_for_surface(surface, requested_fields or [])
    )
    retry_missing_fields = [
        field_name for field_name in missing_fields if field_name in retry_targets
    ]
    if not retry_missing_fields:
        return {
            "should_retry": False,
            "reason": "missing_fields_not_browser_retry_targets",
            "missing_fields": missing_fields,
        }
    if not _low_quality_detail_html_suggests_browser_retry(
        acquisition_result,
        surface=surface,
        missing_fields=retry_missing_fields,
    ):
        return {
            "should_retry": False,
            "reason": "no_browser_recovery_evidence",
            "missing_fields": retry_missing_fields,
            "all_missing_fields": missing_fields,
        }
    return {
        "should_retry": True,
        "reason": "missing_high_value_fields",
        "missing_fields": retry_missing_fields,
        "all_missing_fields": missing_fields,
    }


def annotate_field_repair(
    records: list[dict[str, object]],
    *,
    surface: str,
    requested_fields: list[str] | None,
    llm_enabled: bool,
    action: str,
    reason: str | None,
) -> None:
    if "detail" not in str(surface or "").strip().lower() or not records:
        return
    targets = repair_target_fields_for_surface(surface, requested_fields or [])
    if not targets:
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        missing = [
            field_name
            for field_name in targets
            if record.get(field_name) in (None, "", [], {})
        ]
        if not missing:
            record.pop("_field_repair", None)
            continue
        record["_field_repair"] = {
            "targets": targets,
            "missing_fields": missing,
            "action": action,
            "reason": reason,
            "llm_enabled": bool(llm_enabled),
        }


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
        list(raw_extractable_fields) if isinstance(raw_extractable_fields, list) else []
    )
    extractable_fields = {
        str(field_name).strip()
        for field_name in extractable_field_values
        if str(field_name).strip()
    }
    raw_matched_requested_fields = extractability.get("matched_requested_fields")
    matched_requested_values = (
        list(raw_matched_requested_fields)
        if isinstance(raw_matched_requested_fields, list)
        else []
    )
    matched_requested_fields = {
        str(field_name).strip()
        for field_name in matched_requested_values
        if str(field_name).strip()
    }
    # If we have matched requested fields, that's strong evidence
    if matched_requested_fields:
        return True

    # If static HTML exposes configured price and identity fields, browser retry is a waste.
    has_price = bool(
        extractable_fields & set(PRICE_FIELDS)
    ) or _html_has_configured_detail_price(soup)
    has_identity = bool(set(DETAIL_IDENTITY_FIELDS) & extractable_fields)

    return bool(has_price and has_identity)


def _html_has_configured_detail_price(soup: BeautifulSoup) -> bool:
    for selector in DETAIL_CURRENT_PRICE_SELECTORS:
        for node in soup.select(str(selector or "")):
            aria_label = node.get("aria-label") if hasattr(node, "get") else ""
            if str(aria_label or "").strip():
                return True
            if str(node.get_text(" ", strip=True) or "").strip():
                return True
    return False


def _low_quality_detail_html_suggests_browser_retry(
    acquisition_result: AcquisitionResult,
    *,
    surface: str,
    missing_fields: list[str],
) -> bool:
    html = str(getattr(acquisition_result, "html", "") or "")
    if not html.strip():
        return True
    analysis = analyze_html(html)
    soup = analysis.soup
    if _missing_fields_have_static_html_evidence(
        soup,
        surface=surface,
        missing_fields=missing_fields,
    ):
        return False
    if _html_looks_like_js_required_placeholder(
        analysis.title_text, analysis.visible_text, soup
    ):
        return True
    lowered_html = analysis.lowered_html
    if any(token in lowered_html for token in DETAIL_SHELL_STATE_TOKENS):
        return True
    return any(
        token in lowered_html for token in DETAIL_SHELL_FRAMEWORK_TOKENS
    ) and any(token in lowered_html for token in DETAIL_SHELL_PRODUCT_DATA_TOKENS)


def _missing_fields_have_static_html_evidence(
    soup: BeautifulSoup,
    *,
    surface: str,
    missing_fields: list[str],
) -> bool:
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=missing_fields,
        selector_rules=[],
    )
    raw_matched_requested = extractability.get("matched_requested_fields")
    matched_requested_values = (
        list(raw_matched_requested) if isinstance(raw_matched_requested, list) else []
    )
    matched_requested = {
        str(field_name).strip()
        for field_name in matched_requested_values
        if str(field_name).strip()
    }
    if matched_requested:
        return True
    normalized_missing = {str(field_name).strip() for field_name in missing_fields}
    if normalized_missing & set(PRICE_FIELDS) and _html_has_configured_detail_price(
        soup
    ):
        return True
    if normalized_missing & set(VARIANT_FIELDS) and variant_dom_cues_present(soup):
        return True
    return False


def _html_looks_like_js_required_placeholder(
    title_text: str,
    visible_text: str,
    soup: BeautifulSoup,
) -> bool:
    combined_text = " ".join(f"{title_text} {visible_text}".split()).strip().lower()
    if not combined_text:
        return False
    if not any(phrase in combined_text for phrase in JS_REQUIRED_PLACEHOLDER_PHRASES):
        return False
    return bool(soup.find("noscript")) or len(visible_text) <= 400
