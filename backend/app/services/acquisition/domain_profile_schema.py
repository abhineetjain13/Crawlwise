from __future__ import annotations

# TODO(phase-3): wire as canonical domain profile type in acquisition/domain_memory.py.

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.config.domain_profiles import (
    ACQUISITION_CONTRACT_MAX_FAILURES,
    AUTO_TRAVERSAL,
    DOMAIN_PROFILE_SCHEMA_VERSION,
    FALLBACK_SURFACE,
    SELECTOR_RULE_STALE_AFTER_DAYS,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AcquisitionContract",
    "DomainProfileV2",
    "FetchProfile",
    "SelectorRule",
    "domain_profile_v2_from_legacy",
    "parse_domain_profile_v2",
]


class FetchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fetch_mode: Literal["auto", "http_only", "browser_only", "http_then_browser"] = (
        "auto"
    )
    extraction_source: Literal[
        "raw_html",
        "rendered_dom",
        "rendered_dom_visual",
        "network_payload_first",
    ] = "raw_html"
    js_mode: Literal["auto", "enabled", "disabled"] = "auto"
    include_iframes: bool = False
    traversal_mode: Literal["scroll", "load_more", "view_all", "paginate"] | None = None
    request_delay_ms: int = Field(default=0, ge=0)
    max_pages: int = Field(default=1, ge=1)
    max_scrolls: int = Field(default=1, ge=1)
    host_memory_ttl_seconds: int | None = Field(default=None, ge=0)

class SelectorRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    source: str = "domain_profile"
    hit_count: int = Field(default=0, ge=0)
    miss_count: int = Field(default=0, ge=0)
    last_hit_at: datetime | None = None
    last_miss_at: datetime | None = None
    stale_after_days: int = Field(default=SELECTOR_RULE_STALE_AFTER_DAYS, ge=1)
    stale: bool = False

    @field_validator("field_name", "selector", "source")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class AcquisitionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_browser_engine: Literal["auto", "patchright", "real_chrome"] = "auto"
    prefer_browser: bool = False
    handoff_eligible: bool = False
    handoff_cookie_engine: Literal["auto", "patchright", "real_chrome"] = "auto"
    required_rendering: bool = False
    required_traversal: bool = False
    required_network_payloads: bool = False
    failure_count: int = Field(default=0, ge=0)
    max_failures: int = Field(default=ACQUISITION_CONTRACT_MAX_FAILURES, ge=1)
    stale: bool = False
    last_quality_success: dict[str, Any] | None = None


class DomainProfileV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[DOMAIN_PROFILE_SCHEMA_VERSION] = DOMAIN_PROFILE_SCHEMA_VERSION
    domain: str = ""
    surface: str = FALLBACK_SURFACE
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    profile_stale_after_days: int = Field(default=SELECTOR_RULE_STALE_AFTER_DAYS, ge=1)
    selector_rules: list[SelectorRule] = Field(default_factory=list)
    fetch_profile: FetchProfile = Field(default_factory=FetchProfile)
    acquisition_contract: AcquisitionContract = Field(default_factory=AcquisitionContract)

    @field_validator("domain", "surface")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()


def parse_domain_profile_v2(value: object) -> DomainProfileV2:
    if isinstance(value, DomainProfileV2):
        return value
    if not isinstance(value, dict):
        return DomainProfileV2()
    if value.get("schema_version") == DOMAIN_PROFILE_SCHEMA_VERSION:
        return DomainProfileV2.model_validate(value)
    return domain_profile_v2_from_legacy(value)


def domain_profile_v2_from_legacy(
    profile: object,
    *,
    domain: str = "",
    surface: str = FALLBACK_SURFACE,
) -> DomainProfileV2:
    payload = dict(profile or {}) if isinstance(profile, dict) else {}
    contract = _legacy_acquisition_contract(payload.get("acquisition_contract"))
    return DomainProfileV2(
        domain=str(payload.get("domain") or domain or "").strip(),
        surface=str(payload.get("surface") or surface or FALLBACK_SURFACE).strip(),
        created_at=_datetime_or_now(payload.get("saved_at")),
        updated_at=_datetime_or_now(payload.get("updated_at") or payload.get("saved_at")),
        fetch_profile=_legacy_fetch_profile(payload.get("fetch_profile")),
        selector_rules=_legacy_selector_rules(payload.get("selector_rules")),
        acquisition_contract=contract,
    )


def _datetime_or_now(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return _utc_now()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _utc_now()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _legacy_fetch_profile(value: object) -> FetchProfile:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    allowed = set(FetchProfile.model_fields)
    filtered = {key: item for key, item in payload.items() if key in allowed}
    normalized = str(filtered.get("traversal_mode") or "").strip().lower()
    if normalized == AUTO_TRAVERSAL:
        filtered["traversal_mode"] = None
    return FetchProfile.model_validate(filtered)


def _legacy_selector_rules(value: object) -> list[SelectorRule]:
    rows = value if isinstance(value, list) else []
    rules: list[SelectorRule] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = {
            "field_name": row.get("field_name") or row.get("field") or "",
            "selector": row.get("selector") or row.get("css_selector") or "",
            "source": row.get("source") or "domain_profile",
            "hit_count": row.get("hit_count", row.get("hits", 0)),
            "miss_count": row.get("miss_count", row.get("misses", 0)),
            "last_hit_at": row.get("last_hit_at"),
            "last_miss_at": row.get("last_miss_at"),
            "stale_after_days": row.get(
                "stale_after_days",
                SELECTOR_RULE_STALE_AFTER_DAYS,
            ),
            "stale": row.get("stale", False),
        }
        try:
            rules.append(SelectorRule.model_validate(candidate))
        except ValueError:
            continue
    return rules


def _legacy_acquisition_contract(value: object) -> AcquisitionContract:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    stale_payload = (
        dict(payload.get("stale_after_failures") or {})
        if isinstance(payload.get("stale_after_failures"), dict)
        else {}
    )
    return AcquisitionContract(
        preferred_browser_engine=payload.get("preferred_browser_engine") or "auto",
        prefer_browser=bool(payload.get("prefer_browser", False)),
        handoff_eligible=bool(
            payload.get("handoff_eligible", payload.get("prefer_curl_handoff", False))
        ),
        handoff_cookie_engine=payload.get("handoff_cookie_engine") or "auto",
        required_rendering=bool(payload.get("required_rendering", False)),
        required_traversal=bool(payload.get("required_traversal", False)),
        required_network_payloads=bool(payload.get("required_network_payloads", False)),
        failure_count=stale_payload.get("failure_count", payload.get("failure_count", 0)),
        stale=bool(stale_payload.get("stale", payload.get("stale", False))),
        last_quality_success=payload.get("last_quality_success")
        if isinstance(payload.get("last_quality_success"), dict)
        else None,
    )
