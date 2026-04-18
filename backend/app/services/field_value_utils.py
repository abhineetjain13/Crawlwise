from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import EXTRACTION_RULES
from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.field_policy import (
    expand_requested_fields,
    get_surface_field_aliases,
    normalize_field_key,
    normalize_requested_field,
)
from app.services.normalizers import normalize_record_fields

logger = logging.getLogger(__name__)

PRODUCT_URL_HINTS = ("/dp/", "/p/", "/pd/", "/product", "/products/", "/item/")
JOB_URL_HINTS = ("/job", "/jobs", "/career", "/careers", "/position", "/posting", "/opening")
PRICE_RE = re.compile(r"[$€£₹]\s?\d[\d,]*(?:\.\d{1,2})?")
PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
REVIEW_COUNT_RE = re.compile(r"\b(\d[\d,]*)\s+reviews?\b", re.I)
RATING_RE = re.compile(r"\b([1-5](?:\.\d)?)\s*(?:/5|out of 5|stars?)\b", re.I)
WHITESPACE_RE = re.compile(r"\s+")
ALL_CANONICAL_FIELDS = sorted(
    {
        field_name
        for fields in CANONICAL_SCHEMAS.values()
        for field_name in list(fields or [])
        if field_name
    }
)
STRUCTURED_MULTI_FIELDS = {
    "additional_images",
    "available_sizes",
    "option1_values",
    "option2_values",
    "tags",
}
STRUCTURED_OBJECT_FIELDS = {"product_attributes", "selected_variant", "variant_axes"}
STRUCTURED_OBJECT_LIST_FIELDS = {"variants"}
LONG_TEXT_FIELDS = {
    "benefits",
    "care",
    "description",
    "features",
    "materials",
    "qualifications",
    "requirements",
    "responsibilities",
    "skills",
    "specifications",
    "summary",
}
URL_FIELDS = {"apply_url", "company_logo", "image_url", "url"}
IMAGE_FIELDS = {"additional_images", "company_logo", "image_url"}


def clean_text(value: object) -> str:
    text = unescape(str(value or "")).strip()
    return WHITESPACE_RE.sub(" ", text)


def text_or_none(value: object) -> str | None:
    text = clean_text(value)
    return text or None


def absolute_url(base_url: str, candidate: object) -> str:
    text = clean_text(candidate)
    if not text:
        return ""
    return urljoin(base_url, text)


def same_host(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    return bool(candidate_host) and candidate_host == base_host


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in record.items()
        if value not in (None, "", [], {})
    }


def surface_fields(surface: str, requested_fields: list[str] | None) -> list[str]:
    normalized_surface = str(surface or "").strip().lower()
    fields = list(CANONICAL_SCHEMAS.get(normalized_surface, ALL_CANONICAL_FIELDS))
    for field_name in expand_requested_fields(list(requested_fields or [])):
        if field_name and field_name not in fields:
            fields.append(field_name)
    return fields


def surface_alias_lookup(
    surface: str,
    requested_fields: list[str] | None,
) -> dict[str, str]:
    fields = surface_fields(surface, requested_fields)
    aliases = get_surface_field_aliases(surface)
    lookup: dict[str, str] = {}
    for canonical in fields:
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            lookup[normalized_canonical] = canonical
        for alias in list(aliases.get(canonical, [])):
            normalized_alias = normalize_field_key(alias)
            if normalized_alias:
                lookup[normalized_alias] = canonical
    return lookup


def coerce_text(value: object) -> str | None:
    if isinstance(value, str):
        if "<" in value or "&" in value:
            return text_or_none(
                BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
            )
        return text_or_none(value)
    return text_or_none(value)


def coerce_location(value: object) -> str | None:
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            parts = [
                text_or_none(address.get("streetAddress")),
                text_or_none(address.get("addressLocality")),
                text_or_none(address.get("addressRegion")),
                text_or_none(address.get("postalCode")),
                text_or_none(address.get("addressCountry")),
            ]
            cleaned_parts = [part for part in parts if part]
            if cleaned_parts:
                return ", ".join(cleaned_parts)
        parts = [
            text_or_none(value.get("name")),
            text_or_none(value.get("addressLocality")),
            text_or_none(value.get("addressRegion")),
            text_or_none(value.get("addressCountry")),
        ]
        cleaned_parts = [part for part in parts if part]
        if cleaned_parts:
            return ", ".join(cleaned_parts)
    if isinstance(value, list):
        parts = [coerce_location(item) for item in value]
        cleaned_parts = [part for part in parts if part]
        return " | ".join(cleaned_parts) if cleaned_parts else None
    return coerce_text(value)


