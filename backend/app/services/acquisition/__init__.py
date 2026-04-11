from __future__ import annotations

from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyPoolExhausted,
    acquire,
    scrub_network_payloads_for_storage,
)
from app.services.acquisition.browser_client import (
    BrowserResult,
    browser_pool_snapshot,
    expand_all_interactive_elements,
    fetch_rendered_html,
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool,
    shutdown_browser_pool_sync,
)
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.cookie_store import validate_cookie_policy_config

# TODO: add browser_pool exports after Phase C when app.services.acquisition.browser_pool
# exists as the owning module.

__all__ = [
    "AcquisitionRequest",
    "AcquisitionResult",
    "ProxyPoolExhausted",
    "acquire",
    "BrowserResult",
    "browser_pool_snapshot",
    "detect_blocked_page",
    "fetch_rendered_html",
    "expand_all_interactive_elements",
    "prepare_browser_pool_for_worker_process",
    "shutdown_browser_pool",
    "shutdown_browser_pool_sync",
    "scrub_network_payloads_for_storage",
    "validate_cookie_policy_config",
]
