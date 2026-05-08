from __future__ import annotations

import app.services.acquisition.rate_limiter as _rate_limiter
from app.services.acquisition.rate_limiter import (
    apply_protected_host_backoff,
    record_fetch_outcome,
    reset_pacing_state,
    wait_for_host_slot,
)

asyncio = _rate_limiter.asyncio
crawler_runtime_settings = _rate_limiter.crawler_runtime_settings

__all__ = [
    "apply_protected_host_backoff",
    "asyncio",
    "crawler_runtime_settings",
    "record_fetch_outcome",
    "reset_pacing_state",
    "wait_for_host_slot",
]

