from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import jmespath
from glom import Coalesce, glom

from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    resolve_variants,
    split_variant_axes,
)
from app.services.field_value_dom import dedupe_image_urls
from app.services.field_value_core import extract_urls, text_or_none
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
from app.services.platform_policy import JSStateExtractorConfig, platform_js_state_extractors


_SKIP = ("", [], {})

PRODUCT_FIELD_SPEC = {
    "title": Coalesce("title", "name", default=None, skip=_SKIP),
    "brand": Coalesce("brand.name", "brand", "vendor.name", "vendor", default=None, skip=_SKIP),
    "vendor": Coalesce("vendor.name", "vendor", default=None, skip=_SKIP),
    "handle": Coalesce("handle", "slug", default=None, skip=_SKIP),
    "description": Coalesce("description", "body_html", "descriptionHtml", default=None, skip=_SKIP),
    "product_id": Coalesce("id", "product_id", "legacyResourceId", default=None, skip=_SKIP),
    "category": Coalesce("category", default=None, skip=_SKIP),
    "product_type": Coalesce("product_type", "type", default=None, skip=_SKIP),
    "sku": Coalesce("sku", default=None, skip=_SKIP),
    "barcode": Coalesce("barcode", default=None, skip=_SKIP),
    "currency": Coalesce("currency", "currencyCode", "priceCurrency", "priceRange.minVariantPrice.currencyCode", "priceRange.maxVariantPrice.currencyCode", default=None, skip=_SKIP),
    "price": Coalesce("price", "amount", "minPrice", "maxPrice", "formattedPrice", "priceRange.minVariantPrice.amount", "priceRange.maxVariantPrice.amount", default=None, skip=_SKIP),
    "original_price": Coalesce("compare_at_price", "compareAtPrice", "original_price", "originalPrice", "listPrice", "compareAtPriceRange.minVariantPrice.amount", "compareAtPriceRange.maxVariantPrice.amount", default=None, skip=_SKIP),
    "availability": Coalesce("availability", "inventory.status", "availableForSale", default=None, skip=_SKIP),
    "tags": Coalesce("tags", default=None, skip=_SKIP),
    "created_at": Coalesce("created_at", default=None, skip=_SKIP),
    "updated_at": Coalesce("updated_at", default=None, skip=_SKIP),
    "published_at": Coalesce("published_at", default=None, skip=_SKIP),
}
def map_js_state_to_fields(
    js_state_objects: dict[str, Any],
    *,
    surface: str,
    page_url: str,
) -> dict[str, Any]:
    normalized_surface = str(surface or "").strip().lower()
    if not js_state_objects:
        return {}
    if normalized_surface == "job_detail":
        return _map_job_detail_state(js_state_objects)
    if normalized_surface == "ecommerce_detail":
        return _map_ecommerce_detail_state(js_state_objects, page_url=page_url)
    return {}


def _map_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    mapped = _map_platform_job_detail_state(js_state_objects)
    if not mapped:
        return {}
    description_html = str(mapped.pop("description_html", "") or "").strip()
    if description_html:
        mapped.update(extract_job_sections(description_html))
        if "description" not in mapped:
            mapped["description"] = html_to_text(description_html)
    if mapped.get("apply_url") and not mapped.get("url"):
        mapped["url"] = mapped["apply_url"]
    return mapped


def _map_platform_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    for state_key, payload in js_state_objects.items():
        if not isinstance(payload, dict):
            continue
        extractors = platform_js_state_extractors(
            surface="job_detail",
            state_key=state_key,
        )
        for extractor in extractors:
            mapped = _map_configured_state_payload(
                payload,
                root_paths=extractor.root_paths.get(state_key, []),
                field_paths=extractor.field_paths,
            )
            if mapped:
                return mapped
    return {}


def _map_configured_state_payload(
    payload: dict[str, Any],
    *,
    root_paths: list[list[str]],
    field_paths: dict[str, list[list[str]]],
) -> dict[str, Any]:
    for root_path in root_paths:
        candidate = _path_value(payload, root_path)
        if not isinstance(candidate, dict):
            continue
        mapped = compact_dict(
            {
                field_name: _first_path_value(candidate, paths)
                for field_name, paths in field_paths.items()
            }
        )
        if mapped:
            return mapped
    return {}


