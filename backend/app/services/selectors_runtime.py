from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.crawl_fetch_runtime import fetch_page
from app.services.config.extraction_rules import EXTRACTION_RULES
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_memory_service import (
    load_domain_memory,
    save_domain_memory,
    selector_payload_from_rules,
    selector_rules_from_memory,
)
from app.services.field_policy import normalize_field_key
from app.services.field_value_utils import PRICE_RE, clean_text
from app.services.llm_runtime import discover_xpath_candidates
from app.services.platform_policy import detect_platform_family, job_platform_families
from app.services.xpath_service import (
    build_absolute_xpath,
    extract_selector_value,
    validate_or_convert_xpath,
)
from app.services.url_safety import ensure_public_crawl_targets


_COMMERCE_FIELD_HINTS = {
    "title",
    "price",
    "brand",
    "sku",
    "rating",
    "in_stock",
    "availability",
    "image_url",
}
_JOB_FIELD_HINTS = {
    "company",
    "location",
    "apply_url",
    "salary",
    "remote",
    "responsibilities",
    "qualifications",
}


def infer_surface(*, url: str, expected_fields: Iterable[str] | None = None) -> str:
    normalized_fields = {
        normalize_field_key(value) for value in list(expected_fields or []) if value
    }
    if normalized_fields & _JOB_FIELD_HINTS:
        return "job_detail"
    if normalized_fields & _COMMERCE_FIELD_HINTS:
        return "ecommerce_detail"
    lowered_url = str(url or "").lower()
    detected_family = str(detect_platform_family(url) or "").strip().lower()
    if detected_family and detected_family in job_platform_families():
        return "job_detail"
    if any(token in lowered_url for token in ("jobs", "careers")):
        return "job_detail"
    return "ecommerce_detail"


async def fetch_selector_document(url: str) -> dict[str, object]:
    await ensure_public_crawl_targets([url])
    result = await fetch_page(str(url), prefer_browser=False)
    final_url = result.final_url
    html = result.html
    promoted = False
    visited = {final_url}
    for _ in range(max(1, int(crawler_runtime_settings.iframe_promotion_max_candidates))):
        candidate_url = _primary_iframe_candidate(final_url, html)
        if not candidate_url or candidate_url in visited:
            break
        iframe_result = await fetch_page(candidate_url, prefer_browser=False)
        iframe_text = clean_text(BeautifulSoup(iframe_result.html, "html.parser").get_text(" ", strip=True))
        page_text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        if len(iframe_text) <= len(page_text):
            break
        final_url = iframe_result.final_url
        html = iframe_result.html
        promoted = True
        visited.add(final_url)
    return {
        "url": final_url,
        "html": html,
        "iframe_promoted": promoted,
    }


def build_preview_html(*, source_url: str, html: str) -> str:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    head = soup.head or soup.new_tag("head")
    if soup.head is None:
        if soup.html is None:
            html_node = soup.new_tag("html")
            body = soup.body or soup.new_tag("body")
            body.extend(list(soup.children))
            html_node.append(head)
            html_node.append(body)
            soup.append(html_node)
        else:
            soup.html.insert(0, head)
    base = soup.new_tag("base", href=str(source_url or ""))
    head.insert(0, base)
    return str(soup)


async def list_selector_records(
    session: AsyncSession,
    *,
    domain: str,
    surface: str = "generic",
) -> list[dict[str, object]]:
    memory = await load_domain_memory(session, domain=domain, surface=surface)
    return [
        {
            "id": int(row.get("id") or 0),
            "domain": str(domain or "").strip().lower(),
            "surface": str(surface or "").strip().lower(),
            **dict(row),
        }
        for row in selector_rules_from_memory(memory)
    ]


async def create_selector_record(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    payload: dict[str, object],
) -> dict[str, object]:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower() or "generic"
    await _ensure_unique_selector_ids(session)
    memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    rules = selector_rules_from_memory(memory)
    next_id = await _next_selector_id(session)
    record = {
        "id": next_id,
        "field_name": str(payload.get("field_name") or "").strip().lower(),
        "css_selector": str(payload.get("css_selector") or "").strip() or None,
        "xpath": str(payload.get("xpath") or "").strip() or None,
        "regex": str(payload.get("regex") or "").strip() or None,
        "status": str(payload.get("status") or "validated").strip(),
        "sample_value": str(payload.get("sample_value") or "").strip() or None,
        "source": str(payload.get("source") or "domain_memory").strip(),
        "is_active": bool(payload.get("is_active", True)),
    }
    rules = [row for row in rules if int(row.get("id") or 0) != next_id]
    rules.append(record)
    await save_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        selectors=selector_payload_from_rules(rules),
    )
    await session.commit()
    return {"domain": normalized_domain, "surface": normalized_surface, **record}


