"""
Shared acquisition utilities to break circular dependencies.

This module contains functions that are used by both pipeline.py and batch runtime,
preventing the need for runtime monkeypatching.
"""
from __future__ import annotations

from app.services.acquisition.acquirer import acquire as _acquire, AcquisitionResult
from app.services.pipeline_config import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_SCROLLS,
    DEFAULT_SLEEP_MS,
)
from app.services.adapters.registry import (
    run_adapter as _run_adapter,
    try_blocked_adapter_recovery as _try_blocked_adapter_recovery,
    AdapterResult,
)


async def acquire(
    *,
    run_id: int,
    url: str,
    surface: str,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = DEFAULT_SLEEP_MS,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[str]] | None = None,
    acquisition_profile: dict[str, object] | None = None,
    checkpoint=None,
) -> AcquisitionResult:
    """
    Acquire content from a URL using appropriate method (curl_cffi or playwright).
    
    This is a thin wrapper around the actual acquirer to provide a stable import point.
    """
    return await _acquire(
        run_id=run_id,
        url=url,
        surface=surface,
        proxy_list=proxy_list,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
        requested_fields=requested_fields,
        requested_field_selectors=requested_field_selectors,
        acquisition_profile=acquisition_profile,
        checkpoint=checkpoint,
    )


async def run_adapter(url: str, html: str, surface: str) -> AdapterResult | None:
    """
    Run platform-specific adapter for the given URL and HTML.
    
    This is a thin wrapper around the adapter registry to provide a stable import point.
    """
    return await _run_adapter(url, html, surface)


async def try_blocked_adapter_recovery(
    url: str,
    surface: str,
) -> AdapterResult | None:
    """
    Attempt to recover data from a blocked page using platform adapters.
    
    This is a thin wrapper around the adapter registry to provide a stable import point.
    """
    return await _try_blocked_adapter_recovery(url, surface)
