from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import jmespath
from bs4 import BeautifulSoup
from glom import glom  # type: ignore[import-untyped]

from app.services.config.js_state_field_specs import (
    JS_STATE_PRODUCT_FIELD_SPEC,
    JS_STATE_VARIANT_FIELD_SPEC,
)
from app.services.config.extraction_rules import ECOMMERCE_DESCRIPTION_BLOCK_LIMIT
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_policy import normalize_field_key
from app.services.field_value_dom import dedupe_image_urls, extract_feature_rows
from app.services.extract.shared_variant_logic import (
    merge_variant_rows,
    normalized_variant_axis_key,
    resolve_variants,
    variant_axis_name_is_semantic,
)
from app.services.field_value_core import (
    clean_text,
    coerce_field_value,
    extract_urls,
    surface_alias_lookup,
    text_or_none,
)
from app.services.js_state_helpers import (
    availability_value,
    compact_dict,
    normalize_price,
    select_variant,
    stock_quantity,
    variant_attribute,
    variant_axes,
)
from app.services.platform_policy import JSStateExtractorConfig, platform_js_state_extractors

def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []

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
    merged: dict[str, Any] = {}
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
        for field_name, value in mapped.items():
            if merged.get(field_name) in (None, "", [], {}) and value not in (
                None,
                "",
                [],
                {},
            ):
                merged[field_name] = value
    return compact_dict(merged)

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


map_configured_state_payload = _map_configured_state_payload

