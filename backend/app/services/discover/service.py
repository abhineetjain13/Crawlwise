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
    json_ld: list[dict] = field(default_factory=list)            # rank 4: JSON-LD
    microdata: list[dict] = field(default_factory=list)          # rank 5: Microdata/RDFa
    tables: list[list[list[str]]] = field(default_factory=list)  # rank 8: HTML tables

    def as_dict(self) -> dict:
        return {
            "adapter_data": self.adapter_data,
            "network_payloads": self.network_payloads,
            "next_data": self.next_data,
            "_hydrated_states": self._hydrated_states,
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
    manifest._hydrated_states = _extract_hydrated_states(soup)
    if manifest.next_data is None and manifest._hydrated_states:
        manifest.next_data = {"_hydrated_states": manifest._hydrated_states}
    elif manifest.next_data is not None and manifest._hydrated_states:
        next_data = dict(manifest.next_data)
        next_data["_hydrated_states"] = manifest._hydrated_states
        manifest.next_data = next_data

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
        try:
            data = json.loads(node.string or "{}")
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except json.JSONDecodeError:
            continue
    return results


def _extract_next_data(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node and node.string:
        try:
            return json.loads(node.string)
        except json.JSONDecodeError:
            return None
    return None


def _extract_hydrated_states(soup: BeautifulSoup) -> list[dict | list]:
    """Extract app state blobs beyond __NEXT_DATA__.

    This is intentionally conservative: only JSON-like blobs and known state
    assignments are parsed.
    """
    blobs: list[dict | list] = []
    seen: set[str] = set()

    for node in soup.find_all("script"):
        if node.get("src"):
            continue
        script_type = str(node.get("type") or "").lower()
        if script_type == "application/ld+json":
            continue
        text = node.string or node.get_text(" ", strip=True) or ""
        if not text:
            continue

        parsed = _parse_json_blob(text) if script_type == "application/json" else None
        if parsed is None:
            parsed = _parse_hydrated_assignment(text)
        if parsed is None:
            continue

        fingerprint = json.dumps(parsed, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        blobs.append(parsed)

    return blobs


def _parse_json_blob(text: str) -> dict | list | None:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


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


def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    table_rows = []
    for table in soup.select("table"):
        rows = []
        for row in table.select("tr"):
            values = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
            if values:
                rows.append(values)
        if rows:
            table_rows.append(rows)
    return table_rows
