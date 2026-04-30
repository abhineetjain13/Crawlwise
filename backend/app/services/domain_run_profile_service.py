from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import DomainRunProfile
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.models.crawl_settings import _coerce_int as _coerce_int_clamped

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
_BROWSER_ENGINE_VALUES = {"auto", "patchright", "real_chrome"}


def _empty_acquisition_contract() -> dict[str, object]:
    return {
        "preferred_browser_engine": "auto",
        "prefer_browser": False,
        "prefer_curl_handoff": False,
        "handoff_cookie_engine": "auto",
        "last_quality_success": None,
        "stale_after_failures": {
            "failure_count": 0,
            "stale": False,
        },
    }


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


def normalize_acquisition_contract(value: object) -> dict[str, object]:
    payload = dict(value or {}) if isinstance(value, Mapping) else {}
    last_quality_success = payload.get("last_quality_success")
    if isinstance(last_quality_success, Mapping):
        normalized_success: dict[str, object] | None = {
            "method": _clean_str(last_quality_success.get("method")),
            "browser_engine": _coerce_optional_choice(
                last_quality_success.get("browser_engine"),
                _BROWSER_ENGINE_VALUES,
            ),
            "record_count": _coerce_int_clamped(
                last_quality_success.get("record_count"),
                default=0,
                minimum=0,
            ),
            "field_coverage": dict(last_quality_success.get("field_coverage") or {})
            if isinstance(last_quality_success.get("field_coverage"), Mapping)
            else {},
            "source_run_id": _coerce_int_clamped(
                last_quality_success.get("source_run_id"),
                default=0,
                minimum=0,
            )
            or None,
            "timestamp": _clean_str(last_quality_success.get("timestamp")),
        }
    else:
        normalized_success = None
    stale_payload = (
        dict(payload.get("stale_after_failures") or {})
        if isinstance(payload.get("stale_after_failures"), Mapping)
        else {}
    )
    return {
        "preferred_browser_engine": _coerce_choice(
            payload.get("preferred_browser_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "prefer_browser": bool(payload.get("prefer_browser", False)),
        "prefer_curl_handoff": bool(payload.get("prefer_curl_handoff", False)),
        "handoff_cookie_engine": _coerce_choice(
            payload.get("handoff_cookie_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "last_quality_success": normalized_success,
        "stale_after_failures": {
            "failure_count": _coerce_int_clamped(
                stale_payload.get("failure_count"),
                default=0,
                minimum=0,
            ),
            "stale": bool(stale_payload.get("stale", False)),
        },
    }


def normalize_domain_run_profile(
    profile: object,
    *,
    source_run_id: int,
    saved_at: str | None = None,
) -> dict[str, object]:
    payload = dict(profile or {}) if isinstance(profile, Mapping) else {}
    fetch_profile = dict(payload.get("fetch_profile") or {})
    locality_profile = dict(payload.get("locality_profile") or {})
    diagnostics_profile = dict(payload.get("diagnostics_profile") or {})
    normalized_saved_at = saved_at or datetime.now(UTC).isoformat()
    normalized_source_run_id = _coerce_int_clamped(
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
            "request_delay_ms": _coerce_int_clamped(
                fetch_profile.get("request_delay_ms"),
                default=crawler_runtime_settings.min_request_delay_ms,
                minimum=crawler_runtime_settings.min_request_delay_ms,
            ),
            "max_pages": _coerce_int_clamped(
                fetch_profile.get("max_pages"),
                default=crawler_runtime_settings.default_max_pages,
                minimum=crawler_runtime_settings.min_max_pages,
                maximum=crawler_runtime_settings.max_max_pages,
            ),
            "max_scrolls": _coerce_int_clamped(
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
        "acquisition_contract": normalize_acquisition_contract(
            payload.get("acquisition_contract")
        ),
        "source_run_id": normalized_source_run_id,
        "saved_at": normalized_saved_at,
    }


def acquisition_contract_is_stale(profile: object) -> bool:
    payload = dict(profile or {}) if isinstance(profile, Mapping) else {}
    contract = normalize_acquisition_contract(payload.get("acquisition_contract"))
    stale_value = contract.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    return bool(stale.get("stale"))


def apply_acquisition_contract_to_profile(
    acquisition_profile: object,
    contract: object,
) -> dict[str, object]:
    profile = dict(acquisition_profile or {}) if isinstance(acquisition_profile, Mapping) else {}
    normalized = normalize_acquisition_contract(contract)
    stale_value = normalized.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    if bool(stale.get("stale")):
        profile["acquisition_contract_stale"] = True
        return profile
    engine = str(normalized.get("preferred_browser_engine") or "auto").strip().lower()
    cookie_engine = str(normalized.get("handoff_cookie_engine") or "auto").strip().lower()
    if bool(normalized.get("prefer_browser")):
        profile["prefer_browser"] = True
        profile.setdefault("browser_reason", "acquisition-contract")
    if engine in {"patchright", "real_chrome"} and not profile.get("forced_browser_engine"):
        profile["forced_browser_engine"] = engine
    if bool(normalized.get("prefer_curl_handoff")):
        profile["prefer_curl_handoff"] = True
    if cookie_engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = cookie_engine
    elif engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = engine
    return profile


def build_success_acquisition_contract(
    *,
    method: object,
    browser_engine: object,
    record_count: int,
    requested_fields: list[str],
    found_fields: list[str],
    source_run_id: int,
    timestamp: str | None = None,
) -> dict[str, object]:
    normalized_method = str(method or "").strip().lower()
    normalized_engine = _coerce_optional_choice(browser_engine, _BROWSER_ENGINE_VALUES)
    preferred_engine = normalized_engine if normalized_engine in {"patchright", "real_chrome"} else "auto"
    handoff_engine = preferred_engine if preferred_engine != "auto" else "auto"
    requested_set = set(requested_fields or [])
    covered_fields = [field for field in list(found_fields or []) if field in requested_set]
    return normalize_acquisition_contract(
        {
            "preferred_browser_engine": preferred_engine,
            "prefer_browser": normalized_method == "browser",
            "prefer_curl_handoff": normalized_method == "browser" and handoff_engine != "auto",
            "handoff_cookie_engine": handoff_engine,
            "last_quality_success": {
                "method": normalized_method or None,
                "browser_engine": normalized_engine,
                "record_count": int(record_count or 0),
                "field_coverage": {
                    "requested": list(requested_fields or []),
                    "found": covered_fields,
                    "missing": [
                        field
                        for field in list(requested_fields or [])
                        if field not in set(covered_fields)
                    ],
                },
                "source_run_id": int(source_run_id or 0),
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
            },
            "stale_after_failures": {"failure_count": 0, "stale": False},
        }
    )


async def save_learned_acquisition_contract(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    contract: dict[str, object],
) -> dict[str, object]:
    existing = await load_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
    )
    base_profile = dict(existing.profile or {}) if existing is not None else {}
    if not base_profile:
        base_profile = normalize_domain_run_profile(
            {},
            source_run_id=source_run_id,
        )
    base_profile["acquisition_contract"] = normalize_acquisition_contract(contract)
    return await save_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
        profile=base_profile,
        source_run_id=source_run_id,
        existing_record=existing,
    )


async def note_acquisition_contract_failure(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    threshold: int,
) -> dict[str, object] | None:
    existing = await load_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
    )
    if existing is None:
        return None
    profile = dict(existing.profile or {})
    contract = normalize_acquisition_contract(profile.get("acquisition_contract"))
    if contract.get("last_quality_success") is None:
        return profile
    stale_value = contract.get("stale_after_failures")
    stale_payload = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    failure_count = int(stale_payload.get("failure_count") or 0) + 1
    contract["stale_after_failures"] = {
        "failure_count": failure_count,
        "stale": failure_count >= max(1, int(threshold or 1)),
    }
    profile["acquisition_contract"] = contract
    return await save_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
        profile=profile,
        source_run_id=int(profile.get("source_run_id") or 0) or 1,
        existing_record=existing,
    )


async def apply_saved_acquisition_contract_for_url(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
    settings_view,
    acquisition_profile: dict[str, object],
) -> dict[str, object]:
    explicit_contract = settings_view.acquisition_contract()
    if (
        explicit_contract.get("last_quality_success")
        or explicit_contract.get("prefer_browser")
        or explicit_contract.get("prefer_curl_handoff")
        or str(explicit_contract.get("preferred_browser_engine") or "auto") != "auto"
    ):
        return apply_acquisition_contract_to_profile(
            acquisition_profile,
            explicit_contract,
        )
    saved_profile = await load_domain_run_profile(
        session,
        domain=normalize_domain(url),
        surface=surface,
    )
    if saved_profile is None:
        return acquisition_profile
    saved_contract = dict(saved_profile.profile or {}).get("acquisition_contract")
    if not isinstance(saved_contract, dict):
        return acquisition_profile
    return apply_acquisition_contract_to_profile(
        acquisition_profile,
        saved_contract,
    )


async def record_acquisition_contract_outcome(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    method: object,
    browser_engine: object,
    requested_fields: list[str],
    records: list[dict[str, object]],
    persisted_count: int,
    quality_success: bool,
    count_failure: bool = True,
    stale_threshold: int,
) -> None:
    if quality_success:
        found_fields = sorted(
            {
                str(field_name)
                for record in records
                if isinstance(record, dict)
                for field_name, value in record.items()
                if not str(field_name).startswith("_") and value not in (None, "", [], {})
            }
        )
        await save_learned_acquisition_contract(
            session,
            domain=domain,
            surface=surface,
            source_run_id=source_run_id,
            contract=build_success_acquisition_contract(
                method=method,
                browser_engine=browser_engine,
                record_count=persisted_count,
                requested_fields=requested_fields,
                found_fields=found_fields,
                source_run_id=source_run_id,
            ),
        )
        return
    if not count_failure:
        return
    await note_acquisition_contract_failure(
        session,
        domain=domain,
        surface=surface,
        threshold=stale_threshold,
    )


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
    existing_record: DomainRunProfile | None = None,
) -> dict[str, object]:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    existing = existing_record
    if existing is None:
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
