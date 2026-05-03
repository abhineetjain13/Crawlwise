from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_CATEGORY_LABEL_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
    DETAIL_LOW_SIGNAL_PARENT_MIN,
    DETAIL_LOW_SIGNAL_PRICE_MAX,
    DETAIL_PRICE_COMPARISON_TOLERANCE,
    PLACEHOLDER_IMAGE_URL_PATTERNS,
    VARIANT_OPTION_LABEL_MAX_WORDS,
    VARIANT_OPTION_VALUE_NOISE_TOKENS,
)
from app.services.field_value_core import (
    clean_text,
    flatten_variants_for_public_output,
    same_site,
    text_or_none,
)
from app.services.field_value_dom import dedupe_image_urls
from app.services.extract.detail_dom_extractor import (
    variant_option_value_is_noise as _variant_option_value_is_noise,
)
from app.services.extract.detail_identity import (
    detail_identity_codes_match,
    detail_identity_codes_from_record_fields as _detail_identity_codes_from_record_fields,
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_title_from_url as _detail_title_from_url,
    detail_url_looks_like_product as _detail_url_looks_like_product,
    detail_url_matches_requested_identity as _detail_url_matches_requested_identity,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
    semantic_detail_identity_tokens as _semantic_detail_identity_tokens,
)
from app.services.extract.detail_price_extractor import (
    backfill_detail_price_from_html,
    detail_price_decimal,
    format_detail_price_decimal,
    reconcile_detail_price_magnitudes,
)
from app.services.extract.detail_text_sanitizer import (
    detail_product_type_is_low_signal,
    detail_scalar_size_is_low_signal,
    detail_title_value_is_low_signal,
    sanitize_detail_long_text_fields,
)
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    variant_axis_name_is_semantic,
)

_UUID_LIKE_PATTERN = re.compile(r"(?i)^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_MERCH_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+\b", re.I)
_VARIANT_OPTION_VALUE_NOISE_TOKENS = frozenset(
    str(token).strip().lower()
    for token in VARIANT_OPTION_VALUE_NOISE_TOKENS
    if str(token).strip()
)
_DETAIL_PLACEHOLDER_TITLE_PATTERNS = (
    re.compile(r"^404$"),
    re.compile(r"^(?:error\s*)?404\b", re.I),
    re.compile(r"^error\s+page$", re.I),
    re.compile(r"^your\s+ai-generated\s+outfit$", re.I),
    re.compile(r"^oops,?\s+something\s+went\s+wrong\.?$", re.I),
    re.compile(
        r"^oops!? the page you(?:'|’)re looking for can(?:'|’)t be found\.?$", re.I
    ),
    re.compile(r"\bpage not found\b", re.I),
    re.compile(r"\bnot found\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
)


def _dedupe_primary_and_additional_images(record: dict[str, Any]) -> None:
    raw_additional_images = record.get("additional_images")
    additional_images = (
        list(raw_additional_images)
        if isinstance(raw_additional_images, (list, tuple, set))
        else (
            [raw_additional_images]
            if raw_additional_images not in (None, "", [], {})
            else []
        )
    )
    values: list[str] = []
    for raw_value in (
        record.get("image_url"),
        *additional_images,
    ):
        image = text_or_none(raw_value)
        if image:
            values.append(image)
    merged = dedupe_image_urls(values)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
        return
    record.pop("additional_images", None)

def _sanitize_ecommerce_detail_record(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None,
) -> None:
    identity_url = text_or_none(requested_page_url) or page_url
    _sanitize_detail_placeholder_scalars(record)
    _sanitize_detail_identity_scalars(record, identity_url=identity_url)
    _sanitize_detail_variant_payload(record, identity_url=identity_url)
    sanitize_detail_long_text_fields(
        record,
        title_hint=_detail_title_from_url(identity_url),
    )
    _sanitize_detail_images(record, identity_url=identity_url)
    _reconcile_detail_availability_from_variants(record)


def _sanitize_detail_placeholder_scalars(record: dict[str, Any]) -> None:
    title = clean_text(record.get("title"))
    if _detail_title_looks_like_placeholder(title) or detail_title_value_is_low_signal(
        title
    ):
        record.pop("title", None)
        record["_placeholder_title_removed"] = True
    category = clean_text(record.get("category"))
    if category.lower() in {"category", "categories", "uncategorized"}:
        record.pop("category", None)
    elif category:
        cleaned_category = _clean_detail_category_path(
            category,
            title=record.get("title"),
            sku=record.get("sku"),
        )
        if cleaned_category:
            record["category"] = cleaned_category
        else:
            record.pop("category", None)
    features = record.get("features")
    if isinstance(features, list):
        if not any(text_or_none(item) for item in features):
            record.pop("features", None)
    else:
        feature_text = text_or_none(features)
        if feature_text and feature_text.startswith("{") and feature_text.endswith("}"):
            record.pop("features", None)
    product_type = text_or_none(record.get("product_type"))
    if detail_product_type_is_low_signal(product_type):
        record.pop("product_type", None)
    materials = text_or_none(record.get("materials"))
    if materials and _materials_value_looks_like_org_name(materials):
        record.pop("materials", None)
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict):
        cleaned_attributes = {
            str(key): value
            for key, value in product_attributes.items()
            if not _detail_scalar_value_is_placeholder(value)
        }
        if cleaned_attributes:
            record["product_attributes"] = cleaned_attributes
        else:
            record.pop("product_attributes", None)


