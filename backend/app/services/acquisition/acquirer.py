from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from pydantic import BaseModel

from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.registry import normalize_adapter_acquisition_url
from app.services.crawl_fetch_runtime import fetch_page
from app.services.exceptions import ProxyPoolExhaustedError
from app.services.platform_policy import resolve_platform_runtime_policy


@dataclass(slots=True)
class AcquisitionRequest:
    run_id: int
    url: str
    plan: AcquisitionPlan
    requested_fields: list[str] = field(default_factory=list)
    requested_field_selectors: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    acquisition_profile: dict[str, object] = field(default_factory=dict)
    checkpoint: Any = None
    on_event: Any = None

    def with_profile_updates(self, **updates: object) -> "AcquisitionRequest":
        profile = dict(self.acquisition_profile)
        profile.update(updates)
        return replace(self, acquisition_profile=profile)

    @property
    def surface(self) -> str:
        return self.plan.surface

    @property
    def proxy_list(self) -> list[str]:
        return list(self.plan.proxy_list)

    @property
    def traversal_mode(self) -> str | None:
        return self.plan.traversal_mode

    @property
    def max_pages(self) -> int:
        return self.plan.max_pages

    @property
    def max_scrolls(self) -> int:
        return self.plan.max_scrolls

    @property
    def max_records(self) -> int:
        return self.plan.max_records

@dataclass(slots=True)
class AcquisitionResult:
    request: AcquisitionRequest
    final_url: str
    html: str
    method: str
    status_code: int
    content_type: str = "text/html"
    blocked: bool = False
    platform_family: str | None = None
    json_data: dict[str, object] | list[object] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    adapter_records: list[dict[str, object]] = field(default_factory=list)
    adapter_name: str | None = None
    adapter_source_type: str | None = None
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)
    page_markdown: str = ""


@dataclass(frozen=True, slots=True)
class PageEvidence:
    blocked: bool
    method: str
    diagnostics: dict[str, object]

    @classmethod
    def from_acquisition_result(cls, acquisition_result) -> "PageEvidence":
        diagnostics = getattr(acquisition_result, "browser_diagnostics", {})
        return cls(
            blocked=bool(getattr(acquisition_result, "blocked", False)),
            method=str(getattr(acquisition_result, "method", "") or ""),
            diagnostics=dict(diagnostics or {}) if isinstance(diagnostics, dict) else {},
        )

    @classmethod
    def from_browser_diagnostics(cls, diagnostics: dict[str, object] | object) -> "PageEvidence":
        payload = dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}
        return cls(blocked=False, method="", diagnostics=payload)

    @property
    def browser_attempted(self) -> bool:
        return bool(self.diagnostics.get("browser_attempted")) or self.method == "browser"

    @property
    def browser_outcome(self) -> str:
        return str(self.diagnostics.get("browser_outcome") or "").strip().lower()

    @property
    def browser_reason(self) -> str:
        return str(self.diagnostics.get("browser_reason") or "").strip().lower()

    @property
    def challenge_evidence(self) -> list[str]:
        return [
            str(item or "").strip().lower()
            for item in _list_or_empty(self.diagnostics.get("challenge_evidence"))
            if str(item or "").strip()
        ]

    @property
    def has_ready_readiness_probe(self) -> bool:
        return any(
            isinstance(probe, dict) and bool(probe.get("is_ready"))
            for probe in _list_or_empty(self.diagnostics.get("readiness_probes"))
        )

    @property
    def indicates_block(self) -> bool:
        if self.blocked or self.browser_outcome == "challenge_page":
            return True
        if any(
            item.startswith(("title:", "strong:"))
            for item in self.challenge_evidence
        ):
            return True
        if self.browser_outcome == "usable_content" and self.has_ready_readiness_probe:
            return False
        # INVARIANTS.md Rule 6: usable content beats provider noise.
        if self.browser_outcome == "usable_content":
            return False
        provider_evidence = _list_or_empty(
            self.diagnostics.get("challenge_provider_hits")
        ) or [
            item
            for item in self.challenge_evidence
            if item.startswith(("provider:", "active_provider:"))
        ]
        return bool(provider_evidence and self.browser_outcome != "usable_content")

    @property
    def challenge_shell_reason(self) -> str | None:
        challenge_shell = (
            self.browser_outcome in {"challenge_page", "low_content_shell"}
            or self.indicates_block
            or (
                self.browser_reason.startswith("vendor-block:")
                and not self.has_ready_readiness_probe
            )
        )
        return "challenge_shell" if challenge_shell else None


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


ProxyPoolExhausted = ProxyPoolExhaustedError


