# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import json
import re
from functools import lru_cache
from json import loads as parse_json
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from lxml import etree, html as lxml_html

from app.services.pipeline_config import (
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_GENERIC_CATEGORY_VALUES,
    CANDIDATE_GENERIC_TITLE_VALUES,
    CANDIDATE_IDENTIFIER_TOKENS,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_PLACEHOLDER_VALUES,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_SALARY_TOKENS,
    CANDIDATE_PROMO_ONLY_TITLE_PATTERN,
    CANDIDATE_RATING_TOKENS,
    CANDIDATE_REVIEW_COUNT_TOKENS,
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
    CANDIDATE_URL_SUFFIXES,
    DIMENSION_KEYWORDS,
    DOM_PATTERNS,
    DYNAMIC_FIELD_NAME_DROP_TOKENS,
    DYNAMIC_FIELD_NAME_MAX_TOKENS,
    FIELD_ALIASES,
    FIELD_POLLUTION_RULES,
    GA_DATA_LAYER_KEYS,
    JSONLD_NON_PRODUCT_BLOCK_TYPES,
    JSONLD_STRUCTURAL_KEYS,
    JSONLD_TYPE_NOISE,
    MAX_CANDIDATES_PER_FIELD,
    NESTED_NON_PRODUCT_KEYS,
    PRICE_REGEX,
    PRODUCT_IDENTITY_FIELDS,
    REQUESTED_FIELD_ALIASES,
    SALARY_RANGE_REGEX,
    SEMANTIC_AGGREGATE_SEPARATOR,
    SOURCE_RANKING,
)
from app.services.extract.source_parsers import parse_page_sources
from app.services.extract.signal_inventory import (
    build_signal_inventory,
    classify_page_type,
)
from app.services.requested_field_policy import (
    expand_requested_fields,
    normalize_requested_field,
)
from app.services.semantic_detail_extractor import (
    extract_semantic_detail_data,
    resolve_requested_field_values,
)
from app.services.knowledge_base.store import (
    get_canonical_fields,
    get_domain_mapping,
    get_selector_defaults,
)
from app.services.normalizers import validate_value
from app.services.xpath_service import build_absolute_xpath, extract_selector_value

_UI_NOISE_TOKEN_RE = (
    re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_NOISE_TOKEN_PATTERN
    else None
)
_UI_ICON_TOKEN_RE = (
    re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_ICON_TOKEN_PATTERN
    else None
)
_SCRIPT_NOISE_RE = (
    re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE)
    if CANDIDATE_SCRIPT_NOISE_PATTERN
    else None
)
_PROMO_ONLY_TITLE_RE = (
    re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE)
    if CANDIDATE_PROMO_ONLY_TITLE_PATTERN
    else None
)
_NON_EMPTY_UI_NOISE_PHRASES = [phrase for phrase in CANDIDATE_UI_NOISE_PHRASES if phrase]
_UI_NOISE_PHRASES_RE = (
    re.compile(
        r"\b(?:"
        + "|".join(re.escape(phrase) for phrase in _NON_EMPTY_UI_NOISE_PHRASES)
        + r")\b",
        re.IGNORECASE,
    )
    if _NON_EMPTY_UI_NOISE_PHRASES
    else None
)
_DYNAMIC_NUMERIC_FIELD_RE = re.compile(r"\d+(?:[_-]\d+)*?")
_SALARY_MONEY_RE = re.compile(
    r"(?<!\w)(?:[$€£₹]\s*\d[\d,.]*|\b(?:USD|EUR|GBP|INR)\s*\d[\d,.]*|\d[\d,.]*\s*(?:USD|EUR|GBP|INR)\b)",
    re.IGNORECASE,
)
_COLOR_VARIANT_COUNT_RE = re.compile(r"^\d+\s+colors?\b", re.IGNORECASE)
_TITLE_NOISE_PHRASES = (
    "cookie preferences",
    "privacy policy",
    "terms of service",
    "sign in",
    "log in",
    "my account",
    "add to cart",
    "shopping cart",
    "department navigation",
)
_CATEGORY_NOISE_PHRASES = (
    "breadcrumb",
    "view all",
    "filter by",
    "sort by",
    "shop all",
)
_AVAILABILITY_NOISE_PHRASES = (
    "select options",
    "choose options",
    "add to cart",
    "quantity",
    "wishlist",
)


def _looks_like_ga_data_layer(payload: object) -> bool:
    """Return True if the payload looks like a Google Analytics data layer push."""
    if not isinstance(payload, dict):
        return False
    return bool(GA_DATA_LAYER_KEYS & set(payload.keys()))


def _dynamic_field_name_is_valid(normalized: str) -> bool:
    """Reject field names that are noise: single chars, sentence-like, or JSON-LD types."""
    if len(normalized) <= 1 or len(normalized) > 60:
        return False
    if not re.fullmatch(r"[a-z][a-z0-9_]*", normalized):
        return False
    if normalized in JSONLD_TYPE_NOISE:
        return False
    tokens = [token for token in normalized.split("_") if token]
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return False
    dropped_tokens = sum(
        1 for token in tokens if token in _DYNAMIC_FIELD_NAME_DROP_TOKENS
    )
    if dropped_tokens >= 2 and dropped_tokens >= len(tokens) - 1:
        return False
    # 5+ underscores suggests a sentence heading, not a spec label
    if normalized.count("_") >= 5:
        return False
    return True


_DYNAMIC_FIELD_NAME_DROP_TOKENS = DYNAMIC_FIELD_NAME_DROP_TOKENS
_DYNAMIC_FIELD_NAME_MAX_TOKENS = DYNAMIC_FIELD_NAME_MAX_TOKENS


