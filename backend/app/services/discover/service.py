# Source discovery service — enumerates every data source on a page.
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from app.services.pipeline_config import HYDRATED_STATE_PATTERNS


@dataclass
class DiscoveryManifest:
    """All discovered data sources from a page, ranked by priority."""

    adapter_data: list[dict] = field(default_factory=list)      # rank 1: platform adapter
    network_payloads: list[dict] = field(default_factory=list)   # rank 2: XHR/fetch
    next_data: dict | None = None                                # rank 3: __NEXT_DATA__
    _hydrated_states: list[dict | list] = field(default_factory=list)
    embedded_json: list[dict | list] = field(default_factory=list)
    json_ld: list[dict] = field(default_factory=list)            # rank 4: JSON-LD
    microdata: list[dict] = field(default_factory=list)          # rank 5: Microdata/RDFa
    tables: list[dict] = field(default_factory=list)  # rank 8: HTML tables with preserved structure

    def as_dict(self) -> dict:
        return {
            "adapter_data": self.adapter_data,
            "network_payloads": self.network_payloads,
            "next_data": self.next_data,
            "_hydrated_states": self._hydrated_states,
            "embedded_json": self.embedded_json,
            "json_ld": self.json_ld,
            "microdata": self.microdata,
            "tables": self.tables,
        }


def discover_sources(
    html: str,
    network_payloads: list[dict] | None = None,
    adapter_records: list[dict] | None = None,
) -> DiscoveryManifest:
    """Discover all structured data sources in the HTML.

    Args:
        html: Raw or rendered HTML.
        network_payloads: XHR/fetch intercepts from Playwright.
        adapter_records: Records from platform adapter (already extracted).
    """
    soup = BeautifulSoup(html, "html.parser")
    manifest = DiscoveryManifest()

    # Rank 1: Adapter data (passed in from registry)
    manifest.adapter_data = adapter_records or []

    # Rank 2: Network payloads
    manifest.network_payloads = network_payloads or []

    # Rank 3: __NEXT_DATA__
    manifest.next_data = _extract_next_data(soup)

    # Rank 3b: additional hydrated state blobs found in inline scripts
    manifest._hydrated_states, hydrated_script_ids = _extract_hydrated_states(soup)
    if manifest.next_data is None and manifest._hydrated_states:
        manifest.next_data = {"_hydrated_states": manifest._hydrated_states}
    elif manifest.next_data is not None and manifest._hydrated_states:
        next_data = dict(manifest.next_data)
        next_data["_hydrated_states"] = manifest._hydrated_states
        manifest.next_data = next_data

    # Rank 3c: explicit embedded JSON blobs in scripts/data-* attributes
    manifest.embedded_json = _extract_embedded_json(soup, seen_script_ids=hydrated_script_ids)

    # Rank 4: JSON-LD
    manifest.json_ld = _extract_json_ld(soup)

    # Rank 5: Microdata / RDFa
    manifest.microdata = _extract_microdata(soup)

    # Rank 8: HTML tables
    manifest.tables = _extract_tables(soup)

    return manifest


def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    results = []
    for node in soup.select("script[type='application/ld+json']"):
        data = _parse_json_blob(node.string or node.get_text(" ", strip=True) or "")
        if isinstance(data, list):
            results.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            results.append(data)
    return results


def _extract_next_data(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node and node.string:
        try:
            return json.loads(node.string)
        except json.JSONDecodeError:
            return None
    return None


def _extract_hydrated_states(soup: BeautifulSoup) -> tuple[list[dict | list], set[str]]:
    """Extract app state blobs beyond __NEXT_DATA__.

    This is intentionally conservative: only JSON-like blobs and known state
    assignments are parsed.
    """
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


def _extract_embedded_json(soup: BeautifulSoup, seen_script_ids: set[str] | None = None) -> list[dict | list]:
    """Extract explicit JSON blobs from scripts and data-* attributes.

    This complements hydrated-state parsing for sites that stash structured
    product/app payloads in generic application/json scripts or element
    attributes such as data-product / data-state / data-props.
    """
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
            lowered_name = str(attr_name).lower()
            if not any(
                lowered_name == f"data-{token}" or lowered_name.endswith(f"-{token}")
                for token in data_attr_tokens
            ):
                continue
            if isinstance(attr_value, list):
                raw_value = " ".join(str(part) for part in attr_value)
            else:
                raw_value = str(attr_value or "")
            parsed = _parse_json_blob(raw_value)
            if parsed is not None:
                _append_unique_blob(blobs, seen, parsed)

    return blobs


def _normalized_script_identifier(node: Tag, text: str, fingerprint: str | None = None) -> str:
    script_id = str(node.get("id") or "").strip().lower()
    if script_id:
        return f"id:{script_id}"
    script_type = str(node.get("type") or "").strip().lower()
    normalized_text = " ".join(str(text or "").split())
    return f"type:{script_type}|fp:{fingerprint or normalized_text}"


def _append_unique_blob(blobs: list[dict | list], seen: set[str], parsed: dict | list) -> None:
    fingerprint = json.dumps(parsed, sort_keys=True, default=str)
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    blobs.append(parsed)


def _parse_json_blob(text: str) -> dict | list | None:
    stripped = text.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    if not stripped:
        return None
    if stripped[0] not in "[{":
        extracted = _extract_first_json_literal(stripped)
        if extracted:
            stripped = extracted
        else:
            return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _extract_first_json_literal(text: str) -> str | None:
    for opener in ("{", "["):
        start = text.find(opener)
        if start == -1:
            continue
        candidate = _extract_assigned_json(text, start)
        if candidate:
            return candidate
    return None


def _extract_next_bootstrap_children(text: str) -> list[str]:
    results: list[str] = []
    if "__next_s" not in text:
        return results
    for match in re.finditer(r'"children":"((?:\\.|[^"\\])*)"', text):
        try:
            decoded = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        cleaned = str(decoded or "").strip()
        if cleaned:
            results.append(cleaned)
    return results


def _parse_hydrated_assignment(text: str) -> dict | list | None:
    for marker in HYDRATED_STATE_PATTERNS:
        marker_pattern = rf"(?:window\.|self\.|globalThis\.)?{re.escape(marker)}\s*="
        match = re.search(marker_pattern, text)
        if not match:
            continue
        candidate = _extract_assigned_json(text, match.end())
        if not candidate:
            continue
        parsed = _parse_json_blob(candidate)
        if parsed is not None:
            return parsed
    return None


def _extract_assigned_json(text: str, offset: int) -> str | None:
    index = offset
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] not in "{[":
        return None

    start = index
    stack: list[str] = [text[index]]
    in_string = False
    escape = False
    quote_char = ""
    index += 1

    while index < len(text):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote_char:
                in_string = False
        else:
            if char in {'"', "'"}:
                in_string = True
                quote_char = char
            elif char in "{[":
                stack.append(char)
            elif char in "}]":
                if not stack:
                    return None
                opening = stack.pop()
                if (opening, char) not in {("{", "}"), ("[", "]")}:
                    return None
                if not stack:
                    return text[start:index + 1].strip()
        index += 1
    return None


