# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from lxml import etree, html as lxml_html

from app.services.discover.service import DiscoveryManifest
from app.services.pipeline_config import DOM_PATTERNS, FIELD_ALIASES
from app.services.requested_field_policy import expand_requested_fields
from app.services.semantic_detail_extractor import extract_semantic_detail_data, resolve_requested_field_values
from app.services.knowledge_base.store import get_canonical_fields, get_domain_mapping, get_selector_defaults
from app.services.xpath_service import build_absolute_xpath, extract_selector_value


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
                val = _coerce_candidate_value(_deep_get_aliases(body, field_name))
                if val is not None:
                    rows.append({"value": val, "source": "network_intercept"})

        # 3. Hydrated app state / __NEXT_DATA__ (rank 3)
        for state in manifest._hydrated_states:
            val = _coerce_candidate_value(_deep_get_aliases(state, field_name))
            if val is not None:
                rows.append({"value": val, "source": "hydrated_state"})
                break
        if manifest.next_data:
            val = _coerce_candidate_value(_deep_get_aliases(manifest.next_data, field_name))
            if val is not None:
                rows.append({"value": val, "source": "next_data"})

        # 4. JSON-LD (rank 4)
        for payload in manifest.json_ld:
            if isinstance(payload, dict):
                val = _coerce_candidate_value(_deep_get_aliases(payload, field_name))
                if val is not None:
                    rows.append({"value": val, "source": "json_ld"})

        # 5. Microdata/RDFa (rank 5)
        for item in manifest.microdata:
            if isinstance(item, dict):
                val = _coerce_candidate_value(_deep_get_aliases(item, field_name))
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
            candidates[field_name] = rows
            source_trace[field_name] = rows

    # Apply domain field mappings
    mappings = get_domain_mapping(domain, surface)
    return candidates, {"candidates": source_trace, "mapping_hint": mappings, "semantic": semantic}


def _dom_pattern(soup: BeautifulSoup, field_name: str) -> dict | None:
    """Try common DOM patterns for well-known fields."""
    selector = DOM_PATTERNS.get(field_name)
    if not selector:
        return None
    node = soup.select_one(selector)
    if not node:
        return None
    value: str | None = None
    # For meta tags, get content attribute
    if node.name == "meta":
        value = node.get("content", "")
    # For links, prefer href
    elif field_name in ("apply_url", "image_url", "url") and node.get("href"):
        value = node.get("href", "")
    elif field_name == "image_url" and node.get("src"):
        value = node.get("src", "")
    else:
        value = node.get("content") or node.get_text(" ", strip=True)
    if not value:
        return None
    return {
        "value": value,
        "source": "dom",
        "xpath": build_absolute_xpath(node),
        "css_selector": selector,
        "regex": None,
        "sample_value": value,
    }


def _deep_get(data: object, key: str, max_depth: int = 5) -> object | None:
    """Recursively search a nested dict for a key."""
    if max_depth <= 0:
        return None
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for v in data.values():
            result = _deep_get(v, key, max_depth - 1)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _deep_get(item, key, max_depth - 1)
            if result is not None:
                return result
    return None


def _deep_get_aliases(data: object, field_name: str, max_depth: int = 5) -> object | None:
    aliases = [field_name, *FIELD_ALIASES.get(field_name, [])]
    seen: set[str] = set()
    for alias in aliases:
        key = str(alias or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result = _deep_get(data, key, max_depth)
        if result not in (None, "", [], {}):
            return result
    return None


def _coerce_candidate_value(value: object) -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        scalars: list[str] = []
        for item in value[:5]:
            coerced = _coerce_candidate_value(item)
            if isinstance(coerced, (str, int, float, bool)):
                text = str(coerced).strip()
                if text:
                    scalars.append(text)
        if scalars:
            return " | ".join(dict.fromkeys(scalars))
        return None
    if isinstance(value, dict):
        for key in ("value", "text", "content", "description", "sentence", "summary", "title", "name", "label"):
            candidate = value.get(key)
            coerced = _coerce_candidate_value(candidate)
            if coerced is not None:
                return coerced
        return None
    return None


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
