# Amazon platform adapter.
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from html import unescape
from itertools import product
from urllib.parse import urljoin
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    selectolax_node_attr,
    selectolax_node_text,
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
        return AdapterResult(
            records=records,
            source_type="amazon_adapter",
            adapter_name=self.name,
        )

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
        rating_text = selectolax_node_text(rating_el)
        rating_match = re.search(r"(\d+\.?\d*)", rating_text)
        review_text = selectolax_node_text(review_el)
        review_match = re.search(r"([\d,]+)", review_text)
        record = {
            "title": selectolax_node_text(title_el) or None,
            "price": selectolax_node_text(price_el) or None,
            "brand": _clean_brand(selectolax_node_text(brand_el)) if brand_el else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "review_count": int(review_match.group(1).replace(",", ""))
            if review_match
            else None,
            "image_url": selectolax_node_attr(image_el, "src")
            or selectolax_node_attr(image_el, "data-old-hires")
            if image_el
            else None,
            "description": desc_el.text(separator=" ", strip=True) if desc_el else None,
            "availability": selectolax_node_text(avail_el) or None,
            "url": url,
        }
        record.update(self._extract_detail_variants(parser, url))
        return record

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
        variant_axes: dict[str, list[str]] = {}
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
            variant_axes[axis_name] = values
            index = len(variant_axes)
            record[f"option{index}_name"] = axis_name
            record[f"option{index}_values"] = values
            if axis_name == "size":
                record["available_sizes"] = values
        if not variant_axes:
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
        selected_variant = next(
            (
                variant
                for variant in variants
                if variant.get("option_values") == selected_values
            ),
            None,
        )
        record["variant_axes"] = variant_axes
        if variants:
            record["variants"] = variants
            record["variant_count"] = len(variants)
        if selected_variant:
            record["selected_variant"] = selected_variant
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