def _sanitize_detail_identity_scalars(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    sku = text_or_none(record.get("sku"))
    preferred_code = _preferred_detail_merch_code(record, identity_url=identity_url)
    if preferred_code and (not sku or _looks_like_uuid(sku)):
        record["sku"] = preferred_code
        if text_or_none(record.get("part_number")) in (None, ""):
            record["part_number"] = preferred_code
    placeholder_title_removed = bool(record.pop("_placeholder_title_removed", False))
    if not text_or_none(record.get("title")):
        if placeholder_title_removed and not _detail_title_fallback_is_safe(record):
            return
        fallback_title = _detail_title_from_url(identity_url)
        if fallback_title:
            record["title"] = fallback_title.title()
            field_sources = record.setdefault("_field_sources", {})
            field_sources["title"] = ["url_slug"]


def _detail_title_fallback_is_safe(record: dict[str, Any]) -> bool:
    return any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "sku",
            "part_number",
            "barcode",
            "brand",
            "image_url",
            "availability",
            "product_attributes",
            "variants",
        )
    )


def _preferred_detail_merch_code(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> str | None:
    expected_codes = _detail_identity_codes_from_url(identity_url)
    raw_values = (
        record.get("sku"),
        record.get("part_number"),
        record.get("product_details"),
        record.get("description"),
        record.get("url"),
        identity_url,
    )
    fallback: str | None = None
    for raw_value in raw_values:
        text = text_or_none(raw_value)
        if not text:
            continue
        for match in _MERCH_CODE_PATTERN.findall(text):
            candidate = match.upper()
            if candidate.count("-") > 2:
                continue
            normalized = re.sub(r"[^A-Z0-9]+", "", candidate)
            if (
                len(normalized) < 8
                or not re.search(r"[A-Z]", normalized)
                or not re.search(r"\d", normalized)
            ):
                continue
            if fallback is None:
                fallback = candidate
            if not expected_codes or normalized in expected_codes:
                return candidate
    return fallback


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_LIKE_PATTERN.fullmatch(str(value or "").strip()))


def _detail_scalar_value_is_placeholder(value: object) -> bool:
    cleaned = clean_text(value).lower()
    if not cleaned:
        return True
    if cleaned in {str(item).strip().lower() for item in CANDIDATE_PLACEHOLDER_VALUES}:
        return True
    return cleaned in {"category", "default title", "uncategorized"}


