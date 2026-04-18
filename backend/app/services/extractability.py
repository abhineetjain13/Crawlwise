from __future__ import annotations

import json

from bs4 import BeautifulSoup

NEXT_DATA_PRODUCT_SIGNALS = (
    '"productId"',
    '"partNumber"',
    '"displayName"',
    '"sku"',
    '"skuId"',
    '"price"',
    '"salePrice"',
    '"listPrice"',
    '"imageUrl"',
    '"imageURL"',
    '"image_url"',
    '"availability"',
    '"inStock"',
    '"slug"',
    '"handle"',
    '"jobId"',
    '"jobTitle"',
    '"companyName"',
)


def json_ld_listing_count(
    payload: object,
    *,
    max_depth: int = 3,
    _depth: int = 0,
) -> int:
    if _depth > max_depth:
        return 0
    if isinstance(payload, list):
        return sum(
            json_ld_listing_count(item, _depth=_depth + 1, max_depth=max_depth)
            for item in payload
        )
    if not isinstance(payload, dict):
        return 0

    count = 0
    raw_ld_type = payload.get("@type", "")
    if isinstance(raw_ld_type, str):
        ld_types = {raw_ld_type.strip().lower()} if raw_ld_type.strip() else set()
    elif isinstance(raw_ld_type, (list, tuple, set)):
        ld_types = {
            str(item).strip().lower()
            for item in raw_ld_type
            if isinstance(item, str) and item.strip()
        }
    else:
        ld_types = set()

    if ld_types & {"product", "jobposting"}:
        count += 1
    if "itemlist" in ld_types or "itemListElement" in payload:
        count += len(payload.get("itemListElement", []))

    graph = payload.get("@graph")
    if isinstance(graph, list):
        count += sum(
            json_ld_listing_count(item, _depth=_depth + 1, max_depth=max_depth)
            for item in graph
        )

    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        count += json_ld_listing_count(
            main_entity,
            _depth=_depth + 1,
            max_depth=max_depth,
        )

    offers = payload.get("offers")
    offer_items = (
        offers
        if isinstance(offers, list)
        else [offers]
        if isinstance(offers, dict)
        else []
    )
    for offer in offer_items:
        if not isinstance(offer, dict):
            continue
        item_offered = offer.get("itemOffered")
        if isinstance(item_offered, list):
            count += sum(1 for item in item_offered if isinstance(item, dict))

    return count


def html_has_extractable_listings_from_soup(
    soup: BeautifulSoup,
    *,
    json_loader=json.loads,
) -> bool:
    product_count = 0
    for node in soup.select("script[type='application/ld+json']"):
        raw = node.string or node.get_text(" ", strip=True) or ""
        try:
            payload = json_loader(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        product_count += json_ld_listing_count(payload)
        if product_count >= 2:
            return True

    next_data_node = soup.select_one("script#__NEXT_DATA__")
    if next_data_node is None:
        return False
    raw_next_data = (
        next_data_node.string or next_data_node.get_text(" ", strip=True) or ""
    )
    signal_hits = sum(raw_next_data.count(key) for key in NEXT_DATA_PRODUCT_SIGNALS)
    return signal_hits >= 4
