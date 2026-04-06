# Selector CRUD and testing service.
from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
import regex as regex_lib

from app.models.selector import Selector
from app.services.acquisition.browser_client import fetch_rendered_html
from app.services.acquisition.http_client import fetch_html
from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import (
    clear_selector_defaults,
    get_selector_defaults,
    load_selector_defaults,
    save_domain_selector_defaults,
)
from app.services.llm_runtime import discover_xpath_candidates
from app.services.site_memory_service import clear_all_selector_memory, replace_selector_map
from app.services.xpath_service import (
    build_deterministic_selector_suggestions,
    extract_selector_value,
    validate_xpath_syntax,
)

logger = logging.getLogger(__name__)


async def list_selectors(session: AsyncSession, domain: str = "") -> list[Selector]:
    query = select(Selector).order_by(Selector.created_at.desc())
    if domain:
        query = query.where(Selector.domain == domain)
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_selector(session: AsyncSession, payload: dict) -> Selector:
    selector = Selector(**_normalize_selector_payload(payload))
    snapshots = _snapshot_selector_defaults([selector.domain])
    session.add(selector)
    await session.flush()
    try:
        await _sync_selector_defaults(session, selector.domain)
        await session.commit()
    except Exception:
        await session.rollback()
        await _restore_selector_defaults(snapshots)
        raise
    await session.refresh(selector)
    return selector


async def update_selector(session: AsyncSession, selector: Selector, payload: dict) -> Selector:
    previous_domain = selector.domain
    normalized_payload = _normalize_selector_payload({**selector.__dict__, **payload})
    for key, value in normalized_payload.items():
        setattr(selector, key, value)
    selector.last_validated_at = datetime.now(UTC)
    updated_domain = selector.domain
    snapshots = _snapshot_selector_defaults([previous_domain, updated_domain])
    await session.flush()
    try:
        if previous_domain != updated_domain:
            await _sync_selector_defaults(session, previous_domain)
        await _sync_selector_defaults(session, updated_domain)
        await session.commit()
    except Exception:
        await session.rollback()
        await _restore_selector_defaults(snapshots)
        raise
    await session.refresh(selector)
    return selector


async def delete_selector(session: AsyncSession, selector_id: int) -> None:
    result = await session.execute(select(Selector).where(Selector.id == selector_id))
    selector = result.scalar_one_or_none()
    if selector is None:
        return
    domain = selector.domain
    snapshots = _snapshot_selector_defaults([domain])
    await session.execute(delete(Selector).where(Selector.id == selector_id))
    await session.flush()
    try:
        await _sync_selector_defaults(session, domain)
        await session.commit()
    except Exception:
        await session.rollback()
        await _restore_selector_defaults(snapshots)
        raise


async def delete_selectors_for_domain(session: AsyncSession, domain: str) -> int:
    normalized_domain = str(domain or "").strip().lower()
    if not normalized_domain:
        return 0
    snapshots = _snapshot_selector_defaults([normalized_domain])
    result = await session.execute(select(Selector).where(Selector.domain == normalized_domain))
    rows = list(result.scalars().all())
    if not rows:
        return 0
    await session.execute(delete(Selector).where(Selector.domain == normalized_domain))
    await session.flush()
    try:
        await _sync_selector_defaults(session, normalized_domain)
        await session.commit()
    except Exception:
        await session.rollback()
        await _restore_selector_defaults(snapshots)
        raise
    return len(rows)


async def clear_all_selectors(session: AsyncSession) -> int:
    selector_defaults_snapshot = load_selector_defaults()
    result = await session.execute(select(Selector))
    rows = list(result.scalars().all())
    if not rows and not selector_defaults_snapshot:
        return 0
    if rows:
        await session.execute(delete(Selector))
        await session.flush()
    try:
        await clear_all_selector_memory(session, clear_suggestions=True, commit=False)
        await clear_selector_defaults()
        await session.commit()
    except Exception:
        await session.rollback()
        await _restore_all_selector_defaults(selector_defaults_snapshot)
        raise
    return len(rows)


