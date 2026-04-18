from __future__ import annotations

from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyPoolExhausted,
    acquire,
    detect_blocked_page,
    scrub_network_payloads_for_storage,
)
from app.services.acquisition.browser_client import (
    BrowserResult,
    expand_all_interactive_elements,
    fetch_rendered_html,
)
from app.services.acquisition.browser_pool import (
    BrowserPool,
    browser_pool_snapshot,
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool,
    shutdown_browser_pool_sync,
)
from app.services.acquisition.cookie_store import validate_cookie_policy_config
from app.services.acquisition.http_client import (
    HttpFetchResult,
    close_shared_http_client,
    request_result,
)
from app.services.acquisition.pacing import wait_for_host_slot

__all__ = [
    "AcquisitionRequest",
    "AcquisitionResult",
    "ProxyPoolExhausted",
    "acquire",
    "BrowserPool",
    "BrowserResult",
    "browser_pool_snapshot",
    "detect_blocked_page",
    "expand_all_interactive_elements",
    "fetch_rendered_html",
    "HttpFetchResult",
    "close_shared_http_client",
    "prepare_browser_pool_for_worker_process",
    "request_result",
    "scrub_network_payloads_for_storage",
    "shutdown_browser_pool",
    "shutdown_browser_pool_sync",
    "validate_cookie_policy_config",
    "wait_for_host_slot",
]