def _first_path_value(payload: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        value = _path_value(payload, path)
        if value not in (None, "", [], {}):
            return value
    return None


def _path_value(payload: Any, path: list[str]) -> Any:
    current = payload
    for segment in path:
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list):
            try:
                current = current[int(segment)]
            except (TypeError, ValueError, IndexError):
                return None
            continue
        return None
    return current


def _map_ecommerce_detail_state(
    js_state_objects: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    for state_key, payload in js_state_objects.items():
        normalized_payload = _normalized_state_payload(state_key, payload)
        product, extractor = _extract_product_payload_from_normalized(
            state_key,
            normalized_payload,
        )
        if not isinstance(product, dict):
            continue
        mapped = _map_product_payload(
            product,
            page_url=page_url,
            category_fallback_from_type=(state_key == "__NUXT_DATA__"),
            field_jmespaths=(
                extractor.field_jmespaths if extractor is not None else None
            ),
        )
        if mapped:
            return mapped
    return {}


def _extract_product_payload_from_normalized(
    state_key: str,
    normalized_payload: Any,
) -> tuple[dict[str, Any] | None, JSStateExtractorConfig | None]:
    for extractor in platform_js_state_extractors(
        surface="ecommerce_detail",
        state_key=state_key,
    ):
        for root_path in extractor.root_paths.get(state_key, []):
            candidate = _path_value(normalized_payload, root_path)
            if _looks_like_product_payload(candidate):
                return dict(candidate), extractor
    return _find_product_payload(normalized_payload), None


def _normalized_state_payload(state_key: str, payload: Any) -> Any:
    if state_key == "__NUXT_DATA__":
        revived = _revive_nuxt_data_array(payload)
        if revived is not None:
            return revived
    return payload


def _revive_nuxt_data_array(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return payload if isinstance(payload, dict) else None
    data_rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("state"), dict):
            state.update(item.get("state") or {})
        if isinstance(item.get("data"), dict):
            data_rows.append(item["data"])
        elif "product" in item and isinstance(item.get("product"), dict):
            data_rows.append({"product": item["product"]})
    revived: dict[str, Any] = {}
    if data_rows:
        revived["data"] = data_rows
    if state:
        revived["state"] = state
    return revived or None


def _looks_like_product_payload(value: Any) -> bool:
    return isinstance(value, dict) and any(
        key in value
        for key in (
            "variants",
            "product_type",
            "vendor",
            "handle",
            "price",
            "sku",
            "availability",
            "category",
            "type",
            "id",
            "product_id",
            "offers",
        )
    ) and any(key in value for key in ("title", "name"))


def _find_product_payload(value: Any, *, depth: int = 0, limit: int = 8) -> dict[str, Any] | None:
    if depth > limit:
        return None
    if _looks_like_product_payload(value):
        return dict(value)
    if isinstance(value, dict):
        for item in value.values():
            found = _find_product_payload(item, depth=depth + 1, limit=limit)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value[:25]:
            found = _find_product_payload(item, depth=depth + 1, limit=limit)
            if found is not None:
                return found
    return None


def _map_product_payload(
    product: dict[str, Any],
    *,
    page_url: str,
    category_fallback_from_type: bool,
    field_jmespaths: dict[str, str | list[str]] | None = None,
) -> dict[str, Any]:
    base = _product_base_fields(product, field_jmespaths=field_jmespaths)
    images = _extract_product_images(product, page_url=page_url)
    shopify_like = _looks_like_shopify_product(product)
    option_names = _option_names(product.get("options"))
    raw_variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    normalized_variants = [
        normalized
        for variant in raw_variants
        if isinstance(variant, dict)
        if (
            normalized := _normalize_variant(
                variant,
                option_names=option_names,
                page_url=page_url,
                interpret_integral_as_cents=shopify_like,
            )
        )
    ]
    axes = variant_axes(normalized_variants)
    variants = resolve_variants(axes, normalized_variants) if axes else normalized_variants
    selected_variant = select_variant(variants, page_url=page_url)
    selectable_axes, _ = split_variant_axes(
        axes,
        always_selectable_axes=frozenset({"size"}),
    )
    price = variant_attribute(selected_variant, "price") or normalize_price(
        base.get("price"),
        interpret_integral_as_cents=shopify_like,
    )
    original_price = variant_attribute(
        selected_variant,
        "original_price",
    ) or normalize_price(
        base.get("original_price"),
        interpret_integral_as_cents=shopify_like,
    )
    currency = (
        variant_attribute(selected_variant, "currency")
        or text_or_none(base.get("currency"))
    )
    availability = (
        availability_value(selected_variant)
        or availability_value(product)
    )
    product_stock = stock_quantity(selected_variant)
    if product_stock is None:
        product_stock = stock_quantity(product)
    color = variant_attribute(selected_variant, "color")
    size = variant_attribute(selected_variant, "size")
    size_values = selectable_axes.get("size") if isinstance(selectable_axes, dict) else None
    ordered = ordered_axes(option_names, selectable_axes)

    # Resolve brand/vendor: dict values need name extraction
    brand_raw = base.get("brand")
    vendor_raw = base.get("vendor")
    brand = _name_or_value(brand_raw) if isinstance(brand_raw, dict) else brand_raw
    vendor = _name_or_value(vendor_raw) if isinstance(vendor_raw, dict) else vendor_raw

    # Category fallback from product_type when flag is set
    category = base.get("category")
    if not category and category_fallback_from_type:
        category = base.get("product_type")

    record = compact_dict(
        {
            "title": base.get("title"),
            "brand": brand,
            "vendor": vendor,
            "handle": base.get("handle"),
            "description": base.get("description"),
            "product_id": base.get("product_id"),
            "category": category,
            "product_type": base.get("product_type"),
            "price": price,
            "original_price": original_price,
            "currency": currency,
            "availability": availability,
            "stock_quantity": product_stock,
            "sku": variant_attribute(selected_variant, "sku") or base.get("sku"),
            "barcode": variant_attribute(selected_variant, "barcode") or base.get("barcode"),
            "color": color,
            "size": size,
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
            "tags": base.get("tags") if isinstance(base.get("tags"), list) else None,
            "created_at": base.get("created_at"),
            "updated_at": base.get("updated_at"),
            "published_at": base.get("published_at"),
        }
    )
    if ordered:
        record["option1_name"] = ordered[0][0]
        record["option1_values"] = ordered[0][1]
    if len(ordered) > 1:
        record["option2_name"] = ordered[1][0]
        record["option2_values"] = ordered[1][1]
    return record


def _product_base_fields(
    product: dict[str, Any],
    *,
    field_jmespaths: dict[str, str | list[str]] | None,
) -> dict[str, Any]:
    base = _glom_product_base_fields(product)
    mapped = _map_jmespath_fields(product, field_jmespaths=field_jmespaths)
    if not mapped:
        return base
    merged = dict(mapped)
    for field_name, value in base.items():
        if field_name not in merged or merged[field_name] in (None, "", [], {}):
            merged[field_name] = value
    return compact_dict(merged)


def _glom_product_base_fields(product: dict[str, Any]) -> dict[str, Any]:
    try:
        base = glom(product, PRODUCT_FIELD_SPEC, default=None)
    except Exception:
        base = {}
    if not isinstance(base, dict):
        return {}
    return compact_dict(base)


def _map_jmespath_fields(
    product: dict[str, Any],
    *,
    field_jmespaths: dict[str, str | list[str]] | None,
) -> dict[str, Any]:
    if not isinstance(field_jmespaths, dict) or not field_jmespaths:
        return {}
    mapped: dict[str, Any] = {}
    for field_name, expressions in field_jmespaths.items():
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        value = _first_non_empty_jmespath(product, expressions)
        if value not in (None, "", [], {}):
            mapped[field_name] = value
    return compact_dict(mapped)


def _first_non_empty_jmespath(
    payload: dict[str, Any],
    expressions: str | list[str],
) -> Any:
    candidates = [expressions] if isinstance(expressions, str) else expressions
    if not isinstance(candidates, list):
        return None
    for expression in candidates:
        if not isinstance(expression, str) or not expression.strip():
            continue
        value = jmespath.search(expression, payload)
        if value not in (None, "", [], {}):
            return value
    return None


def _extract_product_images(product: dict[str, Any], *, page_url: str) -> list[str]:
    values = extract_urls(product.get("images"), page_url)
    values.extend(extract_urls(_connection_nodes(product.get("images")), page_url))
    values.extend(extract_urls(product.get("image"), page_url))
    values.extend(extract_urls(product.get("featuredImage"), page_url))
    values.extend(extract_urls(product.get("featured_image"), page_url))
    values.extend(extract_urls(_connection_nodes(product.get("media")), page_url))
    return dedupe_image_urls(values)


def _looks_like_shopify_product(product: dict[str, Any]) -> bool:
    raw_variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    return any(
        key in product
        for key in (
            "handle",
            "compare_at_price",
            "product_type",
            "body_html",
        )
    ) or any(
        isinstance(variant, dict)
        and any(
            field in variant
            for field in ("option1", "compare_at_price", "inventory_quantity")
        )
        for variant in raw_variants
    )


def _option_names(raw_options: object) -> list[str]:
    names: list[str] = []
    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, str):
                names.append(option)
            elif isinstance(option, dict):
                label = option.get("name") or option.get("title")
                if label:
                    names.append(str(label))
    return names


