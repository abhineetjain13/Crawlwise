# DOM-level extraction — label/value patterns, breadcrumb, URL scoping, adapter scoping.
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    CANDIDATE_DEEP_ALIAS_LIST_SCAN_LIMIT,
    CANDIDATE_DESCRIPTION_FALLBACK_CONTENT_SELECTORS,
    CANDIDATE_DESCRIPTION_META_SELECTORS,
    DOM_PATTERNS,
    JSONLD_STRUCTURAL_KEYS,
    NESTED_NON_PRODUCT_KEYS,
)
from app.services.config.field_mappings import REQUESTED_FIELD_ALIASES, get_surface_field_aliases
from app.services.config.extraction_rules import LISTING_DESCRIPTION_CANDIDATE_FIELDS
from app.services.extract.candidate_processing import (
    _embedded_blob_payload,
    _looks_like_ga_data_layer,
    _normalized_candidate_text,
    coerce_field_candidate_value,
    normalize_html_rich_text,
)
from app.services.extract.field_classifier import _field_alias_tokens, _normalized_field_token
from app.services.xpath_service import build_absolute_xpath

# Constant re-used by _build_label_value_text_sources
_HTML_LABEL_VALUE_FALLBACK_BLOCKED_FIELDS = frozenset(
    {"description", "features", "materials", "specifications", "product_attributes"}
)

# ---------------------------------------------------------------------------
# URL / adapter scoping
# ---------------------------------------------------------------------------


def _scoped_url_key(value: object) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.netloc:
        return ""
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"


def _scoped_record_identifiers(record: dict[str, object]) -> set[str]:
    identifiers: set[str] = set()
    for key in ("sku", "product_id", "job_id", "variant_id", "id", "handle"):
        value = str(record.get(key) or "").strip().lower()
        if value:
            identifiers.add(value)
    record_url = str(record.get("url") or record.get("source_url") or "").strip()
    if record_url:
        scoped_url = _scoped_url_key(record_url)
        if scoped_url:
            identifiers.add(scoped_url)
        path_parts = [part for part in urlsplit(record_url).path.split("/") if part]
        if path_parts:
            identifiers.add(path_parts[-1].lower())
    return identifiers


def _scope_adapter_records_for_url(url: str, adapter_records: list[dict]) -> list[dict]:
    if not adapter_records:
        return []
    scoped: list[dict] = []
    current_url_key = _scoped_url_key(url)
    current_identifiers = _scoped_record_identifiers({"url": url})
    for record in adapter_records:
        if not isinstance(record, dict):
            continue
        record_url = str(record.get("url") or record.get("source_url") or "").strip()
        if (
            record_url
            and current_url_key
            and _scoped_url_key(record_url) != current_url_key
        ):
            continue
        record_identifiers = _scoped_record_identifiers(record)
        if (
            current_identifiers
            and record_identifiers
            and current_identifiers.isdisjoint(record_identifiers)
        ):
            continue
        scoped.append(record)
    return scoped


def _scoped_semantic_payload(
    semantic: dict,
    *,
    url: str,
    adapter_records: list[dict],
) -> dict:
    payload = semantic if isinstance(semantic, dict) else {}
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    if not scope:
        return payload
    if _scoped_url_key(scope.get("url")) not in {"", _scoped_url_key(url)}:
        return {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
            "scope": scope,
        }
    scope_ids = {
        str(value).strip().lower()
        for value in (scope.get("product_ids") or [])
        if str(value).strip()
    }
    current_ids = _scoped_record_identifiers({"url": url})
    for record in adapter_records:
        current_ids.update(_scoped_record_identifiers(record))
    if scope_ids and current_ids and scope_ids.isdisjoint(current_ids):
        return {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
            "scope": scope,
        }
    return payload


# ---------------------------------------------------------------------------
# Label/value text pattern extraction
# ---------------------------------------------------------------------------


def extract_label_value_from_text(
    field_name: str,
    text_sources: list[str],
    html: str,
    *,
    surface: str = "",
) -> str | None:
    """Search description text and HTML-derived text from the raw HTML for label/value patterns."""
    label_variants = _label_value_variants(field_name, surface=surface)
    combined_text_sources = list(text_sources)
    if html and field_name not in _HTML_LABEL_VALUE_FALLBACK_BLOCKED_FIELDS:
        combined_text_sources.append(normalize_html_rich_text(html))

    for text in combined_text_sources:
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
        re.escape(variant) + r"\s*:\s*(.+?)(?=\s+[A-Za-z]+:|\s+\(|\n|$|[.]\s|\u2022)",
        re.IGNORECASE,
    )


def _label_value_variants(field_name: str, *, surface: str = "") -> list[str]:
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
    for alias in get_surface_field_aliases(surface).get(field_name, []):
        _append(alias)
    for alias in REQUESTED_FIELD_ALIASES.get(field_name, []):
        _append(alias)
    return variants


