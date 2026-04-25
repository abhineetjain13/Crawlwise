from __future__ import annotations

import re
from html.parser import HTMLParser
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup
from w3lib.url import url_query_cleaner

from app.services.config.extraction_rules import (
    CURRENCY_ALIAS_PATTERNS,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_BRAND_MAX_WORDS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_WEAK_TITLES,
    NOISY_PRODUCT_ATTRIBUTE_KEYS,
)
from app.services.config.field_mappings import CANONICAL_SCHEMAS, FIELD_ALIASES
from app.services.config.surface_hints import detail_path_hints
from app.services.field_policy import (
    exact_requested_field_key,
    expand_requested_fields,
    get_surface_field_aliases,
    normalize_field_key,
)
from app.services.normalizers import normalize_record_fields

PRODUCT_URL_HINTS = detail_path_hints("ecommerce_detail")
JOB_URL_HINTS = detail_path_hints("job_detail")
_FIELD_ALIASES = FIELD_ALIASES if isinstance(FIELD_ALIASES, dict) else {}
_CURRENCY_SYMBOL_PATTERN = "|".join(
    re.escape(str(symbol))
    for symbol in sorted(
        (str(symbol) for symbol in dict(CURRENCY_SYMBOL_MAP or {}).keys() if symbol),
        key=len,
        reverse=True,
    )
) or r"(?!)"  # Never-matching pattern if no symbols defined
_CURRENCY_CODE_PATTERN = "|".join(
    re.escape(str(code))
    for code in sorted(
        (
            str(code)
            for code in tuple(CURRENCY_CODES or ())
            if isinstance(code, str) and len(str(code)) == 3
        ),
        key=len,
        reverse=True,
    )
) or r"(?!)"
PRICE_RE = re.compile(
    rf"(?:(?:{_CURRENCY_SYMBOL_PATTERN})\s*\d[\d.,]*|\d[\d.,]*\s*(?:{_CURRENCY_SYMBOL_PATTERN}))"
)
_CODED_PRICE_RE = re.compile(
    rf"(?:(?:\b(?:{_CURRENCY_CODE_PATTERN})\b)\s*\d[\d.,]*|\d[\d.,]*\s*(?:\b(?:{_CURRENCY_CODE_PATTERN})\b))"
)
_UNMARKED_PRICE_RE = re.compile(r"\d[\d.,]*")
_CURRENCY_CODE_RE = re.compile(rf"\b({_CURRENCY_CODE_PATTERN})\b")
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
_NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    normalize_field_key(str(key or ""))
    for key in tuple(NOISY_PRODUCT_ATTRIBUTE_KEYS or ())
    if str(key or "").strip()
) | {"availability", "available", "in_stock", "stock_status"}
LONG_TEXT_FIELDS = {
    "benefits",
    "care",
    "description",
    "features",
    "materials",
    "product_details",
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
TRACKING_DETAIL_CONTEXT_EXACT_KEYS = {
    "content_source",
    "external",
    "pf_from",
    "qs",
    "sr_prefetch",
}
TRACKING_PARAM_PREFIXES = ("utm_", "click_")
TRACKING_STRIP_URL_FIELDS = {"apply_url", "source_url", "url"}
_PRESERVED_SHORT_QUERY_KEYS = {"id", "ids", "p", "page", "pid", "q", "sku", "v"}
_SHORT_TRACKING_VALUE_RE = re.compile(r"^[a-z0-9_-]{0,8}$", re.I)
_REVIEW_TITLE_RE = re.compile(r"^\s*\d[\d,\s]*\s+reviews?\s*$", re.I)
_LISTING_UTILITY_TITLE_REGEXES = tuple(
    re.compile(pattern, re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS
)


def clean_text(value: object) -> str:
    text = unescape(str(value or "")).strip()
    return WHITESPACE_RE.sub(" ", text)


def is_title_noise(title: object) -> bool:
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if "undefined" in lowered or lowered in {"nan", "none", "null"}:
        return True
    if cleaned.isdigit():
        return True
    if _REVIEW_TITLE_RE.fullmatch(cleaned):
        return True
    if "star" in lowered and RATING_RE.search(lowered) and len(cleaned.split()) <= 4:
        return True
    if lowered in LISTING_TITLE_CTA_TITLES:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True
    if any(pattern.search(lowered) for pattern in LISTING_ACTION_NOISE_PATTERNS):
        return True
    if any(pattern.search(lowered) for pattern in _LISTING_UTILITY_TITLE_REGEXES):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)


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


def slug_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if token
    ]