def _collect_candidates(
    url: str,
    surface: str,
    html: str,
    soup: BeautifulSoup,
    tree,
    page_sources: dict,
    adapter_records: list[dict],
    network_payloads: list[dict],
    target_fields: list[str],
    canonical_target_fields: set[str],
    contract_by_field: dict,
    semantic: dict,
    label_value_text_sources: dict,
) -> dict[str, list[dict]]:
    """Gather candidate values from all sources without filtering.
    
    Implements extraction hierarchy with first-match wins:
    1. Extraction contract
    2. Platform adapter
    3. dataLayer
    4. Network intercept
    5. JSON-LD
    6. Embedded JSON
    7. DOM selectors
    8. Semantic extraction
    9. Text patterns
    
    Returns: {field_name: [candidate_rows]}
    """
    candidates: dict[str, list[dict]] = {}
    domain = _domain(url)
    
    # Extract all page sources
    next_data = page_sources.get("next_data")
    hydrated_states = page_sources.get("hydrated_states") or []
    embedded_json = page_sources.get("embedded_json") or []
    open_graph = page_sources.get("open_graph") or {}
    json_ld = page_sources.get("json_ld") or []
    microdata = page_sources.get("microdata") or []
    datalayer = page_sources.get("datalayer") or {}
    
    for field_name in target_fields:
        rows: list[dict] = []
        
        # 1. Explicit contracts remain the highest-precedence override
        contract_rule = contract_by_field.get(field_name)
        if contract_rule:
            xpath_value = _extract_xpath_value(tree, contract_rule.get("xpath", ""))
            if xpath_value:
                rows.append(
                    {
                        "value": xpath_value,
                        "source": "contract_xpath",
                        "xpath": contract_rule.get("xpath"),
                        "css_selector": None,
                        "regex": None,
                        "sample_value": xpath_value,
                    }
                )
            regex_value = _extract_regex_value(html, contract_rule.get("regex", ""))
            if regex_value:
                rows.append(
                    {
                        "value": regex_value,
                        "source": "contract_regex",
                        "xpath": None,
                        "css_selector": None,
                        "regex": contract_rule.get("regex"),
                        "sample_value": regex_value,
                    }
                )
            if rows:
                candidates[field_name] = rows
                continue
        
        # 2. Platform adapter result
        for record in adapter_records:
            if isinstance(record, dict) and field_name in record and record[field_name]:
                rows.append({"value": record[field_name], "source": "adapter"})
        if rows:
            candidates[field_name] = rows
            continue
        
        # 3. dataLayer (GTM ecommerce data)
        if datalayer and field_name in datalayer and datalayer[field_name]:
            rows.append({"value": datalayer[field_name], "source": "datalayer"})
        if rows:
            candidates[field_name] = rows
            continue
        
        # 4. XHR / JSON API payloads
        for payload in network_payloads:
            if not isinstance(payload, dict):
                continue
            payload_url = str(payload.get("url") or "").lower()
            if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
                continue
            body = payload.get("body", {})
            if isinstance(body, (dict, list)):
                _append_source_candidates(
                    rows, field_name, body, "network_intercept", base_url=url
                )
        if rows:
            candidates[field_name] = rows
            continue
        
        # 5. JSON-LD
        for payload in json_ld:
            if isinstance(payload, dict):
                if _should_skip_jsonld_block(payload, field_name):
                    continue
                _append_source_candidates(
                    rows, field_name, payload, "json_ld", base_url=url
                )
        if rows:
            candidates[field_name] = rows
            continue
        
        # 6. __NEXT_DATA__ / hydrated client state
        for payload in embedded_json:
            _append_source_candidates(
                rows, field_name, payload, "embedded_json", base_url=url
            )
        if next_data:
            _append_source_candidates(
                rows, field_name, next_data, "next_data", base_url=url
            )
        for state in hydrated_states:
            _append_source_candidates(
                rows, field_name, state, "hydrated_state", base_url=url
            )
        rows.extend(
            _structured_source_candidates(
                field_name,
                next_data=next_data,
                hydrated_states=hydrated_states,
                embedded_json=embedded_json,
                network_payloads=network_payloads,
            )
        )
        if rows:
            candidates[field_name] = rows
            continue
        
        # 7. DOM selectors
        selectors = get_selector_defaults(domain, field_name)
        for selector in selectors:
            value, _, selector_used = extract_selector_value(
                html,
                css_selector=selector.get("css_selector"),
                xpath=selector.get("xpath"),
                regex=selector.get("regex"),
            )
            if value:
                rows.append(
                    {
                        "value": value,
                        "source": "selector",
                        "xpath": selector.get("xpath"),
                        "css_selector": selector.get("css_selector"),
                        "regex": selector.get("regex"),
                        "sample_value": selector.get("sample_value") or value,
                        "selector_used": selector_used,
                        "status": selector.get("status") or "validated",
                    }
                )
        dom_row = _dom_pattern(soup, field_name)
        if dom_row:
            rows.append(dom_row)
        for item in microdata:
            if isinstance(item, dict):
                _append_source_candidates(
                    rows, field_name, item, "microdata", base_url=url
                )
        if open_graph:
            _append_source_candidates(
                rows, field_name, open_graph, "open_graph", base_url=url
            )
            if field_name == "company":
                site_name = open_graph.get("og:site_name")
                if site_name not in (None, "", [], {}):
                    rows.append({"value": site_name, "source": "open_graph"})
        
        # 8. Semantic extraction
        if (
            field_name in canonical_target_fields
            or field_name in REQUESTED_FIELD_ALIASES
        ):
            semantic_rows = resolve_requested_field_values(
                [field_name],
                sections=semantic.get("sections")
                if isinstance(semantic.get("sections"), dict)
                else {},
                specifications=semantic.get("specifications")
                if isinstance(semantic.get("specifications"), dict)
                else {},
                promoted_fields=semantic.get("promoted_fields")
                if isinstance(semantic.get("promoted_fields"), dict)
                else {},
            )
            semantic_value = semantic_rows.get(field_name)
            if semantic_value not in (None, "", [], {}):
                rows.append({"value": semantic_value, "source": "semantic_section"})
        
        # 9. Text patterns
        if (
            field_name in canonical_target_fields
            or field_name in REQUESTED_FIELD_ALIASES
        ):
            text_value = _extract_label_value_from_text(
                field_name, label_value_text_sources, html
            )
            if text_value:
                rows.append({"value": text_value, "source": "text_pattern"})
        
        if rows:
            candidates[field_name] = rows
    
    return candidates


def _filter_candidates(
    candidates: dict[str, list[dict]], base_url: str
) -> dict[str, list[dict]]:
    """Apply quality filters to candidates.
    
    Filters:
    - Placeholder rejection (CANDIDATE_PLACEHOLDER_VALUES)
    - Noise removal (empty strings, null values)
    - URL validation (relative → absolute)
    - Field-specific validation (price format, image URLs)
    
    Returns: {field_name: [filtered_rows]}
    """
    filtered_candidates: dict[str, list[dict]] = {}
    
    for field_name, rows in candidates.items():
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=base_url)
        if filtered_rows:
            filtered_candidates[field_name] = filtered_rows
    
    return filtered_candidates


def _finalize_candidates(
    candidates: dict[str, list[dict]],
    surface: str,
    url: str,
    semantic: dict,
    target_fields: set[str],
    canonical_target_fields: set[str],
    next_data: dict | None,
    hydrated_states: list[dict],
    embedded_json: list[dict],
    network_payloads: list[dict],
    soup: BeautifulSoup,
) -> tuple[dict, dict]:
    """Deduplicate, rank, and prepare final output.
    
    - Take first valid candidate per field (first-match wins)
    - Apply domain field mappings
    - Build source trace
    - Add dynamic fields (product_attributes, additional_images)
    
    Returns: (candidates, source_trace)
    """
    def _row_rank(row: dict) -> int:
        source = str(row.get("source") or "").strip()
        if not source:
            return 0
        source_parts = [part.strip() for part in source.split(",") if part.strip()]
        if not source_parts:
            return 0
        return max(int(SOURCE_RANKING.get(part, 0)) for part in source_parts)

    # Choose the highest-ranked candidate per field.
    final_candidates: dict[str, list[dict]] = {}
    for field_name, rows in candidates.items():
        if rows:
            best_row = rows[0]
            best_rank = _row_rank(best_row)
            for candidate_row in rows[1:]:
                candidate_rank = _row_rank(candidate_row)
                if candidate_rank > best_rank:
                    best_row = candidate_row
                    best_rank = candidate_rank
            final_candidates[field_name] = [best_row]
    
    # Add dynamic fields from semantic and structured sources
    dynamic_rows = _build_dynamic_semantic_rows(semantic, surface=surface)
    structured_rows = _build_dynamic_structured_rows(
        surface=surface,
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
    )
    product_detail_rows = _build_product_detail_rows(
        soup,
        base_url=url,
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
    )
    
    # Merge dynamic rows
    merged_dynamic_rows: dict[str, list[dict]] = {}
    for field_name, rows in structured_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in product_detail_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in dynamic_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    
    # Add dynamic fields if not already present
    for field_name, rows in merged_dynamic_rows.items():
        if field_name in final_candidates:
            continue
        if (
            field_name not in canonical_target_fields
            and not _dynamic_field_name_is_valid(field_name)
        ):
            continue
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=url)
        if filtered_rows:
            normalized_value = _normalized_candidate_text(
                filtered_rows[0].get("value")
            ).casefold()
            if normalized_value in CANDIDATE_PLACEHOLDER_VALUES:
                continue
            final_candidates[field_name] = filtered_rows[:1]
    
    # Mirror image_url to additional_images if needed
    if (
        "additional_images" in target_fields
        and "additional_images" not in final_candidates
        and final_candidates.get("image_url")
    ):
        mirrored_rows = [
            {**row, "value": row.get("value")}
            for row in final_candidates["image_url"]
            if row.get("value") not in (None, "", [], {})
        ]
        if mirrored_rows:
            final_candidates["additional_images"] = mirrored_rows
    
    # Add product_attributes from semantic extraction to output
    if "detail" in str(surface or "").lower():
        specifications = semantic.get("specifications")
        if specifications and isinstance(specifications, dict) and specifications:
            final_candidates["product_attributes"] = [
                {"value": specifications, "source": "semantic_specifications"}
            ]
    
    # Apply domain field mappings
    domain = _domain(url)
    mappings = get_domain_mapping(domain, surface)
    
    return final_candidates, {
        "candidates": dict(final_candidates),
        "mapping_hint": mappings,
        "semantic": semantic,
    }