_VARIANT_FIELD_SPEC = {
    "price": Coalesce("price", "amount", "formattedPrice", default=None, skip=_SKIP),
    "original_price": Coalesce("compare_at_price", "compareAtPrice", "original_price", "originalPrice", "listPrice", default=None, skip=_SKIP),
    "currency": Coalesce("currency", "currencyCode", "priceCurrency", default=None, skip=_SKIP),
    "sku": Coalesce("sku", default=None, skip=_SKIP),
    "barcode": Coalesce("barcode", default=None, skip=_SKIP),
}


def _normalize_variant(
    variant: dict[str, Any],
    *,
    option_names: list[str],
    page_url: str,
    interpret_integral_as_cents: bool,
) -> dict[str, Any] | None:
    row: dict[str, Any] = {}
    variant_id = text_or_none(variant.get("id"))
    if variant_id:
        row["variant_id"] = variant_id
        row["url"] = _variant_url(page_url, variant_id)
    try:
        base = glom(variant, _VARIANT_FIELD_SPEC, default=None)
    except Exception:
        base = {}
    if not isinstance(base, dict):
        base = {}
    sku = text_or_none(base.get("sku"))
    if sku:
        row["sku"] = sku
    barcode = text_or_none(base.get("barcode"))
    if barcode:
        row["barcode"] = barcode
    price = normalize_price(
        base.get("price"),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if price is not None:
        row["price"] = price
    original_price = normalize_price(
        base.get("original_price"),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if original_price is not None:
        row["original_price"] = original_price
    currency = text_or_none(base.get("currency"))
    if currency:
        row["currency"] = currency
    availability = availability_value(variant)
    if availability:
        row["availability"] = availability
    variant_stock = stock_quantity(variant)
    if variant_stock is not None:
        row["stock_quantity"] = variant_stock
    image_url = next(
        iter(
            extract_urls(
                variant.get("featured_image") or variant.get("featuredImage") or variant.get("image"),
                page_url,
            )
        ),
        None,
    )
    if image_url:
        row["image_url"] = image_url
    option_values = _variant_option_values(variant, option_names=option_names)
    if option_values:
        row["option_values"] = option_values
        if option_values.get("color"):
            row["color"] = option_values["color"]
        if option_values.get("size"):
            row["size"] = option_values["size"]
    for field_name in ("title", "name", "color", "size"):
        value = text_or_none(variant.get(field_name))
        if value and field_name not in row:
            row["title" if field_name == "name" else field_name] = value
    return row or None


def _variant_option_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
) -> dict[str, str]:
    option_values: dict[str, str] = {}
    raw_options = variant.get("options") if isinstance(variant.get("options"), list) else []
    for index in range(1, 4):
        axis_name = (
            option_names[index - 1]
            if index - 1 < len(option_names)
            else f"option_{index}"
        )
        axis_key = normalized_variant_axis_key(axis_name) or f"option_{index}"
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        cleaned = text_or_none(value)
        if cleaned:
            option_values[axis_key] = cleaned

    # Fallback: non-Shopify sites use direct axis keys (Magento, SFCC, custom React, etc.)
    if not option_values:
        for possible_axis in (
            "color", "size", "style", "material", "flavor",
            "scent", "capacity", "length", "width",
        ):
            val = variant.get(possible_axis)
            if val and isinstance(val, (str, int, float)):
                option_values[possible_axis] = str(val).strip()

    return option_values


def _variant_url(page_url: str, variant_id: str) -> str:
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "variant"
    ]
    query_pairs.append(("variant", variant_id))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))


def _connection_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [node for node in nodes if isinstance(node, dict)]
        edges = value.get("edges")
        if isinstance(edges, list):
            return [
                node
                for edge in edges
                if isinstance(edge, dict)
                for node in [edge.get("node")]
                if isinstance(node, dict)
            ]
    return []


def _name_or_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("value")
    return value
