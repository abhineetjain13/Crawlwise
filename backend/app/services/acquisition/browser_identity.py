from __future__ import annotations

import logging as _logging
import platform as _platform
import re as _re
from dataclasses import dataclass
from typing import Any

from browserforge.fingerprints import FingerprintGenerator

from app.services.pipeline.pipeline_config import FingerprintConfig


def _host_os_fingerprint_arg() -> str:
    system = _platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    return "windows"


_HOST_OS = _host_os_fingerprint_arg()
_FINGERPRINT_GENERATOR = FingerprintGenerator(
    browser=FingerprintConfig.browser,
    os=[_HOST_OS],
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
_HOST_OS_UA_TOKENS = {
    "windows": "windows nt",
    "macos": "macintosh",
    "linux": "linux",
}
_logger = _logging.getLogger(__name__)


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
    fingerprint = _generate_coherent_fingerprint()
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


_UA_VERSION_RE = _re.compile(r"Chrome/(\d+)\.")


def _is_version_coherent(fingerprint) -> bool:
    """Reject fingerprints with Chrome major version mismatches.

    navigator.userAgent says Chrome/X, but userAgentData.brands says
    Chrome/Y — if |X - Y| > 2 or X < 120, the fingerprint is incoherent
    and will trigger bot-detection heuristics.
    """
    ua = str(fingerprint.navigator.userAgent or "")
    match = _UA_VERSION_RE.search(ua)
    if not match:
        return True  # can't validate, accept
    ua_major = int(match.group(1))
    if ua_major < 120:  # reject ancient versions
        return False
    brands = fingerprint.navigator.userAgentData
    if not isinstance(brands, dict):
        return True
    brand_list = brands.get("brands") or []
    for brand in brand_list:
        if isinstance(brand, dict) and "Chrome" in str(brand.get("brand") or ""):
            raw_version = str(brand.get("version") or "0").split(".")[0]
            try:
                brand_major = int(raw_version)
            except ValueError:
                continue
            if abs(brand_major - ua_major) > 2:
                return False
    return True


def _generate_coherent_fingerprint():
    expected_token = _HOST_OS_UA_TOKENS[_HOST_OS]
    for _ in range(3):
        fingerprint = _FINGERPRINT_GENERATOR.generate()
        ua = str(fingerprint.navigator.userAgent or "").lower()
        if expected_token in ua and _is_version_coherent(fingerprint):
            return fingerprint
    _logger.warning(
        "Failed to generate coherent fingerprint after 3 attempts, using last generated"
    )
    return fingerprint


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
