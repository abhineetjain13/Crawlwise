from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.config.crawl_runtime import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_SCROLLS,
    MIN_REQUEST_DELAY_MS,
)


@dataclass(slots=True)
class AcquisitionPlan:
    surface: str
    proxy_list: tuple[str, ...] = ()
    traversal_mode: str | None = None
    max_pages: int = DEFAULT_MAX_PAGES
    max_scrolls: int = DEFAULT_MAX_SCROLLS
    max_records: int = 100
    sleep_ms: int = MIN_REQUEST_DELAY_MS
    adapter_recovery_enabled: bool = False

    def with_updates(self, **updates: object) -> "AcquisitionPlan":
        return replace(self, **updates)