_DYNAMIC_FIELD_NAME_DROP_TOKENS = DYNAMIC_FIELD_NAME_DROP_TOKENS
_DYNAMIC_FIELD_NAME_MAX_TOKENS = DYNAMIC_FIELD_NAME_MAX_TOKENS


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    xhr_payloads: list[dict],
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Extract candidate values for each target field.

    Sources are checked in deterministic priority order and every discovered
    value is preserved as its own candidate row.

    Returns:
        (candidates, source_trace) — candidates maps field -> list of {value, source}
    """
    # Build signal inventory and classify page type before extraction
    signal_inventory = build_signal_inventory(html, url, surface)
    page_type = classify_page_type(signal_inventory)

    if "listing" in str(surface or "").lower():
        return {}, {
            "candidates": {},
            "mapping_hint": {},
            "semantic": {},
            "surface_gate": "listing",
            "page_type": page_type,
        }

    soup = BeautifulSoup(html, "html.parser")
    tree = _build_xpath_tree(html)
    page_sources = parse_page_sources(html)
    adapter_records = adapter_records or []
    network_payloads = xhr_payloads or []
    
    base_target_fields = set(resolved_fields or get_canonical_fields(surface))
    if str(surface or "").strip().lower() in {"job_listing", "job_detail"}:
        base_target_fields = set(get_canonical_fields(surface))
    target_fields = sorted(
        base_target_fields | set(expand_requested_fields(additional_fields))
    )
    
    contract_by_field = _index_extraction_contract(extraction_contract or [])
    semantic = extract_semantic_detail_data(
        html, requested_fields=sorted(target_fields)
    )
    label_value_text_sources = _build_label_value_text_sources(
        url=url,
        soup=soup,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        next_data=page_sources.get("next_data"),
        hydrated_states=page_sources.get("hydrated_states") or [],
        embedded_json=page_sources.get("embedded_json") or [],
        open_graph=page_sources.get("open_graph") or {},
        json_ld=page_sources.get("json_ld") or [],
        microdata=page_sources.get("microdata") or [],
    )

    canonical_target_fields = set(get_canonical_fields(surface))

    # Step 1: Collect all candidates from all sources
    candidates = _collect_candidates(
        url=url,
        surface=surface,
        html=html,
        soup=soup,
        tree=tree,
        page_sources=page_sources,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        target_fields=target_fields,
        canonical_target_fields=canonical_target_fields,
        contract_by_field=contract_by_field,
        semantic=semantic,
        label_value_text_sources=label_value_text_sources,
    )
    
    # Step 2: Filter candidates (remove placeholders, validate)
    candidates = _filter_candidates(candidates, base_url=url)
    
    # Step 3: Finalize candidates (deduplicate, add dynamic fields)
    return _finalize_candidates(
        candidates=candidates,
        surface=surface,
        url=url,
        semantic=semantic,
        target_fields=set(target_fields),
        canonical_target_fields=canonical_target_fields,
        next_data=page_sources.get("next_data"),
        hydrated_states=page_sources.get("hydrated_states") or [],
        embedded_json=page_sources.get("embedded_json") or [],
        network_payloads=network_payloads,
        soup=soup,
    )


def _extract_label_value_from_text(
    field_name: str,
    text_sources: list[str],
    html: str,
) -> str | None:
    """Search description text and raw HTML for 'Label: Value' patterns matching field_name."""
    label_variants = _label_value_variants(field_name)

    # Also search raw HTML for meta/og description
    for text in text_sources:
        for variant in label_variants:
            pattern = _label_value_pattern(variant)
            match = pattern.search(text)
            if match:
                value = match.group(1).strip().rstrip(".")
                if 1 < len(value) < 200:
                    return value

    return None


@lru_cache(maxsize=512)
def _label_value_pattern(variant: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(variant) + r"\s*:\s*(.+?)(?:\n|$|[.]\s|\u2022)", re.IGNORECASE
    )


def _label_value_variants(field_name: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def _append(label: object) -> None:
        text = " ".join(str(label or "").replace("_", " ").split()).strip()
        lowered = text.lower()
        if not lowered or lowered in seen:
            return
        seen.add(lowered)
        variants.append(text)

    _append(field_name)
    for alias in FIELD_ALIASES.get(field_name, []):
        _append(alias)
    for alias in REQUESTED_FIELD_ALIASES.get(field_name, []):
        _append(alias)
    return variants


def _dom_pattern(soup: BeautifulSoup, field_name: str) -> dict | None:
    """Try common DOM patterns for well-known fields."""
    selector_group = DOM_PATTERNS.get(field_name)
    if not selector_group:
        return None
    for selector in [
        part.strip() for part in str(selector_group).split(",") if part.strip()
    ]:
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


def _finalize_candidate_rows(
    field_name: str, rows: list[dict], *, base_url: str = ""
) -> list[dict]:
    filtered: list[dict] = []
    filtered_index: dict[str, int] = {}
    for row in rows:
        value = coerce_field_candidate_value(
            field_name, row.get("value"), base_url=base_url
        )
        if value in (None, "", [], {}):
            value = _normalized_candidate_value(row.get("value"))
        if value in (None, "", [], {}):
            continue
        value = validate_value(field_name, value)
        if value in (None, "", [], {}):
            continue
        value = sanitize_field_value(field_name, value)
        if value in (None, "", [], {}):
            continue
        source_parts = _source_labels(row)
        source = ", ".join(source_parts)
        normalized = _candidate_value_fingerprint(value)
        if normalized in filtered_index:
            existing = filtered[filtered_index[normalized]]
            sources = list(existing.get("sources") or [])
            for source_part in source_parts:
                if source_part not in sources:
                    sources.append(source_part)
            existing["sources"] = sources
            existing["source"] = ", ".join(sources)
            preferred_value = _preferred_display_candidate_value(
                existing.get("value"), value
            )
            if preferred_value != existing.get("value"):
                existing["value"] = preferred_value
            for metadata_key, metadata_value in row.items():
                if metadata_key in {"value", "source", "sources"}:
                    continue
                if existing.get(metadata_key) in (
                    None,
                    "",
                    [],
                    {},
                ) and metadata_value not in (None, "", [], {}):
                    existing[metadata_key] = metadata_value
            continue
        filtered_index[normalized] = len(filtered)
        filtered.append(
            {**row, "value": value, "source": source, "sources": source_parts}
        )
    if len(filtered) > MAX_CANDIDATES_PER_FIELD:
        filtered = filtered[:MAX_CANDIDATES_PER_FIELD]
    return filtered


def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def sanitize_field_value(field_name: str, value: object) -> object | None:
    """Apply config-driven noise phrase filtering for string candidates."""
    if not isinstance(value, str):
        return value
    text = _normalized_candidate_text(value)
    if not text:
        return None
    rules = FIELD_POLLUTION_RULES.get(field_name) or {}
    reject_phrases = [str(item).strip().casefold() for item in rules.get("reject_phrases", []) if str(item).strip()]
    lowered = text.casefold()
    if any(phrase in lowered for phrase in reject_phrases):
        return None
    return text


def _normalize_html_rich_text(value: str) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return _normalized_candidate_text(text)
    soup = BeautifulSoup(text, "html.parser")
    block_tags = list(soup.find_all(name=["p", "li", "br", "div"]))
    for tag in block_tags:
        tag.insert_before("\n")
    rendered = soup.get_text(" ", strip=False)
    rendered = re.sub(r"[ \t]+", " ", rendered)
    rendered = re.sub(r" *\n+ *", "\n", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    lines = []
    for raw_line in rendered.splitlines():
        line = _normalized_candidate_text(raw_line)
        if not line:
            continue
        if line.startswith(("-", "*")):
            line = f"• {line[1:].strip()}"
        lines.append(line)
    return "\n".join(lines).strip()


def _candidate_value_fingerprint(value: object) -> str:
    if isinstance(value, (dict, list)):
        return _comparable_candidate_value(value)
    return _normalized_candidate_text(value).casefold()


def _preferred_display_candidate_value(existing: object, candidate: object) -> object:
    if _display_candidate_priority(candidate) > _display_candidate_priority(existing):
        return candidate
    return existing


def _display_candidate_priority(value: object) -> tuple[int, int]:
    text = _normalized_candidate_text(value)
    if not text:
        return (0, 0)
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return (1, len(text))
    has_lower = any(ch.islower() for ch in letters)
    has_upper = any(ch.isupper() for ch in letters)
    if has_lower and has_upper:
        return (4, len(text))
    if has_lower:
        return (3, len(text))
    if has_upper:
        return (2, len(text))
    return (1, len(text))


def _source_labels(row: dict) -> list[str]:
    raw_sources = row.get("sources")
    if isinstance(raw_sources, list):
        labels = [str(source or "").strip() for source in raw_sources]
    else:
        labels = [
            part.strip() for part in str(row.get("source") or "candidate").split(",")
        ]
    cleaned = [label for label in labels if label]
    return cleaned or ["candidate"]


def _normalized_candidate_value(value: object) -> object | None:
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        return cleaned or None
    return value if value not in (None, "", [], {}) else None


def _comparable_candidate_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            return _normalized_candidate_text(value)
    text = _normalized_candidate_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.fullmatch(r"[$€£₹]?\s*\d[\d,]*(?:\.\d+)?", lowered):
        return re.sub(r"[^\d.]+", "", lowered)
    return lowered


def _field_name_preference(field_name: str, *, target_fields: set[str]) -> int:
    tokens = [token for token in str(field_name or "").split("_") if token]
    score = 100 if field_name in target_fields else 0
    score += max(0, 20 - len(tokens))
    if re.match(r"^\d", field_name):
        score -= 30
    if "price" in tokens and len(tokens) > 2:
        score -= 20
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        score -= 30
    score -= sum(5 for token in tokens if token in _DYNAMIC_FIELD_NAME_DROP_TOKENS)
    return score


def _dynamic_field_name_is_noisy(field_name: str) -> bool:
    normalized = str(field_name or "").strip().lower()
    if not normalized:
        return True
    if re.match(r"^\d", normalized):
        return True
    tokens = [token for token in normalized.split("_") if token]
    if not tokens:
        return True
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return True
    noise_hits = sum(1 for token in tokens if token in _DYNAMIC_FIELD_NAME_DROP_TOKENS)
    if noise_hits >= 2:
        return True
    if "price" in tokens and len(tokens) > 2:
        return True
    if normalized in {"from", "location", "recommended", "reviews", "votes"}:
        return True
    return False


def _should_skip_jsonld_block(payload: dict, field_name: str) -> bool:
    """Skip non-product JSON-LD blocks for product-identity fields."""
    if field_name not in PRODUCT_IDENTITY_FIELDS:
        return False
    raw_types = payload.get("@type")
    if raw_types is None:
        type_names: list[object] = []
    elif isinstance(raw_types, str):
        type_names = [raw_types]
    elif isinstance(raw_types, (list, tuple)):
        type_names = list(raw_types)
    else:
        type_names = [raw_types]
    lowered_types = [
        str(type_name or "").lower()
        for type_name in type_names
        if str(type_name or "").strip()
    ]
    return any(
        type_name in JSONLD_NON_PRODUCT_BLOCK_TYPES for type_name in lowered_types
    )


def _build_label_value_text_sources(
    *,
    url: str,
    soup: BeautifulSoup,
    adapter_records: list[dict],
    network_payloads: list[dict],
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    open_graph: dict[str, object],
    json_ld: list[dict],
    microdata: list[dict],
) -> list[str]:
    text_sources: list[str] = []
    seen: set[str] = set()

    def _append_text(value: object) -> None:
        normalized = _normalized_candidate_text(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        text_sources.append(normalized)

    for selector in (
        "meta[name='description']",
        "meta[property='og:description']",
        "meta[name='twitter:description']",
    ):
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get("content"))

    for desc_field in ("description", "summary"):
        rows: list[dict] = []
        for record in adapter_records:
            if isinstance(record, dict) and record.get(desc_field):
                rows.append({"value": record[desc_field], "source": "adapter"})
        for payload in network_payloads:
            if not isinstance(payload, dict):
                continue
            payload_url = str(payload.get("url") or "").lower()
            if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
                continue
            body = payload.get("body", {})
            if isinstance(body, (dict, list)):
                _append_source_candidates(
                    rows, desc_field, body, "network_intercept", base_url=url
                )
        for state in hydrated_states:
            _append_source_candidates(
                rows, desc_field, state, "hydrated_state", base_url=url
            )
        for payload in embedded_json:
            _append_source_candidates(
                rows, desc_field, payload, "embedded_json", base_url=url
            )
        if open_graph:
            _append_source_candidates(
                rows, desc_field, open_graph, "open_graph", base_url=url
            )
        if next_data:
            _append_source_candidates(
                rows, desc_field, next_data, "next_data", base_url=url
            )
        for payload in json_ld:
            if isinstance(payload, dict):
                _append_source_candidates(
                    rows, desc_field, payload, "json_ld", base_url=url
                )
        for item in microdata:
            if isinstance(item, dict):
                _append_source_candidates(
                    rows, desc_field, item, "microdata", base_url=url
                )
        dom_row = _dom_pattern(soup, desc_field)
        if dom_row:
            rows.append(dom_row)
        for row in rows:
            _append_text(row.get("value"))

    for selector in ("article", "main", "body"):
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get_text("\n", strip=True))
            break

    return text_sources


def _deep_get_all_aliases(
    data: object, field_name: str, max_depth: int = 5
) -> list[object]:
    matches: list[object] = []
    alias_tokens = _field_alias_tokens(field_name)
    if not alias_tokens or max_depth <= 0:
        return matches

    def _collect(node: object, depth: int, parent_key: str = "") -> None:
        if depth <= 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            for current_key, value in node.items():
                if current_key in JSONLD_STRUCTURAL_KEYS:
                    continue
                if _normalized_field_token(
                    current_key
                ) in alias_tokens and value not in (None, "", [], {}):
                    matches.append(value)
                # Don't recurse into non-product containers
                normalized_key = _normalized_field_token(current_key)
                if normalized_key in NESTED_NON_PRODUCT_KEYS:
                    continue
                _collect(value, depth - 1, parent_key=current_key)
        elif isinstance(node, list):
            for item in node[:40]:
                _collect(item, depth - 1, parent_key=parent_key)

    _collect(data, max_depth)
    return matches


def _append_source_candidates(
    rows: list[dict],
    field_name: str,
    payload: object,
    source: str,
    *,
    base_url: str = "",
) -> None:
    # Skip brand/entity_name extraction from GA data layer — GA brand is the retailer's
    # name, not the product manufacturer. JSON-LD (rank 6) will supply the real brand.
    if _field_is_type(field_name, "entity_name") and _looks_like_ga_data_layer(payload):
        return
    for match in _deep_get_all_aliases(payload, field_name):
        value = coerce_field_candidate_value(field_name, match, base_url=base_url)
        if value is not None:
            rows.append({"value": value, "source": source})


# Type-specific coercion functions for field value normalization

def _coerce_url_field(value: str, base_url: str) -> str | None:
    """Coerce URL fields: resolve relative URLs, validate format."""
    resolved = _resolve_candidate_url(value, base_url)
    return resolved or None


def _coerce_image_field(value: object, base_url: str, *, primary: bool = True) -> str | None:
    """Coerce image fields: resolve URLs, validate image extensions."""
    images = _extract_image_urls(value, base_url=base_url)
    if not images:
        return None
    return images[0] if primary else ", ".join(images)


def _coerce_price_field(value: str) -> str | None:
    """Coerce price fields: extract numeric value, preserve currency symbol."""
    numeric = re.search(PRICE_REGEX, value)
    return value if numeric else None


def _coerce_currency_field(value: str) -> str | None:
    """Coerce currency fields: normalize to ISO code (USD, EUR, GBP)."""
    match = re.search(r"\b[A-Z]{3}\b", value.upper())
    return match.group(0) if match else None


def _coerce_color_field(value: str) -> str | None:
    """Coerce color fields: normalize color names."""
    normalized_color = _normalize_color_candidate(value)
    return normalized_color or None


def _coerce_size_field(value: str) -> str | None:
    """Coerce size fields: normalize size values."""
    normalized_size = _normalize_size_candidate(value)
    return normalized_size or None


def _coerce_category_field(value: str) -> str | None:
    """Coerce category fields: filter generic/noise values."""
    lowered = value.lower()
    if (
        lowered
        in CANDIDATE_GENERIC_CATEGORY_VALUES
        | {
            "guest",
            "max_discount",
            "website",
            "web site",
        }
        or "schema.org" in lowered
    ):
        return None
    if any(phrase in lowered for phrase in _CATEGORY_NOISE_PHRASES):
        return None
    if lowered.startswith("home >") or lowered.startswith("home/"):
        return None
    if lowered.count(">") >= 3:
        return None
    # Filter CamelCase schema.org type names (e.g. IndividualProduct, PeopleAudience)
    if re.fullmatch(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", value):
        return None
    return value


def _coerce_rating_field(value: str) -> str | None:
    """Coerce rating fields: extract numeric or word ratings."""
    lowered = value.lower()
    star_word_match = re.search(r"\bstar-rating\s+([a-z]+)\b", lowered)
    if star_word_match:
        token = star_word_match.group(1)
        return token.capitalize() if token else None
    numeric_match = re.search(r"\d+(?:\.\d+)?", value)
    if numeric_match:
        return numeric_match.group(0)
    word_match = re.search(r"\b(one|two|three|four|five)\b", lowered)
    if word_match:
        return word_match.group(1).capitalize()
    return value if re.search(r"[A-Za-z]", value) else None


def _coerce_salary_field(value: str) -> str | None:
    """Coerce salary fields: extract salary ranges and money values."""
    salary_match = re.search(SALARY_RANGE_REGEX, value)
    if salary_match:
        return _normalized_candidate_text(salary_match.group(0))
    money_match = _SALARY_MONEY_RE.search(value)
    if money_match:
        result = _normalized_candidate_text(money_match.group(0))
        unit_match = re.match(
            r"\s*(?:/\s*)?(hour|hr|year|yr|month|mo|week|wk|day)\b",
            value[money_match.end() :],
            re.IGNORECASE,
        )
        if unit_match:
            result = f"{result}/{unit_match.group(1).lower()}"
        return result
    numeric = re.search(PRICE_REGEX, value)
    return _normalized_candidate_text(numeric.group(0)) if numeric else None


def _coerce_availability_field(value: str) -> str | None:
    """Coerce availability fields: drop obvious UI noise, keep meaningful values."""
    lowered = value.lower()
    if lowered == "availability":
        return None
    # Reject Google Analytics custom dimension/metric placeholder names
    if re.fullmatch(r"dimension\d+|metric\d+|cd\d+|ev\d+", lowered):
        return None
    if any(phrase in lowered for phrase in _AVAILABILITY_NOISE_PHRASES):
        return None
    if any(token in lowered for token in ("limited stock", "low stock", "only", "left in stock")):
        return value
    if any(token in lowered for token in ("in stock", "instock", "available", "ready to ship")):
        return value
    if any(token in lowered for token in ("out of stock", "oos", "sold out", "unavailable")):
        return value
    if any(token in lowered for token in ("pre-order", "preorder", "backorder", "back-order")):
        return value
    return value


def _coerce_title_field(value: str) -> str | None:
    """Coerce title fields: strip UI noise, filter generic values."""
    cleaned = _strip_ui_noise(value)
    if not cleaned or cleaned.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
        return None
    lowered = cleaned.lower()
    if any(phrase in lowered for phrase in _TITLE_NOISE_PHRASES):
        return None
    if _PROMO_ONLY_TITLE_RE and _PROMO_ONLY_TITLE_RE.match(cleaned):
        return None
    if not re.search(r"[A-Za-z]", cleaned):
        return None
    return cleaned


def _coerce_description_field(value: str) -> str | None:
    """Coerce description fields: normalize HTML rich text, strip UI noise."""
    cleaned = _strip_ui_noise(value)
    return cleaned or None


def _coerce_default(value: str) -> str | None:
    """Default coercion: basic text normalization."""
    return value or None


# Lookup table mapping field types to coercion functions
FIELD_TYPE_COERCERS = {
    "url": _coerce_url_field,
    "image_primary": lambda v, base_url: _coerce_image_field(v, base_url, primary=True),
    "image_collection": lambda v, base_url: _coerce_image_field(v, base_url, primary=False),
    "currency": _coerce_currency_field,
    "color": _coerce_color_field,
    "size": _coerce_size_field,
    "category": _coerce_category_field,
    "rating": _coerce_rating_field,
    "numeric": _coerce_price_field,
    "salary": _coerce_salary_field,
    "availability": _coerce_availability_field,
    "title": _coerce_title_field,
    "description": _coerce_description_field,
    "entity_name": _coerce_description_field,
}


_STRING_COERCE_ORDER: tuple[tuple[str, Callable[[Any, str], Any]], ...] = (
    ("color", lambda v, _base_url: _coerce_color_field(v)),
    ("size", lambda v, _base_url: _coerce_size_field(v)),
    ("image_primary", lambda v, base_url: _coerce_image_field(v, base_url, primary=True)),
    ("image_collection", lambda v, base_url: _coerce_image_field(v, base_url, primary=False)),
    ("url", _coerce_url_field),
    ("currency", lambda v, _base_url: _coerce_currency_field(v)),
    ("category", lambda v, _base_url: _coerce_category_field(v)),
    ("rating", lambda v, _base_url: _coerce_rating_field(v)),
    ("numeric", lambda v, _base_url: _coerce_price_field(v)),
    ("salary", lambda v, _base_url: _coerce_salary_field(v)),
    ("availability", lambda v, _base_url: _coerce_availability_field(v)),
    ("title", lambda v, _base_url: _coerce_title_field(v)),
)


def _dispatch_string_field_coercer(field_name: str, value: str, *, base_url: str) -> object | None:
    for type_key, coercer in _STRING_COERCE_ORDER:
        if _field_is_type(field_name, type_key):
            return coercer(value, base_url)
    if _field_is_type(field_name, "description") or _field_is_type(field_name, "entity_name"):
        return _coerce_description_field(value)
    return value or None


def coerce_field_candidate_value(
    field_name: str, value: object, *, base_url: str = ""
) -> object | None:
    """Dispatch to type-specific coercion function using lookup table."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        if _field_is_type(field_name, "description") or _field_is_type(
            field_name, "job_text"
        ):
            cleaned = _normalize_html_rich_text(cleaned)
        parsed = _parse_json_like_value(cleaned)
        if parsed is not None:
            parsed_value = coerce_field_candidate_value(
                field_name, parsed, base_url=base_url
            )
            if parsed_value not in (None, "", [], {}):
                return parsed_value
        
        return _dispatch_string_field_coercer(field_name, cleaned, base_url=base_url)
    if isinstance(value, (int, float)) and _field_is_type(field_name, "title"):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        if _field_is_type(field_name, "description"):
            parts: list[str] = []
            for item in value:
                coerced = coerce_field_candidate_value(
                    field_name, item, base_url=base_url
                )
                if isinstance(coerced, str):
                    cleaned = coerced.strip()
                    if cleaned:
                        parts.append(cleaned)
            return " ".join(parts) if parts else None
        if _field_is_type(field_name, "image_primary") or _field_is_type(
            field_name, "image_collection"
        ):
            images = _extract_image_urls(value, base_url=base_url)
            if not images:
                return None
            return (
                images[0]
                if _field_is_type(field_name, "image_primary")
                else ", ".join(images)
            )
        coerced_values = [
            coerce_field_candidate_value(field_name, item, base_url=base_url)
            for item in value
        ]
        return _pick_best_nested_candidate(field_name, coerced_values)
    if isinstance(value, dict):
        nested_matches = [
            match
            for match in _deep_get_all_aliases(value, field_name, max_depth=4)
            if match is not value
        ]
        if nested_matches:
            coerced_nested = [
                coerce_field_candidate_value(field_name, match, base_url=base_url)
                for match in nested_matches
            ]
            nested_value = _pick_best_nested_candidate(field_name, coerced_nested)
            if nested_value not in (None, "", [], {}):
                return nested_value
        if _field_is_type(field_name, "image_primary") or _field_is_type(
            field_name, "image_collection"
        ):
            images = _extract_image_urls(value, base_url=base_url)
            if not images:
                return None
            return (
                images[0]
                if _field_is_type(field_name, "image_primary")
                else ", ".join(images)
            )
        for key in (
            "value",
            "amount",
            "code",
            "text",
            "content",
            "description",
            "sentence",
            "summary",
            "title",
            "name",
            "label",
        ):
            candidate = value.get(key)
            coerced = coerce_field_candidate_value(
                field_name, candidate, base_url=base_url
            )
            if coerced is not None:
                return coerced
        return None
    return None