def _clean_detail_category_path(
    value: object,
    *,
    title: object,
    sku: object,
) -> str:
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:>|/|›|»|→|\|)\s*", clean_text(value))
        if clean_text(part)
    ]
    if not parts:
        return ""
    ui_tokens = {
        clean_text(token).casefold()
        for token in tuple(DETAIL_CATEGORY_UI_TOKENS or ())
        if clean_text(token)
    }
    prefixes = tuple(
        str(prefix).casefold() for prefix in tuple(DETAIL_CATEGORY_LABEL_PREFIXES or ())
    )
    cleaned_parts: list[str] = []
    strip_chars = "".join(tuple(DETAIL_BREADCRUMB_SEPARATOR_LABELS or ())) + " \t\n\r"
    for part in parts:
        cleaned = clean_text(part.strip(strip_chars))
        lowered = cleaned.casefold()
        if (
            not cleaned
            or lowered in ui_tokens
            or any(lowered.startswith(prefix) for prefix in prefixes)
        ):
            continue
        cleaned_parts.append(cleaned)
    identity_values = [clean_text(title), clean_text(sku)]
    while cleaned_parts and any(
        _category_part_matches_identity(cleaned_parts[-1], identity)
        for identity in identity_values
        if identity
    ):
        cleaned_parts.pop()
    return " > ".join(cleaned_parts)


def _category_part_matches_identity(part: object, identity: str) -> bool:
    part_key = re.sub(r"[^a-z0-9]+", "", clean_text(part).casefold())
    identity_key = re.sub(r"[^a-z0-9]+", "", clean_text(identity).casefold())
    if not part_key or not identity_key:
        return False
    if part_key == identity_key:
        return True
    if min(len(part_key), len(identity_key)) < 8:
        return False
    from difflib import SequenceMatcher

    return SequenceMatcher(None, part_key, identity_key).ratio() >= float(
        DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO
    )


def _detail_title_looks_like_placeholder(title: str) -> bool:
    normalized = clean_text(title)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {"404", "not found"}:
        return True
    return any(
        pattern.search(normalized) for pattern in _DETAIL_PLACEHOLDER_TITLE_PATTERNS
    )


def _materials_value_looks_like_org_name(value: str) -> bool:
    lowered = value.lower()
    if any(
        token in lowered
        for token in (
            "cotton",
            "polyester",
            "rubber",
            "leather",
            "wool",
            "nylon",
            "polyamide",
            "spandex",
            "linen",
        )
    ):
        return False
    return bool(
        re.search(r"\b(?:inc|llc|ltd|corp|company|co|se)\b", lowered)
        or re.fullmatch(r"[A-Z0-9 .,&'-]{6,}", value, re.IGNORECASE)
    )


