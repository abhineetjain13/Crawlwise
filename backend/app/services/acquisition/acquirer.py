from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.services.crawl_engine import fetch_page, is_blocked_html


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


class ProxyPoolExhausted(RuntimeError):
    pass


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    prefer_browser = bool(request.acquisition_profile.get("prefer_browser"))
    result = await fetch_page(request.url, prefer_browser=prefer_browser)
    return AcquisitionResult(
        request=request,
        final_url=result.final_url,
        html=result.html,
        method=result.method,
        status_code=result.status_code,
        content_type=result.content_type,
        blocked=result.blocked,
        headers=result.headers,
        network_payloads=list(result.network_payloads or []),
        browser_diagnostics=dict(result.browser_diagnostics or {}),
    )


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
