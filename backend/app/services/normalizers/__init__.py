# Value normalization rules.
from __future__ import annotations

from html import unescape
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.services.pipeline_config import (
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_GENERIC_CATEGORY_VALUES,
    CANDIDATE_PLACEHOLDER_VALUES,
    CANDIDATE_GENERIC_TITLE_VALUES,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_PROMO_ONLY_TITLE_PATTERN,
    CANDIDATE_SALARY_TOKENS,
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
    CANDIDATE_URL_SUFFIXES,
    COLOR_NOISE_TOKENS,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    PRICE_FIELDS,
    PRICE_REGEX,
    SIZE_NOISE_TOKENS,
)

_UI_NOISE_TOKEN_RE = re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_NOISE_TOKEN_PATTERN else None
_UI_ICON_TOKEN_RE = re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_ICON_TOKEN_PATTERN else None
_SCRIPT_NOISE_RE = re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE) if CANDIDATE_SCRIPT_NOISE_PATTERN else None
_PROMO_ONLY_TITLE_RE = re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE) if CANDIDATE_PROMO_ONLY_TITLE_PATTERN else None
_CURRENCY_TOKEN_RE = re.compile(r"\b[A-Z]{3}\b")
_CURRENCY_AFTER_AMOUNT_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*([A-Z]{3})\b")
_CURRENCY_BEFORE_AMOUNT_RE = re.compile(r"\b([A-Z]{3})\s*\d[\d,]*(?:\.\d+)?\b")
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")
_TITLE_NOISE_WORDS = {"home", "cart", "sign in", "search results", "access denied", "loading..."}
_SALARY_NOISE_PATTERN = re.compile(r"\b(?:competitive|depends on experience|doe)\b", re.IGNORECASE)
_IMAGE_NOISE_PATTERN = re.compile(r"\b(?:icon|logo|sprite|placeholder|avatar)\b", re.IGNORECASE)
_NOISE_URL_SUFFIXES = (".js", ".css", ".woff", ".woff2", ".svg", "spinner.gif")
_GENERIC_PLATFORM_URLS = {
    "https://www.shopify.com",
    "https://www.linkedin.com/jobs",
}
_LOWERCASED_GENERIC_PLATFORM_URL_PREFIXES = tuple(url.lower() for url in _GENERIC_PLATFORM_URLS)
_TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "ref_src")


