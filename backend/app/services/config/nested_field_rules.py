from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    NESTED_OBJECT_KEYS_CONFIG,
    PAGE_URL_CURRENCY_HINTS_RAW,
)


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


PAGE_URL_CURRENCY_HINTS = _compile_page_url_currency_hints(PAGE_URL_CURRENCY_HINTS_RAW)
_NESTED_OBJECT_KEYS = NESTED_OBJECT_KEYS_CONFIG
if not isinstance(_NESTED_OBJECT_KEYS, dict):
    raise RuntimeError("NESTED_OBJECT_KEYS_CONFIG must decode to a dict")

NESTED_TEXT_KEYS = tuple(_NESTED_OBJECT_KEYS["text_fields"])
NESTED_URL_KEYS = tuple(_NESTED_OBJECT_KEYS["url_fields"])
NESTED_PRICE_KEYS = tuple(_NESTED_OBJECT_KEYS["price_fields"])
NESTED_ORIGINAL_PRICE_KEYS = tuple(_NESTED_OBJECT_KEYS["original_price_fields"])
NESTED_CURRENCY_KEYS = tuple(_NESTED_OBJECT_KEYS["currency_fields"])
NESTED_CATEGORY_KEYS = tuple(_NESTED_OBJECT_KEYS["category_fields"])