def _pick_best_nested_candidate(field_name: str, values: list[object]) -> object | None:
    rows = [
        {"value": value, "source": "nested"}
        for value in values
        if value not in (None, "", [], {})
    ]
    if not rows:
        return None
    return rows[0]["value"]


def _field_alias_tokens(field_name: str) -> set[str]:
    aliases = [field_name, *FIELD_ALIASES.get(field_name, [])]
    return {token for alias in aliases if (token := _normalized_field_token(alias))}


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _parse_json_like_value(value: str) -> dict | list | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if candidate[:1] not in "{[":
        return None
    try:
        parsed = parse_json(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _resolve_candidate_url(value: str, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        resolved = f"https:{candidate}"
        resolved = _strip_tracking_query_params(resolved)
        return "" if _looks_like_asset_url(resolved) else resolved
    if candidate.startswith(("http://", "https://")):
        normalized = _strip_tracking_query_params(candidate)
        return "" if _looks_like_asset_url(normalized) else normalized
    if candidate.startswith("/"):
        resolved = urljoin(base_url, candidate) if base_url else candidate
        resolved = _strip_tracking_query_params(resolved)
        return "" if _looks_like_asset_url(resolved) else resolved
    resolved = (
        urljoin(base_url, candidate)
        if re.search(r"^[A-Za-z0-9][^ ]*/[^ ]+$", candidate) and base_url
        else ""
    )
    resolved = _strip_tracking_query_params(resolved) if resolved else ""
    return "" if _looks_like_asset_url(resolved) else resolved


def _strip_tracking_query_params(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return str(url or "").strip()
    filtered_query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key
        and (
            (key_lower := key.lower()) not in {"ref", "ref_src"}
            and not key_lower.startswith(("utm_", "fbclid", "gclid", "mc_"))
        )
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(filtered_query, doseq=True),
            parsed.fragment,
        )
    )


def _looks_like_asset_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.lower()
    return path.endswith(
        (
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
            ".eot",
            ".css",
            ".js",
            ".map",
        )
    )


def _extract_image_urls(value: object, *, base_url: str = "") -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = _resolve_candidate_url(candidate, base_url)
        if not resolved:
            return
        lowered = resolved.lower()
        path = urlparse(resolved).path.lower()
        if any(
            token in lowered for token in ("logo", "sprite", "icon", "badge", "favicon")
        ):
            return
        if not (
            path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"))
            or any(
                token in lowered
                for token in ("/image", "/images/", "/img", "image=", "im/")
            )
        ):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        urls.append(resolved)

    def _collect(node: object) -> None:
        if node in (None, "", [], {}):
            return
        if isinstance(node, str):
            for part in re.split(r"\s*\|\s*|\s*,\s*(?=https?://|//|/)", node):
                cleaned = _normalized_candidate_text(part)
                if cleaned:
                    _append(cleaned)
            return
        if isinstance(node, dict):
            for key in ("url", "contentUrl", "src", "image", "thumbnail", "href"):
                candidate = node.get(key)
                if isinstance(candidate, str):
                    _append(candidate)
            for item in list(node.values())[:20]:
                _collect(item)
            return
        if isinstance(node, list):
            for item in node[:20]:
                _collect(item)

    _collect(value)
    return urls


def _field_in_group(field_name: str, group_name: str) -> bool:
    return field_name in CANDIDATE_FIELD_GROUPS.get(group_name, set())


def _field_token(field_name: str) -> str:
    return _normalized_field_token(field_name)


def _field_has_any_token(field_name: str, tokens: tuple[str, ...]) -> bool:
    normalized = _field_token(field_name)
    return any(
        _normalized_field_token(token) in normalized for token in tokens if token
    )


_FIELD_TYPE_TOKENS: dict[str, tuple[str, ...]] = {
    "image_primary": CANDIDATE_IMAGE_TOKENS,
    "url": CANDIDATE_URL_SUFFIXES,
    "currency": CANDIDATE_CURRENCY_TOKENS,
    "numeric": CANDIDATE_PRICE_TOKENS,
    "salary": CANDIDATE_SALARY_TOKENS,
    "rating": CANDIDATE_RATING_TOKENS,
    "availability": CANDIDATE_AVAILABILITY_TOKENS,
    "category": CANDIDATE_CATEGORY_TOKENS,
    "description": CANDIDATE_DESCRIPTION_TOKENS,
    "identifier": CANDIDATE_IDENTIFIER_TOKENS,
    "image_collection": ("images", "gallery", "photos", "media"),
}


def _field_is_type(field_name: str, type_key: str) -> bool:
    normalized = _field_token(field_name)

    if type_key == "color":
        return normalized in _field_alias_tokens("color")
    if type_key == "size":
        return normalized in _field_alias_tokens("size")
    if type_key in ("title", "job_text", "entity_name"):
        return _field_in_group(field_name, type_key)

    is_img_coll = _field_in_group(field_name, "image_collection") or any(
        token in normalized for token in _FIELD_TYPE_TOKENS["image_collection"]
    )
    if type_key == "image_collection":
        return is_img_coll

    is_img_prim = _field_in_group(field_name, "image_primary") or (
        _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["image_primary"])
        and not is_img_coll
    )
    if type_key == "image_primary":
        return is_img_prim

    if type_key == "url":
        if is_img_prim or is_img_coll:
            return False
        return _field_in_group(field_name, "url") or any(
            normalized.endswith(_normalized_field_token(suffix))
            for suffix in _FIELD_TYPE_TOKENS["url"]
        )

    if type_key == "numeric":
        return (
            _field_in_group(field_name, "numeric")
            or _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["numeric"])
            or _field_has_any_token(field_name, CANDIDATE_REVIEW_COUNT_TOKENS)
        )

    return _field_in_group(field_name, type_key) or _field_has_any_token(
        field_name, _FIELD_TYPE_TOKENS.get(type_key, ())
    )


