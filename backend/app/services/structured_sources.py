from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup
from app.services.config.extraction_rules import HYDRATED_STATE_PATTERNS
from app.services.script_text_extractor import (
    extract_script_text_by_id,
    find_first_script_text_matching,
    find_script_regex_matches,
    iter_script_text_nodes,
)

try:
    import extruct
except ImportError:  # pragma: no cover - dependency may be absent in local test envs
    extruct = None

try:
    from w3lib.html import get_base_url
except ImportError:  # pragma: no cover - dependency may be absent in local test envs
    get_base_url = None

_STATE_SCRIPT_IDS = {
    "__next_data__": "__NEXT_DATA__",
    "__nuxt_data__": "__NUXT_DATA__",
}
_EMBEDDED_ASSIGNMENT_NAMES = (
    "data",
    "items",
    "listings",
    "posts",
    "products",
    "records",
    "results",
)
_NON_STATE_ASSIGNMENT_PATTERNS = (
    re.compile(r"ShopifyAnalytics\.meta\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"var\s+meta\s*=\s*(\{.*?\})\s*;", re.S),
)


def json_candidates(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value and isinstance(value["@graph"], list):
            return _resolve_json_ld_graph(value["@graph"])
        return [value]
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(json_candidates(item))
        return rows
    return []


def parse_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            rows.extend(json_ld_candidates(json.loads(raw)))
        except json.JSONDecodeError:
            continue
    return rows


def json_ld_candidates(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value and isinstance(value["@graph"], list):
            return _resolve_json_ld_graph(value["@graph"])
        return [value]
    if isinstance(value, list):
        nodes = [item for item in value if isinstance(item, dict)]
        if nodes and any(_looks_like_json_ld_node(node) for node in nodes):
            return _resolve_json_ld_graph(nodes)
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(json_ld_candidates(item))
        return rows
    return []


def _resolve_json_ld_graph(graph: list[Any]) -> list[dict[str, Any]]:
    nodes = [item for item in graph if isinstance(item, dict)]
    id_index = {
        str(node.get("@id") or "").strip(): node
        for node in nodes
        if str(node.get("@id") or "").strip()
    }
    resolved = [
        _resolve_json_ld_value(node, id_index=id_index, path=()) for node in nodes
    ]
    return sorted(
        resolved,
        key=lambda node: _json_ld_node_priority(node),
    )


def _resolve_json_ld_value(
    value: Any,
    *,
    id_index: dict[str, dict[str, Any]],
    path: tuple[str, ...],
) -> Any:
    if isinstance(value, list):
        return [
            _resolve_json_ld_value(item, id_index=id_index, path=path)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    node_id = str(value.get("@id") or "").strip()
    resolved: dict[str, Any] = {}
    if node_id and node_id in id_index and node_id not in path:
        base_node = id_index[node_id]
        if base_node is not value:
            resolved.update(
                _resolve_json_ld_value(
                    base_node,
                    id_index=id_index,
                    path=path + (node_id,),
                )
            )

    next_path = path + ((node_id,) if node_id else ())
    for key, item in value.items():
        if key == "@graph":
            continue
        if key == "@id" and node_id:
            resolved[key] = node_id
            continue
        resolved[str(key)] = _resolve_json_ld_value(
            item,
            id_index=id_index,
            path=next_path,
        )
    return resolved


def _json_ld_node_priority(node: dict[str, Any]) -> tuple[int, str]:
    raw_type = node.get("@type")
    if isinstance(raw_type, list):
        lowered_types = {str(item or "").strip().lower() for item in raw_type}
    else:
        lowered_types = {str(raw_type or "").strip().lower()}
    lowered_types.discard("")
    if lowered_types & {"product", "productgroup", "jobposting", "itemlist", "listitem"}:
        return (0, _json_ld_node_id(node))
    if lowered_types & {"offer", "aggregateoffer"}:
        return (1, _json_ld_node_id(node))
    if lowered_types & {"brand", "organization", "person"}:
        return (3, _json_ld_node_id(node))
    return (2, _json_ld_node_id(node))


def _json_ld_node_id(node: dict[str, Any]) -> str:
    return str(node.get("@id") or node.get("name") or "").strip().lower()


def _looks_like_json_ld_node(node: dict[str, Any]) -> bool:
    return any(key in node for key in ("@context", "@graph", "@id", "@type"))


def parse_microdata(
    soup: BeautifulSoup,
    html: str,
    page_url: str,
) -> list[dict[str, Any]]:
    rows = _extract_extruct_rows(html, page_url, syntax="microdata")
    if rows:
        return rows
    return _parse_microdata_fallback(soup, page_url)


def parse_opengraph(
    soup: BeautifulSoup,
    html: str,
    page_url: str,
) -> list[dict[str, Any]]:
    rows = _extract_extruct_rows(html, page_url, syntax="opengraph")
    if rows:
        return [_normalize_opengraph_row(row) for row in rows if isinstance(row, dict)]
    return _parse_opengraph_fallback(soup)


def parse_embedded_json(soup: BeautifulSoup, html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in iter_script_text_nodes(html):
        script_type = node.script_type.lower()
        node_id = node.script_id.lower()
        raw = node.text
        looks_json = script_type in {
            "application/json",
            "application/hal+json",
            "application/vnd.api+json",
        }
        if not looks_json:
            continue
        if node_id in _STATE_SCRIPT_IDS:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rows.extend(json_candidates(payload))
    for pattern in _NON_STATE_ASSIGNMENT_PATTERNS:
        for raw in find_script_regex_matches(html, pattern):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rows.extend(json_candidates(payload))
    for payload in _extract_generic_assignment_payloads(html):
        rows.extend(json_candidates(payload))
    return rows


def harvest_js_state_objects(soup: BeautifulSoup | None, html: str) -> dict[str, Any]:
    del soup
    state_objects: dict[str, Any] = {}
    for node_id, state_name in _STATE_SCRIPT_IDS.items():
        raw = extract_script_text_by_id(html, node_id)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if state_name == "__NUXT_DATA__":
            payload = _revive_nuxt_data_payload(payload)
        state_objects[state_name] = payload

    for state_name in _assignment_state_patterns():
        payload = _extract_assignment_payload(html, state_name)
        if payload is not None:
            state_objects[state_name] = payload
    return state_objects


def _assignment_state_patterns() -> tuple[str, ...]:
    values = []
    for value in list(HYDRATED_STATE_PATTERNS or []):
        normalized = str(value or "").strip()
        if normalized:
            values.append(normalized)
    return tuple(dict.fromkeys(values))


def _extract_assignment_payload(html: str, state_name: str) -> Any | None:
    pattern = re.compile(rf"(?:window\.)?{re.escape(state_name)}\s*=\s*", re.S)
    raw = find_first_script_text_matching(html, pattern)
    if raw is None:
        return None
    match = pattern.search(raw)
    if match is None:
        return None
    fragment = _balanced_json_fragment(raw[match.end() :])
    if not fragment:
        return None
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return None


def _extract_generic_assignment_payloads(html: str) -> list[Any]:
    payloads: list[Any] = []
    patterns = [
        re.compile(rf"(?:var|let|const)\s+{re.escape(name)}\s*=\s*", re.S)
        for name in _EMBEDDED_ASSIGNMENT_NAMES
    ]
    for node in iter_script_text_nodes(html):
        raw = node.text
        for pattern in patterns:
            for match in pattern.finditer(raw):
                fragment = _balanced_json_fragment(raw[match.end() :])
                if not fragment:
                    continue
                try:
                    payloads.append(json.loads(fragment))
                except json.JSONDecodeError:
                    continue
    return payloads


def _balanced_json_fragment(text: str) -> str:
    source = str(text or "")
    if not source:
        return ""
    start = next(
        (index for index, char in enumerate(source) if char in "{["),
        -1,
    )
    if start < 0:
        return ""

    opening = source[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return ""


def _extract_extruct_rows(html: str, page_url: str, *, syntax: str) -> list[dict[str, Any]]:
    if extruct is None or get_base_url is None:
        return []
    try:
        extracted = extruct.extract(
            html,
            base_url=get_base_url(html, page_url),
            syntaxes=[syntax],
            uniform=True,
        )
    except Exception:
        return []
    rows = extracted.get(syntax)
    return [row for row in list(rows or []) if isinstance(row, dict)]


def _parse_microdata_fallback(soup: BeautifulSoup, page_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in soup.find_all(attrs={"itemscope": True}):
        if _has_itemscope_ancestor(node):
            continue
        parsed = _parse_microdata_node(node, page_url)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_microdata_node(node: Any, page_url: str) -> dict[str, Any]:
    row: dict[str, Any] = {}
    item_type = str(node.get("itemtype") or "").strip()
    if item_type:
        row["@type"] = item_type
    for candidate in node.find_all(attrs={"itemprop": True}):
        if _belongs_to_nested_itemscope(candidate, node):
            continue
        property_name = str(candidate.get("itemprop") or "").strip()
        if not property_name:
            continue
        if candidate is not node and candidate.has_attr("itemscope"):
            value: object = _parse_microdata_node(candidate, page_url)
        else:
            value = _microdata_node_value(candidate, page_url)
        if value in (None, "", [], {}):
            continue
        _append_property_value(row, property_name, value)
    return row


def _microdata_node_value(node: Any, page_url: str) -> object:
    for attribute in ("content", "href", "src", "datetime"):
        value = node.get(attribute)
        if value not in (None, ""):
            if attribute in {"href", "src"}:
                from app.services.field_value_core import absolute_url

                return absolute_url(page_url, value)
            return str(value).strip()
    return " ".join(node.get_text(" ", strip=True).split()).strip()


def _append_property_value(row: dict[str, Any], key: str, value: object) -> None:
    existing = row.get(key)
    if existing in (None, "", [], {}):
        row[key] = value
        return
    if isinstance(existing, list):
        existing.append(value)
        return
    row[key] = [existing, value]


def _has_itemscope_ancestor(node: Any) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "attrs", {}).get("itemscope") is not None:
            return True
        parent = getattr(parent, "parent", None)
    return False


def _belongs_to_nested_itemscope(candidate: Any, root: Any) -> bool:
    parent = getattr(candidate, "parent", None)
    while parent is not None and parent is not root:
        if getattr(parent, "attrs", {}).get("itemscope") is not None:
            return True
        parent = getattr(parent, "parent", None)
    return False


def _parse_opengraph_fallback(soup: BeautifulSoup) -> list[dict[str, Any]]:
    row: dict[str, Any] = {}
    for node in soup.find_all("meta"):
        property_name = str(node.get("property") or "").strip()
        content = str(node.get("content") or "").strip()
        if not property_name or not content:
            continue
        if not (property_name.startswith("og:") or property_name.startswith("product:")):
            continue
        _append_property_value(row, property_name, content)
    normalized = _normalize_opengraph_row(row)
    return [normalized] if normalized else []


def _normalize_opengraph_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    explicit_type = _first_value(row.get("og:type"))
    saw_product_property = False
    key_map = {
        "og:title": "name",
        "og:description": "description",
        "og:image": "image",
        "og:url": "url",
        "product:price:amount": "price",
        "product:price:currency": "priceCurrency",
        "product:availability": "availability",
        "product:brand": "brand",
        "product:retailer_item_id": "sku",
        "product:item_group_id": "product_id",
    }
    for raw_key, target_key in key_map.items():
        value = row.get(raw_key)
        if value in (None, "", [], {}):
            continue
        normalized[target_key] = value
        if raw_key.startswith("product:"):
            saw_product_property = True
    if explicit_type:
        normalized["@type"] = explicit_type
    elif saw_product_property:
        normalized["@type"] = "product"
    return normalized


def _first_value(value: object) -> object | None:
    if isinstance(value, list):
        return next((item for item in value if item not in (None, "", [], {})), None)
    return value


def _revive_nuxt_data_payload(payload: Any) -> Any:
    if not isinstance(payload, list) or not payload:
        return payload
    return _revive_flattened_slot(payload, 0, {})


def _revive_flattened_slot(
    slots: list[Any],
    index: int,
    cache: dict[int, Any],
) -> Any:
    if index in cache:
        return cache[index]
    if index < 0 or index >= len(slots):
        return None
    value = slots[index]
    if isinstance(value, dict):
        revived: dict[str, Any] = {}
        cache[index] = revived
        for key, item in value.items():
            revived[str(key)] = _revive_flattened_ref(slots, item, cache)
        return revived
    if isinstance(value, list):
        revived_list: list[Any] = []
        cache[index] = revived_list
        wrapper = _revive_flattened_wrapper(slots, value, cache)
        if wrapper is not None:
            cache[index] = wrapper
            return wrapper
        revived_list.extend(_revive_flattened_ref(slots, item, cache) for item in value)
        return revived_list
    cache[index] = value
    return value


def _revive_flattened_ref(
    slots: list[Any],
    value: Any,
    cache: dict[int, Any],
) -> Any:
    if isinstance(value, int):
        return _revive_flattened_slot(slots, value, cache)
    return value


def _revive_flattened_wrapper(
    slots: list[Any],
    value: list[Any],
    cache: dict[int, Any],
) -> Any | None:
    if len(value) != 2 or not isinstance(value[0], str):
        return None
    wrapper_type = value[0]
    payload = _revive_flattened_ref(slots, value[1], cache)
    if wrapper_type in {
        "Reactive",
        "ShallowReactive",
        "Ref",
        "ShallowRef",
        "NuxtError",
    }:
        return payload
    return None
