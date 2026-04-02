# Source discovery service — enumerates every data source on a page.
from __future__ import annotations

import json
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag


@dataclass
class DiscoveryManifest:
    """All discovered data sources from a page, ranked by priority."""

    adapter_data: list[dict] = field(default_factory=list)      # rank 1: platform adapter
    network_payloads: list[dict] = field(default_factory=list)   # rank 2: XHR/fetch
    next_data: dict | None = None                                # rank 3: __NEXT_DATA__
    json_ld: list[dict] = field(default_factory=list)            # rank 4: JSON-LD
    microdata: list[dict] = field(default_factory=list)          # rank 5: Microdata/RDFa
    tables: list[list[list[str]]] = field(default_factory=list)  # rank 8: HTML tables

    def as_dict(self) -> dict:
        return {
            "adapter_data": self.adapter_data,
            "network_payloads": self.network_payloads,
            "next_data": self.next_data,
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
