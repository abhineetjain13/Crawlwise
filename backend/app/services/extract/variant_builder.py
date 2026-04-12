# Variant row construction — demandware, structured, DOM, adapter variants.
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.services.adapters.types import AdapterRecord, AdapterRecords
from app.services.config.extraction_rules import (
    DIMENSION_KEYWORDS,
    LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT,
    SEMANTIC_AGGREGATE_SEPARATOR,
)
from app.services.normalizers import normalize_and_validate_value
from app.services.requested_field_policy import (
    normalize_requested_field,
)
from app.services.extract.candidate_processing import (
    _embedded_blob_metadata,
    _embedded_blob_payload,
    _normalized_candidate_text,
    _parse_json_like_value,
    resolve_candidate_url as _resolve_candidate_url,
)
from app.services.extract.dom_extraction import (
    _scoped_url_key,
)
from app.services.extract.noise_policy import (
    is_network_payload_noise_url,
    sanitize_product_attribute_map,
)
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key as _canonical_structured_key,
    split_variant_axes as _split_variant_axes,
)
from app.services.extract.variant_types import (
    ParsedDemandwareVariantPayload,
    ScoredVariantBundle,
    VariantAxisValues,
    VariantBundle,
    VariantCandidateRowMap,
    VariantProductAttributes,
    VariantRecord,
    VariantRecords,
)
from app.services.extract.variant_extractor import (
    _STRUCTURED_CANONICAL_ATTRIBUTE_KEYS,
)

_VARIANT_PRODUCT_ATTRIBUTE_BLOCKLIST = frozenset(_STRUCTURED_CANONICAL_ATTRIBUTE_KEYS)


# ---------------------------------------------------------------------------
# Page scope helpers
# ---------------------------------------------------------------------------

def _page_scope_tokens(base_url: str) -> set[str]:
    parsed = urlsplit(str(base_url or "").strip())
    tokens = {
        normalize_requested_field(part) or part.lower()
        for part in parsed.path.split("/")
        if part and part not in {"products", "product", "collections"}
    }
    return {token for token in tokens if token}


def _payload_scope_hints(
    payload: object, *, max_depth: int = 4
) -> tuple[set[str], set[str]]:
    urls: set[str] = set()
    handles: set[str] = set()
    if max_depth <= 0 or payload in (None, "", [], {}):
        return urls, handles
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = normalize_requested_field(key)
            if isinstance(value, str):
                cleaned = str(value).strip()
                if normalized_key and normalized_key.endswith("url") and cleaned:
                    urls.add(cleaned)
                if (
                    normalized_key
                    in {"handle", "slug", "product_handle", "product_slug"}
                    and cleaned
                ):
                    handles.add(cleaned)
            child_urls, child_handles = _payload_scope_hints(
                value, max_depth=max_depth - 1
            )
            urls.update(child_urls)
            handles.update(child_handles)
    elif isinstance(payload, list):
        for item in payload[:LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT]:
            child_urls, child_handles = _payload_scope_hints(
                item, max_depth=max_depth - 1
            )
            urls.update(child_urls)
            handles.update(child_handles)
    return urls, handles


def _payload_matches_page_scope(payload: object, *, base_url: str) -> bool:
    if not base_url or payload in (None, "", [], {}):
        return True
    page_scope = _scoped_url_key(base_url)
    page_tokens = _page_scope_tokens(base_url)
    urls, handles = _payload_scope_hints(payload)
    normalized_urls = {_scoped_url_key(url) for url in urls if _scoped_url_key(url)}
    normalized_handles = {
        normalize_requested_field(handle) or str(handle).strip().lower()
        for handle in handles
        if str(handle).strip()
    }
    if normalized_urls:
        if page_scope in normalized_urls:
            return True
        if any(
            token and any(token in scoped_url for scoped_url in normalized_urls)
            for token in page_tokens
        ):
            return True
        return False
    if normalized_handles:
        return any(token in normalized_handles for token in page_tokens if token)
    return True


def _structured_source_payloads(
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str = "",
) -> list[tuple[str, object, dict[str, object]]]:
    sources: list[tuple[str, object, dict[str, object]]] = []
    if _payload_matches_page_scope(next_data, base_url=base_url):
        sources.append(("next_data", next_data, {}))
    sources.extend(
        ("hydrated_state", payload, {})
        for payload in hydrated_states
        if _payload_matches_page_scope(payload, base_url=base_url)
    )
    sources.extend(
        (
            "embedded_json",
            _embedded_blob_payload(payload),
            _embedded_blob_metadata(payload),
        )
        for payload in embedded_json
        if _payload_matches_page_scope(payload, base_url=base_url)
    )
    for payload in network_payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "").lower()
        if is_network_payload_noise_url(payload_url):
            continue
        if _payload_matches_page_scope(payload.get("body"), base_url=base_url):
            sources.append(("network_intercept", payload.get("body"), {}))
    return sources


# ---------------------------------------------------------------------------
# Structured source candidates
# ---------------------------------------------------------------------------

