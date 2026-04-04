# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from lxml import etree, html as lxml_html

from app.services.discover.service import DiscoveryManifest
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
    CANDIDATE_PRICE_TOKENS,
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
    FEATURE_SECTION_ALIASES,
    FIELD_ALIASES,
    SEMANTIC_AGGREGATE_SEPARATOR,
)
from app.services.requested_field_policy import expand_requested_fields, normalize_requested_field
from app.services.semantic_detail_extractor import extract_semantic_detail_data, resolve_requested_field_values
from app.services.knowledge_base.store import get_canonical_fields, get_domain_mapping, get_selector_defaults
from app.services.xpath_service import build_absolute_xpath, extract_selector_value

_UI_NOISE_TOKEN_RE = re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_NOISE_TOKEN_PATTERN else None
_UI_ICON_TOKEN_RE = re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE) if CANDIDATE_UI_ICON_TOKEN_PATTERN else None
_SCRIPT_NOISE_RE = re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE) if CANDIDATE_SCRIPT_NOISE_PATTERN else None
_PROMO_ONLY_TITLE_RE = re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE) if CANDIDATE_PROMO_ONLY_TITLE_PATTERN else None


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    manifest: DiscoveryManifest,
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Extract candidate values for each target field.

    Sources are checked in deterministic priority order and every discovered
    value is preserved as its own candidate row.

    Returns:
        (candidates, source_trace) — candidates maps field -> list of {value, source}
    """
    soup = BeautifulSoup(html, "html.parser")
    tree = _build_xpath_tree(html)
    candidates: dict[str, list[dict]] = {}
    source_trace: dict[str, list[dict]] = {}
    target_fields = sorted(set(get_canonical_fields(surface)) | set(expand_requested_fields(additional_fields)))
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
            body = payload.get("body", {}) if isinstance(payload, dict) else {}
            if isinstance(body, (dict, list)):
                _append_source_candidates(rows, field_name, body, "network_intercept", base_url=url)

        # 3. Hydrated app state / __NEXT_DATA__ (rank 3)
        for state in manifest._hydrated_states:
            _append_source_candidates(rows, field_name, state, "hydrated_state", base_url=url)
        for payload in manifest.embedded_json:
            _append_source_candidates(rows, field_name, payload, "embedded_json", base_url=url)
        if manifest.next_data:
            _append_source_candidates(rows, field_name, manifest.next_data, "next_data", base_url=url)
        rows.extend(_structured_manifest_candidates(manifest, field_name))

        # 4. JSON-LD (rank 4)
        for payload in manifest.json_ld:
            if isinstance(payload, dict):
                _append_source_candidates(rows, field_name, payload, "json_ld", base_url=url)

        # 5. Microdata/RDFa (rank 5)
        for item in manifest.microdata:
            if isinstance(item, dict):
                _append_source_candidates(rows, field_name, item, "microdata", base_url=url)

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
            filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=url)
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
        filtered_rows = _finalize_candidate_rows(field_name, merged_rows, base_url=url)
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


def _finalize_candidate_rows(field_name: str, rows: list[dict], *, base_url: str = "") -> list[dict]:
    filtered: list[dict] = []
    filtered_index: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        value = coerce_field_candidate_value(field_name, row.get("value"), base_url=base_url)
        if value in (None, "", [], {}):
            value = _normalized_candidate_value(row.get("value"))
        if value in (None, "", [], {}):
            continue
        source = str(row.get("source") or "").strip() or "candidate"
        normalized = _normalized_candidate_text(value)
        key = (source, normalized)
        if key in seen:
            existing = filtered[filtered_index[key]]
            for metadata_key, metadata_value in row.items():
                if metadata_key == "value":
                    continue
                if existing.get(metadata_key) in (None, "", [], {}) and metadata_value not in (None, "", [], {}):
                    existing[metadata_key] = metadata_value
            continue
        seen.add(key)
        filtered_index[key] = len(filtered)
        filtered.append({**row, "value": value})
    filtered.sort(key=lambda row: _candidate_sort_key(field_name, row), reverse=True)
    return filtered


def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalized_candidate_value(value: object) -> object | None:
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        return cleaned or None
    return value if value not in (None, "", [], {}) else None


def _deep_get_all(data: object, key: str, max_depth: int = 5) -> list[object]:
    if max_depth <= 0 or data in (None, "", [], {}):
        return []
    matches: list[object] = []

    def _collect(node: object, depth: int) -> None:
        if depth <= 0:
            return
        if isinstance(node, dict):
            if key in node and node[key] not in (None, "", [], {}):
                matches.append(node[key])
            for value in node.values():
                _collect(value, depth - 1)
        elif isinstance(node, list):
            for item in node:
                _collect(item, depth - 1)

    _collect(data, max_depth)
    return matches


def _deep_get_all_aliases(data: object, field_name: str, max_depth: int = 5) -> list[object]:
    matches: list[object] = []
    alias_tokens = _field_alias_tokens(field_name)
    if not alias_tokens or max_depth <= 0:
        return matches

    def _collect(node: object, depth: int) -> None:
        if depth <= 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            for current_key, value in node.items():
                if _normalized_field_token(current_key) in alias_tokens and value not in (None, "", [], {}):
                    matches.append(value)
                _collect(value, depth - 1)
        elif isinstance(node, list):
            for item in node[:40]:
                _collect(item, depth - 1)

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
    for match in _deep_get_all_aliases(payload, field_name):
        value = coerce_field_candidate_value(field_name, match, base_url=base_url)
        if value is not None:
            rows.append({"value": value, "source": source})


def coerce_field_candidate_value(field_name: str, value: object, *, base_url: str = "") -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        parsed = _parse_json_like_value(cleaned)
        if parsed is not None:
            parsed_value = coerce_field_candidate_value(field_name, parsed, base_url=base_url)
            if parsed_value not in (None, "", [], {}):
                return parsed_value
        if _is_image_primary_field(field_name):
            images = _extract_image_urls(cleaned, base_url=base_url)
            return images[0] if images else None
        if _is_image_collection_field(field_name):
            images = _extract_image_urls(cleaned, base_url=base_url)
            return ", ".join(images) if images else None
        if _is_url_field(field_name):
            resolved = _resolve_candidate_url(cleaned, base_url)
            return resolved or None
        if _is_currency_field(field_name):
            match = re.search(r"\b[A-Z]{3}\b", cleaned.upper())
            return match.group(0) if match else None
        if _is_category_field(field_name):
            lowered = cleaned.lower()
            if lowered in CANDIDATE_GENERIC_CATEGORY_VALUES | {
                "guest",
                "max_discount",
                "brand",
                "offer",
                "website",
                "web site",
                "breadcrumblist",
                "listitem",
            } or "schema.org" in lowered:
                return None
            return cleaned
        if _is_numeric_field(field_name):
            numeric = re.search(r"\d[\d,.]*", cleaned)
            return cleaned if numeric else None
        if _is_availability_field(field_name):
            return cleaned if cleaned.lower() != "availability" else None
        if _is_title_field(field_name):
            cleaned = _strip_ui_noise(cleaned)
            if not cleaned or cleaned.lower() in CANDIDATE_GENERIC_TITLE_VALUES:
                return None
            if _PROMO_ONLY_TITLE_RE and _PROMO_ONLY_TITLE_RE.match(cleaned):
                return None
            if not re.search(r"[A-Za-z]", cleaned):
                return None
            return cleaned
        if _is_description_field(field_name) or _is_entity_name_field(field_name):
            cleaned = _strip_ui_noise(cleaned)
        return cleaned or None
    if isinstance(value, (int, float)) and _is_title_field(field_name):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
            images = _extract_image_urls(value, base_url=base_url)
            if not images:
                return None
            return images[0] if _is_image_primary_field(field_name) else ", ".join(images)
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
        if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
            images = _extract_image_urls(value, base_url=base_url)
            if not images:
                return None
            return images[0] if _is_image_primary_field(field_name) else ", ".join(images)
        for key in ("value", "amount", "code", "text", "content", "description", "sentence", "summary", "title", "name", "label"):
            candidate = value.get(key)
            coerced = coerce_field_candidate_value(field_name, candidate, base_url=base_url)
            if coerced is not None:
                return coerced
        return None
    return None


def _pick_best_nested_candidate(field_name: str, values: list[object]) -> object | None:
    rows = [{"value": value, "source": "nested"} for value in values if value not in (None, "", [], {})]
    if not rows:
        return None
    rows.sort(key=lambda row: _candidate_sort_key(field_name, row), reverse=True)
    return rows[0]["value"]


def _field_alias_tokens(field_name: str) -> set[str]:
    aliases = [field_name, *FIELD_ALIASES.get(field_name, [])]
    return {
        token
        for alias in aliases
        if (token := _normalized_field_token(alias))
    }


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
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _resolve_candidate_url(value: str, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        return f"https:{candidate}"
    if candidate.startswith(("http://", "https://")):
        return candidate
    if candidate.startswith("/"):
        return urljoin(base_url, candidate) if base_url else candidate
    return urljoin(base_url, candidate) if re.search(r"^[A-Za-z0-9][^ ]*/[^ ]+$", candidate) and base_url else ""


def _extract_image_urls(value: object, *, base_url: str = "") -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = _resolve_candidate_url(candidate, base_url)
        if not resolved:
            return
        lowered = resolved.lower()
        path = urlparse(resolved).path.lower()
        if any(token in lowered for token in ("logo", "sprite", "icon", "badge", "favicon")):
            return
        if not (
            path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"))
            or any(token in lowered for token in ("/image", "/images/", "/img", "image=", "im/"))
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


_SOURCE_RANK = {
    "contract_xpath": 11,
    "contract_regex": 10,
    "adapter": 9,
    "network_intercept": 8,
    "hydrated_state": 7,
    "embedded_json": 7,
    "next_data": 7,
    "json_ld": 6,
    "microdata": 5,
    "semantic_section": 4,
    "semantic_spec": 4,
    "selector": 3,
    "dom": 2,
    "llm_xpath": 1,
}


def _candidate_sort_key(field_name: str, row: dict) -> tuple[int, int]:
    value = row.get("value")
    source = str(row.get("source") or "").strip()
    return (_field_quality_score(field_name, value), _SOURCE_RANK.get(source, 0))


def _field_quality_score(field_name: str, value: object) -> int:
    text = _normalized_candidate_text(value)
    if not text:
        return 0

    if _is_title_field(field_name):
        score = 10
        lowered = text.lower()
        if len(text) < 10:
            score -= 8
        if 4 <= len(text) <= 120:
            score += 8
        if re.search(r"[A-Za-z]", text):
            score += 6
        if len(text) <= 80:
            score += 4
        if any(token in lowered for token in ("discover this", "purchase", "shop ", "buy now", "sigma-aldrich.com")):
            score -= 12
        if text.count(".") >= 2 or len(text.split()) > 18:
            score -= 8
        if lowered in {"wayfair", "home", "department navigation"}:
            score -= 15
        return score

    if _is_description_field(field_name):
        score = 10
        if len(text) >= 60:
            score += 10
        if len(text) >= 180:
            score += 4
        if "<" in text or ">" in text:
            score -= 2
        if len(text.split()) <= 6:
            score -= 10
        return score

    if _is_entity_name_field(field_name):
        score = 10
        if 2 <= len(text) <= 50:
            score += 8
        if len(text.split()) <= 5:
            score += 4
        if re.search(r"\.(com|net|org)\b", text.lower()):
            score -= 8
        return score

    if _is_numeric_field(field_name):
        return 20 if re.search(r"\d", text) else 0

    if _is_currency_field(field_name):
        return 25 if re.fullmatch(r"[A-Z]{3}", text.upper()) else 0

    if _is_image_primary_field(field_name) or _is_image_collection_field(field_name) or _is_url_field(field_name):
        return 25 if text.startswith(("http://", "https://")) else 0

    if _is_availability_field(field_name):
        return 0 if text.lower() == "availability" else (16 if len(text) <= 48 else 6)

    if _is_identifier_field(field_name):
        score = 12
        if 2 <= len(text) <= 64:
            score += 8
        if " " in text and len(text.split()) > 4:
            score -= 8
        return score

    if _is_category_field(field_name):
        lowered = text.lower()
        if lowered in CANDIDATE_GENERIC_CATEGORY_VALUES | {
            "guest",
            "max_discount",
            "brand",
            "website",
            "web site",
            "offer",
            "breadcrumblist",
            "listitem",
        }:
            return 0
        return 12

    return 10 + min(len(text), 80) // 16


def _field_in_group(field_name: str, group_name: str) -> bool:
    return field_name in CANDIDATE_FIELD_GROUPS.get(group_name, set())


def _field_token(field_name: str) -> str:
    return _normalized_field_token(field_name)


def _field_has_any_token(field_name: str, tokens: tuple[str, ...]) -> bool:
    normalized = _field_token(field_name)
    return any(_normalized_field_token(token) in normalized for token in tokens if token)


def _is_image_collection_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    return _field_in_group(field_name, "image_collection") or any(token in normalized for token in ("images", "gallery", "photos", "media"))


def _is_image_primary_field(field_name: str) -> bool:
    return _field_in_group(field_name, "image_primary") or (
        _field_has_any_token(field_name, CANDIDATE_IMAGE_TOKENS) and not _is_image_collection_field(field_name)
    )


def _is_url_field(field_name: str) -> bool:
    normalized = _field_token(field_name)
    if _is_image_primary_field(field_name) or _is_image_collection_field(field_name):
        return False
    return _field_in_group(field_name, "url") or any(normalized.endswith(_normalized_field_token(suffix)) for suffix in CANDIDATE_URL_SUFFIXES)


def _is_currency_field(field_name: str) -> bool:
    return _field_in_group(field_name, "currency") or _field_has_any_token(field_name, CANDIDATE_CURRENCY_TOKENS)


def _is_numeric_field(field_name: str) -> bool:
    return (
        _field_in_group(field_name, "numeric")
        or _field_has_any_token(field_name, CANDIDATE_PRICE_TOKENS)
        or _field_has_any_token(field_name, CANDIDATE_RATING_TOKENS)
        or _field_has_any_token(field_name, CANDIDATE_REVIEW_COUNT_TOKENS)
    )


def _is_availability_field(field_name: str) -> bool:
    return _field_in_group(field_name, "availability") or _field_has_any_token(field_name, CANDIDATE_AVAILABILITY_TOKENS)


def _is_category_field(field_name: str) -> bool:
    return _field_in_group(field_name, "category") or _field_has_any_token(field_name, CANDIDATE_CATEGORY_TOKENS)


def _is_title_field(field_name: str) -> bool:
    return _field_in_group(field_name, "title")


def _is_description_field(field_name: str) -> bool:
    return _field_in_group(field_name, "description") or _field_has_any_token(field_name, CANDIDATE_DESCRIPTION_TOKENS)


def _is_entity_name_field(field_name: str) -> bool:
    return _field_in_group(field_name, "entity_name")


def _is_identifier_field(field_name: str) -> bool:
    return _field_in_group(field_name, "identifier") or _field_has_any_token(field_name, CANDIDATE_IDENTIFIER_TOKENS)


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
    for phrase in CANDIDATE_UI_NOISE_PHRASES:
        if phrase:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text


def _structured_manifest_candidates(manifest: DiscoveryManifest, field_name: str) -> list[dict]:
    if field_name not in {"specifications", "dimensions"}:
        return []
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    sources: list[tuple[str, object]] = _structured_manifest_sources(manifest)
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


def _build_dynamic_semantic_rows(semantic: dict) -> dict[str, list[dict]]:
    sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    specifications = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}
    aggregates = semantic.get("aggregates") if isinstance(semantic.get("aggregates"), dict) else {}
    table_groups = semantic.get("table_groups") if isinstance(semantic.get("table_groups"), list) else []
    rows: dict[str, list[dict]] = {}

    for field_name, value in specifications.items():
        normalized = normalize_requested_field(field_name)
        if not normalized or value in (None, "", [], {}) or re.fullmatch(r"\d+(?:[_-]\d+)*", normalized):
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
            if not normalized or value in (None, "", [], {}) or re.fullmatch(r"\d+(?:[_-]\d+)*", normalized):
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
            if not normalized or re.fullmatch(r"\d+(?:[_-]\d+)*", normalized):
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
