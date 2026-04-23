from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.acquisition_plan import AcquisitionPlan
from app.services.crawl_utils import normalize_target_url, resolve_traversal_mode
from app.services.config.runtime_settings import crawler_runtime_settings


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


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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

    def fetch_profile(self) -> dict[str, object]:
        stored = _mapping(self.data.get("fetch_profile"))
        if stored:
            return {
                "fetch_mode": str(stored.get("fetch_mode") or "auto").strip().lower() or "auto",
                "extraction_source": str(stored.get("extraction_source") or "raw_html").strip().lower() or "raw_html",
                "js_mode": str(stored.get("js_mode") or "auto").strip().lower() or "auto",
                "include_iframes": bool(stored.get("include_iframes", False)),
                "traversal_mode": str(stored.get("traversal_mode") or "auto").strip().lower() or "auto",
                "request_delay_ms": self.sleep_ms(),
                "max_pages": self.max_pages(),
                "max_scrolls": self.max_scrolls(),
            }
        traversal_mode = self.traversal_mode()
        return {
            "fetch_mode": "auto",
            "extraction_source": "raw_html",
            "js_mode": "auto",
            "include_iframes": False,
            "traversal_mode": traversal_mode or "auto",
            "request_delay_ms": self.sleep_ms(),
            "max_pages": self.max_pages(),
            "max_scrolls": self.max_scrolls(),
        }

    def locality_profile(self) -> dict[str, object]:
        stored = _mapping(self.data.get("locality_profile"))
        return {
            "geo_country": str(stored.get("geo_country") or "auto").strip() or "auto",
            "language_hint": str(stored.get("language_hint") or "").strip() or None,
            "currency_hint": str(stored.get("currency_hint") or "").strip() or None,
        }

    def diagnostics_profile(self) -> dict[str, object]:
        stored = _mapping(self.data.get("diagnostics_profile"))
        capture_network = str(stored.get("capture_network") or "off").strip().lower() or "off"
        return {
            "capture_html": bool(stored.get("capture_html", True)),
            "capture_screenshot": bool(stored.get("capture_screenshot", False)),
            "capture_network": capture_network,
            "capture_response_headers": bool(
                stored.get("capture_response_headers", True)
            ),
            "capture_browser_diagnostics": bool(
                stored.get("capture_browser_diagnostics", True)
            ),
        }

    def advanced_enabled(self) -> bool:
        return bool(self.data.get("advanced_enabled"))

    def max_pages(self) -> int:
        fetch_profile = _mapping(self.data.get("fetch_profile"))
        return _coerce_int(
            fetch_profile.get(
                "max_pages",
                self.data.get("max_pages", crawler_runtime_settings.default_max_pages),
            ),
            crawler_runtime_settings.default_max_pages,
            crawler_runtime_settings.min_max_pages,
            crawler_runtime_settings.max_max_pages,
        )

    def max_records(self) -> int:
        return _coerce_int(
            self.data.get("max_records", crawler_runtime_settings.default_max_records),
            crawler_runtime_settings.default_max_records,
            1,
        )

    def max_scrolls(self) -> int:
        fetch_profile = _mapping(self.data.get("fetch_profile"))
        return _coerce_int(
            fetch_profile.get(
                "max_scrolls",
                self.data.get(
                    "max_scrolls",
                    crawler_runtime_settings.default_max_scrolls,
                ),
            ),
            crawler_runtime_settings.default_max_scrolls,
            1,
        )

    def respect_robots_txt(self) -> bool:
        if "respect_robots_txt" not in self.data:
            return False
        return bool(self.data.get("respect_robots_txt"))

    def sleep_ms(self) -> int:
        fetch_profile = _mapping(self.data.get("fetch_profile"))
        return _coerce_int(
            fetch_profile.get(
                "request_delay_ms",
                self.data.get(
                    "request_delay_ms",
                    self.data.get(
                        "sleep_ms",
                        crawler_runtime_settings.min_request_delay_ms,
                    ),
                ),
            ),
            crawler_runtime_settings.min_request_delay_ms,
            crawler_runtime_settings.min_request_delay_ms,
        )

    def url_batch_concurrency(self) -> int:
        return _coerce_int(
            self.data.get(
                "url_batch_concurrency",
                crawler_runtime_settings.url_batch_concurrency,
            ),
            crawler_runtime_settings.url_batch_concurrency,
            1,
        )

    def url_timeout_seconds(self) -> float:
        return crawler_runtime_settings.coerce_url_timeout_seconds(
            self.data.get(
                "url_timeout_seconds",
                crawler_runtime_settings.url_process_timeout_seconds,
            )
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
        fetch_profile = self.fetch_profile()
        diagnostics_profile = self.diagnostics_profile()
        profile.update(
            {
                "fetch_mode": fetch_profile["fetch_mode"],
                "extraction_source": fetch_profile["extraction_source"],
                "js_mode": fetch_profile["js_mode"],
                "include_iframes": fetch_profile["include_iframes"],
                "capture_html": diagnostics_profile["capture_html"],
                "capture_screenshot": diagnostics_profile["capture_screenshot"],
                "capture_network": diagnostics_profile["capture_network"],
                "capture_response_headers": diagnostics_profile["capture_response_headers"],
                "capture_browser_diagnostics": diagnostics_profile["capture_browser_diagnostics"],
            }
        )
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
        normalized["max_records"] = self.max_records()
        normalized["respect_robots_txt"] = self.respect_robots_txt()
        normalized["fetch_profile"] = self.fetch_profile()
        normalized["locality_profile"] = self.locality_profile()
        normalized["diagnostics_profile"] = self.diagnostics_profile()
        normalized["max_pages"] = self.max_pages()
        normalized["max_scrolls"] = self.max_scrolls()
        normalized["sleep_ms"] = self.sleep_ms()
        normalized["request_delay_ms"] = self.sleep_ms()
        normalized["traversal_mode"] = self.traversal_mode()
        if self.advanced_enabled():
            normalized["advanced_mode"] = self.get("advanced_mode")
        elif "advanced_mode" in normalized:
            normalized["advanced_mode"] = None
        return normalized


def normalize_crawl_settings(value: object) -> dict[str, Any]:
    return CrawlRunSettings.from_value(value).normalized_for_storage()