async def test_selector(
    url: str,
    *,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> tuple[str | None, int, str | None]:
    if css_selector and any(token in css_selector for token in (">>>", "::shadow")):
        html_text = (await fetch_rendered_html(url)).html
    else:
        html_text = await fetch_html(url)
    return extract_selector_value(
        html_text,
        css_selector=css_selector,
        xpath=xpath,
        regex=regex,
    )


async def suggest_selectors(session: AsyncSession, url: str, expected_columns: list[str]) -> dict[str, list[dict]]:
    html_text = await fetch_html(url)
    domain = normalize_domain(url)
    selector_defaults = {
        str(field_name or "").strip().lower(): get_selector_defaults(domain, field_name)
        for field_name in expected_columns
    }
    deterministic = build_deterministic_selector_suggestions(
        html_text,
        expected_columns,
        selector_defaults=selector_defaults,
    )
    llm_rows, _llm_error = await discover_xpath_candidates(
        session,
        run_id=0,
        domain=domain,
        url=url,
        html_text=html_text,
        missing_fields=expected_columns,
        existing_values={},
    )
    llm_grouped: dict[str, list[dict]] = {}
    for row in llm_rows:
        field_name = str(row.get("field_name") or "").strip().lower()
        xpath = str(row.get("xpath") or "").strip()
        css_selector = str(row.get("css_selector") or "").strip()
        if not field_name or not any([xpath, css_selector]):
            continue
        llm_grouped.setdefault(field_name, []).append({
            "field_name": field_name,
            "xpath": xpath or None,
            "css_selector": css_selector or None,
            "regex": None,
            "status": "suggested",
            "sample_value": str(row.get("expected_value") or row.get("sample_value") or "").strip() or None,
            "source": "llm_discovered",
        })

    merged: dict[str, list[dict]] = {}
    for field_name in expected_columns:
        normalized_field = str(field_name or "").strip().lower()
        merged_rows = [*(selector_defaults.get(normalized_field) or []), *(deterministic.get(normalized_field) or []), *(llm_grouped.get(normalized_field) or [])]
        deduped: list[dict] = []
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for row in merged_rows:
            key = (
                str(row.get("xpath") or "") or None,
                str(row.get("css_selector") or "") or None,
                str(row.get("regex") or "") or None,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        if deduped:
            merged[normalized_field] = deduped
    return merged


async def _sync_selector_defaults(session: AsyncSession, domain: str) -> None:
    if not domain:
        return
    result = await session.execute(
        select(Selector)
        .where(
            Selector.domain == domain,
            Selector.is_active.is_(True),
            Selector.status.in_(["validated", "manual"]),
        )
        .order_by(Selector.field_name.asc(), Selector.created_at.desc())
    )
    selectors = list(result.scalars().all())
    selector_rows_by_field: dict[str, list[dict]] = {}
    for selector in selectors:
        selector_rows_by_field.setdefault(selector.field_name, []).append({
            "xpath": selector.xpath,
            "css_selector": selector.css_selector,
            "regex": selector.regex,
            "status": selector.status,
            "sample_value": selector.sample_value,
            "source": selector.source,
        })
    previous_defaults = load_selector_defaults().get(domain)
    try:
        await save_domain_selector_defaults(domain, selector_rows_by_field)
        await replace_selector_map(session, domain, selector_rows_by_field, commit=False)
    except Exception:
        # Attempt to restore previous defaults, but don't mask the original error
        if previous_defaults is None:
            try:
                await save_domain_selector_defaults(domain, {})
            except Exception:
                logger.warning(
                    "Failed to clear selector defaults during rollback for domain=%s previous_defaults_missing=%s",
                    domain,
                    previous_defaults is None,
                    exc_info=True,
                )
        else:
            try:
                await save_domain_selector_defaults(domain, previous_defaults)
            except Exception:
                logger.warning(
                    "Failed to restore selector defaults during rollback for domain=%s previous_defaults_missing=%s",
                    domain,
                    previous_defaults is None,
                    exc_info=True,
                )
        await session.rollback()
        raise


def _snapshot_selector_defaults(domains: list[str]) -> dict[str, dict[str, list[dict]] | None]:
    current = load_selector_defaults()
    snapshots: dict[str, dict[str, list[dict]] | None] = {}
    for domain in domains:
        normalized = str(domain or "").strip().lower()
        if not normalized or normalized in snapshots:
            continue
        snapshots[normalized] = current.get(normalized)
    return snapshots


async def _restore_selector_defaults(snapshots: dict[str, dict[str, list[dict]] | None]) -> None:
    for domain, value in snapshots.items():
        await save_domain_selector_defaults(domain, value or {})


async def _restore_all_selector_defaults(defaults_snapshot: dict[str, dict[str, list[dict]]]) -> None:
    await clear_selector_defaults()
    for domain, rows_by_field in defaults_snapshot.items():
        await save_domain_selector_defaults(domain, rows_by_field)


def _normalize_selector_payload(payload: dict) -> dict:
    normalized = {
        "domain": str(payload.get("domain") or "").strip().lower(),
        "field_name": str(payload.get("field_name") or "").strip(),
        "css_selector": str(payload.get("css_selector") or "").strip() or None,
        "xpath": str(payload.get("xpath") or "").strip() or None,
        "regex": str(payload.get("regex") or "").strip() or None,
        "status": str(payload.get("status") or "validated").strip() or "validated",
        "sample_value": str(payload.get("sample_value") or "").strip() or None,
        "source": str(payload.get("source") or "manual").strip() or "manual",
        "source_run_id": payload.get("source_run_id"),
        "is_active": bool(payload.get("is_active", True)),
    }
    if not normalized["domain"]:
        raise ValueError("domain is required")
    if not normalized["field_name"]:
        raise ValueError("field_name is required")
    if not any([normalized["css_selector"], normalized["xpath"], normalized["regex"]]):
        raise ValueError("At least one of css_selector, xpath, or regex is required")
    if normalized["xpath"]:
        valid_xpath, xpath_error = validate_xpath_syntax(normalized["xpath"])
        if not valid_xpath:
            raise ValueError(f"Invalid XPath: {xpath_error}")
    if normalized["regex"]:
        try:
            regex_lib.compile(normalized["regex"])
        except regex_lib.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc
    return normalized