def _structured_source_candidates(
    field_name: str,
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str = "",
) -> list[dict]:
    from app.services.extract.detail_extractor import _extract_structured_spec_map
    from app.services.extract.candidate_processing import _contains_unresolved_template_value

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    sources: list[tuple[str, object, dict[str, object]]] = _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
        base_url=base_url,
    )
    for source, payload, metadata in sources:
        spec_map = _extract_structured_spec_map(payload)
        if not spec_map:
            continue
        normalized_field = normalize_requested_field(field_name)
        if field_name == "specifications":
            value = SEMANTIC_AGGREGATE_SEPARATOR.join(
                f"{label}: {spec_value}" for label, spec_value in spec_map.items()
            )
        elif field_name == "dimensions":
            value = SEMANTIC_AGGREGATE_SEPARATOR.join(
                f"{label}: {spec_value}"
                for label, spec_value in spec_map.items()
                if any(token in label.lower() for token in DIMENSION_KEYWORDS)
            )
        else:
            value = spec_map.get(normalized_field) or spec_map.get(field_name)
        normalized = _normalized_candidate_text(value)
        if not normalized or _contains_unresolved_template_value(normalized):
            continue
        key = (source, normalized)
        if key in seen:
            continue
        seen.add(key)
        row = {"value": value, "source": source}
        if metadata:
            row.update(metadata)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Row map helpers
# ---------------------------------------------------------------------------

def _merge_dynamic_row_map(
    target: VariantCandidateRowMap,
    source: VariantCandidateRowMap,
) -> None:
    for field_name, field_rows in source.items():
        target.setdefault(field_name, []).extend(field_rows)


def _selected_variant_rows(
    selected_variant: object,
    *,
    source: str,
) -> VariantCandidateRowMap:
    if not isinstance(selected_variant, dict) or not selected_variant:
        return {}
    return {
        "selected_variant": [{"value": selected_variant, "source": source}]
    }


def _product_attribute_rows(
    product_attributes: object,
    *,
    source: str,
) -> VariantCandidateRowMap:
    sanitized = sanitize_product_attribute_map(
        product_attributes,
        blocked_keys=_VARIANT_PRODUCT_ATTRIBUTE_BLOCKLIST,
    )
    if not sanitized:
        return {}
    return {
        "product_attributes": [{"value": sanitized, "source": source}],
    }


# ---------------------------------------------------------------------------
# Adapter variant rows
# ---------------------------------------------------------------------------

def _find_variant_adapter_record(
    adapter_records: AdapterRecords,
) -> AdapterRecord | None:
    for record in adapter_records:
        if isinstance(record, dict) and isinstance(record.get("variants"), list):
            return record
    return None


def _build_adapter_variant_rows(
    adapter_records: AdapterRecords,
) -> VariantCandidateRowMap:
    record = _find_variant_adapter_record(adapter_records)
    if not isinstance(record, dict):
        return {}
    rows: VariantCandidateRowMap = {}
    source = str(record.get("_source") or "adapter").strip() or "adapter"
    variants = record.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    axes = record.get("variant_axes")
    if isinstance(axes, dict) and axes:
        rows["variant_axes"] = [{"value": axes, "source": source}]
    rows.update(_selected_variant_rows(record.get("selected_variant"), source=source))
    rows.update(_product_attribute_rows(record.get("product_attributes"), source=source))
    return rows


# ---------------------------------------------------------------------------
# Demandware variant rows
# ---------------------------------------------------------------------------

def _build_demandware_variant_rows(
    network_payloads: list[dict], *, base_url: str
) -> VariantCandidateRowMap:
    parsed_variants = _extract_demandware_variants_from_payloads(
        network_payloads,
        base_url=base_url,
    )
    if not parsed_variants:
        return {}

    source = "network_intercept"
    rows: VariantCandidateRowMap = {}
    variants = parsed_variants.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    selectable_axes = parsed_variants.get("variant_axes")
    if isinstance(selectable_axes, dict) and selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": source}]
    rows.update(
        _product_attribute_rows(parsed_variants.get("product_attributes"), source=source)
    )
    rows.update(_selected_variant_rows(parsed_variants.get("selected_variant"), source=source))
    return rows


def _extract_demandware_variants_from_payloads(
    network_payloads: list[dict], *, base_url: str
) -> VariantBundle:
    variants: VariantRecords = []
    axis_values: dict[str, list[str]] = {}
    seen_variants: set[str] = set()
    selected_variant: VariantRecord | None = None
    selected_score = -1

    for payload in network_payloads:
        parsed = _parse_demandware_variation_payload(payload, base_url=base_url)
        if not parsed:
            continue
        candidate = parsed.get("selected_variant")
        if isinstance(candidate, dict) and candidate:
            fingerprint = json.dumps(candidate, sort_keys=True, default=str)
            if fingerprint not in seen_variants:
                seen_variants.add(fingerprint)
                variants.append(candidate)
        for axis_name, values in (parsed.get("axis_values") or {}).items():
            cleaned_axis = _canonical_structured_key(axis_name)
            if not cleaned_axis:
                continue
            target = axis_values.setdefault(cleaned_axis, [])
            for value in values:
                cleaned_value = _normalized_candidate_text(value)
                if cleaned_value and cleaned_value not in target:
                    target.append(cleaned_value)
        score = int(parsed.get("selection_score") or 0)
        if isinstance(candidate, dict) and candidate and score >= selected_score:
            selected_variant = candidate
            selected_score = score

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    result: VariantBundle = {}
    if variants:
        result["variants"] = variants
    if selectable_axes:
        result["variant_axes"] = selectable_axes
    if product_attributes:
        result["product_attributes"] = product_attributes
    if selected_variant:
        result["selected_variant"] = selected_variant
    return result


