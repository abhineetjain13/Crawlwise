from __future__ import annotations

import json
import re
from json import loads as parse_json

from bs4 import BeautifulSoup, Tag

from app.services.pipeline_config import HYDRATED_STATE_PATTERNS


def parse_page_sources(html: str) -> dict[str, object]:
    soup = BeautifulSoup(html or "", "html.parser")
    hydrated_states, hydrated_script_ids = extract_hydrated_states(soup)
    next_data = extract_next_data(soup)
    if next_data is None and hydrated_states:
        next_data = {"_hydrated_states": hydrated_states}
    elif next_data is not None and hydrated_states:
        next_data = {**dict(next_data), "_hydrated_states": hydrated_states}
    return {
        "next_data": next_data,
        "hydrated_states": hydrated_states,
        "embedded_json": extract_embedded_json(soup, seen_script_ids=hydrated_script_ids),
        "open_graph": extract_open_graph(soup),
        "json_ld": extract_json_ld(soup),
        "microdata": extract_microdata(soup),
        "tables": extract_tables(soup),
    }


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    results = []
    for node in soup.select("script[type='application/ld+json']"):
        data = _parse_json_blob(node.string or node.get_text(" ", strip=True) or "")
        results.extend(_flatten_json_ld_payloads(data))
    return results


