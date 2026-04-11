from __future__ import annotations

from app.services.acquisition.http_client import HttpFetchResult, request_result, requests
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.acquisition.browser_pool import (
    BrowserPool,
    browser_pool_snapshot,
    prepare_browser_pool_for_worker_process,
    reset_browser_pool_state,
    shutdown_browser_pool,
    shutdown_browser_pool_sync,
)
from app.services.acquisition.browser_client import (
    BrowserResult,
    expand_all_interactive_elements,
    fetch_rendered_html,
)
from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyPoolExhausted,
    acquire,
    scrub_network_payloads_for_storage,
)
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.cookie_store import validate_cookie_policy_config

__all__ = [
    "AcquisitionRequest",
    "AcquisitionResult",
    "ProxyPoolExhausted",
    "acquire",
    "BrowserPool",
    "BrowserResult",
    "browser_pool_snapshot",
    "detect_blocked_page",
    "fetch_rendered_html",
    "expand_all_interactive_elements",
    "HttpFetchResult",
    "reset_browser_pool_state",
    "prepare_browser_pool_for_worker_process",
    "request_result",
    "requests",
    "shutdown_browser_pool",
    "shutdown_browser_pool_sync",
    "scrub_network_payloads_for_storage",
    "validate_cookie_policy_config",
    "wait_for_host_slot",
]