async def update_selector_record(
    session: AsyncSession,
    *,
    selector_id: int,
    payload: dict[str, object],
) -> dict[str, object] | None:
    await _ensure_unique_selector_ids(session)
    for memory in await _all_domain_memories(session):
        rules = selector_rules_from_memory(memory)
        updated = False
        for row in rules:
            if int(row.get("id") or 0) != int(selector_id):
                continue
            for key in (
                "field_name",
                "css_selector",
                "xpath",
                "regex",
                "status",
                "sample_value",
                "source",
                "is_active",
            ):
                if key not in payload:
                    continue
                value = payload.get(key)
                if key == "field_name":
                    row[key] = str(value or "").strip().lower()
                elif key == "is_active":
                    row[key] = bool(value)
                else:
                    row[key] = str(value or "").strip() or None
            updated = True
            break
        if not updated:
            continue
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(rules),
        )
        await session.commit()
        refreshed = next(
            row for row in rules if int(row.get("id") or 0) == int(selector_id)
        )
        return {"domain": memory.domain, "surface": memory.surface, **refreshed}
    return None


async def delete_selector_record(
    session: AsyncSession,
    *,
    selector_id: int,
) -> bool:
    await _ensure_unique_selector_ids(session)
    for memory in await _all_domain_memories(session):
        rules = selector_rules_from_memory(memory)
        next_rules = [
            row for row in rules if int(row.get("id") or 0) != int(selector_id)
        ]
        if len(next_rules) == len(rules):
            continue
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(next_rules),
        )
        await session.commit()
        return True
    return False


async def delete_domain_selector_records(
    session: AsyncSession,
    *,
    domain: str,
    surface: str | None = None,
) -> int:
    await _ensure_unique_selector_ids(session)
    deleted = 0
    normalized_domain = str(domain or "").strip().lower()
    for memory in await _all_domain_memories(session):
        if memory.domain != normalized_domain:
            continue
        if surface and memory.surface != str(surface or "").strip().lower():
            continue
        rules = selector_rules_from_memory(memory)
        deleted += len(rules)
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules([]),
        )
    if deleted:
        await session.commit()
    return deleted


async def suggest_selectors(
    session: AsyncSession,
    *,
    url: str,
    expected_columns: list[str],
    surface: str | None = None,
) -> dict[str, object]:
    document = await fetch_selector_document(url)
    final_url = str(document["url"])
    html = str(document["html"])
    resolved_surface = str(surface or "").strip().lower() or infer_surface(
        url=final_url,
        expected_fields=expected_columns,
    )
    domain = _normalized_domain(final_url)
    suggestions: dict[str, list[dict[str, object]]] = defaultdict(list)

    for row in await list_selector_records(
        session,
        domain=domain,
        surface=resolved_surface,
    ):
        field_name = str(row.get("field_name") or "").strip().lower()
        if field_name and field_name in {normalize_field_key(item) for item in expected_columns}:
            suggestions[field_name].append(_selector_suggestion_from_record(row))

    soup = BeautifulSoup(html, "html.parser")
    for field_name in expected_columns:
        normalized_field = normalize_field_key(field_name)
        for row in _deterministic_suggestions(
            soup,
            html=html,
            url=final_url,
            field_name=normalized_field,
        ):
            if not _suggestion_exists(suggestions[normalized_field], row):
                suggestions[normalized_field].append(row)

    llm_candidates, llm_error = await discover_xpath_candidates(
        session,
        run_id=0,
        domain=domain,
        url=final_url,
        html_text=html,
        missing_fields=[normalize_field_key(value) for value in expected_columns],
        existing_values={},
    )
    if not llm_error:
        for row in llm_candidates:
            if not isinstance(row, dict):
                continue
            field_name = normalize_field_key(str(row.get("field_name") or ""))
            xpath = str(row.get("xpath") or "").strip()
            if not field_name or not xpath:
                continue
            validated_xpath, _ = validate_or_convert_xpath(xpath)
            if not validated_xpath:
                continue
            sample_value, _count, selector_used = extract_selector_value(
                html,
                xpath=validated_xpath,
            )
            candidate = {
                "field_name": field_name,
                "xpath": selector_used or validated_xpath,
                "sample_value": sample_value,
                "source": "llm_xpath",
            }
            if not _suggestion_exists(suggestions[field_name], candidate):
                suggestions[field_name].append(candidate)

    return {
        "surface": resolved_surface,
        "preview_url": final_url,
        "iframe_promoted": bool(document.get("iframe_promoted")),
        "suggestions": {
            normalize_field_key(field_name): values[:3]
            for field_name, values in suggestions.items()
        },
    }


async def test_selector(
    *,
    url: str,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> dict[str, object]:
    document = await fetch_selector_document(url)
    matched_value, count, selector_used = extract_selector_value(
        str(document["html"]),
        css_selector=css_selector,
        xpath=xpath,
        regex=regex,
    )
    return {
        "matched_value": matched_value,
        "count": count,
        "selector_used": selector_used,
    }


async def _all_domain_memories(session: AsyncSession) -> list[Any]:
    from sqlalchemy import select

    from app.models.crawl import DomainMemory

    result = await session.execute(select(DomainMemory).order_by(DomainMemory.id.asc()))
    return list(result.scalars().all())


async def _next_selector_id(session: AsyncSession) -> int:
    max_id = 0
    for memory in await _all_domain_memories(session):
        for row in selector_rules_from_memory(memory):
            max_id = max(max_id, int(row.get("id") or 0))
    return max_id + 1


async def _ensure_unique_selector_ids(session: AsyncSession) -> None:
    memories = await _all_domain_memories(session)
    seen_ids: set[int] = set()
    next_id = 1
    changed = False
    for memory in memories:
        rules = selector_rules_from_memory(memory)
        memory_changed = False
        for row in rules:
            current_id = int(row.get("id") or 0)
            if current_id > 0 and current_id not in seen_ids:
                seen_ids.add(current_id)
                next_id = max(next_id, current_id + 1)
                continue
            row["id"] = next_id
            seen_ids.add(next_id)
            next_id += 1
            memory_changed = True
        if not memory_changed:
            continue
        changed = True
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(rules),
        )
    if changed:
        await session.flush()


