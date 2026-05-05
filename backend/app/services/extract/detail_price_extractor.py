from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_CENT_BASED_PRICE_CURRENCIES,
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_CURRENCY_JSONLD_PATTERN,
    DETAIL_CURRENCY_META_SELECTORS,
    DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS,
    DETAIL_JSONLD_CURRENCY_FIELDS,
    DETAIL_JSONLD_GRAPH_FIELDS,
    DETAIL_JSONLD_OFFER_FIELDS,
    DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS,
    DETAIL_JSONLD_TYPE_FIELDS,
    DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA,
    DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO,
    DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCES,
    DETAIL_ORIGINAL_PRICE_SELECTORS,
    DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX,
    DETAIL_PARENT_VARIANT_PRICE_RATIO_MIN,
    DETAIL_PRICE_CENT_MAGNITUDE_RATIO,
    DETAIL_PRICE_JSONLD_PATTERN,
    DETAIL_PRICE_JSONLD_TYPE_PATTERN,
    DETAIL_PRICE_MAGNITUDE_EPSILON,
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
_AUTHORITATIVE_PRICE_SOURCES = frozenset({"adapter", "network_payload"})
_STRICT_PARENT_PRICE_SOURCES = frozenset({"network_payload"})
_CENT_BASED_CURRENCIES = frozenset(DETAIL_CENT_BASED_PRICE_CURRENCIES)
_PRICE_CENT_MAGNITUDE_RATIO = Decimal(str(DETAIL_PRICE_CENT_MAGNITUDE_RATIO))
_PRICE_MAGNITUDE_EPSILON = Decimal(str(DETAIL_PRICE_MAGNITUDE_EPSILON))
_PARENT_VARIANT_PRICE_RATIO_MIN = Decimal(str(DETAIL_PARENT_VARIANT_PRICE_RATIO_MIN))
_PARENT_VARIANT_PRICE_RATIO_MAX = Decimal(str(DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX))
_installment_price_text_tokens = tuple(
    str(token).strip().lower()
    for token in tuple(DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS or ())
    if str(token).strip()
)
_jsonld_graph_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_GRAPH_FIELDS or ())
)
_jsonld_type_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_TYPE_FIELDS or ())
)
_jsonld_offer_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_OFFER_FIELDS or ())
)
_jsonld_price_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_PRICE_FIELDS or ())
)
_jsonld_original_price_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS or ())
)
_jsonld_price_specification_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS or ())
)
_jsonld_currency_fields = tuple(
    str(field) for field in tuple(DETAIL_JSONLD_CURRENCY_FIELDS or ())
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
    if not str(html or "").strip():
        return

    soup = BeautifulSoup(str(html or ""), "html.parser")
    jsonld_price_bundle = _detail_jsonld_price_bundle(soup, currency=None)
    html_currency = _detail_currency_from_html(
        soup,
        jsonld_price_bundle=jsonld_price_bundle,
    )
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

    if currency != jsonld_price_bundle[2]:
        jsonld_price_bundle = _detail_jsonld_price_bundle(soup, currency=currency)
    jsonld_price, jsonld_original_price, _jsonld_currency = jsonld_price_bundle
    price = jsonld_price or _detail_price_from_html(
        soup,
        currency=currency,
        jsonld_price_bundle=jsonld_price_bundle,
    )
    price_source = "json_ld" if jsonld_price else "dom_text"
    visible_price = _detail_price_from_selector_text(
        soup,
        selectors=DETAIL_CURRENT_PRICE_SELECTORS,
        currency=currency,
    )
    if visible_price and (
        _detail_price_is_cent_magnitude_copy(price, visible_price)
        or _should_override_record_price_from_dom(
            record=record,
            dom_price=visible_price,
            record_price_is_low_signal=record_price_is_low_signal,
        )
    ):
        price = visible_price
        price_source = "dom_text"
    if price in (None, "", [], {}):
        return
    if (
        price_source == "json_ld"
        and price == jsonld_price
        and not (record_field_sources(record, "price") & _AUTHORITATIVE_PRICE_SOURCES)
    ):
        record["price"] = price
        append_record_field_source(record, "price", "json_ld")
    if _should_override_record_price_from_dom(
        record=record,
        dom_price=price,
        record_price_is_low_signal=record_price_is_low_signal,
    ):
        record["price"] = price
        append_record_field_source(record, "price", "dom_text")
    if isinstance(selected_variant, dict) and (
        selected_variant.get("price") in (None, "", [], {})
        or _detail_price_value_is_low_signal(selected_variant.get("price"))
        or _detail_price_is_cent_magnitude_copy(selected_variant.get("price"), price)
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
                and not _detail_price_is_cent_magnitude_copy(
                    variant.get("price"), price
                )
            ):
                continue
            variant["price"] = price
            if currency and variant.get("currency") in (None, "", [], {}):
                variant["currency"] = currency

    original_price = jsonld_original_price or _detail_original_price_from_html(
        soup,
        currency=currency,
        jsonld_price_bundle=jsonld_price_bundle,
    )
    if original_price not in (None, "", [], {}) and record.get("original_price") in (
        None,
        "",
        [],
        {},
    ):
        original_price_source = "json_ld" if jsonld_original_price else "dom_text"
        record["original_price"] = original_price
        append_record_field_source(record, "original_price", original_price_source)
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
            append_record_field_source(
                record, "selected_variant.currency", "url_currency_hint"
            )

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


def reconcile_detail_price_magnitudes(record: dict[str, Any]) -> None:
    parent_price = detail_price_decimal(record.get("price"))
    variant_rows: list[tuple[str, dict[str, Any]]] = []
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        variant_rows.append(("selected_variant", selected_variant))
    variants = record.get("variants")
    if isinstance(variants, list):
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                variant_rows.append((f"variants[{index}]", variant))
    variant_prices = [
        detail_price_decimal(row.get("price"))
        for _path, row in variant_rows
        if detail_price_decimal(row.get("price")) is not None
    ]
    safe_variant_price = _single_decimal_value(variant_prices)
    if (
        parent_price is not None
        and safe_variant_price is not None
        and _decimal_is_cent_magnitude_copy(parent_price, safe_variant_price)
        and not (record_field_sources(record, "price") & _STRICT_PARENT_PRICE_SOURCES)
    ):
        record["price"] = _format_price_decimal(safe_variant_price)
        append_record_field_source(record, "price", "variant_price_magnitude")
        parent_price = safe_variant_price
    if parent_price is None:
        return
    for path, row in variant_rows:
        row_price = detail_price_decimal(row.get("price"))
        if row_price is None:
            continue
        if _decimal_is_cent_magnitude_copy(row_price, parent_price):
            row["price"] = _format_price_decimal(parent_price)
            append_record_field_source(
                record, f"{path}.price", "parent_price_magnitude"
            )


def reconcile_parent_price_against_variant_range(record: dict[str, Any]) -> None:
    """Repair parent ``price`` when every variant reports a single, different price.

    DQ-7 / 2026-05-04 gemini audit (Selfridges): parent price 190 while both
    variants (50ml, 100ml) report 310. The parent value was scraped from an
    unrelated DOM element. When all variant rows agree on a single positive
    price and the parent price falls within the same order of magnitude as
    that variant price (i.e. not a cents/units magnitude copy), adopt the
    unanimous variant price as the parent.

    Conservative by design:
      * only acts when ``_single_decimal_value`` yields a unique variant price;
      * only acts when parent and variant are within 0.5x..2x of each other,
        so cents-magnitude mismatches (100x) are left to
        :func:`reconcile_detail_price_magnitudes`;
      * skips when the parent price came from an authoritative / strict
        source such as ``network_payload``;
      * skips when the parent equals the variant price.
    """
    parent_price = detail_price_decimal(record.get("price"))
    if parent_price is None or parent_price <= 0:
        return
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    variant_dicts = [variant for variant in variants if isinstance(variant, dict)]
    if not variant_dicts:
        return
    variant_prices: list[Decimal] = []
    for variant in variant_dicts:
        parsed_price = detail_price_decimal(variant.get("price"))
        if parsed_price is not None:
            variant_prices.append(parsed_price)
    if len(variant_prices) < len(variant_dicts):
        # At least one variant lacks a price; skip to avoid misjudging the
        # distribution.
        return
    unanimous_variant_price = _single_decimal_value(variant_prices)
    if unanimous_variant_price is None or unanimous_variant_price <= 0:
        return
    if parent_price == unanimous_variant_price:
        return
    # Same-order-of-magnitude guard: skip cents/units magnitude gaps so the
    # dedicated magnitude reconciler can handle them.
    ratio = parent_price / unanimous_variant_price
    if (
        ratio < _PARENT_VARIANT_PRICE_RATIO_MIN
        or ratio > _PARENT_VARIANT_PRICE_RATIO_MAX
    ):
        return
    if record_field_sources(record, "price") & _STRICT_PARENT_PRICE_SOURCES:
        return
    record["price"] = _format_price_decimal(unanimous_variant_price)
    append_record_field_source(record, "price", "variant_price_range")


def record_field_sources(record: dict[str, Any], field_name: str) -> set[str]:
    field_sources = record.get("_field_sources")
    if not isinstance(field_sources, dict):
        return set()
    source_values = field_sources.get(field_name)
    if not isinstance(source_values, list):
        return set()
    return {str(source).strip() for source in source_values if str(source).strip()}


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


def _should_override_record_price_from_dom(
    *,
    record: dict[str, Any],
    dom_price: object,
    record_price_is_low_signal: bool,
) -> bool:
    current_price = record.get("price")
    if current_price in (None, "", [], {}):
        return True
    if record_price_is_low_signal:
        return True
    if _detail_price_is_cent_magnitude_copy(current_price, dom_price):
        return True
    if not _detail_price_is_visible_outlier(current_price, dom_price):
        return False
    current_sources = record_field_sources(record, "price")
    return not bool(current_sources & _AUTHORITATIVE_PRICE_SOURCES)


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
    normalized = detail_price_decimal(value)
    return normalized is not None and normalized == Decimal("0")


def _price_value_is_positive(value: object) -> bool:
    normalized = detail_price_decimal(value)
    return normalized is not None and normalized > Decimal("0")


def _detail_price_value_is_low_signal(value: object) -> bool:
    price = detail_price_decimal(value)
    if price is None:
        return False
    return Decimal("0") < price <= Decimal("1")


def _detail_price_is_visible_outlier(value: object, visible_value: object) -> bool:
    current = detail_price_decimal(value)
    visible = detail_price_decimal(visible_value)
    if current is None or visible is None or current <= 0 or visible <= 0:
        return False
    if _decimal_is_cent_magnitude_copy(current, visible):
        return True
    if visible <= current:
        return False
    if visible - current < Decimal(str(DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA)):
        return False
    return current <= visible * Decimal(str(DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO))


def _normalized_price_value(value: object) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return text
    return normalize_decimal_price(text, interpret_integral_as_cents=False)


def detail_price_decimal(value: object) -> Decimal | None:
    normalized = _normalized_price_value(value)
    if not normalized:
        return None
    try:
        return Decimal(str(normalized))
    except (InvalidOperation, ValueError):
        return None


def _format_price_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def format_detail_price_decimal(value: object) -> str | None:
    price = detail_price_decimal(value)
    if price is None:
        return None
    return _format_price_decimal(price)


def _detail_price_is_cent_magnitude_copy(value: object, reference: object) -> bool:
    value_decimal = detail_price_decimal(value)
    reference_decimal = detail_price_decimal(reference)
    return bool(
        value_decimal is not None
        and reference_decimal is not None
        and _decimal_is_cent_magnitude_copy(value_decimal, reference_decimal)
    )


def _decimal_is_cent_magnitude_copy(value: Decimal, reference: Decimal) -> bool:
    if value <= 0 or reference <= 0:
        return False
    return (
        abs(value - (reference * _PRICE_CENT_MAGNITUDE_RATIO))
        <= _PRICE_MAGNITUDE_EPSILON
    )


def _single_decimal_value(values: list[Decimal]) -> Decimal | None:
    unique = {_format_price_decimal(value) for value in values if value > 0}
    if len(unique) != 1:
        return None
    return Decimal(next(iter(unique)))


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


def _detail_price_from_html(
    soup: BeautifulSoup,
    *,
    currency: str | None,
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    jsonld_price, _jsonld_original_price, _jsonld_currency = jsonld_price_bundle
    # Defensive: callers typically gate on ``jsonld_price or _detail_price_from_html(...)``,
    # but keep this fast-path so direct callers also short-circuit without re-scanning the DOM.
    if jsonld_price:
        return jsonld_price

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
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    _jsonld_price, jsonld_original_price, _jsonld_currency = jsonld_price_bundle
    if jsonld_original_price:
        return jsonld_original_price
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
            if _price_node_looks_like_installment(node):
                continue
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
            if normalized:
                return normalized
    return None


def _price_node_looks_like_installment(node: object) -> bool:
    text_parts: list[str] = []
    if node is None:
        return False
    if hasattr(node, "get_text"):
        text_parts.append(node.get_text(" ", strip=True))
    if hasattr(node, "get"):
        for attr_name in ("aria-label",):
            raw = node.get(attr_name)
            if isinstance(raw, list):
                text_parts.extend(str(item) for item in raw)
            elif raw not in (None, "", [], {}):
                text_parts.append(str(raw))
    lowered = " ".join(text_parts).lower()
    return any(token in lowered for token in _installment_price_text_tokens)


def _detail_currency_from_html(
    soup: BeautifulSoup,
    *,
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    _jsonld_price, _jsonld_original_price, jsonld_currency = jsonld_price_bundle
    if jsonld_currency:
        return jsonld_currency

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


def _detail_jsonld_price_bundle(
    soup: BeautifulSoup,
    *,
    currency: str | None,
) -> tuple[str | None, str | None, str | None]:
    saved_currency = text_or_none(currency)
    for offer in _iter_jsonld_offers(soup):
        offer_currency = _first_text(offer, _jsonld_currency_fields) or currency
        saved_currency = text_or_none(offer_currency) or saved_currency
        price = _first_normalized_price(
            offer,
            _jsonld_price_fields,
            currency=offer_currency,
        )
        original_price = _first_normalized_price(
            offer,
            _jsonld_original_price_fields,
            currency=offer_currency,
        )
        spec_original = _price_from_jsonld_specifications(
            offer,
            currency=offer_currency,
            current_price=price,
        )
        original_price = spec_original or original_price
        if price:
            price = format_detail_price_decimal(price) or price
        if original_price:
            original_price = (
                format_detail_price_decimal(original_price) or original_price
            )
        if price or original_price:
            return price, original_price, text_or_none(offer_currency)
    return None, None, saved_currency


def _iter_jsonld_offers(soup: BeautifulSoup) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for payload in _iter_jsonld_payloads(soup):
        offers.extend(_offers_from_jsonld_node(payload))
    return offers


def _iter_jsonld_payloads(soup: BeautifulSoup) -> list[Any]:
    payloads: list[Any] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text:
            continue
        try:
            payloads.append(json.loads(script_text))
        except json.JSONDecodeError:
            continue
    return payloads


def _offers_from_jsonld_node(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            results.extend(_offers_from_jsonld_node(item))
        return results
    if not isinstance(value, dict):
        return []
    for field_name in _jsonld_graph_fields:
        results.extend(_offers_from_jsonld_node(value.get(field_name)))
    node_type = _jsonld_type_text(value)
    if node_type in {"offer", "aggregateoffer"}:
        results.append(value)
    for field_name in _jsonld_offer_fields:
        results.extend(_offers_from_jsonld_node(value.get(field_name)))
    return results


def _jsonld_type_text(value: dict[str, Any]) -> str:
    for field_name in _jsonld_type_fields:
        raw_type = value.get(field_name)
        if isinstance(raw_type, list):
            raw_type = next((item for item in raw_type if text_or_none(item)), None)
        text = text_or_none(raw_type)
        if text:
            return text.rsplit("/", 1)[-1].lower()
    return ""


def _first_text(value: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        text = text_or_none(value.get(field_name))
        if text:
            return text
    return None


def _first_normalized_price(
    value: dict[str, Any],
    field_names: tuple[str, ...],
    *,
    currency: str | None,
) -> str | None:
    for field_name in field_names:
        normalized = _normalize_detail_price_candidate(
            value.get(field_name),
            currency=currency,
        )
        if normalized:
            return normalized
    return None


def _price_from_jsonld_specifications(
    offer: dict[str, Any],
    *,
    currency: str | None,
    current_price: str | None,
) -> str | None:
    specs: list[Any] = []
    for field_name in _jsonld_price_specification_fields:
        raw_specs = offer.get(field_name)
        if isinstance(raw_specs, list):
            specs.extend(raw_specs)
        elif raw_specs not in (None, "", [], {}):
            specs.append(raw_specs)
    current = detail_price_decimal(current_price)
    candidates: list[Decimal] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        price = detail_price_decimal(
            _first_normalized_price(spec, _jsonld_price_fields, currency=currency)
        )
        if price is None:
            continue
        if current is None or price > current:
            candidates.append(price)
    if not candidates:
        return None
    return _format_price_decimal(max(candidates))


def _normalize_detail_price_candidate(
    value: object,
    *,
    currency: str | None,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    if (
        currency
        and re.fullmatch(r"\d+(?:\.\d+)?", text)
        and "." not in text
        and len(re.sub(r"\D+", "", text)) <= 3
    ):
        return text
    return normalize_decimal_price(text, interpret_integral_as_cents=False)


__all__ = [
    "append_record_field_source",
    "backfill_detail_price_from_html",
    "detail_currency_hint_is_host_level",
    "drop_low_signal_zero_detail_price",
    "format_detail_price_decimal",
    "normalize_mismatched_host_currency_price",
    "reconcile_detail_price_magnitudes",
    "reconcile_detail_currency_with_url",
    "record_field_sources",
    "detail_price_decimal",
]
