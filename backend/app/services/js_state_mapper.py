from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from glom import Coalesce, glom

from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    split_variant_axes,
)
from app.services.field_value_utils import extract_urls, text_or_none
from app.services.normalizers import normalize_decimal_price
from app.services.platform_policy import platform_js_state_extractors


NEXT_DATA_ECOMMERCE_SPEC = {
    "title": Coalesce(
        "props.pageProps.product.title",
        "props.pageProps.product.name",
        "props.pageProps.productData.title",
        "query.product.title",
        default=None,
    ),
    "brand": Coalesce(
        "props.pageProps.product.vendor",
        "props.pageProps.product.brand",
        default=None,
    ),
    "vendor": Coalesce("props.pageProps.product.vendor", default=None),
    "handle": Coalesce("props.pageProps.product.handle", default=None),
    "description": Coalesce(
        "props.pageProps.product.description",
        "props.pageProps.product.body_html",
        default=None,
    ),
}
GENERIC_PRODUCT_SPEC = {
    "title": Coalesce("title", "name", default=None),
    "brand": Coalesce("vendor", "brand.name", "brand", default=None),
    "vendor": Coalesce("vendor.name", "vendor", default=None),
    "handle": Coalesce("handle", "slug", default=None),
    "description": Coalesce("description", "body_html", default=None),
    "product_id": Coalesce("id", "product_id", default=None),
    "category": Coalesce("category", default=None),
    "product_type": Coalesce("product_type", "type", default=None),
    "sku": Coalesce("sku", default=None),
    "availability": Coalesce("availability", "inventory.status", default=None),
}
_DECLARATIVE_PRODUCT_ROOTS: dict[str, tuple[str, ...]] = {
    "__NEXT_DATA__": (
        "props.pageProps.product",
        "props.pageProps.productData",
        "props.pageProps.initialData.product",
        "props.pageProps.initialData",
        "query.product",
        "apollo.product",
    ),
    "__INITIAL_STATE__": (
        "catalog.selected.product",
        "product.current",
        "product",
        "pdp.product",
        "state.product",
    ),
    "__PRELOADED_STATE__": (
        "product.current",
        "product",
        "catalog.selected.product",
        "state.product",
    ),
    "__NUXT__": (
        "data[0].product",
        "data.product",
        "state.product",
        "product",
    ),
    "__NUXT_DATA__": (
        "data[0].product",
        "state.product",
        "product",
    ),
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
                root_paths=extractor.root_paths,
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
        mapped = _compact_dict(
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
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _map_ecommerce_detail_state(
    js_state_objects: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    next_data = js_state_objects.get("__NEXT_DATA__")
    if isinstance(next_data, dict):
        mapped = _compact_dict(glom(next_data, NEXT_DATA_ECOMMERCE_SPEC, default={}))
        product = _extract_product_payload("__NEXT_DATA__", next_data)
        if isinstance(product, dict):
            mapped = _merge_missing(
                mapped,
                _map_product_payload(
                    product,
                    page_url=page_url,
                    category_fallback_from_type=False,
                ),
            )
        if mapped:
            return mapped

    for key in ("__INITIAL_STATE__", "__PRELOADED_STATE__", "__NUXT__", "__NUXT_DATA__"):
        payload = _normalized_state_payload(key, js_state_objects.get(key))
        product = _extract_product_payload(key, payload)
        if not isinstance(product, dict):
            continue
        return _map_product_payload(
            product,
            page_url=page_url,
            category_fallback_from_type=(key == "__NUXT_DATA__"),
        )
    return {}


def _extract_product_payload(state_key: str, payload: Any) -> dict[str, Any] | None:
    normalized_payload = _normalized_state_payload(state_key, payload)
    root_paths = _DECLARATIVE_PRODUCT_ROOTS.get(state_key, ())
    for path in root_paths:
        candidate = glom(normalized_payload, path, default=None)
        if _looks_like_product_payload(candidate):
            return dict(candidate)
    return _find_product_payload(normalized_payload)


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
            "images",
            "image",
            "availability",
            "category",
            "type",
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
) -> dict[str, Any]:
    images = _extract_product_images(product, page_url=page_url)
    shopify_like = _looks_like_shopify_product(product)
    option_names = _option_names(product.get("options"))
    raw_variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variants = _dedupe_variants(
        [
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
    )
    selected_variant = _select_variant(variants, page_url=page_url)
    axes = _variant_axes(variants)
    selectable_axes, _ = split_variant_axes(
        axes,
        always_selectable_axes=frozenset({"size"}),
    )
    price = _variant_attribute(selected_variant, "price") or _normalize_price(
        _first_value(
            product,
            "price",
            "amount",
            "minPrice",
            "maxPrice",
            "formattedPrice",
        ),
        interpret_integral_as_cents=shopify_like,
    )
    original_price = _variant_attribute(
        selected_variant,
        "original_price",
    ) or _normalize_price(
        _first_value(
            product,
            "compare_at_price",
            "compareAtPrice",
            "original_price",
            "originalPrice",
            "listPrice",
        ),
        interpret_integral_as_cents=shopify_like,
    )
    currency = (
        _variant_attribute(selected_variant, "currency")
        or text_or_none(product.get("currency"))
        or text_or_none(product.get("currencyCode"))
        or text_or_none(product.get("priceCurrency"))
    )
    availability = (
        _availability_value(selected_variant)
        or _availability_value(product)
    )
    stock_quantity = _stock_quantity(selected_variant)
    if stock_quantity is None:
        stock_quantity = _stock_quantity(product)
    color = _variant_attribute(selected_variant, "color")
    size = _variant_attribute(selected_variant, "size")
    size_values = selectable_axes.get("size") if isinstance(selectable_axes, dict) else None
    ordered_axes = _ordered_axes(option_names, selectable_axes)

    record = _compact_dict(
        {
            "title": product.get("title") or product.get("name"),
            "brand": _name_or_value(product.get("brand") or product.get("vendor")),
            "vendor": _name_or_value(product.get("vendor")),
            "handle": product.get("handle"),
            "description": product.get("description") or product.get("body_html"),
            "product_id": product.get("id"),
            "category": (
                product.get("category")
                or (
                    product.get("product_type") or product.get("type")
                    if category_fallback_from_type
                    else None
                )
            ),
            "product_type": product.get("product_type") or product.get("type"),
            "price": price,
            "original_price": original_price,
            "currency": currency,
            "availability": availability,
            "stock_quantity": stock_quantity,
            "sku": _variant_attribute(selected_variant, "sku") or product.get("sku"),
            "barcode": _variant_attribute(selected_variant, "barcode") or product.get("barcode"),
            "color": color,
            "size": size,
            "image_url": (
                _variant_attribute(selected_variant, "image_url")
                or (images[0] if images else None)
            ),
            "additional_images": images[1:] if len(images) > 1 else None,
            "image_count": len(images) or None,
            "variants": variants or None,
            "selected_variant": selected_variant,
            "variant_axes": selectable_axes or None,
            "variant_count": len(variants) or None,
            "available_sizes": size_values[:20] if size_values else None,
            "tags": product.get("tags"),
            "created_at": product.get("created_at"),
            "updated_at": product.get("updated_at"),
            "published_at": product.get("published_at"),
        }
    )
    if ordered_axes:
        record["option1_name"] = ordered_axes[0][0]
        record["option1_values"] = ordered_axes[0][1]
    if len(ordered_axes) > 1:
        record["option2_name"] = ordered_axes[1][0]
        record["option2_values"] = ordered_axes[1][1]
    return record


def _extract_product_images(product: dict[str, Any], *, page_url: str) -> list[str]:
    values = extract_urls(product.get("images"), page_url)
    values.extend(extract_urls(product.get("image"), page_url))
    values.extend(extract_urls(product.get("featured_image"), page_url))
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(value)
    return deduped


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
    for field_name in ("sku", "barcode"):
        value = text_or_none(variant.get(field_name))
        if value:
            row[field_name] = value
    price = _normalize_price(
        _first_value(variant, "price", "amount", "formattedPrice"),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if price is not None:
        row["price"] = price
    original_price = _normalize_price(
        _first_value(
            variant,
            "compare_at_price",
            "compareAtPrice",
            "original_price",
            "originalPrice",
            "listPrice",
        ),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if original_price is not None:
        row["original_price"] = original_price
    currency = text_or_none(
        variant.get("currency")
        or variant.get("currencyCode")
        or variant.get("priceCurrency")
    )
    if currency:
        row["currency"] = currency
    availability = _availability_value(variant)
    if availability:
        row["availability"] = availability
    stock_quantity = _stock_quantity(variant)
    if stock_quantity is not None:
        row["stock_quantity"] = stock_quantity
    image_url = next(
        iter(
            extract_urls(
                variant.get("featured_image") or variant.get("image"),
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
    return option_values


def _variant_axes(variants: list[dict[str, Any]]) -> dict[str, list[str]]:
    axes: dict[str, list[str]] = {}
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, value in option_values.items():
            cleaned = text_or_none(value)
            if not cleaned:
                continue
            axes.setdefault(str(axis_name), [])
            if cleaned not in axes[str(axis_name)]:
                axes[str(axis_name)].append(cleaned)
    return axes


def _ordered_axes(
    option_names: list[str],
    selectable_axes: dict[str, list[str]],
) -> list[tuple[str, list[str]]]:
    ordered: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for option_name in option_names:
        axis_key = normalized_variant_axis_key(option_name)
        axis_values = selectable_axes.get(axis_key or "")
        if axis_key and axis_values:
            ordered.append((axis_key, axis_values))
            seen.add(axis_key)
    for axis_name, axis_values in selectable_axes.items():
        if axis_name in seen or not axis_values:
            continue
        ordered.append((axis_name, axis_values))
    return ordered


def _dedupe_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        fingerprint = _variant_fingerprint(variant)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(variant)
    return deduped


def _variant_fingerprint(variant: dict[str, Any]) -> str:
    variant_id = text_or_none(variant.get("variant_id"))
    if variant_id:
        return f"id:{variant_id}"
    sku = text_or_none(variant.get("sku"))
    if sku:
        return f"sku:{sku}"
    option_values = variant.get("option_values")
    if isinstance(option_values, dict) and option_values:
        return repr(sorted(option_values.items()))
    return repr(sorted(variant.items()))


def _select_variant(
    variants: list[dict[str, Any]],
    *,
    page_url: str,
) -> dict[str, Any] | None:
    if not variants:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    requested_variant_id = next(
        (
            str(value).strip()
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if key == "variant" and str(value).strip()
        ),
        "",
    )
    if requested_variant_id:
        matched = next(
            (
                variant
                for variant in variants
                if text_or_none(variant.get("variant_id")) == requested_variant_id
            ),
            None,
        )
        if matched is not None:
            return matched
    return next(
        (variant for variant in variants if variant.get("availability") == "in_stock"),
        variants[0],
    )


def _normalize_price(
    value: Any,
    *,
    interpret_integral_as_cents: bool,
) -> str | None:
    return normalize_decimal_price(
        value,
        interpret_integral_as_cents=interpret_integral_as_cents,
    )


def _availability_value(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("availability") or value.get("inventory_status") or value.get("stock_status")
    cleaned = text_or_none(raw)
    if cleaned:
        lowered = cleaned.lower()
        if lowered in {"instock", "in stock", "available", "true"}:
            return "in_stock"
        if lowered in {"outofstock", "out of stock", "sold out", "false"}:
            return "out_of_stock"
        if lowered in {"limited stock", "low stock"}:
            return "limited_stock"
        return cleaned
    available = value.get("available")
    if isinstance(available, bool):
        return "in_stock" if available else "out_of_stock"
    if available not in (None, "", [], {}):
        normalized_available = str(available).strip().lower()
        if normalized_available in {"1", "true", "yes", "available", "in-stock"}:
            return "in_stock"
        return None
    stock_quantity = _stock_quantity(value)
    if stock_quantity is None:
        return None
    return "in_stock" if stock_quantity > 0 else "out_of_stock"


def _stock_quantity(value: dict[str, Any] | None) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in ("inventory_quantity", "stock_quantity", "quantity"):
        raw = value.get(key)
        if raw in (None, "", [], {}):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _variant_url(page_url: str, variant_id: str) -> str:
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "variant"
    ]
    query_pairs.append(("variant", variant_id))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))


def _variant_attribute(
    variant: dict[str, Any] | None,
    field_name: str,
) -> Any:
    if not isinstance(variant, dict):
        return None
    return variant.get(field_name)


def _first_value(payload: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if payload.get(key) not in (None, "", [], {}):
            return payload.get(key)
    return None


def _merge_missing(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
    return _compact_dict(merged)


def _name_or_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("value")
    return value


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in dict(value or {}).items()
        if item not in (None, "", [], {})
    }
