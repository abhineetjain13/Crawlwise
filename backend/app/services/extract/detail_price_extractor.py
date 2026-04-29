from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_CENT_BASED_PRICE_CURRENCIES,
    DETAIL_CENT_PRICE_HOST_SUFFIXES,
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_CURRENCY_JSONLD_PATTERN,
    DETAIL_CURRENCY_META_SELECTORS,
    DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCES,
    DETAIL_ORIGINAL_PRICE_SELECTORS,
    DETAIL_PRICE_JSONLD_PATTERN,
    DETAIL_PRICE_JSONLD_TYPE_PATTERN,
    DETAIL_PRICE_META_SELECTORS,
    PAGE_URL_CURRENCY_HINTS_RAW,
)
from app.services.field_value_core import (
    extract_currency_code,
    infer_currency_from_page_url,
    text_or_none,
)
from app.services.normalizers import normalize_decimal_price

_LOW_SIGNAL_ZERO_PRICE_SOURCES = frozenset(DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCES)
_CENT_BASED_CURRENCIES = frozenset(DETAIL_CENT_BASED_PRICE_CURRENCIES)
_CENT_PRICE_HOST_SUFFIXES = tuple(
    str(host).strip().lower()
    for host in tuple(DETAIL_CENT_PRICE_HOST_SUFFIXES or ())
    if str(host).strip()
)
_DETAIL_PRICE_JSONLD_TYPE_RE = re.compile(str(DETAIL_PRICE_JSONLD_TYPE_PATTERN))
_DETAIL_PRICE_JSONLD_RE = re.compile(str(DETAIL_PRICE_JSONLD_PATTERN))
_DETAIL_CURRENCY_JSONLD_RE = re.compile(str(DETAIL_CURRENCY_JSONLD_PATTERN))


def backfill_detail_price_from_html(
    record: dict[str, Any],
    *,
    html: str,
) -> None:
    selected_variant = record.get("selected_variant")
    record_price_is_low_signal = _detail_price_value_is_low_signal(record.get("price"))
    needs_price = record.get("price") in (None, "", [], {}) or record_price_is_low_signal or (
        isinstance(selected_variant, dict)
        and selected_variant.get("price") in (None, "", [], {})
    )
    if not needs_price or not str(html or "").strip():
        return

    soup = BeautifulSoup(str(html or ""), "html.parser")
    html_currency = _detail_currency_from_html(soup)
    record_url = text_or_none(record.get("url")) or ""
    expected_currency = text_or_none(infer_currency_from_page_url(record_url))
    if _html_currency_conflicts_with_strong_host_hint(
        html_currency=html_currency,
        expected_currency=expected_currency,
        page_url=record_url,
    ):
        return

    currency = text_or_none(record.get("currency")) or html_currency
    if currency and record.get("currency") in (None, "", [], {}):
        record["currency"] = currency
        append_record_field_source(record, "currency", "dom_text")

    price = _detail_price_from_html(soup, currency=currency)
    if price in (None, "", [], {}):
        return
    if record.get("price") in (None, "", [], {}) or record_price_is_low_signal:
        record["price"] = price
        append_record_field_source(record, "price", "dom_text")
    if isinstance(selected_variant, dict) and (
        selected_variant.get("price") in (None, "", [], {})
        or _detail_price_value_is_low_signal(selected_variant.get("price"))
    ):
        selected_variant["price"] = price
        if currency and selected_variant.get("currency") in (None, "", [], {}):
            selected_variant["currency"] = currency
    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if (
                variant.get("price") not in (None, "", [], {})
                and not _detail_price_value_is_low_signal(variant.get("price"))
            ):
                continue
            variant["price"] = price
            if currency and variant.get("currency") in (None, "", [], {}):
                variant["currency"] = currency

    original_price = _detail_original_price_from_html(soup, currency=currency)
    if original_price not in (None, "", [], {}) and record.get("original_price") in (
        None,
        "",
        [],
        {},
    ):
        record["original_price"] = original_price
        append_record_field_source(record, "original_price", "dom_text")
    if (
        isinstance(selected_variant, dict)
        and original_price not in (None, "", [], {})
        and selected_variant.get("original_price") in (None, "", [], {})
    ):
        selected_variant["original_price"] = original_price