async def _emit_event(on_event: Any, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        return


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    acquisition_profile = _coerce_acquisition_profile(request.acquisition_profile)
    requested_url = str(request.url or "")
    effective_url = await normalize_adapter_acquisition_url(requested_url) or requested_url
    runtime_policy = resolve_platform_runtime_policy(
        effective_url,
        surface=request.surface,
    )
    fetch_mode = _resolve_fetch_mode(request, acquisition_profile=acquisition_profile)
    prefer_browser = bool(acquisition_profile.get("prefer_browser")) or bool(
        runtime_policy.get("requires_browser")
    )
    browser_reason = _resolve_browser_reason(
        request=request,
        acquisition_profile=acquisition_profile,
        requires_browser=bool(runtime_policy.get("requires_browser")),
    )
    try:
        raw_proxy_profile = acquisition_profile.get("proxy_profile")
        proxy_profile = (
            dict(raw_proxy_profile) if isinstance(raw_proxy_profile, Mapping) else None
        )
        raw_locality_profile = acquisition_profile.get("locality_profile")
        locality_profile = (
            dict(raw_locality_profile)
            if isinstance(raw_locality_profile, Mapping)
            else None
        )
        await _emit_event(request.on_event, "info", f"Acquiring {effective_url}")
        result = await fetch_page(
            effective_url,
            run_id=request.run_id,
            proxy_list=request.proxy_list,
            proxy_profile=proxy_profile,
            locality_profile=locality_profile,
            fetch_mode=fetch_mode,
            prefer_browser=prefer_browser,
            surface=request.surface,
            traversal_mode=request.traversal_mode,
            requested_fields=list(request.requested_fields),
            listing_recovery_mode=_resolve_listing_recovery_mode(
                request,
                acquisition_profile=acquisition_profile,
            ),
            max_pages=request.max_pages,
            max_scrolls=request.max_scrolls,
            max_records=request.max_records,
            browser_reason=browser_reason,
            capture_page_markdown=bool(
                acquisition_profile.get("capture_page_markdown", False)
            ),
            capture_screenshot=bool(
                acquisition_profile.get("capture_screenshot", False)
            ),
            forced_browser_engine=str(
                acquisition_profile.get("forced_browser_engine") or ""
            ).strip() or None,
            on_event=request.on_event,
        )
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        if not request.proxy_list:
            raise
        raise ProxyPoolExhausted("No usable proxies remained for acquisition") from exc
    return AcquisitionResult(
        request=request,
        final_url=result.final_url,
        html=result.html,
        method=result.method,
        status_code=result.status_code,
        content_type=result.content_type,
        blocked=result.blocked,
        platform_family=getattr(result, "platform_family", None),
        headers=_headers_to_dict(result.headers),
        network_payloads=list(getattr(result, "network_payloads", []) or []),
        browser_diagnostics=dict(getattr(result, "browser_diagnostics", {}) or {}),
        artifacts=dict(getattr(result, "artifacts", {}) or {}),
        page_markdown=str(getattr(result, "page_markdown", "") or ""),
    )


def _resolve_fetch_mode(
    request: AcquisitionRequest,
    *,
    acquisition_profile: Mapping[str, object] | None = None,
) -> str:
    profile = _coerce_acquisition_profile(
        acquisition_profile
        if acquisition_profile is not None
        else request.acquisition_profile
    )
    normalized = str(profile.get("fetch_mode") or "").strip().lower()
    if normalized in {"auto", "http_only", "browser_only", "http_then_browser"}:
        return normalized
    if bool(profile.get("prefer_browser")):
        return "browser_only"
    return "auto"


def _headers_to_dict(headers: Mapping[str, object] | Any) -> dict[str, str]:
    if isinstance(headers, httpx.Headers):
        return {str(key): str(value) for key, value in headers.items()}
    if isinstance(headers, Mapping):
        return {str(key): str(value) for key, value in headers.items()}
    return {
        str(key): str(value)
        for key, value in getattr(headers, "items", lambda: [])()
    }


def _resolve_browser_reason(
    *,
    request: AcquisitionRequest,
    acquisition_profile: Mapping[str, object] | None = None,
    requires_browser: bool,
) -> str | None:
    profile = _coerce_acquisition_profile(
        acquisition_profile
        if acquisition_profile is not None
        else request.acquisition_profile
    )
    retry_reason = _normalized_retry_reason(
        profile.get("retry_reason")
    )
    if retry_reason == "empty_extraction":
        return "empty-extraction retry"
    if retry_reason == "thin_listing":
        return "thin-listing retry"
    if requires_browser:
        return "platform-required"
    return None


def _resolve_listing_recovery_mode(
    request: AcquisitionRequest,
    *,
    acquisition_profile: Mapping[str, object] | None = None,
) -> str | None:
    profile = _coerce_acquisition_profile(
        acquisition_profile
        if acquisition_profile is not None
        else request.acquisition_profile
    )
    retry_reason = _normalized_retry_reason(
        profile.get("retry_reason")
    )
    if retry_reason == "thin_listing":
        return retry_reason
    return None


def _normalized_retry_reason(value: object) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized


def _coerce_acquisition_profile(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, BaseModel):
        payload = value.model_dump()
        return payload if isinstance(payload, dict) else {}
    return {}
