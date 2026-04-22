from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TypedDict, Unpack

from app.services.config.runtime_settings import crawler_runtime_settings


class AcquisitionPlanUpdates(TypedDict, total=False):
    surface: str
    proxy_list: tuple[str, ...]
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    max_records: int
    sleep_ms: int
    adapter_recovery_enabled: bool


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

    def with_updates(self, **updates: Unpack[AcquisitionPlanUpdates]) -> "AcquisitionPlan":
        return replace(self, **updates)
