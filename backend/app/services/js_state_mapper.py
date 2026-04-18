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

REMIX_GREENHOUSE_SPEC = {
    "title": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.title",
        default=None,
    ),
    "company": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.company_name",
        default=None,
    ),
    "location": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.job_post_location",
        default=None,
    ),
    "apply_url": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.public_url",
        default=None,
    ),
    "posted_date": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.published_at",
        default=None,
    ),
    "description_html": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.content",
        default=None,
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
    remix_state = js_state_objects.get("__remixContext")
    if not isinstance(remix_state, dict):
        return {}
    loader_data = (
        remix_state.get("state", {}).get("loaderData", {})
        if isinstance(remix_state.get("state"), dict)
        else {}
    )
    route_data = (
        loader_data.get("routes/$url_token_.jobs_.$job_post_id", {})
        if isinstance(loader_data, dict)
        else {}
    )
    job_post = route_data.get("jobPost", {}) if isinstance(route_data, dict) else {}
    mapped = _compact_dict(
        {
            "title": job_post.get("title"),
            "company": job_post.get("company_name"),
            "location": job_post.get("job_post_location"),
            "apply_url": job_post.get("public_url"),
            "posted_date": job_post.get("published_at"),
            "description_html": job_post.get("content"),
        }
    )
    description_html = str(mapped.pop("description_html", "") or "").strip()
    if description_html:
        mapped.update(extract_job_sections(description_html))
        if "description" not in mapped:
            mapped["description"] = html_to_text(description_html)
    if mapped.get("apply_url") and not mapped.get("url"):
        mapped["url"] = mapped["apply_url"]
    return mapped


def _map_ecommerce_detail_state(
    js_state_objects: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    next_data = js_state_objects.get("__NEXT_DATA__")
    if isinstance(next_data, dict):
        mapped = _compact_dict(glom(next_data, NEXT_DATA_ECOMMERCE_SPEC, default={}))
        product = _find_product_payload(next_data)
        if isinstance(product, dict):
            mapped = _merge_missing(
                mapped,
                _map_product_payload(product, page_url=page_url),
            )
        if mapped:
            return mapped

    for key in ("__NUXT__", "__NUXT_DATA__", "__INITIAL_STATE__", "__PRELOADED_STATE__"):
        payload = js_state_objects.get(key)
        product = _find_product_payload(payload)
        if not isinstance(product, dict):
            continue
        return _map_product_payload(product, page_url=page_url)
    return {}


def _find_product_payload(value: Any, *, depth: int = 0, limit: int = 8) -> dict[str, Any] | None:
    if depth > limit:
        return None
    if isinstance(value, dict):
        if any(
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
            )
        ) and any(key in value for key in ("title", "name")):
            return value
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


def _map_product_payload(product: dict[str, Any], *, page_url: str) -> dict[str, Any]:
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
            "category": product.get("category") or product.get("product_type") or product.get("type"),
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
