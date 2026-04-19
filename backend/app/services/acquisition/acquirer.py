from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.services.crawl_engine import fetch_page, is_blocked_html
from app.services.exceptions import ProxyPoolExhaustedError
from app.services.platform_policy import detect_platform_family, resolve_platform_runtime_policy
from app.services.platform_url_normalizers import normalize_adp_detail_url


@dataclass(slots=True)
class AcquisitionRequest:
    run_id: int
    url: str
    surface: str
    proxy_list: list[str] = field(default_factory=list)
    traversal_mode: str | None = None
    max_pages: int = 1
    max_scrolls: int = 1
    sleep_ms: int = 0
    requested_fields: list[str] = field(default_factory=list)
    requested_field_selectors: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    acquisition_profile: dict[str, object] = field(default_factory=dict)
    checkpoint: Any = None

    def with_profile_updates(self, **updates: object) -> "AcquisitionRequest":
        profile = dict(self.acquisition_profile)
        profile.update(updates)
        return replace(self, acquisition_profile=profile)


@dataclass(slots=True)
class AcquisitionResult:
    request: AcquisitionRequest
    final_url: str
    html: str
    method: str
    status_code: int
    content_type: str = "text/html"
    blocked: bool = False
    json_data: dict[str, object] | list[object] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    adapter_records: list[dict[str, object]] = field(default_factory=list)
    adapter_name: str | None = None
    adapter_source_type: str | None = None
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    page_markdown: str = ""


class ProxyPoolExhausted(ProxyPoolExhaustedError):
    pass


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    requested_url = str(request.url or "")
    effective_url = requested_url
    if detect_platform_family(requested_url) == "adp":
        normalized_adp_url = normalize_adp_detail_url(requested_url)
        effective_url = normalized_adp_url or requested_url
    runtime_policy = resolve_platform_runtime_policy(effective_url)
    prefer_browser = bool(request.acquisition_profile.get("prefer_browser")) or bool(
        runtime_policy.get("requires_browser")
    )
    try:
        result = await fetch_page(
            effective_url,
            proxy_list=request.proxy_list,
            prefer_browser=prefer_browser,
            surface=request.surface,
            traversal_mode=request.traversal_mode,
            max_pages=request.max_pages,
            max_scrolls=request.max_scrolls,
            sleep_ms=request.sleep_ms,
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
        headers=_headers_to_dict(result.headers),
        network_payloads=list(result.network_payloads or []),
        browser_diagnostics=dict(result.browser_diagnostics or {}),
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


def scrub_network_payloads_for_storage(
    payloads: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                key: value
                for key, value in payload.items()
                if key in {"url", "method", "status", "content_type"}
            }
        )
    return rows


def detect_blocked_page(html: str, status_code: int = 200) -> bool:
    return is_blocked_html(html, status_code)