def _sanitize_detail_variant_payload(
    record: dict[str, Any], *, identity_url: str
) -> None:
    cleaned_variants: list[dict[str, Any]] = []
    title_hint = clean_text(record.get("title"))
    for variant in list(record.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        if not _sanitize_variant_row(
            variant, identity_url=identity_url, title_hint=title_hint
        ):
            continue
        cleaned_variants.append(variant)
    if _detail_variant_cluster_is_low_signal_numeric_only(cleaned_variants):
        cleaned_variants = []
    if cleaned_variants:
        flat_variants = flatten_variants_for_public_output(
            cleaned_variants, page_url=identity_url
        )
        if flat_variants:
            record["variants"] = flat_variants
            record["variant_count"] = len(flat_variants)
        else:
            record.pop("variants", None)
            record.pop("variant_count", None)
    else:
        record.pop("variants", None)
        record.pop("variant_count", None)
    record.pop("selected_variant", None)
    record.pop("variant_axes", None)
    record.pop("available_sizes", None)
    for field_name in list(record):
        if re.fullmatch(r"option\d+_(?:name|values?)", str(field_name)):
            record.pop(field_name, None)
    _drop_detail_variant_scalar_noise(record)
    _drop_variant_derived_parent_axis_scalars(record)


def _sanitize_variant_row(
    variant: dict[str, Any],
    *,
    identity_url: str,
    title_hint: str = "",
) -> bool:
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        cleaned_options: dict[str, str] = {}
        for axis_name, axis_value in option_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned_value = clean_text(axis_value)
            if not axis_key or not cleaned_value:
                continue
            if axis_key.startswith("toggle") or _variant_option_value_is_noise(
                cleaned_value
            ):
                continue
            if not variant_axis_name_is_semantic(axis_name):
                continue
            cleaned_options[axis_key] = cleaned_value
            # Sync existing size/color scalars with cleaned option_values; do not populate missing axes.
            if axis_key in {"size", "color"} and variant.get(axis_key) not in (
                None,
                "",
                [],
                {},
            ):
                variant[axis_key] = cleaned_value
        if cleaned_options:
            variant["option_values"] = cleaned_options
        else:
            variant.pop("option_values", None)
    for field_name in ("size", "color"):
        raw_value = variant.get(field_name)
        cleaned_value = clean_text(raw_value)
        if not cleaned_value:
            # Preserve values from higher-priority sources even if clean_text
            # returns empty (e.g. structured dict that coerce_field_value handles).
            # Only drop if the raw value itself is empty/null.
            if raw_value in (None, "", [], {}):
                variant.pop(field_name, None)
            continue
        if _variant_option_value_is_noise(cleaned_value):
            variant.pop(field_name, None)
            continue
        if _option_value_repeats_product_title(
            cleaned_value, title_hint=title_hint
        ):
            variant.pop(field_name, None)
            continue
        variant[field_name] = cleaned_value
    variant_url = text_or_none(variant.get("url"))
    if (
        variant_url
        and same_site(identity_url, variant_url)
        and _detail_url_looks_like_product(variant_url)
        and not _detail_url_matches_requested_identity(
            variant_url,
            requested_page_url=identity_url,
        )
    ):
        return False
    title = clean_text(variant.get("title"))
    if (
        title
        and not _variant_url_matches_requested_base(
            variant.get("url"), identity_url=identity_url
        )
        and _variant_title_looks_like_other_product(title, identity_url=identity_url)
        and not _variant_title_can_be_option_label(variant, title=title)
    ):
        return False
    return any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "sku",
            "variant_id",
            "barcode",
            "image_url",
            "availability",
            "option_values",
            "size",
            "color",
        )
    )


def repair_ecommerce_detail_record_quality(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    requested_page_url: str | None = None,
) -> None:
    identity_url = text_or_none(requested_page_url) or page_url
    _sanitize_ecommerce_detail_record(
        record,
        page_url=page_url,
        requested_page_url=identity_url,
    )
    backfill_detail_price_from_html(record, html=html)
    reconcile_detail_price_magnitudes(record)
    _normalize_detail_money_precision(record)
    _repair_invalid_original_prices(record)
    _drop_invalid_detail_discounts(record)
    _repair_detail_variant_prices_and_identity(record)


def _repair_detail_variant_prices_and_identity(record: dict[str, Any]) -> None:
    parent_price = text_or_none(record.get("price"))
    parent_availability = text_or_none(record.get("availability"))
    parent_sku = text_or_none(record.get("sku"))
    parent_title = clean_text(record.get("title"))
    rows = [row for row in list(record.get("variants") or []) if isinstance(row, dict)]
    for row in rows:
        if parent_price:
            row_price = text_or_none(row.get("price"))
            if (
                not row_price
                or _price_is_cents_copy(row_price, parent_price)
                or _price_is_low_signal_copy(row_price, parent_price)
            ):
                row["price"] = parent_price
        if (
            parent_availability
            and row.get("availability") in (None, "", [], {})
            and any(
                row.get(field_name) not in (None, "", [], {})
                for field_name in (
                    "sku",
                    "variant_id",
                    "barcode",
                    "image_url",
                    "title",
                    "size",
                    "color",
                    "url",
                )
            )
        ):
            row["availability"] = parent_availability
        row_sku = text_or_none(row.get("sku"))
        if row_sku and _looks_like_uuid(row_sku):
            row.pop("sku", None)
        barcode = text_or_none(row.get("barcode"))
        if (
            barcode
            and row.get("sku") == barcode
            and len(re.sub(r"\D+", "", barcode)) <= 8
        ):
            row.pop("barcode", None)
        title = clean_text(row.get("title"))
        if title and _variant_title_is_low_signal(title):
            replacement = _variant_title_from_parent(parent_title, row)
            if replacement:
                row["title"] = replacement
            else:
                row.pop("title", None)
    variant_rows = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if (
        parent_availability == "in_stock"
        and variant_rows
        and all(
            text_or_none(row.get("availability")) == parent_availability
            for row in variant_rows
        )
    ):
        for row in variant_rows:
            row.pop("availability", None)
    if parent_sku and _looks_like_uuid(parent_sku):
        record.pop("sku", None)