def _strip_ui_noise(value: str) -> str:
    text = _normalized_candidate_text(value)
    if not text:
        return ""
    if _UI_ICON_TOKEN_RE:
        text = _UI_ICON_TOKEN_RE.sub(" ", text)
    if _UI_NOISE_TOKEN_RE:
        text = _UI_NOISE_TOKEN_RE.sub(" ", text)
    if _SCRIPT_NOISE_RE:
        text = _SCRIPT_NOISE_RE.sub(" ", text)
    if _UI_NOISE_PHRASES_RE:
        text = _UI_NOISE_PHRASES_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text


def _normalize_color_candidate(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    tokens = cleaned.split()
    if any(
        token in lowered
        for token in (
            "padding:",
            "font-size",
            "font-weight",
            "transition:",
            "position:",
            "-webkit-",
            "css-",
        )
    ):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if "colors" in cleaned.lower() and cleaned.split()[0].isdigit():
        return None
    # Reject JavaScript minified booleans/expressions: !1 (false), !0 (true)
    if re.search(r"!\d", cleaned):
        return None
    # Reject JS object shorthand patterns: key:value with non-alpha keys
    if re.search(r"(?<![A-Za-z ])\s*:\s*!", cleaned):
        return None
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if len(cleaned) > 40:
        return None
    if len(cleaned.split()) > 6:
        return None
    lowered_clean = cleaned.lower()
    if any(phrase in lowered_clean for phrase in _AVAILABILITY_NOISE_PHRASES):
        return None
    return cleaned or None


def _normalize_size_candidate(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(
        token in lowered
        for token in (
            "max-width",
            "min-width",
            "vw",
            "vh",
            "sizes=",
            "srcset",
            "padding:",
            "font-size",
            "font-weight",
            "transition:",
            "position:",
            "-webkit-",
            "css-",
        )
    ):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?\s*[A-Za-z]{1,8}", cleaned):
        return cleaned
    if any(token in lowered for token in ("pkg of", "pack of", "pack size", "package")):
        return cleaned
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    
    # Check if it's already a clean size value (e.g., "13 in", "XL", "10.5 oz")
    # Don't split and rejoin if it's already good
    if re.fullmatch(r"[A-Za-z0-9.+-]+(?:\s+[A-Za-z0-9.+-]+){0,3}", cleaned):
        return cleaned
    
    # Only split/rejoin for multi-value sizes like "S/M/L" or "10,12,14"
    tokens = [
        token.strip() for token in re.split(r"[\s,/|]+", cleaned) if token.strip()
    ]
    if tokens and all(re.fullmatch(r"[A-Za-z0-9.+-]{1,5}", token) for token in tokens):
        # Use "/" for joining size variants, not comma
        return "/".join(tokens)
    return cleaned or None


def _structured_source_candidates(
    field_name: str,
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    sources: list[tuple[str, object]] = _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
    )
    for source, payload in sources:
        value = _extract_structured_field_value(payload, field_name)
        normalized = _normalized_candidate_text(value)
        if not normalized:
            continue
        key = (source, normalized)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"value": value, "source": source})
    return rows


