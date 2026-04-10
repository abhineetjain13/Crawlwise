# Value normalization rules.
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app.services.pipeline_config import (
    CANDIDATE_ALPHA_CHAR_PATTERN,
    CANDIDATE_ANALYTICS_DIMENSION_TOKEN_PATTERN,
    CANDIDATE_ASSET_FILE_EXTENSIONS,
    CANDIDATE_AVAILABILITY_NOISE_PHRASES,
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_COLOR_CSS_NOISE_TOKENS,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_GENERIC_CATEGORY_VALUES,
    CANDIDATE_GENERIC_TITLE_VALUES,
    CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS,
    CANDIDATE_IMAGE_FILE_EXTENSIONS,
    CANDIDATE_IMAGE_NOISE_TOKENS,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_IMAGE_URL_HINT_TOKENS,
    CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT,
    CANDIDATE_PLACEHOLDER_VALUES,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_PROMO_ONLY_TITLE_PATTERN,
    CANDIDATE_RATING_WORD_TOKENS,
    CANDIDATE_REVIEW_COUNT_TOKENS,
    CANDIDATE_SALARY_TOKENS,
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_SIZE_CSS_NOISE_TOKENS,
    CANDIDATE_SIZE_PACKAGE_TOKENS,
    CANDIDATE_TITLE_NOISE_PHRASES,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
    CANDIDATE_URL_ABSOLUTE_PREFIXES,
    CANDIDATE_URL_SUFFIXES,
    COLOR_NOISE_TOKENS,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    HTTP_URL_PREFIXES,
    PRICE_FIELDS,
    PRICE_REGEX,
    SALARY_RANGE_REGEX,
    SIZE_NOISE_TOKENS,
)
from bs4 import BeautifulSoup

_UI_NOISE_TOKEN_RE = (
    re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_NOISE_TOKEN_PATTERN
    else None
)
_UI_ICON_TOKEN_RE = (
    re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_ICON_TOKEN_PATTERN
    else None
)
_SCRIPT_NOISE_RE = (
    re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE)
    if CANDIDATE_SCRIPT_NOISE_PATTERN
    else None
)
_PROMO_ONLY_TITLE_RE = (
    re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE)
    if CANDIDATE_PROMO_ONLY_TITLE_PATTERN
    else None
)
_CURRENCY_TOKEN_RE = re.compile(r"\b[A-Z]{3}\b")
_CURRENCY_AFTER_AMOUNT_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*([A-Z]{3})\b")
_CURRENCY_BEFORE_AMOUNT_RE = re.compile(r"\b([A-Z]{3})\s*\d[\d,]*(?:\.\d+)?\b")
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_BREADCRUMB_SEPARATOR_RE = re.compile(r"\s>\s|(?:[^/]+/){2,}[^/]+|[^/]+/[^/]+/[^/]*")
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")
_VARIANT_SELECTOR_PROMPT_RE = re.compile(
    r"^(?:select|choose|pick)\s+(?:a|an|the|your)?\s*"
    r"(?:size|sizes|color|colors|colour|colours|option|options|variant|variants|"
    r"style|styles|fit|fits|waist|length|width)\s*$",
    re.IGNORECASE,
)
_CROSSFIELD_VARIANT_VALUE_RE = re.compile(
    r"^(?:size|sizes|waist|length|width|fit|fits)\s*[:\-]?\s*"
    r"[A-Za-z0-9.+/-]{1,8}(?:\s*,\s*\.?)?$",
    re.IGNORECASE,
)
_TITLE_NOISE_WORDS = {"home", "cart", "sign in", "search results", "access denied", "loading..."}
_SALARY_NOISE_PATTERN = re.compile(
    r"\b(?:competitive|depends on experience|doe)\b", re.IGNORECASE
)
_IMAGE_NOISE_PATTERN = re.compile(
    r"\b(?:icon|logo|sprite|placeholder|avatar)\b", re.IGNORECASE
)
_NOISE_URL_SUFFIXES = (".js", ".css", ".woff", ".woff2", ".svg", "spinner.gif")
_TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "ref_src")
_GENERIC_SENTINEL_VALUES = {"object", "array", "boolean", "null", "none", "undefined", "unknown", "pending", "n/a", "na"}
_MAX_REGEX_INPUT_LEN = 500