def salary_from_json(value: object) -> str | None:
    if isinstance(value, dict):
        currency = text_or_none(
            value.get("currency")
            or value.get("salaryCurrency")
            or value.get("currencyCode")
        )
        nested = value.get("value")
        if isinstance(nested, dict):
            minimum = text_or_none(nested.get("minValue"))
            maximum = text_or_none(nested.get("maxValue"))
            amount = text_or_none(nested.get("value"))
            unit = text_or_none(nested.get("unitText"))
            numbers = " - ".join(part for part in (minimum, maximum) if part)
            if not numbers:
                numbers = amount or ""
            if numbers:
                return " ".join(
                    piece for piece in (currency, numbers, unit) if piece
                )
        text = coerce_text(value.get("value"))
        if text:
            return f"{currency} {text}".strip() if currency else text
    return coerce_text(value)


def extract_urls(value: object, page_url: str) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        absolute = absolute_url(page_url, value)
        if absolute:
            results.append(absolute)
        return results
    if isinstance(value, dict):
        for key in ("url", "href", "src", "contentUrl", "image", "thumbnail"):
            candidate = value.get(key)
            if candidate in (None, "", [], {}):
                continue
            results.extend(extract_urls(candidate, page_url))
    elif isinstance(value, list):
        for item in value:
            results.extend(extract_urls(item, page_url))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in results:
        normalized = candidate.lower()
        if not candidate or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def coerce_field_value(field_name: str, value: object, page_url: str) -> object | None:
    if value in (None, "", [], {}):
        return None
    if field_name in STRUCTURED_OBJECT_FIELDS and isinstance(value, dict):
        return value
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS and isinstance(value, list):
        dict_rows = [item for item in value if isinstance(item, dict)]
        return dict_rows or None
    if field_name == "location":
        return coerce_location(value)
    if field_name == "salary":
        return salary_from_json(value)
    if field_name in {"brand", "company", "dealer_name", "vendor"} and isinstance(
        value,
        dict,
    ):
        return coerce_text(value.get("name") or value.get("title") or value.get("value"))
    if field_name in {"price", "sale_price", "original_price", "discount_amount"} and isinstance(value, dict):
        for key in (
            "price",
            "amount",
            "value",
            "currentValue",
            "minValue",
            "maxValue",
            "displayPrice",
            "formattedPrice",
        ):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
    if field_name in {"currency", "salary_currency"} and isinstance(value, dict):
        for key in ("currency", "currencyCode", "priceCurrency", "salaryCurrency"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
    if field_name == "rating" and isinstance(value, dict):
        for key in ("ratingValue", "value", "rating", "score"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
    if field_name == "review_count" and isinstance(value, dict):
        for key in ("reviewCount", "ratingCount", "count", "totalCount", "numberOfReviews"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
    if field_name == "availability" and isinstance(value, dict):
        for key in ("availability", "availabilityStatus", "status", "name", "value"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
    if field_name in URL_FIELDS:
        urls = extract_urls(value, page_url)
        return urls[0] if urls else None
    if field_name in IMAGE_FIELDS:
        urls = extract_urls(value, page_url)
        if field_name == "additional_images":
            return urls or None
        return urls[0] if urls else None
    if field_name in STRUCTURED_MULTI_FIELDS:
        if isinstance(value, list):
            rows = [coerce_text(item) for item in value]
            return [row for row in rows if row] or None
        if isinstance(value, dict):
            rows = [coerce_text(item) for item in value.values()]
            return [row for row in rows if row] or None
    if isinstance(value, list):
        rows: list[object] = []
        for item in value:
            normalized = coerce_field_value(field_name, item, page_url)
            if normalized in (None, "", [], {}):
                continue
            if isinstance(normalized, list):
                rows.extend(normalized)
            else:
                rows.append(normalized)
        return rows or None
    if field_name in LONG_TEXT_FIELDS:
        return coerce_text(value)
    return coerce_text(value)


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
        color = coerce_text(item.get("color"))
        if color:
            row["color"] = color
        size = coerce_text(item.get("size"))
        if size:
            row["size"] = size
        price = coerce_field_value("price", offer or item, page_url)
        if price not in (None, "", [], {}):
            row["price"] = price
        availability = coerce_field_value("availability", offer or item, page_url)
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
                    coerce_field_value(canonical, value, page_url),
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
            add_candidate(candidates, "color", coerce_text(payload.get("color")))
            add_candidate(candidates, "size", coerce_text(payload.get("size")))
            add_candidate(candidates, "materials", coerce_text(payload.get("material")))
            if images:
                add_candidate(candidates, "image_url", images[0])
                add_candidate(candidates, "additional_images", images[1:])
            variants = _structured_variant_rows(payload.get("hasVariant"), page_url)
            if variants:
                add_candidate(candidates, "variants", variants)
                axes = _variant_axes_from_rows(variants)
                if axes:
                    add_candidate(candidates, "variant_axes", axes)
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


def safe_select(root: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except Exception:
        logger.debug("Invalid selector %s", selector, exc_info=True)
        return []


def extract_node_value(node: Tag, field_name: str, page_url: str) -> object | None:
    if field_name in IMAGE_FIELDS:
        urls = extract_urls(
            node.get("content")
            or node.get("src")
            or node.get("data-src")
            or node.get("data-image")
            or node.get("href")
            or node.get("srcset")
            or "",
            page_url,
        )
        if field_name == "additional_images":
            return urls or None
        return urls[0] if urls else None
    if field_name in URL_FIELDS:
        urls = extract_urls(
            node.get("href") or node.get("content") or node.get("data-apply-url") or "",
            page_url,
        )
        return urls[0] if urls else None
    if node.name == "meta":
        return coerce_field_value(field_name, node.get("content"), page_url)
    for attr_name in ("content", "value", "datetime", "data-value", "data-price", "data-availability"):
        attr_value = node.get(attr_name)
        if attr_value not in (None, "", [], {}):
            return coerce_field_value(field_name, attr_value, page_url)
    return coerce_field_value(field_name, node.get_text(" ", strip=True), page_url)


def extract_selector_values(
    root: BeautifulSoup | Tag,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    for node in safe_select(root, selector)[:12]:
        value = extract_node_value(node, field_name, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_page_images(root: BeautifulSoup | Tag, page_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for node in root.find_all("img"):
        candidate = absolute_url(
            page_url,
            node.get("src") or node.get("data-src") or node.get("data-original") or "",
        )
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(candidate)
    return values[:12]


def extract_label_value_pairs(root: BeautifulSoup | Tag) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = clean_text(cells[0].get_text(" ", strip=True))
        value = clean_text(cells[1].get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for dt in root.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = clean_text(dt.get_text(" ", strip=True))
        value = clean_text(dd.get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for node in root.find_all(["li", "p", "div", "span"]):
        text = clean_text(node.get_text(" ", strip=True))
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        label = clean_text(label)
        value = clean_text(value)
        if not label or not value:
            continue
        if len(label) > 40 or len(value) > 250:
            continue
        rows.append((label, value))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in rows:
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, value))
    return deduped


def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in root.find_all(["h2", "h3", "h4", "h5", "strong"]):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if len(heading_text) < 3 or len(heading_text) > 60:
            continue
        values: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3", "h4", "h5"}:
                break
            text = clean_text(
                sibling.get_text(" ", strip=True) if isinstance(sibling, Tag) else str(sibling)
            )
            if not text:
                continue
            values.append(text)
            if len(values) >= 4 or sum(len(item) for item in values) >= 1000:
                break
        if values:
            sections[heading_text] = " ".join(values)
    return sections


def apply_selector_fallbacks(
    root: BeautifulSoup | Tag,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    selector_rules: list[dict[str, object]] | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    for row in list(selector_rules or []):
        if not isinstance(row, dict):
            continue
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        if field_name not in fields or not bool(row.get("is_active", True)):
            continue
        for selector_key in ("css_selector", "xpath", "regex"):
            selector = str(row.get(selector_key) or "").strip()
            if not selector:
                continue
            for value in extract_selector_values(root, selector, field_name, page_url):
                add_candidate(candidates, field_name, value)
    dom_patterns = dict(EXTRACTION_RULES.get("dom_patterns") or {})
    for field_name in fields:
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in extract_selector_values(root, selector, field_name, page_url):
            add_candidate(candidates, field_name, value)
    for label, value in extract_label_value_pairs(root):
        normalized_label = normalize_requested_field(label) or normalize_field_key(label)
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            add_candidate(
                candidates,
                canonical,
                coerce_field_value(canonical, value, page_url),
            )


def finalize_record(
    record: dict[str, Any],
    *,
    normalize_fields: bool = True,
) -> dict[str, Any]:
    cleaned = clean_record(record)
    return normalize_record_fields(cleaned) if normalize_fields else cleaned