def _build_dynamic_semantic_rows(
    semantic: dict, *, surface: str = ""
) -> dict[str, list[dict]]:
    specifications = (
        semantic.get("specifications")
        if isinstance(semantic.get("specifications"), dict)
        else {}
    )
    aggregates = (
        semantic.get("aggregates")
        if isinstance(semantic.get("aggregates"), dict)
        else {}
    )
    table_groups = (
        semantic.get("table_groups")
        if isinstance(semantic.get("table_groups"), list)
        else []
    )
    rows: dict[str, list[dict]] = {}

    for field_name, value in specifications.items():
        normalized = normalize_requested_field(field_name)
        if (
            not normalized
            or value in (None, "", [], {})
            or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
        ):
            continue
        if normalized in JSONLD_TYPE_NOISE:
            continue
        if not _dynamic_field_name_is_valid(normalized):
            continue
        rows.setdefault(normalized, []).append(
            {"value": value, "source": "semantic_spec"}
        )

    for group in table_groups:
        if not isinstance(group, dict):
            continue
        group_label = _normalized_candidate_text(
            group.get("title")
        ) or _normalized_candidate_text(group.get("caption"))
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            normalized = normalize_requested_field(
                row.get("normalized_key") or row.get("label")
            )
            value = row.get("value")
            if (
                not normalized
                or value in (None, "", [], {})
                or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
            ):
                continue
            if not _dynamic_field_name_is_valid(normalized):
                continue
            rows.setdefault(normalized, []).append(
                {
                    "value": value,
                    "source": "semantic_spec",
                    "display_label": _normalized_candidate_text(row.get("label"))
                    or normalized,
                    "group_label": group_label or None,
                    "href": _normalized_candidate_text(row.get("href")) or None,
                    "preserve_visible": bool(row.get("preserve_visible")),
                    "row_index": row.get("row_index"),
                    "table_index": group.get("table_index"),
                }
            )

    # Only emit specification/dimension aggregates when the semantic extractor
    # found real spec entries (tables, dl, data-attributes). Skip phantom
    # aggregates built from inline label/value guesses on JS-shell pages.
    spec_entry_count = len(specifications)
    for aggregate_field in ("specifications", "dimensions"):
        value = aggregates.get(aggregate_field)
        if value in (None, "", [], {}):
            continue
        if aggregate_field == "specifications" and str(
            surface or ""
        ).lower().startswith("job_"):
            continue
        if aggregate_field in {"specifications", "dimensions"} and spec_entry_count < 2:
            continue
        rows.setdefault(aggregate_field, []).append(
            {"value": value, "source": "semantic_spec"}
        )

    feature_value = aggregates.get("features")
    if feature_value not in (None, "", [], {}):
        rows.setdefault("features", []).append(
            {
                "value": feature_value,
                "source": "semantic_section",
            }
        )
    return rows