def _price_is_cents_copy(value: str, parent_price: str) -> bool:
    value_number = detail_price_decimal(value)
    parent_number = detail_price_decimal(parent_price)
    if value_number is None or parent_number is None or parent_number <= 0:
        return False
    return abs(value_number - (parent_number * 100)) < Decimal(
        str(DETAIL_PRICE_COMPARISON_TOLERANCE)
    )


def _price_is_low_signal_copy(value: str, parent_price: str) -> bool:
    value_number = detail_price_decimal(value)
    parent_number = detail_price_decimal(parent_price)
    if value_number is None or parent_number is None:
        return False
    return Decimal("0") < value_number <= Decimal(
        str(DETAIL_LOW_SIGNAL_PRICE_MAX)
    ) and parent_number >= Decimal(str(DETAIL_LOW_SIGNAL_PARENT_MIN))


def _normalize_detail_money_precision(record: dict[str, Any]) -> None:
    for container in _detail_money_containers(record):
        if not isinstance(container, dict):
            continue
        if not text_or_none(container.get("currency")):
            continue
        for field_name in ("price", "original_price"):
            normalized = _money_two_decimals(container.get(field_name))
            if normalized is not None:
                container[field_name] = normalized


def _detail_money_containers(record: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [record]
    variants = record.get("variants")
    if isinstance(variants, list):
        containers.extend(row for row in variants if isinstance(row, dict))
    return containers


def _money_two_decimals(value: object) -> str | None:
    text = text_or_none(value)
    if not text or not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return format_detail_price_decimal(text)


def _drop_invalid_detail_discounts(record: dict[str, Any]) -> None:
    price = detail_price_decimal(record.get("price"))
    original_price = detail_price_decimal(record.get("original_price"))
    discount_amount = detail_price_decimal(record.get("discount_amount"))
    discount_percentage = detail_price_decimal(record.get("discount_percentage"))
    if discount_percentage is not None and not (0 < discount_percentage <= 100):
        record.pop("discount_percentage", None)
    if discount_amount is None:
        return
    if discount_amount <= 0:
        record.pop("discount_amount", None)
        return
    if price is not None and discount_amount > max(price, 0):
        record.pop("discount_amount", None)
        return
    if original_price is not None and discount_amount > max(original_price, 0):
        record.pop("discount_amount", None)


def _repair_invalid_original_prices(record: dict[str, Any]) -> None:
    for container in _detail_money_containers(record):
        if not isinstance(container, dict):
            continue
        price = detail_price_decimal(container.get("price"))
        original_price = detail_price_decimal(container.get("original_price"))
        if price is None or original_price is None or original_price >= price:
            continue
        normalized_price = _money_two_decimals(container.get("price"))
        if normalized_price is not None:
            container["original_price"] = normalized_price


def _variant_title_is_low_signal(title: str) -> bool:
    normalized = clean_text(title)
    return bool(normalized) and (
        normalized.isdigit()
        or normalized.lower() in _VARIANT_OPTION_VALUE_NOISE_TOKENS
        or len(normalized) <= 2
    )


def _variant_title_from_parent(parent_title: str, row: dict[str, Any]) -> str | None:
    if not parent_title:
        return None
    option_values = row.get("option_values")
    values: list[str] = []
    if isinstance(option_values, dict):
        values.extend(
            clean_text(value) for value in option_values.values() if clean_text(value)
        )
    for field_name in ("size", "color"):
        value = clean_text(row.get(field_name))
        if value and value not in values:
            values.append(value)
    if values:
        return f"{parent_title} - {' / '.join(values)}"
    return parent_title


def _variant_url_matches_requested_base(value: object, *, identity_url: str) -> bool:
    variant_url = text_or_none(value)
    if not variant_url or not identity_url or not same_site(identity_url, variant_url):
        return False
    requested = urlparse(identity_url)
    candidate = urlparse(variant_url)
    return requested.path.rstrip("/") == candidate.path.rstrip("/")


def _detail_variant_row_is_low_signal_numeric_only(variant: object) -> bool:
    if not isinstance(variant, dict):
        return False
    if any(
        clean_text(variant.get(field_name))
        for field_name in ("variant_id", "barcode", "image_url", "title")
    ):
        return False
    if clean_text(variant.get("url")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or set(option_values) != {"size"}:
        return False
    size_value = clean_text(option_values.get("size") or variant.get("size"))
    return bool(size_value) and size_value.isdigit() and int(size_value) <= 4


def _detail_variant_cluster_is_low_signal_numeric_only(
    variants: list[dict[str, Any]],
) -> bool:
    return bool(variants) and all(
        _detail_variant_row_is_low_signal_numeric_only(variant) for variant in variants
    )


def _variant_title_looks_like_other_product(title: str, *, identity_url: str) -> bool:
    candidate: dict[str, object] = {"title": title}
    return not _record_matches_requested_detail_identity(
        candidate,
        requested_page_url=identity_url,
    )


def _variant_title_can_be_option_label(variant: dict[str, Any], *, title: str) -> bool:
    title_words = clean_text(title).split()
    if len(title_words) > int(VARIANT_OPTION_LABEL_MAX_WORDS):
        return False
    has_option_axis = any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "option_values",
            "size",
            "color",
        )
    )
    if has_option_axis:
        return True
    return len(title_words) == 1 and any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in ("sku", "variant_id", "barcode")
    )


