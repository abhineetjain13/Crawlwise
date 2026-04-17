from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.extract.field_decision import FieldDecisionEngine

_EMPTY_VALUES = (None, "", [], {})
_STRONG_IDENTITY_FIELDS = ("job_id", "sku", "part_number", "id", "url", "apply_url")
_VARIANT_CONFLICT_FIELDS = ("price", "color", "size", "image_url", "brand")
_WHITESPACE_RE = re.compile(r"\s+")
_JOB_PRIMARY_SIGNAL_FIELDS = frozenset(
    {
        "company",
        "location",
        "salary",
        "job_id",
        "apply_url",
        "job_type",
        "posted_date",
        "department",
        "category",
        "description",
    }
)
_SOURCE_PREFERENCE = {
    "structured": 7,
    "comparison_table": 6,
    "next_flight": 5,
    "inline_array": 4,
    "json_ld": 3,
    "adapter": 2,
    "dom": 1,
}
_MERGE_ENGINE = FieldDecisionEngine()


def strong_identity_key(record: dict) -> str:
    for field_name in _STRONG_IDENTITY_FIELDS:
        value = str(record.get(field_name) or "").strip()
        if not value:
            continue
        if field_name in {"url", "apply_url"}:
            parsed = urlparse(value)
            normalized = parsed._replace(fragment="").geturl().lower()
            return f"url:{normalized}"
        if field_name in {"sku", "id"}:
            return f"item:{value.lower()}"
        return f"{field_name}:{value.lower()}"
    return ""


def choose_primary_record_set(
    record_sets: dict[str, list[dict]],
    *,
    surface: str,
) -> tuple[str, list[dict]]:
    best_label = ""
    best_records: list[dict] = []
    normalized_surface = str(surface or "").lower()
    is_job_surface = "job" in normalized_surface
    is_ecommerce_surface = "commerce" in normalized_surface
    best_score: tuple[int, ...] = (0, 0, 0, 0, 0)

    for label, records in record_sets.items():
        if not records:
            continue
        strong_count = sum(1 for record in records if strong_identity_key(record))
        title_count = sum(
            1 for record in records if record.get("title") not in _EMPTY_VALUES
        )
        detail_anchor_count = sum(
            1
            for record in records
            if record.get("url") not in _EMPTY_VALUES
            or record.get("apply_url") not in _EMPTY_VALUES
        )
        rich_count = sum(
            1
            for record in records
            if record.get("title") not in _EMPTY_VALUES
            and (
                record.get("url") not in _EMPTY_VALUES
                or record.get("apply_url") not in _EMPTY_VALUES
                or record.get("price") not in _EMPTY_VALUES
                or record.get("image_url") not in _EMPTY_VALUES
            )
        )
        field_richness = sum(
            len(
                [
                    key
                    for key, value in record.items()
                    if not str(key).startswith("_") and value not in _EMPTY_VALUES
                ]
            )
            for record in records
        )
        source_preference = int(_SOURCE_PREFERENCE.get(label, 0))
        if is_job_surface:
            surface_count = sum(
                1
                for record in records
                if any(
                    record.get(field_name) not in _EMPTY_VALUES
                    for field_name in _JOB_PRIMARY_SIGNAL_FIELDS
                )
            )
            score = (
                detail_anchor_count,
                surface_count,
                field_richness,
                rich_count,
                source_preference,
            )
        elif is_ecommerce_surface:
            surface_count = sum(
                1
                for record in records
                if record.get("price") not in _EMPTY_VALUES
                or record.get("image_url") not in _EMPTY_VALUES
            )
            score = (
                detail_anchor_count,
                rich_count,
                field_richness,
                surface_count,
                source_preference,
            )
        else:
            surface_count = sum(
                1
                for record in records
                if record.get("price") not in _EMPTY_VALUES
                or record.get("image_url") not in _EMPTY_VALUES
            )
            score = (
                detail_anchor_count or strong_count,
                rich_count,
                field_richness,
                surface_count,
                source_preference,
            )
        if score > best_score:
            best_label = label
            best_records = records
            best_score = score
    return best_label, best_records