def _build_dynamic_structured_rows(
    *,
    surface: str = "",
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict] | None = None,
) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for source, payload in _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads or [],
    ):
        spec_map = _extract_structured_spec_map(payload)
        if not spec_map:
            continue
        spec_lines = [f"{label}: {value}" for label, value in spec_map.items()]
        if spec_lines and not str(surface or "").lower().startswith("job_"):
            rows.setdefault("specifications", []).append(
                {
                    "value": SEMANTIC_AGGREGATE_SEPARATOR.join(spec_lines),
                    "source": source,
                }
            )
        dimension_lines = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        if dimension_lines:
            rows.setdefault("dimensions", []).append(
                {
                    "value": SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_lines),
                    "source": source,
                }
            )
        for field_name, value in spec_map.items():
            normalized = normalize_requested_field(field_name)
            if not normalized or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized):
                continue
            if not _dynamic_field_name_is_valid(normalized):
                continue
            rows.setdefault(normalized, []).append({"value": value, "source": source})
    return rows


def _build_product_detail_rows(
    soup: BeautifulSoup,
    *,
    base_url: str,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict] | None = None,
) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for source, payload in _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads or [],
    ):
        detail = _find_product_detail_payload(payload)
        if not isinstance(detail, dict):
            continue
        for field_name, value in _normalize_product_detail_payload(
            detail, base_url=base_url
        ).items():
            normalized_source = "product_detail" if field_name == "sku" else source
            rows.setdefault(field_name, []).append(
                {"value": value, "source": normalized_source}
            )

    for field_name, value in _extract_buy_box_candidates(soup).items():
        rows.setdefault(field_name, []).append(
            {"value": value, "source": "dom_buy_box"}
        )
    return rows


