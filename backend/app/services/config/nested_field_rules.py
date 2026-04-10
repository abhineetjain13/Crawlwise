from __future__ import annotations

import re

from app.services.config.extraction_rules import NORMALIZATION_RULES

_NORMALIZATION_RULES = NORMALIZATION_RULES


def _build_page_url_currency_hint_pattern(token: object) -> str:
    raw_token = str(token or "").strip().lower()
    if not raw_token:
        raise RuntimeError(
            "Invalid empty locale token in normalization_rules.page_url_currency_hints"
        )
    locale_segment = raw_token.strip("/")
    if not locale_segment:
        raise RuntimeError(
            "Invalid slash-only locale token in normalization_rules.page_url_currency_hints"
        )
    return rf"(?:^|/){re.escape(locale_segment)}(?:/|$)"


def _compile_page_url_currency_hints(
    hints: object,
) -> dict[re.Pattern[str], str]:
    compiled_hints: dict[re.Pattern[str], str] = {}
    normalized_hints = hints if isinstance(hints, dict) else {}
    for token, currency in normalized_hints.items():
        compiled_hints[
            re.compile(_build_page_url_currency_hint_pattern(token), re.IGNORECASE)
        ] = str(currency)
    return compiled_hints


PAGE_URL_CURRENCY_HINTS = _compile_page_url_currency_hints(
    _NORMALIZATION_RULES.get("page_url_currency_hints", {})
)
_NESTED_OBJECT_KEYS = _NORMALIZATION_RULES.get("nested_object_keys", {})
NESTED_TEXT_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "text_fields",
        ["name", "label", "title", "text", "value", "content", "description", "alt"],
    )
)
NESTED_URL_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get("url_fields", ["href", "url", "link", "canonical_url"])
)
NESTED_PRICE_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "price_fields",
        [
            "specialValue",
            "currentValue",
            "special",
            "current",
            "price",
            "amount",
            "value",
            "lowPrice",
            "minPrice",
            "displayPrice",
            "formattedPrice",
        ],
    )
)
NESTED_ORIGINAL_PRICE_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "original_price_fields",
        [
            "compareAtPrice",
            "compare_at_price",
            "listPrice",
            "regularPrice",
            "wasPrice",
            "originalPrice",
            "maxPrice",
            "currentValue",
            "price",
        ],
    )
)
NESTED_CURRENCY_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "currency_fields",
        ["currency", "currencyCode", "priceCurrency", "currency_code"],
    )
)
NESTED_CATEGORY_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "category_fields", ["name", "path", "pathEn", "breadcrumb", "categoryPath"]
    )
)
