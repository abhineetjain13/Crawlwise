from __future__ import annotations

import json
from typing import Any

from app.services.field_policy import normalize_field_key, normalize_requested_field

from app.services.field_value_core import (
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    LONG_TEXT_FIELDS,
    absolute_url,
    coerce_field_value,
    coerce_text,
    extract_urls,
    text_or_none,
)
from app.services.extract.shared_variant_logic import resolve_variants
from app.services.normalizers import normalize_decimal_price


def candidate_fingerprint(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def add_candidate(
    candidates: dict[str, list[object]],
    field_name: str,
    value: object,
) -> None:
    if value in (None, "", [], {}):
        return
    bucket = candidates.setdefault(field_name, [])
    values = list(value) if field_name in STRUCTURED_MULTI_FIELDS and isinstance(value, list) else [value]
    seen = {candidate_fingerprint(existing) for existing in bucket}
    for item in values:
        if item in (None, "", [], {}):
            continue
        fingerprint = candidate_fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bucket.append(item)


def _structured_variant_rows(variants: object, page_url: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in variants if isinstance(variants, list) else []:
        if not isinstance(item, dict):
            continue
        offer = item.get("offers")
        offer = offer[0] if isinstance(offer, list) and offer else offer
        availability_source = offer if isinstance(offer, dict) else item.get("availability")
        row: dict[str, object] = {}
        sku = coerce_text(item.get("sku"))
        if sku:
            row["sku"] = sku
        gtin = coerce_text(item.get("gtin13") or item.get("gtin") or item.get("gtin14"))
        if gtin:
            row["barcode"] = gtin
        title = coerce_text(item.get("name"))
        if title:
            row["title"] = title
        color = coerce_field_value("color", item.get("color"), page_url)
        if color:
            row["color"] = color
        size = coerce_field_value("size", item.get("size"), page_url)
        if size:
            row["size"] = size
        price = coerce_field_value("price", offer or item, page_url)
        if price not in (None, "", [], {}):
            row["price"] = price
        availability = coerce_field_value("availability", availability_source, page_url)
        if availability not in (None, "", [], {}):
            row["availability"] = availability
        image_url = coerce_field_value("image_url", item.get("image"), page_url)
        if image_url not in (None, "", [], {}):
            row["image_url"] = image_url
        variant_url = coerce_field_value("url", offer or item, page_url)
        if variant_url not in (None, "", [], {}):
            row["url"] = variant_url
        option_values = {
            key: value
            for key, value in {"color": color, "size": size}.items()
            if value not in (None, "", [], {})
        }
        if option_values:
            row["option_values"] = option_values
        if row:
            rows.append(row)
    return rows


def _variant_axes_from_rows(variants: list[dict[str, object]]) -> dict[str, list[str]]:
    axes: dict[str, list[str]] = {}
    for row in variants:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, axis_value in option_values.items():
                cleaned = text_or_none(axis_value)
                if not cleaned:
                    continue
                axes.setdefault(str(axis_name), [])
                if cleaned not in axes[str(axis_name)]:
                    axes[str(axis_name)].append(cleaned)
        for axis_name in ("color", "size"):
            cleaned = text_or_none(row.get(axis_name))
            if not cleaned:
                continue
            axes.setdefault(axis_name, [])
            if cleaned not in axes[axis_name]:
                axes[axis_name].append(cleaned)
    return axes


def _looks_like_shopify_price_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if any(
        key in payload
        for key in ("handle", "body_html", "product_type", "compare_at_price")
    ):
        return True
    raw_variants = payload.get("variants")
    if isinstance(raw_variants, list):
        return any(
            isinstance(variant, dict)
            and any(
                field in variant
                for field in ("option1", "compare_at_price", "inventory_quantity")
            )
            for variant in raw_variants
        )
    return any(field in payload for field in ("option1", "compare_at_price", "inventory_quantity"))


def _coerce_structured_candidate_value(
    canonical: str,
    value: object,
    *,
    page_url: str,
    payload: object,
) -> object | None:
    if canonical in {"price", "sale_price", "original_price"} and _looks_like_shopify_price_payload(payload):
        normalized = normalize_decimal_price(
            value,
            interpret_integral_as_cents=True,
        )
        if normalized not in (None, ""):
            return normalized
    return coerce_field_value(canonical, value, page_url)


def collect_structured_candidates(
    payload: object,
    alias_lookup: dict[str, str],
    page_url: str,
    candidates: dict[str, list[object]],
    *,
    depth: int = 0,
    limit: int = 8,
) -> None:
    if depth > limit:
        return
    if isinstance(payload, dict):
        additional_properties = payload.get("additionalProperty")
        if isinstance(additional_properties, list):
            for item in additional_properties[:20]:
                if not isinstance(item, dict):
                    continue
                label = normalize_requested_field(item.get("name")) or normalize_field_key(
                    item.get("name")
                )
                canonical = alias_lookup.get(label)
                if canonical:
                    add_candidate(
                        candidates,
                        canonical,
                        coerce_field_value(canonical, item.get("value"), page_url),
                    )
        for key, value in payload.items():
            if str(key).startswith("@"):
                collect_structured_candidates(
                    value,
                    alias_lookup,
                    page_url,
                    candidates,
                    depth=depth + 1,
                    limit=limit,
                )
                continue
            normalized_key = normalize_field_key(key)
            canonical = alias_lookup.get(normalized_key)
            if canonical:
                add_candidate(
                    candidates,
                    canonical,
                    _coerce_structured_candidate_value(
                        canonical,
                        value,
                        page_url=page_url,
                        payload=payload,
                    ),
                )
            collect_structured_candidates(
                value,
                alias_lookup,
                page_url,
                candidates,
                depth=depth + 1,
                limit=limit,
            )
        raw_type = payload.get("@type")
        normalized_type = " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        normalized_type = normalized_type.lower()
        if "product" in normalized_type or "productgroup" in normalized_type:
            offer = payload.get("offers")
            offer = offer[0] if isinstance(offer, list) and offer else offer
            aggregate = payload.get("aggregateRating")
            brand = payload.get("brand")
            images = extract_urls(payload.get("image"), page_url)
            add_candidate(candidates, "title", coerce_text(payload.get("name") or payload.get("title")))
            add_candidate(candidates, "url", absolute_url(page_url, payload.get("url") or page_url))
            add_candidate(candidates, "description", coerce_text(payload.get("description")))
            add_candidate(candidates, "brand", coerce_field_value("brand", brand, page_url))
            add_candidate(candidates, "sku", coerce_text(payload.get("sku")))
            add_candidate(candidates, "part_number", coerce_text(payload.get("mpn")))
            add_candidate(candidates, "barcode", coerce_text(payload.get("gtin13") or payload.get("gtin") or payload.get("gtin14")))
            add_candidate(candidates, "price", coerce_field_value("price", offer or payload, page_url))
            add_candidate(candidates, "currency", coerce_field_value("currency", offer or payload, page_url))
            add_candidate(candidates, "availability", coerce_field_value("availability", offer or payload, page_url))
            add_candidate(candidates, "rating", coerce_field_value("rating", aggregate, page_url))
            add_candidate(candidates, "review_count", coerce_field_value("review_count", aggregate, page_url))
            add_candidate(candidates, "category", coerce_text(payload.get("category")))
            add_candidate(candidates, "color", coerce_field_value("color", payload.get("color"), page_url))
            add_candidate(candidates, "size", coerce_field_value("size", payload.get("size"), page_url))
            add_candidate(candidates, "materials", coerce_text(payload.get("material")))
            if images:
                add_candidate(candidates, "image_url", images[0])
                add_candidate(candidates, "additional_images", images[1:])
            variants = _structured_variant_rows(payload.get("hasVariant"), page_url)
            if variants:
                axes = _variant_axes_from_rows(variants)
                if axes:
                    variants = resolve_variants(axes, variants)
                    add_candidate(candidates, "variant_axes", axes)
                add_candidate(candidates, "variants", variants)
                add_candidate(candidates, "selected_variant", variants[0])
                add_candidate(candidates, "variant_count", len(variants))
        if "jobposting" in normalized_type:
            organization = payload.get("hiringOrganization")
            remote_hint = coerce_text(payload.get("jobLocationType"))
            add_candidate(candidates, "title", coerce_text(payload.get("title") or payload.get("name")))
            add_candidate(candidates, "url", absolute_url(page_url, payload.get("url") or page_url))
            add_candidate(candidates, "apply_url", absolute_url(page_url, payload.get("url") or page_url))
            add_candidate(candidates, "company", coerce_field_value("company", organization, page_url))
            add_candidate(candidates, "location", coerce_field_value("location", payload.get("jobLocation"), page_url))
            add_candidate(candidates, "posted_date", coerce_text(payload.get("datePosted")))
            add_candidate(candidates, "job_type", coerce_text(payload.get("employmentType")))
            add_candidate(candidates, "salary", coerce_field_value("salary", payload.get("baseSalary"), page_url))
            add_candidate(candidates, "description", coerce_text(payload.get("description")))
            if remote_hint:
                add_candidate(candidates, "remote", remote_hint)
    elif isinstance(payload, list):
        for item in payload[:20]:
            collect_structured_candidates(
                item,
                alias_lookup,
                page_url,
                candidates,
                depth=depth + 1,
                limit=limit,
            )


def finalize_candidate_value(field_name: str, values: list[object]) -> object | None:
    if not values:
        return None
    if field_name in STRUCTURED_OBJECT_FIELDS:
        return next((value for value in values if isinstance(value, dict)), None)
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        return next((value for value in values if isinstance(value, list) and value), None)
    if field_name in STRUCTURED_MULTI_FIELDS:
        rows: list[str] = []
        seen: set[str] = set()
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = text_or_none(item)
                if not text:
                    continue
                lowered = text.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                rows.append(text)
        if field_name == "additional_images":
            return rows or None
        return ", ".join(rows) if rows else None
    if field_name in LONG_TEXT_FIELDS:
        rows: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = coerce_text(value)
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            rows.append(text)
        return "\n\n".join(rows) if rows else None
    return values[0]


def record_score(record: dict[str, Any]) -> int:
    return sum(
        1
        for key, value in record.items()
        if key not in {"source_url", "url", "_source"}
        and value not in (None, "", [], {})
    )
