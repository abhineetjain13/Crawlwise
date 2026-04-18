from __future__ import annotations

from dataclasses import dataclass

SCHEMA_MAX_AGE_DAYS = 30
LISTING_FALLBACK_FRAGMENT_LIMIT: int = 200
SECTION_PATTERNS: dict[str, list[str]] = {
    "responsibilities": ["what you", "responsibil"],
    "qualifications": ["should have", "qualif", "who you are"],
    "benefits": ["benefit", "perks", "what we offer"],
    "skills": ["skill", "bring"],
}


class PipelineDefaults:
    MAX_PAGES: int = 5
    MAX_SCROLLS: int = 3
    MAX_RECORDS: int = 100
    SLEEP_MS: int = 0


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
