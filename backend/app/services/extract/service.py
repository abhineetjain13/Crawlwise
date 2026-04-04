# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from lxml import etree, html as lxml_html

from app.services.discover.service import DiscoveryManifest
from app.services.pipeline_config import (
    CANDIDATE_GENERIC_CATEGORY_VALUES,
    CANDIDATE_GENERIC_TITLE_VALUES,
    CANDIDATE_PLACEHOLDER_VALUES,
    DIMENSION_KEYWORDS,
    DOM_PATTERNS,
    FEATURE_SECTION_ALIASES,
    FIELD_ALIASES,
    SEMANTIC_AGGREGATE_SEPARATOR,
)
from app.services.requested_field_policy import expand_requested_fields, normalize_requested_field
from app.services.semantic_detail_extractor import extract_semantic_detail_data, resolve_requested_field_values
from app.services.knowledge_base.store import get_canonical_fields, get_domain_mapping, get_selector_defaults
from app.services.xpath_service import build_absolute_xpath, extract_selector_value

GENERIC_ALIAS_KEYS = {"name", "type", "label", "id"}
TRUSTED_BRAND_SOURCES = {
    "contract_xpath",
    "contract_regex",
    "adapter",
    "json_ld",
    "microdata",
    "selector",
    "dom",
    "semantic_spec",
    "semantic_section",
}
PRODUCT_CONTEXT_KEYS = {
    "product",
    "productdata",
    "product_data",
    "productdetails",
    "product_details",
    "item",
    "variant",
    "offer",
    "offers",
    "sku",
    "brand",
    "manufacturer",
    "title",
    "name",
    "description",
    "price",
    "image",
}


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    manifest: DiscoveryManifest,
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Extract candidate values for each target field.

    Sources are checked in priority order (adapter > network > JSON-LD > microdata > selectors > DOM).

    Returns:
        (candidates, source_trace) — candidates maps field -> list of {value, source}
    """
    soup = BeautifulSoup(html, "html.parser")
    tree = _build_xpath_tree(html)
    candidates: dict[str, list[dict]] = {}
    source_trace: dict[str, list[dict]] = {}
    target_fields = set(get_canonical_fields(surface)) | set(expand_requested_fields(additional_fields))
    domain = _domain(url)
    contract_by_field = _index_extraction_contract(extraction_contract or [])
    semantic = extract_semantic_detail_data(html, requested_fields=sorted(target_fields))

    for field_name in target_fields:
        rows: list[dict] = []

        # 0. User-provided extraction contract (highest precedence)
        contract_rule = contract_by_field.get(field_name)
        if contract_rule:
            xpath_value = _extract_xpath_value(tree, contract_rule.get("xpath", ""))
            if xpath_value:
                rows.append({
                    "value": xpath_value,
                    "source": "contract_xpath",
                    "xpath": contract_rule.get("xpath"),
                    "css_selector": None,
                    "regex": None,
                    "sample_value": xpath_value,
                })
            regex_value = _extract_regex_value(html, contract_rule.get("regex", ""))
            if regex_value:
                rows.append({
                    "value": regex_value,
                    "source": "contract_regex",
                    "xpath": None,
                    "css_selector": None,
                    "regex": contract_rule.get("regex"),
                    "sample_value": regex_value,
                })

        # 1. Adapter data (rank 1)
        for record in manifest.adapter_data:
            if isinstance(record, dict) and field_name in record and record[field_name]:
                rows.append({"value": record[field_name], "source": "adapter"})

        # 2. Network payloads (rank 2)
        for payload in manifest.network_payloads:
            body = payload.get("body", {})
            if isinstance(body, (dict, list)):
                val = _coerce_candidate_value(_deep_get_aliases(body, field_name), field_name=field_name)
                if val is not None:
                    rows.append({"value": val, "source": "network_intercept"})

        # 3. Hydrated app state / __NEXT_DATA__ (rank 3)
        for state in manifest._hydrated_states:
            val = _coerce_candidate_value(_deep_get_aliases(state, field_name), field_name=field_name)
            if val is not None:
                rows.append({"value": val, "source": "hydrated_state"})
                break
        for payload in manifest.embedded_json:
            val = _coerce_candidate_value(_deep_get_aliases(payload, field_name), field_name=field_name)
            if val is not None:
                rows.append({"value": val, "source": "embedded_json"})
                break
        if manifest.next_data:
            val = _coerce_candidate_value(_deep_get_aliases(manifest.next_data, field_name), field_name=field_name)
            if val is not None:
                rows.append({"value": val, "source": "next_data"})

        structured_manifest_row = _structured_manifest_candidate(manifest, field_name)
        if structured_manifest_row:
            rows.append(structured_manifest_row)

        # 4. JSON-LD (rank 4)
        for payload in manifest.json_ld:
            if isinstance(payload, dict):
                val = _coerce_candidate_value(_deep_get_aliases(payload, field_name), field_name=field_name)
                if val is not None:
                    rows.append({"value": val, "source": "json_ld"})

        # 5. Microdata/RDFa (rank 5)
        for item in manifest.microdata:
            if isinstance(item, dict):
                val = _coerce_candidate_value(_deep_get_aliases(item, field_name), field_name=field_name)
                if val is not None:
                    rows.append({"value": val, "source": "microdata"})

        # 6. Semantic sections/specifications extracted from page-local HTML
        semantic_rows = resolve_requested_field_values(
            [field_name],
            sections=semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {},
            specifications=semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {},
            promoted_fields=semantic.get("promoted_fields") if isinstance(semantic.get("promoted_fields"), dict) else {},
        )
        semantic_value = semantic_rows.get(field_name)
        if semantic_value not in (None, "", [], {}):
            rows.append({"value": semantic_value, "source": "semantic_section"})

        # 7. Saved domain selectors (rank 7)
        selectors = get_selector_defaults(domain, field_name)
        for selector in selectors:
            value, count, selector_used = extract_selector_value(
                html,
                css_selector=selector.get("css_selector"),
                xpath=selector.get("xpath"),
                regex=selector.get("regex"),
            )
            if value:
                rows.append({
                    "value": value,
                    "source": "selector",
                    "xpath": selector.get("xpath"),
                    "css_selector": selector.get("css_selector"),
                    "regex": selector.get("regex"),
                    "sample_value": selector.get("sample_value") or value,
                    "selector_used": selector_used,
                    "status": selector.get("status") or "validated",
                })

        # 8. Deterministic DOM patterns (rank 8)
        dom_row = _dom_pattern(soup, field_name)
        if dom_row:
            rows.append(dom_row)

        if rows:
            filtered_rows = _finalize_candidate_rows(field_name, rows)
            if filtered_rows:
                candidates[field_name] = filtered_rows
                source_trace[field_name] = filtered_rows

    dynamic_rows = _build_dynamic_semantic_rows(semantic)
    structured_rows = _build_dynamic_structured_rows(manifest)
    merged_dynamic_rows: dict[str, list[dict]] = {}
    for field_name, rows in structured_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in dynamic_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in merged_dynamic_rows.items():
        existing_rows = candidates.get(field_name, [])
        merged_rows = [*existing_rows, *rows]
        filtered_rows = _finalize_candidate_rows(field_name, merged_rows)
        if filtered_rows:
            candidates[field_name] = filtered_rows
            source_trace[field_name] = filtered_rows

    # Apply domain field mappings
    mappings = get_domain_mapping(domain, surface)
    return candidates, {"candidates": source_trace, "mapping_hint": mappings, "semantic": semantic}


def _dom_pattern(soup: BeautifulSoup, field_name: str) -> dict | None:
    """Try common DOM patterns for well-known fields."""
    selector_group = DOM_PATTERNS.get(field_name)
    if not selector_group:
        return None
    for selector in [part.strip() for part in str(selector_group).split(",") if part.strip()]:
        node = soup.select_one(selector)
        if not node:
            continue
        value = _extract_dom_node_value(node, field_name)
        if not value:
            continue
        return {
            "value": value,
            "source": "dom",
            "xpath": build_absolute_xpath(node),
            "css_selector": selector,
            "regex": None,
            "sample_value": value,
        }
    return None


def _extract_dom_node_value(node, field_name: str) -> str | None:
    value: str | None = None
    if node.name == "meta":
        value = node.get("content", "")
    elif field_name == "availability" and node.get("href"):
        value = node.get("href", "")
    elif field_name in ("apply_url", "image_url", "url") and node.get("href"):
        value = node.get("href", "")
    elif field_name == "image_url" and node.get("src"):
        value = node.get("src", "")
    else:
        value = node.get("content") or node.get_text(" ", strip=True)
    cleaned = str(value or "").strip()
    return cleaned or None


def _finalize_candidate_rows(field_name: str, rows: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not _candidate_allowed(field_name, row):
            continue
        value = _normalized_candidate_text(row.get("value"))
        source = str(row.get("source") or "").strip() or "candidate"
        key = (source, value)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(row)
    return filtered


def _candidate_allowed(field_name: str, row: dict) -> bool:
    source = str(row.get("source") or "").strip()
    value = _normalized_candidate_text(row.get("value"))
    if not value:
        return False
    lowered = value.lower()
    if lowered in CANDIDATE_PLACEHOLDER_VALUES and not row.get("preserve_visible"):
        return False
    if field_name == "title":
        if lowered in CANDIDATE_GENERIC_TITLE_VALUES:
            return False
        if len(value) < 4 or not re.search(r"[A-Za-z]", value):
            return False
    if field_name == "brand" and source not in TRUSTED_BRAND_SOURCES:
        return False
    if field_name == "category" and lowered in CANDIDATE_GENERIC_CATEGORY_VALUES:
        return False
    if field_name == "specifications" and ":" not in value:
        if lowered.startswith("check the details") or "general specifications" in lowered or "technical specifications" in lowered:
            return False
    return True


def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _deep_get(data: object, key: str, max_depth: int = 5) -> object | None:
    """Recursively search a nested dict for a key.

    When the same key appears at multiple depths, the longest string value wins.
    This prevents a short top-level description from shadowing a richer nested
    one (e.g. JSON-LD top-level description vs offers.description).
    """
    if max_depth <= 0:
        return None
    best: object | None = None

    def _collect(node: object, depth: int) -> None:
        nonlocal best
        if depth <= 0:
            return
        if isinstance(node, dict):
            if key in node:
                candidate = node[key]
                if candidate not in (None, "", [], {}):
                    # Prefer longer strings; fall back to first non-null for non-strings
                    if best is None:
                        best = candidate
                    elif isinstance(candidate, str) and isinstance(best, str):
                        if len(candidate) > len(best):
                            best = candidate
            for v in node.values():
                _collect(v, depth - 1)
        elif isinstance(node, list):
            for item in node:
                _collect(item, depth - 1)

    _collect(data, max_depth)
    return best


def _deep_get_aliases(data: object, field_name: str, max_depth: int = 5) -> object | None:
    aliases = [field_name, *FIELD_ALIASES.get(field_name, [])]
    seen: set[str] = set()
    for alias in aliases:
        key = str(alias or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if key in GENERIC_ALIAS_KEYS and key != field_name:
            result = _deep_get_generic_alias(data, field_name, key, max_depth)
        else:
            result = _deep_get(data, key, max_depth)
        if result not in (None, "", [], {}):
            return result
    return None


def _deep_get_generic_alias(
    data: object,
    field_name: str,
    alias: str,
    max_depth: int = 5,
    *,
    parent_key: str = "",
) -> object | None:
    if max_depth <= 0:
        return None
    if isinstance(data, dict):
        if alias in data and _looks_like_entity_context(data, field_name, parent_key):
            return data[alias]
        for key, value in data.items():
            result = _deep_get_generic_alias(
                value,
                field_name,
                alias,
                max_depth - 1,
                parent_key=str(key or ""),
            )
            if result not in (None, "", [], {}):
                return result
    elif isinstance(data, list):
        for item in data:
            result = _deep_get_generic_alias(item, field_name, alias, max_depth - 1, parent_key=parent_key)
            if result not in (None, "", [], {}):
                return result
    return None


def _looks_like_entity_context(data: dict, field_name: str, parent_key: str) -> bool:
    parent = str(parent_key or "").strip().lower()
    if parent in PRODUCT_CONTEXT_KEYS:
        return True
    lowered_keys = {str(key or "").strip().lower() for key in data.keys()}
    contextual_keys = lowered_keys - GENERIC_ALIAS_KEYS
    if contextual_keys & PRODUCT_CONTEXT_KEYS:
        return True
    if field_name == "title":
        return bool(contextual_keys & {"sku", "brand", "price", "description", "offers", "image", "url"})
    if field_name == "category":
        return bool(contextual_keys & {"title", "sku", "brand", "price"})
    if field_name == "sku":
        return bool(contextual_keys & {"title", "brand", "price"})
    return False


def _coerce_candidate_value(value: object, *, field_name: str = "") -> object | None:
    """Coerce an extracted value to a scalar or pipe-joined string.

    For ``image_url``, a list collapses to the *first* URL (primary image).
    For ``additional_images``, the full list is pipe-joined so all URLs are
    preserved and visible in the intelligence tab.
    All other list fields are also pipe-joined (deduped, order-preserving).
    """
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        scalars: list[str] = []
        for item in value:
            coerced = _coerce_candidate_value(item)
            if isinstance(coerced, (str, int, float, bool)):
                text = str(coerced).strip()
                if text:
                    scalars.append(text)
        if not scalars:
            return None
        # Primary image: collapse to first URL only
        if field_name == "image_url":
            return scalars[0]
        return " | ".join(dict.fromkeys(scalars))
    if isinstance(value, dict):
        for key in ("value", "text", "content", "description", "sentence", "summary", "title", "name", "label"):
            candidate = value.get(key)
            coerced = _coerce_candidate_value(candidate)
            if coerced is not None:
                return coerced
        return None
    return None


def _structured_manifest_candidate(manifest: DiscoveryManifest, field_name: str) -> dict | None:
    if field_name not in {"specifications", "dimensions"}:
        return None
    sources: list[tuple[str, object]] = [("next_data", manifest.next_data)]
    sources.extend(("hydrated_state", payload) for payload in manifest._hydrated_states)
    sources.extend(("embedded_json", payload) for payload in manifest.embedded_json)
    sources.extend(
        ("network_intercept", payload.get("body"))
        for payload in manifest.network_payloads
        if isinstance(payload, dict)
    )
    for source, payload in sources:
        value = _extract_structured_field_value(payload, field_name)
        if value:
            return {"value": value, "source": source}
    return None


def _build_dynamic_semantic_rows(semantic: dict) -> dict[str, list[dict]]:
    sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    specifications = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}
    aggregates = semantic.get("aggregates") if isinstance(semantic.get("aggregates"), dict) else {}
    table_groups = semantic.get("table_groups") if isinstance(semantic.get("table_groups"), list) else []
    rows: dict[str, list[dict]] = {}

    for field_name, value in specifications.items():
        normalized = normalize_requested_field(field_name)
        if not normalized or value in (None, "", [], {}):
            continue
        rows.setdefault(normalized, []).append({"value": value, "source": "semantic_spec"})

    for group in table_groups:
        if not isinstance(group, dict):
            continue
        group_label = _normalized_candidate_text(group.get("title")) or _normalized_candidate_text(group.get("caption"))
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            normalized = normalize_requested_field(row.get("normalized_key") or row.get("label"))
            value = row.get("value")
            if not normalized or value in (None, "", [], {}):
                continue
            rows.setdefault(normalized, []).append({
                "value": value,
                "source": "semantic_spec",
                "display_label": _normalized_candidate_text(row.get("label")) or normalized,
                "group_label": group_label or None,
                "href": _normalized_candidate_text(row.get("href")) or None,
                "preserve_visible": bool(row.get("preserve_visible")),
                "row_index": row.get("row_index"),
                "table_index": group.get("table_index"),
            })

    for aggregate_field in ("specifications", "dimensions"):
        value = aggregates.get(aggregate_field)
        if value not in (None, "", [], {}):
            rows.setdefault(aggregate_field, []).append({"value": value, "source": "semantic_spec"})

    feature_blocks = [
        body
        for key, body in sections.items()
        if key in FEATURE_SECTION_ALIASES and body not in (None, "", [], {})
    ]
    if feature_blocks:
        rows.setdefault("features", []).append({
            "value": SEMANTIC_AGGREGATE_SEPARATOR.join(feature_blocks),
            "source": "semantic_section",
        })
    return rows


def _build_dynamic_structured_rows(manifest: DiscoveryManifest) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for source, payload in _structured_manifest_sources(manifest):
        spec_map = _extract_structured_spec_map(payload)
        if not spec_map:
            continue
        spec_lines = [f"{label}: {value}" for label, value in spec_map.items()]
        if spec_lines:
            rows.setdefault("specifications", []).append({
                "value": SEMANTIC_AGGREGATE_SEPARATOR.join(spec_lines),
                "source": source,
            })
        dimension_lines = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        if dimension_lines:
            rows.setdefault("dimensions", []).append({
                "value": SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_lines),
                "source": source,
            })
        for field_name, value in spec_map.items():
            normalized = normalize_requested_field(field_name)
            if not normalized:
                continue
            rows.setdefault(normalized, []).append({"value": value, "source": source})
    return rows


def _extract_structured_field_value(payload: object, field_name: str) -> str | None:
    spec_map = _extract_structured_spec_map(payload)
    if not spec_map:
        return None
    if field_name == "specifications":
        return SEMANTIC_AGGREGATE_SEPARATOR.join(f"{label}: {value}" for label, value in spec_map.items()) or None
    if field_name == "dimensions":
        dimension_pairs = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        return SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_pairs) or None
    return spec_map.get(normalize_requested_field(field_name)) or spec_map.get(field_name)


def _find_key_values(payload: object, key: str, *, max_depth: int) -> list[object]:
    if max_depth <= 0 or payload in (None, "", [], {}):
        return []
    matches: list[object] = []
    if isinstance(payload, dict):
        for current_key, value in payload.items():
            if current_key == key:
                matches.append(value)
            matches.extend(_find_key_values(value, key, max_depth=max_depth - 1))
    elif isinstance(payload, list):
        for item in payload[:20]:
            matches.extend(_find_key_values(item, key, max_depth=max_depth - 1))
    return matches


def _structured_manifest_sources(manifest: DiscoveryManifest) -> list[tuple[str, object]]:
    sources: list[tuple[str, object]] = [("next_data", manifest.next_data)]
    sources.extend(("hydrated_state", payload) for payload in manifest._hydrated_states)
    sources.extend(("embedded_json", payload) for payload in manifest.embedded_json)
    sources.extend(
        ("network_intercept", payload.get("body"))
        for payload in manifest.network_payloads
        if isinstance(payload, dict)
    )
    return sources


def _extract_structured_spec_map(payload: object) -> dict[str, str]:
    groups = _find_key_values(payload, "specificationGroups", max_depth=7)
    structured: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for entry in group[:8]:
            if not isinstance(entry, dict):
                continue
            specs = entry.get("specifications")
            if not isinstance(specs, list):
                continue
            for row in specs[:24]:
                if not isinstance(row, dict):
                    continue
                title = normalize_requested_field(_normalized_candidate_text(row.get("title")))
                content = _normalized_candidate_text(row.get("content"))
                if not title or not content:
                    continue
                structured.setdefault(title, content)
    return structured


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()


def _build_xpath_tree(document_html: str):
    try:
        return lxml_html.fromstring(document_html)
    except (etree.ParserError, ValueError):
        return None


def _index_extraction_contract(extraction_contract: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in extraction_contract:
        field_name = str(row.get("field_name", "")).strip()
        if field_name and field_name not in indexed:
            indexed[field_name] = row
    return indexed


def _extract_xpath_value(tree, xpath: str) -> str | None:
    if tree is None or not xpath.strip():
        return None
    try:
        results = tree.xpath(xpath)
    except etree.XPathError:
        return None
    if not results:
        return None
    first = results[0]
    if isinstance(first, str):
        return first.strip() or None
    if hasattr(first, "text_content"):
        value = first.text_content().strip()
        return value or None
    value = str(first).strip()
    return value or None


def _extract_regex_value(document_html: str, pattern: str) -> str | None:
    if not pattern.strip():
        return None
    try:
        match = re.search(pattern, document_html, re.DOTALL)
    except re.error:
        return None
    if not match:
        return None
    if match.groups():
        return next((group for group in match.groups() if group), None)
    return match.group(0)
