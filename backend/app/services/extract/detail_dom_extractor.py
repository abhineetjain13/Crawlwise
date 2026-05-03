from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS,
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
    VARIANT_PROMO_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_UI_NOISE_PHRASES,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_SIZE_VALUE_PATTERNS,
)
from app.services.field_value_core import (
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    flatten_variants_for_public_output,
    is_title_noise,
    object_dict as _object_dict,
    object_list as _object_list,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.field_value_dom import (
    apply_selector_fallbacks,
    extract_feature_rows,
    extract_heading_sections,
    extract_page_images,
)
from app.services.extract.detail_raw_signals import (
    breadcrumb_category_from_dom,
    gender_from_detail_context,
)
from app.services.js_state_helpers import select_variant
from app.services.extract.shared_variant_logic import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    merge_variant_pair,
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    resolve_variants,
    resolve_variant_group_name,
    split_variant_axes,
    variant_axis_name_is_semantic,
    variant_dom_cues_present,
)

logger = logging.getLogger(__name__)

_detail_variant_size_value_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_SIZE_VALUE_PATTERNS
    if str(pattern).strip()
)
_variant_option_value_suffix_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS
    if str(pattern).strip()
)
_variant_option_value_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in VARIANT_OPTION_VALUE_NOISE_TOKENS
    if str(token).strip()
)
_variant_option_value_ui_noise_phrases = tuple(
    str(token).strip().lower()
    for token in tuple(VARIANT_OPTION_VALUE_UI_NOISE_PHRASES or ())
    if str(token).strip()
)
_variant_promo_noise_tokens = tuple(
    str(token).strip().lower()
    for token in tuple(VARIANT_PROMO_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_artifact_value_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS or ())
    if str(token).strip()
)


def primary_dom_context(
    context: Any,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup
    if cleaned_parser.css_first(
        DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR
    ) or cleaned_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR):
        return cleaned_parser, cleaned_soup
    original_parser = LexborHTMLParser(context.original_html)
    original_soup = BeautifulSoup(context.original_html, "html.parser")
    if not (
        original_parser.css_first(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
        or original_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
    ):
        return cleaned_parser, cleaned_soup
    logger.debug(
        "Using original DOM after cleaned DOM lost primary content for %s", page_url
    )
    return original_parser, original_soup


def apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    *,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    selector_rules: list[dict[str, object]] | None,
    add_sourced_candidate: Callable[..., None],
    breadcrumb_soup: BeautifulSoup | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    h1 = dom_parser.css_first("h1")
    page_title = dom_parser.css_first("title")
    h1_title = text_or_none(h1.text(separator=" ", strip=True) if h1 else "")
    page_title_text = text_or_none(
        page_title.text(separator=" ", strip=True) if page_title else ""
    )
    title = next(
        (
            candidate
            for candidate in (h1_title, page_title_text)
            if candidate and not is_title_noise(candidate)
        ),
        None,
    )
    if title:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "title",
            title,
            source="dom_h1",
        )
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        selector_trace_candidates=selector_trace_candidates,
    )
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    canonical_href = canonical.get("href") if canonical is not None else None
    if canonical_href:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "url",
            absolute_url(page_url, canonical_href),
            source="dom_canonical",
        )
    images = extract_page_images(
        soup,
        page_url,
        exclude_linked_detail_images="detail" in str(surface or "").strip().lower(),
        surface=surface,
    )
    if images:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "image_url",
            images[0],
            source="dom_images",
        )
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "additional_images",
            images[1:],
            source="dom_images",
        )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    for label, value in extract_heading_sections(soup).items():
        normalized = alias_lookup.get(label.lower()) or alias_lookup.get(
            re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        )
        if normalized:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    if "features" in fields:
        feature_rows = extract_feature_rows(soup)
        if feature_rows:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "features",
                feature_rows,
                source="dom_sections",
            )
    breadcrumb_category = breadcrumb_category_from_dom(
        breadcrumb_soup or soup,
        current_title=title,
        page_url=page_url,
    )
    if "category" in fields and breadcrumb_category:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "category",
            breadcrumb_category,
            source="dom_breadcrumb",
        )
    if "gender" in fields and not candidates.get("gender"):
        gender = gender_from_detail_context(
            breadcrumb_category, title, urlsplit(page_url).path
        )
        if gender:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "gender",
                gender,
                source="dom_text",
            )
    body_node = dom_parser.body
    body_text = (
        clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
    )
    if "currency" in fields and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if not currency_code:
                continue
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "currency",
                currency_code,
                source="dom_text",
            )
            break
    if "review_count" in fields and not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(body_text)
        if review_match:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "review_count",
                review_match.group(1),
                source="dom_text",
            )
    if "rating" in fields and not candidates.get("rating"):
        rating_match = RATING_RE.search(body_text)
        if rating_match:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    normalized_surface = str(surface or "")
    if (
        normalized_surface.startswith("job_")
        and "remote" in fields
        and not candidates.get("remote")
    ):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "remote",
                "remote",
                source="dom_text",
            )