def _extract_microdata(soup: BeautifulSoup) -> list[dict]:
    """Extract Microdata (itemprop) and RDFa (typeof/property) items."""
    items = []

    # Microdata: elements with itemprop
    for scope in soup.select("[itemscope]"):
        item: dict = {"_type": scope.get("itemtype", "")}
        for prop in scope.select("[itemprop]"):
            name = prop.get("itemprop", "")
            value = (
                prop.get("content")
                or prop.get("href")
                or prop.get("src")
                or prop.get_text(" ", strip=True)
            )
            if name and value:
                item[name] = value
        if len(item) > 1:  # more than just _type
            items.append(item)

    # RDFa: elements with typeof
    for node in soup.select("[typeof]"):
        item = {"_type": node.get("typeof", "")}
        for prop in node.select("[property]"):
            name = prop.get("property", "").split(":")[-1]  # strip namespace prefix
            value = (
                prop.get("content")
                or prop.get("href")
                or prop.get("src")
                or prop.get_text(" ", strip=True)
            )
            if name and value:
                item[name] = value
        if len(item) > 1:
            items.append(item)

    return items


def _extract_tables(soup: BeautifulSoup) -> list[dict]:
    tables: list[dict] = []
    for index, table in enumerate(soup.select("table"), start=1):
        caption = _clean_text(table.find("caption").get_text(" ", strip=True)) if table.find("caption") else ""
        section_title = _nearest_table_heading(table)
        rows: list[dict] = []
        headers: list[dict] = []

        for row_index, row in enumerate(table.find_all("tr"), start=1):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            cell_payloads = [_table_cell_payload(cell) for cell in cells]
            if not any(cell.get("text") for cell in cell_payloads):
                continue
            is_header = all(cell.name == "th" for cell in cells)
            if is_header and not headers:
                headers = cell_payloads
                continue
            rows.append({
                "row_index": row_index,
                "cells": cell_payloads,
            })

        if not headers and rows:
            first_row = rows[0]
            first_cells = first_row.get("cells") or []
            if len(first_cells) >= 2 and all((cell.get("text") or "") for cell in first_cells):
                headers = [{"text": "", "href": None} for _ in first_cells]

        if headers or rows:
            tables.append({
                "table_index": index,
                "section_title": section_title or None,
                "caption": caption or None,
                "headers": headers or None,
                "rows": rows,
            })
    return tables


def _table_cell_payload(cell: Tag) -> dict:
    text = _clean_text(cell.get_text(" ", strip=True))
    link = cell.find("a", href=True)
    return {
        "text": text,
        "href": str(link.get("href") or "").strip() or None if link else None,
    }


def _nearest_table_heading(table: Tag) -> str:
    for sibling in table.previous_siblings:
        if not isinstance(sibling, Tag):
            continue
        heading = _heading_text_from_node(sibling)
        if heading:
            return heading
        nested_heading = sibling.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for node in reversed(nested_heading):
            heading = _clean_text(node.get_text(" ", strip=True))
            if heading:
                return heading

    parent = table.parent if isinstance(table.parent, Tag) else None
    steps = 0
    while isinstance(parent, Tag) and steps < 4:
        for sibling in parent.previous_siblings:
            if not isinstance(sibling, Tag):
                continue
            heading = _heading_text_from_node(sibling)
            if heading:
                return heading
        parent = parent.parent if isinstance(parent.parent, Tag) else None
        steps += 1
    return ""


def _heading_text_from_node(node: Tag) -> str:
    if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return _clean_text(node.get_text(" ", strip=True))
    return ""


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()
