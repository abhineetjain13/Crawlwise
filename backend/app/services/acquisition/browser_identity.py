from __future__ import annotations

import logging as _logging
import copy as _copy
import ctypes as _ctypes
import hashlib as _hashlib
import json as _json
import os as _os
import platform as _platform
import re as _re
import threading as _threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace as _SimpleNamespace
from typing import Any

from browserforge.fingerprints import FingerprintGenerator
from cachetools import TTLCache
import pytz  # type: ignore[import-untyped]
from tzlocal import get_localzone_name as _get_localzone_name

from app.services.config.browser_fingerprint_profiles import (
    DEVICE_MEMORY_BUCKETS,
    HOST_OS_PLATFORM_LABELS,
    HOST_OS_UA_TOKENS,
    NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL,
    TIMEZONE_ALIASES,
    USER_AGENT_PLATFORM_LABELS,
)
from app.services.config.browser_init_scripts import (
    _CATCH_IGNORE_LINE,
    _CONFIGURABLE_TRUE_LINE,
    _DEFINE_PROPERTY_CLOSE_LINE,
    _ENUMERABLE_FALSE_LINE,
    _INIT_WRAPPER_END,
    _INIT_WRAPPER_START,
    _TRY_LINE,
    build_audio_fingerprint_init_script,
    build_canvas_fingerprint_init_script,
    build_chrome_runtime_init_script,
    build_font_surface_init_script,
    build_intl_coherence_init_script,
    build_navigator_coherence_init_script,
    build_permissions_coherence_init_script,
    build_performance_coherence_init_script,
    build_webgl_fingerprint_init_script,
)
from app.services.config.runtime_settings import (
    crawler_runtime_settings,
)
from app.services.network_resolution import _accept_language_for_locale

try:
    from browserforge.fingerprints import Fingerprint as _BrowserforgeFingerprintType
except Exception:  # pragma: no cover - optional dependency contract
    _BrowserforgeFingerprintType = None  # type: ignore[assignment,misc]
_BrowserforgeFingerprint: Any | None = _BrowserforgeFingerprintType

try:
    from browserforge.injectors.utils import InjectFunction as _BrowserforgeInjectFunctionType
except Exception:  # pragma: no cover - optional dependency contract
    _BrowserforgeInjectFunctionType = None  # type: ignore[assignment]
_BrowserforgeInjectFunction: Any | None = _BrowserforgeInjectFunctionType


def _host_os_fingerprint_arg() -> str:
    system = _platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    return "windows"


