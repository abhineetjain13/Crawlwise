from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.config.extraction_rules import (
    BELK_BRAND_SELECTORS,
    BELK_IMAGE_SELECTORS,
    BELK_PRICE_SELECTORS,
    BELK_PRODUCT_BRAND_KEYS,
    BELK_PRODUCT_CARD_SELECTORS,
    BELK_PRODUCT_ID_KEYS,
    BELK_PRODUCT_IMAGE_KEYS,
    BELK_PRODUCT_ORIGINAL_PRICE_KEYS,
    BELK_PRODUCT_PRICE_KEYS,
    BELK_PRODUCT_TITLE_KEYS,
    BELK_PRODUCT_URL_KEYS,
    BELK_TITLE_MAX_CHARS,
    BELK_TITLE_MIN_CHARS,
    BELK_TITLE_SELECTORS,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_UTILITY_TITLE_TOKENS,
)
from app.services.field_value_core import absolute_url, clean_text, finalize_record, text_or_none
from app.services.js_state_helpers import compact_dict, normalize_price
from app.services.structured_sources import harvest_js_state_objects


class BelkAdapter(BaseAdapter):
    name = "belk"
    platform_family = "belk"

    async def can_handle(self, url: str, html: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host.endswith("belk.com") or "belk.com" in str(html or "").lower()

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        normalized_surface = str(surface or "").strip().lower()
        records: list[dict[str, Any]] = []
        if normalized_surface == "ecommerce_listing":
            records.extend(_extract_listing_records(url, html))
        elif normalized_surface == "ecommerce_detail":
            record = _extract_detail_record(url, html)
            if record:
                records.append(record)
        return AdapterResult(records=records, source_type="belk_adapter", adapter_name=self.name)


def _extract_listing_records(page_url: str, html: str) -> list[dict[str, Any]]:
    state_index = _state_product_index(page_url, html)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for record in _dom_listing_records(page_url, html):
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        state_record = state_index.get(url)
        if state_record:
            merged = dict(state_record)
            merged.update({key: value for key, value in record.items() if value not in (None, "", [], {})})
            record = merged
        finalized = _finalize_adapter_record(record, surface="ecommerce_listing")
        final_url = str(finalized.get("url") or "")
        if not final_url or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        records.append(finalized)
    for url, record in state_index.items():
        if url in seen_urls:
            continue
        finalized = _finalize_adapter_record(record, surface="ecommerce_listing")
        final_url = str(finalized.get("url") or "")
        if not final_url or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        records.append(finalized)
        if len(records) >= adapter_runtime_settings.belk_max_products:
            break
    return records[: adapter_runtime_settings.belk_max_products]


def _extract_detail_record(page_url: str, html: str) -> dict[str, Any] | None:
    page_path = (urlparse(page_url).path or "").rstrip("/").lower()
    for record in _state_product_index(page_url, html).values():
        record_url = str(record.get("url") or "")
        if (urlparse(record_url).path or "").rstrip("/").lower() == page_path:
            return _finalize_adapter_record(record, surface="ecommerce_detail")
    dom_records = _dom_listing_records(page_url, html)
    if len(dom_records) == 1:
        return _finalize_adapter_record(dom_records[0], surface="ecommerce_detail")
    return None


def _state_product_index(page_url: str, html: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for root in harvest_js_state_objects(None, html).values():
        for product in _walk_product_payloads(root):
            record = _record_from_payload(product, page_url=page_url)
            url = str(record.get("url") or "")
            if url:
                index[url] = record
            if len(index) >= adapter_runtime_settings.belk_max_products:
                return index
    return index


def _walk_product_payloads(value: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(node: object) -> None:
        if len(rows) >= adapter_runtime_settings.belk_max_products:
            return
        if isinstance(node, dict):
            if _looks_like_product_payload(node):
                rows.append(node)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child)
            return
        if isinstance(node, list):
            for child in node:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(value)
    return rows


def _looks_like_product_payload(payload: dict[str, Any]) -> bool:
    return bool(
        _first_text(payload, BELK_PRODUCT_TITLE_KEYS)
        and _first_text(payload, BELK_PRODUCT_URL_KEYS)
        and (
            _first_text(payload, BELK_PRODUCT_BRAND_KEYS)
            or _first_text(payload, BELK_PRODUCT_PRICE_KEYS)
            or _first_text(payload, BELK_PRODUCT_IMAGE_KEYS)
        )
    )


def _record_from_payload(product: dict[str, Any], *, page_url: str) -> dict[str, Any]:
    image = _first_text(product, BELK_PRODUCT_IMAGE_KEYS)
    return compact_dict(
        {
            "title": _first_text(product, BELK_PRODUCT_TITLE_KEYS),
            "brand": _first_text(product, BELK_PRODUCT_BRAND_KEYS),
            "price": normalize_price(_first_text(product, BELK_PRODUCT_PRICE_KEYS), interpret_integral_as_cents=False),
            "original_price": normalize_price(_first_text(product, BELK_PRODUCT_ORIGINAL_PRICE_KEYS), interpret_integral_as_cents=False),
            "image_url": absolute_url(page_url, image) if image else None,
            "product_id": _first_text(product, BELK_PRODUCT_ID_KEYS),
            "url": absolute_url(page_url, _first_text(product, BELK_PRODUCT_URL_KEYS)),
        }
    )


def _dom_listing_records(page_url: str, html: str) -> list[dict[str, Any]]:
    parser = LexborHTMLParser(html)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for node in _product_card_nodes(parser):
        record = _record_from_card(node, page_url=page_url)
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        records.append(record)
        if len(records) >= adapter_runtime_settings.belk_max_products:
            break
    return records


def _product_card_nodes(parser: LexborHTMLParser) -> list[Any]:
    nodes: list[Any] = []
    seen: set[str] = set()
    for selector in BELK_PRODUCT_CARD_SELECTORS:
        try:
            matches = parser.css(str(selector))
        except Exception:
            continue
        for node in matches:
            key = str(getattr(node, "html", "") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            nodes.append(node)
    return nodes


def _record_from_card(node: Any, *, page_url: str) -> dict[str, Any]:
    anchor = node.css_first("a[href]")
    href = _attr(anchor, "href") if anchor is not None else ""
    image = _first_selector_attr(node, BELK_IMAGE_SELECTORS, ("src", "data-src", "srcset"))
    return compact_dict(
        {
            "title": _first_belk_title(node),
            "brand": _first_selector_text(node, BELK_BRAND_SELECTORS),
            "price": normalize_price(_first_selector_text(node, BELK_PRICE_SELECTORS), interpret_integral_as_cents=False),
            "image_url": absolute_url(page_url, _srcset_first(image)) if image else None,
            "url": absolute_url(page_url, href),
        }
    )


def _finalize_adapter_record(record: dict[str, Any], *, surface: str) -> dict[str, Any]:
    shaped = dict(record)
    shaped["_source"] = "belk_adapter"
    return finalize_record(shaped, surface=surface)


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = text_or_none(payload.get(key))
        if value:
            return value
    return None


def _first_selector_text(node: Any, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        try:
            match = node.css_first(str(selector))
        except Exception:
            continue
        if match is None:
            continue
        value = clean_text(match.text(strip=True)) or _attr(match, "title") or _attr(match, "aria-label")
        if value:
            return value
    return None


def _first_belk_title(node: Any) -> str | None:
    for selector in BELK_TITLE_SELECTORS:
        try:
            match = node.css_first(str(selector))
        except Exception:
            continue
        if match is None:
            continue
        value = clean_text(match.text(strip=True)) or _attr(match, "title") or _attr(match, "aria-label")
        if _valid_belk_title(value):
            return value
    return None


def _valid_belk_title(value: object) -> bool:
    text = clean_text(str(value or ""))
    if len(text) < BELK_TITLE_MIN_CHARS or len(text) > BELK_TITLE_MAX_CHARS:
        return False
    lowered = text.casefold()
    if any(re.search(pattern, lowered, flags=re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS):
        return False
    return not any(token in lowered for token in LISTING_UTILITY_TITLE_TOKENS)


def _first_selector_attr(node: Any, selectors: tuple[str, ...], attrs: tuple[str, ...]) -> str | None:
    for selector in selectors:
        try:
            matches = node.css(str(selector))
        except Exception:
            continue
        for match in matches:
            for attr in attrs:
                value = _attr(match, attr)
                if value:
                    return value
    return None


def _attr(node: Any, name: str) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    return str(attrs.get(name) or "").strip()


def _srcset_first(value: object) -> str:
    return str(value or "").split(",", 1)[0].strip().split(" ", 1)[0].strip()
