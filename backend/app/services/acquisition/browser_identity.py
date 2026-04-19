from __future__ import annotations

import logging as _logging
import platform as _platform
import re as _re
from dataclasses import dataclass
from types import SimpleNamespace as _SimpleNamespace
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
_HOST_OS_PLATFORM_LABELS = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
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
    user_agent_data = fingerprint.navigator.userAgentData
    if not isinstance(user_agent_data, dict):
        return True
    brand_list = user_agent_data.get("brands") or []
    chromium_brand_seen = False
    for brand in brand_list:
        if not isinstance(brand, dict):
            continue
        brand_name = str(brand.get("brand") or "").strip().lower()
        if brand_name not in {"chromium", "google chrome", "chrome"}:
            continue
        chromium_brand_seen = True
        raw_version = str(brand.get("version") or "0").split(".")[0]
        try:
            brand_major = int(raw_version)
        except ValueError:
            continue
        if abs(brand_major - ua_major) > 2:
            return False
    if chromium_brand_seen:
        return True
    ua_full_version = str(user_agent_data.get("uaFullVersion") or "").split(".")[0]
    if ua_full_version.isdigit():
        return abs(int(ua_full_version) - ua_major) <= 2
    return True


def _generate_coherent_fingerprint():
    expected_token = _HOST_OS_UA_TOKENS[_HOST_OS]
    fallback_fingerprint = None
    for _ in range(3):
        fingerprint = _FINGERPRINT_GENERATOR.generate()
        fallback_fingerprint = fingerprint
        ua = str(fingerprint.navigator.userAgent or "").lower()
        if expected_token in ua and _is_version_coherent(fingerprint):
            return fingerprint
    _logger.warning(
        "Failed to generate coherent fingerprint after 3 attempts, normalizing client hints"
    )
    if fallback_fingerprint is None:
        raise RuntimeError("Fingerprint generator returned no candidates")
    return _normalize_incoherent_fingerprint(fallback_fingerprint)


def _normalize_incoherent_fingerprint(fingerprint):
    user_agent = str(getattr(fingerprint.navigator, "userAgent", "") or "")
    match = _UA_VERSION_RE.search(user_agent)
    if not match:
        return fingerprint
    ua_major = int(match.group(1))
    original_user_agent_data = getattr(fingerprint.navigator, "userAgentData", None)
    user_agent_data = (
        dict(original_user_agent_data)
        if isinstance(original_user_agent_data, dict)
        else {}
    )
    user_agent_data["brands"] = [
        {"brand": "Not/A)Brand", "version": "99"},
        {"brand": "Chromium", "version": str(ua_major)},
        {"brand": "Google Chrome", "version": str(ua_major)},
    ]
    user_agent_data["fullVersionList"] = [
        {"brand": "Not/A)Brand", "version": "99.0.0.0"},
        {"brand": "Chromium", "version": f"{ua_major}.0.0.0"},
        {"brand": "Google Chrome", "version": f"{ua_major}.0.0.0"},
    ]
    user_agent_data["uaFullVersion"] = f"{ua_major}.0.0.0"
    user_agent_data.setdefault("mobile", False)
    user_agent_data["platform"] = _HOST_OS_PLATFORM_LABELS[_HOST_OS]

    headers = dict(getattr(fingerprint, "headers", {}) or {})
    headers["sec-ch-ua"] = (
        f'"Not/A)Brand";v="99", "Chromium";v="{ua_major}", "Google Chrome";v="{ua_major}"'
    )
    headers["sec-ch-ua-mobile"] = "?1" if bool(user_agent_data.get("mobile")) else "?0"
    headers["sec-ch-ua-platform"] = f'"{_HOST_OS_PLATFORM_LABELS[_HOST_OS]}"'

    navigator_payload = dict(vars(fingerprint.navigator))
    navigator_payload["userAgentData"] = user_agent_data
    navigator = _SimpleNamespace(**navigator_payload)
    return _SimpleNamespace(
        screen=fingerprint.screen,
        navigator=navigator,
        headers=headers,
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