def drop_low_signal_zero_detail_price(record: dict[str, Any]) -> None:
    if not _price_value_is_zero(record.get("price")):
        return
    price_sources = record_field_sources(record, "price")
    if not price_sources or not price_sources <= _LOW_SIGNAL_ZERO_PRICE_SOURCES:
        return
    if _detail_record_has_positive_price_corroboration(record):
        return

    record.pop("price", None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and _price_value_is_zero(
        selected_variant.get("price")
    ):
        selected_variant.pop("price", None)
        selected_variant.pop("currency", None)

    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict) or not _price_value_is_zero(
                variant.get("price")
            ):
                continue
            variant.pop("price", None)
            variant.pop("currency", None)

    currency_sources = record_field_sources(record, "currency")
    if (
        not currency_sources or currency_sources <= _LOW_SIGNAL_ZERO_PRICE_SOURCES
    ) and record.get("original_price") in (None, "", [], {}):
        record.pop("currency", None)


def reconcile_detail_currency_with_url(
    record: dict[str, Any],
    *,
    page_url: str,
) -> None:
    expected_currency = text_or_none(infer_currency_from_page_url(page_url))
    if not expected_currency:
        return
    strong_host_hint = detail_currency_hint_is_host_level(
        page_url,
        expected_currency=expected_currency,
    )
    before_currency = text_or_none(record.get("currency"))

    _reconcile_container_currency(
        record,
        expected_currency=expected_currency,
        strong_host_hint=strong_host_hint,
    )
    if before_currency != text_or_none(record.get("currency")):
        append_record_field_source(record, "currency", "url_currency_hint")

    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        before_currency = text_or_none(selected_variant.get("currency"))
        _reconcile_container_currency(
            selected_variant,
            expected_currency=expected_currency,
            strong_host_hint=strong_host_hint,
        )
        if before_currency != text_or_none(selected_variant.get("currency")):
            append_record_field_source(record, "selected_variant.currency", "url_currency_hint")

    variants = record.get("variants")
    if isinstance(variants, list):
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                before_currency = text_or_none(variant.get("currency"))
                _reconcile_container_currency(
                    variant,
                    expected_currency=expected_currency,
                    strong_host_hint=strong_host_hint,
                )
                if before_currency != text_or_none(variant.get("currency")):
                    append_record_field_source(
                        record,
                        f"variants[{index}].currency",
                        "url_currency_hint",
                    )


def normalize_detail_cent_prices_for_context(
    record: dict[str, Any],
    *,
    page_url: str,
) -> None:
    if not _detail_price_context_uses_cents(page_url):
        return
    for container in _detail_price_containers(record):
        _normalize_cent_price_container(container)


def record_field_sources(record: dict[str, Any], field_name: str) -> set[str]:
    field_sources = record.get("_field_sources")
    if not isinstance(field_sources, dict):
        return set()
    source_values = field_sources.get(field_name)
    if not isinstance(source_values, list):
        return set()
    return {
        str(source).strip()
        for source in source_values
        if str(source).strip()
    }


def append_record_field_source(
    record: dict[str, Any],
    field_name: str,
    source: str,
) -> None:
    normalized_source = str(source).strip()
    if not normalized_source:
        return
    field_sources = record.setdefault("_field_sources", {})
    if not isinstance(field_sources, dict):
        return
    source_bucket = field_sources.setdefault(field_name, [])
    if not isinstance(source_bucket, list):
        return
    if normalized_source not in source_bucket:
        source_bucket.append(normalized_source)


