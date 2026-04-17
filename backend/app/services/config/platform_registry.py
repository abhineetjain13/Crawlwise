from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PlatformConfig(BaseModel):
    family: str
    domain_patterns: list[str] = Field(default_factory=list)
    url_contains: list[str] = Field(default_factory=list)
    html_contains: list[str] = Field(default_factory=list)
    html_regex: list[str] = Field(default_factory=list)
    adapter_names: list[str] = Field(default_factory=list)
    job_platform: bool = False
    requires_browser: bool = False
    proxy_policy: str | None = None
    readiness_domains: list[str] = Field(default_factory=list)
    readiness_path_patterns: list[str] = Field(default_factory=list)


class PlatformRegistryDocument(BaseModel):
    platforms: list[PlatformConfig] = Field(default_factory=list)


def _platforms_path() -> Path:
    return Path(__file__).with_name("platforms.json")


@lru_cache(maxsize=1)
def load_platform_registry() -> PlatformRegistryDocument:
    payload = json.loads(_platforms_path().read_text(encoding="utf-8"))
    return PlatformRegistryDocument.model_validate(payload)


def platform_configs() -> list[PlatformConfig]:
    return list(load_platform_registry().platforms)


def platform_family_names() -> set[str]:
    from app.services.platform_policy import platform_family_names as _platform_family_names

    return _platform_family_names()


def job_platform_families() -> set[str]:
    from app.services.platform_policy import job_platform_families as _job_platform_families

    return _job_platform_families()


def known_job_adapter_names() -> set[str]:
    from app.services.platform_policy import (
        known_job_adapter_names as _known_job_adapter_names,
    )

    return _known_job_adapter_names()


def known_ats_domains() -> list[str]:
    from app.services.platform_policy import known_ats_domains as _known_ats_domains

    return _known_ats_domains()


def browser_first_platform_families() -> set[str]:
    from app.services.platform_policy import (
        browser_first_platform_families as _browser_first_platform_families,
    )

    return _browser_first_platform_families()


def browser_first_domains() -> list[str]:
    from app.services.platform_policy import browser_first_domains as _browser_first_domains

    return _browser_first_domains()


def configured_adapter_names() -> tuple[str, ...]:
    from app.services.platform_policy import (
        configured_adapter_names as _configured_adapter_names,
    )

    return _configured_adapter_names()


def acquisition_hint_tokens() -> tuple[str, ...]:
    from app.services.platform_policy import (
        acquisition_hint_tokens as _acquisition_hint_tokens,
    )

    return _acquisition_hint_tokens()


def platform_config_for_family(family: str | None) -> PlatformConfig | None:
    from app.services.platform_policy import (
        platform_config_for_family as _platform_config_for_family,
    )

    return _platform_config_for_family(family)


def is_job_platform_signal(
    platform_family: str | None = None,
    adapter_hint: str | None = None,
) -> bool:
    from app.services.platform_policy import (
        is_job_platform_signal as _is_job_platform_signal,
    )

    return _is_job_platform_signal(
        platform_family=platform_family,
        adapter_hint=adapter_hint,
    )


def detect_platform_family(url: str, html: str = "") -> str | None:
    from app.services.platform_policy import (
        detect_platform_family as _detect_platform_family,
    )

    return _detect_platform_family(url, html)


def resolve_listing_readiness_platform(url: str) -> str | None:
    from app.services.platform_policy import (
        resolve_listing_readiness_platform as _resolve_listing_readiness_platform,
    )

    return _resolve_listing_readiness_platform(url)


def listing_readiness_domains() -> dict[str, list[str]]:
    from app.services.platform_policy import (
        listing_readiness_domains as _listing_readiness_domains,
    )

    return _listing_readiness_domains()


def resolve_platform_runtime_policy(url: str, html: str = "") -> dict[str, Any]:
    from app.services.platform_policy import (
        resolve_platform_runtime_policy as _resolve_platform_runtime_policy,
    )

    return _resolve_platform_runtime_policy(url, html)
