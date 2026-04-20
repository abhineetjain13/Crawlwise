from __future__ import annotations

import logging as _logging
import platform as _platform
import re as _re
import threading as _threading
from dataclasses import dataclass
from types import SimpleNamespace as _SimpleNamespace
from typing import Any

from browserforge.fingerprints import FingerprintGenerator
from cachetools import TTLCache

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
MAX_BROWSER_IDENTITIES = 1024
BROWSER_IDENTITY_TTL_SECONDS = 60 * 60
# Bound per-run identities so stale run IDs age out and the cache cannot grow forever.
_RUN_BROWSER_IDENTITIES: TTLCache[int, BrowserIdentity] = TTLCache(
    maxsize=MAX_BROWSER_IDENTITIES,
    ttl=BROWSER_IDENTITY_TTL_SECONDS,
)
_RUN_BROWSER_IDENTITIES_LOCK = _threading.Lock()


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


def browser_identity_for_run(run_id: int | None = None) -> BrowserIdentity:
    if run_id is None:
        return create_browser_identity()
    normalized_run_id = int(run_id)
    identity = _RUN_BROWSER_IDENTITIES.get(normalized_run_id)
    if identity is not None:
        return identity
    with _RUN_BROWSER_IDENTITIES_LOCK:
        identity = _RUN_BROWSER_IDENTITIES.get(normalized_run_id)
        if identity is None:
            identity = create_browser_identity()
            _RUN_BROWSER_IDENTITIES[normalized_run_id] = identity
    return identity


def clear_browser_identity_cache() -> None:
    with _RUN_BROWSER_IDENTITIES_LOCK:
        _RUN_BROWSER_IDENTITIES.clear()


_UA_VERSION_RE = _re.compile(r"Chrome/(\d+)\.")
_MOBILE_UA_RE = _re.compile(r"\bmobile\b", _re.I)


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
        "Failed to generate coherent fingerprint after 3 attempts, repairing client hints from fallback fingerprint"
    )
    if fallback_fingerprint is None:
        raise RuntimeError("Fingerprint generator returned no candidates")
    return _repair_incoherent_client_hints(fallback_fingerprint)


def _repair_incoherent_client_hints(fingerprint):
    original_user_agent_data = getattr(fingerprint.navigator, "userAgentData", None)
    user_agent = str(getattr(fingerprint.navigator, "userAgent", "") or "").strip()
    original_mobile = (
        bool(original_user_agent_data.get("mobile"))
        if isinstance(original_user_agent_data, dict)
        else None
    )
    repaired_client_hints = _coherent_client_hints_from_user_agent(
        user_agent,
        mobile=original_mobile,
    )
    if repaired_client_hints is None:
        return _strip_incoherent_client_hints(fingerprint)
    headers = dict(getattr(fingerprint, "headers", {}) or {})
    for key in tuple(headers.keys()):
        if str(key).lower().startswith("sec-ch-ua"):
            headers.pop(key, None)
    headers.update(_coherent_sec_ch_headers(repaired_client_hints))

    navigator_payload = dict(vars(fingerprint.navigator))
    navigator_payload["userAgentData"] = repaired_client_hints
    navigator = _SimpleNamespace(**navigator_payload)
    return _SimpleNamespace(
        screen=fingerprint.screen,
        navigator=navigator,
        headers=headers,
    )


def _strip_incoherent_client_hints(fingerprint):
    original_user_agent_data = getattr(fingerprint.navigator, "userAgentData", None)
    user_agent_data = (
        dict(original_user_agent_data)
        if isinstance(original_user_agent_data, dict)
        else {}
    )
    for key in ("brands", "fullVersionList", "platform", "uaFullVersion"):
        user_agent_data.pop(key, None)

    headers = dict(getattr(fingerprint, "headers", {}) or {})
    for key in tuple(headers.keys()):
        if str(key).lower().startswith("sec-ch-ua"):
            headers.pop(key, None)

    navigator_payload = dict(vars(fingerprint.navigator))
    navigator_payload["userAgentData"] = user_agent_data
    navigator = _SimpleNamespace(**navigator_payload)
    return _SimpleNamespace(
        screen=fingerprint.screen,
        navigator=navigator,
        headers=headers,
    )


def _coherent_client_hints_from_user_agent(
    user_agent: str,
    *,
    mobile: bool | None,
) -> dict[str, object] | None:
    major_version = _chrome_major_version(user_agent)
    if major_version is None:
        return None
    resolved_mobile = bool(mobile) if mobile is not None else bool(_MOBILE_UA_RE.search(user_agent))
    full_version = f"{major_version}.0.0.0"
    return {
        "brands": [
            {"brand": "Not.A/Brand", "version": "24"},
            {"brand": "Chromium", "version": str(major_version)},
            {"brand": "Google Chrome", "version": str(major_version)},
        ],
        "fullVersionList": [
            {"brand": "Not.A/Brand", "version": "24.0.0.0"},
            {"brand": "Chromium", "version": full_version},
            {"brand": "Google Chrome", "version": full_version},
        ],
        "mobile": resolved_mobile,
        "platform": _HOST_OS_PLATFORM_LABELS[_HOST_OS],
        "uaFullVersion": full_version,
    }


def _coherent_sec_ch_headers(user_agent_data: dict[str, object]) -> dict[str, str]:
    brands = user_agent_data.get("brands") or []
    sec_ch_ua = ", ".join(
        f'"{str(item.get("brand") or "").replace("\"", "")}";v="{str(item.get("version") or "").replace("\"", "")}"'
        for item in brands
        if isinstance(item, dict) and item.get("brand") and item.get("version")
    )
    if not sec_ch_ua:
        return {}
    return {
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?1" if bool(user_agent_data.get("mobile")) else "?0",
        "sec-ch-ua-platform": f'"{user_agent_data.get("platform") or _HOST_OS_PLATFORM_LABELS[_HOST_OS]}"',
    }


def _chrome_major_version(user_agent: str) -> int | None:
    match = _UA_VERSION_RE.search(str(user_agent or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def build_playwright_context_options(
    identity: BrowserIdentity | None = None,
    *,
    run_id: int | None = None,
) -> dict[str, Any]:
    identity = identity or browser_identity_for_run(run_id)
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