def _resolve_dom_variant_group_name(node: Any) -> str:
    resolved = resolve_variant_group_name(node)
    if resolved:
        return resolved
    if not hasattr(node, "select"):
        return ""
    for input_node in node.select("input[type='radio'], input[type='checkbox']")[:24]:
        resolved = resolve_variant_group_name(input_node)
        if resolved:
            return resolved
    return ""


def _variant_option_value_is_noise(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    compact = re.sub(r"[^a-z0-9%#]+", "", lowered)
    return (
        compact in _variant_option_value_noise_tokens
        or compact in _variant_artifact_value_tokens
        or re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", compact) is not None
        or (
            "%" in lowered
            and any(token in lowered for token in _variant_promo_noise_tokens)
        )
        or lowered in {"select", "choose", "option", "size guide"}
        or any(phrase in lowered for phrase in _variant_option_value_ui_noise_phrases)
        or (
            "size guide" in lowered
            and re.search(r"\b(?:please\s+)?select\b", lowered) is not None
        )
        or (
            re.fullmatch(r"[-\s]*(?:click\s+to\s+)?(?:choose|select)\b.*", lowered)
            is not None
        )
        or re.fullmatch(r"[-\s]+.+[-\s]+", lowered) is not None
        or re.fullmatch(r"\(\d+\)", value) is not None
        or re.fullmatch(r"\d{3,5}/\d{2,5}/\d{2,5}", value) is not None
    )


def _strip_variant_option_value_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in _variant_option_value_suffix_noise_patterns:
        stripped = pattern.sub("", stripped).strip()
    return stripped or cleaned


def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = (
        text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    )
    if input_id:
        label = container.find("label", attrs={"for": input_id})
        if label is not None:
            return label
    if hasattr(input_node, "find_parent"):
        label = input_node.find_parent("label")
        if label is not None:
            return label
    sibling = getattr(input_node, "next_sibling", None)
    while sibling is not None:
        if getattr(sibling, "name", None) == "label":
            return sibling
        sibling = getattr(sibling, "next_sibling", None)
    return None


def _node_state_matches(node: Any, *tokens: str) -> bool:
    if not hasattr(node, "get"):
        return False
    class_attr = node.get("class")
    probe = (
        " ".join(str(value) for value in class_attr)
        if isinstance(class_attr, list)
        else str(class_attr or "")
    ).lower()
    return any(token in probe for token in tokens)


def _node_attr_is_truthy(node: Any, *attr_names: str) -> bool:
    if not hasattr(node, "get"):
        return False
    for attr_name in attr_names:
        value = node.get(attr_name)
        if value in (None, "", [], {}, False):
            continue
        if value is True:
            return True
        normalized = str(value).strip().lower()
        if normalized in {"", "false", "0", "none"}:
            continue
        return True
    return False


def variant_option_availability(
    *, node: Any, label_node: Any | None
) -> tuple[str | None, int | None]:
    attr_probe_parts: list[str] = []
    text_probe_parts: list[str] = []
    for candidate in (
        node,
        label_node,
        getattr(node, "parent", None),
        getattr(label_node, "parent", None) if label_node is not None else None,
    ):
        if candidate is None or not hasattr(candidate, "get"):
            continue
        class_attr = candidate.get("class")
        if isinstance(class_attr, list):
            attr_probe_parts.extend(str(value) for value in class_attr if value)
        elif class_attr not in (None, "", [], {}):
            attr_probe_parts.append(str(class_attr))
        for attr_name in ("aria-label", "data-testid", "name", "id"):
            value = candidate.get(attr_name)
            if value not in (None, "", [], {}):
                attr_probe_parts.append(str(value))
        if hasattr(candidate, "get_text"):
            text_probe_parts.append(candidate.get_text(" ", strip=True))
    attr_probe = clean_text(" ".join(attr_probe_parts)).lower()
    text_probe = clean_text(" ".join(text_probe_parts)).lower()
    if any(
        token in attr_probe
        for token in ("outstock", "out-stock", "soldout", "sold-out", "unavailable")
    ):
        return "out_of_stock", 0
    stock_match = re.search(r"\b(\d+)\s+left\b", text_probe)
    if stock_match:
        quantity = int(stock_match.group(1))
        return ("in_stock" if quantity > 0 else "out_of_stock"), quantity
    if "out of stock" in text_probe or "sold out" in text_probe:
        return "out_of_stock", 0
    if "in stock" in text_probe or "available" in text_probe:
        return "in_stock", None
    return None, None


def _variant_option_url(
    *,
    container: Any,
    node: Any,
    label_node: Any | None,
    page_url: str,
) -> str | None:
    attr_names = (
        "href",
        "data-href",
        "data-url",
        "data-product-url",
        "data-target-url",
        "data-link",
        "data-variant-url",
    )
    candidates: list[Any] = [node, label_node]
    if hasattr(node, "find_parent"):
        parent_anchor = node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if label_node is not None and hasattr(label_node, "find_parent"):
        parent_anchor = label_node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if hasattr(node, "find"):
        anchor = node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if label_node is not None and hasattr(label_node, "find"):
        anchor = label_node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if hasattr(container, "find"):
        anchor = container.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "get"):
            continue
        for attr_name in attr_names:
            raw = candidate.get(attr_name)
            url = text_or_none(raw)
            if url:
                from app.services.field_value_core import absolute_url

                return absolute_url(page_url, url)
    return None


