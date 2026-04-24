from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import DomainRunProfile
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain

_FETCH_MODE_VALUES = {
    "auto",
    "http_only",
    "browser_only",
    "http_then_browser",
}
_EXTRACTION_SOURCE_VALUES = {
    "raw_html",
    "rendered_dom",
    "rendered_dom_visual",
    "network_payload_first",
}
_JS_MODE_VALUES = {"auto", "enabled", "disabled"}
_TRAVERSAL_MODE_VALUES = {"auto", "scroll", "load_more", "view_all", "paginate"}
_CAPTURE_NETWORK_VALUES = {"off", "matched_only", "all_small_json"}


def _clean_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_choice(value: object, allowed: set[str], *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _coerce_optional_choice(value: object, allowed: set[str]) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else None


def _coerce_nullable_text(value: object) -> str | None:
    text = _clean_str(value)
    return text or None


def _coerce_proxy_list(value: object) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    seen: set[str] = set()
    proxies: list[str] = []
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        proxies.append(text)
    return proxies


def _coerce_country(value: object) -> str:
    text = str(value or "").strip()
    return text or "auto"


def _coerce_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        result = max(minimum, int(str(value)))
        if maximum is not None:
            result = min(maximum, result)
        return result
    except (TypeError, ValueError):
        return default


def normalize_domain_run_profile(
    profile: object,
    *,
    source_run_id: int,
    saved_at: str | None = None,
) -> dict[str, object]:
    payload = dict(profile or {}) if isinstance(profile, dict) else {}
    fetch_profile = dict(payload.get("fetch_profile") or {})
    locality_profile = dict(payload.get("locality_profile") or {})
    diagnostics_profile = dict(payload.get("diagnostics_profile") or {})
    normalized_saved_at = saved_at or datetime.now(UTC).isoformat()
    normalized_source_run_id = _coerce_int(
        source_run_id,
        default=0,
        minimum=0,
    )
    if normalized_source_run_id <= 0:
        raise ValueError("source_run_id must be a positive integer")
    return {
        "version": 1,
        "fetch_profile": {
            "fetch_mode": _coerce_choice(
                fetch_profile.get("fetch_mode"),
                _FETCH_MODE_VALUES,
                default="auto",
            ),
            "extraction_source": _coerce_choice(
                fetch_profile.get("extraction_source"),
                _EXTRACTION_SOURCE_VALUES,
                default="raw_html",
            ),
            "js_mode": _coerce_choice(
                fetch_profile.get("js_mode"),
                _JS_MODE_VALUES,
                default="auto",
            ),
            "include_iframes": bool(fetch_profile.get("include_iframes", False)),
            "traversal_mode": _coerce_optional_choice(
                fetch_profile.get("traversal_mode"),
                _TRAVERSAL_MODE_VALUES,
            ),
            "request_delay_ms": _coerce_int(
                fetch_profile.get("request_delay_ms"),
                default=crawler_runtime_settings.min_request_delay_ms,
                minimum=crawler_runtime_settings.min_request_delay_ms,
            ),
            "max_pages": _coerce_int(
                fetch_profile.get("max_pages"),
                default=crawler_runtime_settings.default_max_pages,
                minimum=crawler_runtime_settings.min_max_pages,
                maximum=crawler_runtime_settings.max_max_pages,
            ),
            "max_scrolls": _coerce_int(
                fetch_profile.get("max_scrolls"),
                default=crawler_runtime_settings.default_max_scrolls,
                minimum=1,
            ),
        },
        "locality_profile": {
            "geo_country": _coerce_country(locality_profile.get("geo_country")),
            "language_hint": _coerce_nullable_text(locality_profile.get("language_hint")),
            "currency_hint": _coerce_nullable_text(locality_profile.get("currency_hint")),
        },
        "diagnostics_profile": {
            "capture_html": bool(diagnostics_profile.get("capture_html", True)),
            "capture_screenshot": bool(
                diagnostics_profile.get("capture_screenshot", False)
            ),
            "capture_network": _coerce_choice(
                diagnostics_profile.get("capture_network"),
                _CAPTURE_NETWORK_VALUES,
                default="off",
            ),
            "capture_response_headers": bool(
                diagnostics_profile.get("capture_response_headers", True)
            ),
            "capture_browser_diagnostics": bool(
                diagnostics_profile.get("capture_browser_diagnostics", True)
            ),
        },
        "source_run_id": normalized_source_run_id,
        "saved_at": normalized_saved_at,
    }


async def load_domain_run_profile(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> DomainRunProfile | None:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    try:
        result = await session.execute(
            select(DomainRunProfile)
            .where(
                DomainRunProfile.domain == normalized_domain,
                DomainRunProfile.surface == normalized_surface,
            )
            .order_by(DomainRunProfile.updated_at.desc(), DomainRunProfile.id.desc())
            .limit(1)
        )
    except ProgrammingError as exc:
        if "domain_run_profiles" not in str(exc).lower():
            raise
        await session.rollback()
        return None
    return result.scalar_one_or_none()


async def list_domain_run_profiles(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
) -> list[DomainRunProfile]:
    statement = select(DomainRunProfile)
    normalized_domain = normalize_domain(domain or "") if domain else ""
    normalized_surface = str(surface or "").strip().lower()
    if normalized_domain:
        statement = statement.where(DomainRunProfile.domain == normalized_domain)
    if normalized_surface:
        statement = statement.where(DomainRunProfile.surface == normalized_surface)
    try:
        result = await session.execute(
            statement.order_by(
                DomainRunProfile.domain.asc(),
                DomainRunProfile.surface.asc(),
                DomainRunProfile.updated_at.desc(),
                DomainRunProfile.id.desc(),
            )
        )
    except ProgrammingError as exc:
        if "domain_run_profiles" not in str(exc).lower():
            raise
        await session.rollback()
        return []
    return list(result.scalars().all())


async def save_domain_run_profile(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    profile: object,
    source_run_id: int,
    commit: bool = False,
) -> dict[str, object]:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    existing = await load_domain_run_profile(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    saved_at = datetime.now(UTC).isoformat()
    normalized_profile = normalize_domain_run_profile(
        profile,
        source_run_id=source_run_id,
        saved_at=saved_at,
    )
    if existing is None:
        existing = DomainRunProfile(
            domain=normalized_domain,
            surface=normalized_surface,
            profile=normalized_profile,
        )
        session.add(existing)
    else:
        existing.profile = normalized_profile
    if commit:
        await session.commit()
        await session.refresh(existing)
    else:
        await session.flush()
    return dict(existing.profile or {})
