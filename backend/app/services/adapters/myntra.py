from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter
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
    stock_quantity,
    variant_attribute,
    variant_axes,
)
from app.services.structured_sources import harvest_js_state_objects


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class MyntraAdapter(BaseAdapter):
    name = "myntra"
    platform_family = "myntra"

    async def can_handle(self, url: str, html: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host.endswith("myntra.com") or "window.__myx" in str(html or "")

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        normalized_surface = str(surface or "").strip().lower()
        records: list[dict[str, Any]] = []
        if normalized_surface == "ecommerce_detail":
            record = _extract_detail_record(url, html)
            if record:
                records.append(record)
        elif normalized_surface == "ecommerce_listing":
            records.extend(_extract_listing_records(url, html))
        return self._result(records)


def _extract_detail_record(page_url: str, html: str) -> dict[str, Any] | None:
    state_objects = harvest_js_state_objects(None, html)
    myx = state_objects.get("__myx")
    if not isinstance(myx, dict):
        return None
    product = myx.get("pdpData")
    if not isinstance(product, dict):
        return None
    if not looks_like_myx_product_payload(product):
        return None
    mapped = map_myx_product_payload(product, page_url=page_url)
    if not mapped:
        return None
    mapped["_source"] = "myntra_adapter"
    return finalize_record(mapped, surface="ecommerce_detail")


def _extract_listing_records(page_url: str, html: str) -> list[dict[str, Any]]:
    state_index = _myntra_listing_state_index(page_url, html)
    parser = LexborHTMLParser(html)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for node in parser.css("li.product-base"):
        record = _listing_record_from_card(node, page_url=page_url)
        if not record:
            continue
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        state_record = state_index.get(url)
        if state_record:
            merged = dict(state_record)
            merged.update(
                {
                    key: value
                    for key, value in record.items()
                    if value not in (None, "", [], {})
                }
            )
            record = merged
        record["_source"] = "myntra_adapter"
        finalized = finalize_record(record, surface="ecommerce_listing")
        final_url = str(finalized.get("url") or "")
        if not final_url or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        records.append(finalized)
    return records


def _myntra_listing_state_index(page_url: str, html: str) -> dict[str, dict[str, Any]]:
    state_objects = harvest_js_state_objects(None, html)
    myx = state_objects.get("__myx")
    products = (
        ((myx or {}).get("searchData") or {}).get("results") or {}
    ).get("products")
    if not isinstance(products, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        record = _listing_record_from_state_product(product, page_url=page_url)
        url = str(record.get("url") or "")
        if url:
            index[url] = record
    return index


def _listing_record_from_state_product(
    product: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    inventory = next(
        (
            row
            for row in list(product.get("inventoryInfo") or [])
            if isinstance(row, dict)
        ),
        None,
    )
    original_price = normalize_price(
        product.get("mrp"),
        interpret_integral_as_cents=False,
    )
    price = normalize_price(
        product.get("price"),
        interpret_integral_as_cents=False,
    ) or original_price
    return compact_dict(
        {
            "title": product.get("productName") or product.get("product"),
            "brand": product.get("brand"),
            "price": price,
            "original_price": original_price,
            "rating": product.get("rating"),
            "review_count": product.get("ratingCount"),
            "sizes": text_or_none(product.get("sizes")),
            "product_id": product.get("productId"),
            "image_url": text_or_none(product.get("searchImage")),
            "url": absolute_url(page_url, product.get("landingPageUrl")),
            "availability": availability_value(inventory),
        }
    )


def _listing_record_from_card(
    node,
    *,
    page_url: str,
) -> dict[str, Any] | None:
    anchor = node.css_first("a[href]")
    if anchor is None:
        return None
    href = text_or_none((getattr(anchor, "attributes", {}) or {}).get("href"))
    url = absolute_url(page_url, href)
    if not url:
        return None
    attrs = getattr(node, "attributes", {}) or {}
    brand = _node_text(node, "h3.product-brand")
    product_name = _node_text(node, "h4.product-product")
    if not product_name:
        return None
    discounted_text = _node_text(node, ".product-discountedPrice")
    strike_text = _node_text(node, ".product-strike")
    sizes = _node_text(node, "h4.product-sizes")
    rating = _node_text(node, ".product-ratingsContainer > span")
    review_count = _node_text(node, ".product-ratingsCount")
    return compact_dict(
        {
            "title": product_name,
            "brand": brand,
            "price": normalize_price(discounted_text, interpret_integral_as_cents=False),
            "original_price": normalize_price(
                strike_text,
                interpret_integral_as_cents=False,
            ),
            "sizes": sizes.replace("Sizes:", "").strip() if sizes else None,
            "rating": rating,
            "review_count": review_count,
            "product_id": text_or_none(attrs.get("id")),
            "url": url,
        }
    )


def _node_text(node, selector: str) -> str | None:
    match = node.css_first(selector)
    if match is None:
        return None
    return text_or_none(clean_text(match.text(strip=True)))


def looks_like_myx_product_payload(product: dict[str, Any]) -> bool:
    return isinstance(product, dict) and bool(
        isinstance(product.get("sizes"), list)
        and isinstance(product.get("media"), dict)
        and (
            product.get("mrp") not in (None, "", [], {})
            or isinstance(product.get("price"), dict)
        )
    )


def map_myx_product_payload(product: dict[str, Any], *, page_url: str) -> dict[str, Any]:
    images = _myx_images(product)
    base_color = text_or_none(product.get("baseColour"))
    variants = _myx_variants(product, page_url=page_url, color=base_color)
    selected_variant = select_variant(variants, page_url=page_url)
    axes = variant_axes(variants)
    selectable_axes, _ = split_variant_axes(
        axes,
        always_selectable_axes=frozenset({"size"}),
    )
    size_values = selectable_axes.get("size") if isinstance(selectable_axes, dict) else None
    ordered = ordered_axes(["size", "color"], selectable_axes)
    color_options = [
        color
        for color in (
            text_or_none(item.get("label"))
            for item in list(product.get("colours") or [])
            if isinstance(item, dict)
        )
        if color
    ]
    record = compact_dict(
        {
            "title": product.get("name"),
            "brand": product.get("brand"),
            "product_id": product.get("id"),
            "price": _myx_price(product, price_key="discountedPrice"),
            "original_price": _myx_price(product, price_key="mrp"),
            "currency": text_or_none(product.get("currency")) or text_or_none(product.get("currencyCode")) or text_or_none(product.get("priceCurrency")),
            "availability": availability_value(selected_variant) or None,
            "stock_quantity": stock_quantity(selected_variant),
            "sku": variant_attribute(selected_variant, "sku"),
            "color": variant_attribute(selected_variant, "color") or base_color,
            "size": variant_attribute(selected_variant, "size"),
            "image_url": (
                variant_attribute(selected_variant, "image_url")
                or (images[0] if images else None)
            ),
            "additional_images": images[1:] if len(images) > 1 else None,
            "image_count": len(images) or None,
            "variants": variants or None,
            "selected_variant": selected_variant,
            "variant_axes": selectable_axes or None,
            "variant_count": len(variants) or None,
            "available_sizes": size_values[:20] if size_values else None,
            "option2_values": color_options[:20] if color_options else None,
            "url": text_or_none(product.get("landingPageUrl")) or page_url,
        }
    )
    if ordered:
        record["option1_name"] = ordered[0][0]
        record["option1_values"] = ordered[0][1]
    if len(ordered) > 1:
        record["option2_name"] = ordered[1][0]
        record["option2_values"] = ordered[1][1]
    elif color_options:
        record["option2_name"] = "color"
    return record


def _myx_price(product: dict[str, Any], *, price_key: str) -> str | None:
    if price_key == "discountedPrice":
        selected_seller = product.get("selectedSeller")
        if isinstance(selected_seller, dict):
            value = selected_seller.get("discountedPrice")
            if value not in (None, "", [], {}):
                return normalize_price(value, interpret_integral_as_cents=False)
    price_payload = _dict_or_empty(product.get("price"))
    common_price = _dict_or_empty(product.get("commonPrice"))
    value = (
        price_payload.get("discounted")
        if price_key == "discountedPrice"
        else price_payload.get("mrp")
    )
    if value in (None, "", [], {}):
        value = common_price.get("discountedPrice" if price_key == "discountedPrice" else "mrp")
    if value in (None, "", [], {}):
        value = price_payload.get("discountedPrice" if price_key == "discountedPrice" else "mrp")
    if value in (None, "", [], {}):
        value = product.get("mrp" if price_key == "mrp" else "discountedPrice")
    return normalize_price(value, interpret_integral_as_cents=False)


def _myx_images(product: dict[str, Any]) -> list[str]:
    media = product.get("media")
    if not isinstance(media, dict):
        return []
    values: list[str] = []
    for album in list(media.get("albums") or []):
        if not isinstance(album, dict):
            continue
        for image in list(album.get("images") or []):
            if not isinstance(image, dict):
                continue
            for key in ("imageURL", "secureSrc", "src"):
                value = text_or_none(image.get(key))
                if value:
                    values.append(value)
                    break
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.replace("http://", "https://").lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value.replace("http://", "https://"))
    return deduped


def _myx_variants(
    product: dict[str, Any],
    *,
    page_url: str,
    color: str | None,
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for item in list(product.get("sizes") or []):
        if not isinstance(item, dict):
            continue
        seller = _dict_or_empty(item.get("selectedSeller"))
        discount = _dict_or_empty(seller.get("discount"))
        row = compact_dict(
            {
                "variant_id": text_or_none(item.get("skuId")),
                "sku": text_or_none(item.get("skuId")),
                "size": text_or_none(item.get("label")),
                "color": color,
                "price": normalize_price(
                    seller.get("discountedPrice"),
                    interpret_integral_as_cents=False,
                ),
                "original_price": normalize_price(
                    seller.get("mrp") or product.get("mrp"),
                    interpret_integral_as_cents=False,
                ),
                "availability": "in_stock" if bool(item.get("available")) else "out_of_stock",
                "stock_quantity": seller.get("availableCount"),
                "url": _myx_variant_url(page_url, item),
                "image_url": None,
                "option_values": compact_dict({"size": text_or_none(item.get("label")), "color": color}),
            }
        )
        if discount.get("discountPercent") not in (None, "", [], {}):
            row["discount_percentage"] = discount.get("discountPercent")
        if row:
            variants.append(row)
    return variants


def _myx_variant_url(page_url: str, item: dict[str, Any]) -> str | None:
    action = text_or_none(item.get("action"))
    if action:
        return absolute_url(page_url, action)
    return page_url
