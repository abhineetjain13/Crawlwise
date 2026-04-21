from __future__ import annotations

import re
from html.parser import HTMLParser
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup
from w3lib.url import url_query_cleaner

from app.services.config.extraction_rules import CURRENCY_SYMBOL_MAP
from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.config.surface_hints import detail_path_hints
from app.services.field_policy import (
    expand_requested_fields,
    field_allowed_for_surface,
    get_surface_field_aliases,
    normalize_field_key,
)
from app.services.normalizers import normalize_record_fields

PRODUCT_URL_HINTS = detail_path_hints("ecommerce_detail")
JOB_URL_HINTS = detail_path_hints("job_detail")
_CURRENCY_SYMBOL_PATTERN = "|".join(
    re.escape(str(symbol))
    for symbol in sorted(
        (str(symbol) for symbol in dict(CURRENCY_SYMBOL_MAP or {}).keys() if symbol),
        key=len,
        reverse=True,
    )
) or r"(?!)"  # Never-matching pattern if no symbols defined
PRICE_RE = re.compile(
    rf"(?:(?:{_CURRENCY_SYMBOL_PATTERN})\s*\d[\d.,]*|\d[\d.,]*\s*(?:{_CURRENCY_SYMBOL_PATTERN}))"
)
_UNMARKED_PRICE_RE = re.compile(r"\d[\d.,]*")
_CURRENCY_CODE_RE = re.compile(r"\b([A-Z]{3})\b")
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
# Price-like fields: string values must contain at least one digit to be valid
_PRICE_FIELD_NAMES = {"price", "sale_price", "original_price", "discount_amount"}
# Integer-only fields: string values like "out_of_stock" should be nulled
_INTEGER_FIELD_NAMES = {"stock_quantity", "variant_count", "image_count"}
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


class _HTMLTextStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html_tags(value: object) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return text
    stripper = _HTMLTextStripper()
    stripper.feed(text)
    stripper.close()
    return stripper.get_text()


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


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in record.items()
        if value not in (None, "", [], {})
    }


def validate_record_for_surface(
    record: dict[str, Any],
    surface: str,
) -> tuple[dict[str, Any], list[str]]:
    logical_fields = {
        key: value for key, value in dict(record).items() if not str(key).startswith("_")
    }
    internal_fields = {
        key: value for key, value in dict(record).items() if str(key).startswith("_")
    }
    validated_fields, errors = validate_and_clean(logical_fields, surface)
    for field_name, value in logical_fields.items():
        if field_name in validated_fields:
            continue
        if field_allowed_for_surface(surface, field_name):
            validated_fields[field_name] = value
    return {
        **clean_record({**logical_fields, **validated_fields}),
        **internal_fields,
    }, errors


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