_HOST_OS = _host_os_fingerprint_arg()
_FINGERPRINT_GENERATOR: FingerprintGenerator | None = None
_FINGERPRINT_GENERATOR_CONFIG: tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
] | None = None
_FINGERPRINT_GENERATOR_LOCK = _threading.Lock()
_HEADER_DROP_KEYS = {
    "accept-encoding",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "user-agent",
}
_TIMEZONE_TO_COUNTRY = {
    timezone_name: country_code
    for country_code, timezone_names in pytz.country_timezones.items()
    for timezone_name in timezone_names
}
_logger = _logging.getLogger(__name__)
_CHROMIUM_BROWSER_ENGINE = "chromium"
_PATCHRIGHT_BROWSER_ENGINE = "patchright"
_REAL_CHROME_BROWSER_ENGINE = "real_chrome"
_SUPPORTED_BROWSER_ENGINES = {
    _CHROMIUM_BROWSER_ENGINE,
    _PATCHRIGHT_BROWSER_ENGINE,
    _REAL_CHROME_BROWSER_ENGINE,
}
# Bound per-run identities so stale run IDs age out and the cache cannot grow forever.
_RUN_BROWSER_IDENTITIES: TTLCache[int, BrowserIdentity] = TTLCache(
    maxsize=crawler_runtime_settings.browser_identity_cache_max_entries,
    ttl=crawler_runtime_settings.browser_identity_cache_ttl_seconds,
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
    raw_fingerprint: Any | None = None


@dataclass(frozen=True, slots=True)
class PlaywrightContextSpec:
    context_options: dict[str, Any]
    init_script: str | None = None


def _normalize_browser_engine_label(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _SUPPORTED_BROWSER_ENGINES:
        return normalized
    return _CHROMIUM_BROWSER_ENGINE


def _context_color_scheme() -> str | None:
    normalized = str(
        crawler_runtime_settings.fingerprint_color_scheme or ""
    ).strip().lower()
    if normalized in {"light", "dark", "no-preference"}:
        return normalized
    return None


def _should_use_legacy_init_script(browser_engine: str) -> bool:
    normalized_engine = _normalize_browser_engine_label(browser_engine)
    return normalized_engine != _PATCHRIGHT_BROWSER_ENGINE


def _viewport_from_screen(
    screen: Any,
    *,
    is_mobile: bool,
) -> dict[str, int]:
    screen_width = max(1, int(getattr(screen, "width", 0) or 0))
    screen_height = max(1, int(getattr(screen, "height", 0) or 0))
    avail_width = int(getattr(screen, "availWidth", 0) or 0)
    avail_height = int(getattr(screen, "availHeight", 0) or 0)
    viewport_width = (
        avail_width
        if 0 < avail_width <= screen_width
        else screen_width
    )
    viewport_height = (
        avail_height
        if 0 < avail_height < screen_height
        else (
            screen_height
            if is_mobile
            else max(
                1,
                screen_height
                - int(
                    crawler_runtime_settings.browser_desktop_viewport_reserved_height_px
                    or 0
                ),
            )
        )
    )
    return {
        "width": viewport_width,
        "height": viewport_height,
    }


def _positive_int(value: object) -> int | None:
    try:
        normalized = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _positive_float(value: object) -> float | None:
    try:
        normalized = (
            float(value) if isinstance(value, (int, float)) else float(str(value))
        )
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _host_total_memory_bytes() -> int | None:
    if _HOST_OS == "windows":
        try:
            class _MemoryStatusEx(_ctypes.Structure):
                _fields_ = [
                    ("dwLength", _ctypes.c_ulong),
                    ("dwMemoryLoad", _ctypes.c_ulong),
                    ("ullTotalPhys", _ctypes.c_ulonglong),
                    ("ullAvailPhys", _ctypes.c_ulonglong),
                    ("ullTotalPageFile", _ctypes.c_ulonglong),
                    ("ullAvailPageFile", _ctypes.c_ulonglong),
                    ("ullTotalVirtual", _ctypes.c_ulonglong),
                    ("ullAvailVirtual", _ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", _ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = _ctypes.sizeof(_MemoryStatusEx)
            if _ctypes.windll.kernel32.GlobalMemoryStatusEx(_ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None
        return None
    sysconf = getattr(_os, "sysconf", None)
    if not callable(sysconf):
        return None
    try:
        page_size = int(sysconf("SC_PAGE_SIZE"))
        page_count = int(sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError):
        return None
    total_bytes = page_size * page_count
    return total_bytes if total_bytes > 0 else None


def _bucket_device_memory_gb(value: object) -> float | None:
    normalized = _positive_float(value)
    if normalized is None:
        return None
    bucket = DEVICE_MEMORY_BUCKETS[0]
    for candidate in DEVICE_MEMORY_BUCKETS:
        if normalized >= candidate:
            bucket = candidate
        else:
            break
    return bucket


def _resolved_device_memory_gb(raw_value: object) -> float | None:
    configured = _bucket_device_memory_gb(
        crawler_runtime_settings.fingerprint_device_memory_gb
    )
    if configured is not None:
        return configured
    host_total_memory = _host_total_memory_bytes()
    if host_total_memory is not None:
        host_gb = host_total_memory / float(1024**3)
        bucketed = _bucket_device_memory_gb(host_gb)
        if bucketed is not None:
            return bucketed
    return _bucket_device_memory_gb(raw_value)


def _resolved_hardware_concurrency(raw_value: object) -> int | None:
    configured = _positive_int(
        crawler_runtime_settings.fingerprint_hardware_concurrency
    )
    if configured is not None:
        return configured
    host_cpu_count = _positive_int(_os.cpu_count())
    raw_cpu_count = _positive_int(raw_value)
    if host_cpu_count is not None and raw_cpu_count is not None:
        return min(raw_cpu_count, host_cpu_count)
    return host_cpu_count or raw_cpu_count


def _platform_label_from_user_agent(user_agent: object) -> str:
    lowered = str(user_agent or "").strip().lower()
    for token, label in USER_AGENT_PLATFORM_LABELS:
        if token in lowered:
            return label
    return HOST_OS_PLATFORM_LABELS[_HOST_OS]


def _navigator_platform_from_user_agent(
    user_agent: object,
    *,
    fallback: object = None,
) -> str:
    platform_label = _platform_label_from_user_agent(user_agent)
    fallback_value = str(fallback or "").strip()
    return NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL.get(platform_label) or fallback_value or "Win32"


def _platform_version_for_platform_label(platform_label: str) -> str:
    if platform_label == "Windows":
        return "15.0.0"
    if platform_label == "macOS":
        return "14.0.0"
    return "6.0.0"


def _ua_bitness_from_user_agent(user_agent: str) -> str:
    lowered = str(user_agent or "").lower()
    if "x86_64" in lowered or "win64" in lowered or "x64" in lowered or "amd64" in lowered:
        return "64"
    return "32"


def _safely_clone_fingerprint(raw_fingerprint: Any) -> Any:
    try:
        return _copy.deepcopy(raw_fingerprint)
    except Exception:
        try:
            cloned_fingerprint = _copy.copy(raw_fingerprint)
        except Exception:
            return None
        fallback_navigator = getattr(cloned_fingerprint, "navigator", None)
        if fallback_navigator is not None:
            try:
                setattr(cloned_fingerprint, "navigator", _copy.copy(fallback_navigator))
            except Exception:
                return None
        return cloned_fingerprint


def _align_raw_fingerprint_to_user_agent_platform(raw_fingerprint: Any | None) -> Any | None:
    if raw_fingerprint is None:
        return None
    aligned_fingerprint = _safely_clone_fingerprint(raw_fingerprint)
    if aligned_fingerprint is None:
        return raw_fingerprint
    navigator = getattr(aligned_fingerprint, "navigator", None)
    if navigator is None:
        return raw_fingerprint
    user_agent = str(getattr(navigator, "userAgent", "") or "")
    platform_label = _platform_label_from_user_agent(user_agent)
    navigator_platform = _navigator_platform_from_user_agent(
        user_agent,
        fallback=getattr(navigator, "platform", None),
    )
    setattr(navigator, "platform", navigator_platform)
    existing_user_agent_data = getattr(navigator, "userAgentData", None)
    if isinstance(existing_user_agent_data, dict):
        user_agent_data = dict(existing_user_agent_data)
        user_agent_data["platform"] = platform_label
        setattr(navigator, "userAgentData", user_agent_data)
    headers = _drop_sec_ch_headers(getattr(aligned_fingerprint, "headers", {}) or {})
    coherent_hints = _coherent_client_hints_from_user_agent(
        user_agent,
        mobile=(
            bool(existing_user_agent_data.get("mobile"))
            if isinstance(existing_user_agent_data, Mapping)
            else None
        ),
    )
    if coherent_hints:
        headers.update(_coherent_sec_ch_headers(coherent_hints))
    setattr(aligned_fingerprint, "headers", headers)
    return aligned_fingerprint


def _align_raw_fingerprint_to_runtime_hardware(raw_fingerprint: Any | None) -> Any | None:
    if raw_fingerprint is None:
        return None
    aligned_fingerprint = _safely_clone_fingerprint(raw_fingerprint)
    navigator = getattr(aligned_fingerprint, "navigator", None)
    if navigator is None:
        return raw_fingerprint
    hardware_concurrency = _resolved_hardware_concurrency(
        getattr(navigator, "hardwareConcurrency", None)
    )
    if hardware_concurrency is not None:
        setattr(navigator, "hardwareConcurrency", hardware_concurrency)
    device_memory_gb = _resolved_device_memory_gb(
        getattr(navigator, "deviceMemory", None)
    )
    if device_memory_gb is not None:
        setattr(navigator, "deviceMemory", device_memory_gb)
    return aligned_fingerprint


def _harmonize_fingerprint_screen_geometry(
    screen: Any,
    *,
    viewport: Mapping[str, int],
    is_mobile: bool,
) -> None:
    viewport_width = max(1, int(viewport.get("width", 0) or 0))
    viewport_height = max(1, int(viewport.get("height", 0) or 0))
    screen_width = max(
        viewport_width,
        int(getattr(screen, "width", 0) or 0),
    )
    screen_height = max(
        viewport_height,
        int(getattr(screen, "height", 0) or 0),
    )
    setattr(screen, "innerWidth", viewport_width)
    setattr(screen, "innerHeight", viewport_height)
    setattr(screen, "clientWidth", viewport_width)
    setattr(screen, "clientHeight", viewport_height)
    if is_mobile:
        return
    frame_width = max(
        1,
        int(crawler_runtime_settings.browser_desktop_window_frame_width_px or 1),
    )
    frame_height = max(
        1,
        int(crawler_runtime_settings.browser_desktop_window_frame_height_px or 1),
    )
    outer_width = max(
        viewport_width + frame_width,
        int(getattr(screen, "outerWidth", 0) or 0),
    )
    outer_width = min(screen_width, outer_width)
    outer_height = max(
        viewport_height + frame_height,
        int(getattr(screen, "outerHeight", 0) or 0),
    )
    if outer_height >= screen_height:
        outer_height = max(viewport_height + 1, screen_height - 1)
    else:
        outer_height = min(screen_height, outer_height)
    avail_width = min(
        screen_width,
        max(
            viewport_width,
            int(getattr(screen, "availWidth", 0) or 0),
        ),
    )
    avail_height = min(
        screen_height,
        max(
            viewport_height,
            int(getattr(screen, "availHeight", 0) or 0),
        ),
    )
    setattr(screen, "outerWidth", outer_width)
    setattr(screen, "outerHeight", outer_height)
    setattr(screen, "availWidth", avail_width)
    setattr(screen, "availHeight", avail_height)
    setattr(screen, "width", screen_width)
    setattr(screen, "height", screen_height)


def create_browser_identity() -> BrowserIdentity:
    fingerprint = _align_raw_fingerprint_to_user_agent_platform(
        _align_raw_fingerprint_to_runtime_hardware(
            _generate_coherent_fingerprint()
        )
    )
    if fingerprint is None:
        raise RuntimeError("Browser fingerprint generation returned no identity")
    screen = fingerprint.screen
    navigator = fingerprint.navigator
    headers = {
        key: value
        for key, value in fingerprint.headers.items()
        if str(key).lower() not in _HEADER_DROP_KEYS
    }
    user_agent = str(navigator.userAgent or "")
    user_agent_data = (
        dict(navigator.userAgentData)
        if isinstance(navigator.userAgentData, dict)
        else {}
    )
    if _should_replace_client_hint_headers(headers, user_agent=user_agent, user_agent_data=user_agent_data):
        headers.update(
            _coherent_sec_ch_headers(
                _coherent_client_hints_from_user_agent(
                    user_agent,
                    mobile=(
                        bool(user_agent_data.get("mobile"))
                        if isinstance(user_agent_data, dict)
                        else None
                    ),
                )
                or {}
            )
        )
    locale = str(navigator.language or "en-US")
    if not _accept_language_matches_locale(headers.get("Accept-Language"), locale=locale):
        headers["Accept-Language"] = _accept_language_for_locale(locale)
    is_mobile = (
        bool(navigator.userAgentData.get("mobile"))
        if isinstance(navigator.userAgentData, dict)
        else False
    )
    has_touch = bool((navigator.maxTouchPoints or 0) > 0)
    if not is_mobile:
        has_touch = False
    viewport = _viewport_from_screen(screen, is_mobile=is_mobile)
    _harmonize_fingerprint_screen_geometry(
        screen,
        viewport=viewport,
        is_mobile=is_mobile,
    )
    return BrowserIdentity(
        user_agent=user_agent,
        viewport=viewport,
        extra_http_headers=headers,
        locale=locale,
        device_scale_factor=max(1.0, float(screen.devicePixelRatio or 1.0)),
        has_touch=has_touch,
        is_mobile=is_mobile,
        raw_fingerprint=fingerprint,
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


def _normalize_fingerprint_setting(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = str(value).strip()
        return (normalized,) if normalized else ()
    if not isinstance(value, Iterable) or isinstance(
        value,
        (bytes, bytearray, Mapping),
    ):
        return ()
    normalized_values: list[str] = []
    for item in value:
        normalized = str(item).strip()
        if normalized:
            normalized_values.append(normalized)
    return tuple(normalized_values)


def _fingerprint_generator() -> FingerprintGenerator:
    global _FINGERPRINT_GENERATOR, _FINGERPRINT_GENERATOR_CONFIG
    if _FINGERPRINT_GENERATOR is not None and not isinstance(
        _FINGERPRINT_GENERATOR,
        FingerprintGenerator,
    ):
        return _FINGERPRINT_GENERATOR
    config = (
        _normalize_fingerprint_setting(
            crawler_runtime_settings.fingerprint_browser
        ),
        _normalize_fingerprint_setting(
            crawler_runtime_settings.fingerprint_device
        ),
        _normalize_fingerprint_setting(
            crawler_runtime_settings.fingerprint_locale
        ),
    )
    if (
        _FINGERPRINT_GENERATOR is not None
        and _FINGERPRINT_GENERATOR_CONFIG == config
    ):
        return _FINGERPRINT_GENERATOR
    with _FINGERPRINT_GENERATOR_LOCK:
        if (
            _FINGERPRINT_GENERATOR is None
            or _FINGERPRINT_GENERATOR_CONFIG != config
        ):
            _FINGERPRINT_GENERATOR = FingerprintGenerator(
                browser=list(config[0]),
                os=[_HOST_OS],
                device=list(config[1]),
                locale=list(config[2]),
            )
            _FINGERPRINT_GENERATOR_CONFIG = config
    return _FINGERPRINT_GENERATOR


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
    if ua_major < crawler_runtime_settings.browser_identity_min_chrome_version:
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


def _generate_coherent_fingerprint() -> Any:
    expected_token = HOST_OS_UA_TOKENS[_HOST_OS]
    fallback_fingerprint = None
    for _ in range(3):
        fingerprint = _fingerprint_generator().generate()
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


def _repair_incoherent_client_hints(fingerprint: Any) -> Any:
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


def _strip_incoherent_client_hints(fingerprint: Any) -> Any:
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
    platform_label = _platform_label_from_user_agent(user_agent)
    return {
        "brands": [
            {"brand": "Not:A-Brand", "version": "99"},
            {"brand": "Google Chrome", "version": str(major_version)},
            {"brand": "Chromium", "version": str(major_version)},
        ],
        "fullVersionList": [
            {"brand": "Not:A-Brand", "version": "99.0.0.0"},
            {"brand": "Google Chrome", "version": full_version},
            {"brand": "Chromium", "version": full_version},
        ],
        "mobile": resolved_mobile,
        "platform": platform_label,
        "platformVersion": _platform_version_for_platform_label(platform_label),
        "bitness": _ua_bitness_from_user_agent(user_agent),
        "uaFullVersion": full_version,
    }


def _coherent_sec_ch_headers(user_agent_data: dict[str, object]) -> dict[str, str]:
    raw_brands = user_agent_data.get("brands")
    brands = (
        list(raw_brands)
        if isinstance(raw_brands, Iterable)
        and not isinstance(raw_brands, (str, bytes, bytearray, Mapping))
        else []
    )
    sec_ch_ua = ", ".join(
        f'"{str(item.get("brand") or "").replace("\"", "")}";v="{str(item.get("version") or "").replace("\"", "")}"'
        for item in brands
        if isinstance(item, dict) and item.get("brand") and item.get("version")
    )
    if not sec_ch_ua:
        return {}
    headers = {
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?1" if bool(user_agent_data.get("mobile")) else "?0",
        "sec-ch-ua-platform": f'"{user_agent_data.get("platform") or HOST_OS_PLATFORM_LABELS[_HOST_OS]}"',
    }
    platform_version = str(user_agent_data.get("platformVersion") or "").strip()
    if platform_version:
        headers["sec-ch-ua-platform-version"] = (
            f'"{platform_version.replace("\"", "")}"'
        )
    bitness = str(user_agent_data.get("bitness") or "").strip()
    if bitness:
        headers["sec-ch-ua-bitness"] = f'"{bitness.replace("\"", "")}"'
    return headers


def _should_replace_client_hint_headers(
    headers: Mapping[str, object],
    *,
    user_agent: str,
    user_agent_data: Mapping[str, object] | None,
) -> bool:
    normalized_headers = {
        str(key or "").strip().lower(): str(value or "").strip()
        for key, value in headers.items()
    }
    sec_ch_ua = normalized_headers.get("sec-ch-ua", "")
    if not sec_ch_ua:
        return True
    if "(" in sec_ch_ua or "not(a:brand" in sec_ch_ua.lower():
        return True
    ua_major = _chrome_major_version(user_agent)
    if ua_major is None:
        return False
    major_versions = _sec_ch_ua_major_versions(sec_ch_ua)
    if not major_versions:
        return True
    if any(abs(version - ua_major) > 2 for version in major_versions):
        return True
    expected_mobile = (
        bool(user_agent_data.get("mobile"))
        if isinstance(user_agent_data, Mapping)
        else bool(_MOBILE_UA_RE.search(user_agent))
    )
    if normalized_headers.get("sec-ch-ua-mobile") not in {
        "?1" if expected_mobile else "?0",
        "",
    }:
        return True
    expected_platform = HOST_OS_PLATFORM_LABELS[_HOST_OS].lower()
    raw_platform = normalized_headers.get("sec-ch-ua-platform", "").strip('"').lower()
    if raw_platform and raw_platform != expected_platform:
        return True
    return False


def _sec_ch_ua_major_versions(value: str) -> list[int]:
    matches = _re.findall(r'v="(\d+)', str(value or ""))
    versions: list[int] = []
    for match in matches:
        try:
            versions.append(int(match))
        except ValueError:
            continue
    return versions


def _accept_language_matches_locale(value: object, *, locale: str) -> bool:
    header = str(value or "").strip().lower()
    normalized_locale = str(locale or "").strip().lower()
    if not header or not normalized_locale:
        return False
    first_language = header.split(",", 1)[0].split(";", 1)[0].strip()
    return first_language == normalized_locale


def _normalized_locale(locale: object) -> str:
    return str(locale or "").strip().replace("_", "-")


def _locale_language(locale: object) -> str:
    normalized = _normalized_locale(locale)
    if not normalized:
        return ""
    return normalized.split("-", 1)[0].strip()


def _locale_region(locale: object) -> str | None:
    normalized = _normalized_locale(locale)
    if not normalized:
        return None
    parts = [part.strip() for part in normalized.split("-") if part.strip()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            return part.upper()
    return None


def _locale_languages(locale: object) -> list[str]:
    normalized = _normalized_locale(locale)
    if not normalized:
        return []
    language = _locale_language(normalized)
    if not language or language.lower() == normalized.lower():
        return [normalized]
    return [normalized, language]


def _country_code(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if not normalized or normalized == "AUTO":
        return None
    if normalized in pytz.country_timezones:
        return normalized
    return None


def _normalize_timezone_id(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    alias = TIMEZONE_ALIASES.get(normalized.lower())
    candidate = alias or normalized
    if candidate in pytz.all_timezones_set:
        return candidate
    if alias and alias in pytz.all_timezones_set:
        return alias
    return None


def _country_code_from_timezone(timezone_id: object) -> str | None:
    normalized_timezone = _normalize_timezone_id(timezone_id)
    if not normalized_timezone:
        return None
    return _TIMEZONE_TO_COUNTRY.get(normalized_timezone)


def _local_timezone_id() -> str | None:
    try:
        return _normalize_timezone_id(_get_localzone_name())
    except Exception:
        return None


def _resolve_timezone_id(locality_profile: Mapping[str, object] | None) -> str | None:
    configured = _normalize_timezone_id(
        crawler_runtime_settings.fingerprint_timezone_id
    )
    if configured:
        return configured
    explicit_locality_timezone = _normalize_timezone_id(
        locality_profile.get("timezone_id") if locality_profile else None
    )
    if explicit_locality_timezone:
        return explicit_locality_timezone
    country = _country_code(
        locality_profile.get("geo_country") if locality_profile else None
    )
    if country:
        country_timezones = tuple(pytz.country_timezones.get(country, ()))
        if country_timezones:
            return _normalize_timezone_id(country_timezones[0])
    return _local_timezone_id()


def _locale_with_region(
    locale: object,
    region: str | None,
    *,
    replace_region: bool,
) -> str:
    normalized = _normalized_locale(locale)
    if not normalized:
        return ""
    normalized_region = str(region or "").strip().upper()
    if not normalized_region:
        return normalized
    language = _locale_language(normalized)
    current_region = _locale_region(normalized)
    if current_region and not replace_region:
        return normalized
    if not language:
        return normalized
    return f"{language}-{normalized_region}"


def _chrome_major_version(user_agent: str) -> int | None:
    match = _UA_VERSION_RE.search(str(user_agent or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _replace_chrome_major_version(user_agent: str, major_version: int) -> str:
    return _UA_VERSION_RE.sub(f"Chrome/{int(major_version)}.", str(user_agent or ""), count=1)


def _drop_sec_ch_headers(headers: Mapping[str, object]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in headers.items()
        if not str(key).lower().startswith("sec-ch-ua")
    }


def _align_identity_to_browser_major(
    identity: BrowserIdentity,
    *,
    browser_major_version: int | None,
) -> BrowserIdentity:
    resolved_major = int(browser_major_version or 0)
    if resolved_major <= 0:
        return identity
    current_major = _chrome_major_version(identity.user_agent)
    if current_major is None:
        return identity
    if current_major == resolved_major:
        return identity
    aligned_user_agent = _replace_chrome_major_version(identity.user_agent, resolved_major)
    aligned_headers = _drop_sec_ch_headers(identity.extra_http_headers)
    coherent_hints = _coherent_client_hints_from_user_agent(
        aligned_user_agent,
        mobile=identity.is_mobile,
    )
    if coherent_hints:
        aligned_headers.update(_coherent_sec_ch_headers(coherent_hints))
    aligned_fingerprint = _align_raw_fingerprint_to_browser_major(
        identity.raw_fingerprint,
        browser_major_version=resolved_major,
        is_mobile=identity.is_mobile,
    )
    return BrowserIdentity(
        user_agent=aligned_user_agent,
        viewport=dict(identity.viewport),
        extra_http_headers=aligned_headers,
        locale=identity.locale,
        device_scale_factor=identity.device_scale_factor,
        has_touch=identity.has_touch,
        is_mobile=identity.is_mobile,
        raw_fingerprint=aligned_fingerprint,
    )


def _align_raw_fingerprint_to_browser_major(
    raw_fingerprint: Any | None,
    *,
    browser_major_version: int | None,
    is_mobile: bool,
) -> Any | None:
    resolved_major = int(browser_major_version or 0)
    if raw_fingerprint is None or resolved_major <= 0:
        return raw_fingerprint
    navigator = getattr(raw_fingerprint, "navigator", None)
    original_user_agent = str(getattr(navigator, "userAgent", "") or "")
    if not original_user_agent:
        return raw_fingerprint
    current_major = _chrome_major_version(original_user_agent)
    if current_major is None:
        return raw_fingerprint
    if current_major == resolved_major:
        return raw_fingerprint
    aligned_user_agent = _replace_chrome_major_version(
        original_user_agent,
        resolved_major,
    )
    aligned_fingerprint = _safely_clone_fingerprint(raw_fingerprint)
    aligned_navigator = getattr(aligned_fingerprint, "navigator", None)
    if aligned_navigator is None:
        return raw_fingerprint
    user_agent_data = (
        dict(getattr(aligned_navigator, "userAgentData", {}) or {})
        if isinstance(getattr(aligned_navigator, "userAgentData", None), dict)
        else {}
    )
    coherent_hints = _coherent_client_hints_from_user_agent(
        aligned_user_agent,
        mobile=is_mobile,
    )
    if coherent_hints:
        user_agent_data.update(coherent_hints)
    headers = _drop_sec_ch_headers(getattr(aligned_fingerprint, "headers", {}) or {})
    if coherent_hints:
        headers.update(_coherent_sec_ch_headers(user_agent_data))
    setattr(aligned_navigator, "userAgent", aligned_user_agent)
    if user_agent_data:
        setattr(aligned_navigator, "userAgentData", user_agent_data)
    setattr(aligned_fingerprint, "headers", headers)
    return aligned_fingerprint


def _align_raw_fingerprint_to_locale(
    raw_fingerprint: Any | None,
    *,
    locale: str,
) -> Any | None:
    if raw_fingerprint is None:
        return None
    aligned_fingerprint = _safely_clone_fingerprint(raw_fingerprint)
    navigator = getattr(aligned_fingerprint, "navigator", None)
    if navigator is None:
        return raw_fingerprint
    setattr(navigator, "language", locale)
    setattr(navigator, "languages", _locale_languages(locale))
    headers = dict(getattr(aligned_fingerprint, "headers", {}) or {})
    headers["Accept-Language"] = _accept_language_for_locale(locale)
    setattr(aligned_fingerprint, "headers", headers)
    return aligned_fingerprint


def _resolve_locale(
    identity: BrowserIdentity,
    *,
    locality_profile: Mapping[str, object] | None,
    timezone_id: str | None,
) -> str:
    explicit_locale = _normalized_locale(
        locality_profile.get("language_hint") if locality_profile else None
    )
    if explicit_locale:
        return _locale_with_region(
            explicit_locale,
            _country_code(locality_profile.get("geo_country") if locality_profile else None),
            replace_region=False,
        )
    locale = _normalized_locale(identity.locale) or _normalized_locale(
        crawler_runtime_settings.fingerprint_locale
    )
    if not bool(
        crawler_runtime_settings.fingerprint_locale_auto_align_timezone_region
    ) or timezone_id is None:
        return locale
    return _locale_with_region(
        locale,
        _country_code_from_timezone(timezone_id),
        replace_region=True,
    )


def _align_identity_to_locality(
    identity: BrowserIdentity,
    *,
    locality_profile: Mapping[str, object] | None,
) -> tuple[BrowserIdentity, str | None]:
    timezone_id = _resolve_timezone_id(locality_profile)
    resolved_locale = _resolve_locale(
        identity,
        locality_profile=locality_profile,
        timezone_id=timezone_id,
    )
    if not resolved_locale:
        return identity, timezone_id
    headers = dict(identity.extra_http_headers)
    if not _accept_language_matches_locale(
        headers.get("Accept-Language"),
        locale=resolved_locale,
    ):
        headers["Accept-Language"] = _accept_language_for_locale(resolved_locale)
    raw_fingerprint = _align_raw_fingerprint_to_locale(
        identity.raw_fingerprint,
        locale=resolved_locale,
    )
    return (
        BrowserIdentity(
            user_agent=identity.user_agent,
            viewport=dict(identity.viewport),
            extra_http_headers=headers,
            locale=resolved_locale,
            device_scale_factor=identity.device_scale_factor,
            has_touch=identity.has_touch,
            is_mobile=identity.is_mobile,
            raw_fingerprint=raw_fingerprint,
        ),
        timezone_id,
    )


def _playwright_context_options_from_identity(
    identity: BrowserIdentity,
    *,
    timezone_id: str | None = None,
) -> dict[str, Any]:
    options = {
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
    color_scheme = _context_color_scheme()
    if color_scheme is not None:
        options["color_scheme"] = color_scheme
    permissions = [
        str(value or "").strip()
        for value in tuple(crawler_runtime_settings.browser_context_permissions or ())
        if str(value or "").strip()
    ]
    if permissions:
        options["permissions"] = permissions
    if timezone_id:
        options["timezone_id"] = timezone_id
    return options


def playwright_masking_init_script() -> str:
    globals_to_mask = [
        str(value or "").strip()
        for value in tuple(crawler_runtime_settings.browser_mask_playwright_globals or ())
        if str(value or "").strip()
    ]
    lines = [
        _INIT_WRAPPER_START,
        "  const roots = [globalThis];",
        "  if (typeof window !== 'undefined' && window !== globalThis) {",
        "    roots.push(window);",
        "  }",
        "  const maskGlobal = (key) => {",
        "    for (const root of roots) {",
        "      try {",
        "        Object.defineProperty(root, key, {",
        "          get: () => undefined,",
        "          set: () => true,",
        "          enumerable: false,",
        "          configurable: false,",
        "        });",
        "      } catch (_) {}",
        "    }",
        "  };",
        f"  const pwKeys = {globals_to_mask!r};",
        "  for (const key of pwKeys) {",
        "    maskGlobal(key);",
        "  }",
    ]
    if bool(crawler_runtime_settings.browser_disable_web_workers):
        lines.extend(
            [
                "  maskGlobal('Worker');",
                "  maskGlobal('SharedWorker');",
                _TRY_LINE,
                "    Object.defineProperty(Navigator.prototype, 'serviceWorker', {",
                "      get: () => undefined,",
                "      set: () => true,",
                _ENUMERABLE_FALSE_LINE,
                _CONFIGURABLE_TRUE_LINE,
                _DEFINE_PROPERTY_CLOSE_LINE,
                _CATCH_IGNORE_LINE,
            ]
        )
    lines.append(_INIT_WRAPPER_END)
    return "\n".join(lines)


def _playwright_identity_seed(
    identity: BrowserIdentity,
    *,
    timezone_id: str | None = None,
) -> int:
    raw_fingerprint = identity.raw_fingerprint
    navigator = getattr(raw_fingerprint, "navigator", None)
    seed_payload = _json.dumps(
        {
            "user_agent": identity.user_agent,
            "viewport": dict(identity.viewport),
            "locale": identity.locale,
            "timezone_id": timezone_id or "",
            "device_scale_factor": identity.device_scale_factor,
            "has_touch": identity.has_touch,
            "is_mobile": identity.is_mobile,
            "hardware_concurrency": _resolved_hardware_concurrency(
                getattr(navigator, "hardwareConcurrency", None)
            ),
            "device_memory_gb": _resolved_device_memory_gb(
                getattr(navigator, "deviceMemory", None)
            ),
        },
        sort_keys=True,
    )
    return int(
        _hashlib.sha256(seed_payload.encode("utf-8")).hexdigest()[:8],
        16,
    )


def _playwright_init_script_from_identity(
    identity: BrowserIdentity,
    *,
    timezone_id: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> str | None:
    if not _should_use_legacy_init_script(browser_engine):
        return None

    def _bundle_init_scripts(*parts: str) -> str:
        return "\n;\n".join(
            part for part in parts if str(part or "").strip()
        )

    masking_script = playwright_masking_init_script()
    raw_fingerprint = identity.raw_fingerprint
    identity_seed = _playwright_identity_seed(
        identity,
        timezone_id=timezone_id,
    )
    user_agent_version_match = _UA_VERSION_RE.search(identity.user_agent)
    chrome_runtime_version = (
        f"{int(user_agent_version_match.group(1))}.0.0.0"
        if user_agent_version_match is not None
        else "145.0.0.0"
    )
    color_scheme = str(
        crawler_runtime_settings.fingerprint_color_scheme or ""
    ).strip().lower()
    permissions_script = build_permissions_coherence_init_script(
        granted_permissions=tuple(
            str(value).strip().lower()
            for value in tuple(crawler_runtime_settings.browser_context_permissions or ())
            if str(value).strip()
        ),
    )
    runtime_hardware_script = "\n".join(
        [
            _INIT_WRAPPER_START,
            f"  const hardwareConcurrency = {_json.dumps(_resolved_hardware_concurrency(getattr(getattr(raw_fingerprint, 'navigator', None), 'hardwareConcurrency', None)))};",
            f"  const deviceMemory = {_json.dumps(_resolved_device_memory_gb(getattr(getattr(raw_fingerprint, 'navigator', None), 'deviceMemory', None)))};",
            "  const installNavigatorValue = (key, value) => {",
            "    if (value === null || value === undefined) {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(Navigator.prototype, key, {",
            "        get: () => value,",
            "        enumerable: false,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  installNavigatorValue('hardwareConcurrency', hardwareConcurrency);",
            "  installNavigatorValue('deviceMemory', deviceMemory);",
            _INIT_WRAPPER_END,
        ]
    )
    chrome_runtime_script = build_chrome_runtime_init_script(
        chrome_runtime_version=chrome_runtime_version,
    )
    audio_fingerprint_script = build_audio_fingerprint_init_script(
        audio_seed=identity_seed,
    )
    performance_coherence_script = build_performance_coherence_init_script()
    platform_label = _platform_label_from_user_agent(identity.user_agent)
    # Builder injects getImageData/toDataURL and getParameter/readPixels patches.
    canvas_fingerprint_script = build_canvas_fingerprint_init_script(
        canvas_seed=identity_seed,
    )
    webgl_fingerprint_script = build_webgl_fingerprint_init_script(
        platform_label=platform_label,
        is_mobile=identity.is_mobile,
        webgl_seed=identity_seed,
    )
    navigator_coherence_script = build_navigator_coherence_init_script(
        platform_label=platform_label,
        is_mobile=identity.is_mobile,
        viewport_width=int(identity.viewport.get("width", 0) or 0),
        viewport_height=int(identity.viewport.get("height", 0) or 0),
    )
    font_surface_script = build_font_surface_init_script(
        platform_label=platform_label,
        is_mobile=identity.is_mobile,
    )
    intl_coherence_script = build_intl_coherence_init_script(
        locale=identity.locale,
        timezone_id=timezone_id,
    )
    color_scheme_script = "\n".join(
        [
            _INIT_WRAPPER_START,
            f"  const preferredColorScheme = {_json.dumps(color_scheme)};",
            "  if (!preferredColorScheme || typeof window.matchMedia !== 'function') {",
            "    return;",
            "  }",
            "  const nativeMatchMedia = window.matchMedia.bind(window);",
            "  window.matchMedia = function matchMedia(query) {",
            "    const result = nativeMatchMedia(query);",
            "    const normalized = String(query || '').toLowerCase();",
            "    if (!normalized.includes('prefers-color-scheme')) {",
            "      return result;",
            "    }",
            "    const matches = normalized.includes(preferredColorScheme);",
            "    const wrapped = Object.create(result);",
            "    try {",
            "      Object.defineProperty(wrapped, 'matches', {",
            "        get: () => matches,",
            "        enumerable: true,",
            "        configurable: true,",
            "      });",
            "      Object.defineProperty(wrapped, 'media', {",
            "        get: () => result.media,",
            "        enumerable: true,",
            "        configurable: true,",
            "      });",
            _CATCH_IGNORE_LINE,
            "    return wrapped;",
            "  };",
            _INIT_WRAPPER_END,
        ]
    )
    webrtc_mask_script = "\n".join(
        [
            _INIT_WRAPPER_START,
            f"  const enabled = {_json.dumps(bool(crawler_runtime_settings.browser_mask_webrtc_local_ips))};",
            "  if (!enabled) {",
            "    return;",
            "  }",
            "  const emptyStats = new Map();",
            "  const noop = () => undefined;",
            "  class MaskedRTCDataChannel {",
            "    constructor(label = '') {",
            "      this.label = String(label || '');",
            "      this.readyState = 'open';",
            "      this.bufferedAmount = 0;",
            "      this.binaryType = 'blob';",
            "      this.onopen = null;",
            "      this.onclose = null;",
            "      this.onerror = null;",
            "      this.onmessage = null;",
            "    }",
            "    addEventListener() {}",
            "    removeEventListener() {}",
            "    dispatchEvent() { return true; }",
            "    close() {",
            "      this.readyState = 'closed';",
            "      if (typeof this.onclose === 'function') {",
            "        try { this.onclose(new Event('close')); } catch (_) {}",
            "      }",
            "    }",
            "    send() {}",
            "  }",
            "  class MaskedRTCPeerConnection {",
            "    constructor() {",
            "      this.localDescription = null;",
            "      this.remoteDescription = null;",
            "      this.pendingLocalDescription = null;",
            "      this.pendingRemoteDescription = null;",
            "      this._senders = [];",
            "      this.connectionState = 'new';",
            "      this.iceConnectionState = 'new';",
            "      this.iceGatheringState = 'complete';",
            "      this.signalingState = 'stable';",
            "      this.canTrickleIceCandidates = false;",
            "      this.onicecandidate = null;",
            "      this.onicecandidateerror = null;",
            "      this.onconnectionstatechange = null;",
            "      this.oniceconnectionstatechange = null;",
            "      this.onicegatheringstatechange = null;",
            "      this.onnegotiationneeded = null;",
            "      this.onsignalingstatechange = null;",
            "      this.ondatachannel = null;",
            "      queueMicrotask(() => {",
            "        if (typeof this.onicecandidate === 'function') {",
            "          try { this.onicecandidate({ candidate: null, type: 'icecandidate', target: this, currentTarget: this }); } catch (_) {}",
            "        }",
            "      });",
            "    }",
            "    addEventListener() {}",
            "    removeEventListener() {}",
            "    dispatchEvent() { return true; }",
            "    createDataChannel(label) { return new MaskedRTCDataChannel(label); }",
            "    createOffer() { return Promise.resolve({ type: 'offer', sdp: 'v=0\\r\\n' }); }",
            "    createAnswer() { return Promise.resolve({ type: 'answer', sdp: 'v=0\\r\\n' }); }",
            "    addTrack(track) {",
            "      const sender = {",
            "        track: track || null,",
            "        transport: null,",
            "        dtmf: null,",
            "        replaceTrack(nextTrack) { this.track = nextTrack || null; return Promise.resolve(); },",
            "        setStreams() {},",
            "        getParameters() { return {}; },",
            "        setParameters() { return Promise.resolve(); },",
            "        stop() { this.track = null; },",
            "      };",
            "      this._senders.push(sender);",
            "      return sender;",
            "    }",
            "    setLocalDescription(description) {",
            "      this.localDescription = description || { type: 'offer', sdp: 'v=0\\r\\n' };",
            "      this.pendingLocalDescription = this.localDescription;",
            "      return Promise.resolve();",
            "    }",
            "    setRemoteDescription(description) {",
            "      this.remoteDescription = description || null;",
            "      this.pendingRemoteDescription = this.remoteDescription;",
            "      return Promise.resolve();",
            "    }",
            "    addIceCandidate() { return Promise.resolve(); }",
            "    getConfiguration() { return { iceServers: [] }; }",
            "    setConfiguration() {}",
            "    getSenders() { return this._senders.slice(); }",
            "    getReceivers() { return []; }",
            "    getTransceivers() { return []; }",
            "    getStats() { return Promise.resolve(emptyStats); }",
            "    removeTrack(sender) {",
            "      const index = this._senders.indexOf(sender);",
            "      if (index >= 0) {",
            "        this._senders.splice(index, 1);",
            "      }",
            "      if (sender && typeof sender.stop === 'function') {",
            "        try { sender.stop(); } catch (_) {}",
            "      }",
            "    }",
            "    restartIce() {}",
            "    close() {",
            "      this._senders = [];",
            "      this.connectionState = 'closed';",
            "      this.iceConnectionState = 'closed';",
            "      this.signalingState = 'closed';",
            "    }",
            "  }",
            "  MaskedRTCPeerConnection.prototype.createDTMFSender = noop;",
            "  MaskedRTCPeerConnection.generateCertificate = () => Promise.resolve({});",
            _TRY_LINE,
            "    Object.defineProperty(MaskedRTCPeerConnection, 'name', { value: 'RTCPeerConnection' });",
            _CATCH_IGNORE_LINE,
            "  globalThis.RTCPeerConnection = MaskedRTCPeerConnection;",
            "  if (globalThis.webkitRTCPeerConnection) {",
            "    globalThis.webkitRTCPeerConnection = MaskedRTCPeerConnection;",
            "  }",
            "  if (globalThis.mozRTCPeerConnection) {",
            "    globalThis.mozRTCPeerConnection = MaskedRTCPeerConnection;",
            "  }",
            _INIT_WRAPPER_END,
        ]
    )
    locality_script = "\n".join(
        [
            _INIT_WRAPPER_START,
            f"  const locale = {_json.dumps(identity.locale)};",
            f"  const languages = {_json.dumps(_locale_languages(identity.locale))};",
            f"  const navigatorPlatform = {_json.dumps(_navigator_platform_from_user_agent(identity.user_agent))};",
            f"  const uaPlatform = {_json.dumps(_platform_label_from_user_agent(identity.user_agent))};",
            _TRY_LINE,
            "    Object.defineProperty(Navigator.prototype, 'language', {",
            "      get: () => locale,",
            _ENUMERABLE_FALSE_LINE,
            _CONFIGURABLE_TRUE_LINE,
            _DEFINE_PROPERTY_CLOSE_LINE,
            _CATCH_IGNORE_LINE,
            _TRY_LINE,
            "    Object.defineProperty(Navigator.prototype, 'languages', {",
            "      get: () => Array.from(languages),",
            _ENUMERABLE_FALSE_LINE,
            _CONFIGURABLE_TRUE_LINE,
            _DEFINE_PROPERTY_CLOSE_LINE,
            _CATCH_IGNORE_LINE,
            _TRY_LINE,
            "    Object.defineProperty(Navigator.prototype, 'platform', {",
            "      get: () => navigatorPlatform,",
            _ENUMERABLE_FALSE_LINE,
            _CONFIGURABLE_TRUE_LINE,
            _DEFINE_PROPERTY_CLOSE_LINE,
            _CATCH_IGNORE_LINE,
            _TRY_LINE,
            "    const nativeUaData = Navigator.prototype.userAgentData || navigator.userAgentData;",
            "    if (nativeUaData) {",
            "      const patchedUaData = new Proxy(nativeUaData, {",
            "        get(target, prop, receiver) {",
            "          if (prop === 'platform') {",
            "            return uaPlatform;",
            "          }",
            "          if (prop === 'getHighEntropyValues') {",
            "            return async (hints) => {",
            "              const result = await target.getHighEntropyValues(hints);",
            "              return { ...result, platform: uaPlatform, platformVersion: target.platformVersion || result.platformVersion, bitness: target.bitness || result.bitness, uaFullVersion: target.uaFullVersion || result.uaFullVersion, fullVersionList: target.fullVersionList || result.fullVersionList };",
            "            };",
            "          }",
            "          return Reflect.get(target, prop, receiver);",
            "        },",
            "      });",
            "      Object.defineProperty(Navigator.prototype, 'userAgentData', {",
            "        get: () => patchedUaData,",
            "        enumerable: false,",
            "        configurable: true,",
            "      });",
            "    }",
            _CATCH_IGNORE_LINE,
            "})();",
        ]
    )
    base_scripts = [
        masking_script,
        permissions_script,
        color_scheme_script,
        webrtc_mask_script,
        locality_script,
        intl_coherence_script,
    ]
    tail_scripts = [
        runtime_hardware_script,
        chrome_runtime_script,
        audio_fingerprint_script,
        performance_coherence_script,
        canvas_fingerprint_script,
        webgl_fingerprint_script,
        navigator_coherence_script,
        font_surface_script,
    ]
    if raw_fingerprint is None or _BrowserforgeInjectFunction is None:
        return _bundle_init_scripts(*base_scripts, *tail_scripts)
    if (
        _BrowserforgeFingerprint is not None
        and not isinstance(raw_fingerprint, _BrowserforgeFingerprint)
    ):
        return _bundle_init_scripts(*base_scripts, *tail_scripts)
    if not callable(getattr(raw_fingerprint, "dumps", None)):
        return _bundle_init_scripts(*base_scripts, *tail_scripts)
    try:
        browserforge_script = str(_BrowserforgeInjectFunction(raw_fingerprint))
        return _bundle_init_scripts(*base_scripts, browserforge_script, *tail_scripts)
    except Exception:
        _logger.debug("Failed to build browserforge init script", exc_info=True)
        return _bundle_init_scripts(*base_scripts, *tail_scripts)


def build_playwright_context_spec(
    identity: BrowserIdentity | None = None,
    *,
    run_id: int | None = None,
    browser_major_version: int | None = None,
    locality_profile: Mapping[str, object] | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> PlaywrightContextSpec:
    identity = identity or browser_identity_for_run(run_id)
    identity = _align_identity_to_browser_major(
        identity,
        browser_major_version=browser_major_version,
    )
    identity, timezone_id = _align_identity_to_locality(
        identity,
        locality_profile=locality_profile,
    )
    return PlaywrightContextSpec(
        context_options=_playwright_context_options_from_identity(
            identity,
            timezone_id=timezone_id,
        ),
        init_script=_playwright_init_script_from_identity(
            identity,
            timezone_id=timezone_id,
            browser_engine=browser_engine,
        ),
    )


def build_playwright_context_options(
    identity: BrowserIdentity | None = None,
    *,
    run_id: int | None = None,
    browser_major_version: int | None = None,
    locality_profile: Mapping[str, object] | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> dict[str, Any]:
    return build_playwright_context_spec(
        identity=identity,
        run_id=run_id,
        browser_major_version=browser_major_version,
        locality_profile=locality_profile,
        browser_engine=browser_engine,
    ).context_options
