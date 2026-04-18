from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS,
    CSS_NOISE_PATTERN,
    CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN,
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN,
    FIELD_POLLUTION_RULES,
    FIELD_VALUE_NOISE_FRAGMENTS,
    LOW_QUALITY_MERGE_TOKENS,
    NETWORK_PAYLOAD_NOISE_URL_PATTERN,
    NOISE_CONTAINER_REMOVAL_SELECTOR,
    NOISE_CONTAINER_TOKENS,
    NOISY_PRODUCT_ATTRIBUTE_KEYS,
    NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS,
    NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES,
    SIZE_CHART_REGION_KEYS,
    SOCIAL_HOST_SUFFIXES,
    TITLE_NOISE_WORDS,
)
from app.services.requested_field_policy import normalize_requested_field
from app.services.text_sanitization import strip_ui_noise
from app.services.text_utils import normalized_text
from bs4 import Tag

_BREADCRUMB_STYLE_BRAND_RE = re.compile(r"\s(?:>|/)\s")
_CSS_NOISE_VALUE_RE = re.compile(CSS_NOISE_PATTERN or CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN)
_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_RE = re.compile(
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN
)
_SIZE_CHART_PRODUCT_ATTRIBUTE_KEY_RE = re.compile(
    r"^(?:xxs|xs|s|m|l|xl|xxl|xxxl)(?:_\d+(?:_\d+)*)+$",
    re.IGNORECASE,
)
_NETWORK_PAYLOAD_NOISE_URL_RE = re.compile(
    NETWORK_PAYLOAD_NOISE_URL_PATTERN,
    re.IGNORECASE,
)
_PAGE_NATIVE_FIELD_LABEL_ALLOWLIST: dict[str, frozenset[str]] = {
    "availability": frozenset({"availability"}),
    "color": frozenset(
        {"select color", "select colour", "choose color", "choose colour"}
    ),
    "size": frozenset({"select size", "choose size"}),
}


def normalized_noise_text(value: object) -> str:
    return normalized_text(value)


def contains_low_quality_merge_token(value: object) -> bool:
    text = normalized_noise_text(value).casefold()
    return bool(text) and any(token in text for token in LOW_QUALITY_MERGE_TOKENS)


def field_value_contains_noise(field_name: str, value: object) -> bool:
    text = normalized_noise_text(value).casefold()
    if not text:
        return False
    return any(
        fragment in text for fragment in FIELD_VALUE_NOISE_FRAGMENTS.get(field_name, frozenset())
    )


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
    if lowered in _PAGE_NATIVE_FIELD_LABEL_ALLOWLIST.get(field_name, frozenset()):
        return text, None
    reject_phrases = (
        *((FIELD_POLLUTION_RULES.get("__common__") or {}).get("reject_phrases", ())),
        *((FIELD_POLLUTION_RULES.get(field_name) or {}).get("reject_phrases", ())),
    )
    if any(phrase in lowered for phrase in reject_phrases):
        return None, "detail_field_noise"
    if field_name == "brand" and _BREADCRUMB_STYLE_BRAND_RE.search(text):
        return None, "breadcrumb_like_brand"
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
    if len(normalized_key) > 40:
        return True
    text_value_slug = re.sub(r"[^a-z0-9]+", "_", text_value).strip("_")
    if len(normalized_key) > 15 and (normalized_key in text_value_slug or text_value_slug in normalized_key):
        return True
    if normalized_key in NOISY_PRODUCT_ATTRIBUTE_KEYS:
        return True
    if normalized_key in SIZE_CHART_REGION_KEYS:
        return True
    if _SIZE_CHART_PRODUCT_ATTRIBUTE_KEY_RE.fullmatch(normalized_key):
        return True
    if "sizeguide" in normalized_key or normalized_key.startswith("size_guide"):
        return True
    if normalized_key.startswith(("select_a_size", "select_size", "choose_size")):
        return True
    if normalized_key.endswith("_code") and any(
        token in normalized_key for token in ("promo", "coupon", "offer", "discount", "_off")
    ):
        return True
    if normalized_key.startswith(("contact_", "customer_", "privacy_", "terms_")):
        return True
    if any(
        token in normalized_key.split("_")
        for token in CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS
    ):
        return True
    if any(phrase in text_value for phrase in NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES):
        return True
    if any(token in text_value for token in NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS):
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
    if len(text_value) > 200:
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
        if isinstance(raw_value, str):
            raw_value = re.sub(
                r"(?i)\s+select\s+(?:a\s+)?(?:size|color|colour)\s*:.*$",
                "",
                normalized_noise_text(raw_value),
            ).strip(" ,:-")
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
    tokens = NOISE_CONTAINER_TOKENS + tuple(extra_tokens)
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
        for suffix in SOCIAL_HOST_SUFFIXES
    )


def strip_noise_containers(soup: Tag) -> None:
    for noise_el in soup.select(NOISE_CONTAINER_REMOVAL_SELECTOR):
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