def direct_record_to_surface_fields(
    record: dict[str, Any],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None = None,
    base_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shaped = dict(base_fields or {})
    source_fields = surface_fields(surface, requested_fields)
    for field_name in source_fields:
        value = coerce_field_value(field_name, dict(record or {}).get(field_name), page_url)
        if value not in (None, "", [], {}):
            shaped[field_name] = value
    return finalize_record(shaped, surface=surface)


def coerce_text(value: object) -> str | None:
    if isinstance(value, str):
        if "<" in value or "&" in value:
            return text_or_none(
                BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
            )
        return text_or_none(value)
    return text_or_none(value)


def extract_price_text(
    value: object,
    *,
    prefer_last: bool = True,
    allow_unmarked: bool = False,
) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    matches = list(PRICE_RE.finditer(text))
    if not matches and allow_unmarked:
        matches = list(_UNMARKED_PRICE_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1] if prefer_last else matches[0]
    return clean_text(match.group(0))


def extract_currency_code(value: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    for symbol, code in dict(CURRENCY_SYMBOL_MAP or {}).items():
        if str(symbol) in text:
            return str(code)
    code_match = _CURRENCY_CODE_RE.search(text.upper())
    if code_match:
        return code_match.group(1)
    return None


def coerce_structured_scalar(
    value: object,
    *,
    keys: tuple[str, ...],
) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate in (None, "", [], {}):
                continue
            text = coerce_structured_scalar(candidate, keys=keys)
            if text:
                return text
        return None
    if isinstance(value, list):
        for item in value:
            text = coerce_structured_scalar(item, keys=keys)
            if text:
                return text
        return None
    return coerce_text(value)


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
    if field_name in {"currency", "salary_currency"} and isinstance(value, str):
        currency_code = extract_currency_code(value)
        if currency_code:
            return currency_code
        text = coerce_text(value)
        if text and re.fullmatch(r"[A-Za-z]{3}", text):
            return text.upper()
        return text
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
    if field_name in {"color", "size"}:
        return coerce_structured_scalar(
            value,
            keys=(field_name, "name", "title", "label", "value", "text"),
        )
    # Reject non-numeric sentinel strings for price fields (e.g. "unavailable", "contact us")
    if field_name in _PRICE_FIELD_NAMES and isinstance(value, str):
        text = coerce_text(value)
        if text and not re.search(r"\d", text):
            return None
        return text or None
    # Reject non-numeric sentinel strings for integer fields (e.g. "out_of_stock")
    if field_name in _INTEGER_FIELD_NAMES and isinstance(value, str):
        text = coerce_text(value)
        if text and not re.search(r"\d", text):
            return None
        return text or None
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
        normalized_rows: list[object] = []
        for item in value:
            normalized = coerce_field_value(field_name, item, page_url)
            if normalized in (None, "", [], {}):
                continue
            if isinstance(normalized, list):
                normalized_rows.extend(normalized)
            else:
                normalized_rows.append(normalized)
        return normalized_rows or None
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


# ---------------------------------------------------------------------------
# Output schema validation
# ---------------------------------------------------------------------------

# Defines the allowed Python type names for key fields per surface.
# Used by validate_and_clean() to catch type-mismatched values after extraction.
_OUTPUT_SCHEMAS: dict[str, dict[str, frozenset[str]]] = {
    "ecommerce_listing": {
        "title": frozenset({"str", "NoneType"}),
        "url": frozenset({"str", "NoneType"}),
        "price": frozenset({"str", "NoneType"}),
        "sale_price": frozenset({"str", "NoneType"}),
        "original_price": frozenset({"str", "NoneType"}),
        "image_url": frozenset({"str", "NoneType"}),
        "additional_images": frozenset({"list", "NoneType"}),
    },
    "ecommerce_detail": {
        "price": frozenset({"str", "NoneType"}),
        "sale_price": frozenset({"str", "NoneType"}),
        "original_price": frozenset({"str", "NoneType"}),
        "variants": frozenset({"list", "NoneType"}),
        "stock_quantity": frozenset({"int", "str", "NoneType"}),
        "image_url": frozenset({"str", "NoneType"}),
        "additional_images": frozenset({"list", "NoneType"}),
    },
    "job_listing": {
        "title": frozenset({"str", "NoneType"}),
        "company": frozenset({"str", "NoneType"}),
        "location": frozenset({"str", "NoneType"}),
        "url": frozenset({"str", "NoneType"}),
        "apply_url": frozenset({"str", "NoneType"}),
        "salary": frozenset({"str", "NoneType"}),
    },
    "job_detail": {
        "salary": frozenset({"str", "NoneType"}),
        "salary_range": frozenset({"dict", "str", "NoneType"}),
    },
}


def validate_and_clean(
    record: dict[str, Any],
    surface: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a post-extraction record against the surface output schema.

    Fields whose type does not match the expected schema are nullified so they
    are dropped by the downstream ``clean_record`` pass.  Returns a
    ``(cleaned_record, errors)`` tuple where *errors* is a list of human-readable
    messages describing each violation found.

    Example usage::

        cleaned, errors = validate_and_clean(record, "ecommerce_detail")
        if errors:
            logger.warning("Schema violations: %s", errors)
        record = clean_record(cleaned)
    """
    normalized_surface = str(surface or "").strip().lower()
    schema = _OUTPUT_SCHEMAS.get(normalized_surface, {})
    if not schema:
        return dict(record), []
    errors: list[str] = []
    cleaned: dict[str, Any] = {}
    for field_name, value in record.items():
        if field_name not in schema:
            continue
        if value in (None, "", [], {}):
            cleaned[field_name] = value
            continue
        expected_types = schema[field_name]
        actual_type = type(value).__name__
        if actual_type not in expected_types:
            errors.append(
                f"{field_name}: expected one of {sorted(expected_types)}, "
                f"got {actual_type!r} (value={str(value)[:60]!r})"
            )
            cleaned[field_name] = None  # Nullify so clean_record drops it
        else:
            cleaned[field_name] = value
    return cleaned, errors