def _find_product_detail_payload(payload: object) -> dict | None:
    if payload in (None, "", [], {}):
        return None
    if isinstance(payload, str):
        parsed = _parse_json_like_value(payload)
        if isinstance(parsed, (dict, list)):
            return _find_product_detail_payload(parsed)
        return None
    if isinstance(payload, dict):
        props = payload.get("props")
        if isinstance(props, dict):
            page_props = props.get("pageProps")
            if isinstance(page_props, dict):
                data = page_props.get("data")
                if isinstance(data, dict) and isinstance(
                    data.get("getProductDetail"), dict
                ):
                    return data["getProductDetail"]
                product_blob = page_props.get("product")
                if isinstance(product_blob, str):
                    parsed_product = _parse_json_like_value(product_blob)
                    if isinstance(parsed_product, dict):
                        return parsed_product
                if isinstance(page_props.get("product"), dict):
                    return page_props["product"]
        if isinstance(payload.get("getProductDetail"), dict):
            return payload["getProductDetail"]
        required_keys = {"productNumber", "productKey", "name"}
        if required_keys.issubset(payload.keys()):
            return payload
        if {"description", "variants", "detailedImages"} & set(payload.keys()):
            return payload
        for value in payload.values():
            found = _find_product_detail_payload(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload[:20]:
            found = _find_product_detail_payload(item)
            if found:
                return found
    return None


def _normalize_product_detail_payload(
    detail: dict, *, base_url: str
) -> dict[str, object]:
    record: dict[str, object] = {}
    title = _normalized_candidate_text(detail.get("name"))
    if title:
        record["title"] = title
    material_ids = detail.get("materialIds")
    material_skus = (
        [
            _normalized_candidate_text(item)
            for item in material_ids
            if _normalized_candidate_text(item)
        ]
        if isinstance(material_ids, list)
        else []
    )
    sku = (
        material_skus[0]
        if material_skus
        else _normalized_candidate_text(
            detail.get("productNumber") or detail.get("productKey")
        )
    )
    if sku:
        record["sku"] = sku
    brand = detail.get("brand")
    if isinstance(brand, dict):
        brand_name = _normalized_candidate_text(brand.get("name"))
        if brand_name:
            record["brand"] = brand_name
    description = _normalized_candidate_text(detail.get("description"))
    if description:
        record["description"] = description
    synonyms = detail.get("synonyms")
    if isinstance(synonyms, list):
        values = [
            _normalized_candidate_text(item)
            for item in synonyms
            if _normalized_candidate_text(item)
        ]
        if values:
            record["synonyms"] = " | ".join(dict.fromkeys(values))

    images = _extract_image_urls(detail.get("images"), base_url=base_url)
    if not images:
        images = _extract_image_urls(detail.get("detailedImages"), base_url=base_url)
    if not images:
        images = _extract_image_urls(
            detail.get("colourAlternateViews"), base_url=base_url
        )
    if not images:
        images = _extract_image_urls(detail.get("variants"), base_url=base_url)
    if images:
        record["image_url"] = images[0]
        record["additional_images"] = ", ".join(
            images[1:] if len(images) > 1 else images
        )

    attributes = detail.get("attributes")
    if isinstance(attributes, list):
        attr_map = _normalize_product_detail_attributes(attributes)
        if attr_map.get("material"):
            record["materials"] = attr_map["material"]
        if attr_map.get("packaging"):
            record["size"] = attr_map["packaging"]
            record["pack_size"] = attr_map["packaging"]
        dimensions = _product_detail_dimensions(attr_map)
        if dimensions:
            record["dimensions"] = dimensions
    features_text = _product_detail_features(detail.get("features"))
    feature_tile_text = _product_detail_feature_tiles(
        ((detail.get("centreSectionTemplate") or {}).get("featureTiles"))
        if isinstance(detail.get("centreSectionTemplate"), dict)
        else None
    )
    if features_text and feature_tile_text:
        record["features"] = (
            f"{features_text}{SEMANTIC_AGGREGATE_SEPARATOR}{feature_tile_text}"
        )
    elif features_text:
        record["features"] = features_text
    elif feature_tile_text:
        record["features"] = feature_tile_text

    fit_text = _product_detail_fit_and_sizing(detail)
    if fit_text:
        record["fit_and_sizing"] = fit_text

    materials_and_care = _product_detail_materials_and_care(detail)
    if materials_and_care:
        record["materials_and_care"] = materials_and_care
    return record


def _normalize_product_detail_attributes(attributes: list[object]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = normalize_requested_field(attribute.get("label"))
        values = attribute.get("values")
        if not label or not isinstance(values, list):
            continue
        normalized_values = []
        for value in values:
            cleaned = _normalized_candidate_text(str(value).replace("&#160;", " "))
            if cleaned:
                normalized_values.append(cleaned)
        if normalized_values:
            mapped[label] = " | ".join(dict.fromkeys(normalized_values))
    return mapped


def _product_detail_dimensions(attr_map: dict[str, str]) -> str | None:
    rows: list[str] = []
    for label, value in attr_map.items():
        if (
            any(token in label.lower() for token in DIMENSION_KEYWORDS)
            or "thread" in label.lower()
        ):
            rows.append(f"{label.replace('_', ' ')}: {value}")
    return SEMANTIC_AGGREGATE_SEPARATOR.join(rows) if rows else None


def _product_detail_features(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    sections: list[str] = []
    for row in value[:12]:
        if not isinstance(row, dict):
            continue
        label = _normalized_candidate_text(row.get("label"))
        bullet_rows = row.get("value")
        bullets = [
            _normalized_candidate_text(item)
            for item in (bullet_rows if isinstance(bullet_rows, list) else [])
            if _normalized_candidate_text(item)
        ]
        if not bullets:
            continue
        if label:
            sections.append(
                f"{label}:{SEMANTIC_AGGREGATE_SEPARATOR}"
                + SEMANTIC_AGGREGATE_SEPARATOR.join(f"- {item}" for item in bullets)
            )
        else:
            sections.append(
                SEMANTIC_AGGREGATE_SEPARATOR.join(f"- {item}" for item in bullets)
            )
    return SEMANTIC_AGGREGATE_SEPARATOR.join(sections) if sections else None


def _product_detail_feature_tiles(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    rows: list[str] = []
    for tile in value[:12]:
        if not isinstance(tile, dict):
            continue
        title = _normalized_candidate_text(tile.get("title") or tile.get("name"))
        description = _normalized_candidate_text(tile.get("description"))
        if title and description:
            rows.append(f"{title}: {description}")
        elif description:
            rows.append(description)
    return SEMANTIC_AGGREGATE_SEPARATOR.join(dict.fromkeys(rows)) if rows else None


def _product_detail_fit_and_sizing(detail: dict) -> str | None:
    rows: list[str] = []
    widgets = detail.get("bigWidgets")
    if isinstance(widgets, list):
        for widget in widgets[:12]:
            if not isinstance(widget, dict):
                continue
            label = _normalized_candidate_text(widget.get("label"))
            widget_type = _normalized_candidate_text(widget.get("type"))
            html = _normalize_html_rich_text(str(widget.get("html") or ""))
            html = _normalized_candidate_text(html)
            if (
                any(
                    token in f"{label} {widget_type}".lower()
                    for token in ("fit", "size", "sizing")
                )
                and html
            ):
                rows.append(f"{label}: {html}" if label else html)
    customer_tip = ""
    customer_tips = detail.get("customerTips")
    if isinstance(customer_tips, dict):
        customer_tip = _normalized_candidate_text(customer_tips.get("value"))
    if customer_tip:
        rows.append(f"Product tip: {customer_tip}")
    sizing_chart = detail.get("sizingChart")
    if isinstance(sizing_chart, dict):
        label = _normalized_candidate_text(sizing_chart.get("label"))
        url = _resolve_candidate_url(
            _normalized_candidate_text(sizing_chart.get("url")), base_url=""
        )
        if label and url:
            rows.append(f"{label}: {url}")
        elif label:
            rows.append(label)
    size = detail.get("size")
    if isinstance(size, dict):
        size_value = _normalized_candidate_text(size.get("value"))
        if size_value:
            rows.append(f"Size: {size_value}")
    return (
        SEMANTIC_AGGREGATE_SEPARATOR.join(dict.fromkeys(row for row in rows if row))
        or None
    )


def _product_detail_materials_and_care(detail: dict) -> str | None:
    rows: list[str] = []
    materials = [
        _normalized_candidate_text(item)
        for item in (
            detail.get("materials") if isinstance(detail.get("materials"), list) else []
        )
        if _normalized_candidate_text(item)
    ]
    if materials:
        rows.append("Materials:")
        rows.extend(f"- {item}" for item in materials)
    care = [
        _normalized_candidate_text(item)
        for item in (
            detail.get("careInstructions")
            if isinstance(detail.get("careInstructions"), list)
            else []
        )
        if _normalized_candidate_text(item)
    ]
    if care:
        rows.append("Care:")
        rows.extend(f"- {item}" for item in care)
    return SEMANTIC_AGGREGATE_SEPARATOR.join(rows) if rows else None


def _extract_buy_box_candidates(soup: BeautifulSoup) -> dict[str, str]:
    heading = next(
        (
            node
            for node in list(soup.find_all(["h2", "h3", "button", "p", "span"]))
            if _normalized_candidate_text(node.get_text(" ", strip=True)).lower()
            in {
                "select a size",
                "select an option",
                "pricing and availability",
            }
        ),
        None,
    )
    if heading is None:
        return {}

    container = heading.parent
    text = ""
    while container is not None:
        text = _normalized_candidate_text(container.get_text(" ", strip=True))
        if any(
            token in text for token in ("Pack Size", "SKU", "Availability", "Price")
        ):
            break
        container = container.parent
    if not text:
        return {}

    normalized_text = re.sub(r"\s+", " ", text)
    candidates: dict[str, str] = {}
    pack_match = re.search(
        r"Pack Size\s+(?P<value>.+?)\s+SKU(?:\s|$)", normalized_text, re.I
    )
    if pack_match:
        pack_value = _normalized_candidate_text(pack_match.group("value"))
        if pack_value:
            candidates["pack_size"] = pack_value
            candidates.setdefault("size", pack_value)
    sku_match = re.search(r"SKU\s+(?P<value>[A-Z0-9-]{3,})", normalized_text, re.I)
    if sku_match:
        candidates["sku"] = _normalized_candidate_text(sku_match.group("value"))
    availability_match = re.search(
        r"Availability\s+(?P<value>.+?)\s+Price(?:\s|$)", normalized_text, re.I
    )
    if availability_match:
        availability = _normalized_candidate_text(availability_match.group("value"))
        if availability:
            candidates["availability"] = availability
    price_match = re.search(r"Price\s+(?P<value>[$€£₹]\s*[\d,.]+)", normalized_text)
    if price_match:
        price_text = _normalized_candidate_text(price_match.group("value"))
        if price_text:
            candidates["price"] = price_text
            symbol = price_text[0]
            candidates["currency"] = {
                "$": "USD",
                "£": "GBP",
                "€": "EUR",
                "₹": "INR",
            }.get(symbol, "")
    return {key: value for key, value in candidates.items() if value}


def _extract_structured_field_value(payload: object, field_name: str) -> str | None:
    spec_map = _extract_structured_spec_map(payload)
    if not spec_map:
        return None
    if field_name == "specifications":
        return (
            SEMANTIC_AGGREGATE_SEPARATOR.join(
                f"{label}: {value}" for label, value in spec_map.items()
            )
            or None
        )
    if field_name == "dimensions":
        dimension_pairs = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        return SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_pairs) or None
    return spec_map.get(normalize_requested_field(field_name)) or spec_map.get(
        field_name
    )


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


_NETWORK_PAYLOAD_NOISE_URL_PATTERNS = re.compile(
    r"geolocation|geoip|geo/|/geo\b|"
    r"\banalytics\b|tracking|telemetry|"
    r"klarna\.com|affirm\.com|afterpay\.com|"
    r"olapic-cdn\.com|"
    r"livechat|zendesk\.com|intercom\.io|"
    r"facebook\.com|google-analytics|googletagmanager|"
    r"sentry\.io|datadome|px\.ads|"
    r"cdn-cgi/|captcha",
    re.IGNORECASE,
)


def _structured_source_payloads(
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
) -> list[tuple[str, object]]:
    sources: list[tuple[str, object]] = [("next_data", next_data)]
    sources.extend(("hydrated_state", payload) for payload in hydrated_states)
    sources.extend(("embedded_json", payload) for payload in embedded_json)
    for payload in network_payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "").lower()
        if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
            continue
        sources.append(("network_intercept", payload.get("body")))
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
                title = normalize_requested_field(
                    _normalized_candidate_text(row.get("title"))
                )
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
