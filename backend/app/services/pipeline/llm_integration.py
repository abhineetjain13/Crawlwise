"""LLM integration functions for field extraction and review."""

from __future__ import annotations

from app.services.extract import coerce_field_candidate_value, parse_page_sources

from .field_normalization import (
    _normalize_review_value,
    _passes_detail_quality_gate,
    _review_values_equal,
)
from .review_helpers import _merge_review_bucket_entries
from .utils import _clean_candidate_text, _compact_dict
from .verdict import _review_bucket_fingerprint

LLM_CLEAN_CANDIDATE_TEXT_LIMIT = 2000


def _apply_llm_suggestions_to_candidate_values(
    candidate_values: dict[str, object],
    *,
    allowed_fields: set[str],
    source_trace: dict,
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Apply LLM cleanup suggestions to candidate values."""
    suggestions = source_trace.get("llm_cleanup_suggestions")
    if not isinstance(suggestions, dict):
        return candidate_values, {}

    trace_candidates = source_trace.setdefault("candidates", {})
    promoted: dict[str, dict[str, object]] = {}
    for field_name, raw_suggestion in suggestions.items():
        normalized_field = str(field_name or "").strip()
        if not normalized_field or normalized_field not in allowed_fields:
            continue
        if candidate_values.get(normalized_field) not in (None, "", [], {}):
            continue
        if not isinstance(raw_suggestion, dict):
            continue

        suggested_value = raw_suggestion.get("suggested_value")
        normalized_value = coerce_field_candidate_value(
            normalized_field, suggested_value, base_url=url
        )
        if normalized_value in (None, "", [], {}):
            continue
        if not _passes_detail_quality_gate(normalized_field, normalized_value):
            continue

        source = (
            str(raw_suggestion.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        )
        note = _clean_candidate_text(
            raw_suggestion.get("note") or raw_suggestion.get("reason"), limit=280
        )
        candidate_values[normalized_field] = normalized_value
        promoted[normalized_field] = _compact_dict(
            {
                "value": normalized_value,
                "source": source,
                "note": note or None,
            }
        )

        existing_rows = trace_candidates.setdefault(normalized_field, [])
        normalized_fingerprint = _review_bucket_fingerprint(normalized_value)
        if not any(
            isinstance(row, dict)
            and str(row.get("source") or "").strip() == source
            and _review_bucket_fingerprint(row.get("value")) == normalized_fingerprint
            for row in existing_rows
        ):
            existing_rows.insert(
                0,
                _compact_dict(
                    {
                        "value": normalized_value,
                        "source": source,
                        "status": "auto_promoted",
                        "note": note or None,
                    }
                ),
            )

        updated_suggestion = dict(raw_suggestion)
        updated_suggestion["status"] = "auto_promoted"
        updated_suggestion["accepted_value"] = normalized_value
        suggestions[normalized_field] = _compact_dict(updated_suggestion)

    if promoted:
        source_trace["llm_cleanup_suggestions"] = suggestions
        source_trace["llm_promoted_fields"] = promoted
    return candidate_values, promoted


def _build_llm_candidate_evidence(
    trace_candidates: dict, preview_record: dict
) -> dict[str, list[dict]]:
    """Build evidence for LLM review from trace candidates and preview record."""
    evidence: dict[str, list[dict]] = {}
    field_names = sorted(
        {
            str(field_name or "").strip()
            for field_name in [*trace_candidates.keys(), *preview_record.keys()]
            if str(field_name or "").strip() and not str(field_name).startswith("_")
        }
    )
    for field_name in field_names:
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        current_value = _clean_candidate_text(preview_record.get(field_name))
        if current_value:
            rows.append(
                {
                    "value": current_value,
                    "source": "current_output",
                }
            )
            seen.add(("current_output", current_value))
        for row in trace_candidates.get(field_name, []):
            if not isinstance(row, dict):
                continue
            value = _clean_candidate_text(
                row.get("value")
                if row.get("value") not in (None, "", [], {})
                else row.get("sample_value")
            )
            if not value:
                continue
            source = str(row.get("source") or "candidate").strip() or "candidate"
            key = (source, value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                _compact_dict(
                    {
                        "value": value,
                        "source": source,
                        "xpath": str(row.get("xpath") or "").strip() or None,
                        "css_selector": str(row.get("css_selector") or "").strip()
                        or None,
                        "regex": str(row.get("regex") or "").strip() or None,
                        "selector_used": str(row.get("selector_used") or "").strip()
                        or None,
                    }
                )
            )
            if len(rows) >= 8:
                break
        if rows:
            evidence[field_name] = rows
    return evidence


def _build_llm_discovered_sources(
    source_trace: dict,
    *,
    html: str,
    xhr_payloads: list[dict],
    target_fields: list[str] | None = None,
    page_sources: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build discovered sources snapshot for LLM."""
    page_sources = (
        page_sources
        if isinstance(page_sources, dict) and page_sources
        else parse_page_sources(html)
    )
    semantic = (
        source_trace.get("semantic")
        if isinstance(source_trace.get("semantic"), dict)
        else {}
    )
    relevant_fields = {field for field in (target_fields or []) if field}
    semantic_sections = (
        semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    )
    semantic_specs = (
        semantic.get("specifications")
        if isinstance(semantic.get("specifications"), dict)
        else {}
    )
    semantic_promoted = (
        semantic.get("promoted_fields")
        if isinstance(semantic.get("promoted_fields"), dict)
        else {}
    )
    manifest_snapshot = _compact_dict(
        {
            "next_data": _snapshot_for_llm(
                page_sources.get("next_data"), max_items=150, text_limit=2000
            ),
            "hydrated_states": _snapshot_for_llm(
                page_sources.get("hydrated_states"), max_items=150, text_limit=2000
            ),
            "embedded_json": _snapshot_for_llm(
                page_sources.get("embedded_json"), max_items=150, text_limit=2000
            ),
            "json_ld": _snapshot_for_llm(
                page_sources.get("json_ld"), max_items=150, text_limit=2000
            ),
            "microdata": _snapshot_for_llm(
                page_sources.get("microdata"), max_items=150, text_limit=2000
            ),
            "network_payloads": _snapshot_for_llm(
                [
                    _compact_dict(
                        {
                            "url": payload.get("url"),
                            "status": payload.get("status"),
                            "body": payload.get("body"),
                        }
                    )
                    for payload in xhr_payloads[:2]
                    if isinstance(payload, dict)
                ],
                max_items=150,
                text_limit=2000,
            ),
            "tables": _snapshot_for_llm(
                page_sources.get("tables"), max_items=150, text_limit=2000
            ),
        }
    )
    semantic_snapshot = _compact_dict(
        {
            "sections": _snapshot_for_llm(
                {
                    key: value
                    for key, value in semantic_sections.items()
                    if not relevant_fields or key in relevant_fields
                },
                text_limit=2000,
            ),
            "specifications": _snapshot_for_llm(
                {
                    key: value
                    for key, value in semantic_specs.items()
                    if not relevant_fields or key in relevant_fields
                },
                text_limit=2000,
            ),
            "promoted_fields": _snapshot_for_llm(
                {
                    key: value
                    for key, value in semantic_promoted.items()
                    if not relevant_fields or key in relevant_fields
                },
                text_limit=2000,
            ),
        }
    )
    return _compact_dict(
        {
            "semantic": semantic_snapshot,
            "manifest": manifest_snapshot,
        }
    )


def _snapshot_for_llm(
    value: object,
    *,
    depth: int = 0,
    max_depth: int = 8,
    max_items: int = 150,
    text_limit: int = 2000,
) -> object:
    """Create a size-limited snapshot of data for LLM consumption."""
    if value in (None, "", [], {}):
        return None
    if depth >= max_depth:
        return _clean_candidate_text(value, limit=text_limit)
    if isinstance(value, dict):
        snapshot: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                break
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            nested = _snapshot_for_llm(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
            if nested not in (None, "", [], {}):
                snapshot[normalized_key] = nested
        return snapshot or None
    if isinstance(value, list):
        rows: list[object] = []
        for item in value[:max_items]:
            nested = _snapshot_for_llm(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
            if nested not in (None, "", [], {}):
                rows.append(nested)
        return rows or None
    return _clean_candidate_text(value, limit=text_limit)


def _normalize_llm_cleanup_review(
    field_name: object, raw_review: object, *, current_value: object
) -> dict | None:
    """Normalize an LLM cleanup review item."""
    normalized_field = str(field_name or "").strip()
    if not normalized_field or normalized_field.startswith("_"):
        return None
    if isinstance(raw_review, dict):
        suggested_value = _normalize_review_value(
            raw_review.get("suggested_value")
            if raw_review.get("suggested_value") not in (None, "", [], {})
            else raw_review.get("value"),
        )
        source = str(raw_review.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        note = _clean_candidate_text(
            raw_review.get("note") or raw_review.get("reason"), limit=280
        )
        supporting_sources = [
            str(item).strip()
            for item in (raw_review.get("supporting_sources") or [])
            if str(item).strip()
        ]
    else:
        suggested_value = _normalize_review_value(raw_review)
        source = "llm_cleanup"
        note = ""
        supporting_sources = []
    if not suggested_value:
        return None
    if _review_values_equal(current_value, suggested_value):
        return None
    return _compact_dict(
        {
            "field_name": normalized_field,
            "suggested_value": suggested_value,
            "source": source,
            "supporting_sources": supporting_sources or None,
            "note": note or None,
            "status": "pending_review",
        }
    )


def _split_llm_cleanup_payload(
    payload: object,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Split LLM cleanup payload into canonical and review bucket."""
    if not isinstance(payload, dict):
        return {}, []
    if "canonical" not in payload and "review_bucket" not in payload:
        canonical = {
            str(key).strip(): value
            for key, value in payload.items()
            if str(key).strip()
        }
        return canonical, []
    raw_canonical = payload.get("canonical")
    canonical = raw_canonical if isinstance(raw_canonical, dict) else {}
    raw_review_bucket = payload.get("review_bucket")
    review_bucket: list[dict[str, object]] = []
    if isinstance(raw_review_bucket, list):
        for row in raw_review_bucket:
            normalized = _normalize_llm_review_bucket_item(row)
            if normalized is not None:
                review_bucket.append(normalized)
    return canonical, _merge_review_bucket_entries(review_bucket)


def _normalize_llm_review_bucket_item(value: object) -> dict[str, object] | None:
    """Normalize a single LLM review bucket item."""
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if not key or key.startswith("_"):
        return None
    normalized_value = _normalize_review_value(value.get("value"))
    if normalized_value is None:
        return None
    return _compact_dict(
        {
            "key": key,
            "value": normalized_value,
            "source": str(value.get("source") or "llm_cleanup").strip()
            or "llm_cleanup",
        }
    )


def _select_llm_review_candidates(
    candidate_evidence: dict[str, list[dict]],
    preview_record: dict,
    target_fields: list[str],
) -> dict[str, list[dict]]:
    """Select candidates that need LLM review."""
    selected: dict[str, list[dict]] = {}
    for field_name in target_fields:
        rows = candidate_evidence.get(field_name) or []
        if not rows:
            continue
        current_value = _clean_candidate_text(preview_record.get(field_name))
        distinct_values = {
            _clean_candidate_text(row.get("value"))
            for row in rows
            if _clean_candidate_text(row.get("value"))
        }
        source_labels = {str(row.get("source") or "").strip() for row in rows}
        if (
            not current_value
            and len(distinct_values) <= 1
            and "llm_xpath" not in source_labels
        ):
            continue
        if (
            not current_value
            or len(distinct_values) > 1
            or "llm_xpath" in source_labels
        ):
            selected[field_name] = rows[:6]
    return selected
