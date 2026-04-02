# Listing page extractor — finds repeating cards and extracts N records.
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


# Common CSS selectors for product/job listing cards, ordered by specificity.
_CARD_SELECTORS_COMMERCE = [
    "[data-component-type='s-search-result']",  # Amazon
    ".s-item",                                   # eBay
    ".product-card",
    ".product-item",
    ".product-tile",
    ".product-grid-item",
    "[data-testid='product-card']",
    ".grid-item[data-product-id]",
    ".collection-product-card",
    "li.grid__item",
    ".plp-card",
    ".search-result-gridview-item",
    ".product",
    "article.product",
]

_CARD_SELECTORS_JOBS = [
    ".job_seen_beacon",          # Indeed
    ".base-card",                # LinkedIn
    ".job-card",
    ".job-listing",
    ".job-result",
    "[data-testid='job-card']",
    ".jobsearch-ResultsList > div",
    "li.jobs-search__results-list-item",
]


def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
) -> list[dict]:
    """Extract multiple records from a listing/category page.

    Detects repeating card patterns in the DOM and extracts fields
    from each card.

    Returns:
        List of dicts, one per detected card/item.
    """
    soup = BeautifulSoup(html, "html.parser")

    selectors = _CARD_SELECTORS_COMMERCE if "commerce" in surface or "ecommerce" in surface else _CARD_SELECTORS_JOBS

    cards: list[Tag] = []
    used_selector = ""
    for sel in selectors:
        found = soup.select(sel)
        if len(found) >= 2:  # need at least 2 to confirm it's a repeating pattern
            cards = found
            used_selector = sel
            break

    # Fallback: auto-detect repeating siblings
    if not cards:
        cards, used_selector = _auto_detect_cards(soup)

    records = []
    for card in cards[:max_records]:
        record = _extract_from_card(card, target_fields, surface, page_url)
        if record and any(v for v in record.values() if v):
            record["_source"] = "listing_card"
            record["_selector"] = used_selector
            records.append(record)

    return records


def _auto_detect_cards(soup: BeautifulSoup) -> tuple[list[Tag], str]:
    """Heuristic: find the largest group of sibling elements with similar structure."""
    best_cards: list[Tag] = []
    best_selector = ""
    # Check common container patterns
    containers = soup.select("ul, ol, div.grid, div.row, div[class*='results'], main, section")
    for container in containers:
        children = [c for c in container.children if isinstance(c, Tag)]
        if len(children) < 3:
            continue
        # Check if children share a common tag + class pattern
        tag_classes = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            tag_classes.setdefault(key, []).append(child)
        for key, group in tag_classes.items():
            if len(group) >= 3 and len(group) > len(best_cards):
                best_cards = group
                classes = ".".join(key[1]) if key[1] else ""
                best_selector = f"{key[0]}.{classes}" if classes else key[0]
    return best_cards, best_selector


def _extract_from_card(card: Tag, target_fields: set[str], surface: str, page_url: str) -> dict:
    """Extract field values from a single listing card element."""
    record: dict = {}

    # Title: first heading or link text
    title_el = card.select_one("h2, h3, h4, a[title], .product-title, .job-title, .card-title")
    if title_el:
        record["title"] = title_el.get_text(" ", strip=True)

    # URL: first link
    link_el = card.select_one("a[href]")
    if link_el:
        href = link_el.get("href", "")
        record["url"] = urljoin(page_url, href) if page_url else href

    # Image
    img_el = card.select_one("img[src]")
    if img_el:
        record["image_url"] = img_el.get("src") or img_el.get("data-src", "")

    # Price (commerce)
    if "ecommerce" in surface:
        price_el = card.select_one(
            "[itemprop='price'], .price, .product-price, .a-price .a-offscreen, "
            ".s-item__price, span[data-price], .amount"
        )
        if price_el:
            record["price"] = price_el.get("content") or price_el.get_text(" ", strip=True)

    # Brand
    brand_el = card.select_one(".brand, [itemprop='brand'], .product-brand")
    if brand_el:
        record["brand"] = brand_el.get_text(strip=True)

    # Rating
    rating_el = card.select_one("[aria-label*='star'], .rating, [itemprop='ratingValue']")
    if rating_el:
        record["rating"] = rating_el.get("content") or rating_el.get("aria-label", "")

    # Job fields
    if "job" in surface:
        company_el = card.select_one(".company, .companyName, [data-testid='company-name']")
        if company_el:
            record["company"] = company_el.get_text(strip=True)
        location_el = card.select_one(".location, .companyLocation, [data-testid='text-location']")
        if location_el:
            record["location"] = location_el.get_text(strip=True)
        salary_el = card.select_one(".salary, .salary-snippet-container")
        if salary_el:
            record["salary"] = salary_el.get_text(strip=True)

    return record