def _drop_detail_variant_scalar_noise(record: dict[str, Any]) -> None:
    for field_name in list(record.keys()):
        if str(field_name).startswith("toggle_"):
            record.pop(field_name, None)
    for field_name in ("size", "color"):
        cleaned_value = clean_text(record.get(field_name))
        if field_name == "size" and detail_scalar_size_is_low_signal(
            cleaned_value,
            title=record.get("title"),
        ):
            record.pop(field_name, None)
            continue
        if (
            cleaned_value
            and not _variant_option_value_is_noise(cleaned_value)
            and not _option_value_repeats_product_title(
                cleaned_value,
                title_hint=clean_text(record.get("title")),
            )
        ):
            record[field_name] = cleaned_value
            continue
        record.pop(field_name, None)


def _option_value_repeats_product_title(value: str, *, title_hint: str) -> bool:
    if not value or not title_hint:
        return False
    value_key = re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())
    title_key = re.sub(r"[^a-z0-9]+", "", clean_text(title_hint).casefold())
    if not value_key or not title_key or len(title_key) < 8:
        return False
    return title_key in value_key


def _drop_variant_derived_parent_axis_scalars(record: dict[str, Any]) -> None:
    variants = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if not variants:
        return
    field_sources = record.get("_field_sources")
    sources = field_sources if isinstance(field_sources, dict) else {}
    for field_name in ("size", "color"):
        if sources.get(field_name):
            continue
        parent_value = clean_text(record.get(field_name))
        if not parent_value:
            continue
        variant_values = {
            clean_text(row.get(field_name)).casefold()
            for row in variants
            if clean_text(row.get(field_name))
        }
        if variant_values == {parent_value.casefold()}:
            record.pop(field_name, None)


