from __future__ import annotations

from app.core.config import settings
from app.services.acquisition.browser_proxy_config import display_proxy, proxy_scheme
from app.services.config.runtime_settings import crawler_runtime_settings

CHROMIUM_BROWSER_ENGINE = "chromium"
PATCHRIGHT_BROWSER_ENGINE = "patchright"
REAL_CHROME_BROWSER_ENGINE = "real_chrome"
SUPPORTED_BROWSER_ENGINES = {
    CHROMIUM_BROWSER_ENGINE,
    PATCHRIGHT_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE,
}


def normalize_browser_engine(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_BROWSER_ENGINES:
        return normalized
    return PATCHRIGHT_BROWSER_ENGINE


def launch_headless_for_engine(engine: str) -> bool:
    normalized_engine = normalize_browser_engine(engine)
    if (
        normalized_engine == REAL_CHROME_BROWSER_ENGINE
        and crawler_runtime_settings.browser_real_chrome_force_headful
    ):
        return False
    return bool(settings.playwright_headless)


def use_native_real_chrome_context(engine: str) -> bool:
    return (
        normalize_browser_engine(engine) == REAL_CHROME_BROWSER_ENGINE
        and crawler_runtime_settings.browser_real_chrome_native_context
    )


def browser_launch_mode(engine: str) -> str:
    return "headless" if launch_headless_for_engine(engine) else "headful"


def browser_profile(engine: str) -> str:
    normalized_engine = normalize_browser_engine(engine)
    if normalized_engine == PATCHRIGHT_BROWSER_ENGINE:
        return "patchright_shaped"
    if normalized_engine == REAL_CHROME_BROWSER_ENGINE:
        if use_native_real_chrome_context(normalized_engine):
            return "real_chrome_native"
        return "real_chrome_shaped"
    return "chromium_shaped"


def browser_profile_diagnostics(engine: str) -> dict[str, object]:
    normalized_engine = normalize_browser_engine(engine)
    return {
        "browser_profile": browser_profile(normalized_engine),
        "browser_launch_mode": browser_launch_mode(normalized_engine),
        "browser_headless": launch_headless_for_engine(normalized_engine),
        "browser_native_context": use_native_real_chrome_context(normalized_engine),
        "browser_stealth_enabled": False,
    }


def build_browser_diagnostics_contract(
    *,
    diagnostics: dict[str, object] | None = None,
    browser_reason: str | None = None,
    browser_outcome: str | None = None,
    browser_engine: str = CHROMIUM_BROWSER_ENGINE,
    browser_binary: str | None = None,
    failure_reason: str | None = None,
    retry_reason: str | None = None,
    phase_timings_ms: dict[str, int] | None = None,
) -> dict[str, object]:
    normalized_engine = normalize_browser_engine(browser_engine)
    payload = dict(diagnostics or {})
    payload["browser_attempted"] = True
    payload["browser_reason"] = str(browser_reason or "").strip().lower() or None
    payload["browser_outcome"] = str(browser_outcome or "").strip().lower() or None
    payload["failure_reason"] = str(failure_reason or "").strip().lower() or None
    if retry_reason is not None:
        normalized_retry = str(retry_reason or "").strip().lower() or None
        if normalized_retry or "retry_reason" not in payload:
            payload["retry_reason"] = normalized_retry
    else:
        payload.setdefault("retry_reason", None)
    payload["browser_engine"] = normalized_engine
    payload["browser_binary"] = str(browser_binary or normalized_engine)
    payload.update(browser_profile_diagnostics(normalized_engine))
    phase_timings_payload = payload.get("phase_timings_ms")
    existing_timings: dict[str, object] = (
        dict(phase_timings_payload)
        if isinstance(phase_timings_payload, dict)
        else {}
    )
    incoming_timings = dict(phase_timings_ms or {}) if phase_timings_ms is not None else {}
    existing_timings.update(incoming_timings)
    payload["phase_timings_ms"] = existing_timings
    payload.setdefault("artifact_paths", {})
    return payload


def is_timeout_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    return "timeout" in class_name or "timeout" in message


def browser_failure_kind(exc: Exception) -> str:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    if "targetclosed" in class_name or "target closed" in message:
        return "page_closed"
    if "page closed" in message or "browser has been closed" in message:
        return "page_closed"
    if "connection closed while reading from the driver" in message:
        return "browser_driver_closed"
    if "real chrome executable is not available" in message:
        return "engine_unavailable"
    if "patchright package is not available" in message:
        return "engine_unavailable"
    if (
        isinstance(exc, ValueError)
        and "browser proxy" in message
    ) or "socks5 proxy authentication" in message:
        return "unsupported_proxy"
    if is_timeout_error(exc):
        return "timeout"
    return "navigation_error"


def build_failed_browser_diagnostics(
    *,
    browser_reason: str | None,
    exc: Exception,
    proxy: str | None = None,
    proxy_attempt_index: int | None = None,
    browser_engine: str = CHROMIUM_BROWSER_ENGINE,
    browser_binary: str | None = None,
    bridge_used: bool = False,
    escalation_lane: str | None = None,
    host_policy_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    outcome = "render_timeout" if is_timeout_error(exc) else "navigation_failed"
    failure_kind = browser_failure_kind(exc)
    failure_stage = str(getattr(exc, "browser_failure_stage", "navigation") or "navigation")
    normalized_engine = normalize_browser_engine(browser_engine)
    diagnostics = {
        "failure_kind": failure_kind,
        "failure_stage": failure_stage,
        "timeout_phase": failure_stage if is_timeout_error(exc) else None,
        "proxy_url_redacted": display_proxy(proxy),
        "proxy_scheme": proxy_scheme(proxy),
        "browser_proxy_mode": str(
            getattr(
                exc,
                "browser_proxy_mode",
                "launch" if proxy else "direct",
            )
            or ("launch" if proxy else "direct")
        ),
        "proxy_attempt_index": proxy_attempt_index,
        "bridge_used": bool(bridge_used),
        "escalation_lane": str(escalation_lane or "").strip().lower() or None,
        "host_policy_snapshot": dict(host_policy_snapshot or {}),
        "error": f"{type(exc).__name__}: {exc}",
        "navigation_strategy": getattr(exc, "browser_navigation_strategy", None),
    }
    return build_browser_diagnostics_contract(
        diagnostics=diagnostics,
        browser_reason=browser_reason,
        browser_outcome=outcome,
        browser_engine=normalized_engine,
        browser_binary=browser_binary,
        failure_reason=failure_kind,
        phase_timings_ms=dict(getattr(exc, "browser_phase_timings_ms", {}) or {}),
    )


__all__ = [
    "CHROMIUM_BROWSER_ENGINE",
    "PATCHRIGHT_BROWSER_ENGINE",
    "REAL_CHROME_BROWSER_ENGINE",
    "SUPPORTED_BROWSER_ENGINES",
    "browser_failure_kind",
    "browser_launch_mode",
    "browser_profile",
    "browser_profile_diagnostics",
    "build_browser_diagnostics_contract",
    "build_failed_browser_diagnostics",
    "launch_headless_for_engine",
    "normalize_browser_engine",
    "use_native_real_chrome_context",
]
