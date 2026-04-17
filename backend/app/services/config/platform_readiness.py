from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.platform_policy import (
    listing_readiness_domains,
    resolve_listing_readiness_platform,
)
from pydantic import BaseModel, Field


class PlatformReadinessConfig(BaseModel):
    selectors: list[str] = Field(default_factory=list)
    max_wait_ms: int = 0


class PlatformReadinessDocument(BaseModel):
    version: int = 1
    families: dict[str, PlatformReadinessConfig] = Field(default_factory=dict)


def _platform_readiness_path() -> Path:
    return Path(__file__).with_name("platform_readiness.json")


@lru_cache(maxsize=1)
def load_platform_readiness() -> PlatformReadinessDocument:
    payload = json.loads(_platform_readiness_path().read_text(encoding="utf-8"))
    return PlatformReadinessDocument.model_validate(payload)


def readiness_selectors_by_family() -> dict[str, list[str]]:
    return {
        family: list(config.selectors)
        for family, config in load_platform_readiness().families.items()
    }


def readiness_max_wait_by_family() -> dict[str, int]:
    return {
        family: int(config.max_wait_ms or 0)
        for family, config in load_platform_readiness().families.items()
    }


PLATFORM_LISTING_READINESS_SELECTORS: dict[str, list[str]] = readiness_selectors_by_family()
PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES: dict[str, int] = readiness_max_wait_by_family()
LISTING_READINESS_OVERRIDES: dict[str, dict[str, object]] = {
    key: {
        "platform": platform,
        "selectors": list(PLATFORM_LISTING_READINESS_SELECTORS.get(platform) or []),
        "max_wait_ms": int(
            PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES.get(platform, 0) or 0
        ),
    }
    for platform, domains in listing_readiness_domains().items()
    for key in [platform, *domains]
}


def resolve_listing_readiness_override(page_url: str) -> dict[str, Any] | None:
    """Return readiness selectors for the platform family matched to this URL."""
    platform = resolve_listing_readiness_platform(page_url)
    if not platform:
        return None
    selectors = list(PLATFORM_LISTING_READINESS_SELECTORS.get(platform) or [])
    if not selectors:
        return None
    return {
        "platform": platform,
        "domain": str(urlparse(str(page_url or "").strip().lower()).netloc or "").strip(),
        "selectors": selectors,
        "max_wait_ms": int(
            PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES.get(platform, 0) or 0
        ),
    }
