from __future__ import annotations

from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyPoolExhausted,
    acquire,
)
from app.services.acquisition.browser_runtime import (
    browser_runtime_snapshot,
    expand_all_interactive_elements,
    shutdown_browser_runtime,
    shutdown_browser_runtime_sync,
)
from app.services.acquisition.cookie_store import validate_cookie_policy_config
from app.services.acquisition.http_client import (
    HttpFetchResult,
    close_shared_http_client as _close_adapter_shared_http_client,
    request_result,
)
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.acquisition.runtime import (
    PageFetchResult,
    close_shared_http_client as _close_runtime_shared_http_client,
    fetch_page,
    is_blocked_html,
)


async def close_shared_http_client() -> None:
    await _close_runtime_shared_http_client()
    await _close_adapter_shared_http_client()

__all__ = [
    "AcquisitionRequest",
    "AcquisitionResult",
    "ProxyPoolExhausted",
    "acquire",
    "browser_runtime_snapshot",
    "expand_all_interactive_elements",
    "HttpFetchResult",
    "close_shared_http_client",
    "PageFetchResult",
    "request_result",
    "fetch_page",
    "is_blocked_html",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
    "validate_cookie_policy_config",
    "wait_for_host_slot",
]