# ---------------------------------------------------------------------------
# DOM pattern matching
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Structured source traversal
# ---------------------------------------------------------------------------


def _deep_get_all_aliases(
    data: object, field_name: str, *, surface: str = "", max_depth: int = 5
) -> list[object]:
    matches: list[object] = []
    alias_tokens = _field_alias_tokens(field_name, surface=surface)
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
                normalized_key = _normalized_field_token(current_key)
                if normalized_key in NESTED_NON_PRODUCT_KEYS:
                    continue
                _collect(value, depth - 1, parent_key=current_key)
        elif isinstance(node, list):
            for item in node[:CANDIDATE_DEEP_ALIAS_LIST_SCAN_LIMIT]:
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
    source_metadata: dict[str, object] | None = None,
    surface: str = "",
) -> None:
    actual_payload = _embedded_blob_payload(payload)
    if _field_is_type(field_name, "entity_name") and _looks_like_ga_data_layer(
        actual_payload
    ):
        return
    for match in _deep_get_all_aliases(
        actual_payload,
        field_name,
        surface=surface,
    ):
        value = coerce_field_candidate_value(field_name, match, base_url=base_url)
        if value is not None:
            row = {"value": value, "source": source}
            if source_metadata:
                row.update(source_metadata)
            rows.append(row)


# ---------------------------------------------------------------------------
# Label/value text source building
# ---------------------------------------------------------------------------


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
    # Import here to avoid import-time circular reference with service.py
    from app.services.extract.service import _NETWORK_PAYLOAD_NOISE_URL_PATTERNS

    text_sources: list[str] = []
    seen: set[str] = set()

    def _append_text(value: object) -> None:
        normalized = _normalized_candidate_text(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        text_sources.append(normalized)

    for selector in CANDIDATE_DESCRIPTION_META_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get("content"))

    for desc_field in LISTING_DESCRIPTION_CANDIDATE_FIELDS:
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

    for selector in CANDIDATE_DESCRIPTION_FALLBACK_CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get_text("\n", strip=True))
            break

    return text_sources


# ---------------------------------------------------------------------------
# Breadcrumb extraction
# ---------------------------------------------------------------------------


def _extract_breadcrumb_category(soup: BeautifulSoup) -> str | None:
    selectors = (
        "nav[aria-label*='breadcrumb' i] a",
        ".breadcrumb a",
        "[class*='breadcrumb' i] a",
        "[itemtype*='BreadcrumbList'] [itemprop='name']",
    )
    parts: list[str] = []
    for selector in selectors:
        nodes = soup.select(selector)
        if not nodes:
            continue
        candidate_parts = [
            _normalized_candidate_text(node.get_text(" ", strip=True))
            for node in nodes
            if _normalized_candidate_text(node.get_text(" ", strip=True))
        ]
        if candidate_parts:
            parts = candidate_parts
            break
    if not parts:
        return None
    if parts and parts[0].lower() == "home":
        parts = parts[1:]
    title_text = _normalized_candidate_text(
        (
            soup.select_one("main h1")
            or soup.select_one("article h1")
            or soup.select_one("h1")
        ).get_text(" ", strip=True)
        if (
            soup.select_one("main h1")
            or soup.select_one("article h1")
            or soup.select_one("h1")
        )
        else ""
    )
    if parts and title_text and _breadcrumb_item_matches_title(parts[-1], title_text):
        parts = parts[:-1]
    if not parts:
        return None
    return " > ".join(parts)


def _breadcrumb_item_matches_title(item: str, title: str) -> bool:
    def _normalize(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
        return " ".join(normalized.split())

    normalized_item = _normalize(item)
    normalized_title = _normalize(title)
    if not normalized_item or not normalized_title:
        return False
    if normalized_item == normalized_title:
        return True
    if normalized_item in normalized_title or normalized_title in normalized_item:
        return True
    item_tokens = set(normalized_item.split())
    title_tokens = set(normalized_title.split())
    if not item_tokens or not title_tokens:
        return False
    overlap = len(item_tokens & title_tokens)
    return overlap >= max(2, min(len(item_tokens), len(title_tokens)))


# ---------------------------------------------------------------------------
# _field_is_type (needed by _append_source_candidates — kept here to avoid
# importing from service.py and creating a circular dependency)
# ---------------------------------------------------------------------------


def _field_is_type(field_name: str, type_key: str) -> bool:
    """Thin re-implementation for the entity_name gate used in _append_source_candidates."""
    from app.services.config.extraction_rules import CANDIDATE_FIELD_GROUPS

    if type_key == "entity_name":
        return field_name in CANDIDATE_FIELD_GROUPS.get("entity_name", set())
    # Fallback to service for other type keys (called rarely from dom_extraction)
    from app.services.extract.service import _field_is_type as _svc_field_is_type

    return _svc_field_is_type(field_name, type_key)