def _merge_variant_option_state(
    entry: dict[str, object],
    *,
    container: Any,
    node: Any,
    page_url: str,
    label_node: Any | None = None,
) -> None:
    selected = (
        _node_state_matches(
            node, "selected", "active", "current", "highlight", "checked"
        )
        or _node_attr_is_truthy(
            node,
            "checked",
            "aria-checked",
        )
        or text_or_none(
            getattr(node, "get", lambda *_args, **_kwargs: None)("data-state")
        )
        == "checked"
    )
    if selected:
        entry["selected"] = True
    availability, stock_quantity = variant_option_availability(
        node=node, label_node=label_node
    )
    if availability and entry.get("availability") in (None, "", [], {}):
        entry["availability"] = availability
    if stock_quantity is not None:
        entry["stock_quantity"] = stock_quantity
    variant_url = _variant_option_url(
        container=container,
        node=node,
        label_node=label_node,
        page_url=page_url,
    )
    if variant_url and entry.get("url") in (None, "", [], {}):
        entry["url"] = variant_url


def _collect_variant_choice_entries(
    container: Any, *, page_url: str
) -> list[dict[str, object]]:
    axis_name = normalized_variant_axis_key(_resolve_dom_variant_group_name(container))
    entries_by_value: dict[str, dict[str, object]] = {}
    for node in container.select(
        "[role='radio'], "
        "[role='option'], "
        "button, "
        "[data-value], [data-option-value], "
        "[aria-pressed], [aria-selected], [data-state], [data-selected]"
    )[:24]:
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(container, node),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=node,
            page_url=page_url,
        )
        variant_id = text_or_none(
            node.get("data-sku")
            or node.get("data-variant-id")
            or node.get("data-product-id")
        )
        if variant_id and entry.get("variant_id") in (None, "", [], {}):
            entry["variant_id"] = variant_id
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[
        :24
    ]:
        label_node = _variant_input_label(container, input_node)
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(
                    container, input_node, label_node=label_node
                ),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=input_node,
            page_url=page_url,
            label_node=label_node,
        )
    return list(entries_by_value.values())


