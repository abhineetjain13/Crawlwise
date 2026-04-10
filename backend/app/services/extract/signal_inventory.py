"""Signal inventory module for centralized signal collection before page classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from app.services.extract.source_parsers import (
    extract_hydrated_states,
    extract_json_ld,
    extract_next_data,
)


@dataclass
class SignalInventory:
    """Complete signal collection for page classification."""

    structured_data: dict[str, Any]
    dom_patterns: dict[str, Any]
    metadata: dict[str, Any]
    page_type: str | None = None


def build_signal_inventory(html: str, url: str, surface: str) -> SignalInventory:
    """Collect all signals before classification.

    Returns SignalInventory with:
    - structured_data: {json_ld, datalayer, next_data, hydrated_states}
    - dom_patterns: {card_count, detail_markers, url_patterns}
    - metadata: {link_count, text_ratio, domain}
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Collect structured data signals
    json_ld = extract_json_ld(soup)
    next_data = extract_next_data(soup)
    hydrated_states, _ = extract_hydrated_states(soup)
    datalayer = _extract_datalayer_signal(html)

    structured_data = {
        "json_ld": json_ld,
        "datalayer": datalayer,
        "next_data": next_data,
        "hydrated_states": hydrated_states,
    }

    # Collect DOM pattern signals
    card_count = _count_card_selectors(soup)
    detail_markers = _detect_detail_markers(soup)
    url_patterns = _analyze_url_patterns(url)

    dom_patterns = {
        "card_count": card_count,
        "detail_markers": detail_markers,
        "url_patterns": url_patterns,
    }

    # Collect metadata
    link_count = len(soup.find_all("a", href=True))
    text_ratio = _calculate_text_ratio(soup)
    domain = _extract_domain(url)

    metadata = {
        "link_count": link_count,
        "text_ratio": text_ratio,
        "domain": domain,
        "surface": surface,
    }

    return SignalInventory(
        structured_data=structured_data,
        dom_patterns=dom_patterns,
        metadata=metadata,
    )


def classify_page_type(inventory: SignalInventory) -> str:
    """Derive page_type from collected signals.

    Classification logic:
    - JSON-LD @type in ["ItemList", "CollectionPage"] → "listing"
    - JSON-LD @type in ["Product", "JobPosting"] → "detail"
    - dataLayer has "items" array → "listing"
    - DOM has 5+ card selectors → "listing"
    - DOM has detail markers (price, description, specs) → "detail"
    - Otherwise → "unknown"
    """
    # Check JSON-LD signals
    json_ld = inventory.structured_data.get("json_ld", [])
    for item in json_ld:
        if not isinstance(item, dict):
            continue
        item_type = item.get("@type", "")
        if isinstance(item_type, list):
            item_type = item_type[0] if item_type else ""
        item_type = str(item_type).lower()

        if item_type in ["itemlist", "collectionpage"] or item_type.endswith("itemlist") or item_type.endswith("collectionpage"):
            return "listing"
        if item_type in ["product", "jobposting"] or item_type.endswith("product") or item_type.endswith("jobposting"):
            return "detail"

    # Check dataLayer signals
    datalayer = inventory.structured_data.get("datalayer", {})
    if isinstance(datalayer, dict):
        event_name = str(datalayer.get("event", "")).lower()
        ecommerce = datalayer.get("ecommerce", {})
        if isinstance(ecommerce, dict):
            # GA4 schema has items array for listing pages
            if "items" in ecommerce and isinstance(ecommerce["items"], list):
                items = ecommerce["items"]
                # Check item-level fields on items[0] and top-level fields on ecommerce
                item_level_fields = {"item_id", "item_name", "item_variant", "item_brand", "item_category"}
                top_level_fields = {"currency", "value"}
                has_item_hint = items and isinstance(items[0], dict) and any(key in items[0] for key in item_level_fields)
                has_top_hint = any(key in ecommerce for key in top_level_fields)
                has_detail_hint = event_name == "view_item" or has_item_hint or has_top_hint
                if len(items) > 1:
                    return "listing"
                if len(items) == 1 and has_detail_hint:
                    return "detail"
            # UA schema has detail object for detail pages
            if "detail" in ecommerce:
                return "detail"

    # Check DOM pattern signals
    card_count = inventory.dom_patterns.get("card_count", 0)
    if card_count >= 5:
        return "listing"

    detail_markers = inventory.dom_patterns.get("detail_markers", {})
    if detail_markers.get("has_price") and detail_markers.get("has_description"):
        return "detail"

    # Check URL patterns
    url_patterns = inventory.dom_patterns.get("url_patterns", {})
    if url_patterns.get("is_listing_url"):
        return "listing"
    if url_patterns.get("is_detail_url"):
        return "detail"

    return "unknown"


