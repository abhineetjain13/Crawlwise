from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.services.acquisition_plan import AcquisitionPlan
from app.services.crawl_fetch_runtime import fetch_page
from app.services.exceptions import ProxyPoolExhaustedError
from app.services.platform_policy import resolve_platform_runtime_policy
from app.services.platform_url_normalizers import normalize_platform_acquisition_url


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


ProxyPoolExhausted = ProxyPoolExhaustedError


async def _emit_event(on_event: Any, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        return


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    requested_url = str(request.url or "")
    effective_url = normalize_platform_acquisition_url(requested_url) or requested_url
    runtime_policy = resolve_platform_runtime_policy(
        effective_url,
        surface=request.surface,
    )
    prefer_browser = bool(request.acquisition_profile.get("prefer_browser")) or bool(
        runtime_policy.get("requires_browser")
    )
    browser_reason = _resolve_browser_reason(
        request=request,
        requires_browser=bool(runtime_policy.get("requires_browser")),
    )
    try:
        await _emit_event(request.on_event, "info", f"Acquiring {effective_url}")
        result = await fetch_page(
            effective_url,
            run_id=request.run_id,
            proxy_list=request.proxy_list,
            prefer_browser=prefer_browser,
            surface=request.surface,
            traversal_mode=request.traversal_mode,
            max_pages=request.max_pages,
            max_scrolls=request.max_scrolls,
            browser_reason=browser_reason,
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
    )


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
    requires_browser: bool,
) -> str | None:
    retry_reason = str(request.acquisition_profile.get("retry_reason") or "").strip().lower()
    if retry_reason == "empty_extraction":
        return "empty-extraction retry"
    if requires_browser:
        return "platform-required"
    return None
