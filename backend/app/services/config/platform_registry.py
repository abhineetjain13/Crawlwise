from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


_GENERIC_JOB_TOKENS = (
    "/jobs",
    "/careers",
    "/career",
    "job-search",
    "jobboard",
    "recruitment",
    "currentopenings",
)
_GENERIC_COMMERCE_TOKENS = (
    "/product",
    "/product/",
    "/products/",
    "/shop/",
    "/collections/",
)


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


def _normalize_patterns(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value and value.strip()]


def _normalize_domain(value: str) -> str:
    return str(value or "").strip().lower().removeprefix("www.")


def _matches_domain(host: str, pattern: str) -> bool:
    normalized_host = _normalize_domain(host)
    normalized_pattern = _normalize_domain(pattern)
    if not normalized_host or not normalized_pattern:
        return False
    return normalized_host == normalized_pattern or normalized_host.endswith(f".{normalized_pattern}")


def platform_family_names() -> set[str]:
    return {config.family for config in platform_configs() if config.family}


def job_platform_families() -> set[str]:
    return {
        config.family
        for config in platform_configs()
        if config.family and bool(config.job_platform)
    }


def known_job_adapter_names() -> set[str]:
    names: set[str] = set()
    for config in platform_configs():
        if not config.job_platform:
            continue
        if config.family:
            normalized_family = str(config.family).strip().lower()
            if normalized_family:
                names.add(normalized_family)
        for name in config.adapter_names:
            normalized = str(name or "").strip().lower()
            if normalized:
                names.add(normalized)
    return names


def known_ats_domains() -> list[str]:
    values = {
        pattern.strip().lower()
        for config in platform_configs()
        if config.job_platform
        for pattern in config.domain_patterns
        if pattern and pattern.strip()
    }
    return sorted(values)


def browser_first_platform_families() -> set[str]:
    return {
        config.family
        for config in platform_configs()
        if config.family and bool(config.requires_browser)
    }


def acquisition_hint_tokens() -> tuple[str, ...]:
    tokens = {
        token.strip().lower().strip("/")
        for config in platform_configs()
        for token in [*config.domain_patterns, *config.url_contains, *config.adapter_names]
        if token and token.strip()
    }
    return tuple(sorted(token for token in tokens if len(token) >= 3))


def platform_config_for_family(family: str | None) -> PlatformConfig | None:
    normalized = str(family or "").strip().lower()
    if not normalized:
        return None
    for config in platform_configs():
        if str(config.family or "").strip().lower() == normalized:
            return config
    return None


def is_job_platform_signal(
    platform_family: str | None = None,
    adapter_hint: str | None = None,
) -> bool:
    job_signals = known_job_adapter_names()
    normalized_family = str(platform_family or "").strip().lower()
    normalized_hint = str(adapter_hint or "").strip().lower()
    return normalized_family in job_signals or normalized_hint in job_signals


def detect_platform_family(url: str, html: str = "") -> str | None:
    normalized_url = str(url or "").strip().lower()
    normalized_html = str(html or "").lower()
    domain = _normalize_domain(urlparse(normalized_url).netloc)

    for config in platform_configs():
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if any(_matches_domain(domain, pattern) for pattern in domain_patterns):
            return config.family

    for config in platform_configs():
        html_patterns = _normalize_patterns(config.html_contains)
        if any(pattern in normalized_html for pattern in html_patterns):
            return config.family
        for pattern in config.html_regex:
            raw_pattern = str(pattern or "").strip()
            if not raw_pattern:
                continue
            try:
                if re.search(raw_pattern, normalized_html, re.IGNORECASE):
                    return config.family
            except re.error as exc:
                logger.warning(
                    "Skipping invalid platform html_regex for family=%s pattern=%r: %s",
                    config.family,
                    raw_pattern,
                    exc,
                )

    for config in platform_configs():
        url_patterns = _normalize_patterns(config.url_contains)
        if not url_patterns:
            continue
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if domain_patterns and not any(_matches_domain(domain, pattern) for pattern in domain_patterns):
            continue
        if any(pattern in normalized_url for pattern in url_patterns):
            return config.family

    if any(token in normalized_url for token in _GENERIC_JOB_TOKENS):
        return "generic_jobs"
    if any(token in normalized_url for token in _GENERIC_COMMERCE_TOKENS):
        return "generic_commerce"
    return None


def resolve_listing_readiness_platform(url: str) -> str | None:
    normalized_url = str(url or "").strip().lower()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url)
    host = _normalize_domain(parsed.netloc)
    path = str(parsed.path or "").strip().lower()
    if not host or not path:
        return None

    for config in platform_configs():
        readiness_domains = _normalize_patterns(config.readiness_domains)
        readiness_patterns = [
            str(pattern or "").strip().lower()
            for pattern in config.readiness_path_patterns
            if str(pattern or "").strip()
        ]
        if not readiness_domains or not readiness_patterns:
            continue
        if not any(_matches_domain(host, pattern) for pattern in readiness_domains):
            continue
        for pattern in readiness_patterns:
            try:
                if re.search(pattern, path, re.IGNORECASE):
                    return config.family
            except re.error as exc:
                logger.warning(
                    "Skipping invalid readiness path regex for family=%s pattern=%r: %s",
                    config.family,
                    pattern,
                    exc,
                )
    return None


def listing_readiness_domains() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for config in platform_configs():
        domains = _normalize_patterns(config.readiness_domains)
        if not domains or not config.family:
            continue
        existing = mapping.setdefault(config.family, [])
        for domain in domains:
            if domain not in existing:
                existing.append(domain)
    return mapping


def resolve_platform_runtime_policy(url: str, html: str = "") -> dict[str, Any]:
    family = detect_platform_family(url, html)
    config = platform_config_for_family(family)
    return {
        "family": family,
        "requires_browser": bool(config.requires_browser) if config else False,
        "proxy_policy": config.proxy_policy if config else None,
    }