def _extract_datalayer_signal(html: str) -> dict[str, Any]:
    """Extract dataLayer object from HTML for signal collection."""
    # Look for dataLayer variable assignment
    match = re.search(r"dataLayer\s*=\s*", html, re.DOTALL)
    if not match:
        return {}

    try:
        import json

        # Find the start position after the assignment
        start_pos = match.end()
        if start_pos >= len(html):
            return {}
        
        # Determine if it's an array or object
        opening_char = None
        for i in range(start_pos, min(start_pos + 10, len(html))):
            if html[i] in ('[', '{'):
                opening_char = html[i]
                start_pos = i
                break
        
        if opening_char is None:
            return {}
        
        # Find matching closing bracket by counting
        closing_char = ']' if opening_char == '[' else '}'
        bracket_count = 0
        in_string = False
        string_quote = None  # Track which quote character opened the current string
        escape_next = False
        end_pos = start_pos
        
        for i in range(start_pos, len(html)):
            char = html[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            # Handle string literals - track which quote character opened the string
            if char in ('"', "'"):
                if not in_string:
                    # Entering a string
                    in_string = True
                    string_quote = char
                elif char == string_quote:
                    # Exiting the string (matching quote)
                    in_string = False
                    string_quote = None
                # else: different quote type inside string, ignore
                continue
            
            if in_string:
                continue
            
            if char == opening_char:
                bracket_count += 1
            elif char == closing_char:
                bracket_count -= 1
                if bracket_count == 0:
                    end_pos = i + 1
                    break
        
        if bracket_count != 0:
            # Fallback to original regex approach
            match = re.search(r"dataLayer\s*=\s*(\[.*?\]|\{.*?\})", html, re.DOTALL)
            if not match:
                return {}
            datalayer_text = match.group(1)
        else:
            datalayer_text = html[start_pos:end_pos]
        
        # Try to parse as JSON
        parsed = json.loads(datalayer_text)
        if isinstance(parsed, list) and parsed:
            # dataLayer is typically an array, get the last item with ecommerce data
            for item in reversed(parsed):
                if isinstance(item, dict) and "ecommerce" in item:
                    return item
            return parsed[-1] if isinstance(parsed[-1], dict) else {}
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def _count_card_selectors(soup: BeautifulSoup) -> int:
    """Count potential product/job card elements in the DOM."""
    card_selectors = [
        "[class*='card']",
        "[class*='item']",
        "[class*='product']",
        "[class*='job']",
        "[class*='listing']",
        "[data-testid*='card']",
        "[data-testid*='item']",
    ]

    card_count = 0
    for selector in card_selectors:
        elements = soup.select(selector)
        # Filter out nested cards (only count top-level cards)
        top_level = [el for el in elements if not any(parent in elements for parent in el.parents)]
        card_count = max(card_count, len(top_level))

    return card_count


def _detect_detail_markers(soup: BeautifulSoup) -> dict[str, bool]:
    """Detect markers that indicate a detail page."""
    # Check for price indicators
    price_selectors = [
        "[class*='price']",
        "[data-testid*='price']",
        "[itemprop='price']",
    ]
    has_price = any(soup.select(selector) for selector in price_selectors)

    # Check for description indicators
    description_selectors = [
        "[class*='description']",
        "[data-testid*='description']",
        "[itemprop='description']",
    ]
    has_description = any(soup.select(selector) for selector in description_selectors)

    # Check for specification tables or lists
    has_specs = bool(soup.find("dl") or soup.find("table"))

    return {
        "has_price": has_price,
        "has_description": has_description,
        "has_specs": has_specs,
    }


def _analyze_url_patterns(url: str) -> dict[str, bool]:
    """Analyze URL patterns to infer page type."""
    url_lower = url.lower()

    # Listing page patterns
    listing_patterns = [
        r"/jobs/?$",
        r"/products/?$",
        r"/listings/?$",
        r"/search(?:/|$|\?)",
        r"/category(?:/|$|\?)",
        r"/collection(?:/|$|\?)",
    ]
    is_listing_url = any(re.search(pattern, url_lower) for pattern in listing_patterns)

    # Detail page patterns
    detail_patterns = [
        r"/job/[^/]+",
        r"/product/[^/]+",
        r"/item/[^/]+",
        r"/p/[^/]+",
        r"/[^/]+-\d+$",  # URLs ending with ID
    ]
    is_detail_url = any(re.search(pattern, url_lower) for pattern in detail_patterns)

    return {
        "is_listing_url": is_listing_url,
        "is_detail_url": is_detail_url,
    }


def _calculate_text_ratio(soup: BeautifulSoup) -> float:
    """Calculate ratio of text content to HTML size."""
    html_size = len(str(soup))
    if html_size == 0:
        return 0.0

    text = soup.get_text(" ", strip=True)
    text_size = len(text)

    return text_size / html_size


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.netloc