def detail_currency_hint_is_host_level(
    page_url: str,
    *,
    expected_currency: str,
) -> bool:
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").strip().lower()
    path_segments = {
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    }
    if not hostname and not path_segments:
        return False
    for token, code in dict(PAGE_URL_CURRENCY_HINTS_RAW or {}).items():
        normalized_token = str(token).strip().lower()
        if not normalized_token or normalized_token.startswith("/"):
            continue
        host_token, _, raw_path = normalized_token.partition("/")
        token_path_segments = {
            segment.strip().lower()
            for segment in raw_path.split("/")
            if segment.strip()
        }
        host_matches = hostname == host_token or hostname.endswith(f".{host_token}")
        path_matches = not token_path_segments or token_path_segments <= path_segments
        if str(code) == expected_currency and host_matches and path_matches:
            return True
    return False


def normalize_mismatched_host_currency_price(
    value: object,
    *,
    expected_currency: str,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    digits_only = re.sub(r"\D+", "", text)
    if "." in text or not digits_only or len(digits_only) < 4:
        return None
    normalized = normalize_decimal_price(
        text,
        interpret_integral_as_cents=expected_currency in _CENT_BASED_CURRENCIES,
    )
    if normalized and "." not in normalized:
        return f"{normalized}.00"
    return normalized


def _detail_price_context_uses_cents(page_url: str) -> bool:
    hostname = str(urlparse(str(page_url or "")).hostname or "").strip().lower()
    return bool(
        hostname
        and any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _CENT_PRICE_HOST_SUFFIXES)
    )


