from __future__ import annotations

# TODO(phase-3): wire as canonical domain profile type in acquisition/domain_memory.py.

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.config.domain_profiles import (
    ACQUISITION_CONTRACT_MAX_FAILURES,
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
    payload = value if isinstance(value, dict) else {}
    return DomainProfileV2.model_validate(payload)
