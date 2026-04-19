from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.config.runtime_settings import crawler_runtime_settings


@dataclass(slots=True)
class AcquisitionPlan:
    surface: str
    proxy_list: tuple[str, ...] = ()
    traversal_mode: str | None = None
    max_pages: int = crawler_runtime_settings.default_max_pages
    max_scrolls: int = crawler_runtime_settings.default_max_scrolls
    max_records: int = crawler_runtime_settings.default_max_records
    sleep_ms: int = crawler_runtime_settings.min_request_delay_ms
    adapter_recovery_enabled: bool = False

    def with_updates(self, **updates: object) -> "AcquisitionPlan":
        return replace(self, **updates)
