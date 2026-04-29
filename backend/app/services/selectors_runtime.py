from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.crawl_fetch_runtime import fetch_page
from app.services.config.extraction_rules import (
    COMMERCE_FIELD_HINTS,
    EXTRACTION_RULES,
    JOB_FIELD_HINTS,
    LISTING_URL_HINTS,
    SELECTOR_NOISE_VALUES,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS, LISTING_FIELD_SELECTORS
from app.services.domain_memory_service import (
    load_domain_memory,
    save_domain_memory,
    selector_payload_from_rules,
    selector_rules_from_memory,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import normalize_field_key
from app.services.field_value_core import PRICE_RE, clean_text, coerce_int as _coerce_int
from app.services.llm_runtime import discover_xpath_candidates
from app.services.platform_policy import detect_platform_family, job_platform_families
from app.services.xpath_service import (
    build_absolute_xpath,
    extract_selector_value,
    validate_or_convert_xpath,
)
from app.services.url_safety import ensure_public_crawl_targets


def infer_surface(*, url: str, expected_fields: Iterable[str] | None = None) -> str:
    normalized_fields = {
        normalize_field_key(value) for value in list(expected_fields or []) if value
    }
    lowered_url = str(url or "").lower()
    if normalized_fields & JOB_FIELD_HINTS:
        return "job_detail"
    if any(hint in lowered_url for hint in LISTING_URL_HINTS):
        return "ecommerce_listing"
    if normalized_fields & COMMERCE_FIELD_HINTS:
        return "ecommerce_detail"
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
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_domain:
        records: list[dict[str, object]] = []
        for memory in await _all_domain_memories(session):
            for row in selector_rules_from_memory(memory):
                records.append(
                    {
                        **dict(row),
                        "id": _coerce_int(row.get("id"), default=0),
                        "domain": memory.domain,
                        "surface": memory.surface,
                        "source_run_id": row.get("source_run_id"),
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                    }
                )
        return records
    if not normalized_surface:
        domain_records: list[dict[str, object]] = []
        for memory in await _all_domain_memories(session):
            if memory.domain != normalized_domain:
                continue
            for row in selector_rules_from_memory(memory):
                domain_records.append(
                    {
                        **dict(row),
                        "id": _coerce_int(row.get("id"), default=0),
                        "domain": memory.domain,
                        "surface": memory.surface,
                        "source_run_id": row.get("source_run_id"),
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                    }
                )
        return domain_records
    memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return [
        {
            **dict(row),
            "id": _coerce_int(row.get("id"), default=0),
            "domain": normalized_domain,
            "surface": normalized_surface,
            "source_run_id": row.get("source_run_id"),
            "created_at": memory.created_at if memory is not None else None,
            "updated_at": memory.updated_at if memory is not None else None,
        }
        for row in selector_rules_from_memory(memory)
    ]


async def list_selector_domain_summaries(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, object]]:
    from sqlalchemy import select

    from app.models.crawl import DomainMemory

    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    query = select(DomainMemory).order_by(DomainMemory.id.asc())
    if normalized_domain:
        query = query.where(DomainMemory.domain == normalized_domain)
    if normalized_surface:
        query = query.where(DomainMemory.surface == normalized_surface)
    if offset > 0:
        query = query.offset(int(offset))
    if limit is not None:
        query = query.limit(int(limit))
    result = await session.execute(query)
    summaries: list[dict[str, object]] = []
    for memory in list(result.scalars().all()):
        summaries.append(
            {
                "domain": memory.domain,
                "surface": memory.surface,
                "selector_count": _selector_rule_count(memory.selectors),
                "updated_at": memory.updated_at,
            }
        )
    return summaries


async def create_selector_record(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    payload: dict[str, object],
    commit: bool = True,
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
        "source_run_id": payload.get("source_run_id"),
        "is_active": bool(payload.get("is_active", True)),
    }
    rules = [row for row in rules if _coerce_int(row.get("id"), default=0) != next_id]
    rules.append(record)
    await save_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        selectors=selector_payload_from_rules(rules),
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return {
        "domain": normalized_domain,
        "surface": normalized_surface,
        **record,
        "created_at": memory.created_at if memory is not None else None,
        "updated_at": memory.updated_at if memory is not None else None,
    }


async def update_selector_record(
    session: AsyncSession,
    *,
    selector_id: int,
    payload: dict[str, object],
    commit: bool = True,
) -> dict[str, object] | None:
    await _ensure_unique_selector_ids(session)
    for memory in await _all_domain_memories(session):
        rules = selector_rules_from_memory(memory)
        updated = False
        for row in rules:
            if _coerce_int(row.get("id"), default=0) != int(selector_id):
                continue
            for key in (
                "field_name",
                "css_selector",
                "xpath",
                "regex",
                "status",
                "sample_value",
                "source",
                "source_run_id",
                "is_active",
            ):
                if key not in payload:
                    continue
                value = payload.get(key)
                if key == "field_name":
                    row[key] = str(value or "").strip().lower()
                elif key == "is_active":
                    row[key] = bool(value)
                elif key == "source_run_id":
                    row[key] = value
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
        if commit:
            await session.commit()
        else:
            await session.flush()
        refreshed_memory = await load_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
        )
        refreshed = next(
            row for row in rules if _coerce_int(row.get("id"), default=0) == int(selector_id)
        )
        return {
            "domain": memory.domain,
            "surface": memory.surface,
            **refreshed,
            "created_at": (
                refreshed_memory.created_at if refreshed_memory is not None else None
            ),
            "updated_at": (
                refreshed_memory.updated_at if refreshed_memory is not None else None
            ),
        }
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
            row for row in rules if _coerce_int(row.get("id"), default=0) != int(selector_id)
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
    domain = normalize_domain(final_url)
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

    if resolved_surface.endswith("_listing"):
        for field_name in expected_columns:
            normalized_field = normalize_field_key(field_name)
            for row in _listing_card_suggestions(
                soup,
                html=html,
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
            if not field_name:
                continue
            xpath = str(row.get("xpath") or "").strip() or None
            css_selector = str(row.get("css_selector") or "").strip() or None
            if not xpath and not css_selector:
                continue
            if xpath:
                validated_xpath, _ = validate_or_convert_xpath(xpath)
                if validated_xpath:
                    sample_value, _count, selector_used = extract_selector_value(
                        html,
                        xpath=validated_xpath,
                    )
                    if _is_noise_value(sample_value, field_name):
                        xpath = None
                    elif sample_value or selector_used:
                        candidate: dict[str, object] = {
                            "field_name": field_name,
                            "xpath": selector_used or validated_xpath,
                            "sample_value": sample_value,
                            "source": "llm_xpath",
                        }
                        if not _suggestion_exists(suggestions[field_name], candidate):
                            suggestions[field_name].append(candidate)
            if css_selector:
                sample_value, _count, selector_used = extract_selector_value(
                    html,
                    css_selector=css_selector,
                )
                if _is_noise_value(sample_value, field_name):
                    css_selector = None
                elif sample_value or selector_used:
                    css_candidate: dict[str, object] = {
                        "field_name": field_name,
                        "css_selector": selector_used or css_selector,
                        "sample_value": sample_value,
                        "source": "llm_css",
                    }
                    if not _suggestion_exists(suggestions[field_name], css_candidate):
                        suggestions[field_name].append(css_candidate)

    return {
        "surface": resolved_surface,
        "preview_url": final_url,
        "iframe_promoted": bool(document.get("iframe_promoted")),
        "suggestions": {
            normalize_field_key(field_name): values[:5]
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
            max_id = max(max_id, _coerce_int(row.get("id"), default=0))
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
            current_id = _coerce_int(row.get("id"), default=0)
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


def _selector_rule_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    rules = value.get("rules")
    if isinstance(rules, list):
        return sum(1 for row in rules if isinstance(row, dict))
    return sum(
        1
        for field_name, payload in value.items()
        if not str(field_name).startswith("_") and isinstance(payload, dict)
    )


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


def _listing_card_suggestions(
    soup: BeautifulSoup,
    *,
    html: str,
    field_name: str,
) -> list[dict[str, object]]:
    card_selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    first_card = None
    for card_sel in card_selectors:
        cards = soup.select(str(card_sel))
        if cards:
            first_card = cards[0]
            break
    if not first_card:
        return []
    field_selectors = LISTING_FIELD_SELECTORS.get(field_name, [])
    if not field_selectors:
        return []
    suggestions: list[dict[str, object]] = []
    for sel in field_selectors:
        nodes = first_card.select(sel)
        if not nodes:
            continue
        node = nodes[0]
        xpath = build_absolute_xpath(node)
        if not xpath:
            continue
        sample_value, count, selector_used = extract_selector_value(html, xpath=xpath)
        if count <= 0:
            continue
        suggestion: dict[str, object] = {
            "field_name": field_name,
            "xpath": selector_used or xpath,
            "sample_value": sample_value,
            "source": "listing_card_xpath",
        }
        if not _suggestion_exists(suggestions, suggestion):
            suggestions.append(suggestion)
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


_SELECTOR_NOISE_FROZEN = frozenset(
    str(v).strip().lower() for v in (SELECTOR_NOISE_VALUES or []) if str(v).strip()
)


def _is_noise_value(value: str | None, field_name: str) -> bool:
    if not value:
        return False
    cleaned = " ".join(str(value).split()).strip().lower()
    if len(cleaned) < 3:
        return True
    if cleaned in _SELECTOR_NOISE_FROZEN:
        return True
    return False


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
