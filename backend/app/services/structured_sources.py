from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

_STATE_SCRIPT_IDS = {
    "__next_data__": "__NEXT_DATA__",
    "__nuxt_data__": "__NUXT_DATA__",
}
_ASSIGNMENT_STATE_PATTERNS = (
    "__NUXT__",
    "__APOLLO_STATE__",
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__remixContext",
)
_NON_STATE_ASSIGNMENT_PATTERNS = (
    re.compile(r"ShopifyAnalytics\.meta\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"var\s+meta\s*=\s*(\{.*?\})\s*;", re.S),
)


def json_candidates(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value and isinstance(value["@graph"], list):
            rows: list[dict[str, Any]] = []
            for item in value["@graph"]:
                rows.extend(json_candidates(item))
            return rows
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
            rows.extend(json_candidates(json.loads(raw)))
        except json.JSONDecodeError:
            continue
    return rows


def parse_embedded_json(soup: BeautifulSoup, html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in soup.find_all("script"):
        script_type = str(node.get("type") or "").strip().lower()
        node_id = str(node.get("id") or "").strip().lower()
        raw = node.string or node.get_text()
        if not raw:
            continue
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
        for match in pattern.finditer(html):
            raw = match.group(1)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rows.extend(json_candidates(payload))
    return rows


def harvest_js_state_objects(soup: BeautifulSoup, html: str) -> dict[str, Any]:
    state_objects: dict[str, Any] = {}
    for node in soup.find_all("script"):
        node_id = str(node.get("id") or "").strip().lower()
        raw = node.string or node.get_text()
        if not raw:
            continue
        state_name = _STATE_SCRIPT_IDS.get(node_id)
        if state_name:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            state_objects[state_name] = payload

    for state_name in _ASSIGNMENT_STATE_PATTERNS:
        payload = _extract_assignment_payload(html, state_name)
        if payload is not None:
            state_objects[state_name] = payload
    return state_objects


def _extract_assignment_payload(html: str, state_name: str) -> Any | None:
    pattern = re.compile(rf"(?:window\.)?{re.escape(state_name)}\s*=\s*", re.S)
    match = pattern.search(str(html or ""))
    if match is None:
        return None
    fragment = _balanced_json_fragment(html[match.end() :])
    if not fragment:
        return None
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return None


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