def _parse_demandware_variation_payload(
    payload: dict[str, object], *, base_url: str
) -> ParsedDemandwareVariantPayload | None:
    if not isinstance(payload, dict):
        return None
    payload_url = str(payload.get("url") or "")
    if not _is_demandware_variation_payload_url(payload_url):
        return None
    body = payload.get("body")
    root = (
        body.get("product")
        if isinstance(body, dict) and isinstance(body.get("product"), dict)
        else body
    )
    if not isinstance(root, dict):
        return None
    variation_attributes = root.get("variationAttributes") or root.get(
        "variation_attributes"
    )
    if not isinstance(variation_attributes, list) or not variation_attributes:
        return None

    axis_values: dict[str, list[str]] = {}
    selected_values = _demandware_selected_values_from_url(payload_url)
    for attribute in variation_attributes:
        if not isinstance(attribute, dict):
            continue
        axis_name = _normalize_demandware_axis_name(attribute)
        if not axis_name:
            continue
        raw_values = attribute.get("values")
        if not isinstance(raw_values, list):
            continue
        for raw_value in raw_values:
            if not isinstance(raw_value, dict):
                continue
            display_value = _normalized_candidate_text(
                raw_value.get("displayValue")
                or raw_value.get("displayvalue")
                or raw_value.get("value")
                or raw_value.get("id")
            )
            if display_value:
                axis_values.setdefault(axis_name, [])
                if display_value not in axis_values[axis_name]:
                    axis_values[axis_name].append(display_value)
            if raw_value.get("selected") is True and display_value:
                selected_values[axis_name] = display_value

    selected_variant = _build_demandware_selected_variant(
        root,
        base_url=base_url,
        payload_url=payload_url,
        selected_values=selected_values,
    )
    if not selected_variant:
        return None
    return {
        "axis_values": axis_values,
        "selected_variant": selected_variant,
        "selection_score": _score_demandware_selected_variant(
            selected_variant,
            base_url=base_url,
            payload_url=payload_url,
        ),
    }


def _is_demandware_variation_payload_url(payload_url: str) -> bool:
    lowered = str(payload_url or "").lower()
    return (
        "product-variation" in lowered
        or "/product/variation" in lowered
        or ("dwvar_" in lowered and "variation" in lowered)
    )


def _normalize_demandware_axis_name(attribute: dict[str, object]) -> str:
    label = (
        attribute.get("id")
        or attribute.get("attributeId")
        or attribute.get("displayName")
        or attribute.get("name")
    )
    normalized = _canonical_structured_key(label)
    if normalized:
        return normalized
    text = _normalized_candidate_text(label).lower()
    if text in {"colour", "colors", "colours"}:
        return "color"
    if text == "sizes":
        return "size"
    return text


def _demandware_selected_values_from_url(payload_url: str) -> dict[str, str]:
    selected: dict[str, str] = {}
    parsed = urlsplit(str(payload_url or "").strip())
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if not key.lower().startswith("dwvar_"):
            continue
        axis_name = key.split("_")[-1]
        normalized_axis = _canonical_structured_key(axis_name)
        cleaned_value = _normalized_candidate_text(value)
        if normalized_axis and cleaned_value:
            selected[normalized_axis] = cleaned_value
    return selected


def _build_demandware_selected_variant(
    root: dict[str, object],
    *,
    base_url: str,
    payload_url: str,
    selected_values: dict[str, str],
) -> VariantRecord | None:
    row: VariantRecord = {}
    _append_demandware_variant_identity(row, root)
    resolved_url = _resolve_candidate_url(_demandware_variant_url(root, base_url), base_url)
    if resolved_url:
        row["url"] = resolved_url
    option_values = _selected_demandware_option_values(selected_values)
    if option_values:
        row["option_values"] = option_values
        _append_demandware_variant_option_fields(row, option_values)
    _append_demandware_variant_commerce_fields(row, root)
    image_url = _extract_demandware_image_url(root, base_url=payload_url or base_url)
    if image_url:
        row["image_url"] = image_url
    return row or None


def _append_demandware_variant_identity(
    row: dict[str, object], root: dict[str, object]
) -> None:
    variant_id = root.get("id") or root.get("productId") or root.get("pid") or root.get("sku")
    if variant_id in (None, "", [], {}):
        return
    row["variant_id"] = str(variant_id)
    row["sku"] = str(variant_id)


def _demandware_variant_url(root: dict[str, object], base_url: str) -> object:
    return root.get("selectedProductUrl") or root.get("selected_product_url") or base_url


def _selected_demandware_option_values(
    selected_values: dict[str, str]
) -> dict[str, str]:
    return {
        axis_name: value
        for axis_name, value in selected_values.items()
        if value not in (None, "", [], {})
    }


def _append_demandware_variant_option_fields(
    row: dict[str, object],
    option_values: dict[str, str],
) -> None:
    for axis_name in ("color", "size"):
        if option_values.get(axis_name):
            row[axis_name] = option_values[axis_name]


def _append_demandware_variant_commerce_fields(
    row: dict[str, object],
    root: dict[str, object],
) -> None:
    for field_name, value in (
        (
            "price",
            _extract_demandware_price(
                root.get("price"),
                preferred_keys=("sales", "sale", "current"),
            ),
        ),
        (
            "original_price",
            _extract_demandware_price(
                root.get("price"),
                preferred_keys=("list", "regular", "base", "strikeThrough"),
            ),
        ),
        ("availability", _extract_demandware_availability(root)),
    ):
        if value:
            row[field_name] = value


def _extract_demandware_price(
    value: object, *, preferred_keys: tuple[str, ...]
) -> str | None:
    if isinstance(value, (str, int, float)):
        return normalize_and_validate_value("price", value)
    if not isinstance(value, dict):
        return None
    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, dict):
            for nested_key in ("formatted", "value", "amount", "price"):
                normalized = normalize_and_validate_value(
                    "price", candidate.get(nested_key)
                )
                if normalized:
                    return normalized
        else:
            normalized = normalize_and_validate_value("price", candidate)
            if normalized:
                return normalized
    for nested_key in ("formatted", "value", "amount", "price"):
        normalized = normalize_and_validate_value("price", value.get(nested_key))
        if normalized:
            return normalized
    return None


