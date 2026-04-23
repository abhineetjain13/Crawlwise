from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET

from app.services.detail_extractor import (
    _backfill_detail_price_from_html,
    _normalize_variant_record,
    extract_detail_records,
)
from app.services.field_value_core import (
    absolute_url,
    clean_text,
    coerce_text,
    direct_record_to_surface_fields,
    finalize_record,
    surface_alias_lookup,
    surface_fields,
)
from app.services.field_value_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.field_policy import (
    canonical_fields_for_surface,
    normalize_field_key,
)
from app.services.extract.listing_candidate_ranking import best_listing_candidate_set
from app.services.listing_extractor import (
    _detail_like_path,
    _listing_title_is_noise,
    _url_is_structural,
    extract_listing_records,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.normalizers import normalize_decimal_price

_JSON_LIST_KEYS = (
    "data",
    "edges",
    "entries",
    "items",
    "jobs",
    "listings",
    "nodes",
    "posts",
    "products",
    "records",
    "results",
)


def extract_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
    requested_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
    content_type: str | None = None,
) -> list[dict]:
    xml_records = _extract_xml_sitemap_records(
        html,
        page_url,
        surface,
        max_records=max_records,
        content_type=content_type,
    )
    if xml_records:
        return xml_records[:max_records]
    json_records = _extract_raw_json_records(
        html,
        page_url,
        surface,
        max_records=max_records,
        requested_fields=requested_fields,
        content_type=content_type,
    )
    if json_records:
        if "listing" in surface:
            return json_records[:max_records]
        return _postprocess_detail_records(json_records[:max_records], html=html)
    if "listing" in surface:
        adapter_rows: list[dict[str, Any]] = []
        if adapter_records:
            for record in list(adapter_records or [])[: max(1, int(max_records)) * 4]:
                if not isinstance(record, dict):
                    continue
                shaped = direct_record_to_surface_fields(
                    record,
                    surface=surface,
                    page_url=page_url,
                    requested_fields=requested_fields,
                    base_fields={
                        "source_url": page_url,
                        "_source": str(record.get("_source") or "adapter"),
                    },
                )
                if shaped.get("title") and shaped.get("url"):
                    adapter_rows.append(shaped)
        listing_rows = extract_listing_records(
            html,
            page_url,
            surface,
            max_records=max_records,
            artifacts=artifacts,
            selector_rules=selector_rules,
            network_payloads=network_payloads,
        )
        adapter_rows = _backfill_listing_rows_from_network(
            adapter_rows,
            network_payloads=network_payloads,
        )
        listing_rows = _backfill_listing_rows_from_network(
            listing_rows,
            network_payloads=network_payloads,
        )
        if adapter_rows and listing_rows:
            candidate_rows = best_listing_candidate_set(
                [
                    ("adapter", adapter_rows),
                    ("generic", listing_rows),
                    ("generic_plus_adapter", [*listing_rows, *adapter_rows]),
                ],
                page_url=page_url,
                surface=surface,
                max_records=max_records,
                title_is_noise=_listing_title_is_noise,
                url_is_structural=_url_is_structural,
                detail_like_url=lambda candidate_url: _detail_like_path(
                    candidate_url,
                    is_job=str(surface or "").startswith("job_"),
                ),
            )
            return candidate_rows[:max_records]
        if listing_rows:
            return listing_rows[:max_records]
        if adapter_rows:
            return adapter_rows[:max_records]
        return []
    return _postprocess_detail_records(
        extract_detail_records(
        html,
        page_url,
        surface,
        requested_page_url=requested_page_url,
        requested_fields=requested_fields,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
        )[:max_records],
        html=html,
    )


def _postprocess_detail_records(
    records: list[dict],
    *,
    html: str,
) -> list[dict]:
    rows: list[dict] = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        _normalize_variant_record(record)
        _backfill_detail_price_from_html(record, html=html)
        rows.append(record)
    return rows


