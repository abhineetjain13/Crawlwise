from __future__ import annotations

from app.services.config.runtime_settings import crawler_runtime_settings

LONG_RUN_THRESHOLD_SECONDS = 30 * 60
MAX_DURATION_SAMPLE_SIZE = 1000
STALLED_RUN_THRESHOLD_SECONDS = 2 * 60
STEALTH_MIN_TTL_HOURS = 1

__all__ = [
    "LONG_RUN_THRESHOLD_SECONDS",
    "MAX_DURATION_SAMPLE_SIZE",
    "STALLED_RUN_THRESHOLD_SECONDS",
    "STEALTH_MIN_TTL_HOURS",
    "coerce_url_timeout_seconds",
    "crawler_runtime_settings",
]


def coerce_url_timeout_seconds(value: object) -> float:
    return crawler_runtime_settings.coerce_url_timeout_seconds(value)