def _map_ecommerce_detail_state(
    js_state_objects: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    base_record: dict[str, Any] = {}
    for state_key, payload in js_state_objects.items():
        normalized_payload = _normalized_state_payload(state_key, payload)
        product_payloads = _extract_product_payloads_from_normalized(
            state_key,
            normalized_payload,
        )
        for product, extractor in product_payloads:
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
                if not base_record:
                    base_record = mapped
                elif _mapped_product_identity_matches(base_record, mapped, page_url=page_url):
                    base_record = _merge_same_product_record(
                        base_record,
                        mapped,
                        page_url=page_url,
                    )
    return base_record

def _extract_product_payloads_from_normalized(
    state_key: str,
    normalized_payload: Any,
) -> list[tuple[dict[str, Any], JSStateExtractorConfig | None]]:
    products: list[tuple[dict[str, Any], JSStateExtractorConfig | None]] = []
    for extractor in platform_js_state_extractors(
        surface="ecommerce_detail",
        state_key=state_key,
    ):
        for root_path in extractor.root_paths.get(state_key, []):
            candidate = _path_value(normalized_payload, root_path)
            if _looks_like_product_payload(candidate):
                products.append((dict(candidate), extractor))
    products.extend((product, None) for product in _find_product_payloads(normalized_payload))
    if products:
        return _dedupe_product_payloads(products)
    return []


def _dedupe_product_payloads(
    products: list[tuple[dict[str, Any], JSStateExtractorConfig | None]],
) -> list[tuple[dict[str, Any], JSStateExtractorConfig | None]]:
    deduped: list[tuple[dict[str, Any], JSStateExtractorConfig | None]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for product, extractor in products:
        key = tuple(
            sorted(
                (field_name, str(product.get(field_name)))
                for field_name in ("id", "product_id", "productId", "sku", "handle", "title", "name")
                if product.get(field_name) not in (None, "", [], {})
            )
        ) + (("__keys__", ",".join(sorted(str(key) for key in product))),)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((product, extractor))
    return deduped[:8]


def _merge_same_product_record(
    base_record: dict[str, Any],
    incoming: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    merged = dict(base_record)
    for field_name, field_value in incoming.items():
        if field_name in {"variants", "variant_count"}:
            continue
        if (
            field_name in {"availability", "stock_quantity", "original_price"}
            and field_value not in (None, "", [], {})
        ):
            merged[field_name] = field_value
            continue
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value

    merged_variants = merge_variant_rows(
        base_record.get("variants"),
        incoming.get("variants"),
    )
    if merged_variants:
        merged["variants"] = merged_variants
        merged["variant_count"] = len(merged_variants)
    return compact_dict(merged)

def _mapped_product_identity_matches(
    base_record: dict[str, Any],
    mapped: dict[str, Any],
    *,
    page_url: str,
) -> bool:
    for field_name in ("product_id", "sku", "handle"):
        base_value = text_or_none(base_record.get(field_name))
        mapped_value = text_or_none(mapped.get(field_name))
        if base_value and mapped_value:
            return base_value == mapped_value
    base_url = text_or_none(base_record.get("url"))
    mapped_url = text_or_none(mapped.get("url"))
    if base_url and mapped_url and base_url == mapped_url:
        return True
    base_title = text_or_none(base_record.get("title"))
    mapped_title = text_or_none(mapped.get("title"))
    return bool(base_title and mapped_title and base_title == mapped_title)

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
            "options",
            "colors",
            "sizes",
            "prices",
            "representative",
            "product_type",
            "productType",
            "vendor",
            "brand",
            "handle",
            "price",
            "sku",
            "availability",
            "category",
            "type",
            "id",
            "product_id",
            "productId",
            "pid",
            "mrp",
            "Img",
            "offers",
            "images",
            "image",
        )
    ) and any(key in value for key in ("title", "name", "pn"))

def _find_product_payload(value: Any, *, depth: int = 0, limit: int = 8) -> dict[str, Any] | None:
    payloads = _find_product_payloads(value, depth=depth, limit=limit)
    return payloads[0] if payloads else None


def _find_product_payloads(
    value: Any,
    *,
    depth: int = 0,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    payloads: list[dict[str, Any]] = []
    if _looks_like_product_payload(value):
        payloads.append(dict(value))
    if isinstance(value, dict):
        for item in value.values():
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    elif isinstance(value, list):
        for item in value[:25]:
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    payloads.sort(key=_product_payload_score, reverse=True)
    return payloads[:8]

def _product_payload_score(product: dict[str, Any]) -> tuple[int, ...]:
    raw_variants = _as_list(product.get("variants"))
    raw_options = _as_list(product.get("options"))
    raw_colors = _as_list(product.get("colors"))
    raw_sizes = _as_list(product.get("sizes"))
    product_keys = set(product)
    strong_product_keys = {
        "variants",
        "options",
        "colors",
        "sizes",
        "prices",
        "representative",
        "product_type",
        "productType",
        "vendor",
        "brand",
        "handle",
        "price",
        "sku",
        "availability",
        "category",
        "type",
        "productId",
        "product_id",
        "id",
        "pid",
        "mrp",
        "Img",
        "offers",
        "images",
        "image",
    }
    variant_axis_keys = {
        "color",
        "size",
        "style",
        "material",
        "flavor",
        "scent",
        "capacity",
        "length",
        "width",
        "condition",
        "grade",
        "storage",
        "memory",
        "finish",
        "model",
    }
    axis_signal_count = sum(
        1
        for variant in raw_variants
        if isinstance(variant, dict)
        and any(key in variant for key in variant_axis_keys)
    )
    product_identifier_count = sum(
        1
        for key in ("productId", "product_id", "id", "sku", "handle")
        if product.get(key) not in (None, "", [], {})
    )
    price_signal_count = sum(
        1
        for key in ("price", "prices", "offers")
        if product.get(key) not in (None, "", [], {})
    )
    return (
        len(raw_variants),
        len(raw_options),
        len(raw_colors) + len(raw_sizes),
        axis_signal_count,
        product_identifier_count,
        price_signal_count,
        1 if product.get("images") not in (None, "", [], {}) or product.get("image") not in (None, "", [], {}) else 0,
        len(product_keys & strong_product_keys),
        len(product_keys),
    )

def _map_product_payload(
    product: dict[str, Any],
    *,
    page_url: str,
    category_fallback_from_type: bool,
    field_jmespaths: dict[str, str | list[str]] | None = None,
) -> dict[str, Any]:
    base = _product_base_fields(product, field_jmespaths=field_jmespaths)
    images = _extract_product_images(product, page_url=page_url)
    description_fields = _extract_ecommerce_description_fields(base.get("description"))
    shopify_like = _looks_like_shopify_product(product)
    option_names = _option_names(product.get("options"))
    option_value_labels = _option_value_labels(product)
    raw_variants = _as_list(product.get("variants"))
    normalized_variants = [
        normalized
        for variant in raw_variants
        if isinstance(variant, dict)
        if (
            normalized := _normalize_variant(
                variant,
                option_names=option_names,
                option_value_labels=option_value_labels,
                page_url=page_url,
                interpret_integral_as_cents=shopify_like,
            )
        )
    ]
    axes = variant_axes(normalized_variants)
    variants = resolve_variants(axes, normalized_variants) if axes else normalized_variants
    active_variant = select_variant(variants, page_url=page_url)
    price = variant_attribute(active_variant, "price")
    if price in (None, "", [], {}):
        raw_current_price = _raw_current_price_value(product)
        if raw_current_price is not None:
            price = raw_current_price
        else:
            price = normalize_price(
                base.get("price"),
                interpret_integral_as_cents=shopify_like,
            )
    if price in (None, "", [], {}):
        price = _discounted_percentage_price(product)
    original_price = variant_attribute(
        active_variant,
        "original_price",
    )
    if original_price in (None, "", [], {}):
        raw_original_price = _raw_original_price_value(product)
        original_price = raw_original_price if raw_original_price is not None else normalize_price(
            base.get("original_price"),
            interpret_integral_as_cents=shopify_like,
        )
    currency = (
        variant_attribute(active_variant, "currency")
        or text_or_none(base.get("currency"))
    )
    availability = (
        availability_value(active_variant)
        or availability_value(product)
    )
    product_stock = stock_quantity(active_variant)
    if product_stock is None:
        product_stock = stock_quantity(product)
    color = variant_attribute(active_variant, "color")
    size = variant_attribute(active_variant, "size")

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
            "description": description_fields.get("description"),
            "product_id": base.get("product_id"),
            "category": category,
            "product_type": base.get("product_type"),
            "price": price,
            "original_price": original_price,
            "currency": currency,
            "availability": availability,
            "stock_quantity": product_stock,
            "sku": variant_attribute(active_variant, "sku") or base.get("sku"),
            "barcode": variant_attribute(active_variant, "barcode") or base.get("barcode"),
            "color": color,
            "size": size,
            "image_url": (
                variant_attribute(active_variant, "image_url")
                or (images[0] if images else None)
            ),
            "additional_images": images[1:] if len(images) > 1 else None,
            "image_count": len(images) or None,
            "features": description_fields.get("features"),
            "variants": variants or None,
            "variant_count": len(variants) if variants else None,
            "tags": base.get("tags") if isinstance(base.get("tags"), list) else None,
            "created_at": base.get("created_at"),
            "updated_at": base.get("updated_at"),
            "published_at": base.get("published_at"),
        }
    )
    return record