def _normalized_domain(url: str) -> str:
    from app.services.domain_utils import normalize_domain

    return normalize_domain(url)


def _primary_iframe_candidate(page_url: str, html: str) -> str:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    if len(page_text) > 400:
        return ""
    for frame in soup.select("iframe[src]"):
        src = str(frame.get("src") or "").strip()
        if not src:
            continue
        return urljoin(page_url, src)
    return ""


def _selector_suggestion_from_record(record: dict[str, object]) -> dict[str, object]:
    return {
        "field_name": str(record.get("field_name") or "").strip().lower(),
        "css_selector": record.get("css_selector"),
        "xpath": record.get("xpath"),
        "regex": record.get("regex"),
        "sample_value": record.get("sample_value"),
        "source": record.get("source") or "domain_memory",
    }


def _deterministic_suggestions(
    soup: BeautifulSoup,
    *,
    html: str,
    url: str,
    field_name: str,
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    selector = str((EXTRACTION_RULES.get("dom_patterns") or {}).get(field_name) or "").strip()
    if selector:
        matched_value, count, _selector_used = extract_selector_value(html, css_selector=selector)
        if count > 0:
            suggestions.append(
                {
                    "field_name": field_name,
                    "css_selector": selector,
                    "sample_value": matched_value,
                    "source": "auto_css",
                }
            )

    for node in _candidate_nodes_for_field(soup, field_name):
        suggestion = _build_node_suggestion(node, field_name, html)
        if suggestion and not _suggestion_exists(suggestions, suggestion):
            suggestions.append(suggestion)
    if field_name == "price":
        price_match = PRICE_RE.search(clean_text(soup.get_text(" ", strip=True)))
        if price_match:
            suggestions.append(
                {
                    "field_name": field_name,
                    "regex": PRICE_RE.pattern,
                    "sample_value": price_match.group(0),
                    "source": "auto_regex",
                }
            )
    return suggestions


def _candidate_nodes_for_field(soup: BeautifulSoup, field_name: str) -> list[Tag]:
    selectors_by_field = {
        "title": ["h1", "[itemprop='name']", "meta[property='og:title']"],
        "price": [
            "[itemprop='price']",
            "[class*='price']",
            "[data-test*='price']",
        ],
        "brand": ["[itemprop='brand']", "[class*='brand']", "[data-test*='brand']"],
        "sku": ["[itemprop='sku']", "[data-sku]", "[class*='sku']"],
        "rating": ["[itemprop='ratingValue']", "[class*='rating']"],
        "availability": ["[itemprop='availability']", "[class*='stock']"],
        "in_stock": ["button:not([disabled])", "[itemprop='availability']"],
    }
    nodes: list[Tag] = []
    for selector in selectors_by_field.get(field_name, []):
        for node in soup.select(selector):
            if isinstance(node, Tag):
                nodes.append(node)
    return nodes[:3]


def _build_node_suggestion(
    node: Tag,
    field_name: str,
    html: str,
) -> dict[str, object] | None:
    if node.name == "meta":
        prop = str(node.get("property") or node.get("itemprop") or "").strip()
        if prop:
            sample_value, count, _selector_used = extract_selector_value(
                html,
                css_selector=f"meta[property='{prop}'], meta[itemprop='{prop}']",
            )
            if count > 0:
                return {
                    "field_name": field_name,
                    "css_selector": f"meta[property='{prop}'], meta[itemprop='{prop}']",
                    "sample_value": sample_value,
                    "source": "auto_meta",
                }
    xpath = build_absolute_xpath(node)
    if not xpath:
        return None
    sample_value, count, selector_used = extract_selector_value(html, xpath=xpath)
    if count <= 0:
        return None
    return {
        "field_name": field_name,
        "xpath": selector_used or xpath,
        "sample_value": sample_value,
        "source": "auto_xpath",
    }


def _suggestion_exists(
    rows: list[dict[str, object]],
    candidate: dict[str, object],
) -> bool:
    candidate_key = (
        str(candidate.get("field_name") or ""),
        str(candidate.get("css_selector") or ""),
        str(candidate.get("xpath") or ""),
        str(candidate.get("regex") or ""),
    )
    return any(
        (
            str(row.get("field_name") or ""),
            str(row.get("css_selector") or ""),
            str(row.get("xpath") or ""),
            str(row.get("regex") or ""),
        )
        == candidate_key
        for row in rows
    )
