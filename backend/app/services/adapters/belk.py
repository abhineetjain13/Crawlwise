from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.config.extraction_rules import (
    BELK_BRAND_SELECTORS,
    BELK_CARD_TITLE_ATTRS,
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
    LISTING_BRAND_MAX_WORDS,
)
from app.services.extract.listing_candidate_ranking import looks_like_utility_title
from app.services.field_value_core import (
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_price_text,
    finalize_record,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
)
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
    state_by_identity = {
        identity: record
        for record in state_index.values()
        if (identity := _belk_record_identity(record))
    }
    for record in _dom_listing_records(page_url, html):
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        state_record = state_index.get(url)
        if state_record is None:
            identity = _belk_record_identity(record)
            if identity:
                state_record = state_by_identity.get(identity)
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
        _first_payload_field(payload, field_name="title", page_url="", keys=BELK_PRODUCT_TITLE_KEYS)
        and _first_payload_field(payload, field_name="url", page_url="", keys=BELK_PRODUCT_URL_KEYS)
        and (
            _first_payload_field(payload, field_name="brand", page_url="", keys=BELK_PRODUCT_BRAND_KEYS)
            or _first_payload_field(payload, field_name="price", page_url="", keys=BELK_PRODUCT_PRICE_KEYS)
            or _first_payload_field(payload, field_name="image_url", page_url="", keys=BELK_PRODUCT_IMAGE_KEYS)
        )
    )


def _record_from_payload(product: dict[str, Any], *, page_url: str) -> dict[str, Any]:
    title = _first_payload_field(product, field_name="title", page_url=page_url, keys=BELK_PRODUCT_TITLE_KEYS)
    brand = _first_payload_field(product, field_name="brand", page_url=page_url, keys=BELK_PRODUCT_BRAND_KEYS)
    price_value = _first_payload_field(product, field_name="price", page_url=page_url, keys=BELK_PRODUCT_PRICE_KEYS)
    original_price_value = _first_payload_field(
        product,
        field_name="original_price",
        page_url=page_url,
        keys=BELK_PRODUCT_ORIGINAL_PRICE_KEYS,
    )
    image = _first_payload_field(product, field_name="image_url", page_url=page_url, keys=BELK_PRODUCT_IMAGE_KEYS)
    url = _first_payload_field(product, field_name="url", page_url=page_url, keys=BELK_PRODUCT_URL_KEYS)
    if brand in (None, "", [], {}):
        brand = _infer_belk_brand_from_url(url=str(url or ""), title=title)
    currency = coerce_field_value("currency", product, page_url)
    if currency in (None, "", [], {}):
        for key in (*BELK_PRODUCT_PRICE_KEYS, *BELK_PRODUCT_ORIGINAL_PRICE_KEYS):
            nested_value = product.get(key)
            if not isinstance(nested_value, dict):
                continue
            currency = coerce_field_value("currency", nested_value, page_url)
            if currency not in (None, "", [], {}):
                break
    return compact_dict(
        {
            "title": title,
            "brand": brand,
            "price": normalize_price(price_value, interpret_integral_as_cents=False),
            "original_price": normalize_price(original_price_value, interpret_integral_as_cents=False),
            "currency": currency,
            "image_url": image,
            "product_id": _first_payload_field(product, field_name="product_id", page_url=page_url, keys=BELK_PRODUCT_ID_KEYS),
            "url": url,
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
    image_title = _first_selector_attr(
        node,
        BELK_IMAGE_SELECTORS,
        ("alt", "title", "aria-label"),
    )
    title = (
        _first_belk_title(node)
        or _first_node_attr(node, BELK_CARD_TITLE_ATTRS)
        or image_title
    )
    url = absolute_url(page_url, href)
    brand = (
        _first_selector_text(node, BELK_BRAND_SELECTORS)
        or infer_brand_from_title_marker(title)
        or _infer_belk_brand_from_url(url=url, title=title)
    )
    return compact_dict(
        {
            "title": title,
            "brand": brand,
            "price": normalize_price(
                _first_selector_text(node, BELK_PRICE_SELECTORS)
                or extract_price_text(node.text(separator=" ", strip=True), prefer_last=False),
                interpret_integral_as_cents=False,
            ),
            "image_url": absolute_url(page_url, _srcset_first(image)) if image else None,
            "product_id": _attr(node, "data-cnstrc-item-id")
            or _attr(node, "data-tile-pid"),
            "url": url,
        }
    )


def _finalize_adapter_record(record: dict[str, Any], *, surface: str) -> dict[str, Any]:
    shaped = dict(record)
    shaped["_source"] = "belk_adapter"
    return finalize_record(shaped, surface=surface)


def _first_payload_field(
    payload: dict[str, Any],
    *,
    field_name: str,
    page_url: str,
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = coerce_field_value(field_name, payload.get(key), page_url)
        if value:
            return str(value)
    return None


def _infer_belk_brand_from_url(*, url: str, title: object) -> str | None:
    return infer_brand_from_product_url(url=url, title=title) or _infer_belk_brand_from_slug_prefix(
        url=url,
        title=title,
    )


def _infer_belk_brand_from_slug_prefix(*, url: str, title: object) -> str | None:
    title_tokens = _belk_slug_tokens(title)
    if len(title_tokens) < 2:
        return None
    path_parts = [
        part.split(".", 1)[0]
        for part in (urlparse(str(url or "")).path or "").split("/")
        if part
    ]
    slug = ""
    for index, part in enumerate(path_parts):
        if part.lower() == "p" and index + 1 < len(path_parts):
            slug = path_parts[index + 1]
            break
    if not slug and path_parts:
        slug = path_parts[-1]
    path_tokens = _belk_slug_tokens(slug)
    if len(path_tokens) < 2:
        return None
    min_match = min(3, len(title_tokens))
    for start in range(1, len(path_tokens)):
        if path_tokens[start] != title_tokens[0]:
            continue
        matched = 0
        while (
            matched < len(title_tokens)
            and start + matched < len(path_tokens)
            and path_tokens[start + matched] == title_tokens[matched]
        ):
            matched += 1
        if matched < min_match:
            continue
        brand_tokens = path_tokens[:start]
        if not brand_tokens or len(brand_tokens) > LISTING_BRAND_MAX_WORDS:
            continue
        return " ".join(token.capitalize() for token in brand_tokens)
    return None


def _belk_slug_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if token
    ]


def _belk_record_identity(record: dict[str, Any]) -> str:
    product_id = clean_text(record.get("product_id") or record.get("productId") or record.get("sku"))
    if product_id:
        return product_id.lower()
    return _belk_identity_from_url(str(record.get("url") or ""))


def _belk_identity_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path
    match = re.search(r"/([^/?#]+)/?$", path)
    segment = str(match.group(1) if match is not None else "").strip().lower()
    if not segment:
        return ""
    return re.sub(r"\.(?:html?|php|aspx?)$", "", segment)


def _first_node_attr(node: Any, attrs: tuple[str, ...]) -> str | None:
    for attr in attrs:
        value = clean_text(_attr(node, str(attr)))
        if _valid_belk_title(value):
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
    return not looks_like_utility_title(text)


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