def _extract_ecommerce_description_fields(value: object) -> dict[str, object]:
    description_html = str(value or "").strip()
    if not description_html:
        return {}
    if "<" not in description_html and "&" not in description_html:
        text = text_or_none(description_html)
        return {"description": text} if text else {}

    soup = BeautifulSoup(description_html, "html.parser")
    for node in soup.select("script, style, iframe, svg, img, picture, source, video"):
        node.decompose()

    features = extract_feature_rows(soup)
    blocks: list[tuple[str, str]] = []
    alias_lookup = surface_alias_lookup("ecommerce_detail", None)
    for node in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p"],
        limit=ECOMMERCE_DESCRIPTION_BLOCK_LIMIT,
    ):
        text = text_or_none(node.get_text(" ", strip=True))
        if text:
            blocks.append((str(node.name).lower(), text))

    lead_parts: list[str] = []
    seen: set[str] = set()
    for tag_name, text in blocks:
        normalized_text = normalize_field_key(text)
        canonical = alias_lookup.get(normalized_text)
        if lead_parts and canonical and canonical != "description":
            break
        lowered = text.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        lead_parts.append(text)

    lead_description = clean_text(" ".join(lead_parts))
    description = text_or_none(lead_description) or text_or_none(
        html_to_text(description_html)
    )
    result: dict[str, object] = {}
    if description:
        result["description"] = description
    if features:
        result["features"] = features
    return result


