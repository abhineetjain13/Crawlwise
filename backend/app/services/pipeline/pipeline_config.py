from __future__ import annotations

from dataclasses import dataclass

from app.services.config.runtime_settings import crawler_runtime_settings

SCHEMA_MAX_AGE_DAYS = 30
LISTING_FALLBACK_FRAGMENT_LIMIT: int = 200


class PipelineDefaults:
    MAX_PAGES: int = crawler_runtime_settings.default_max_pages
    MAX_SCROLLS: int = crawler_runtime_settings.default_max_scrolls
    MAX_RECORDS: int = crawler_runtime_settings.default_max_records
    SLEEP_MS: int = crawler_runtime_settings.default_sleep_ms


class LLMFallbackConfig:
    CONFIDENCE_THRESHOLD: float = 0.55


class FingerprintConfig:
    browser: str = "chrome"
    os: tuple[str, ...] = ("windows", "macos", "linux")
    device: str = "desktop"
    locale: str = "en-US"


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    robots_cache_size: int = 512
    robots_cache_ttl: float = 3600.0
    robots_fetch_user_agent: str = "CrawlerAI"


PIPELINE_CONFIG = PipelineConfig()
