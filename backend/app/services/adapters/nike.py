from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter, adapter_host_matches
from app.services.extract.shared_variant_logic import split_variant_axes
from app.services.field_value_core import (
    absolute_url,
    clean_text,
    finalize_record,
    text_or_none,
)
from app.services.js_state_helpers import (
    availability_value,
    compact_dict,
    normalize_price,
    ordered_axes,
    select_variant,
    variant_attribute,
    variant_axes,
)


_NIKE_CURRENCY_BY_HOST = {
    "nike.com": "USD",
    "nike.in": "INR",
    "nike.co.in": "INR",
    "nike.co.uk": "GBP",
    "nike.com.au": "AUD",
    "nike.ca": "CAD",
}


def _currency_for(page_url: str) -> str:
    host = (urlparse(str(page_url or "")).hostname or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return _NIKE_CURRENCY_BY_HOST.get(host, "USD")


class NikeAdapter(BaseAdapter):
    name = "nike"
    platform_family = "nike"

    async def can_handle(self, url: str, html: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        raw_html = str(html or "")
        return (
            adapter_host_matches(host, "nike.com")
            or adapter_host_matches(host, "nike.in")
            or adapter_host_matches(host, "nike.co.in")
            or adapter_host_matches(host, "nike.co.uk")
            or adapter_host_matches(host, "nike.com.au")
            or adapter_host_matches(host, "nike.ca")
            or ("__PRELOADED_STATE__" in raw_html and "skuData" in raw_html)
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records: list[dict[str, Any]] = []
        if str(surface or "").strip().lower() == "ecommerce_detail":
            record = _extract_detail_record(url, html)
            if record:
                records.append(record)
        return AdapterResult(
            records=records, source_type="nike_adapter", adapter_name=self.name
        )


def _extract_detail_record(page_url: str, html: str) -> dict[str, Any] | None:
    product = _preloaded_product(html)
    if not product:
        return None
    record = _map_product(product, page_url=page_url)
    if not record:
        return None
    record["_source"] = "nike_adapter"
    return finalize_record(record, surface="ecommerce_detail")


def _preloaded_product(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    node = soup.find("script", id="__PRELOADED_STATE__")
    if node is None:
        return None
    raw = node.string or node.get_text()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    details = payload.get("details") if isinstance(payload, dict) else None
    sku_data = details.get("skuData") if isinstance(details, dict) else None
    product = sku_data.get("product") if isinstance(sku_data, dict) else None
    return product if isinstance(product, dict) and product.get("id") else None


def _map_product(product: dict[str, Any], *, page_url: str) -> dict[str, Any]:
    variants = _variants(product, page_url=page_url)
    selected_variant = select_variant(variants, page_url=page_url)
    axes = variant_axes(variants)
    selectable_axes, _single_value_axes = split_variant_axes(
        axes,
        always_selectable_axes=frozenset({"size"}),
    )
    size_values = (
        selectable_axes.get("size") if isinstance(selectable_axes, dict) else None
    )
    ordered = ordered_axes(["size", "color"], selectable_axes)
    images = _images(product)
    color = variant_attribute(selected_variant, "color") or _color_name(product)
    record = compact_dict(
        {
            "title": _title(product),
            "brand": "Nike",
            "product_id": product.get("id"),
            "sku": product.get("sku"),
            "part_number": product.get("sku"),
            "price": normalize_price(
                product.get("discountedPrice"), interpret_integral_as_cents=False
            ),
            "original_price": normalize_price(
                product.get("price"), interpret_integral_as_cents=False
            ),
            "currency": _currency_for(page_url),
            "availability": "out_of_stock"
            if product.get("isOutOfStock")
            else "in_stock",
            "description": _description(product),
            "product_details": _product_details(product),
            "color": color,
            "size": variant_attribute(selected_variant, "size"),
            "image_url": images[0] if images else text_or_none(product.get("imageUrl")),
            "additional_images": images[1:] if len(images) > 1 else None,
            "variants": variants or None,
            "selected_variant": selected_variant,
            "variant_axes": selectable_axes or None,
            "variant_count": len(variants) or None,
            "available_sizes": size_values[:20] if size_values else None,
            "url": absolute_url(page_url, product.get("action_url")) or page_url,
        }
    )
    for index, (axis_name, values) in enumerate(ordered[:2], start=1):
        record[f"option{index}_name"] = axis_name
        record[f"option{index}_values"] = values
    return record


def _title(product: dict[str, Any]) -> str | None:
    title = text_or_none(product.get("title"))
    subtitle = text_or_none(product.get("subTitle"))
    return clean_text(" ".join(part for part in (title, subtitle) if part)) or title


def _description(product: dict[str, Any]) -> str | None:
    summary = product.get("product_summary")
    if isinstance(summary, dict):
        return text_or_none(summary.get("description"))
    return None


def _product_details(product: dict[str, Any]) -> str | None:
    raw = text_or_none(product.get("view_product_details"))
    if not raw:
        return None
    return clean_text(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))


def _color_name(product: dict[str, Any]) -> str | None:
    color = product.get("color")
    if isinstance(color, dict):
        return text_or_none(color.get("name"))
    return text_or_none(color)


def _images(product: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in list(product.get("productMedia") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("mediaType") or "").strip().lower() != "image":
            continue
        image = text_or_none(item.get("url"))
        if image:
            values.append(image)
    fallback = text_or_none(product.get("imageUrl"))
    if fallback:
        values.insert(0, fallback)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _variants(product: dict[str, Any], *, page_url: str) -> list[dict[str, Any]]:
    size_options = product.get("sizeOptions")
    options = size_options.get("options") if isinstance(size_options, dict) else None
    color = _color_name(product)
    rows: list[dict[str, Any]] = []
    for option in list(options or []):
        if not isinstance(option, dict):
            continue
        size = text_or_none(
            option.get("sizeName") or option.get("label") or option.get("size")
        )
        if not size:
            continue
        row = compact_dict(
            {
                "variant_id": option.get("id"),
                "sku": option.get("sku"),
                "size": size,
                "color": color,
                "price": normalize_price(
                    option.get("discountedPrice"), interpret_integral_as_cents=False
                ),
                "original_price": normalize_price(
                    option.get("price"), interpret_integral_as_cents=False
                ),
                "currency": _currency_for(page_url),
                "availability": "out_of_stock"
                if option.get("isOutOfStock")
                else "in_stock",
                "url": absolute_url(page_url, option.get("action_url")) or page_url,
                "option_values": compact_dict({"size": size, "color": color}),
            }
        )
        if row:
            rows.append(row)
    if rows:
        return rows
    if product.get("isOneSize"):
        size = "One Size"
        return [
            compact_dict(
                {
                    "variant_id": product.get("id"),
                    "sku": product.get("sku"),
                    "size": size,
                    "color": color,
                    "price": normalize_price(
                        product.get("discountedPrice"),
                        interpret_integral_as_cents=False,
                    ),
                    "original_price": normalize_price(
                        product.get("price"), interpret_integral_as_cents=False
                    ),
                    "currency": _currency_for(page_url),
                    "availability": availability_value(
                        {"available": not product.get("isOutOfStock")}
                    ),
                    "url": absolute_url(page_url, product.get("action_url"))
                    or page_url,
                    "option_values": compact_dict({"size": size, "color": color}),
                }
            )
        ]
    return []