def merge_record_sets_on_identity(
    primary_records: list[dict],
    supplemental_sets: list[list[dict]],
) -> list[dict]:
    merged = [dict(record) for record in primary_records]
    
    def _build_by_key(records):
        by_key = {}
        for index, record in enumerate(records):
            for field_name in _STRONG_IDENTITY_FIELDS:
                value = str(record.get(field_name) or "").strip()
                if not value:
                    continue
                if field_name in {"url", "apply_url"}:
                    parsed = urlparse(value)
                    normalized = parsed._replace(fragment="").geturl().lower()
                    by_key[f"url:{normalized}"] = index
                elif field_name in {"sku", "id"}:
                    by_key[f"item:{value.lower()}"] = index
                else:
                    by_key[f"{field_name}:{value.lower()}"] = index
        return by_key

    by_key = _build_by_key(merged)
    if not by_key:
        return merged
    title_index = _build_title_index(merged)

    for records in supplemental_sets:
        for record in records:
            index = None
            for field_name in _STRONG_IDENTITY_FIELDS:
                value = str(record.get(field_name) or "").strip()
                if not value:
                    continue
                if field_name in {"url", "apply_url"}:
                    parsed = urlparse(value)
                    normalized = parsed._replace(fragment="").geturl().lower()
                    key = f"url:{normalized}"
                elif field_name in {"sku", "id"}:
                    key = f"item:{value.lower()}"
                else:
                    key = f"{field_name}:{value.lower()}"
                    
                if key in by_key:
                    index = by_key[key]
                    break
            
            if index is None:
                fallback_index = _fallback_title_backfill_index(merged, title_index, record)
                if fallback_index is None:
                    continue
                merged[fallback_index] = _backfill_link_fields(
                    merged[fallback_index], record
                )
                for field_name in _STRONG_IDENTITY_FIELDS:
                    val = str(merged[fallback_index].get(field_name) or "").strip()
                    if val:
                        if field_name in {"url", "apply_url"}:
                            parsed = urlparse(val)
                            norm = parsed._replace(fragment="").geturl().lower()
                            by_key[f"url:{norm}"] = fallback_index
                        elif field_name in {"sku", "id"}:
                            by_key[f"item:{val.lower()}"] = fallback_index
                        else:
                            by_key[f"{field_name}:{val.lower()}"] = fallback_index
                continue
            merged[index] = merge_listing_record(merged[index], record)
            for field_name in _STRONG_IDENTITY_FIELDS:
                val = str(merged[index].get(field_name) or "").strip()
                if val:
                    if field_name in {"url", "apply_url"}:
                        parsed = urlparse(val)
                        norm = parsed._replace(fragment="").geturl().lower()
                        by_key[f"url:{norm}"] = index
                    elif field_name in {"sku", "id"}:
                        by_key[f"item:{val.lower()}"] = index
                    else:
                        by_key[f"{field_name}:{val.lower()}"] = index
    return merged


def merge_listing_record(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for key, value in incoming.items():
        if key.startswith("_"):
            if key == "_source":
                merged["_source"] = _merge_source_labels(merged.get("_source"), value)
            elif key not in merged and value not in _EMPTY_VALUES:
                merged[key] = value
            continue
        
        # FIX: Prevent discount_amount and discount_percentage from coexisting
        # If we're adding discount_percentage, remove discount_amount
        if key == "discount_percentage" and value not in _EMPTY_VALUES:
            merged.pop("discount_amount", None)
            merged[key] = value
            continue
        # If we're adding discount_amount but discount_percentage already exists, skip it
        if key == "discount_amount" and merged.get("discount_percentage") not in _EMPTY_VALUES:
            continue

        decision = _MERGE_ENGINE.decide_merge(
            key,
            merged.get(key),
            value,
            candidate_source="listing_identity",
        )
        merged[key] = decision.value
    return merged


def _merge_source_labels(*values: object) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").replace("+", "|").split("|"):
            label = part.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
    return " + ".join(labels)


def _normalized_title_key(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text)


def _build_title_index(records: list[dict]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for idx, record in enumerate(records):
        key = _normalized_title_key(record.get("title"))
        if not key:
            continue
        index.setdefault(key, []).append(idx)
    return index


def _fallback_title_backfill_index(
    merged_records: list[dict],
    title_index: dict[str, list[int]],
    incoming: dict,
) -> int | None:
    incoming_link = str(incoming.get("url") or incoming.get("apply_url") or "").strip()
    if not incoming_link:
        return None
    title_key = _normalized_title_key(incoming.get("title"))
    if not title_key:
        return None
    candidates = title_index.get(title_key) or []
    if len(candidates) != 1:
        return None
    idx = candidates[0]
    base = merged_records[idx]
    if _has_strong_identity_conflict(base, incoming):
        return None
    base_has_link = bool(str(base.get("url") or base.get("apply_url") or "").strip())
    if base_has_link:
        return None
    return idx


def _has_strong_identity_conflict(base: dict, incoming: dict) -> bool:
    # 1. Check strong identifiers first
    for field_name in _STRONG_IDENTITY_FIELDS:
        base_value = _normalized_identity_value(field_name, base.get(field_name))
        incoming_value = _normalized_identity_value(field_name, incoming.get(field_name))
        if base_value and incoming_value and base_value != incoming_value:
            return True
            
    # FIX: Prevent merging distinct product variants (colors, sizes, prices) 
    # into a single record just because they share the same title.
    for variant_field in _VARIANT_CONFLICT_FIELDS:
        base_value = _normalized_identity_value(variant_field, base.get(variant_field))
        incoming_value = _normalized_identity_value(variant_field, incoming.get(variant_field))
        if base_value and incoming_value and base_value != incoming_value:
            return True
            
    return False


def _normalized_identity_value(field_name: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if field_name in {"url", "apply_url"}:
        parsed = urlparse(text)
        return parsed._replace(fragment="").geturl().lower()
    return text.lower()


def _backfill_link_fields(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    if not str(merged.get("url") or "").strip() and str(incoming.get("url") or "").strip():
        merged["url"] = incoming["url"]
    if not str(merged.get("apply_url") or "").strip() and str(
        incoming.get("apply_url") or ""
    ).strip():
        merged["apply_url"] = incoming["apply_url"]
    if "_source" in incoming:
        merged["_source"] = _merge_source_labels(merged.get("_source"), incoming.get("_source"))
    return merged