def _compile_noise_token_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    if not tokens:
        return re.compile(r"(?!.*)", re.IGNORECASE)
    parts: list[str] = []
    for token in tokens:
        escaped = re.escape(token)
        parts.append(rf"\b{escaped}\b" if token.isalnum() else escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


_COLOR_NOISE_RE = _compile_noise_token_pattern(COLOR_NOISE_TOKENS)
_SIZE_NOISE_RE = _compile_noise_token_pattern(SIZE_NOISE_TOKENS)


def normalize_value(field_name: str, value: object, *, base_url: str = "") -> object:
    if not isinstance(value, str):
        return value
    text = _normalized_candidate_text(unescape(value))
    _ = base_url
    if not text:
        return ""
    lowered = text.lower()
    if lowered in _GENERIC_SENTINEL_VALUES or lowered in CANDIDATE_PLACEHOLDER_VALUES:
        return ""
    if _is_color_field(field_name):
        cleaned = _coerce_color_field(text)
        return cleaned or ""
    if _is_size_field(field_name):
        cleaned = _strip_ui_noise(_strip_html(text))
        if _SIZE_NOISE_RE.search(cleaned.lower()):
            return ""
        cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
        tokens = [token.strip() for token in re.split(r"[\s,/|]+", cleaned) if token.strip()]
        if tokens and all(re.fullmatch(r"[A-Za-z0-9.+-]{1,5}", token) for token in tokens):
            return ", ".join(tokens)
        return cleaned
    if _is_image_primary_field(field_name):
        return _strip_tracking_params(_resolve_candidate_url(text, base_url) or text)
    if _is_image_collection_field(field_name):
        return ", ".join(_extract_image_urls(text, base_url=base_url))
    if _is_numeric_field(field_name):
        match = re.search(PRICE_REGEX, text)
        return match.group(0) if match else text
    if _is_description_field(field_name):
        return " ".join(_strip_html(text, preserve_paragraphs=True).split()).strip()
    if _is_availability_field(field_name):
        coerced = _coerce_availability_field(text)
        return coerced if coerced is not None else text
    if _is_category_field(field_name) and lowered in {
        item.lower() for item in CANDIDATE_GENERIC_CATEGORY_VALUES
    }:
        return ""
    if _is_title_field(field_name):
        return _coerce_title_field(text) or ""
    if _is_entity_name_field(field_name):
        cleaned = _strip_ui_noise(_strip_html(text))
        return cleaned or text
    if _is_currency_field(field_name):
        return extract_currency_hint(text) or text
    if lowered in CANDIDATE_GENERIC_TITLE_VALUES:
        return ""
    return text


def normalize_candidate_value(field_name: str, value: object, *, base_url: str = "") -> object:
    return _preprocess_value(field_name, value, base_url=base_url)

def normalize_and_validate_value(
    field_name: str, value: object, *, base_url: str = ""
) -> object | None:
    return validate_value(field_name, normalize_candidate_value(field_name, value, base_url=base_url))

def dispatch_string_field_coercer(field_name: str, value: str, *, base_url: str = "") -> object | None:
    return _dispatch_string_field_coercer(field_name, value, base_url=base_url)

def _is_empty_value(value: object) -> bool:
    return value in (None, "", [], {})

def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_rich_candidate_text(value: str) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return _normalized_candidate_text(text)
    rendered = _strip_html(text, preserve_paragraphs=True)
    lines = []
    for raw_line in rendered.splitlines():
        line = _normalized_candidate_text(raw_line)
        if line:
            lines.append(f"• {line[1:].strip()}" if line.startswith(("-", "*")) else line)
    return "\n".join(lines).strip()


def _parse_json_like_value(value: str) -> dict | list | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if candidate[:1] not in "{[":
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _coerce_url_field(value: str, base_url: str) -> str | None:
    return _resolve_candidate_url(value, base_url) or None


def _coerce_image_field(
    value: object, base_url: str, *, primary: bool = True
) -> str | None:
    images = _extract_image_urls(value, base_url=base_url)
    return (images[0] if primary else ", ".join(images)) if images else None


def _coerce_price_field(value: str) -> str | None:
    text = _normalized_candidate_text(value)
    numeric = re.search(PRICE_REGEX, text)
    if not numeric:
        return None
    if re.fullmatch(r"\d+", text):
        try:
            amount = float(text)
        except (TypeError, ValueError):
            return None
        if amount < 10:
            return None
    return text


def _coerce_currency_field(value: str) -> str | None:
    return extract_currency_hint(value) or None


def _coerce_color_field(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned or _looks_like_variant_selector_text(cleaned):
        return None
    lowered = cleaned.lower()
    if any(token in lowered for token in CANDIDATE_COLOR_CSS_NOISE_TOKENS):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if "colors" in lowered and cleaned.split()[0].isdigit():
        return None
    if re.search(r"!\d", cleaned) or re.search(r"(?<![A-Za-z ])\s*:\s*!", cleaned):
        return None
    hex_match = _HEX_COLOR_RE.search(lowered)
    if hex_match:
        return hex_match.group(0)
    if _COLOR_NOISE_RE.search(lowered):
        return None
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if len(cleaned) > 40 or len(cleaned.split()) > 6:
        return None
    if any(phrase in lowered for phrase in CANDIDATE_AVAILABILITY_NOISE_PHRASES):
        return None
    return cleaned or None


def _coerce_size_field(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if len(cleaned) > 100 or "gsm:" in lowered or "weight:" in lowered or "lbs" in lowered:
        return None
    if any(token in lowered for token in CANDIDATE_SIZE_CSS_NOISE_TOKENS):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?\s*[A-Za-z]{1,8}", cleaned):
        return cleaned
    if any(token in lowered for token in CANDIDATE_SIZE_PACKAGE_TOKENS):
        return cleaned
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    if re.fullmatch(r"[A-Za-z0-9.+-]+(?:\s+[A-Za-z0-9.+-]+){0,3}", cleaned):
        return cleaned
    tokens = [token.strip() for token in re.split(r"[\s,/|]+", cleaned) if token.strip()]
    if tokens and all(re.fullmatch(r"[A-Za-z0-9.+-]{1,5}", token) for token in tokens):
        return "/".join(tokens)
    return cleaned or None


def _coerce_category_field(value: str) -> str | None:
    cleaned = _normalized_candidate_text(value)
    lowered = cleaned.lower()
    if lowered in _GENERIC_SENTINEL_VALUES:
        return None
    if lowered in {item.lower() for item in CANDIDATE_GENERIC_CATEGORY_VALUES}:
        return None
    if "schema.org" in lowered or "cookie" in lowered or "sign in" in lowered:
        return None
    if lowered in {"regular", "petite", "plus", "tall", "maternity", "slim", "fitted", "oversized", "husky"}:
        return None
    if ">" in cleaned or "/" in cleaned:
        parts = [part.strip() for part in re.split(r"\s*(?:>|/)\s*", cleaned) if part.strip()]
        if parts and parts[0].lower() == "home":
            parts = parts[1:]
        cleaned = " > ".join(parts)
        lowered = cleaned.lower()
    if not cleaned or lowered in _GENERIC_SENTINEL_VALUES:
        return None
    if lowered in {"detail-page", "product", "category", "page", "object"} or re.fullmatch(r"e\d+", lowered):
        return None
    if re.fullmatch(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", cleaned):
        return None
    return cleaned


def _coerce_rating_field(value: str) -> str | None:
    lowered = value.lower()
    star_word_match = re.search(r"\bstar-rating\s+([a-z]+)\b", lowered)
    if star_word_match:
        token = star_word_match.group(1)
        return token.capitalize() if token else None
    numeric_match = re.search(r"\d+(?:\.\d+)?", value)
    if numeric_match:
        return numeric_match.group(0)
    rating_tokens = [re.escape(token) for token in CANDIDATE_RATING_WORD_TOKENS if token]
    word_match = re.search(r"\b(" + "|".join(rating_tokens) + r")\b", lowered) if rating_tokens else None
    if word_match:
        return word_match.group(1).capitalize()
    return value if re.search(CANDIDATE_ALPHA_CHAR_PATTERN, value) else None


def _build_salary_money_re() -> re.Pattern[str]:
    currency_symbols = sorted(
        {re.escape(str(symbol).strip()) for symbol in CURRENCY_SYMBOL_MAP if str(symbol).strip()}
    )
    symbol_pattern = "(?:" + "|".join(currency_symbols) + ")" if currency_symbols else r"[$€£₹]"
    currency_codes = sorted(
        {re.escape(str(code).strip().upper()) for code in CURRENCY_CODES if str(code).strip()}
    )
    code_pattern = "(?:" + "|".join(currency_codes) + ")" if currency_codes else r"(?:USD|EUR|GBP|INR)"
    pattern = (
        rf"(?<!\w)(?:{symbol_pattern}\s*\d[\d,.]*|"
        rf"\b{code_pattern}\s*\d[\d,.]*|"
        rf"\d[\d,.]*\s*{code_pattern}\b)"
    )
    return re.compile(pattern, re.IGNORECASE)


_SALARY_MONEY_RE = _build_salary_money_re()


def _coerce_salary_field(value: str) -> str | None:
    if len(value) > _MAX_REGEX_INPUT_LEN:
        return None
    salary_match = re.search(SALARY_RANGE_REGEX, value)
    if salary_match:
        return _normalized_candidate_text(salary_match.group(0))
    money_match = _SALARY_MONEY_RE.search(value)
    if money_match:
        result = _normalized_candidate_text(money_match.group(0))
        unit_match = re.match(
            r"\s*(?:/\s*)?(hour|hr|year|yr|month|mo|week|wk|day)\b",
            value[money_match.end() :],
            re.IGNORECASE,
        )
        if unit_match:
            result = f"{result}/{unit_match.group(1).lower()}"
        return result
    numeric = re.search(PRICE_REGEX, value)
    return _normalized_candidate_text(numeric.group(0)) if numeric else None


_SCHEMA_ORG_AVAILABILITY_MAP: dict[str, str] = {
    "instock": "in_stock",
    "outofstock": "out_of_stock",
    "preorder": "preorder",
    "pre-order": "preorder",
    "preorder": "preorder",
    "limitedavailability": "limited_availability",
    "soldout": "out_of_stock",
    "discontinued": "discontinued",
    "backorder": "backorder",
    "instoreonly": "in_store_only",
    "onlineonly": "online_only",
}


def _coerce_availability_field(value: str) -> str | None:
    text = unescape(value).strip()
    lowered = text.lower()
    if lowered == "availability":
        return None
    # Normalize schema.org URIs (e.g. "http://schema.org/InStock" → "in_stock").
    if "schema.org/" in lowered:
        # Extract the token after the last slash.
        tail = lowered.rsplit("/", 1)[-1]
        mapped = _SCHEMA_ORG_AVAILABILITY_MAP.get(tail)
        if mapped:
            return mapped
        # Unrecognized schema.org token — still strip the URI prefix.
        return tail or None
    if re.fullmatch(CANDIDATE_ANALYTICS_DIMENSION_TOKEN_PATTERN, lowered):
        return None
    if any(phrase in lowered for phrase in CANDIDATE_AVAILABILITY_NOISE_PHRASES):
        return None
    return text or None


def _coerce_title_field(value: str) -> str | None:
    cleaned = _strip_ui_noise(_strip_html(value))
    if not cleaned or cleaned.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
        return None
    if _looks_like_variant_selector_text(cleaned):
        return None
    lowered = cleaned.lower()
    if any(phrase in lowered for phrase in CANDIDATE_TITLE_NOISE_PHRASES):
        return None
    if "cookie" in lowered or "sign in" in lowered:
        return None
    if _PROMO_ONLY_TITLE_RE and _PROMO_ONLY_TITLE_RE.match(cleaned):
        return None
    if not re.search(CANDIDATE_ALPHA_CHAR_PATTERN, cleaned):
        return None
    return cleaned


def _coerce_description_field(value: str) -> str | None:
    return _strip_ui_noise(value, preserve_newlines=True) or None


def _coerce_keyword_field(value: str, keywords: set[str]) -> str | None:
    text = _normalized_candidate_text(value)
    if not text:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matches = [sentence for sentence in sentences if any(keyword in sentence.lower() for keyword in keywords)]
    return " ".join(matches) if matches else (None if len(text) > 80 else text)


def _coerce_care_field(value: str) -> str | None:
    return _coerce_keyword_field(
        value,
        {"wash", "dry", "iron", "bleach", "clean", "tumble", "machine", "wipe"},
    )


def _coerce_materials_field(value: str) -> str | None:
    return _coerce_keyword_field(
        value,
        {
            "cotton", "polyester", "spandex", "elastane", "nylon", "leather", "wool",
            "silk", "viscose", "rayon", "linen", "acrylic", "synthetic", "blend",
        },
    )


def _dispatch_string_field_coercer(
    field_name: str, value: str, *, base_url: str = ""
) -> object | None:
    if _is_color_field(field_name):
        return _coerce_color_field(value)
    if _is_size_field(field_name):
        return _coerce_size_field(value)
    if _is_image_primary_field(field_name):
        return _coerce_image_field(value, base_url, primary=True)
    if _is_image_collection_field(field_name):
        return _coerce_image_field(value, base_url, primary=False)
    if _is_url_field(field_name):
        return _coerce_url_field(value, base_url)
    if _is_currency_field(field_name):
        return _coerce_currency_field(value)
    if _is_category_field(field_name):
        return _coerce_category_field(value)
    if _is_numeric_field(field_name) or _field_has_any_token(field_name, CANDIDATE_REVIEW_COUNT_TOKENS):
        return _coerce_price_field(value)
    if _is_salary_field(field_name):
        return _coerce_salary_field(value)
    if _is_availability_field(field_name):
        return _coerce_availability_field(value)
    if _is_title_field(field_name):
        return _coerce_title_field(value)
    if _is_description_field(field_name) or _is_entity_name_field(field_name) or _is_job_text_field(field_name):
        return _coerce_description_field(value)
    if _field_token(field_name) in {"rating", "reviewrating", "starrating"}:
        return _coerce_rating_field(value)
    if _field_token(field_name) == "care":
        return _coerce_care_field(value)
    if _field_token(field_name) == "materials":
        return _coerce_materials_field(value)
    return value or None


def _preprocess_value(field_name: str, value: object, *, base_url: str = "") -> object:
    if _is_empty_value(value) or isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        if not cleaned:
            return ""
        lowered = cleaned.lower()
        if lowered in _GENERIC_SENTINEL_VALUES or lowered in CANDIDATE_PLACEHOLDER_VALUES:
            return ""
        if _is_description_field(field_name) or _is_job_text_field(field_name):
            cleaned = _normalize_rich_candidate_text(cleaned)
        parsed = _parse_json_like_value(cleaned)
        if parsed is not None:
            parsed_value = _preprocess_value(field_name, parsed, base_url=base_url)
            if not _is_empty_value(parsed_value):
                return parsed_value
        coerced = _dispatch_string_field_coercer(field_name, cleaned, base_url=base_url)
        return "" if coerced is None else coerced
    if isinstance(value, (int, float)):
        if _is_title_field(field_name):
            return None
        if _is_numeric_field(field_name):
            return value if float(value) >= 10 else None
        if _is_salary_field(field_name):
            return _coerce_salary_field(str(value)) or ""
        return value
    if isinstance(value, list):
        if _is_description_field(field_name) or _is_job_text_field(field_name):
            parts: list[str] = []
            for item in value:
                coerced = _preprocess_value(field_name, item, base_url=base_url)
                if isinstance(coerced, str) and coerced.strip():
                    parts.append(coerced.strip())
            return " ".join(parts)
        if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
            return _coerce_image_field(value, base_url, primary=_is_image_primary_field(field_name)) or ""
        for item in value:
            coerced = _preprocess_value(field_name, item, base_url=base_url)
            if not _is_empty_value(coerced):
                return coerced
        return None
    if isinstance(value, dict):
        if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
            return _coerce_image_field(value, base_url, primary=_is_image_primary_field(field_name)) or ""
        for key in ("value", "amount", "code", "text", "content", "description", "sentence", "summary", "title", "name", "label"):
            candidate = _preprocess_value(field_name, value.get(key), base_url=base_url)
            if not _is_empty_value(candidate):
                return candidate
        for nested in value.values():
            candidate = _preprocess_value(field_name, nested, base_url=base_url)
            if not _is_empty_value(candidate):
                return candidate
        return None
    return value
def validate_value(field_name: str, value: object) -> object | None:
    """Strict canonical validation gate."""
    if value in (None, "", [], {}):
        return None
    text = ""
    lowered = ""
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        lowered = text.lower()
        if lowered in {"null", "undefined", "n/a", "none", "nan"}:
            return None
    if _is_brand_field(field_name):
        if not isinstance(value, str):
            return value
        if len(text) > 60:
            return None
        if _BREADCRUMB_SEPARATOR_RE.search(text):
            return None
        if "cookie" in lowered or "privacy" in lowered:
            return None
    elif _is_color_field(field_name):
        if not isinstance(value, str):
            return value
        if len(text) > 40:
            return None
        if _looks_like_variant_selector_text(text):
            return None
        if re.search(r"[{};]|rgb\(|rgba\(", lowered):
            return None
        if "#" in lowered:
            if _HEX_COLOR_RE.fullmatch(lowered):
                return text
            return None
        if "cookie" in lowered or "select" in lowered:
            return None
    elif _is_availability_field(field_name):
        if not isinstance(value, str):
            return value
        if len(text) > 150:
            return None
        if re.search(r"dimension\d+|metric\d+", lowered):
            return None
    elif _is_category_field(field_name):
        if not isinstance(value, str):
            return value
        if len(text) > 150:
            return None
        if "cookie" in lowered or "sign in" in lowered:
            return None
        if lowered in {"detail-page", "product", "category", "page", "object"}:
            return None
        if re.fullmatch(r"e\d+", lowered):
            return None
    if not isinstance(value, str):
        return value
    if _is_title_field(field_name) or _is_entity_name_field(field_name):
        if len(text) < 3 or len(text) > 250:
            return None
        if _is_title_field(field_name) and _looks_like_variant_selector_text(text):
            return None
        if lowered in _TITLE_NOISE_WORDS or _NUMERIC_ONLY_RE.fullmatch(text):
            return None
        return text
    if _is_numeric_field(field_name):
        amount = _extract_positive_number(text)
        return text if amount is not None and amount > 0 else None
    if _is_salary_field(field_name):
        if _SALARY_NOISE_PATTERN.search(text) or not re.search(r"\d", text):
            return None
        return text
    if _is_image_collection_field(field_name):
        normalized_urls = _extract_image_urls(text)
        return ", ".join(normalized_urls) if normalized_urls else None
    if _is_image_primary_field(field_name):
        normalized_url = _strip_tracking_params(text)
        if not _is_valid_http_url(normalized_url) or _IMAGE_NOISE_PATTERN.search(
            normalized_url
        ):
            return None
        return normalized_url
    if _is_url_field(field_name):
        normalized_url = _strip_tracking_params(text)
        if not _is_valid_http_url(normalized_url):
            return None
        return normalized_url
    return text
def _resolve_candidate_url(value: str, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        return _strip_tracking_params(f"https:{candidate}")
    if candidate.startswith(CANDIDATE_URL_ABSOLUTE_PREFIXES):
        return _strip_tracking_params(candidate)
    if candidate.startswith("/"):
        return _strip_tracking_params(urljoin(base_url, candidate) if base_url else candidate)
    if re.search(r"^[A-Za-z0-9][^ ]*/[^ ]+$", candidate) and base_url:
        return _strip_tracking_params(urljoin(base_url, candidate))
    return ""


def _extract_image_urls(value: object, *, base_url: str = "") -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def append_url(candidate: str) -> None:
        resolved = _resolve_candidate_url(candidate, base_url)
        if not resolved or not _is_valid_http_url(resolved):
            return
        lowered = resolved.lower()
        path = urlsplit(resolved).path.lower()
        if any(token in lowered for token in CANDIDATE_IMAGE_NOISE_TOKENS):
            return
        if not (
            path.endswith(CANDIDATE_IMAGE_FILE_EXTENSIONS)
            or any(token in lowered for token in CANDIDATE_IMAGE_URL_HINT_TOKENS)
        ):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        urls.append(resolved)

    def collect(node: object) -> None:
        if _is_empty_value(node):
            return
        if isinstance(node, str):
            for part in re.split(r"\s*\|\s*|\s*,\s*(?=https?://|//|/)", node):
                cleaned = _normalized_candidate_text(part)
                if cleaned:
                    append_url(cleaned)
            return
        if isinstance(node, dict):
            for key in CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS:
                candidate = node.get(key)
                if isinstance(candidate, str):
                    append_url(candidate)
            for item in list(node.values())[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                collect(item)
            return
        if isinstance(node, list):
            for item in node[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                collect(item)

    collect(value)
    return urls


def extract_currency_hint(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper_text = text.upper()
    adjacent_matches = [
        match.group(1)
        for match in (
            _CURRENCY_AFTER_AMOUNT_RE.search(upper_text),
            _CURRENCY_BEFORE_AMOUNT_RE.search(upper_text),
        )
        if match and match.group(1) in CURRENCY_CODES
    ]
    if adjacent_matches:
        return adjacent_matches[0]
    for symbol, currency in CURRENCY_SYMBOL_MAP.items():
        if symbol in text:
            return currency
    valid_tokens = [
        token
        for token in _CURRENCY_TOKEN_RE.findall(upper_text)
        if token in CURRENCY_CODES
    ]
    return valid_tokens[0] if valid_tokens else ""


def _strip_tracking_params(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith(HTTP_URL_PREFIXES):
        return text
    parsed = urlsplit(text)
    filtered = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key
        and all(
            not key.lower().startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES
        )
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered, doseq=True), "")
    )


def _is_valid_http_url(value: str) -> bool:
    text = str(value or "").strip()
    if not text.startswith(HTTP_URL_PREFIXES):
        return False
    lowered = text.lower()
    if any(lowered.endswith(suffix) for suffix in _NOISE_URL_SUFFIXES):
        return False
    return not urlsplit(text).path.lower().endswith(CANDIDATE_ASSET_FILE_EXTENSIONS)


def _extract_positive_number(value: str) -> float | None:
    match = re.search(PRICE_REGEX, str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _strip_html(value: str, *, preserve_paragraphs: bool = False) -> str:
    if "<" not in value or ">" not in value:
        return unescape(value).strip()
    soup = BeautifulSoup(value, "html.parser")
    if preserve_paragraphs:
        for tag in soup.find_all(["p", "li", "br", "div"]):
            tag.insert_before("\n")
        text = soup.get_text(" ", strip=False)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return unescape(text).strip()
    text = soup.get_text(" ", strip=True)
    return " ".join(unescape(text).split()).strip()
def _looks_like_variant_selector_text(value: str) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return False
    return bool(
        _VARIANT_SELECTOR_PROMPT_RE.match(text)
        or _CROSSFIELD_VARIANT_VALUE_RE.match(text)
    )
def _strip_ui_noise(value: str, *, preserve_newlines: bool = False) -> str:
    text = unescape(value).strip()
    if not text:
        return ""
    if _UI_ICON_TOKEN_RE:
        text = _UI_ICON_TOKEN_RE.sub(" ", text)
    if _UI_NOISE_TOKEN_RE:
        text = _UI_NOISE_TOKEN_RE.sub(" ", text)
    if _SCRIPT_NOISE_RE:
        text = _SCRIPT_NOISE_RE.sub(" ", text)
    for phrase in CANDIDATE_UI_NOISE_PHRASES:
        if phrase:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.IGNORECASE)
    if preserve_newlines:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.strip(" -|,:;/") for line in text.split("\n"))
    else:
        text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text.strip()


def _field_token(field_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(field_name or "").strip().lower())


def _field_in_group(field_name: str, group_name: str) -> bool:
    return field_name in CANDIDATE_FIELD_GROUPS.get(group_name, set())


def _field_has_any_token(field_name: str, tokens: tuple[str, ...]) -> bool:
    normalized = _field_token(field_name)
    return any(_field_token(token) in normalized for token in tokens if token)


def _is_image_collection_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return _field_in_group(field_name, "image_collection") or any(
        token in normalized for token in ("images", "gallery", "photos", "media")
    )


def _is_image_primary_field(field_name: str) -> bool:
    return _field_in_group(field_name, "image_primary") or (
        _field_has_any_token(field_name, CANDIDATE_IMAGE_TOKENS)
        and not _is_image_collection_field(field_name)
    )


def _is_url_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
        return False
    return _field_in_group(field_name, "url") or any(
        normalized.endswith(_field_token(suffix)) for suffix in CANDIDATE_URL_SUFFIXES
    )


def _is_numeric_field(field_name: str) -> bool:
    return (
        field_name in PRICE_FIELDS
        or _field_in_group(field_name, "numeric")
        or _field_has_any_token(field_name, CANDIDATE_PRICE_TOKENS)
    )
def _is_description_field(field_name: str) -> bool:
    return _field_in_group(field_name, "description") or _field_has_any_token(
        field_name, CANDIDATE_DESCRIPTION_TOKENS
    )


def _is_availability_field(field_name: str) -> bool:
    return _field_in_group(field_name, "availability") or _field_has_any_token(
        field_name, CANDIDATE_AVAILABILITY_TOKENS
    )


def _is_category_field(field_name: str) -> bool:
    return _field_in_group(field_name, "category") or _field_has_any_token(
        field_name, CANDIDATE_CATEGORY_TOKENS
    )


def _is_color_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return normalized in {_field_token("color"), _field_token("colors"), _field_token("color_name")}


def _is_brand_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return normalized in {
        _field_token("brand"), _field_token("vendor"), _field_token("manufacturer"),
        _field_token("company_name"), _field_token("brand_name"), _field_token("designer"), _field_token("brandname"),
    }


def _is_size_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return normalized in {_field_token("size"), _field_token("sizes"), _field_token("variant_size")}


def _is_title_field(field_name: str) -> bool:
    return _field_in_group(field_name, "title")


def _is_job_text_field(field_name: str) -> bool:
    return _field_in_group(field_name, "job_text")


def _is_entity_name_field(field_name: str) -> bool:
    return _field_in_group(field_name, "entity_name")


def _is_currency_field(field_name: str) -> bool:
    return _field_in_group(field_name, "currency") or _field_has_any_token(
        field_name, CANDIDATE_CURRENCY_TOKENS
    )


def _is_salary_field(field_name: str) -> bool:
    return _field_in_group(field_name, "salary") or _field_has_any_token(
        field_name, CANDIDATE_SALARY_TOKENS
    )
