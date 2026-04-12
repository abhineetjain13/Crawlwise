from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "AcquisitionRequest": (
        "app.services.acquisition.acquirer",
        "AcquisitionRequest",
    ),
    "AcquisitionResult": ("app.services.acquisition.acquirer", "AcquisitionResult"),
    "ProxyPoolExhausted": ("app.services.acquisition.acquirer", "ProxyPoolExhausted"),
    "acquire": ("app.services.acquisition.acquirer", "acquire"),
    "BrowserPool": ("app.services.acquisition.browser_pool", "BrowserPool"),
    "BrowserResult": ("app.services.acquisition.browser_client", "BrowserResult"),
    "browser_pool_snapshot": (
        "app.services.acquisition.browser_pool",
        "browser_pool_snapshot",
    ),
    "detect_blocked_page": (
        "app.services.acquisition.blocked_detector",
        "detect_blocked_page",
    ),
    "expand_all_interactive_elements": (
        "app.services.acquisition.browser_client",
        "expand_all_interactive_elements",
    ),
    "fetch_rendered_html": (
        "app.services.acquisition.browser_client",
        "fetch_rendered_html",
    ),
    "HttpFetchResult": ("app.services.acquisition.http_client", "HttpFetchResult"),
    "prepare_browser_pool_for_worker_process": (
        "app.services.acquisition.browser_pool",
        "prepare_browser_pool_for_worker_process",
    ),
    "request_result": ("app.services.acquisition.http_client", "request_result"),
    "reset_browser_pool_state": (
        "app.services.acquisition.browser_pool",
        "reset_browser_pool_state",
    ),
    "scrub_network_payloads_for_storage": (
        "app.services.acquisition.acquirer",
        "scrub_network_payloads_for_storage",
    ),
    "shutdown_browser_pool": (
        "app.services.acquisition.browser_pool",
        "shutdown_browser_pool",
    ),
    "shutdown_browser_pool_sync": (
        "app.services.acquisition.browser_pool",
        "shutdown_browser_pool_sync",
    ),
    "validate_cookie_policy_config": (
        "app.services.acquisition.cookie_store",
        "validate_cookie_policy_config",
    ),
    "wait_for_host_slot": ("app.services.acquisition.pacing", "wait_for_host_slot"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
