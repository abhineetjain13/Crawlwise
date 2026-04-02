# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from lxml import etree, html as lxml_html

from app.services.discover.service import DiscoveryManifest
from app.services.knowledge_base.store import get_canonical_fields, get_domain_mapping, get_selector_defaults


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
        (candidates, source_trace) — candidates maps field -> list of {value, source, confidence}
    """
    soup = BeautifulSoup(html, "html.parser")
    tree = _build_xpath_tree(html)
    candidates: dict[str, list[dict]] = {}
    source_trace: dict[str, list[dict]] = {}
    target_fields = set(get_canonical_fields(surface)) | set(additional_fields)
    domain = _domain(url)
    contract_by_field = _index_extraction_contract(extraction_contract or [])

    for field_name in target_fields:
        rows: list[dict] = []

        # 0. User-provided extraction contract (highest precedence)
        contract_rule = contract_by_field.get(field_name)
        if contract_rule:
            xpath_value = _extract_xpath_value(tree, contract_rule.get("xpath", ""))
            if xpath_value:
                rows.append({"value": xpath_value, "source": "contract_xpath", "confidence": 0.99})
            regex_value = _extract_regex_value(html, contract_rule.get("regex", ""))
            if regex_value:
                rows.append({"value": regex_value, "source": "contract_regex", "confidence": 0.98})

        # 1. Adapter data (rank 1, highest confidence)
        for record in manifest.adapter_data:
            if isinstance(record, dict) and field_name in record and record[field_name]:
                rows.append({"value": record[field_name], "source": "adapter", "confidence": 0.95})

        # 2. Network payloads (rank 2)
        for payload in manifest.network_payloads:
            body = payload.get("body", {})
            if isinstance(body, dict):
                val = _deep_get(body, field_name)
                if val:
                    rows.append({"value": val, "source": "network_intercept", "confidence": 0.90})

        # 3. __NEXT_DATA__ (rank 3)
        if manifest.next_data:
            val = _deep_get(manifest.next_data, field_name)
            if val:
                rows.append({"value": val, "source": "next_data", "confidence": 0.88})

        # 4. JSON-LD (rank 4)
        for payload in manifest.json_ld:
            if isinstance(payload, dict) and field_name in payload and payload[field_name]:
                rows.append({"value": payload[field_name], "source": "json_ld", "confidence": 0.90})

        # 5. Microdata/RDFa (rank 5)
        for item in manifest.microdata:
            if isinstance(item, dict) and field_name in item and item[field_name]:
                rows.append({"value": item[field_name], "source": "microdata", "confidence": 0.85})

        # 6. Saved domain selectors (rank 6)
        selectors = get_selector_defaults(domain, field_name)
        for selector in selectors:
            if selector.get("selector_type") != "css":
                continue
            node = soup.select_one(selector.get("selector", ""))
            if node:
                rows.append({"value": node.get_text(" ", strip=True), "source": "selector", "confidence": 0.80})

        # 7. Deterministic DOM patterns (rank 7)
        dom_value = _dom_pattern(soup, field_name)
        if dom_value:
            rows.append({"value": dom_value, "source": "dom", "confidence": 0.60})

        if rows:
            candidates[field_name] = rows
            source_trace[field_name] = rows

    # Apply domain field mappings
    mappings = get_domain_mapping(domain, surface)
    return candidates, {"candidates": source_trace, "mapping_hint": mappings}


def _dom_pattern(soup: BeautifulSoup, field_name: str) -> str | None:
    """Try common DOM patterns for well-known fields."""
    patterns: dict[str, str] = {
        "title": "h1, title, [itemprop='name']",
        "price": "[itemprop='price'], .price, .product-price",
        "sale_price": ".sale-price, .discount-price, [data-sale-price]",
        "description": "meta[name='description'], [itemprop='description'], .product-description",
        "brand": "[itemprop='brand'], .brand, .product-brand",
        "image_url": "[itemprop='image'], meta[property='og:image']",
        "rating": "[itemprop='ratingValue']",
        "review_count": "[itemprop='reviewCount']",
        "sku": "[itemprop='sku']",
        "availability": "[itemprop='availability']",
        "category": "[itemprop='category'], nav.breadcrumb li:last-child",
        "company": ".company-name, [itemprop='hiringOrganization'] [itemprop='name']",
        "location": ".job-location, [itemprop='jobLocation'] [itemprop='name']",
        "salary": ".salary, [itemprop='baseSalary']",
        "job_type": "[itemprop='employmentType']",
        "apply_url": "a[data-apply-url], a.apply-button",
    }
    selector = patterns.get(field_name)
    if not selector:
        return None
    node = soup.select_one(selector)
    if not node:
        return None
    # For meta tags, get content attribute
    if node.name == "meta":
        return node.get("content", "")
    # For links, prefer href
    if field_name in ("apply_url", "image_url", "url") and node.get("href"):
        return node.get("href", "")
    if field_name == "image_url" and node.get("src"):
        return node.get("src", "")
    return node.get("content") or node.get_text(" ", strip=True)


def _deep_get(data: dict, key: str, max_depth: int = 5) -> object | None:
    """Recursively search a nested dict for a key."""
    if max_depth <= 0:
        return None
    if key in data:
        return data[key]
    for v in data.values():
        if isinstance(v, dict):
            result = _deep_get(v, key, max_depth - 1)
            if result is not None:
                return result
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    result = _deep_get(item, key, max_depth - 1)
                    if result is not None:
                        return result
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