def _extract_demandware_availability(root: dict[str, object]) -> str | None:
    for model in (
        root,
        root.get("availability"),
        root.get("availabilityModel"),
        root.get("availability_model"),
        root.get("inventory"),
        root.get("inventoryRecord"),
    ):
        if not isinstance(model, dict):
            continue
        for key in ("availability", "message", "status", "stockLevelStatus"):
            normalized = normalize_and_validate_value("availability", model.get(key))
            if normalized:
                return str(normalized)
        if any(
            model.get(key) is True
            for key in (
                "readyToOrder",
                "ready_to_order",
                "orderable",
                "available",
                "inStock",
            )
        ):
            return "in_stock"
        if any(
            model.get(key) is False
            for key in (
                "readyToOrder",
                "ready_to_order",
                "orderable",
                "available",
                "inStock",
            )
        ):
            return "out_of_stock"
        try:
            ats = model.get("ats") or model.get("stockLevel")
            if ats is not None and float(ats) > 0:
                return "in_stock"
            if ats is not None and float(ats) <= 0:
                return "out_of_stock"
        except (TypeError, ValueError):
            continue
    return None


def _extract_demandware_image_url(
    root: dict[str, object], *, base_url: str
) -> str | None:
    images = root.get("images")
    if isinstance(images, dict):
        for key in ("large", "medium", "small"):
            values = images.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    resolved = _resolve_candidate_url(item.get("url"), base_url)
                else:
                    resolved = _resolve_candidate_url(item, base_url)
                if resolved:
                    return resolved
    featured = root.get("image") or root.get("featuredImage")
    if isinstance(featured, dict):
        return _resolve_candidate_url(
            featured.get("url") or featured.get("src"), base_url
        )
    return _resolve_candidate_url(featured, base_url)


def _score_demandware_selected_variant(
    variant: dict[str, object], *, base_url: str, payload_url: str
) -> int:
    score = 0
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        score += len(option_values)
        score += _demandware_selected_option_query_score(
            option_values,
            base_url=base_url,
        )
    if variant.get("url") and _scoped_url_key(
        str(variant.get("url"))
    ) == _scoped_url_key(base_url):
        score += 5
    if variant.get("availability") == "in_stock":
        score += 1
    if _is_demandware_variation_payload_url(payload_url):
        score += 1
    return score


def _demandware_selected_option_query_score(
    option_values: dict[str, object],
    *,
    base_url: str,
) -> int:
    parsed_base = urlsplit(str(base_url or "").strip())
    base_query = dict(parse_qsl(parsed_base.query, keep_blank_values=False))
    base_pid = base_query.get("pid")
    if not base_pid:
        return 0
    score = 0
    for axis_name, value in option_values.items():
        key = f"dwvar_{base_pid}_{axis_name}"
        if str(base_query.get(key) or "").strip() == str(value).strip():
            score += 10
    return score


# ---------------------------------------------------------------------------
# DOM variant axis extraction
# ---------------------------------------------------------------------------

def _variant_axis_name(button) -> str:
    raw_data_attr = _normalized_candidate_text(button.get("data-attr")).lower()
    if raw_data_attr in {"color", "colour"}:
        return "color"
    if raw_data_attr == "size":
        return "size"
    data_attr = normalize_requested_field(raw_data_attr)
    if data_attr:
        return data_attr
    class_names = " ".join(button.get("class", []))
    if "color-attribute" in class_names:
        return "color"
    if "size-attribute" in class_names:
        return "size"
    attr_blob = " ".join(
        filter(
            None,
            (
                class_names,
                str(button.get("id") or ""),
                str(button.get("data-testid") or ""),
                str(button.get("data-reactid") or ""),
            ),
        )
    ).lower()
    if "colour" in attr_blob or "color" in attr_blob or "swatch" in attr_blob:
        return "color"
    if "size" in attr_blob:
        return "size"
    aria_label = str(button.get("aria-label") or "").lower()
    if "color" in aria_label:
        return "color"
    if "size" in aria_label:
        return "size"
    attr_name = _normalized_candidate_text(
        button.get("name") or button.get("data-name")
    )
    normalized_attr_name = normalize_requested_field(attr_name)
    if normalized_attr_name:
        return normalized_attr_name
    return ""


def _variant_button_label(button, *, axis_name: str) -> str:
    for attr_name in (
        "data-size",
        "data-color",
        "data-colour",
        "data-value",
        "data-label",
        "data-name",
        "title",
        "value",
        "aria-label",
    ):
        label = _normalized_candidate_text(button.get(attr_name))
        if label:
            return label
    span = button.find(attrs={"data-displayvalue": True}) or button.find(
        attrs={"data-display-value": True}
    )
    if span:
        label = _normalized_candidate_text(
            span.get("data-displayvalue") or span.get("data-display-value")
        )
        if label:
            return label
    described = button.find("span", class_="description")
    if described:
        label = _normalized_candidate_text(described.get_text(" ", strip=True))
        if label:
            return label
    aria_label = _normalized_candidate_text(button.get("aria-label"))
    if aria_label.lower().startswith("select "):
        parts = aria_label.split(" ", 2)
        if len(parts) == 3:
            return parts[2].strip()
    text = _normalized_candidate_text(button.get_text(" ", strip=True))
    if text:
        return text
    return axis_name


def _variant_button_selected(button) -> bool:
    class_names = " ".join(button.get("class", []))
    if "selected" in class_names:
        return True
    if button.select_one(".selected"):
        return True
    assistive = button.select_one(".selected-assistive-text")
    if assistive:
        return (
            "selected"
            in _normalized_candidate_text(assistive.get_text(" ", strip=True)).lower()
        )
    return False


