from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

from app.services.acquisition.runtime import classify_blocked_page
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.extraction_rules import (
    LISTING_NETWORK_BACKFILL_FIELDS,
    LISTING_NETWORK_BRAND_CANDIDATE_KEYS,
    LISTING_NETWORK_DIRECT_PRICE_KEYS,
    LISTING_NETWORK_FALLBACK_PRICE_KEYS,
    LISTING_NETWORK_ID_KEYS,
    LISTING_NETWORK_PRICE_BUCKETS,
    LISTING_NETWORK_PRICE_CANDIDATE_KEYS,
    LISTING_NETWORK_PRIMARY_PRICE_KEYS,
    LISTING_NETWORK_TITLE_KEYS,
)
from app.services.detail_extractor import (
    _backfill_detail_price_from_html,
    drop_low_signal_zero_detail_price,
    extract_detail_records,
)
from app.services.extract.variant_record_normalization import (
    normalize_variant_record,
)
from app.services.field_value_core import (
    absolute_url,
    clean_text,
    coerce_text,
    direct_record_to_surface_fields,
    finalize_record,
    is_title_noise,
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
    _finalize_listing_price_fields,
    _detail_like_path,
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
        return xml_records
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
            return [
                _finalize_listing_price_fields(dict(row))
                for row in json_records
                if isinstance(row, dict)
            ]
        return _postprocess_detail_records(json_records[:max_records], html=html)
    if _html_is_blocked_extraction_shell(html):
        return []
    if "listing" in surface:
        adapter_rows: list[dict[str, Any]] = []
        if adapter_records:
            for record in list(adapter_records or []):
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
        adapter_rows = [
            _finalize_listing_price_fields(dict(row))
            for row in adapter_rows
            if isinstance(row, dict)
        ]
        listing_rows = [
            _finalize_listing_price_fields(dict(row))
            for row in listing_rows
            if isinstance(row, dict)
        ]
        listing_rows = _backfill_listing_rows_from_adapter(
            listing_rows,
            adapter_rows=adapter_rows,
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
                title_is_noise=is_title_noise,
                url_is_structural=_url_is_structural,
                detail_like_url=lambda candidate_url: _detail_like_path(
                    candidate_url,
                    is_job=str(surface or "").startswith("job_"),
                ),
            )
            return candidate_rows
        if listing_rows:
            return listing_rows
        if adapter_rows:
            return adapter_rows
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


def _html_is_blocked_extraction_shell(html: str) -> bool:
    lowered = str(html or "").lower()
    if not lowered.strip():
        return False
    classification = classify_blocked_page(html, 0)
    if classification.blocked:
        return True
    phrases_raw = BLOCK_SIGNATURES.get("phrases")
    blocked_phrase_values = phrases_raw if isinstance(phrases_raw, list) else []
    blocked_phrases = [
        str(phrase or "").strip().lower()
        for phrase in blocked_phrase_values
        if str(phrase or "").strip()
    ]
    active_provider_markers_raw = BLOCK_SIGNATURES.get("active_provider_markers")
    active_provider_markers = (
        active_provider_markers_raw if isinstance(active_provider_markers_raw, list) else []
    )
    active_markers = [
        str(item.get("marker") or "").strip().lower()
        for item in active_provider_markers
        if isinstance(item, dict) and str(item.get("marker") or "").strip()
    ]
    challenge_elements_raw = BLOCK_SIGNATURES.get("challenge_elements")
    challenge_elements = challenge_elements_raw if isinstance(challenge_elements_raw, dict) else {}
    html_markers_raw = challenge_elements.get("html_markers")
    html_markers_map = html_markers_raw if isinstance(html_markers_raw, dict) else {}
    html_markers = [
        str(marker or "").strip().lower()
        for marker in html_markers_map.keys()
        if str(marker or "").strip()
    ]
    title_patterns_raw = BLOCK_SIGNATURES.get("title_regexes")
    title_pattern_values = title_patterns_raw if isinstance(title_patterns_raw, list) else []
    title_patterns = [
        str(pattern or "").strip()
        for pattern in title_pattern_values
        if str(pattern or "").strip()
    ]
    phrase_hit = any(phrase in lowered for phrase in blocked_phrases)
    active_provider_hit = any(marker in lowered for marker in active_markers)
    challenge_html_hit = any(marker in lowered for marker in html_markers)
    title_hit = any(
        re.search(pattern, lowered, re.IGNORECASE) is not None
        for pattern in title_patterns
    )
    return (active_provider_hit or challenge_html_hit) and (phrase_hit or title_hit)


def _postprocess_detail_records(
    records: list[dict],
    *,
    html: str,
) -> list[dict]:
    rows: list[dict] = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        normalize_variant_record(record)
        _backfill_detail_price_from_html(record, html=html)
        drop_low_signal_zero_detail_price(record)
        rows.append(record)
    return rows


def _backfill_listing_rows_from_network(
    rows: list[dict],
    *,
    network_payloads: list[dict[str, object]] | None,
) -> list[dict]:
    if not rows or not network_payloads:
        return rows
    fields_by_id, fields_by_title = _listing_network_backfill_maps(network_payloads)
    if not fields_by_id and not fields_by_title:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(
            row.get(field_name) not in (None, "", [], {})
            for field_name in LISTING_NETWORK_BACKFILL_FIELDS
        ):
            continue
        candidate = None
        row_url = str(row.get("url") or "").strip()
        row_id = _listing_identity_from_url(row_url)
        if row_id:
            candidate = fields_by_id.get(row_id)
        if candidate is None:
            row_title = clean_text(row.get("title"))
            if row_title:
                candidate = fields_by_title.get(row_title.lower())
        if not isinstance(candidate, dict):
            continue
        price = candidate.get("price")
        currency = candidate.get("currency")
        brand = candidate.get("brand")
        if price not in (None, "", [], {}) and row.get("price") in (None, "", [], {}):
            row["price"] = price
        if currency not in (None, "", [], {}) and row.get("currency") in (None, "", [], {}):
            row["currency"] = currency
        if brand not in (None, "", [], {}) and row.get("brand") in (None, "", [], {}):
            row["brand"] = brand
    return rows


def _backfill_listing_rows_from_adapter(
    rows: list[dict],
    *,
    adapter_rows: list[dict[str, Any]],
) -> list[dict]:
    if not rows or not adapter_rows:
        return rows
    adapter_by_url = {
        str(row.get("url") or "").strip(): row
        for row in adapter_rows
        if isinstance(row, dict) and str(row.get("url") or "").strip()
    }
    adapter_by_identity = {
        identity: row
        for row in adapter_rows
        if isinstance(row, dict) and (identity := _listing_row_identity(row))
    }
    if not adapter_by_url and not adapter_by_identity:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        adapter_row = adapter_by_url.get(str(row.get("url") or "").strip())
        if adapter_row is None:
            row_identity = _listing_row_identity(row)
            if row_identity:
                adapter_row = adapter_by_identity.get(row_identity)
        if not isinstance(adapter_row, dict):
            continue
        for field_name, value in adapter_row.items():
            if str(field_name).startswith("_") or value in (None, "", [], {}):
                continue
            if row.get(field_name) in (None, "", [], {}):
                row[field_name] = value
    return rows


def _listing_network_backfill_maps(
    network_payloads: list[dict[str, object]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_id: dict[str, dict[str, str]] = {}
    by_title: dict[str, dict[str, str]] = {}
    alias_lookup = surface_alias_lookup("ecommerce_listing", None)
    for payload in list(network_payloads or []):
        body = payload.get("body")
        for candidate in _iter_listing_price_candidates(body):
            entry = _listing_candidate_backfill_entry(candidate, alias_lookup=alias_lookup)
            if not entry:
                continue
            identifier = _first_candidate_text(candidate, LISTING_NETWORK_ID_KEYS)
            if identifier:
                by_id[identifier.lower()] = entry
            title = _first_candidate_text(candidate, LISTING_NETWORK_TITLE_KEYS)
            if title:
                by_title[title.lower()] = entry
    return by_id, by_title


def _iter_listing_price_candidates(value: object, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4:
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(
            key in value
            for key in (
                *LISTING_NETWORK_PRICE_CANDIDATE_KEYS,
                *LISTING_NETWORK_BRAND_CANDIDATE_KEYS,
            )
        ) and any(
            key in value
            for key in (
                *LISTING_NETWORK_TITLE_KEYS,
                *LISTING_NETWORK_ID_KEYS,
            )
        ):
            rows.append(value)
        for item in value.values():
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
        return rows
    if isinstance(value, list):
        for item in value[:200]:
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
    return rows


def _first_candidate_text(candidate: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = clean_text(candidate.get(key))
        if value:
            return value
    return ""


def _listing_candidate_backfill_entry(
    candidate: dict[str, Any],
    *,
    alias_lookup: dict[str, str],
) -> dict[str, str]:
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(candidate, alias_lookup, "", candidates)
    entry: dict[str, str] = {}
    brand = finalize_candidate_value("brand", candidates.get("brand", []))
    if brand not in (None, "", [], {}):
        entry["brand"] = str(brand)
    price = _listing_candidate_price(candidate)
    if price:
        entry["price"] = price
    currency = _listing_candidate_currency(candidate)
    if currency:
        entry["currency"] = currency
    return entry


def _listing_candidate_price(candidate: dict[str, Any]) -> str | None:
    currency = _listing_candidate_currency(candidate)
    raw_price = _listing_candidate_raw_price(candidate)
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


def _listing_candidate_raw_price(candidate: dict[str, Any]) -> object | None:
    prices = candidate.get("prices")
    offers = candidate.get("offers")
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), None)
    for key in LISTING_NETWORK_DIRECT_PRICE_KEYS:
        if candidate.get(key) not in (None, "", [], {}):
            return candidate.get(key)
    if isinstance(prices, dict):
        for bucket_name in LISTING_NETWORK_PRICE_BUCKETS:
            bucket = prices.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            for key in ("value", *LISTING_NETWORK_PRIMARY_PRICE_KEYS):
                if bucket.get(key) not in (None, "", [], {}):
                    return bucket.get(key)
            for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
                if bucket.get(key) not in (None, "", [], {}):
                    return bucket.get(key)
        for key in LISTING_NETWORK_PRIMARY_PRICE_KEYS:
            if prices.get(key) not in (None, "", [], {}):
                return prices.get(key)
        for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
            if prices.get(key) not in (None, "", [], {}):
                return prices.get(key)
    if isinstance(offers, dict):
        for key in LISTING_NETWORK_PRIMARY_PRICE_KEYS:
            if offers.get(key) not in (None, "", [], {}):
                return offers.get(key)
        for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
            if offers.get(key) not in (None, "", [], {}):
                return offers.get(key)
    return None


def _listing_candidate_currency(candidate: dict[str, Any]) -> str | None:
    prices = candidate.get("prices")
    if isinstance(prices, dict):
        for bucket_name in LISTING_NETWORK_PRICE_BUCKETS:
            bucket = prices.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            code = _listing_currency_code(bucket.get("currency"))
            if code:
                return code
        code = _listing_currency_code(prices.get("currency"))
        if code:
            return code
        for key in ("currencyCode", "priceCurrency"):
            code = clean_text(prices.get(key))
            if code:
                return code
    offers = candidate.get("offers")
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), None)
    if isinstance(offers, dict):
        code = clean_text(offers.get("priceCurrency"))
        if code:
            return code
    return clean_text(candidate.get("currency") or candidate.get("currencyCode")) or None


def _listing_currency_code(value: object) -> str | None:
    if isinstance(value, dict):
        return clean_text(value.get("code") or value.get("currencyCode"))
    return clean_text(value) or None


def _listing_row_identity(row: dict[str, Any]) -> str:
    product_id = clean_text(row.get("product_id") or row.get("productId") or row.get("sku"))
    if product_id:
        return product_id.lower()
    return _listing_identity_from_url(str(row.get("url") or ""))


def _listing_identity_from_url(url: str) -> str:
    if not url:
        return ""
    path = urlsplit(url).path
    match = re.search(r"/([A-Z]\d{6}-\d{3})(?:/|$)", path)
    if match is not None:
        return match.group(1).lower()
    match = re.search(r"/([^/?#]+)/?$", path)
    segment = str(match.group(1) if match is not None else "").strip().lower()
    if not segment:
        return ""
    return re.sub(r"\.(?:html?|php|aspx?)$", "", segment)


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
        if "listing" in surface:
            cleaned = _finalize_listing_price_fields(cleaned)
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
