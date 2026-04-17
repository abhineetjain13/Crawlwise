from __future__ import annotations

import json
import re
from collections.abc import Callable

from bs4 import Tag


def looks_like_commerce_detail_path(path: str) -> bool:
    normalized_path = str(path or "").strip().lower()
    if not normalized_path:
        return False
    leaf = normalized_path.rstrip("/").split("/")[-1]
    if leaf.endswith(".html") and re.search(r"[a-z0-9-]{6,}", leaf):
        return True
    return bool(re.search(r"[a-z0-9-]+-[a-z0-9]{4,}(?:\.html)?$", leaf))


def candidate_card_contexts(card: Tag) -> list[Tag]:
    contexts: list[Tag] = []
    seen: set[int] = set()
    current: Tag | None = card
    for _depth in range(5):
        current = current.parent if isinstance(current.parent, Tag) else None
        if not isinstance(current, Tag):
            break
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if _looks_like_product_card_context(current):
            contexts.append(current)
    return contexts


def extract_embedded_card_metadata(
    card: Tag,
    *,
    page_url: str,
    normalize_title: Callable[[object], str],
    coerce_product_url: Callable[[str, str], str],
) -> dict[str, object]:
    record: dict[str, object] = {}
    selectors = (
        "[data-analytics], [data-product], [data-product-json], [data-item], "
        "[data-item-json], [data-gtm], [data-gtmdata], [data-ga4-item]"
    )
    for node in [card, *card.select(selectors)]:
        for attr_name, raw_value in node.attrs.items():
            if not str(attr_name).startswith("data-"):
                continue
            payload = _parse_embedded_json_attr(raw_value)
            if not isinstance(payload, dict):
                continue
            record = backfill_card_record(
                record,
                _map_embedded_card_metadata(
                    payload,
                    page_url=page_url,
                    normalize_title=normalize_title,
                    coerce_product_url=coerce_product_url,
                ),
            )
    return record


def backfill_card_record(
    base: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(base)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key.startswith("_"):
            merged.setdefault(key, value)
            continue
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
    return merged


def _looks_like_product_card_context(node: Tag) -> bool:
    attrs = " ".join(
        str(value)
        for key, value in node.attrs.items()
        if key.startswith("data-") or key in {"class", "id", "aria-label"}
    ).lower()
    return any(
        token in attrs
        for token in (
            "data-pid",
            "data-product-id",
            "data-productid",
            "product",
            "tile",
            "card",
            "listing",
            "result",
            "item",
        )
    )


def _parse_embedded_json_attr(raw_value: object) -> dict[str, object] | None:
    value = str(raw_value or "").strip()
    if not value or len(value) > 4000 or value[0] != "{":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _map_embedded_card_metadata(
    payload: dict[str, object],
    *,
    page_url: str,
    normalize_title: Callable[[object], str],
    coerce_product_url: Callable[[str, str], str],
) -> dict[str, object]:
    mapped: dict[str, object] = {}
    title = (
        payload.get("item_name")
        or payload.get("name")
        or payload.get("title")
        or payload.get("product_name")
    )
    if title:
        mapped["title"] = normalize_title(title)
    url = (
        payload.get("url")
        or payload.get("href")
        or payload.get("productUrl")
        or payload.get("product_url")
        or payload.get("item_url")
    )
    resolved_url = coerce_product_url(str(url or ""), page_url)
    if resolved_url:
        mapped["url"] = resolved_url
    for source_key, target_key in (
        ("price", "price"),
        ("currency", "currency"),
        ("item_brand", "brand"),
        ("brand", "brand"),
        ("item_id", "id"),
        ("product_id", "id"),
        ("id", "id"),
        ("variant_id", "sku"),
        ("sku", "sku"),
    ):
        value = payload.get(source_key)
        if value not in (None, "", [], {}):
            mapped[target_key] = value
    return mapped