def _sanitize_detail_images(record: dict[str, Any], *, identity_url: str) -> None:
    raw_images = [
        text_or_none(record.get("image_url")),
        *[text_or_none(value) for value in list(record.get("additional_images") or [])],
    ]
    images = [image for image in raw_images if image]
    if not images:
        return
    primary_image = (
        "https://" + images[0][7:]
        if images[0].lower().startswith("http://")
        else images[0]
    )
    cleaned: list[str] = []
    for image in images:
        normalized_image = (
            "https://" + image[7:] if image.lower().startswith("http://") else image
        )
        if not _detail_image_candidate_is_usable(
            normalized_image, identity_url=identity_url
        ):
            continue
        if not _detail_image_matches_primary_family(
            normalized_image,
            primary_image=primary_image,
            title=record.get("title"),
        ):
            continue
        cleaned.append(normalized_image)
    merged = dedupe_image_urls(cleaned)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
    else:
        record.pop("additional_images", None)


def _detail_image_candidate_is_usable(url: str, *, identity_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = str(parsed.path or "").strip()
    if not path or path == "/":
        return False
    lowered = url.lower()
    if "base64," in lowered or lowered.startswith("data:"):
        return False
    if any(pattern in lowered for pattern in tuple(PLACEHOLDER_IMAGE_URL_PATTERNS or ())):
        return False
    if _detail_image_url_is_extensionless_transform(path):
        return False
    if (
        same_site(identity_url, url)
        and _detail_url_looks_like_product(url)
        and not _detail_path_looks_like_image_asset(path, lowered)
    ):
        return False
    if re.search(r"/products?/[\d?=&-]*$", lowered):
        return False
    candidate_title = _detail_image_title_from_url(url)
    if (
        candidate_title
        and _detail_image_title_has_identity_signal(candidate_title)
        and not (
            (candidate_codes := _detail_identity_codes_from_url(url))
            and detail_identity_codes_match(
                _detail_identity_codes_from_url(identity_url), candidate_codes
            )
        )
        and not _detail_image_title_matches_requested_identity(
            candidate_title,
            requested_page_url=identity_url,
        )
    ):
        return False
    return True

def _detail_image_url_is_extensionless_transform(path: str) -> bool:
    filename = unquote(str(path or "").rsplit("/", 1)[-1])
    if re.search(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)$", filename, re.I):
        return False
    return re.search(r"\._[A-Z]+_[A-Z]{2}\d+\s*$", filename, re.I) is not None

def _detail_path_looks_like_image_asset(path: str, lowered_url: str) -> bool:
    lowered_path = str(path or "").lower()
    if re.search(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)(?:$|\?)", lowered_url):
        return True
    return any(
        token in lowered_path
        for token in (
            "/image/",
            "/images/",
            "/media/",
            "/picture",
            "/is/image/",
            "/cdn/",
        )
    )


def _detail_image_matches_primary_family(
    url: str,
    *,
    primary_image: str,
    title: object,
) -> bool:
    if url == primary_image:
        return True
    primary_tokens = _detail_image_family_tokens(primary_image)
    candidate_tokens = _detail_image_family_tokens(url)
    if primary_tokens and candidate_tokens and primary_tokens & candidate_tokens:
        return True
    title_tokens = _semantic_detail_identity_tokens(title)
    if (
        title_tokens
        and candidate_tokens
        and len(title_tokens & candidate_tokens) >= min(2, len(title_tokens))
    ):
        return True
    primary_code = _detail_image_media_code(primary_image)
    candidate_code = _detail_image_media_code(url)
    if primary_code and candidate_code and primary_code == candidate_code:
        return True
    return not primary_tokens and not title_tokens


def _detail_image_title_from_url(url: str) -> str | None:
    path = unquote(urlparse(url).path)
    filename = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)$", "", filename, flags=re.I)
    if not stem or re.fullmatch(r"img\d+", stem, re.I):
        return None
    if _detail_image_stem_looks_encoded(stem):
        return None
    normalized = clean_text(
        re.sub(
            r"[_-]+",
            " ",
            re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem),
        )
    )
    return normalized or None