def _selected_dom_variant(
    base_url: str, *, selected_values: dict[str, str]
) -> VariantRecord | None:
    if not selected_values:
        return None
    row: VariantRecord = {"url": base_url}
    option_values = {
        axis_name: value for axis_name, value in selected_values.items() if value
    }
    row.update(option_values)
    if option_values:
        row["option_values"] = option_values
    return row


def _build_dom_variant_rows(
    soup: BeautifulSoup, *, base_url: str
) -> VariantCandidateRowMap:
    axis_values, selected_values = _extract_dom_variant_axes(soup)
    if not axis_values:
        return {}

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    rows: VariantCandidateRowMap = {}
    if selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": "dom_variant"}]
    rows.update(
        _product_attribute_rows(product_attributes, source="dom_variant")
    )
    rows.update(
        _selected_variant_rows(
            _selected_dom_variant(base_url, selected_values=selected_values),
            source="dom_variant",
        )
    )

    return rows


# ---------------------------------------------------------------------------
# Structured variant rows
# ---------------------------------------------------------------------------

def _build_structured_variant_rows(
    structured_sources: list[tuple[str, object, dict[str, object]]],
    *,
    base_url: str,
) -> VariantCandidateRowMap:
    parsed_variants = _extract_structured_variants_from_sources(
        structured_sources,
        base_url=base_url,
    )
    if not parsed_variants:
        return {}

    source = "structured_variant"
    rows: VariantCandidateRowMap = {}
    variants = parsed_variants.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    selectable_axes = parsed_variants.get("variant_axes")
    if isinstance(selectable_axes, dict) and selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": source}]
    rows.update(
        _product_attribute_rows(parsed_variants.get("product_attributes"), source=source)
    )
    rows.update(_selected_variant_rows(parsed_variants.get("selected_variant"), source=source))
    return rows


def _extract_structured_variants_from_sources(
    structured_sources: list[tuple[str, object, dict[str, object]]],
    *,
    base_url: str,
) -> VariantBundle:
    variants: VariantRecords = []
    axis_values: VariantAxisValues = {}
    seen_variants: set[str] = set()
    selected_variant: VariantRecord | None = None
    selected_score = -1
    selection_hints = _structured_variant_selection_hints(base_url)

    for _source_name, payload, _metadata in structured_sources:
        for container in _iter_structured_variant_containers(payload):
            parsed = _parse_structured_variant_container(
                container,
                base_url=base_url,
                selection_hints=selection_hints,
            )
            if not parsed:
                continue
            for variant in parsed.get("variants") or []:
                if not isinstance(variant, dict):
                    continue
                fingerprint = json.dumps(variant, sort_keys=True, default=str)
                if fingerprint in seen_variants:
                    continue
                seen_variants.add(fingerprint)
                variants.append(variant)
            for axis_name, values in (parsed.get("axis_values") or {}).items():
                cleaned_axis = _canonical_structured_key(axis_name)
                if not cleaned_axis:
                    continue
                target = axis_values.setdefault(cleaned_axis, [])
                for value in values:
                    cleaned_value = _normalized_candidate_text(value)
                    if cleaned_value and cleaned_value not in target:
                        target.append(cleaned_value)
            score = int(parsed.get("selection_score") or 0)
            candidate = parsed.get("selected_variant")
            if isinstance(candidate, dict) and candidate and score >= selected_score:
                selected_variant = candidate
                selected_score = score

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    result: VariantBundle = {}
    if variants:
        result["variants"] = variants
    if selectable_axes:
        result["variant_axes"] = selectable_axes
    if product_attributes:
        result["product_attributes"] = product_attributes
    if selected_variant:
        result["selected_variant"] = selected_variant
    return result


