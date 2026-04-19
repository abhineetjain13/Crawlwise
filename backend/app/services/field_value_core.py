from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup
from w3lib.url import url_query_cleaner

from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.field_policy import (
    expand_requested_fields,
    get_surface_field_aliases,
    normalize_field_key,
)
from app.services.normalizers import normalize_record_fields

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
TRACKING_PARAM_EXACT_KEYS = {"fbclid", "gclid", "ref", "sid"}
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_STRIP_URL_FIELDS = {"apply_url", "source_url", "url"}


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


def _surface_needs_tracking_strip(surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    return normalized_surface.startswith(("ecommerce_", "job_"))


def strip_tracking_query_params(url: object) -> str | None:
    text = text_or_none(url)
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.query:
        return text
    removable_keys: list[str] = []
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_PARAM_EXACT_KEYS or any(
            lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES
        ):
            removable_keys.append(key)
    if not removable_keys:
        return text
    return url_query_cleaner(
        text,
        parameterlist=tuple(dict.fromkeys(removable_keys)),
        remove=True,
        keep_fragments=True,
    )


def strip_record_tracking_params(
    record: dict[str, Any],
    *,
    surface: str | None,
) -> dict[str, Any]:
    if not _surface_needs_tracking_strip(surface):
        return record
    cleaned = dict(record)
    for field_name in TRACKING_STRIP_URL_FIELDS:
        value = strip_tracking_query_params(cleaned.get(field_name))
        if value:
            cleaned[field_name] = value
    return cleaned


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
        if isinstance(address, str):
            address_text = text_or_none(address)
            if address_text:
                return address_text
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
        return None
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
    if field_name == "category" and isinstance(value, dict):
        return coerce_text(
            value.get("name")
            or value.get("title")
            or value.get("slug")
            or value.get("value")
        )
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
        return None
    if field_name in {"currency", "salary_currency"} and isinstance(value, dict):
        for key in ("currency", "currencyCode", "priceCurrency", "salaryCurrency"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
    if field_name == "rating" and isinstance(value, dict):
        for key in ("ratingValue", "value", "rating", "score"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
    if field_name == "review_count" and isinstance(value, dict):
        for key in ("reviewCount", "ratingCount", "count", "totalCount", "numberOfReviews"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
    if field_name == "availability" and isinstance(value, dict):
        for key in ("availability", "availabilityStatus", "status", "name", "value"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
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


def finalize_record(
    record: dict[str, Any],
    *,
    normalize_fields: bool = True,
    surface: str | None = None,
) -> dict[str, Any]:
    cleaned = clean_record(record)
    cleaned = strip_record_tracking_params(cleaned, surface=surface)
    return normalize_record_fields(cleaned) if normalize_fields else cleaned