def _detail_price_containers(record: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [record]
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        containers.append(selected_variant)
    variants = record.get("variants")
    if isinstance(variants, list):
        containers.extend(variant for variant in variants if isinstance(variant, dict))
    return containers


def _normalize_cent_price_container(container: dict[str, Any]) -> None:
    for field_name in ("price", "original_price"):
        normalized = _normalize_cent_integer_price(container.get(field_name))
        if normalized:
            container[field_name] = normalized


def _normalize_cent_integer_price(value: object) -> str | None:
    text = text_or_none(value)
    if not text or "." in text:
        return None
    digits_only = re.sub(r"\D+", "", text)
    if len(digits_only) < 4:
        return None
    normalized = normalize_decimal_price(text, interpret_integral_as_cents=True)
    if normalized is None:
        return None
    try:
        return f"{float(normalized):.2f}"
    except (TypeError, ValueError):
        return normalized


def _reconcile_container_currency(
    container: dict[str, Any],
    *,
    expected_currency: str,
    strong_host_hint: bool,
) -> None:
    actual_currency = text_or_none(container.get("currency"))
    has_price = container.get("price") not in (None, "", [], {})
    if not actual_currency:
        if has_price:
            container["currency"] = expected_currency
        return
    if actual_currency == expected_currency or not strong_host_hint:
        return

    corrected_price = normalize_mismatched_host_currency_price(
        container.get("price"),
        expected_currency=expected_currency,
    )
    if corrected_price:
        container["price"] = corrected_price
        container["currency"] = expected_currency
        return
    container.pop("price", None)
    container.pop("currency", None)


def _html_currency_conflicts_with_strong_host_hint(
    *,
    html_currency: str | None,
    expected_currency: str | None,
    page_url: str,
) -> bool:
    return bool(
        html_currency
        and expected_currency
        and html_currency != expected_currency
        and detail_currency_hint_is_host_level(
            page_url,
            expected_currency=expected_currency,
        )
    )


def _price_value_is_zero(value: object) -> bool:
    normalized = _normalized_price_value(value)
    return bool(normalized) and _coerce_float(normalized, default=1.0) == 0.0


def _price_value_is_positive(value: object) -> bool:
    normalized = _normalized_price_value(value)
    return bool(normalized) and _coerce_float(normalized, default=0.0) > 0.0


def _detail_price_value_is_low_signal(value: object) -> bool:
    normalized = _normalized_price_value(value)
    if not normalized:
        return False
    try:
        price = float(normalized)
    except ValueError:
        return False
    return 0.0 < price <= 1.0


def _normalized_price_value(value: object) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    return normalize_decimal_price(text, interpret_integral_as_cents=False)


def _detail_record_has_positive_price_corroboration(record: dict[str, Any]) -> bool:
    if _price_value_is_positive(record.get("original_price")):
        return True
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and any(
        _price_value_is_positive(selected_variant.get(field_name))
        for field_name in ("price", "original_price")
    ):
        return True
    variants = record.get("variants")
    if not isinstance(variants, list):
        return False
    return any(
        isinstance(variant, dict)
        and any(
            _price_value_is_positive(variant.get(field_name))
            for field_name in ("price", "original_price")
        )
        for variant in variants
    )


def _detail_price_from_html(soup: BeautifulSoup, *, currency: str | None) -> str | None:
    for selector in DETAIL_PRICE_META_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        raw_value = node.get("content") if hasattr(node, "get") else None
        if raw_value in (None, "", [], {}):
            raw_value = node.get_text(" ", strip=True)
        normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
        if normalized:
            return normalized

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text or '"price"' not in script_text.lower():
            continue
        if _DETAIL_PRICE_JSONLD_TYPE_RE.search(script_text) is None:
            continue
        match = _DETAIL_PRICE_JSONLD_RE.search(script_text)
        if match is None:
            continue
        normalized = _normalize_detail_price_candidate(
            match.group("price"),
            currency=currency,
        )
        if normalized:
            return normalized

    return _detail_price_from_selector_text(
        soup,
        selectors=DETAIL_CURRENT_PRICE_SELECTORS,
        currency=currency,
    )


def _detail_original_price_from_html(
    soup: BeautifulSoup,
    *,
    currency: str | None,
) -> str | None:
    return _detail_price_from_selector_text(
        soup,
        selectors=DETAIL_ORIGINAL_PRICE_SELECTORS,
        currency=currency,
    )


def _detail_price_from_selector_text(
    soup: BeautifulSoup,
    *,
    selectors: tuple[str, ...],
    currency: str | None,
) -> str | None:
    for selector in selectors:
        for node in soup.select(selector):
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
            if normalized:
                return normalized
    return None


def _detail_currency_from_html(soup: BeautifulSoup) -> str | None:
    for selector in DETAIL_CURRENCY_META_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        currency = text_or_none(node.get("content") if hasattr(node, "get") else None)
        if currency:
            return currency

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text:
            continue
        match = _DETAIL_CURRENCY_JSONLD_RE.search(script_text)
        if match is not None:
            return text_or_none(match.group("currency"))

    for selector in (*DETAIL_CURRENT_PRICE_SELECTORS, *DETAIL_ORIGINAL_PRICE_SELECTORS):
        for node in soup.select(selector):
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            currency = extract_currency_code(raw_value)
            if currency:
                return currency
    return None


def _normalize_detail_price_candidate(
    value: object,
    *,
    currency: str | None,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    digits_only = re.sub(r"\D+", "", text)
    if (
        currency
        and re.fullmatch(r"\d+(?:\.\d+)?", text)
        and "." not in text
        and len(digits_only) <= 3
    ):
        return text
    return normalize_decimal_price(
        text,
        interpret_integral_as_cents=(
            "." not in text
            and len(digits_only) >= 4
            and currency in _CENT_BASED_CURRENCIES
        ),
    )


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


__all__ = [
    "append_record_field_source",
    "backfill_detail_price_from_html",
    "detail_currency_hint_is_host_level",
    "drop_low_signal_zero_detail_price",
    "normalize_mismatched_host_currency_price",
    "normalize_detail_cent_prices_for_context",
    "reconcile_detail_currency_with_url",
    "record_field_sources",
]
