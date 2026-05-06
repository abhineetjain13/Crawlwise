from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TypedDict, Unpack

from app.services.acquisition_plan import AcquisitionPlan
from app.services.config.runtime_settings import VALID_FETCH_MODES


class AcquisitionPolicyUpdates(TypedDict, total=False):
    fetch_mode: str
    prefer_browser: bool
    retry_reason: str | None
    proxy_profile: dict[str, object]
    locality_profile: dict[str, object]
    capture_page_markdown: bool
    capture_screenshot: bool
    prefer_curl_handoff: bool
    handoff_cookie_engine: str | None
    forced_browser_engine: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    fetch_mode: str = "auto"
    prefer_browser: bool = False
    retry_reason: str | None = None
    proxy_profile: Mapping[str, object] = field(default_factory=dict)
    locality_profile: Mapping[str, object] = field(default_factory=dict)
    capture_page_markdown: bool = False
    capture_screenshot: bool = False
    prefer_curl_handoff: bool = False
    handoff_cookie_engine: str | None = None
    forced_browser_engine: str | None = None

    @classmethod
    def from_profile(
        cls, profile: Mapping[str, object] | object | None
    ) -> "AcquisitionPolicy":
        payload = _coerce_profile(profile)
        prefer_browser = bool(payload.get("prefer_browser"))
        return cls(
            fetch_mode=_normalize_fetch_mode(
                payload.get("fetch_mode"),
                prefer_browser=prefer_browser,
            ),
            prefer_browser=prefer_browser,
            retry_reason=_normalized_retry_reason(payload.get("retry_reason")),
            proxy_profile=_mapping_value(
                payload.get("proxy_profile"),
                field_name="proxy_profile",
            ),
            locality_profile=_mapping_value(
                payload.get("locality_profile"),
                field_name="locality_profile",
            ),
            capture_page_markdown=bool(payload.get("capture_page_markdown", False)),
            capture_screenshot=bool(payload.get("capture_screenshot", False)),
            prefer_curl_handoff=bool(payload.get("prefer_curl_handoff", False)),
            handoff_cookie_engine=_optional_text(payload.get("handoff_cookie_engine")),
            forced_browser_engine=_optional_text(payload.get("forced_browser_engine")),
        )

    def with_updates(
        self, **updates: Unpack[AcquisitionPolicyUpdates]
    ) -> "AcquisitionPolicy":
        if not updates:
            return self
        # Keep the profile round-trip so updates still use from_profile validation.
        profile = self.to_profile()
        profile.update(updates)
        return type(self).from_profile(profile)

    def with_platform_requirements(
        self,
        *,
        requires_browser: bool,
    ) -> "AcquisitionPolicy":
        if not requires_browser:
            return self
        return replace(self, prefer_browser=True)

    @property
    def browser_reason(self) -> str | None:
        if self.retry_reason == "empty_extraction":
            return "empty-extraction retry"
        if self.retry_reason == "thin_listing":
            return "thin-listing retry"
        return None

    @property
    def listing_recovery_mode(self) -> str | None:
        if self.retry_reason == "thin_listing":
            return self.retry_reason
        return None

    def to_profile(self) -> dict[str, object]:
        profile: dict[str, object] = {
            "fetch_mode": self.fetch_mode,
            "prefer_browser": self.prefer_browser,
        }
        if self.retry_reason:
            profile["retry_reason"] = self.retry_reason
        if self.proxy_profile:
            profile["proxy_profile"] = dict(self.proxy_profile)
        if self.locality_profile:
            profile["locality_profile"] = dict(self.locality_profile)
        if self.capture_page_markdown:
            profile["capture_page_markdown"] = True
        if self.capture_screenshot:
            profile["capture_screenshot"] = True
        if self.prefer_curl_handoff:
            profile["prefer_curl_handoff"] = True
        if self.handoff_cookie_engine:
            profile["handoff_cookie_engine"] = self.handoff_cookie_engine
        if self.forced_browser_engine:
            profile["forced_browser_engine"] = self.forced_browser_engine
        return profile

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proxy_profile",
            MappingProxyType(dict(self.proxy_profile)),
        )
        object.__setattr__(
            self,
            "locality_profile",
            MappingProxyType(dict(self.locality_profile)),
        )


def _coerce_profile(value: Mapping[str, object] | object | None) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _mapping_value(value: object, *, field_name: str) -> dict[str, object]:
    if value in (None, ""):
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise ValueError(f"{field_name} must be a mapping")


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_fetch_mode(value: object, *, prefer_browser: bool) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        if prefer_browser:
            return "browser_only"
        return "auto"
    if normalized in VALID_FETCH_MODES:
        return normalized
    raise ValueError(f"fetch_mode must be one of {sorted(VALID_FETCH_MODES)}")


def _normalized_retry_reason(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized or None


__all__ = ["AcquisitionPlan", "AcquisitionPolicy"]
