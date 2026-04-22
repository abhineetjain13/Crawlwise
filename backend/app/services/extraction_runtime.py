from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET

from app.services.detail_extractor import extract_detail_records
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
from app.services.listing_extractor import extract_listing_records
from app.services.config.runtime_settings import crawler_runtime_settings

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
        return json_records[:max_records]
    if "listing" in surface:
        if adapter_records:
            rows: list[dict[str, Any]] = []
            for record in list(adapter_records or [])[:max_records]:
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
                    rows.append(shaped)
            return rows
        return extract_listing_records(
            html,
            page_url,
            surface,
            max_records=max_records,
            artifacts=artifacts,
            selector_rules=selector_rules,
        )
    return extract_detail_records(
        html,
        page_url,
        surface,
        requested_page_url=requested_page_url,
        requested_fields=requested_fields,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )[:max_records]


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
