# Amazon platform adapter.
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from html import unescape
from itertools import product
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    selectolax_node_attr,
    selectolax_node_text,
)
from app.services.field_value_core import (
    extract_currency_code,
    flatten_variants_for_public_output,
)


def _clean_brand(value: str) -> str:
    cleaned = re.sub(r"^\s*Brand:\s*", "", value or "", flags=re.I).strip()
    store_match = re.match(r"^\s*Visit\s+the\s+(.+?)\s+Store\s*$", cleaned, flags=re.I)
    if store_match:
        return store_match.group(1).strip()
    return cleaned


def _axis_key(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("color"):
        return "color"
    if normalized.startswith("size"):
        return "size"
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _availability(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized == "UNAVAILABLE":
        return "out_of_stock"
    if normalized in {"AVAILABLE", "SELECTED"}:
        return "in_stock"
    return None


def _normalize_price_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    match = re.search(
        r"(?:(?:[$€£₹]|[A-Z]{3})\s*)?\d[\d,]*(?:\.\d{1,2})?(?:\s*(?:[$€£₹]|[A-Z]{3}))?",
        text,
        re.I,
    )
    return match.group(0) if match else None


def _asin_from_url(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, re.I)
    return match.group(1).upper() if match else None


def _clean_detail_text(value: object) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _gtin_like(value: object) -> str | None:
    text = re.sub(r"\D+", "", str(value or ""))
    return text if len(text) in {8, 12, 13, 14} else None


def _iter_json_state_payloads(
    parser: LexborHTMLParser,
) -> Iterable[Mapping[str, object]]:
    for script in parser.css("script[type='a-state']"):
        raw = selectolax_node_text(script)
        if not raw:
            continue
        try:
            payload = json.loads(unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            yield payload


class AmazonAdapter(BaseAdapter):
    name = "amazon"
    domains = [
        "amazon.com",
        "amazon.co.uk",
        "amazon.de",
        "amazon.fr",
        "amazon.it",
        "amazon.es",
        "amazon.ca",
        "amazon.in",
        "amazon.co.jp",
        "amazon.com.au",
        "amazon.com.br",
    ]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        parser = LexborHTMLParser(html)
        records = []
        if surface in ("ecommerce_detail",):
            record = self._extract_detail(parser, url)
            if record:
                records.append(record)
        elif surface in ("ecommerce_listing",):
            records = self._extract_listing(parser, url)
        return self._result(records)

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first("#productTitle")
        price_el = parser.css_first(
            ".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice"
        )
        brand_el = parser.css_first("#bylineInfo, .po-brand .a-span9 .a-size-base")
        rating_el = parser.css_first("#acrPopover .a-icon-alt, .a-icon-star span")
        review_el = parser.css_first("#acrCustomerReviewText")
        image_el = parser.css_first("#landingImage, #imgBlkFront")
        desc_el = parser.css_first("#productDescription p, #feature-bullets")
        avail_el = parser.css_first("#availability span")
        if not title_el:
            return None
        detail_table = self._detail_table(parser)
        asin = (
            _asin_from_url(url)
            or self._detail_value_from_table(detail_table, "asin")
            or self._detail_value_from_table(detail_table, "item model number")
        )
        rating_text = selectolax_node_text(rating_el)
        rating_match = re.search(r"(\d+\.?\d*)", rating_text)
        review_text = selectolax_node_text(review_el)
        review_match = re.search(r"([\d,]+)", review_text)
        price_text = _normalize_price_text(selectolax_node_text(price_el))
        currency = extract_currency_code(price_text)
        images = self._detail_images(parser)
        bullets = self._feature_bullets(parser)
        description = self._detail_description(parser)
        specifications = self._detail_specifications_text(detail_table)
        record = {
            "title": selectolax_node_text(title_el) or None,
            "price": price_text,
            "brand": _clean_brand(selectolax_node_text(brand_el)) if brand_el else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "review_count": int(review_match.group(1).replace(",", ""))
            if review_match
            else None,
            "image_url": (
                images[0]
                if images
                else (
                    selectolax_node_attr(image_el, "src")
                    or selectolax_node_attr(image_el, "data-old-hires")
                    if image_el
                    else None
                )
            ),
            "additional_images": images[1:] if len(images) > 1 else None,
            "description": description
            or (desc_el.text(separator=" ", strip=True) if desc_el else None),
            "availability": _clean_detail_text(selectolax_node_text(avail_el)),
            "currency": currency,
            "product_id": asin,
            "part_number": self._detail_value_from_table(
                detail_table, "item model number"
            ),
            "barcode": (
                self._detail_value_from_table(detail_table, "upc")
                or self._detail_value_from_table(detail_table, "ean")
            ),
            "product_type": self._detail_product_type(parser),
            "features": bullets or None,
            "specifications": specifications,
            "product_details": self._detail_product_details_text(
                description, bullets, detail_table
            ),
            "url": url,
        }
        record.update(self._extract_detail_variants(parser, url))
        return record

    def _detail_images(self, parser: LexborHTMLParser) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for node in parser.css(
            "#landingImage, #imgBlkFront, #altImages img, #imageBlock img"
        ):
            for attr_name in ("data-old-hires", "src"):
                candidate = selectolax_node_attr(node, attr_name)
                if not candidate:
                    continue
                normalized = candidate.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    values.append(normalized)
            dynamic_images = selectolax_node_attr(node, "data-a-dynamic-image")
            if not dynamic_images:
                continue
            try:
                payload = json.loads(dynamic_images)
            except json.JSONDecodeError:
                continue
            for candidate in payload.keys() if isinstance(payload, Mapping) else []:
                normalized = str(candidate or "").strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    values.append(normalized)
        return values

    def _feature_bullets(self, parser: LexborHTMLParser) -> list[str]:
        values: list[str] = []
        for node in parser.css("#feature-bullets li, #feature-bullets .a-list-item"):
            text = _clean_detail_text(selectolax_node_text(node))
            if not text or text.lower() in {"", "see more product details"}:
                continue
            if text not in values:
                values.append(text)
        return values

    def _detail_description(self, parser: LexborHTMLParser) -> str | None:
        parts = [
            _clean_detail_text(selectolax_node_text(node))
            for node in parser.css(
                "#productDescription p, #productDescription, #bookDescription_feature_div"
            )
        ]
        cleaned_parts = [part for part in parts if isinstance(part, str) and part]
        return " ".join(dict.fromkeys(cleaned_parts)).strip() or None

    def _detail_table(self, parser: LexborHTMLParser) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in parser.css(
            "#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr"
        ):
            header = _clean_detail_text(selectolax_node_text(row.css_first("th")))
            value = _clean_detail_text(selectolax_node_text(row.css_first("td")))
            if header and value:
                values[header] = value
        for item in parser.css("#detailBullets_feature_div li"):
            text = _clean_detail_text(selectolax_node_text(item))
            if not text or ":" not in text:
                continue
            key, value = text.split(":", 1)
            cleaned_key = _clean_detail_text(key)
            cleaned_value = _clean_detail_text(value)
            if cleaned_key and cleaned_value:
                values.setdefault(cleaned_key, cleaned_value)
        return values

    def _detail_value_from_table(
        self, detail_table: dict[str, str], label: str
    ) -> str | None:
        target = label.strip().lower()
        for key, value in detail_table.items():
            normalized_key = str(key or "").strip().lower().removesuffix(":")
            if normalized_key == target:
                return value
        return None

    def _detail_product_type(self, parser: LexborHTMLParser) -> str | None:
        crumbs = [
            _clean_detail_text(selectolax_node_text(node))
            for node in parser.css(
                "#wayfinding-breadcrumbs_feature_div li, #wayfinding-breadcrumbs_container li"
            )
        ]
        crumbs = [crumb for crumb in crumbs if crumb]
        return crumbs[-1] if crumbs else None

    def _detail_specifications_text(self, detail_table: dict[str, str]) -> str | None:
        if not detail_table:
            return None
        return " ".join(f"{key}: {value}" for key, value in detail_table.items())

    def _detail_product_details_text(
        self,
        description: str | None,
        bullets: list[str],
        detail_table: dict[str, str],
    ) -> str | None:
        parts: list[str] = []
        if description:
            parts.append(description)
        if bullets:
            parts.append(" ".join(bullets))
        if detail_table:
            parts.append(self._detail_specifications_text(detail_table) or "")
        merged = " ".join(part for part in parts if part).strip()
        return merged or None

    def _extract_detail_variants(self, parser: LexborHTMLParser, url: str) -> dict:
        state = next(
            (
                payload
                for payload in _iter_json_state_payloads(parser)
                if isinstance(payload.get("sortedDimValuesForAllDims"), Mapping)
            ),
            None,
        )
        if not state:
            return {}
        raw_dims = state.get("sortedDimValuesForAllDims")
        if not isinstance(raw_dims, Mapping):
            return {}
        dim_order = self._twister_dimension_order(parser, raw_dims)
        if not dim_order:
            return {}
        axis_entries: dict[str, list[dict[str, object]]] = {}
        axis_values_by_name: dict[str, list[str]] = {}
        selected_values: dict[str, str] = {}
        record: dict[str, object] = {}
        for raw_dim in dim_order:
            raw_entries = raw_dims.get(raw_dim)
            if not isinstance(raw_entries, list):
                continue
            axis_name = _axis_key(raw_dim)
            entries: list[dict[str, object]] = []
            values: list[str] = []
            for entry in raw_entries:
                if not isinstance(entry, Mapping):
                    continue
                value = str(entry.get("dimensionValueDisplayText") or "").strip()
                if not value:
                    continue
                entry_map = dict(entry)
                entry_map["value"] = value
                entries.append(entry_map)
                if value not in values:
                    values.append(value)
                if (
                    str(entry.get("dimensionValueState") or "").strip().upper()
                    == "SELECTED"
                ):
                    selected_values[axis_name] = value
            if not values:
                continue
            axis_entries[axis_name] = entries
            axis_values_by_name[axis_name] = values
        if not axis_values_by_name:
            return {}
        variants = self._twister_variants(
            state.get("sortedVariations"),
            dim_order=dim_order,
            axis_entries=axis_entries,
            page_url=url,
        )
        if not variants:
            variants = self._twister_variants_from_product(
                dim_order=dim_order,
                axis_entries=axis_entries,
                page_url=url,
            )
        if variants:
            flat_variants = flatten_variants_for_public_output(variants, page_url=url)
            if flat_variants:
                record["variants"] = flat_variants
                record["variant_count"] = len(flat_variants)
        for axis_name, value in selected_values.items():
            record[axis_name] = value
        return record

    def _twister_dimension_order(
        self,
        parser: LexborHTMLParser,
        raw_dims: Mapping[object, object],
    ) -> list[str]:
        dim_keys = [str(key) for key in raw_dims.keys()]
        ordered: list[str] = []
        for node in parser.css("[id^='inline-twister-row-']"):
            raw_id = selectolax_node_attr(node, "id") or ""
            dim = raw_id.removeprefix("inline-twister-row-")
            if dim in raw_dims and dim not in ordered:
                ordered.append(dim)
        ordered.extend(dim for dim in dim_keys if dim not in ordered)
        return ordered

    def _twister_variants(
        self,
        raw_variations: object,
        *,
        dim_order: list[str],
        axis_entries: dict[str, list[dict[str, object]]],
        page_url: str,
    ) -> list[dict[str, object]]:
        variants: list[dict[str, object]] = []
        if not isinstance(raw_variations, list):
            return variants
        axis_names = [_axis_key(dim) for dim in dim_order]
        for row in raw_variations:
            if not isinstance(row, list) or len(row) != len(axis_names):
                continue
            option_values: dict[str, str] = {}
            metadata: dict[str, object] = {}
            for axis_name, index in zip(axis_names, row, strict=False):
                if not isinstance(index, int):
                    continue
                entries = axis_entries.get(axis_name) or []
                if index < 0 or index >= len(entries):
                    continue
                self._merge_twister_entry(
                    option_values, metadata, axis_name, entries[index], page_url
                )
            if option_values:
                variants.append(
                    {"option_values": option_values, **option_values, **metadata}
                )
        return variants

    def _twister_variants_from_product(
        self,
        *,
        dim_order: list[str],
        axis_entries: dict[str, list[dict[str, object]]],
        page_url: str,
    ) -> list[dict[str, object]]:
        variants: list[dict[str, object]] = []
        axis_names = [_axis_key(dim) for dim in dim_order]
        if len(axis_names) != 1:
            return variants
        entry_lists = [axis_entries.get(axis_name) or [] for axis_name in axis_names]
        for combo in product(*entry_lists):
            option_values: dict[str, str] = {}
            metadata: dict[str, object] = {}
            for axis_name, entry in zip(axis_names, combo, strict=False):
                self._merge_twister_entry(
                    option_values, metadata, axis_name, entry, page_url
                )
            if option_values:
                variants.append(
                    {"option_values": option_values, **option_values, **metadata}
                )
        return variants

    def _merge_twister_entry(
        self,
        option_values: dict[str, str],
        metadata: dict[str, object],
        axis_name: str,
        entry: Mapping[str, object],
        page_url: str,
    ) -> None:
        value = str(entry.get("value") or "").strip()
        if value:
            option_values[axis_name] = value
        asin = str(entry.get("defaultAsin") or "").strip()
        page_load_url = str(entry.get("pageLoadURL") or "").strip()
        if asin and (not metadata.get("variant_id") or page_load_url):
            metadata["variant_id"] = asin
        if page_load_url:
            metadata["url"] = urljoin(page_url, page_load_url)
        availability = _availability(entry.get("dimensionValueState"))
        if availability and metadata.get("availability") in (None, "", [], {}):
            metadata["availability"] = availability

    def _extract_listing(self, parser: LexborHTMLParser, url: str) -> list[dict]:
        records = []
        cards = parser.css("[data-component-type='s-search-result']")
        for card in cards:
            title_el = card.css_first("h2 a span")
            price_whole = card.css_first(".a-price-whole")
            price_frac = card.css_first(".a-price-fraction")
            image_el = card.css_first(".s-image")
            link_el = card.css_first("h2 a")
            rating_el = card.css_first(".a-icon-star-small span")
            price = None
            if price_whole:
                whole = selectolax_node_text(price_whole).rstrip(".")
                frac = selectolax_node_text(price_frac) if price_frac else "00"
                price = f"{whole}.{frac}"
            rating_text = selectolax_node_text(rating_el)
            rating_match = re.search(r"(\d+\.?\d*)", rating_text)
            href = selectolax_node_attr(link_el, "href") or ""
            if href and not href.startswith("http"):
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            if title_el:
                records.append(
                    {
                        "title": selectolax_node_text(title_el),
                        "price": price,
                        "image_url": selectolax_node_attr(image_el, "src"),
                        "url": href,
                        "rating": float(rating_match.group(1))
                        if rating_match
                        else None,
                    }
                )
        return records