def _raw_current_price_value(product: dict[str, Any]) -> str | None:
    return _contextual_numeric_value(
        product,
        (
            ("prices", "currentPrice"),
            ("currentPrice",),
            ("pricing_information", "currentPrice"),
            ("pricing_information", "standard_price"),
        ),
    )

def _raw_original_price_value(product: dict[str, Any]) -> str | None:
    return _contextual_numeric_value(
        product,
        (
            ("prices", "initialPrice"),
            ("fullPrice",),
            ("pricing_information", "listPrice"),
            ("mrp",),
        ),
    )


def _discounted_percentage_price(product: dict[str, Any]) -> str | None:
    list_price = _raw_numeric_value(product, (("mrp",),))
    discount_percent = _raw_numeric_value(product, (("Dis",),))
    if list_price is None or discount_percent is None:
        return None
    try:
        discounted = float(list_price) * (100.0 - float(discount_percent)) / 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if discounted <= 0:
        return None
    return f"{discounted:.2f}".rstrip("0").rstrip(".") or None

def _contextual_numeric_value(
    product: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> str | None:
    currency = _raw_currency_value(product)
    if not currency:
        return None
    value = _raw_numeric_value(product, paths)
    if value is None:
        return None
    return f"{currency} {value}"

def _raw_numeric_value(
    product: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> int | float | None:
    for path in paths:
        current: Any = product
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            return current
    return None

def _raw_currency_value(product: dict[str, Any]) -> str | None:
    for path in (
        ("prices", "currency"),
        ("pricing_information", "currency"),
        ("currency",),
        ("currencyCode",),
        ("priceCurrency",),
    ):
        current: Any = product
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return None

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
        base = glom(product, JS_STATE_PRODUCT_FIELD_SPEC, default=None)
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
    values.extend(_extract_nested_image_urls(product.get("images"), page_url=page_url))
    values.extend(extract_urls(product.get("image"), page_url))
    values.extend(extract_urls(product.get("featuredImage"), page_url))
    values.extend(extract_urls(product.get("featured_image"), page_url))
    values.extend(extract_urls(_connection_nodes(product.get("media")), page_url))
    return dedupe_image_urls(values)

def _extract_nested_image_urls(value: Any, *, page_url: str, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    urls = extract_urls(value, page_url)
    if urls:
        return urls
    nested: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            nested.extend(
                _extract_nested_image_urls(item, page_url=page_url, depth=depth + 1)
            )
    elif isinstance(value, list):
        for item in value[:25]:
            nested.extend(
                _extract_nested_image_urls(item, page_url=page_url, depth=depth + 1)
            )
    return dedupe_image_urls(nested)

def _looks_like_shopify_product(product: dict[str, Any]) -> bool:
    raw_variants = _as_list(product.get("variants"))
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
    option_value_labels: dict[str, dict[str, str]] | None = None,
    page_url: str,
    interpret_integral_as_cents: bool,
) -> dict[str, Any] | None:
    row: dict[str, Any] = {}
    variant_id = text_or_none(
        variant.get("id") or variant.get("variantId") or variant.get("variant_id")
    )
    if variant_id:
        row["variant_id"] = variant_id
        row["url"] = _variant_url(page_url, variant_id)
    try:
        base = glom(variant, JS_STATE_VARIANT_FIELD_SPEC, default=None)
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
    selection_values = _variant_selection_values(
        variant,
        option_names=option_names,
    )
    if selection_values:
        row["_selection_values"] = selection_values
    option_values = _variant_option_values(
        variant,
        option_names=option_names,
        option_value_labels=option_value_labels,
    )
    if option_values:
        row["option_values"] = option_values
        if option_values.get("color"):
            row["color"] = option_values["color"]
        if option_values.get("size"):
            row["size"] = option_values["size"]
    for field_name in ("title", "name", "color", "size"):
        raw_value = variant.get(field_name)
        value = (
            _variant_axis_value(field_name, raw_value, page_url=page_url)
            if field_name in {"color", "size"}
            else text_or_none(raw_value)
        )
        if value and field_name not in row:
            row["title" if field_name == "name" else field_name] = value
    return row or None


def _variant_axis_value(
    axis_name: str,
    value: object,
    *,
    page_url: str,
) -> str | None:
    axis_key = normalized_variant_axis_key(axis_name) or str(axis_name or "")
    coerced = coerce_field_value(axis_key, value, page_url)
    return text_or_none(coerced)


def _variant_selection_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
) -> dict[str, str]:
    selection_values: dict[str, str] = {}
    selected_options = (
        variant.get("selectedOptions")
        if isinstance(variant.get("selectedOptions"), list)
        else variant.get("selected_options")
    )
    if isinstance(selected_options, list):
        for item in selected_options:
            if not isinstance(item, dict):
                continue
            axis_name = text_or_none(item.get("name") or item.get("label"))
            axis_key = normalized_variant_axis_key(axis_name)
            axis_value = _variant_axis_value(
                axis_key,
                item.get("value") or item.get("title") or item.get("label"),
                page_url="",
            )
            if axis_key and axis_value and variant_axis_name_is_semantic(axis_name):
                selection_values[axis_key] = axis_value
    if selection_values:
        return selection_values
    variation_values = variant.get("variationValues")
    if not isinstance(variation_values, dict):
        variation_values = variant.get("variation_values")
    if isinstance(variation_values, dict):
        for axis_name, raw_value in variation_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = _variant_axis_value(axis_key, raw_value, page_url="")
            if axis_key and cleaned and variant_axis_name_is_semantic(axis_name):
                selection_values[axis_key] = cleaned
    if selection_values:
        return selection_values
    raw_options = _as_list(variant.get("options"))
    for index in range(1, 4):
        axis_name = (
            option_names[index - 1]
            if index - 1 < len(option_names)
            else f"option_{index}"
        )
        axis_key = normalized_variant_axis_key(axis_name)
        if not axis_key or not variant_axis_name_is_semantic(axis_name):
            continue
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        cleaned = _variant_axis_value(axis_key, value, page_url="")
        if cleaned:
            selection_values[axis_key] = cleaned
    return selection_values

def _variant_option_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
    option_value_labels: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    option_values: dict[str, str] = {}
    selected_options = (
        variant.get("selectedOptions")
        if isinstance(variant.get("selectedOptions"), list)
        else variant.get("selected_options")
    )
    if isinstance(selected_options, list):
        for item in selected_options:
            if not isinstance(item, dict):
                continue
            axis_name = text_or_none(item.get("name") or item.get("label"))
            axis_value = _variant_axis_value(
                normalized_variant_axis_key(axis_name or ""),
                item.get("value") or item.get("title") or item.get("label"),
                page_url="",
            )
            if not axis_name or not axis_value or not variant_axis_name_is_semantic(axis_name):
                continue
            axis_key = normalized_variant_axis_key(axis_name)
            if axis_key:
                option_values[axis_key] = _display_option_value(
                    axis_key,
                    axis_value,
                    option_value_labels=option_value_labels,
                )
    if option_values:
        return option_values
    variation_values = variant.get("variationValues")
    if not isinstance(variation_values, dict):
        variation_values = variant.get("variation_values")
    if isinstance(variation_values, dict):
        direct_axis_keys = {
            normalized_variant_axis_key(axis_name)
            for axis_name in variation_values
            if normalized_variant_axis_key(axis_name)
            == str(axis_name or "").strip().lower().replace("-", "_")
        }
        for axis_name, raw_value in variation_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = _variant_axis_value(axis_key, raw_value, page_url="")
            if not axis_key or not cleaned or not variant_axis_name_is_semantic(axis_name):
                continue
            if axis_key in direct_axis_keys and axis_key != str(axis_name).strip().lower():
                continue
            if axis_key in option_values:
                continue
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    attributes = variant.get("attributes")
    if isinstance(attributes, dict):
        for axis_name, raw_value in attributes.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = _variant_axis_value(axis_key, raw_value, page_url="")
            if not axis_key or not cleaned or not variant_axis_name_is_semantic(axis_name):
                continue
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    raw_options = _as_list(variant.get("options"))
    for index in range(1, 4):
        axis_name = (
            option_names[index - 1]
            if index - 1 < len(option_names)
            else f"option_{index}"
        )
        axis_key = normalized_variant_axis_key(axis_name) or f"option_{index}"
        if not variant_axis_name_is_semantic(axis_name):
            continue
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        cleaned = _variant_axis_value(axis_key, value, page_url="")
        if cleaned:
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )

    # Fallback: non-Shopify sites use direct axis keys (Magento, SFCC, custom React, etc.)
    if not option_values:
        for possible_axis in (
            "color", "size", "style", "material", "flavor",
            "scent", "capacity", "length", "width",
            "condition", "grade", "storage", "memory",
            "finish", "model",
        ):
            val = variant.get(possible_axis)
            cleaned = _variant_axis_value(possible_axis, val, page_url="")
            if cleaned:
                option_values[possible_axis] = _display_option_value(
                    possible_axis,
                    cleaned,
                    option_value_labels=option_value_labels,
                )

    return option_values