def _compile_noise_token_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    """Compile a case-insensitive regular expression that matches any of the given noise tokens.
    Parameters:
        - tokens (tuple[str, ...]): A tuple of token strings to match exactly, using word boundaries for alphanumeric tokens.
    Returns:
        - re.Pattern[str]: A compiled regular expression pattern matching any token, or a pattern that matches nothing when tokens is empty."""
    if not tokens:
        return re.compile(r"(?!x)x", re.IGNORECASE)
    parts: list[str] = []
    for token in tokens:
        escaped = re.escape(token)
        parts.append(rf"\b{escaped}\b" if token.isalnum() else escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


_COLOR_NOISE_RE = _compile_noise_token_pattern(COLOR_NOISE_TOKENS)
_SIZE_NOISE_RE = _compile_noise_token_pattern(SIZE_NOISE_TOKENS)


def normalize_value(field_name: str, value: object) -> object:
    """Normalize a field value based on its field type and content.
    Parameters:
        - field_name (str): Name of the field used to determine normalization rules.
        - value (object): Input value to normalize.
    Returns:
        - object: Normalized value, or the original value when no string normalization applies."""
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if text.lower() in CANDIDATE_PLACEHOLDER_VALUES:
            return ""
        if _is_color_field(field_name):
            return _normalize_color_text(text)
        if _is_size_field(field_name):
            return _normalize_size_text(text)
        if _is_image_primary_field(field_name):
            return _strip_tracking_params(_normalize_image_url(text))
        if _is_image_collection_field(field_name):
            return _strip_tracking_params(_normalize_additional_images(text))
        if _is_numeric_field(field_name):
            match = re.search(PRICE_REGEX, text)
            return match.group(0) if match else text
        if _is_description_field(field_name):
            return _clean_description_text(text)
        if _is_availability_field(field_name):
            return _normalize_availability(text)
        if _is_category_field(field_name) and text.lower() in CANDIDATE_GENERIC_CATEGORY_VALUES:
            return ""
        if _is_title_field(field_name):
            cleaned = _clean_title_text(text)
            return cleaned
        if _is_entity_name_field(field_name):
            cleaned = _strip_ui_noise(text)
            return cleaned or text
        if _is_currency_field(field_name):
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
            valid_tokens = [token for token in _CURRENCY_TOKEN_RE.findall(upper_text) if token in CURRENCY_CODES]
            return valid_tokens[0] if valid_tokens else text
        if text.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
            return ""
        return text
    return value


def validate_value(field_name: str, value: object) -> object | None:
    """Validate and normalize a field value based on the field name.
    Parameters:
        - field_name (str): Name of the field used to determine validation rules.
        - value (object): Input value to validate and normalize.
    Returns:
        - object | None: Normalized value if valid, otherwise None."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        text = " ".join(str(value).split()).strip()
        if not text:
            return None
        if _is_title_field(field_name) or _is_entity_name_field(field_name):
            lowered = text.lower()
            if len(text) < 3 or len(text) > 250:
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
            normalized_urls = [
                normalized_url
                for normalized_url in (
                    _strip_tracking_params(url)
                    for url in _split_image_values(text)
                )
                if _is_valid_http_url(normalized_url) and not _IMAGE_NOISE_PATTERN.search(normalized_url)
            ]
            return ", ".join(normalized_urls) if normalized_urls else None
        if _is_image_primary_field(field_name):
            normalized_url = _strip_tracking_params(text)
            if not _is_valid_http_url(normalized_url) or _IMAGE_NOISE_PATTERN.search(normalized_url):
                return None
            return normalized_url
        if _is_url_field(field_name):
            normalized_url = _strip_tracking_params(text)
            if not _is_valid_http_url(normalized_url):
                return None
            return normalized_url
    return value


def extract_currency_hint(value: object) -> str:
    """Extracts a likely currency code from a text value.
    Parameters:
        - value (object): Input value to inspect for a currency hint.
    Returns:
        - str: The detected currency code, or an empty string if none is found."""
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
    valid_tokens = [token for token in _CURRENCY_TOKEN_RE.findall(upper_text) if token in CURRENCY_CODES]
    return valid_tokens[0] if valid_tokens else ""


def _strip_tracking_params(value: str) -> str:
    """Remove tracking query parameters from a URL string.
    Parameters:
        - value (str): Input string to normalize and strip tracking parameters from.
    Returns:
        - str: The cleaned URL string, or the original trimmed text if it is not an HTTP or HTTPS URL."""
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return text
    parsed = urlsplit(text)
    filtered = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key and not any(key.lower().startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered, doseq=True), ""))


def _is_valid_http_url(value: str) -> bool:
    """Check whether a string is a valid HTTP or HTTPS URL.
    Parameters:
        - value (str): Input value to validate as a URL.
    Returns:
        - bool: True if the value starts with http:// or https:// and is not a known noise or generic platform URL; otherwise False."""
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    if any(lowered.endswith(suffix) for suffix in _NOISE_URL_SUFFIXES):
        return False
    if any(lowered.startswith(prefix) for prefix in _LOWERCASED_GENERIC_PLATFORM_URL_PREFIXES):
        return False
    return True


def _extract_positive_number(value: str) -> float | None:
    """Extract the first positive numeric value from a string-like input.
    Parameters:
        - value (str): Input text to search for a numeric value.
    Returns:
        - float | None: The extracted number as a float, or None if no valid number is found."""
    match = re.search(PRICE_REGEX, str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _normalize_image_url(value: str) -> str:
    urls = _split_image_values(value)
    return urls[0] if urls else value


def _normalize_additional_images(value: str) -> str:
    urls = _split_image_values(value)
    return ", ".join(urls) if urls else value


def _split_image_values(value: str) -> list[str]:
    """Split a delimited string into a unique list of image URLs.
    Parameters:
        - value (str): Input string containing image URLs separated by pipes or commas.
    Returns:
        - list[str]: Ordered list of unique, valid http/https URLs extracted from the input."""
    if not value:
        return []
    parts = re.split(r"\s*\|\s*|\s*,\s*(?=https?://)", value)
    urls: list[str] = []
    seen: set[str] = set()
    for part in parts:
        candidate = unescape(part).strip()
        if not candidate or not candidate.startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _strip_html(value: str, *, preserve_paragraphs: bool = False) -> str:
    """Remove HTML tags from a string and optionally preserve paragraph breaks.
    Parameters:
        - value (str): Input text that may contain HTML markup.
        - preserve_paragraphs (bool): If True, retain line breaks around paragraph-like tags.
    Returns:
        - str: The cleaned text with HTML removed and whitespace normalized."""
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


def _clean_title_text(value: str) -> str:
    """Clean and normalize a title string by removing HTML/UI noise and filtering generic or promo-only values.
    Parameters:
        - value (str): Raw title text to clean.
    Returns:
        - str: Cleaned title string, or an empty string if the input is invalid or non-informative."""
    cleaned = _strip_ui_noise(_strip_html(value))
    if not cleaned:
        return ""
    if cleaned.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
        return ""
    if _PROMO_ONLY_TITLE_RE and _PROMO_ONLY_TITLE_RE.match(cleaned):
        return ""
    return cleaned


def _clean_description_text(value: str) -> str:
    cleaned = _strip_html(value, preserve_paragraphs=True)
    cleaned = _strip_ui_noise(cleaned, preserve_newlines=True)
    return cleaned


def _normalize_color_text(value: str) -> str:
    """Normalize color text by stripping UI noise and extracting hex color codes when present.
    Parameters:
        - value (str): Raw color text to normalize.
    Returns:
        - str: The normalized color string, a hex color code if found, or an empty string when the text contains only color noise."""
    cleaned = _strip_ui_noise(_strip_html(value))
    lowered = cleaned.lower()

    hex_match = _HEX_COLOR_RE.search(lowered)
    if hex_match:
        return hex_match.group(0)

    if _COLOR_NOISE_RE.search(lowered):
        return ""

    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    return cleaned


def _normalize_size_text(value: str) -> str:
    """Normalize and clean size text extracted from UI or HTML content.
    Parameters:
        - value (str): The input size text to normalize.
    Returns:
        - str: The cleaned size text, or an empty string when the text is considered noise."""
    cleaned = _strip_ui_noise(_strip_html(value))
    lowered = cleaned.lower()

    if _SIZE_NOISE_RE.search(lowered):
        return ""

    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    tokens = [token.strip() for token in re.split(r"[\s,/|]+", cleaned) if token.strip()]
    if tokens and all(re.fullmatch(r"[A-Za-z0-9.+-]{1,5}", token) for token in tokens):
        return ", ".join(tokens)
    return cleaned


def _normalize_availability(value: str) -> str:
    """Normalize an availability string into a canonical status when possible.
    Parameters:
        - value (str): Raw availability text to normalize.
    Returns:
        - str: Canonical availability label such as "in_stock", "out_of_stock", "preorder", or "limited_availability"; otherwise the cleaned original text."""
    text = unescape(value).strip()
    lowered = text.lower()
    if lowered.endswith("/instock"):
        return "in_stock"
    if lowered.endswith("/outofstock"):
        return "out_of_stock"
    if lowered.endswith("/preorder"):
        return "preorder"
    if lowered.endswith("/limitedavailability"):
        return "limited_availability"
    return text


def _strip_ui_noise(value: str, *, preserve_newlines: bool = False) -> str:
    """Remove UI-related noise tokens, icons, and script artifacts from a string.
    Parameters:
        - value (str): Input text to clean.
        - preserve_newlines (bool): Whether to keep line breaks while normalizing whitespace. Defaults to False.
    Returns:
        - str: Cleaned text with UI noise removed and whitespace normalized."""
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
    return _field_in_group(field_name, "image_collection") or any(token in normalized for token in ("images", "gallery", "photos", "media"))


def _is_image_primary_field(field_name: str) -> bool:
    return _field_in_group(field_name, "image_primary") or (
        _field_has_any_token(field_name, CANDIDATE_IMAGE_TOKENS) and not _is_image_collection_field(field_name)
    )


def _is_url_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
        return False
    return _field_in_group(field_name, "url") or any(normalized.endswith(_field_token(suffix)) for suffix in CANDIDATE_URL_SUFFIXES)


def _is_numeric_field(field_name: str) -> bool:
    return field_name in PRICE_FIELDS or _field_in_group(field_name, "numeric") or _field_has_any_token(field_name, CANDIDATE_PRICE_TOKENS)


def _is_price_like_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return field_name in PRICE_FIELDS or _field_has_any_token(field_name, CANDIDATE_PRICE_TOKENS) or "price" in normalized


def _is_description_field(field_name: str) -> bool:
    return _field_in_group(field_name, "description") or _field_has_any_token(field_name, CANDIDATE_DESCRIPTION_TOKENS)


def _is_availability_field(field_name: str) -> bool:
    return _field_in_group(field_name, "availability") or _field_has_any_token(field_name, CANDIDATE_AVAILABILITY_TOKENS)


def _is_category_field(field_name: str) -> bool:
    return _field_in_group(field_name, "category") or _field_has_any_token(field_name, CANDIDATE_CATEGORY_TOKENS)


def _is_color_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return normalized in {_field_token("color"), _field_token("colors"), _field_token("color_name")}


def _is_size_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return normalized in {_field_token("size"), _field_token("sizes"), _field_token("variant_size")}


def _is_title_field(field_name: str) -> bool:
    return _field_in_group(field_name, "title")


def _is_entity_name_field(field_name: str) -> bool:
    return _field_in_group(field_name, "entity_name")


def _is_currency_field(field_name: str) -> bool:
    return _field_in_group(field_name, "currency") or _field_has_any_token(field_name, CANDIDATE_CURRENCY_TOKENS)


def _is_salary_field(field_name: str) -> bool:
    return _field_in_group(field_name, "salary") or _field_has_any_token(field_name, CANDIDATE_SALARY_TOKENS)
