from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from app.services.config.extraction_rules import SOURCE_TIERS, SURFACE_WEIGHTS
from app.services.field_policy import (
    get_surface_field_aliases,
    normalize_field_key,
    repair_target_fields_for_surface,
)

_GENERIC_TITLE_RE = re.compile(
    r"^(product|item|details?|job|career opportunity|untitled|listing)$",
    re.I,
)
_PRICEISH_RE = re.compile(r"\d")
_URLISH_RE = re.compile(r"^https?://", re.I)


def score_record_confidence(
    record: dict[str, Any],
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    normalized_surface = str(surface or "").strip().lower()
    weights = dict(SURFACE_WEIGHTS.get(normalized_surface) or {})
    if not weights:
        weights = {
            key: 1.0
            for key in ("title", "description", "image_url", "price", "company", "location")
        }

    total_weight = sum(weights.values()) or 1.0
    score = 0.0
    present_fields: list[str] = []
    missing_fields: list[str] = []
    penalties: list[dict[str, Any]] = []
    source_tier_weights: defaultdict[str, float] = defaultdict(float)
    field_sources = _normalized_field_sources(record)

    for field_name, weight in weights.items():
        value = record.get(field_name)
        if value in (None, "", [], {}):
            missing_fields.append(field_name)
            continue
        present_fields.append(field_name)
        source_quality, tier_name = _field_source_quality(
            field_sources.get(field_name),
            fallback_source=record.get("_source"),
        )
        penalty_items = _field_penalties(
            surface=normalized_surface,
            field_name=field_name,
            value=value,
            sources=field_sources.get(field_name),
        )
        penalty_total = min(
            sum(float(item.get("weight") or 0.0) for item in penalty_items),
            0.85,
        )
        score += weight * source_quality * (1.0 - penalty_total)
        source_tier_weights[tier_name] += weight
        penalties.extend(penalty_items)

    raw_requested = [
        " ".join(str(field_name or "").split()).strip()
        for field_name in list(requested_fields or [])
        if " ".join(str(field_name or "").split()).strip()
    ]
    requested = repair_target_fields_for_surface(normalized_surface, raw_requested)
    field_sources_by_key = {
        normalize_field_key(field_name): field_name
        for field_name in field_sources
        if normalize_field_key(field_name)
    }
    alias_map = get_surface_field_aliases(normalized_surface)
    requested_match_keys = _requested_match_keys(
        requested=requested,
        raw_requested=raw_requested,
        alias_map=alias_map,
    )
    requested_matches = [
        match
        for field_name in requested_match_keys
        if (match := _resolve_requested_field_match(
            record,
            field_name=field_name,
            alias_map=alias_map,
            field_sources_by_key=field_sources_by_key,
        )) is not None
    ]
    for field_name in requested:
        if _resolve_requested_field_match(
            record,
            field_name=field_name,
            alias_map=alias_map,
            field_sources_by_key=field_sources_by_key,
        ) is None and field_name not in missing_fields:
            missing_fields.append(field_name)
    requested_found_total = len(requested_matches)
    if requested:
        requested_bonus = 0.0
        for _requested_key, actual_field_name in requested_matches:
            source_quality, _ = _field_source_quality(
                field_sources.get(actual_field_name),
                fallback_source=record.get("_source"),
            )
            requested_bonus += source_quality / max(len(requested), 1)
        score += 0.15 * requested_bonus
        total_weight += 0.15

    normalized_score = round(max(0.0, min(score / total_weight, 1.0)), 4)
    source_reasoning = _source_reasoning(source_tier_weights)
    return {
        "score": normalized_score,
        "level": _confidence_level(normalized_score),
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "requested_fields_total": len(raw_requested) if raw_requested else len(requested),
        "requested_fields_found_best": requested_found_total,
        "penalties": [
            {
                "field": str(item["field"]),
                "kind": str(item["kind"]),
                "weight": round(float(item["weight"]), 3),
            }
            for item in penalties
        ],
        "source_tier": source_reasoning,
    }


def _requested_match_keys(
    *,
    requested: list[str],
    raw_requested: list[str],
    alias_map: dict[str, list[str]],
) -> list[str]:
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            alias_to_canonical.setdefault(normalized_canonical, normalized_canonical)
        for alias in aliases or []:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias:
                alias_to_canonical.setdefault(normalized_alias, normalized_canonical)
    ordered: list[str] = []
    seen: set[str] = set()
    for field_name in [*requested, *raw_requested]:
        normalized = normalize_field_key(field_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
        canonical_key = alias_to_canonical.get(normalized)
        if canonical_key and canonical_key not in seen:
            seen.add(canonical_key)
            ordered.append(canonical_key)
        for alias in alias_map.get(normalized) or []:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias and normalized_alias not in seen:
                seen.add(normalized_alias)
                ordered.append(normalized_alias)
    return ordered


def _resolve_requested_field_match(
    record: dict[str, Any],
    *,
    field_name: str,
    alias_map: dict[str, list[str]],
    field_sources_by_key: dict[str, str],
) -> tuple[str, str] | None:
    candidate_keys = [
        normalize_field_key(field_name),
        *[
            normalize_field_key(alias)
            for alias in list(alias_map.get(normalize_field_key(field_name)) or [])
        ],
    ]
    seen: set[str] = set()
    for candidate_key in candidate_keys:
        if not candidate_key or candidate_key in seen:
            continue
        seen.add(candidate_key)
        if record.get(candidate_key) not in (None, "", [], {}):
            return (field_name, candidate_key)
        source_field_name = field_sources_by_key.get(candidate_key)
        if source_field_name and record.get(source_field_name) not in (None, "", [], {}):
            return (field_name, source_field_name)
    return None


def _normalized_field_sources(record: dict[str, Any]) -> dict[str, list[str]]:
    raw = record.get("_field_sources")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for field_name, sources in raw.items():
        if not isinstance(sources, list):
            continue
        source_rows: list[str] = []
        for source in sources:
            normalized_source = str(source or "").strip()
            if normalized_source:
                source_rows.append(normalized_source)
        normalized[str(field_name)] = source_rows
    return normalized


def _field_source_quality(
    sources: list[str] | None,
    *,
    fallback_source: Any,
) -> tuple[float, str]:
    candidates = list(sources or [])
    fallback = str(fallback_source or "").strip()
    if fallback:
        candidates.append(fallback)
    best_quality = 0.58
    best_tier = "text"
    for source in candidates:
        tier, quality = SOURCE_TIERS.get(str(source), ("text", 0.58))
        if quality > best_quality:
            best_quality = quality
            best_tier = tier
    return best_quality, best_tier


def _field_penalties(
    *,
    surface: str,
    field_name: str,
    value: Any,
    sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    penalties: list[dict[str, Any]] = []
    text = _text_value(value)
    lowered = text.lower()
    normalized_sources = {str(source or "").strip() for source in list(sources or [])}

    if field_name == "title":
        if _GENERIC_TITLE_RE.match(text):
            penalties.append(
                {"field": field_name, "kind": "generic_title", "weight": 0.55}
            )
        elif "url_slug" in normalized_sources:
            penalties.append(
                {"field": field_name, "kind": "generic_title", "weight": 0.25}
            )
        elif len(text) < 4:
            penalties.append(
                {"field": field_name, "kind": "too_short", "weight": 0.35}
            )

    if field_name in {"description", "responsibilities", "qualifications"}:
        if len(text) < 40:
            penalties.append(
                {"field": field_name, "kind": "thin_content", "weight": 0.4}
            )

    if field_name in {"price", "salary"} and text and not _PRICEISH_RE.search(text):
        penalties.append(
            {"field": field_name, "kind": "non_numeric_value", "weight": 0.45}
        )

    if field_name in {"image_url", "apply_url", "url"} and text and not _URLISH_RE.match(text):
        penalties.append(
            {"field": field_name, "kind": "non_url_value", "weight": 0.45}
        )

    if surface == "ecommerce_detail" and field_name == "availability":
        if lowered in {"maybe", "unknown", "n/a"}:
            penalties.append(
                {"field": field_name, "kind": "ambiguous_availability", "weight": 0.35}
            )

    if surface == "job_detail" and field_name == "posted_date":
        if text and len(text) < 8:
            penalties.append(
                {"field": field_name, "kind": "partial_date", "weight": 0.25}
            )

    return penalties


def _source_reasoning(source_tier_weights: dict[str, float]) -> dict[str, Any]:
    total = sum(source_tier_weights.values()) or 1.0
    coverage = {
        tier: round(weight / total, 4)
        for tier, weight in sorted(
            source_tier_weights.items(),
            key=lambda item: (-item[1], item[0]),
        )
    }
    dominant = next(iter(coverage), "text")
    if dominant == "authoritative":
        reason = "coverage is primarily from adapter or network sources"
    elif dominant == "structured":
        reason = "coverage is primarily from JS state or structured metadata"
    elif dominant == "dom":
        reason = "coverage is primarily from DOM selectors and visible page structure"
    elif dominant == "llm":
        reason = "coverage depends on missing-field LLM enrichment"
    else:
        reason = "coverage depends mostly on raw DOM text heuristics"
    return {
        "dominant": dominant,
        "coverage": coverage,
        "reason": reason,
    }


def _text_value(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item or "").strip() for item in value if str(item or "").strip()).strip()
    if isinstance(value, dict):
        return " ".join(
            str(item or "").strip() for item in value.values() if str(item or "").strip()
        ).strip()
    return str(value or "").strip()


def _confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"
