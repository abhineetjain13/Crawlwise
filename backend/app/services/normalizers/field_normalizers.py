# Value normalization rules.
from __future__ import annotations

from html import unescape
import re

from bs4 import BeautifulSoup

from app.services.pipeline_config import (
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_GENERIC_CATEGORY_VALUES,
    CANDIDATE_GENERIC_TITLE_VALUES,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_IDENTIFIER_TOKENS,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_PROMO_ONLY_TITLE_PATTERN,
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
    CANDIDATE_URL_SUFFIXES,
    PRICE_FIELDS,
    PRICE_REGEX,
)

PLACEHOLDER_VALUES = {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}
_UI_NOISE_TOKEN_RE = re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_NOISE_TOKEN_PATTERN else None
_UI_ICON_TOKEN_RE = re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_ICON_TOKEN_PATTERN else None
_SCRIPT_NOISE_RE = re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE) if CANDIDATE_SCRIPT_NOISE_PATTERN else None
_PROMO_ONLY_TITLE_RE = re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE) if CANDIDATE_PROMO_ONLY_TITLE_PATTERN else None
CURRENCY_CODES = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BOV",
    "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE", "CHF",
    "CHW", "CLF", "CLP", "CNY", "COP", "COU", "CRC", "CUP", "CVE", "CZK",
    "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP",
    "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL",
    "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR", "ISK", "JMD", "JOD",
    "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT",
    "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD",
    "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MXV", "MYR",
    "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN",
    "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF",
    "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD",
    "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP",
    "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD", "USN", "UYI", "UYU",
    "UYW", "UZS", "VED", "VES", "VND", "VUV", "WST", "XAF", "XAG", "XAU",
    "XBA", "XBB", "XBC", "XBD", "XCD", "XDR", "XOF", "XPD", "XPF", "XPT",
    "XSU", "XTS", "XUA", "XXX", "YER", "ZAR", "ZMW", "ZWG",
}
_CURRENCY_TOKEN_RE = re.compile(r"\b[A-Z]{3}\b")
_CURRENCY_AFTER_AMOUNT_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*([A-Z]{3})\b")
_CURRENCY_BEFORE_AMOUNT_RE = re.compile(r"\b([A-Z]{3})\s*\d[\d,]*(?:\.\d+)?\b")
_CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}


def normalize_value(field_name: str, value: object) -> object:
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if text.lower() in PLACEHOLDER_VALUES:
            return ""
        if _is_color_field(field_name):
            return _normalize_color_text(text)
        if _is_size_field(field_name):
            return _normalize_size_text(text)
        if _is_image_primary_field(field_name):
            return _normalize_image_url(text)
        if _is_image_collection_field(field_name):
            return _normalize_additional_images(text)
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
    for symbol, currency in _CURRENCY_SYMBOL_MAP.items():
        if symbol in text:
            return currency
    valid_tokens = [token for token in _CURRENCY_TOKEN_RE.findall(upper_text) if token in CURRENCY_CODES]
    return valid_tokens[0] if valid_tokens else ""


def _normalize_image_url(value: str) -> str:
    urls = _split_image_values(value)
    return urls[0] if urls else value


def _normalize_additional_images(value: str) -> str:
    urls = _split_image_values(value)
    return ", ".join(urls) if urls else value


def _split_image_values(value: str) -> list[str]:
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


def _strip_html(value: str) -> str:
    if "<" not in value or ">" not in value:
        return unescape(value).strip()
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(unescape(text).split()).strip()


def _clean_title_text(value: str) -> str:
    cleaned = _strip_ui_noise(_strip_html(value))
    if not cleaned:
        return ""
    if cleaned.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
        return ""
    if _PROMO_ONLY_TITLE_RE and _PROMO_ONLY_TITLE_RE.match(cleaned):
        return ""
    return cleaned


def _clean_description_text(value: str) -> str:
    cleaned = _strip_html(value)
    cleaned = _strip_ui_noise(cleaned)
    return cleaned


def _normalize_color_text(value: str) -> str:
    cleaned = _strip_ui_noise(_strip_html(value))
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    return cleaned


def _normalize_size_text(value: str) -> str:
    cleaned = _strip_ui_noise(_strip_html(value))
    lowered = cleaned.lower()
    if any(token in lowered for token in ("max-width", "min-width", "vw", "vh", "sizes=", "srcset")):
        return ""
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    tokens = [token.strip() for token in re.split(r"[\s,/|]+", cleaned) if token.strip()]
    if tokens and all(re.fullmatch(r"[A-Za-z0-9.+-]{1,5}", token) for token in tokens):
        return ", ".join(tokens)
    return cleaned


def _normalize_availability(value: str) -> str:
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


def _strip_ui_noise(value: str) -> str:
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
    text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text


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