def _iter_structured_variant_containers(
    payload: object,
    *,
    max_depth: int = 8,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen_objects: set[int] = set()
    seen_strings: set[str] = set()

    def walk(node: object, depth: int) -> None:
        if depth < 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            node_id = id(node)
            if node_id in seen_objects:
                return
            seen_objects.add(node_id)
            if _looks_like_structured_variant_container(node):
                results.append(node)
            for value in node.values():
                walk(value, depth - 1)
            return
        if isinstance(node, list):
            for item in node[:200]:
                walk(item, depth - 1)
            return
        if not isinstance(node, str):
            return
        parsed = _parse_json_like_value(node)
        if not isinstance(parsed, (dict, list)):
            return
        cache_key = str(node[:500])
        if cache_key in seen_strings:
            return
        seen_strings.add(cache_key)
        walk(parsed, depth - 1)

    walk(payload, max_depth)
    return results


def _looks_like_structured_variant_container(payload: dict[str, object]) -> bool:
    sizes = payload.get("sizes")
    if isinstance(sizes, list) and sizes:
        dict_sizes = [item for item in sizes[:30] if isinstance(item, dict)]
        if dict_sizes and any(
            any(token in size for token in ("skuId", "label", "available", "sizeSellerData"))
            for size in dict_sizes
        ):
            return True
    variations = payload.get("variations")
    if not isinstance(variations, list) or not variations:
        return False
    dict_variations = [item for item in variations[:20] if isinstance(item, dict)]
    if not dict_variations:
        return False
    return any(
        key in payload
        for key in ("colors", "name", "id", "product", "orderable", "configureID")
    ) or any(
        any(
            token in variation
            for token in (
                "variantId",
                "id",
                "sku",
                "ean",
                "colorValue",
                "colorName",
                "price",
                "salePrice",
            )
        )
        for variation in dict_variations
    )


def _parse_structured_variant_container(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> ScoredVariantBundle | None:
    sizes = payload.get("sizes")
    if isinstance(sizes, list) and sizes:
        parsed_sizes = _parse_structured_size_variant_container(
            sizes,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if parsed_sizes:
            return parsed_sizes

    variations = payload.get("variations")
    if not isinstance(variations, list) or not variations:
        return None

    axis_values: dict[str, list[str]] = {}
    for color_name in _structured_color_axis_values(payload.get("colors")):
        axis_values.setdefault("color", [])
        if color_name not in axis_values["color"]:
            axis_values["color"].append(color_name)

    parsed_variants: VariantRecords = []
    selected_variant: VariantRecord | None = None
    selected_score = -1
    for item in variations:
        if not isinstance(item, dict):
            continue
        variant = _build_structured_variant_row(
            item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if not variant:
            continue
        parsed_variants.append(variant)
        option_values = variant.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, value in option_values.items():
                cleaned_axis = _canonical_structured_key(axis_name)
                cleaned_value = _normalized_candidate_text(value)
                if not cleaned_axis or not cleaned_value:
                    continue
                target = axis_values.setdefault(cleaned_axis, [])
                if cleaned_value not in target:
                    target.append(cleaned_value)
        score = _score_structured_selected_variant(
            variant,
            raw_variant=item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if score >= selected_score:
            selected_variant = variant
            selected_score = score

    if not parsed_variants:
        return None
    return {
        "variants": parsed_variants,
        "axis_values": axis_values,
        "selected_variant": selected_variant,
        "selection_score": selected_score,
    }


def _parse_structured_size_variant_container(
    sizes: list[object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> ScoredVariantBundle | None:
    axis_values: dict[str, list[str]] = {}
    parsed_variants: VariantRecords = []
    selected_variant: VariantRecord | None = None
    selected_score = -1

    for item in sizes:
        if not isinstance(item, dict):
            continue
        variant = _build_structured_size_variant_row(
            item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if not variant:
            continue
        parsed_variants.append(variant)
        option_values = variant.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, value in option_values.items():
                cleaned_axis = _canonical_structured_key(axis_name)
                cleaned_value = _normalized_candidate_text(value)
                if not cleaned_axis or not cleaned_value:
                    continue
                target = axis_values.setdefault(cleaned_axis, [])
                if cleaned_value not in target:
                    target.append(cleaned_value)
        score = _score_structured_selected_variant(
            variant,
            raw_variant=item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if score >= selected_score:
            selected_variant = variant
            selected_score = score

    if not parsed_variants:
        return None
    return {
        "variants": parsed_variants,
        "axis_values": axis_values,
        "selected_variant": selected_variant,
        "selection_score": selected_score,
    }


def _structured_color_axis_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    colors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _normalized_candidate_text(
            item.get("name")
            or item.get("label")
            or item.get("colorName")
            or item.get("displayValue")
        )
        if name and name not in colors:
            colors.append(name)
    return colors


def _structured_variant_selection_hints(base_url: str) -> dict[str, str]:
    hints: dict[str, str] = {}
    parsed = urlsplit(str(base_url or "").strip())
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = normalize_requested_field(key)
        cleaned_value = _normalized_candidate_text(value)
        if not normalized_key or not cleaned_value:
            continue
        if normalized_key in {"swatch", "color", "colour"}:
            hints["color"] = cleaned_value
        elif normalized_key == "size":
            hints["size"] = cleaned_value
        elif normalized_key in {"variant", "variant_id", "sku", "pid", "vid", "id"}:
            hints["variant_id"] = cleaned_value
    return hints


def _build_structured_variant_row(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> VariantRecord | None:
    row: VariantRecord = {}
    variant_id = _normalized_candidate_text(
        payload.get("variantId")
        or payload.get("ean")
        or payload.get("sku")
        or payload.get("id")
    )
    if variant_id:
        row["variant_id"] = variant_id
        row["sku"] = variant_id

    option_values = _structured_variant_option_values(payload)
    if option_values:
        row["option_values"] = option_values
        for axis_name in ("color", "size"):
            if option_values.get(axis_name):
                row[axis_name] = option_values[axis_name]

    url = _structured_variant_url(payload, base_url=base_url, selection_hints=selection_hints)
    if url:
        row["url"] = url

    price = normalize_and_validate_value(
        "price",
        payload.get("salePrice") or payload.get("price"),
    )
    if price:
        row["price"] = price
    original_price = normalize_and_validate_value(
        "price",
        payload.get("listPrice")
        or payload.get("originalPrice")
        or payload.get("compareAtPrice")
        or payload.get("compare_at_price"),
    )
    if original_price:
        row["original_price"] = original_price
    availability = _structured_variant_availability(payload)
    if availability:
        row["availability"] = availability
    image_url = _structured_variant_image_url(payload, base_url=base_url)
    if image_url:
        row["image_url"] = image_url
    return row or None


def _build_structured_size_variant_row(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> VariantRecord | None:
    row: VariantRecord = {}
    variant_id = _normalized_candidate_text(
        payload.get("skuId") or payload.get("sku") or payload.get("id")
    )
    if variant_id:
        row["variant_id"] = variant_id
        row["sku"] = variant_id

    size_label = _normalized_candidate_text(
        payload.get("label") or payload.get("size") or payload.get("displaySize")
    )
    if size_label:
        row["option_values"] = {"size": size_label}
        row["size"] = size_label

    url = _structured_variant_url(payload, base_url=base_url, selection_hints=selection_hints)
    if url:
        row["url"] = url

    seller_rows = payload.get("sizeSellerData")
    primary_seller = seller_rows[0] if isinstance(seller_rows, list) and seller_rows else {}
    if not isinstance(primary_seller, dict):
        primary_seller = {}
    price = normalize_and_validate_value(
        "price",
        primary_seller.get("discountedPrice") or payload.get("discountedPrice") or payload.get("price"),
    )
    if price:
        row["price"] = price
    original_price = normalize_and_validate_value(
        "price",
        primary_seller.get("mrp") or payload.get("mrp") or payload.get("originalPrice"),
    )
    if original_price:
        row["original_price"] = original_price
    availability = _structured_variant_availability(payload)
    if availability:
        row["availability"] = availability
    return row or None


def _structured_variant_option_values(payload: dict[str, object]) -> dict[str, str]:
    option_values: dict[str, str] = {}
    raw_option_values = payload.get("option_values") or payload.get("optionValues")
    if isinstance(raw_option_values, dict):
        for key, value in raw_option_values.items():
            axis_name = _canonical_structured_key(key)
            cleaned_value = _normalized_candidate_text(value)
            if axis_name and cleaned_value:
                option_values[axis_name] = cleaned_value
    for axis_name, raw_value in (
        ("color", payload.get("colorName") or payload.get("color") or payload.get("colour")),
        ("size", payload.get("sizeName") or payload.get("size") or payload.get("displaySize")),
        ("waist", payload.get("waist")),
        ("length", payload.get("length")),
        ("width", payload.get("width")),
    ):
        cleaned_value = _normalized_candidate_text(raw_value)
        if cleaned_value:
            option_values[axis_name] = cleaned_value
    all_sizes = payload.get("allSizesList")
    if isinstance(all_sizes, list):
        for entry in all_sizes:
            if not isinstance(entry, dict):
                continue
            axis_name = _canonical_structured_key(entry.get("name"))
            cleaned_value = _normalized_candidate_text(entry.get("label") or entry.get("value"))
            if axis_name and cleaned_value:
                option_values.setdefault(axis_name, cleaned_value)
    if "size" not in option_values:
        cleaned_label = _normalized_candidate_text(payload.get("label"))
        if cleaned_label:
            option_values["size"] = cleaned_label
    return option_values


def _structured_variant_url(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> str | None:
    for field_name in ("url", "href", "permalink", "link"):
        resolved = _resolve_candidate_url(payload.get(field_name), base_url)
        if resolved:
            return resolved
    if not base_url:
        return None
    parsed = urlsplit(str(base_url or "").strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "swatch" in query:
        swatch_value = _normalized_candidate_text(payload.get("colorValue"))
        if swatch_value:
            query["swatch"] = swatch_value
    elif selection_hints.get("color") and payload.get("colorValue"):
        query["color"] = _normalized_candidate_text(payload.get("colorValue"))
    encoded_query = urlencode(query, doseq=True)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, encoded_query, parsed.fragment)
    )


def _structured_variant_availability(payload: dict[str, object]) -> str | None:
    for field_name in ("availability", "stockLevelStatus", "stock_status", "status"):
        normalized = normalize_and_validate_value("availability", payload.get(field_name))
        if normalized:
            return str(normalized)
    if payload.get("availableToSell") is True:
        return "in_stock"
    if payload.get("availableToSell") is False:
        return "out_of_stock"
    if any(payload.get(key) is True for key in ("orderable", "available", "inStock")):
        return "in_stock"
    if any(payload.get(key) is False for key in ("orderable", "available", "inStock")):
        return "out_of_stock"
    return None


def _structured_variant_image_url(
    payload: dict[str, object], *, base_url: str
) -> str | None:
    for field_name in ("preview", "image", "image_url", "imageUrl"):
        value = payload.get(field_name)
        if isinstance(value, dict):
            resolved = _resolve_candidate_url(
                value.get("href") or value.get("url") or value.get("src"),
                base_url,
            )
        else:
            resolved = _resolve_candidate_url(value, base_url)
        if resolved:
            return resolved
    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                resolved = _resolve_candidate_url(
                    item.get("href") or item.get("url") or item.get("src"),
                    base_url,
                )
            else:
                resolved = _resolve_candidate_url(item, base_url)
            if resolved:
                return resolved
    return None


def _score_structured_selected_variant(
    variant: dict[str, object],
    *,
    raw_variant: dict[str, object],
    base_url: str,
    selection_hints: dict[str, str],
) -> int:
    score = 0
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        for axis_name, selected_value in selection_hints.items():
            option_value = _normalized_candidate_text(option_values.get(axis_name))
            if option_value and option_value.casefold() == selected_value.casefold():
                score += 10
    raw_color_value = _normalized_candidate_text(raw_variant.get("colorValue"))
    if raw_color_value and selection_hints.get("color"):
        if raw_color_value.casefold() == selection_hints["color"].casefold():
            score += 12
    for key in ("variant_id", "sku"):
        value = _normalized_candidate_text(variant.get(key))
        if value and selection_hints.get("variant_id"):
            if value.casefold() == selection_hints["variant_id"].casefold():
                score += 12
    if variant.get("availability") == "in_stock":
        score += 1
    if variant.get("url") and _scoped_url_key(str(variant.get("url"))) == _scoped_url_key(base_url):
        score += 5
    return score


def _extract_dom_variant_axes(
    soup: BeautifulSoup,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    from app.services.extract.noise_policy import is_inside_site_chrome

    axis_values: dict[str, list[str]] = {}
    selected_values: dict[str, str] = {}

    for select in soup.find_all("select"):
        if not isinstance(select, Tag) or is_inside_site_chrome(select):
            continue
        axis_name = _variant_axis_name(select) or _variant_axis_name_from_context(select)
        if not axis_name:
            continue
        for option in select.find_all("option"):
            label = _variant_button_label(option, axis_name=axis_name)
            if not _dom_variant_value_is_valid(label, axis_name=axis_name):
                continue
            values = axis_values.setdefault(axis_name, [])
            if label not in values:
                values.append(label)
            if option.has_attr("selected"):
                selected_values[axis_name] = label

    candidate_nodes = soup.select(
        ",".join(
            (
                "[data-size]",
                "[data-color]",
                "[data-colour]",
                "[data-attr]",
                "[data-value]",
                "[role='radio']",
                "[role='option']",
                "button",
                "label",
                "li",
                "div",
            )
        )
    )
    for node in candidate_nodes:
        if not isinstance(node, Tag) or is_inside_site_chrome(node):
            continue
        if not _looks_like_dom_variant_button(node):
            continue
        axis_name = _variant_axis_name(node) or _variant_axis_name_from_context(node)
        if not axis_name:
            continue
        label = _variant_button_label(node, axis_name=axis_name)
        if not _dom_variant_value_is_valid(label, axis_name=axis_name):
            continue
        values = axis_values.setdefault(axis_name, [])
        if label not in values:
            values.append(label)
        if _variant_button_selected(node):
            selected_values[axis_name] = label

    return axis_values, selected_values


def _variant_axis_name_from_context(node: Tag) -> str:
    candidates = [
        node.get("aria-label"),
        node.get("title"),
        node.get("name"),
        node.get("id"),
        " ".join(node.get("class", [])),
    ]
    for candidate in candidates:
        axis_name = _normalized_variant_axis_token(candidate)
        if axis_name:
            return axis_name

    for sibling in list(node.previous_siblings)[:4]:
        if not isinstance(sibling, Tag):
            continue
        axis_name = _normalized_variant_axis_token(sibling.get_text(" ", strip=True))
        if axis_name:
            return axis_name

    parent = node.parent
    steps = 0
    while isinstance(parent, Tag) and steps < 4:
        axis_name = _normalized_variant_axis_token(
            " ".join(
                filter(
                    None,
                    (
                        parent.get("aria-label"),
                        parent.get("title"),
                        parent.get("id"),
                        " ".join(parent.get("class", [])),
                    ),
                )
            )
        )
        if axis_name:
            return axis_name
        heading = parent.find(["legend", "label", "h2", "h3", "h4", "p", "span"])
        if isinstance(heading, Tag):
            axis_name = _normalized_variant_axis_token(
                heading.get_text(" ", strip=True)
            )
            if axis_name:
                return axis_name
        parent = parent.parent
        steps += 1
    return ""


def _normalized_variant_axis_token(value: object) -> str:
    text = _normalized_candidate_text(value).lower()
    if not text:
        return ""
    if any(token in text for token in ("size", "fit")):
        return "size"
    if any(token in text for token in ("color", "colour", "swatch")):
        return "color"
    return ""


def _looks_like_dom_variant_button(node: Tag) -> bool:
    if node.name not in {"button", "option", "label", "li"}:
        direct_children = node.find_all(["button", "option", "label", "li"], recursive=False)
        if direct_children:
            return False
    attr_blob = " ".join(
        filter(
            None,
            (
                str(node.get("aria-label") or ""),
                str(node.get("title") or ""),
                str(node.get("name") or ""),
                str(node.get("id") or ""),
                " ".join(node.get("class", [])),
            ),
        )
    ).lower()
    if any(
        token in attr_blob
        for token in ("size", "color", "colour", "swatch", "variant", "option")
    ):
        return True
    return any(
        node.has_attr(attr_name)
        for attr_name in (
            "data-size",
            "data-color",
            "data-colour",
            "data-attr",
            "data-value",
        )
    )


def _dom_variant_value_is_valid(value: str, *, axis_name: str) -> bool:
    from app.services.extract.candidate_processing import _VARIANT_SELECTOR_PROMPT_RE

    text = _normalized_candidate_text(value)
    if not text:
        return False
    lowered = text.casefold()
    if lowered in {"select size", "choose size", "size", "select color", "color"}:
        return False
    if _VARIANT_SELECTOR_PROMPT_RE.match(text):
        return False
    if axis_name == "size" and re.fullmatch(r"[A-Za-z0-9.+/-]{1,8}", text):
        return True
    return len(text.split()) <= 5


# ---------------------------------------------------------------------------
# Top-level build_variant_rows
# ---------------------------------------------------------------------------

def _build_variant_rows(
    *,
    base_url: str,
    soup: BeautifulSoup,
    adapter_records: AdapterRecords,
    network_payloads: list[dict],
    structured_sources: list[tuple[str, object, dict[str, object]]] | None = None,
) -> VariantCandidateRowMap:
    rows: VariantCandidateRowMap = {}
    adapter_variant_rows = _build_adapter_variant_rows(adapter_records)
    if adapter_variant_rows:
        _merge_dynamic_row_map(rows, adapter_variant_rows)

    demandware_rows = _build_demandware_variant_rows(
        network_payloads,
        base_url=base_url,
    )
    if demandware_rows:
        _merge_dynamic_row_map(rows, demandware_rows)

    structured_rows = _build_structured_variant_rows(
        structured_sources or [],
        base_url=base_url,
    )
    if structured_rows:
        _merge_dynamic_row_map(rows, structured_rows)

    dom_rows = _build_dom_variant_rows(soup, base_url=base_url)
    if dom_rows:
        _merge_dynamic_row_map(rows, dom_rows)

    return rows
