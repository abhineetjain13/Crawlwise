from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_GENDER_TERMS,
    DETAIL_IRRELEVANT_JSON_LD_TYPES,
    INTEGRAL_PRICE_PAYLOAD_HINT_FIELDS,
    INTEGRAL_PRICE_PAYLOAD_VARIANT_FIELDS,
    STRUCTURED_CANDIDATE_LIST_SLICE,
    STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT,
)
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
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    resolve_variants,
)
from app.services.normalizers import normalize_decimal_price

logger = logging.getLogger(__name__)
_structured_candidate_list_slice = int(STRUCTURED_CANDIDATE_LIST_SLICE)
_structured_candidate_traversal_limit = int(STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT)


def candidate_fingerprint(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def add_candidate(
    candidates: dict[str, list[object]],
    field_name: str,
    value: object,
) -> int:
    if value in (None, "", [], {}):
        return 0
    bucket = candidates.setdefault(field_name, [])
    values = (
        list(value)
        if field_name in STRUCTURED_MULTI_FIELDS and isinstance(value, list)
        else [value]
    )
    seen = {candidate_fingerprint(existing) for existing in bucket}
    added = 0
    for item in values:
        if item in (None, "", [], {}):
            continue
        fingerprint = candidate_fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bucket.append(item)
        added += 1
    return added


def _normalized_text_token(value: object) -> str:
    return " ".join(str(value or "").replace("&", " ").split()).strip().lower()


def _gender_from_text(value: object) -> str | None:
    text = _normalized_text_token(value)
    if not text:
        return None
    padded = f" {text.replace('-', ' ')} "
    matches: list[str] = []
    for canonical, terms in DETAIL_GENDER_TERMS.items():
        if any(f" {str(term).lower().replace('-', ' ')} " in padded for term in terms):
            matches.append(str(canonical))
    return matches[0] if len(set(matches)) == 1 else None


def _breadcrumb_item_name(item: object) -> str | None:
    if isinstance(item, str):
        return text_or_none(item)
    if not isinstance(item, dict):
        return None
    source = item.get("item")
    if isinstance(source, dict):
        name = source.get("name") or source.get("title")
        if name not in (None, "", [], {}):
            return text_or_none(name)
    return text_or_none(item.get("name") or item.get("title"))


def _breadcrumb_names(payload: dict[str, object], page_url: str = "") -> list[str]:
    raw_items = payload.get("itemListElement")
    if not isinstance(raw_items, list):
        return []

    def _get_position(item: Any) -> float:
        if not isinstance(item, dict):
            return 0.0
        try:
            return float(item.get("position", 0))
        except (ValueError, TypeError):
            return 0.0

    try:
        if all(isinstance(x, dict) and _get_position(x) > 0 for x in raw_items):
            raw_items = sorted(raw_items, key=_get_position)
    except Exception:
        logger.exception("Failed to sort breadcrumb itemListElement by position")

    names: list[str] = []
    strip_chars = " \t\n\r" + "".join(DETAIL_BREADCRUMB_SEPARATOR_LABELS)
    for item in raw_items:
        name = _breadcrumb_item_name(item)
        if name:
            clean_name = name.strip(strip_chars)
            if clean_name and clean_name not in DETAIL_BREADCRUMB_SEPARATOR_LABELS:
                names.append(clean_name)
    if not names:
        return []

    def _is_root_label(text: str) -> bool:
        lowered = text.strip().lower()
        if lowered in DETAIL_BREADCRUMB_ROOT_LABELS:
            return True
        if page_url:
            host = urlparse(page_url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            host_parts = [part for part in host.split(".") if part]
            second_level_domain = host_parts[-2] if len(host_parts) >= 2 else host
            if host and (lowered == host or lowered == second_level_domain):
                return True
        return False

    if len(names) > 1 and _is_root_label(names[-1]) and not _is_root_label(names[0]):
        names.reverse()

    if _is_root_label(names[0]):
        names = names[1:]
    return [name for name in names if name]


def _breadcrumb_category_path(
    payload: dict[str, object], page_url: str = ""
) -> str | None:
    names = _breadcrumb_names(payload, page_url)
    return " > ".join(names) if names else None


def _structured_variant_rows(
    variants: object, page_url: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in variants if isinstance(variants, list) else []:
        if not isinstance(item, dict):
            continue
        offer = item.get("offers")
        offer = offer[0] if isinstance(offer, list) and offer else offer
        availability_source = (
            offer if isinstance(offer, dict) else item.get("availability")
        )
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
        option_values: dict[str, object] = {}
        if color:
            option_values["color"] = color
        if size:
            option_values["size"] = size
        # Schema.org additionalProperty: captures material, style, scent, weight, etc.
        additional_props = item.get("additionalProperty")
        if isinstance(additional_props, list):
            for prop in additional_props:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value"):
                    axis_key = normalized_variant_axis_key(prop["name"])
                    if axis_key:
                        option_values[axis_key] = str(prop["value"]).strip()
        if option_values:
            row["option_values"] = option_values
        if row:
            rows.append(row)
    return rows


def _structured_offer_variant_rows(
    offers: object, page_url: str
) -> list[dict[str, object]]:
    raw_offers = offers if isinstance(offers, list) else []
    if len(raw_offers) < 2:
        return []
    rows: list[dict[str, object]] = []
    for item in raw_offers:
        if not isinstance(item, dict):
            continue
        row: dict[str, object] = {}
        offered_item = item.get("itemOffered")
        offered_item = offered_item if isinstance(offered_item, dict) else {}
        title = coerce_text(item.get("name") or offered_item.get("name"))
        if title:
            row["title"] = title
        sku = coerce_text(item.get("sku") or offered_item.get("sku"))
        if sku:
            row["sku"] = sku
        price = coerce_field_value("price", item, page_url)
        if price not in (None, "", [], {}):
            row["price"] = price
        currency = coerce_field_value("currency", item, page_url)
        if currency not in (None, "", [], {}):
            row["currency"] = currency
        availability = coerce_field_value("availability", item, page_url)
        if availability not in (None, "", [], {}):
            row["availability"] = availability
        variant_url = coerce_field_value("url", item, page_url)
        if variant_url not in (None, "", [], {}):
            row["url"] = variant_url
        if row.get("url") or row.get("price"):
            rows.append(row)
    return rows


def _structured_feature_rows(payload: dict[str, object], page_url: str) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()

    def _add(value: object) -> None:
        coerced = coerce_field_value("features", value, page_url)
        values = coerced if isinstance(coerced, list) else [coerced]
        for item in values:
            text = text_or_none(item)
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            rows.append(text)

    for key in ("feature", "features"):
        raw_value = payload.get(key)
        if raw_value not in (None, "", [], {}):
            _add(raw_value)

    additional_properties = payload.get("additionalProperty")
    if isinstance(additional_properties, list):
        for item in additional_properties[: _structured_candidate_list_slice]:
            if not isinstance(item, dict):
                continue
            name = text_or_none(item.get("name") or item.get("label"))
            value = text_or_none(item.get("value") or item.get("description"))
            if name and value:
                _add(f"{name}: {value}")
            elif value:
                _add(value)
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


def _variation_attribute_labels(
    payload: dict[str, object],
) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    raw_attributes = payload.get("variationAttributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = payload.get("variation_attributes")
    for attribute in raw_attributes if isinstance(raw_attributes, list) else []:
        if not isinstance(attribute, dict):
            continue
        axis_key = normalized_variant_axis_key(
            attribute.get("id") or attribute.get("name") or attribute.get("label")
        )
        values = attribute.get("values")
        if not axis_key or not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            raw_value = text_or_none(item.get("value") or item.get("id"))
            display = text_or_none(
                item.get("name")
                or item.get("displayValue")
                or item.get("display_value")
                or item.get("label")
            )
            if raw_value and display:
                labels.setdefault(axis_key, {})[raw_value] = display
    return labels


def _structured_variants_from_product_payload(
    payload: dict[str, object],
    page_url: str,
) -> list[dict[str, object]]:
    raw_variants = payload.get("variants")
    if not isinstance(raw_variants, list):
        return []
    labels = _variation_attribute_labels(payload)
    rows: list[dict[str, object]] = []
    for item in raw_variants:
        if not isinstance(item, dict):
            continue
        variation_values = item.get("variationValues")
        if not isinstance(variation_values, dict):
            variation_values = item.get("variation_values")
        if not isinstance(variation_values, dict):
            continue
        option_values: dict[str, str] = {}
        for axis_name, raw_value in variation_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = text_or_none(raw_value)
            if not axis_key or not cleaned:
                continue
            option_values[axis_key] = labels.get(axis_key, {}).get(cleaned, cleaned)
        if not option_values:
            continue
        row: dict[str, object] = {"option_values": option_values}
        sku = text_or_none(
            item.get("sku") or item.get("productId") or item.get("product_id")
        )
        if sku:
            row["sku"] = sku
        variant_id = text_or_none(
            item.get("id") or item.get("productId") or item.get("product_id")
        )
        if variant_id:
            row["variant_id"] = variant_id
        price = _coerce_structured_candidate_value(
            "price",
            item.get("price"),
            page_url=page_url,
            payload=payload,
            source_key="price",
        )
        if price not in (None, "", [], {}):
            row["price"] = price
        for axis_key, axis_value in option_values.items():
            if axis_key in {"color", "size"}:
                row[axis_key] = axis_value
        rows.append(row)
    return rows


def _uses_integral_price_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    payload_hint_fields = INTEGRAL_PRICE_PAYLOAD_HINT_FIELDS
    variant_hint_fields = INTEGRAL_PRICE_PAYLOAD_VARIANT_FIELDS
    if any(key in payload for key in payload_hint_fields):
        return True
    raw_variants = payload.get("variants")
    if isinstance(raw_variants, list):
        return any(
            isinstance(variant, dict)
            and any(field in variant for field in variant_hint_fields)
            for variant in raw_variants
        )
    return any(field in payload for field in variant_hint_fields)


def _coerce_structured_candidate_value(
    canonical: str,
    value: object,
    *,
    page_url: str,
    payload: object,
    source_key: str = "",
) -> object | None:
    if canonical in {
        "price",
        "sale_price",
        "original_price",
    } and _source_key_is_price_field(source_key) and _uses_integral_price_payload(payload):
        normalized = normalize_decimal_price(
            value,
            interpret_integral_as_cents=True,
        )
        if normalized not in (None, ""):
            return normalized
    return coerce_field_value(canonical, value, page_url)


def _source_key_is_price_field(value: object) -> bool:
    normalized = normalize_field_key(str(value or ""))
    return normalized in {"price", "sale_price", "original_price", "compare_at_price"}


def _is_product_attribute_row(payload: dict[str, object]) -> bool:
    keys = {normalize_field_key(str(key or "")) for key in payload}
    return bool(keys & {"id", "name", "label"}) and bool(keys & {"value", "values"})


def _structured_alias_allowed(
    *,
    canonical: str,
    normalized_key: str,
    payload: dict[str, object],
) -> bool:
    if (
        canonical == "sku"
        and normalized_key == "id"
        and _is_product_attribute_row(payload)
    ):
        return False
    payload_types = _structured_payload_types(payload)
    raw_types = payload.get("@type")
    if not payload_types:
        return raw_types in (None, "", [], {})
    if canonical in {
        "title",
        "description",
        "image_url",
        "additional_images",
        "url",
    } and (payload_types & {"brand", "review", "reviewrating"}):
        return False
    if canonical == "brand" and "person" in payload_types:
        return False
    return True


def _structured_payload_types(payload: dict[str, object]) -> set[str]:
    raw_types = payload.get("@type")
    normalized_types = {
        str(item or "").strip().lower()
        for item in (raw_types if isinstance(raw_types, list) else [raw_types])
        if str(item or "").strip()
    }
    irrelevant_types = {
        str(value).strip().lower()
        for value in tuple(DETAIL_IRRELEVANT_JSON_LD_TYPES or ())
        if str(value).strip()
    }
    if normalized_types and normalized_types <= irrelevant_types:
        return set()
    return normalized_types


def collect_structured_candidates(
    payload: object,
    alias_lookup: dict[str, str],
    page_url: str,
    candidates: dict[str, list[object]],
    *,
    depth: int = 0,
    limit: int = _structured_candidate_traversal_limit,
) -> None:
    if depth > limit:
        return
    if isinstance(payload, dict):
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        )
        normalized_type = normalized_type.lower()
        breadcrumb_list = "breadcrumblist" in normalized_type
        list_item_wrapper = "listitem" in normalized_type and (
            "position" in payload or "item" in payload
        )
        review_like = any(
            token in normalized_type for token in ("review", "reviewrating")
        )
        additional_properties = payload.get("additionalProperty")
        if isinstance(additional_properties, list):
            for item in additional_properties[: _structured_candidate_list_slice]:
                if not isinstance(item, dict):
                    continue
                label = normalize_requested_field(
                    item.get("name")
                ) or normalize_field_key(item.get("name"))
                canonical = alias_lookup.get(label)
                if canonical:
                    add_candidate(
                        candidates,
                        canonical,
                        coerce_field_value(canonical, item.get("value"), page_url),
                    )
        if breadcrumb_list:
            category_path = _breadcrumb_category_path(payload, page_url)
            if category_path:
                add_candidate(candidates, "category", category_path)
                gender = _gender_from_text(category_path)
                if gender:
                    add_candidate(candidates, "gender", gender)
        if {normalize_field_key(str(key or "")) for key in payload.keys()} & {
            "field_name",
            "field_value",
            "field_values",
        }:
            label = normalize_requested_field(
                payload.get("FieldName")
                or payload.get("fieldName")
                or payload.get("field_name")
            ) or normalize_field_key(
                payload.get("FieldName")
                or payload.get("fieldName")
                or payload.get("field_name")
            )
            canonical = alias_lookup.get(label)
            if canonical:
                raw_value = (
                    payload.get("FieldValues")
                    or payload.get("fieldValues")
                    or payload.get("field_values")
                    or payload.get("FieldValue")
                    or payload.get("fieldValue")
                    or payload.get("field_value")
                )
                if isinstance(raw_value, list):
                    if canonical in STRUCTURED_MULTI_FIELDS:
                        coerced_value: object = raw_value
                    else:
                        coerced_value = " ".join(
                            text for item in raw_value if (text := text_or_none(item))
                        )
                else:
                    coerced_value = raw_value
                add_candidate(
                    candidates,
                    canonical,
                    coerce_field_value(canonical, coerced_value, page_url),
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
            if (
                breadcrumb_list
                and normalized_key
                in {"item_list_element", "item", "name", "title", "position"}
            ) or (
                list_item_wrapper
                and normalized_key in {"item", "name", "title", "position"}
            ):
                continue
            if "productgroup" in normalized_type and normalized_key in {
                "has_variant",
                "hasvariant",
            }:
                continue
            canonical = alias_lookup.get(normalized_key)
            if (
                canonical
                and not (
                    review_like
                    and canonical
                    in {"title", "description", "image_url", "additional_images"}
                )
                and _structured_alias_allowed(
                    canonical=canonical,
                    normalized_key=normalized_key,
                    payload=payload,
                )
            ):
                add_candidate(
                    candidates,
                    canonical,
                    _coerce_structured_candidate_value(
                        canonical,
                        value,
                        page_url=page_url,
                        payload=payload,
                        source_key=normalized_key,
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
        if "product" in normalized_type or "productgroup" in normalized_type:
            offer = payload.get("offers")
            offer = offer[0] if isinstance(offer, list) and offer else offer
            aggregate = payload.get("aggregateRating")
            brand = payload.get("brand")
            images = extract_urls(payload.get("image"), page_url)
            add_candidate(
                candidates,
                "title",
                coerce_text(payload.get("name") or payload.get("title")),
            )
            add_candidate(
                candidates,
                "url",
                absolute_url(page_url, payload.get("url") or page_url),
            )
            add_candidate(
                candidates, "description", coerce_text(payload.get("description"))
            )
            add_candidate(
                candidates, "brand", coerce_field_value("brand", brand, page_url)
            )
            add_candidate(candidates, "sku", coerce_text(payload.get("sku")))
            add_candidate(candidates, "part_number", coerce_text(payload.get("mpn")))
            add_candidate(
                candidates,
                "barcode",
                coerce_text(
                    payload.get("gtin13")
                    or payload.get("gtin")
                    or payload.get("gtin14")
                ),
            )
            add_candidate(
                candidates,
                "price",
                coerce_field_value("price", offer or payload, page_url),
            )
            add_candidate(
                candidates,
                "currency",
                coerce_field_value("currency", offer or payload, page_url),
            )
            add_candidate(
                candidates,
                "availability",
                coerce_field_value("availability", offer or payload, page_url),
            )
            add_candidate(
                candidates, "rating", coerce_field_value("rating", aggregate, page_url)
            )
            add_candidate(
                candidates,
                "review_count",
                coerce_field_value("review_count", aggregate, page_url),
            )
            add_candidate(candidates, "category", coerce_text(payload.get("category")))
            add_candidate(
                candidates,
                "gender",
                coerce_field_value("gender", payload.get("gender"), page_url),
            )
            add_candidate(
                candidates,
                "color",
                coerce_field_value("color", payload.get("color"), page_url),
            )
            add_candidate(
                candidates,
                "size",
                coerce_field_value("size", payload.get("size"), page_url),
            )
            add_candidate(candidates, "materials", coerce_text(payload.get("material")))
            feature_rows = _structured_feature_rows(payload, page_url)
            if feature_rows:
                add_candidate(candidates, "features", feature_rows)
            if images:
                add_candidate(candidates, "image_url", images[0])
                add_candidate(candidates, "additional_images", images[1:])
            variants = _structured_variant_rows(payload.get("hasVariant"), page_url)
            offer_variants = _structured_offer_variant_rows(
                payload.get("offers"), page_url
            )
            if offer_variants:
                variants.extend(offer_variants)
            product_variants = _structured_variants_from_product_payload(
                payload, page_url
            )
            if product_variants:
                variants.extend(product_variants)
            if variants:
                axes = _variant_axes_from_rows(variants)
                if axes:
                    variants = resolve_variants(axes, variants)
                add_candidate(candidates, "variants", variants)
                add_candidate(candidates, "variant_count", len(variants))
        if "jobposting" in normalized_type:
            organization = payload.get("hiringOrganization")
            remote_hint = coerce_text(payload.get("jobLocationType"))
            add_candidate(
                candidates,
                "title",
                coerce_text(payload.get("title") or payload.get("name")),
            )
            add_candidate(
                candidates,
                "url",
                absolute_url(page_url, payload.get("url") or page_url),
            )
            add_candidate(
                candidates,
                "apply_url",
                absolute_url(page_url, payload.get("url") or page_url),
            )
            add_candidate(
                candidates,
                "company",
                coerce_field_value("company", organization, page_url),
            )
            add_candidate(
                candidates,
                "location",
                coerce_field_value("location", payload.get("jobLocation"), page_url),
            )
            add_candidate(
                candidates, "posted_date", coerce_text(payload.get("datePosted"))
            )
            add_candidate(
                candidates, "job_type", coerce_text(payload.get("employmentType"))
            )
            add_candidate(
                candidates,
                "salary",
                coerce_field_value("salary", payload.get("baseSalary"), page_url),
            )
            add_candidate(
                candidates, "description", coerce_text(payload.get("description"))
            )
            if remote_hint:
                add_candidate(candidates, "remote", remote_hint)
    elif isinstance(payload, list):
        for item in payload[: _structured_candidate_list_slice]:
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
        merged: dict[str, object] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            merged = _deep_merge_structured_dict(merged, value)
        return merged or None
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        merged_rows: list[dict[str, object]] = []
        seen_rows: set[str] = set()
        for value in values:
            if not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict):
                    continue
                fingerprint = candidate_fingerprint(row)
                if fingerprint in seen_rows:
                    continue
                seen_rows.add(fingerprint)
                merged_rows.append(row)
        rows_with_option_values = [
            row
            for row in merged_rows
            if isinstance(row.get("option_values"), dict) and bool(row.get("option_values"))
        ]
        if field_name == "variants" and rows_with_option_values:
            merged_rows = rows_with_option_values
        return merged_rows or None
    if field_name in STRUCTURED_MULTI_FIELDS:
        rows: list[str] = []
        seen_values: set[str] = set()
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = text_or_none(item)
                if not text:
                    continue
                lowered = text.lower()
                if lowered in seen_values:
                    continue
                seen_values.add(lowered)
                rows.append(text)
        if field_name in {"additional_images", "features", "tags"}:
            return rows or None
        return "\n".join(rows) if rows else None
    if field_name in LONG_TEXT_FIELDS:
        text_rows: list[str] = []
        text_seen: set[str] = set()
        for value in values:
            text = coerce_text(value)
            if not text:
                continue
            lowered = text.lower()
            if lowered in text_seen:
                continue
            text_seen.add(lowered)
            text_rows.append(text)
        return "\n\n".join(text_rows) if text_rows else None
    return values[0]


def _deep_merge_structured_dict(
    base: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(base)
    incoming_option_values = incoming.get("option_values")
    incoming_option_keys = (
        {str(key) for key in incoming_option_values.keys()}
        if isinstance(incoming_option_values, dict)
        else set()
    )
    for key, value in incoming.items():
        normalized_key = str(key)
        existing = merged.get(normalized_key)
        if (
            normalized_key == "option_values"
            and isinstance(existing, dict)
            and existing
            and isinstance(value, dict)
        ):
            continue
        if (
            incoming_option_keys
            and isinstance(merged.get("option_values"), dict)
            and merged["option_values"]
            and normalized_key in incoming_option_keys
            and existing in (None, "", [], {})
        ):
            continue
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[normalized_key] = _deep_merge_structured_dict(existing, value)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            combined: list[object] = []
            seen: set[str] = set()
            for item in [*existing, *value]:
                fingerprint = candidate_fingerprint(item)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                combined.append(item)
            merged[normalized_key] = combined
            continue
        if existing in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[normalized_key] = value
            continue
        if normalized_key not in merged:
            merged[normalized_key] = value
    return merged


def record_score(record: dict[str, Any]) -> int:
    return sum(
        1
        for key, value in record.items()
        if key not in {"source_url", "url", "_source"}
        and value not in (None, "", [], {})
    )