def extract_next_data(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node and node.string:
        try:
            parsed = parse_json(node.string)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def extract_hydrated_states(soup: BeautifulSoup) -> tuple[list[dict | list], set[str]]:
    blobs: list[dict | list] = []
    seen: set[str] = set()
    seen_script_ids: set[str] = set()
    for node in soup.find_all("script"):
        if node.get("src"):
            continue
        script_type = str(node.get("type") or "").lower()
        if script_type == "application/ld+json":
            continue
        text = node.string or node.get_text(" ", strip=True) or ""
        if not text:
            continue
        parsed_blobs: list[dict | list] = []
        candidate_texts = [text, *_extract_next_bootstrap_children(text)]
        for candidate_text in candidate_texts:
            parsed = _parse_json_blob(candidate_text) if script_type == "application/json" else None
            if parsed is None:
                parsed = _parse_hydrated_assignment(candidate_text)
            if parsed is None:
                parsed = _parse_react_create_element_props(candidate_text)
            if parsed is not None:
                parsed_blobs.append(parsed)
        for parsed in parsed_blobs:
            fingerprint = json.dumps(parsed, sort_keys=True, default=str)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            blobs.append(parsed)
            seen_script_ids.add(_normalized_script_identifier(node, text, fingerprint))
    return blobs, seen_script_ids


def extract_embedded_json(soup: BeautifulSoup, seen_script_ids: set[str] | None = None) -> list[dict | list]:
    blobs: list[dict | list] = []
    seen: set[str] = set()
    seen_script_ids = set(seen_script_ids or ())
    for node in soup.find_all("script"):
        if node.get("src"):
            continue
        script_type = str(node.get("type") or "").lower()
        script_id = str(node.get("id") or "").lower()
        text = node.string or node.get_text(" ", strip=True) or ""
        if not text or script_type == "application/ld+json":
            continue
        if script_type == "application/json" or any(token in script_id for token in ("state", "data", "props", "product")):
            for candidate_text in [text, *_extract_next_bootstrap_children(text)]:
                parsed = _parse_json_blob(candidate_text)
                if parsed is not None:
                    fingerprint = json.dumps(parsed, sort_keys=True, default=str)
                    if _normalized_script_identifier(node, text, fingerprint) in seen_script_ids:
                        continue
                    _append_unique_blob(blobs, seen, parsed)
    data_attr_tokens = ("json", "state", "props", "product", "config", "schema", "payload")
    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        for attr_name, attr_value in node.attrs.items():
            if not str(attr_name or "").startswith("data-"):
                continue
            attr_name_lower = str(attr_name).lower()
            if not any(token in attr_name_lower for token in data_attr_tokens):
                continue
            if isinstance(attr_value, list):
                attr_text = " ".join(str(item) for item in attr_value)
            else:
                attr_text = str(attr_value or "")
            parsed = _parse_json_blob(attr_text)
            if parsed is not None:
                _append_unique_blob(blobs, seen, parsed)
    return blobs


def extract_open_graph(soup: BeautifulSoup) -> dict[str, object]:
    payload: dict[str, object] = {}
    for node in soup.select("meta[property], meta[name]"):
        key = str(node.get("property") or node.get("name") or "").strip()
        if key.lower().startswith(("og:", "twitter:")):
            value = node.get("content")
            if value not in (None, "", [], {}):
                payload[key] = value
    return payload


def extract_microdata(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for node in soup.select("[itemscope]"):
        item: dict[str, object] = {}
        item_type = node.get("itemtype")
        if item_type:
            item["@type"] = item_type
        # Find direct properties - exclude those inside nested itemscopes
        nested_scopes = {nested for nested in node.select("[itemscope]")}
        for prop in node.select("[itemprop]"):
            # Skip if this prop is inside a nested itemscope
            if any(prop in scope.descendants for scope in nested_scopes if scope != node):
                continue
            prop_name = str(prop.get("itemprop") or "").strip()
            if not prop_name:
                continue
            if prop.name == "meta":
                value = prop.get("content")
            elif prop.name in {"a", "link"} and prop.get("href"):
                value = prop.get("href")
            elif prop.name in {"img", "source"} and prop.get("src"):
                value = prop.get("src")
            else:
                value = prop.get_text(" ", strip=True)
            if value not in (None, "", [], {}):
                item[prop_name] = value
        if item:
            items.append(item)
    return items


def extract_tables(soup: BeautifulSoup) -> list[dict]:
    tables: list[dict] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = []
        body_rows = []
        first_row_cells = rows[0].find_all(["th", "td"])
        if any(cell.name == "th" for cell in first_row_cells):
            headers = [_serialize_table_cell(cell, index) for index, cell in enumerate(first_row_cells, start=1)]
            data_rows = rows[1:]
        else:
            data_rows = rows
        for row_index, row in enumerate(data_rows, start=1):
            cells = row.find_all(["td", "th"])
            serialized_cells = [_serialize_table_cell(cell, index) for index, cell in enumerate(cells, start=1)]
            if any(cell.get("text") for cell in serialized_cells):
                body_rows.append({"row_index": row_index, "cells": serialized_cells})
        if headers or body_rows:
            tables.append(
                {
                    "table_index": table_index,
                    "caption": table.find("caption").get_text(" ", strip=True) if table.find("caption") else None,
                    "section_title": _nearest_section_heading(table),
                    "headers": headers,
                    "rows": body_rows,
                }
            )
    return tables


def _flatten_json_ld_payloads(payload: dict | list | None) -> list[dict]:
    flattened: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            flattened.extend(_flatten_json_ld_payloads(item))
        return flattened
    if not isinstance(payload, dict):
        return flattened
    graph = payload.get("@graph")
    if isinstance(graph, list):
        flattened.extend(item for item in graph if isinstance(item, dict))
        payload = {key: value for key, value in payload.items() if key != "@graph"}
    if any(key != "@context" for key in payload):
        flattened.append(payload)
    return flattened


def _append_unique_blob(blobs: list[dict | list], seen: set[str], parsed: dict | list) -> None:
    fingerprint = json.dumps(parsed, sort_keys=True, default=str)
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    blobs.append(parsed)


def _parse_json_blob(text: str) -> dict | list | None:
    candidate = str(text or "").strip()
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


def _parse_hydrated_assignment(text: str) -> dict | list | None:
    for pattern in HYDRATED_STATE_PATTERNS:
        match = re.search(rf"(?:window\.)?{re.escape(pattern)}\s*=\s*", text, re.DOTALL)
        if not match:
            continue
        fragment = _extract_balanced_json_fragment(text[match.end():])
        if not fragment:
            continue
        parsed = _parse_json_blob(fragment)
        if parsed is not None:
            return parsed
    return None


def _parse_react_create_element_props(text: str) -> dict | list | None:
    match = re.search(r"createElement\([^,]+,\s*(\{.*\})\s*\)", text, re.DOTALL)
    if not match:
        return None
    return _parse_json_blob(match.group(1))


def _extract_next_bootstrap_children(text: str) -> list[str]:
    matches = re.findall(r"self\.__next_f\.push\(\s*\[(?:.|\n)*?({.*?}|\[.*?\])(?:.|\n)*?\]\s*\)", text)
    return [match for match in matches if isinstance(match, str)]


def _extract_balanced_json_fragment(text: str) -> str:
    candidate = str(text or "").lstrip()
    if not candidate or candidate[0] not in "{[":
        return ""
    closing = "}" if candidate[0] == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(candidate):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == candidate[0]:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return candidate[: index + 1]
    return ""


def _normalized_script_identifier(node: Tag, text: str, fingerprint: str) -> str:
    return f"{node.get('id') or ''}|{node.get('type') or ''}|{hash(text)}|{fingerprint[:64]}"


def _serialize_table_cell(cell: Tag, cell_index: int) -> dict[str, object]:
    href = None
    link = cell.find("a", href=True)
    if link is not None:
        href = link.get("href")
    return {
        "cell_index": cell_index,
        "text": cell.get_text(" ", strip=True),
        "href": href,
        "tag": cell.name,
    }


def _nearest_section_heading(node: Tag) -> str | None:
    for previous in node.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=6):
        text = previous.get_text(" ", strip=True)
        if text:
            return text
    return None