def infer_brand_from_title_marker(title: object) -> str | None:
    text = clean_text(title)
    if not text:
        return None
    leading_marker = next((marker for marker in ("\u2122", "\u00ae") if text.startswith(marker)), "")
    if leading_marker:
        leading_token = clean_text(text[len(leading_marker) :]).split(" ", 1)[0].strip()
        brand = clean_text(f"{leading_marker}{leading_token}") if leading_token else ""
        if not brand or len(slug_tokens(brand)) > LISTING_BRAND_MAX_WORDS:
            return None
        return brand
    marker_positions = [
        index
        for marker in ("\u2122", "\u00ae")
        if (index := text.find(marker)) >= 0
    ]
    if not marker_positions:
        return None
    brand = clean_text(text[: min(marker_positions) + 1])
    if not brand or len(slug_tokens(brand)) > LISTING_BRAND_MAX_WORDS:
        return None
    return brand


def infer_brand_from_product_url(*, url: str, title: object) -> str | None:
    title_parts = slug_tokens(title)
    if len(title_parts) < 2:
        return None
    path_parts = [
        part.split(".", 1)[0]
        for part in (urlparse(str(url or "")).path or "").split("/")
        if part
    ]
    for path_part in reversed(path_parts):
        path_tokens = slug_tokens(path_part)
        if len(path_tokens) <= len(title_parts):
            continue
        for start in range(1, len(path_tokens) - len(title_parts) + 1):
            if path_tokens[start : start + len(title_parts)] != title_parts:
                continue
            brand_tokens = path_tokens[:start]
            if not brand_tokens or len(brand_tokens) > LISTING_BRAND_MAX_WORDS:
                continue
            return " ".join(token.capitalize() for token in brand_tokens)
    return None


def absolute_url(base_url: str, candidate: object) -> str:
    text = clean_text(candidate)
    if not text:
        return ""
    return urljoin(base_url, text)


def same_host(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    return bool(candidate_host) and candidate_host == base_host


_MULTI_PART_PUBLIC_SUFFIXES = frozenset(
    {
        "ac.in",
        "co.in",
        "co.jp",
        "co.kr",
        "co.nz",
        "co.uk",
        "com.au",
        "com.br",
        "com.cn",
        "com.mx",
        "com.sg",
        "com.tr",
        "edu.au",
        "gov.in",
        "gov.uk",
        "net.au",
        "org.au",
        "org.uk",
    }
)


def registrable_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().strip(".")
    if not host:
        return ""
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in _MULTI_PART_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(base_url: str, candidate_url: str) -> bool:
    base_site = registrable_host(base_url)
    candidate_site = registrable_host(candidate_url)
    return bool(candidate_site) and candidate_site == base_site


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in record.items()
        if value not in (None, "", [], {})
    }


