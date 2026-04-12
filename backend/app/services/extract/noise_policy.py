from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS,
    CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN,
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN,
)
from app.services.requested_field_policy import normalize_requested_field
from app.services.text_sanitization import strip_ui_noise
from app.services.text_utils import normalized_text
from bs4 import Tag

_COMMON_DETAIL_REJECT_PHRASES = (
    "cookie",
    "privacy",
    "sign in",
    "log in",
    "my account",
    "analytics",
    "pageview",
    "gtm",
)
_DETAIL_FIELD_REJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "title": ("add to cart", "shop now", "view cart", "menu"),
    "brand": ("home >", "home /", "policy"),
    "category": ("page type", "page category", "detail page"),
    "availability": ("add to cart", "choose options", "select options", "view details"),
    "color": ("add to cart", "choose options", "select options"),
    "size": ("select size", "choose size"),
    "features": ("livechat",),
    "care": ("care instructions",),
}
_BREADCRUMB_STYLE_BRAND_RE = re.compile(r"\s(?:>|/)\s")

_NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    {
        "about",
        "about_us",
        "accessibility_statement",
        "contact",
        "contact_us",
        "customer_service",
        "faq",
        "faqs",
        "policies",
        "privacy",
        "privacy_policy",
        "return_policy",
        "returns",
        "shipping",
        "shipping_policy",
        "shopping_cart",
        "store_locations",
        "terms",
        "terms_policies",
    }
)
_NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES = (
    "loading... read more",
    "privacy policy",
    "terms of service",
    "shipping policy",
    "return policy",
    "request a catalog",
    "join our team",
    "account login",
    "store locations",
    "accessibility statement",
    "subscribe to our newsletter",
    "sign up for",
    "follow us on",
    "download our app",
    "manage preferences",
    "cookie settings",
    "do not sell my personal",
)
_NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS = (
    "gift cards",
    "press inquiries",
    "the gazette",
    "your privacy choices",
)
_CSS_NOISE_VALUE_RE = re.compile(CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN)
_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_RE = re.compile(
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN
)
_NETWORK_PAYLOAD_NOISE_URL_RE = re.compile(
    r"geolocation|geoip|geo/|/geo\b|"
    r"\banalytics\b|tracking|telemetry|"
    r"klarna\.com|affirm\.com|afterpay\.com|"
    r"olapic-cdn\.com|"
    r"livechat|zendesk\.com|intercom\.io|"
    r"facebook\.com|google-analytics|googletagmanager|"
    r"sentry\.io|datadome|px\.ads|"
    r"cdn-cgi/|captcha",
    re.IGNORECASE,
)

SECTION_LABEL_SKIP_TOKENS = (
    "contact",
    "share",
    "top searches",
    "you may also like",
    "similar",
    "related",
)
SECTION_KEY_SKIP_PREFIXES = (
    "contact_",
    "share",
    "top_searches",
    "you_may_also_like",
    "related",
    "similar",
    "ad_id_",
    "images",
)
SECTION_BODY_SKIP_PHRASES = (
    "click to reveal phone number",
    "dealer network partner",
    "buy report now",
    "share this ad",
)
_NOISE_CONTAINER_TOKENS = (
    "footer",
    "legal",
    "privacy",
    "cookie",
    "consent",
    "iubenda",
    "menu",
    "navigation",
    "navbar",
    "contact",
    "share",
    "app-store",
    "app_store",
    "newsletter",
)
_SOCIAL_HOST_SUFFIXES = (
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
)
_NOISE_CONTAINER_REMOVAL_SELECTOR = (
    "aside, nav, [class*='filter' i], [class*='facet' i], "
    "[class*='sidebar' i], [class*='breadcrumb' i], "
    "[class*='navigation' i], [class*='menu' i], footer, header"
)


def normalized_noise_text(value: object) -> str:
    return normalized_text(value)


def is_network_payload_noise_url(value: object) -> bool:
    return bool(
        _NETWORK_PAYLOAD_NOISE_URL_RE.search(normalized_noise_text(value).lower())
    )


def sanitize_detail_field_value(
    field_name: str, value: object
) -> tuple[object | None, str | None]:
    if not isinstance(value, str):
        return value, None

    text = normalized_noise_text(value)
    if not text:
        return None, "empty_after_sanitization"

    lowered = text.casefold()
    reject_phrases = (
        *_COMMON_DETAIL_REJECT_PHRASES,
        *(_DETAIL_FIELD_REJECT_PHRASES.get(field_name) or ()),
    )
    if any(phrase in lowered for phrase in reject_phrases):
        return None, "detail_field_noise"
    if field_name == "brand" and _BREADCRUMB_STYLE_BRAND_RE.search(text):
        return None, "breadcrumb_like_brand"
    if field_name == "availability" and lowered in {
        "availability",
        "select size",
        "select color",
        "select colour",
    }:
        return None, "availability_shell_text"
    if field_name == "color" and len(text.split()) > 4:
        return None, "improbable_color_label"
    return text, None


