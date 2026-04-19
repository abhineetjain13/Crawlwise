from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from browserforge.fingerprints import FingerprintGenerator

from app.services.pipeline.pipeline_config import FingerprintConfig

_FINGERPRINT_GENERATOR = FingerprintGenerator(
    browser=FingerprintConfig.browser,
    os=FingerprintConfig.os,
    device=FingerprintConfig.device,
    locale=FingerprintConfig.locale,
)
_HEADER_DROP_KEYS = {
    "accept-encoding",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "user-agent",
}


@dataclass(frozen=True, slots=True)
class BrowserIdentity:
    user_agent: str
    viewport: dict[str, int]
    extra_http_headers: dict[str, str]
    locale: str
    device_scale_factor: float
    has_touch: bool
    is_mobile: bool


def create_browser_identity() -> BrowserIdentity:
    fingerprint = _FINGERPRINT_GENERATOR.generate()
    screen = fingerprint.screen
    navigator = fingerprint.navigator
    headers = {
        key: value
        for key, value in fingerprint.headers.items()
        if str(key).lower() not in _HEADER_DROP_KEYS
    }
    return BrowserIdentity(
        user_agent=navigator.userAgent,
        viewport={
            "width": max(1, int(screen.width or 0)),
            "height": max(1, int(screen.height or 0)),
        },
        extra_http_headers=headers,
        locale=str(navigator.language or "en-US"),
        device_scale_factor=max(1.0, float(screen.devicePixelRatio or 1.0)),
        has_touch=bool((navigator.maxTouchPoints or 0) > 0),
        is_mobile=bool(navigator.userAgentData.get("mobile"))
        if isinstance(navigator.userAgentData, dict)
        else False,
    )


def build_playwright_context_options(
    identity: BrowserIdentity | None = None,
) -> dict[str, Any]:
    identity = identity or create_browser_identity()
    return {
        "user_agent": identity.user_agent,
        "viewport": dict(identity.viewport),
        "extra_http_headers": dict(identity.extra_http_headers),
        "locale": identity.locale,
        "device_scale_factor": identity.device_scale_factor,
        "has_touch": identity.has_touch,
        "is_mobile": identity.is_mobile,
        "service_workers": "block",
        "bypass_csp": False,
    }