def validate_record_for_surface(
    record: dict[str, Any],
    surface: str,
    *,
    requested_fields: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    logical_fields = {
        key: value for key, value in dict(record).items() if not str(key).startswith("_")
    }
    internal_fields = {
        key: value for key, value in dict(record).items() if str(key).startswith("_")
    }
    allowed_fields = {
        normalize_field_key(field_name)
        for field_name in surface_fields(surface, requested_fields)
    }
    validated_fields, errors = validate_and_clean(logical_fields, surface)
    for field_name, value in logical_fields.items():
        if field_name in validated_fields:
            continue
        if normalize_field_key(field_name) in allowed_fields:
            validated_fields[field_name] = value
    return {
        **clean_record(validated_fields),
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
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    has_detail_context_tracking = any(
        _is_tracking_detail_context_key(key)
        for key, _ in query_pairs
    )
    removable_keys: list[str] = []
    for key, value in query_pairs:
        if _is_tracking_query_key(key) or _is_short_tracking_flag(
            key,
            value,
            has_detail_context_tracking=has_detail_context_tracking,
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


def _is_tracking_query_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAM_EXACT_KEYS | TRACKING_DETAIL_CONTEXT_EXACT_KEYS or any(
        lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES
    )


def _is_tracking_detail_context_key(key: str) -> bool:
    return key.lower() in TRACKING_DETAIL_CONTEXT_EXACT_KEYS


def _is_short_tracking_flag(
    key: str,
    value: str,
    *,
    has_detail_context_tracking: bool,
) -> bool:
    lowered = key.lower()
    if not has_detail_context_tracking or lowered in _PRESERVED_SHORT_QUERY_KEYS:
        return False
    if len(lowered) > 3:
        return False
    normalized_value = str(value or "").strip().lower()
    if len(normalized_value) > 8:
        return False
    if normalized_value and _SHORT_TRACKING_VALUE_RE.fullmatch(normalized_value) is None:
        return False
    return True


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
    allowed_fields = set(fields)
    if "url" not in fields:
        fields.append("url")
        allowed_fields.add("url")
    for field_name in list(requested_fields or []):
        exact_field = exact_requested_field_key(field_name)
        if (
            exact_field
            and exact_field not in fields
            and (exact_field in allowed_fields or exact_field not in ALL_CANONICAL_FIELDS)
        ):
            fields.append(exact_field)
    for field_name in expand_requested_fields(list(requested_fields or [])):
        if (
            field_name
            and field_name not in fields
            and (field_name in allowed_fields or field_name not in ALL_CANONICAL_FIELDS)
        ):
            fields.append(field_name)
    return fields


def surface_alias_lookup(
    surface: str,
    requested_fields: list[str] | None,
) -> dict[str, str]:
    fields = surface_fields(surface, requested_fields)
    aliases = get_surface_field_aliases(surface)
    lookup: dict[str, str] = {}
    for requested in list(requested_fields or []):
        normalized_requested = normalize_field_key(requested)
        exact_field = exact_requested_field_key(requested)
        if normalized_requested:
            lookup[normalized_requested] = exact_field or normalized_requested
        if exact_field:
            lookup[exact_field] = exact_field
        if normalized_requested and exact_field:
            lookup[normalized_requested] = exact_field
    for canonical in fields:
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            lookup[normalized_canonical] = canonical
        canonical_aliases = list(aliases.get(canonical, []))
        if not canonical_aliases:
            canonical_aliases = list(_FIELD_ALIASES.get(canonical, []))
        for alias in canonical_aliases:
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
    if not matches:
        matches = list(_CODED_PRICE_RE.finditer(text.upper()))
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
    for pattern, code in dict(CURRENCY_ALIAS_PATTERNS or {}).items():
        if re.search(str(pattern), text, flags=re.I):
            return str(code)
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


def _sanitize_option_scalar(field_name: str, value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    cleaned = text
    if field_name == "color":
        match = re.fullmatch(r"select\s+(.+?)\s+color", cleaned, flags=re.I)
        if match is not None:
            cleaned = clean_text(match.group(1))
        cleaned = re.sub(r"^color\s*:\s*", "", cleaned, flags=re.I)
        cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = re.split(r"\bsize(?:\s*\([^)]*\))?\b", cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = clean_text(cleaned)
        if not cleaned or re.search(r"\d+\s*x\s*\d+", cleaned):
            return None
    elif field_name == "size":
        cleaned = re.sub(r"^size\s*:\s*", "", cleaned, flags=re.I)
        cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = clean_text(cleaned)
    return cleaned or None


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
        text = str(value or "").strip()
        if not text:
            return results
        embedded_urls = re.findall(r"https?://[^\s,]+", text)
        if len(embedded_urls) >= 2:
            for candidate in embedded_urls:
                absolute = absolute_url(
                    page_url,
                    _trim_trailing_url_candidate(candidate),
                )
                if absolute:
                    results.append(absolute)
            return results
        absolute = absolute_url(page_url, _trim_trailing_url_candidate(text))
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


def _trim_trailing_url_candidate(value: str) -> str:
    trimmed = str(value or "").rstrip(".,:;!?}'\"")
    while trimmed.endswith((")", "]")):
        closer = trimmed[-1]
        opener = "(" if closer == ")" else "["
        if trimmed.count(closer) <= trimmed.count(opener):
            break
        trimmed = trimmed[:-1].rstrip(".,:;!?}'\"")
    return trimmed


def coerce_variant_axes(value: object) -> dict[str, list[str]] | None:
    if not isinstance(value, dict) or not value:
        return None
    normalized_axes: dict[str, list[str]] = {}
    for raw_axis_name, raw_axis_values in value.items():
        axis_name = text_or_none(raw_axis_name)
        if not axis_name:
            continue
        if not isinstance(raw_axis_values, list):
            continue
        cleaned_values: list[str] = []
        seen: set[str] = set()
        for item in raw_axis_values:
            if isinstance(item, (dict, list, tuple, set)):
                continue
            cleaned = text_or_none(item)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned_values.append(cleaned)
        if not cleaned_values:
            continue
        normalized_axes[axis_name] = cleaned_values
    return normalized_axes or None


def coerce_product_attributes(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    cleaned = _clean_product_attribute_dict(value)
    return cleaned or None


def _product_attribute_key_is_noise(value: object) -> bool:
    normalized = normalize_field_key(str(value or ""))
    return bool(normalized and normalized in _NOISY_PRODUCT_ATTRIBUTE_KEYS)


def _product_attribute_row_is_noise(value: dict[str, object]) -> bool:
    row_id = value.get("Id") or value.get("id") or value.get("name") or value.get("label")
    return _product_attribute_key_is_noise(row_id)


def _clean_product_attribute_value(value: object) -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        if _product_attribute_row_is_noise(value):
            return None
        return _clean_product_attribute_dict(value)
    if isinstance(value, list):
        rows = [
            cleaned
            for item in value
            if (cleaned := _clean_product_attribute_value(item)) not in (None, "", [], {})
        ]
        return rows or None
    return value


def _clean_product_attribute_dict(value: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, item in value.items():
        if _product_attribute_key_is_noise(key):
            continue
        cleaned_value = _clean_product_attribute_value(item)
        if cleaned_value not in (None, "", [], {}):
            cleaned[str(key)] = cleaned_value
    return cleaned


def coerce_availability_dict(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    explicit_keys = ("availability", "availabilityStatus", "status")
    for key in explicit_keys:
        candidate = value.get(key)
        if candidate not in (None, "", [], {}):
            if isinstance(candidate, bool):
                return "in_stock" if candidate else "out_of_stock"
            return coerce_text(candidate)
    if len(value) == 1:
        for key in ("name", "value"):
            candidate = value.get(key)
            if candidate not in (None, "", [], {}):
                if isinstance(candidate, bool):
                    return "in_stock" if candidate else "out_of_stock"
                return coerce_text(candidate)
    return None


def coerce_field_value(field_name: str, value: object, page_url: str) -> object | None:
    if value in (None, "", [], {}):
        return None
    if field_name == "variant_axes":
        return coerce_variant_axes(value)
    if field_name == "product_attributes":
        return coerce_product_attributes(value)
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
        return _sanitize_option_scalar(
            field_name,
            coerce_structured_scalar(
                value,
                keys=(field_name, "name", "title", "label", "value", "text"),
            ),
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
            "lowPrice",
            "minPrice",
            "minValue",
            "highPrice",
            "maxPrice",
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
    if field_name == "availability" and isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if field_name == "availability" and isinstance(value, dict):
        return coerce_availability_dict(value)
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