def is_noisy_product_attribute_entry(key: object, value: object) -> bool:
    normalized_key = normalize_requested_field(key)
    text_value = normalized_noise_text(value).lower()
    if not normalized_key or not text_value:
        return True
    if _PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_RE.fullmatch(normalized_key):
        return True
    if not re.search(r"[a-z]", normalized_key):
        return True
    if normalized_key in _NOISY_PRODUCT_ATTRIBUTE_KEYS:
        return True
    if normalized_key.startswith(("contact_", "customer_", "privacy_", "terms_")):
        return True
    if any(
        token in normalized_key.split("_")
        for token in CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS
    ):
        return True
    if any(phrase in text_value for phrase in _NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES):
        return True
    if any(token in text_value for token in _NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS):
        return True
    if _CSS_NOISE_VALUE_RE.search(text_value):
        return True
    if (
        text_value.count("{") >= 1
        and text_value.count("}") >= 1
        and text_value.count(":") >= 3
    ):
        return True
    if text_value.count(" - ") >= 2:
        return True
    return False


def sanitize_product_attribute_map(
    value: object,
    *,
    blocked_keys: tuple[str, ...] | frozenset[str] | set[str] = (),
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None

    blocked = {
        normalize_requested_field(key) or str(key).strip().lower()
        for key in blocked_keys
        if str(key or "").strip()
    }
    sanitized: dict[str, object] = {}
    for key, raw_value in value.items():
        normalized_key = normalize_requested_field(key)
        if not normalized_key or normalized_key in blocked:
            continue
        if is_noisy_product_attribute_entry(normalized_key, raw_value):
            continue
        sanitized[normalized_key] = raw_value
    return sanitized or None


def is_noise_title(
    title: object,
    *,
    navigation_hints: set[str] | frozenset[str],
    merchandising_prefixes: tuple[str, ...],
    editorial_patterns: tuple[re.Pattern[str], ...],
    alt_text_pattern: re.Pattern[str] | None,
    weak_titles: set[str] | frozenset[str],
) -> bool:
    normalized = normalized_noise_text(title).lower()
    if not normalized:
        return True
    if normalized in navigation_hints:
        return True
    if normalized.startswith(merchandising_prefixes):
        return True
    if any(pattern.search(normalized) for pattern in editorial_patterns):
        return True
    if alt_text_pattern and alt_text_pattern.search(normalized):
        return True
    if normalized in weak_titles:
        return True
    return False


def is_noise_container(
    node: Tag | None,
    *,
    max_depth: int = 6,
    extra_tokens: tuple[str, ...] = (),
) -> bool:
    tokens = _NOISE_CONTAINER_TOKENS + tuple(extra_tokens)
    current = node
    steps = 0
    while isinstance(current, Tag) and steps <= max_depth:
        tag_name = str(current.name or "").lower()
        if tag_name in {"footer", "nav", "header", "aside"}:
            return True
        attrs = " ".join(
            filter(
                None,
                [
                    str(current.get("id") or ""),
                    " ".join(current.get("class", []))
                    if isinstance(current.get("class"), list)
                    else str(current.get("class") or ""),
                    str(current.get("role") or ""),
                    str(current.get("aria-label") or ""),
                ],
            )
        ).lower()
        if any(token in attrs for token in tokens):
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        steps += 1
    return False


def is_listing_noise_group(group: list[Tag]) -> bool:
    if not group:
        return False
    return is_noise_container(group[0], extra_tokens=("nav-",))


def is_social_url(value: object) -> bool:
    from urllib.parse import urlparse

    host = urlparse(str(value or "").strip()).netloc.lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _SOCIAL_HOST_SUFFIXES
    )


def strip_noise_containers(soup: Tag) -> None:
    for noise_el in soup.select(_NOISE_CONTAINER_REMOVAL_SELECTOR):
        noise_el.decompose()


def is_inside_site_chrome(node: Tag | None) -> bool:
    if not isinstance(node, Tag):
        return False
    for ancestor in node.parents:
        if not isinstance(ancestor, Tag):
            continue
        if str(ancestor.name or "").lower() in {"footer", "nav", "header", "aside"}:
            return True
    return False