def _variant_choice_entry_value(
    container: Any,
    node: Any,
    *,
    label_node: Any | None = None,
) -> str:
    resolved_label = label_node or _variant_input_label(container, node)
    label_text = (
        resolved_label.get_text(" ", strip=True)
        if resolved_label is not None and hasattr(resolved_label, "get_text")
        else ""
    )
    return clean_text(
        label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or node.get("aria-label")
        or node.get("value")
        or (node.get_text(" ", strip=True) if hasattr(node, "get_text") else "")
    )


def _split_compound_axis_name(name: object) -> list[tuple[str, str]]:
    cleaned = clean_text(name)
    if not cleaned:
        return []
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:&|/|\band\b)\s*", cleaned, flags=re.I)
        if clean_text(part)
    ]
    if len(parts) < 2:
        return []
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        if not variant_axis_name_is_semantic(part):
            return []
        axis_key = normalized_variant_axis_key(part)
        if not axis_key or axis_key in seen:
            return []
        seen.add(axis_key)
        resolved.append((axis_key, normalized_variant_axis_display_name(part) or part))
    return resolved if len(resolved) >= 2 else []


def _strip_variant_option_price_suffix(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    without_price = re.sub(r"\s*\([^)]*[\d][^)]*\)\s*$", "", cleaned).strip()
    return without_price or cleaned


def _split_compound_option_value(
    value: object,
    *,
    axis_keys: tuple[str, ...],
) -> dict[str, str] | None:
    cleaned = _strip_variant_option_price_suffix(value)
    if not cleaned or len(axis_keys) != 2 or "size" not in axis_keys:
        return None
    other_axis = next((axis for axis in axis_keys if axis != "size"), "")
    if not other_axis:
        return None
    tokens = [token for token in cleaned.split() if token]
    for width in range(min(3, len(tokens)), 0, -1):
        size_candidate = " ".join(tokens[-width:])
        if not any(
            pattern.fullmatch(size_candidate)
            for pattern in _detail_variant_size_value_patterns
        ):
            continue
        other_value = clean_text(" ".join(tokens[:-width]))
        if not other_value:
            return None
        return {
            other_axis: other_value,
            "size": size_candidate,
        }
    return None


def _expand_compound_option_group(
    group: dict[str, object],
) -> list[dict[str, object]] | None:
    axis_parts = _split_compound_axis_name(group.get("name"))
    if len(axis_parts) != 2:
        return None
    entries = [
        entry for entry in _object_list(group.get("entries")) if isinstance(entry, dict)
    ]
    if not entries:
        return None
    axis_keys = tuple(axis_key for axis_key, _ in axis_parts)
    parsed_rows: list[dict[str, str]] = []
    for entry in entries:
        parsed = _split_compound_option_value(entry.get("value"), axis_keys=axis_keys)
        if not parsed:
            return None
        parsed_rows.append(parsed)
    axis_values: dict[str, list[str]] = {axis_key: [] for axis_key, _ in axis_parts}
    observed_combos: set[tuple[str, ...]] = set()
    for parsed in parsed_rows:
        combo = tuple(parsed.get(axis_key, "") for axis_key, _ in axis_parts)
        if any(not value for value in combo):
            return None
        observed_combos.add(combo)
        for axis_key, _ in axis_parts:
            axis_value = parsed[axis_key]
            if axis_value not in axis_values[axis_key]:
                axis_values[axis_key].append(axis_value)
    expected_combo_count = 1
    for axis_key, _ in axis_parts:
        values = axis_values.get(axis_key) or []
        if len(values) < 2:
            return None
        expected_combo_count *= len(values)
    if (
        len(observed_combos) != len(parsed_rows)
        or len(observed_combos) != expected_combo_count
    ):
        return None
    return [
        {
            "name": display_name,
            "values": axis_values[axis_key],
            "entries": [{"value": axis_value} for axis_value in axis_values[axis_key]],
        }
        for axis_key, display_name in axis_parts
    ]


def _variant_query_url(
    page_url: str, *, query_key: str, query_value: str
) -> str | None:
    normalized_key = text_or_none(query_key)
    normalized_value = text_or_none(query_value)
    if not normalized_key or not normalized_value:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != normalized_key
    ]
    query_pairs.append((normalized_key, normalized_value))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))


