from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.acquisition_plan import AcquisitionPlan
from app.services.crawl_utils import normalize_target_url, resolve_traversal_mode
from app.services.config.crawl_runtime import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_SCROLLS,
    MAX_MAX_PAGES,
    MIN_MAX_PAGES,
    MIN_REQUEST_DELAY_MS,
    URL_BATCH_CONCURRENCY,
    URL_PROCESS_TIMEOUT_SECONDS,
    coerce_url_timeout_seconds,
)


def _coerce_int(
    value: object, default: int, minimum: int, maximum: int | None = None
) -> int:
    try:
        result = max(minimum, int(str(value)))
        if maximum is not None:
            result = min(result, maximum)
        return result
    except (TypeError, ValueError):
        return default


def _coerce_sequence(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


@dataclass(slots=True)
class CrawlRunSettings:
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> CrawlRunSettings:
        if isinstance(value, Mapping):
            return cls(dict(value))
        return cls({})

    def as_dict(self) -> dict[str, Any]:
        return dict(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.data

    def urls(self) -> list[str]:
        return [
            normalize_target_url(value)
            for value in _coerce_sequence(self.data.get("urls"))
        ]

    def proxy_list(self) -> list[str]:
        values = []
        for value in _coerce_sequence(self.data.get("proxy_list")):
            text = str(value or "").strip()
            if text:
                values.append(text)
        return values

    def traversal_mode(self) -> str | None:
        return resolve_traversal_mode(self.data)

    def advanced_enabled(self) -> bool:
        return bool(self.data.get("advanced_enabled"))

    def max_pages(self) -> int:
        return _coerce_int(
            self.data.get("max_pages", DEFAULT_MAX_PAGES),
            DEFAULT_MAX_PAGES,
            MIN_MAX_PAGES,
            MAX_MAX_PAGES,
        )

    def max_records(self) -> int:
        return _coerce_int(self.data.get("max_records", 100), 100, 1)

    def max_scrolls(self) -> int:
        return _coerce_int(
            self.data.get("max_scrolls", DEFAULT_MAX_SCROLLS), DEFAULT_MAX_SCROLLS, 1
        )

    def respect_robots_txt(self) -> bool:
        if "respect_robots_txt" not in self.data:
            return False
        return bool(self.data.get("respect_robots_txt"))

    def sleep_ms(self) -> int:
        return _coerce_int(
            self.data.get("sleep_ms", MIN_REQUEST_DELAY_MS),
            MIN_REQUEST_DELAY_MS,
            MIN_REQUEST_DELAY_MS,
        )

    def url_batch_concurrency(self) -> int:
        return _coerce_int(
            self.data.get("url_batch_concurrency", URL_BATCH_CONCURRENCY),
            URL_BATCH_CONCURRENCY,
            1,
        )

    def url_timeout_seconds(self) -> float:
        return coerce_url_timeout_seconds(
            self.data.get("url_timeout_seconds", URL_PROCESS_TIMEOUT_SECONDS)
        )

    def llm_enabled(self) -> bool:
        return bool(self.data.get("llm_enabled"))

    def llm_config_snapshot(self) -> dict[str, Any]:
        snapshot = self.data.get("llm_config_snapshot")
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}

    def has_llm_config_snapshot(self) -> bool:
        return bool(self.llm_config_snapshot())

    def extraction_runtime_snapshot(self) -> dict[str, Any]:
        snapshot = self.data.get("extraction_runtime_snapshot")
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}

    def extraction_contract(self) -> list[dict[str, Any]]:
        rows = self.data.get("extraction_contract")
        if not isinstance(rows, Sequence) or isinstance(rows, str):
            return []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def acquisition_profile(self) -> dict[str, object]:
        profile: dict[str, object] = {}
        for key in ("ignore_https_errors", "bypass_csp"):
            if key in self.data:
                profile[key] = bool(self.data.get(key))
        return profile

    def acquisition_plan(
        self,
        *,
        surface: str,
        max_records: int | None = None,
        adapter_recovery_enabled: bool = False,
    ) -> AcquisitionPlan:
        return AcquisitionPlan(
            surface=str(surface or "").strip(),
            proxy_list=tuple(self.proxy_list()),
            traversal_mode=self.traversal_mode(),
            max_pages=self.max_pages(),
            max_scrolls=self.max_scrolls(),
            max_records=max_records if max_records is not None else self.max_records(),
            sleep_ms=self.sleep_ms(),
            adapter_recovery_enabled=adapter_recovery_enabled,
        )

    def with_updates(self, **updates: Any) -> CrawlRunSettings:
        merged = dict(self.data)
        merged.update(updates)
        return CrawlRunSettings(merged)

    def normalized_for_storage(self) -> dict[str, Any]:
        normalized = dict(self.data)
        normalized["urls"] = self.urls()
        normalized["max_pages"] = self.max_pages()
        normalized["max_records"] = self.max_records()
        normalized["max_scrolls"] = self.max_scrolls()
        normalized["sleep_ms"] = self.sleep_ms()
        normalized["respect_robots_txt"] = self.respect_robots_txt()
        normalized["traversal_mode"] = self.traversal_mode()
        normalized["advanced_mode"] = (
            normalized["traversal_mode"] if self.advanced_enabled() else None
        )
        return normalized


def normalize_crawl_settings(value: object) -> dict[str, Any]:
    return CrawlRunSettings.from_value(value).normalized_for_storage()