def _option_value_labels(product: dict[str, Any]) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    raw_attributes = product.get("variationAttributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = product.get("variation_attributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = product.get("attributes")
    if not isinstance(raw_attributes, list):
        return labels
    # Direct axis keys prefer raw IDs already matching their normalized form,
    # so later label mapping skips normalized duplicates like color over colorID.
    direct_axis_keys = {
        normalized_variant_axis_key(
            text_or_none(attribute.get("id") or attribute.get("name") or attribute.get("label")) or ""
        )
        for attribute in raw_attributes
        if isinstance(attribute, dict)
        if normalized_variant_axis_key(
            text_or_none(attribute.get("id") or attribute.get("name") or attribute.get("label")) or ""
        )
        == str(text_or_none(attribute.get("id") or "") or "").strip().lower().replace("-", "_")
    }
    for attribute in raw_attributes:
        if not isinstance(attribute, dict):
            continue
        axis_name = text_or_none(
            attribute.get("id")
            or attribute.get("name")
            or attribute.get("label")
            or attribute.get("type")
        )
        axis_key = normalized_variant_axis_key(axis_name or "")
        if not axis_key:
            continue
        if axis_key in direct_axis_keys and axis_key != str(axis_name or "").strip().lower():
            continue
        values = attribute.get("values")
        if not isinstance(values, list):
            values = attribute.get("options")
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            raw_value = text_or_none(item.get("value") or item.get("id") or item.get("slug"))
            display = text_or_none(
                item.get("name")
                or item.get("displayValue")
                or item.get("display_value")
                or item.get("label")
            )
            if not raw_value or not display:
                continue
            labels.setdefault(axis_key, {})[raw_value] = display
            item_id = text_or_none(item.get("id") or item.get("slug"))
            if item_id:
                labels.setdefault(axis_key, {})[item_id] = display
    return labels

def _display_option_value(
    axis_key: str,
    value: str,
    *,
    option_value_labels: dict[str, dict[str, str]] | None,
) -> str:
    cleaned = text_or_none(value)
    if not cleaned:
        return ""
    return (option_value_labels or {}).get(axis_key, {}).get(cleaned, cleaned)

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
