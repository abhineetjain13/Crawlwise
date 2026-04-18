from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(slots=True)
class URLProcessingResult:
    records: list[dict] = field(default_factory=list)
    verdict: str = ""
    url_metrics: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator:
        return iter((self.records, self.verdict, self.url_metrics))

    def __len__(self) -> int:
        return 3


@dataclass(slots=True)
class URLProcessingConfig:
    proxy_list: list[str] = field(default_factory=list)
    traversal_mode: str | None = None
    max_pages: int = 5
    max_scrolls: int = 3
    max_records: int = 100
    sleep_ms: int = 0
    update_run_state: bool = True
    persist_logs: bool = True
    prefetch_only: bool = False
    record_writer: object | None = None