def _backfill_listing_rows_from_network(
    rows: list[dict],
    *,
    network_payloads: list[dict[str, object]] | None,
) -> list[dict]:
    if not rows or not network_payloads:
        return rows
    prices_by_id, prices_by_title = _listing_network_price_maps(network_payloads)
    if not prices_by_id and not prices_by_title:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("price") not in (None, "", [], {}):
            continue
        candidate = None
        row_url = str(row.get("url") or "").strip()
        row_id = _listing_identity_from_url(row_url)
        if row_id:
            candidate = prices_by_id.get(row_id)
        if candidate is None:
            row_title = clean_text(row.get("title"))
            if row_title:
                candidate = prices_by_title.get(row_title.lower())
        if not isinstance(candidate, dict):
            continue
        price = candidate.get("price")
        currency = candidate.get("currency")
        if price not in (None, "", [], {}):
            row["price"] = price
        if currency not in (None, "", [], {}) and row.get("currency") in (None, "", [], {}):
            row["currency"] = currency
    return rows


def _listing_network_price_maps(
    network_payloads: list[dict[str, object]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_id: dict[str, dict[str, str]] = {}
    by_title: dict[str, dict[str, str]] = {}
    for payload in list(network_payloads or []):
        body = payload.get("body")
        for candidate in _iter_listing_price_candidates(body):
            price = _listing_candidate_price(candidate)
            if not price:
                continue
            currency = _listing_candidate_currency(candidate)
            entry = {"price": price}
            if currency:
                entry["currency"] = currency
            identifier = clean_text(
                candidate.get("productId") or candidate.get("product_id") or candidate.get("id") or candidate.get("sku")
            )
            if identifier:
                by_id[identifier.lower()] = entry
            title = clean_text(candidate.get("name") or candidate.get("title"))
            if title:
                by_title[title.lower()] = entry
    return by_id, by_title


def _iter_listing_price_candidates(value: object, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4:
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in ("price", "prices", "sale_price", "offers")) and any(
            key in value for key in ("name", "title", "productId", "product_id", "id", "sku")
        ):
            rows.append(value)
        for item in value.values():
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
        return rows
    if isinstance(value, list):
        for item in value[:200]:
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
    return rows


def _listing_candidate_price(candidate: dict[str, Any]) -> str | None:
    currency = _listing_candidate_currency(candidate)
    raw_price = (
        candidate.get("price")
        or (((candidate.get("prices") or {}).get("promo") or {}).get("value") if isinstance(candidate.get("prices"), dict) else None)
        or (((candidate.get("prices") or {}).get("base") or {}).get("value") if isinstance(candidate.get("prices"), dict) else None)
        or (((candidate.get("offers") or {}).get("price")) if isinstance(candidate.get("offers"), dict) else None)
        or candidate.get("sale_price")
    )
    if raw_price in (None, "", [], {}):
        return None
    digits_only = re.sub(r"\D+", "", str(raw_price))
    return normalize_decimal_price(
        raw_price,
        interpret_integral_as_cents=(
            "." not in str(raw_price)
            and len(digits_only) >= 4
            and currency in {"AUD", "CAD", "EUR", "GBP", "NZD", "USD"}
        ),
    )


def _listing_candidate_currency(candidate: dict[str, Any]) -> str | None:
    prices = candidate.get("prices")
    if isinstance(prices, dict):
        base_currency = ((prices.get("base") or {}).get("currency") if isinstance(prices.get("base"), dict) else None)
        if isinstance(base_currency, dict):
            code = clean_text(base_currency.get("code"))
            if code:
                return code
    offers = candidate.get("offers")
    if isinstance(offers, dict):
        code = clean_text(offers.get("priceCurrency"))
        if code:
            return code
    return clean_text(candidate.get("currency") or candidate.get("currencyCode")) or None


def _listing_identity_from_url(url: str) -> str:
    if not url:
        return ""
    path = urlsplit(url).path
    match = re.search(r"/([A-Z]\d{6}-\d{3})(?:/|$)", path)
    if match is not None:
        return match.group(1).lower()
    match = re.search(r"/([^/?#]+)/?$", path)
    return str(match.group(1) if match is not None else "").strip().lower()


async def extract_records_async(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
    requested_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
    content_type: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(
        extract_records,
        html,
        page_url,
        surface,
        max_records=max_records,
        requested_page_url=requested_page_url,
        requested_fields=requested_fields,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        artifacts=artifacts,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
        content_type=content_type,
    )


def _extract_xml_sitemap_records(
    text: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    content_type: str | None,
) -> list[dict[str, Any]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    raw = str(text or "").lstrip("\ufeff").strip()
    lowered_content_type = str(content_type or "").strip().lower()
    if not _looks_like_xml_document(raw, content_type=lowered_content_type):
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for loc_text in _xml_sitemap_locations(root):
        url = absolute_url(page_url, loc_text)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _xml_listing_title(url)
        if not title:
            continue
        records.append(
            finalize_record(
                {
                    "source_url": page_url,
                    "_source": "xml_sitemap",
                    "title": title,
                    "url": url,
                },
                surface=surface,
            )
        )
        if len(records) >= max_records:
            break
    return records


def _looks_like_xml_document(text: str, *, content_type: str) -> bool:
    if not text:
        return False
    if any(token in content_type for token in ("xml", "rss", "atom")):
        return True
    return (
        text.startswith("<?xml")
        or text.startswith("<urlset")
        or text.startswith("<sitemapindex")
        or text.startswith("<rss")
        or text.startswith("<feed")
    )


def _xml_sitemap_locations(root: ET.Element) -> list[str]:
    locations: list[str] = []
    for node in root.iter():
        tag_name = str(node.tag or "")
        local_tag_name = tag_name.rsplit("}", 1)[-1]
        if local_tag_name == "loc":
            value = " ".join(str(node.text or "").split()).strip()
        elif local_tag_name == "link":
            value = " ".join(str(node.get("href") or node.text or "").split()).strip()
        else:
            continue
        if value:
            locations.append(value)
    return locations


def _xml_listing_title(url: str) -> str:
    path = str(urlsplit(url).path or "").strip("/")
    if not path:
        return ""
    terminal = unquote(path.rsplit("/", 1)[-1])
    terminal = re.sub(r"\.(html?|xml)$", "", terminal, flags=re.I)
    if not terminal:
        return ""
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if title:
        return title
    return clean_text(path.rsplit("/", 1)[-1])


def _extract_raw_json_records(
    text: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_fields: list[str] | None,
    content_type: str | None,
) -> list[dict[str, Any]]:
    payload = _parse_raw_json_payload(text, content_type=content_type)
    if payload is None:
        return []
    items = _raw_json_items(payload, surface=surface)
    if not items:
        return []
    records: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(items, start=1):
        record = _raw_json_record(
            item,
            page_url,
            surface,
            requested_fields=requested_fields,
            fallback_index=index,
        )
        if not record:
            continue
        dedupe_key = (
            str(record.get("url") or ""),
            str(record.get("title") or record.get("description") or ""),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        records.append(record)
        if len(records) >= max_records:
            break
    return records


def _parse_raw_json_payload(text: str, *, content_type: str | None) -> object | None:
    raw = str(text or "").lstrip("\ufeff").strip()
    lowered_content_type = str(content_type or "").strip().lower()
    if not raw:
        return None
    if "json" not in lowered_content_type and not raw.startswith(("{", "[")):
        return None
    if raw.startswith("<"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _has_surface_field_overlap(items: list[object], *, surface: str) -> bool:
    canonical = set(canonical_fields_for_surface(surface))
    if not canonical:
        return True
    dict_items = [item for item in items[:20] if isinstance(item, dict) and item]
    if not dict_items:
        return True
    matching = 0
    for item in dict_items:
        item_keys = {normalize_field_key(k) for k in item if k}
        if item_keys & canonical:
            matching += 1
    ratio = matching / len(dict_items) if dict_items else 0
    return (
        ratio >= crawler_runtime_settings.raw_json_surface_field_overlap_ratio
        and matching >= crawler_runtime_settings.raw_json_surface_field_overlap_absolute
    )


def _raw_json_items(payload: object, *, surface: str) -> list[object]:
    is_listing_surface = "listing" in str(surface or "").lower()
    if isinstance(payload, list):
        if is_listing_surface and not _has_surface_field_overlap(payload, surface=surface):
            return []
        return list(payload)
    if not isinstance(payload, dict):
        return [] if is_listing_surface else [payload]
    for key in _JSON_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and value:
            if is_listing_surface and not _has_surface_field_overlap(value, surface=surface):
                continue
            return value
    if is_listing_surface:
        return _best_nested_listing_items(payload, surface=surface)
    return [payload]


def _best_nested_listing_items(payload: object, *, depth: int = 0, surface: str = "") -> list[object]:
    if depth > 6:
        return []
    candidates: list[tuple[int, list[object]]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list):
                score = _listing_items_score(key, value)
                if score > 0:
                    candidates.append((score, value))
                for item in value[:10]:
                    nested = _best_nested_listing_items(item, depth=depth + 1, surface=surface)
                    if nested:
                        candidates.append((_listing_items_score("nested", nested), nested))
            elif isinstance(value, dict):
                nested = _best_nested_listing_items(value, depth=depth + 1, surface=surface)
                if nested:
                    candidates.append((_listing_items_score(key, nested), nested))
    elif isinstance(payload, list):
        score = _listing_items_score("list", payload)
        if score > 0:
            if surface and not _has_surface_field_overlap(payload, surface=surface):
                score = 0
        if score > 0:
            candidates.append((score, payload))
        for item in payload[:10]:
            nested = _best_nested_listing_items(item, depth=depth + 1, surface=surface)
            if nested:
                candidates.append((_listing_items_score("nested", nested), nested))
    if not candidates:
        return []
    return max(candidates, key=lambda row: (row[0], len(row[1])))[1]


def _listing_items_score(key: str, items: list[object]) -> int:
    if not items:
        return 0
    dict_like_count = sum(
        1 for item in items[:20] if isinstance(item, dict) and item
    )
    if dict_like_count == 0:
        return 0
    lowered_key = str(key or "").strip().lower()
    score = dict_like_count
    if lowered_key in _JSON_LIST_KEYS:
        score += 20
    if lowered_key in {"edges", "nodes"}:
        score += 10
    if any(isinstance(item, dict) and any(token in item for token in ("node", "url", "title", "name")) for item in items[:10]):
        score += 5
    return score


def _raw_json_record(
    payload: object,
    page_url: str,
    surface: str,
    *,
    requested_fields: list[str] | None,
    fallback_index: int,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        alias_lookup = surface_alias_lookup(surface, requested_fields)
        candidates: dict[str, list[object]] = {}
        collect_structured_candidates(payload, alias_lookup, page_url, candidates)
        record: dict[str, Any] = {"source_url": page_url, "_source": "raw_json"}
        for field_name in surface_fields(surface, requested_fields):
            finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
            if finalized not in (None, "", [], {}):
                record[field_name] = finalized
        preferred_title = coerce_text(
            payload.get("title")
            or payload.get("name")
            or payload.get("label")
        )
        if preferred_title:
            record["title"] = preferred_title
        if not record.get("description"):
            description = coerce_text(payload.get("description") or payload.get("body"))
            if description:
                record["description"] = description
        if not record.get("url"):
            record["url"] = _raw_json_url(payload, page_url, fallback_index=fallback_index)
        cleaned = finalize_record(record, surface=surface)
        return cleaned if len(cleaned) > 2 else {}
    title = coerce_text(payload)
    if not title:
        return {}
    return finalize_record(
        {
            "source_url": page_url,
            "_source": "raw_json",
            "title": title,
            "url": f"{page_url.split('#', 1)[0]}#item-{fallback_index}",
        },
        surface=surface,
    )


def _raw_json_url(
    payload: dict[str, Any],
    page_url: str,
    *,
    fallback_index: int,
) -> str:
    for key in ("url", "link", "href", "permalink"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            resolved = absolute_url(page_url, value)
            if resolved:
                return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        author_url = author.get("url") or author.get("link")
        resolved = absolute_url(page_url, author_url)
        if resolved:
            return resolved
    identifier = clean_text(payload.get("id") or payload.get("slug") or payload.get("handle"))
    base_url = page_url.split("#", 1)[0]
    if identifier:
        return f"{base_url}#item-{identifier}"
    return f"{base_url}#item-{fallback_index}"