def _iter_variant_mapping_payloads(
    value: Any, *, depth: int = 0, limit: int = 8
) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("options"), list):
            matches.append(value)
        for item in value.values():
            matches.extend(
                _iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit)
            )
    elif isinstance(value, list):
        for item in value[:25]:
            matches.extend(
                _iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit)
            )
    return matches


def _state_variant_targets(
    js_state_objects: dict[str, Any] | None,
    *,
    page_url: str,
) -> tuple[
    dict[str, dict[str, dict[str, object]]],
    dict[tuple[tuple[str, str], ...], dict[str, object]],
]:
    axis_targets: dict[str, dict[str, dict[str, object]]] = {}
    combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]] = {}
    if not isinstance(js_state_objects, dict):
        return axis_targets, combo_targets
    mapping_row_id_keys = (
        "productId",
        "product_id",
        "variantId",
        "variant_id",
        "sku",
        "id",
    )
    url_keys = ("url", "href", "productUrl", "product_url", "targetUrl", "target_url")
    for payload in _iter_variant_mapping_payloads(js_state_objects):
        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            continue
        option_definitions: list[dict[str, object]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                continue
            axis_field = text_or_none(
                option.get("id") or option.get("key") or option.get("name")
            )
            axis_key = normalized_variant_axis_key(option.get("label") or axis_field)
            option_list = (
                option.get("optionList")
                if isinstance(option.get("optionList"), list)
                else None
            )
            if not axis_field or not axis_key or not option_list:
                continue
            value_by_id: dict[str, str] = {}
            for item in option_list:
                if not isinstance(item, dict):
                    continue
                option_id = text_or_none(item.get("id") or item.get("value"))
                option_value = text_or_none(
                    item.get("title") or item.get("label") or item.get("value")
                )
                if (
                    option_id
                    and option_value
                    and not _variant_option_value_is_noise(option_value)
                ):
                    value_by_id[option_id] = option_value
            if value_by_id:
                option_definitions.append(
                    {
                        "axis_field": axis_field,
                        "axis_key": axis_key,
                        "value_by_id": value_by_id,
                    }
                )
        if not option_definitions:
            continue
        mapping_lists = [
            item
            for item in payload.values()
            if isinstance(item, list)
            and item
            and all(isinstance(row, dict) for row in item)
        ]
        for mapping_rows in mapping_lists:
            for mapping_row in mapping_rows:
                option_values: dict[str, str] = {}
                for option_definition in option_definitions:
                    axis_field = str(option_definition["axis_field"])
                    axis_key = str(option_definition["axis_key"])
                    mapping_value_by_id = _object_dict(
                        option_definition.get("value_by_id")
                    )
                    option_id = text_or_none(mapping_row.get(axis_field))
                    mapped_option_value = mapping_value_by_id.get(option_id or "")
                    if mapped_option_value:
                        option_values[axis_key] = str(mapped_option_value)
                if not option_values:
                    continue
                row_metadata: dict[str, object] = {}
                explicit_url = next(
                    (
                        text_or_none(mapping_row.get(key))
                        for key in url_keys
                        if text_or_none(mapping_row.get(key))
                    ),
                    None,
                )
                if explicit_url:
                    from app.services.field_value_core import absolute_url

                    row_metadata["url"] = absolute_url(page_url, explicit_url)
                for key in mapping_row_id_keys:
                    raw_value = text_or_none(mapping_row.get(key))
                    if not raw_value:
                        continue
                    row_metadata.setdefault("variant_id", raw_value)
                    if "url" not in row_metadata:
                        inferred_url = _variant_query_url(
                            page_url,
                            query_key=key,
                            query_value=raw_value,
                        )
                        if inferred_url:
                            row_metadata["url"] = inferred_url
                    break
                if not row_metadata:
                    continue
                if len(option_values) == 1:
                    axis_key, option_value = next(iter(option_values.items()))
                    axis_targets.setdefault(axis_key, {}).setdefault(
                        option_value, {}
                    ).update(row_metadata)
                combo_targets[tuple(sorted(option_values.items()))] = row_metadata
    return axis_targets, combo_targets


def _extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    option_groups: list[dict[str, object]] = []
    for select in iter_variant_select_groups(soup):
        raw_option_values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
        ]
        cleaned_name = resolve_variant_group_name(
            select
        ) or infer_variant_group_name_from_values(raw_option_values)
        inferred_name = infer_variant_group_name_from_values(raw_option_values)
        if inferred_name and normalized_variant_axis_key(cleaned_name) != inferred_name:
            cleaned_name = inferred_name
        if not cleaned_name:
            continue
        option_entries: list[dict[str, object]] = []
        axis_key = normalized_variant_axis_key(cleaned_name)
        select_options = list(select.find_all("option"))
        for option_index, option in enumerate(select_options):
            cleaned_value = text_or_none(
                coerce_field_value(
                    axis_key if axis_key in {"color", "size"} else "size",
                    option.get_text(" ", strip=True),
                    page_url,
                )
            ) or clean_text(option.get_text(" ", strip=True))
            cleaned_value = _strip_variant_option_value_suffix_noise(cleaned_value)
            raw_value_attr = text_or_none(option.get("value"))
            if (
                not cleaned_value
                or _variant_option_value_is_noise(cleaned_value)
                or (
                    raw_value_attr is not None
                    and raw_value_attr.lower() in {"select", "choose"}
                )
            ):
                continue
            entry: dict[str, object] = {"value": cleaned_value}
            if _node_attr_is_truthy(option, "selected", "aria-selected"):
                entry["selected"] = True
            variant_url = _variant_option_url(
                container=select,
                node=option,
                label_node=None,
                page_url=page_url,
            )
            if variant_url:
                entry["url"] = variant_url
            option_entries.append(entry)
        deduped_values = list(
            dict.fromkeys(
                str(entry["value"])
                for entry in option_entries
                if text_or_none(entry.get("value"))
            )
        )
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": cleaned_name,
                    "values": deduped_values,
                    "entries": option_entries,
                }
            )

    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(container, page_url=page_url)
        deduped_values = [
            str(entry["value"])
            for entry in option_entries
            if text_or_none(entry.get("value"))
        ]
        inferred_name = infer_variant_group_name_from_values(deduped_values)
        if (
            inferred_name
            and normalized_variant_axis_key(cleaned_name) != inferred_name
            and not variant_axis_name_is_semantic(cleaned_name)
        ):
            cleaned_name = inferred_name
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": cleaned_name,
                    "values": deduped_values,
                    "entries": option_entries,
                }
            )

    expanded_option_groups: list[dict[str, object]] = []
    for group in option_groups:
        compound_groups = _expand_compound_option_group(group)
        if compound_groups:
            expanded_option_groups.extend(compound_groups)
            continue
        expanded_option_groups.append(group)

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in expanded_option_groups:
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(
            axis_key, {"name": name or axis_key, "values": [], "entries": {}}
        )
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        existing_values = _object_list(merged.get("values"))
        merged["values"] = list(dict.fromkeys([*existing_values, *values]))
        merged_entries = merged.setdefault("entries", {})
        if not isinstance(merged_entries, dict):
            merged_entries = {}
            merged["entries"] = merged_entries
        for group_entry in _object_list(group.get("entries")):
            if not isinstance(group_entry, dict):
                continue
            value = clean_text(group_entry.get("value"))
            if not value:
                continue
            existing = _object_dict(merged_entries.get(value, {"value": value}))
            availability = text_or_none(group_entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if group_entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = group_entry.get("stock_quantity")
            if group_entry.get("selected"):
                existing["selected"] = True
            if group_entry.get("url") not in (None, "", [], {}) and existing.get(
                "url"
            ) in (None, "", [], {}):
                existing["url"] = group_entry.get("url")
            if group_entry.get("variant_id") not in (None, "", [], {}) and existing.get(
                "variant_id"
            ) in (None, "", [], {}):
                existing["variant_id"] = group_entry.get("variant_id")
            merged_entries[value] = existing
    for group in merged_groups.values():
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        merged_entries = _object_dict(group.get("entries"))
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list(merged_entries.values()),
            }
        )
        if len(deduped_groups) >= 4:
            break

    if not deduped_groups:
        return {}

    state_axis_targets, state_combo_targets = _state_variant_targets(
        js_state_objects,
        page_url=page_url,
    )
    record: dict[str, object] = {}
    axis_values_by_name: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = [str(value) for value in _object_list(group.get("values"))]
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        axis_values_by_name[axis_key] = values
        axis_option_metadata[axis_key] = {
            clean_text(entry.get("value")): {
                key: entry.get(key)
                for key in (
                    "availability",
                    "selected",
                    "stock_quantity",
                    "url",
                    "variant_id",
                )
                if entry.get(key) not in (None, "", [], {})
            }
            for entry in _object_list(group.get("entries"))
            if isinstance(entry, dict)
            if clean_text(entry.get("value"))
        }
        for option_value, state_metadata in dict(
            state_axis_targets.get(axis_key) or {}
        ).items():
            merged_metadata = axis_option_metadata[axis_key].setdefault(
                option_value, {}
            )
            for key in ("url", "variant_id"):
                if state_metadata.get(key) not in (
                    None,
                    "",
                    [],
                    {},
                ) and merged_metadata.get(key) in (None, "", [], {}):
                    merged_metadata[key] = state_metadata[key]
        axis_order.append((axis_key, name, values))
    if not axis_values_by_name:
        return {}

    variants: list[dict[str, object]] = []
    axis_names = [axis_key for axis_key, _label, _values in axis_order]
    axis_value_lists = [values for _axis_key, _label, values in axis_order]
    for combo in product(*axis_value_lists):
        option_values = {
            axis_name: value
            for axis_name, value in zip(axis_names, combo, strict=False)
            if clean_text(value)
        }
        if not option_values:
            continue
        variant: dict[str, object] = {
            "option_values": option_values,
        }
        for axis_name, value in option_values.items():
            variant[axis_name] = value
        combo_metadata = state_combo_targets.get(
            tuple(sorted(option_values.items())), {}
        )
        for key in ("url", "variant_id"):
            if combo_metadata.get(key) not in (None, "", [], {}):
                variant[key] = combo_metadata[key]
        if len(axis_names) == 1:
            axis_key = axis_names[0]
            option_metadata = axis_option_metadata.get(axis_key, {}).get(
                str(combo[0]), {}
            )
            availability = text_or_none(option_metadata.get("availability"))
            if availability:
                variant["availability"] = availability
            if option_metadata.get("stock_quantity") not in (None, "", [], {}):
                variant["stock_quantity"] = option_metadata.get("stock_quantity")
            for key in ("url", "variant_id"):
                if option_metadata.get(key) not in (None, "", [], {}):
                    variant[key] = option_metadata.get(key)
        variants.append(variant)

    selectable_axes, single_value_attributes = split_variant_axes(
        axis_values_by_name,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = (
        resolve_variants(selectable_axes or axis_values_by_name, variants)
        if variants
        else []
    )
    active_variant = select_variant(resolved_variants, page_url=page_url)
    selected_option_values = {
        axis_name: option_value
        for axis_name, option_value in (
            (
                axis_name,
                next(
                    (
                        value
                        for value, metadata in axis_option_metadata.get(
                            axis_name, {}
                        ).items()
                        if metadata.get("selected")
                    ),
                    None,
                ),
            )
            for axis_name in axis_names
        )
        if option_value
    }
    if selected_option_values:
        active_variant = next(
            (
                variant
                for variant in resolved_variants
                if variant.get("option_values") == selected_option_values
            ),
            active_variant,
        )
    for axis_name, value in single_value_attributes.items():
        record.setdefault(axis_name, value)
    if resolved_variants:
        flat_variants = flatten_variants_for_public_output(
            resolved_variants,
            page_url=page_url,
        )
        if flat_variants:
            record["variants"] = flat_variants
            record["variant_count"] = len(flat_variants)
        if active_variant:
            if record.get("availability") in (None, "", [], {}):
                selected_availability = text_or_none(active_variant.get("availability"))
                if selected_availability:
                    record["availability"] = selected_availability
    return record


def _backfill_variants_from_dom_if_missing(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> None:
    existing_variants = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    existing_has_axis = any(
        row.get("color") not in (None, "", [], {})
        or row.get("size") not in (None, "", [], {})
        for row in existing_variants
    )
    if existing_variants and existing_has_axis:
        return
    if not variant_dom_cues_present(soup):
        return
    dom_variants = _extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    dom_variant_rows = [
        row for row in list(dom_variants.get("variants") or []) if isinstance(row, dict)
    ]
    if dom_variant_rows:
        existing_by_key: dict[str, dict[str, Any]] = {}
        existing_by_index: dict[int, dict[str, Any]] = {}
        for index, row in enumerate(existing_variants):
            row_key = text_or_none(row.get("variant_id")) or text_or_none(
                row.get("url")
            )
            if row_key:
                # Preserve the first occurrence so duplicate variant_id/url
                # keys cannot overwrite earlier rows and merge unrelated variants.
                existing_by_key.setdefault(row_key, row)
            existing_by_index[index] = row
        index_fallback_allowed = bool(existing_variants) and (
            len(dom_variant_rows) == len(existing_variants)
            or abs(len(dom_variant_rows) - len(existing_variants)) <= 1
        )
        merged_rows: list[dict[str, Any]] = []
        for index, dom_row in enumerate(dom_variant_rows):
            dom_key = text_or_none(dom_row.get("variant_id")) or text_or_none(
                dom_row.get("url")
            )
            existing_row = existing_by_key.get(dom_key or "") if dom_key else None
            if existing_row is None and index_fallback_allowed:
                existing_row = existing_by_index.get(index)
            merged_rows.append(
                merge_variant_pair(dom_row, existing_row)
                if isinstance(existing_row, dict)
                else dom_row
            )
        record["variants"] = merged_rows
        record["variant_count"] = len(merged_rows)
    currency = text_or_none(record.get("currency"))
    price = text_or_none(record.get("price"))
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if any(
        isinstance(variant, dict) and variant.get("price") not in (None, "", [], {})
        for variant in variants
    ):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if price:
            variant["price"] = price
        if currency and variant.get("currency") in (None, "", [], {}):
            variant["currency"] = currency


backfill_variants_from_dom_if_missing = _backfill_variants_from_dom_if_missing
extract_variants_from_dom = _extract_variants_from_dom
variant_option_value_is_noise = _variant_option_value_is_noise