def _detail_image_stem_looks_encoded(stem: str) -> bool:
    compact = re.sub(r"[^A-Za-z0-9_-]+", "", str(stem or ""))
    alpha = re.sub(r"[^A-Za-z]+", "", compact)
    if (
        6 <= len(compact) < 24
        and re.search(r"[A-Z]", compact)
        and re.search(r"[a-z]", compact)
        and not re.search(r"[aeiou]{2,}", alpha, re.I)
    ):
        return True
    if len(compact) < 24:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]+", compact):
        return False
    if not (re.search(r"[A-Z]", compact) and re.search(r"[a-z]", compact)):
        return False
    return (
        len(re.findall(r"[A-Z]", compact)) >= 3 and len(re.findall(r"\d", compact)) >= 2
    )


def _detail_image_title_has_identity_signal(title: str) -> bool:
    return bool(
        len(_semantic_detail_identity_tokens(title)) >= 2
        or _detail_identity_codes_from_record_fields({"title": title})
    )


def _detail_image_title_matches_requested_identity(
    title: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_record_fields({"title": title})
    if (
        requested_codes
        and candidate_codes
        and detail_identity_codes_match(requested_codes, candidate_codes)
    ):
        return True
    requested_title = _detail_title_from_url(requested_page_url)
    normalized_requested_title = clean_text(requested_title)
    normalized_candidate_title = clean_text(title)
    if (
        normalized_requested_title
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(
            normalized_requested_title.lower()
        )
    ):
        return True
    requested_path = str(urlparse(requested_page_url).path or "")
    requested_segments = [
        clean_text(re.sub(r"[_-]+", " ", segment))
        for segment in requested_path.split("/")
        if clean_text(re.sub(r"[_-]+", " ", segment))
    ]
    requested_slug = next(
        (
            segment
            for segment in reversed(requested_segments)
            if segment.lower() not in {"product", "products", "p", "pd", "dp"}
        ),
        "",
    )
    if (
        requested_slug
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(requested_slug.lower())
    ):
        return True
    requested_tokens = _detail_identity_tokens(requested_title or requested_page_url)
    candidate_tokens = _detail_identity_tokens(title)
    if not requested_tokens or not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    minimum_overlap = 2 if min(len(requested_tokens), len(candidate_tokens)) <= 4 else 4
    return len(overlap) >= min(minimum_overlap, len(requested_tokens))


def _detail_image_family_tokens(url: str) -> set[str]:
    parts = [
        segment
        for segment in re.split(r"[^a-z0-9]+", unquote(urlparse(url).path).lower())
        if len(segment) >= 4
    ]
    noise = {
        "assets",
        "image",
        "images",
        "product",
        "products",
        "media",
        "picture",
        "files",
        "file",
        "main",
        "hero",
        "detail",
        "standard",
        "hover",
        "editorial",
        "square",
        "width",
        "height",
        "crop",
        "shop",
        "cdn",
        "public",
    }
    return {part for part in parts if part not in noise}


def _detail_image_media_code(url: str) -> str | None:
    match = re.search(r"/([a-z]\d{5,})/", urlparse(url).path.lower())
    if match is not None:
        return match.group(1)
    return None


def _reconcile_detail_availability_from_variants(record: dict[str, Any]) -> None:
    variants = list(record.get("variants") or [])
    if not variants:
        return
    availabilities = {
        clean_text(variant.get("availability")).lower()
        for variant in variants
        if isinstance(variant, dict) and clean_text(variant.get("availability"))
    }
    if "in_stock" in availabilities:
        record["availability"] = "in_stock"
    elif availabilities == {"out_of_stock"}:
        record["availability"] = "out_of_stock"


dedupe_primary_and_additional_images = _dedupe_primary_and_additional_images
detail_image_matches_primary_family = _detail_image_matches_primary_family
detail_title_looks_like_placeholder = _detail_title_looks_like_placeholder
sanitize_variant_row = _sanitize_variant_row
