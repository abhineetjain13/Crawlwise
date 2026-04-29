from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.surface_hints import GENERIC_PLATFORM_URL_TOKENS, surface_group
from app.services.domain_utils import normalize_domain

logger = logging.getLogger(__name__)
_DEFAULT_ADAPTER_ORDER = (
    "amazon",
    "walmart",
    "ebay",
    "shopify",
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
    readiness_selectors: list[str] = Field(default_factory=list)
    readiness_max_wait_ms: int = 0
    network_signature_patterns: list[str] = Field(default_factory=list)
    path_tenant_boundary: bool = False
    js_state_extractors: list["JSStateExtractorConfig"] = Field(default_factory=list)


class JSStateExtractorConfig(BaseModel):
    surface: str
    state_keys: list[str] = Field(default_factory=list)
    root_paths: dict[str, list[list[str]]] = Field(default_factory=dict)
    field_paths: dict[str, list[list[str]]] = Field(default_factory=dict)
    field_jmespaths: dict[str, str | list[str]] = Field(default_factory=dict)


class PlatformRegistryDocument(BaseModel):
    platforms: list[PlatformConfig] = Field(default_factory=list)


def _platforms_path() -> Path:
    return Path(__file__).with_name("config").joinpath("platforms.json")


@lru_cache(maxsize=1)
def _load_platform_registry() -> PlatformRegistryDocument:
    payload = json.loads(_platforms_path().read_text(encoding="utf-8"))
    return PlatformRegistryDocument.model_validate(payload)


def platform_configs() -> list[PlatformConfig]:
    return list(_load_platform_registry().platforms)


def _normalize_patterns(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value and value.strip()]


def _matches_domain(host: str, pattern: str) -> bool:
    normalized_host = normalize_domain(host)
    normalized_pattern = normalize_domain(pattern)
    if not normalized_host or not normalized_pattern:
        return False
    return normalized_host == normalized_pattern or normalized_host.endswith(
        f".{normalized_pattern}"
    )


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


def browser_first_domains() -> list[str]:
    values = {
        normalize_domain(pattern)
        for config in platform_configs()
        if bool(config.requires_browser)
        for pattern in config.domain_patterns
        if normalize_domain(pattern)
    }
    return sorted(values)


def configured_adapter_names() -> tuple[str, ...]:
    ordered_names: list[str] = []
    for config in platform_configs():
        for adapter_name in config.adapter_names:
            normalized = str(adapter_name or "").strip().lower()
            if normalized and normalized not in ordered_names:
                ordered_names.append(normalized)
    for adapter_name in _DEFAULT_ADAPTER_ORDER:
        if adapter_name not in ordered_names:
            ordered_names.append(adapter_name)
    return tuple(ordered_names)


def acquisition_hint_tokens() -> tuple[str, ...]:
    tokens = {
        token.strip().lower().strip("/")
        for config in platform_configs()
        for token in [
            *config.domain_patterns,
            *config.url_contains,
            *config.adapter_names,
        ]
        if token and token.strip()
    }
    return tuple(sorted(token for token in tokens if len(token) >= 3))


def platform_config_for_family(
    family: str | None,
) -> PlatformConfig | None:
    normalized = str(family or "").strip().lower()
    if not normalized:
        return None
    for config in platform_configs():
        if str(config.family or "").strip().lower() == normalized:
            return config
    return None


def classify_network_endpoint_family(response_url: str) -> str:
    lowered_url = str(response_url or "").strip().lower()
    if not lowered_url:
        return "generic"
    for config in platform_configs():
        for pattern in _normalize_patterns(config.network_signature_patterns):
            if pattern and pattern in lowered_url:
                return config.family
    return "generic"


def platform_js_state_extractors(
    *,
    surface: str,
    state_key: str,
) -> list[JSStateExtractorConfig]:
    normalized_surface = str(surface or "").strip().lower()
    normalized_state_key = str(state_key or "").strip()
    if not normalized_surface or not normalized_state_key:
        return []
    extractors: list[JSStateExtractorConfig] = []
    for config in platform_configs():
        for extractor in config.js_state_extractors:
            if str(extractor.surface or "").strip().lower() != normalized_surface:
                continue
            extractor_state_keys = [str(k or "").strip() for k in extractor.state_keys]
            if normalized_state_key in extractor_state_keys:
                extractors.append(extractor)
    return extractors


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
    normalized_html = str(html or "").lower()[:_platform_detection_html_search_limit()]
    domain = normalize_domain(urlparse(normalized_url).netloc)

    for config in platform_configs():
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if any(_matches_domain(domain, pattern) for pattern in domain_patterns):
            return config.family

    for config in platform_configs():
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if domain_patterns and not any(
            _matches_domain(domain, pattern) for pattern in domain_patterns
        ):
            continue
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
        if domain_patterns and not any(
            _matches_domain(domain, pattern) for pattern in domain_patterns
        ):
            continue
        if any(pattern in normalized_url for pattern in url_patterns):
            return config.family

    if any(token in normalized_url for token in GENERIC_PLATFORM_URL_TOKENS["job"]):
        return "generic_jobs"
    if any(token in normalized_url for token in GENERIC_PLATFORM_URL_TOKENS["ecommerce"]):
        return "generic_commerce"
    return None


def resolve_listing_readiness_platform(url: str) -> str | None:
    normalized_url = str(url or "").strip().lower()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url)
    host = normalize_domain(parsed.netloc)
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


def _platform_detection_html_search_limit() -> int:
    return max(1, int(crawler_runtime_settings.platform_detection_html_search_limit))


def platform_domain_patterns(family: str | None) -> tuple[str, ...]:
    config = platform_config_for_family(family)
    if config is None:
        return ()
    return tuple(_normalize_patterns(config.domain_patterns))


def url_host_matches_platform_family(url: str | None, family: str | None) -> bool:
    host = normalize_domain(urlparse(str(url or "")).netloc)
    if not host:
        return False
    return any(_matches_domain(host, pattern) for pattern in platform_domain_patterns(family))


def requires_path_tenant_boundary_for_family(family: str | None) -> bool:
    config = platform_config_for_family(family)
    return bool(config.path_tenant_boundary) if config is not None else False


def requires_path_tenant_boundary(url: str | None) -> bool:
    family = detect_platform_family(str(url or ""))
    return requires_path_tenant_boundary_for_family(family)


def path_tenant_boundary_family(url: str | None) -> str | None:
    family = detect_platform_family(str(url or ""))
    if not requires_path_tenant_boundary_for_family(family):
        return None
    return family


def resolve_listing_readiness_override(url: str) -> dict[str, Any] | None:
    family = resolve_listing_readiness_platform(url)
    config = platform_config_for_family(family)
    if config is None:
        return None
    selectors = [
        str(selector or "").strip()
        for selector in list(config.readiness_selectors or [])
        if str(selector or "").strip()
    ]
    if not selectors:
        return None
    parsed = urlparse(str(url or "").strip().lower())
    return {
        "platform": family,
        "domain": str(parsed.netloc or "").strip(),
        "selectors": selectors,
        "max_wait_ms": int(config.readiness_max_wait_ms or 0),
    }


def resolve_browser_readiness_policy(
    url: str,
    *,
    surface: str | None = None,
    traversal_active: bool = False,
) -> dict[str, Any]:
    listing_override = resolve_listing_readiness_override(url)
    normalized_surface = str(surface or "").strip().lower()
    detail_surface = normalized_surface.endswith("_detail")
    if traversal_active:
        networkidle_reason = "traversal"
    elif listing_override is not None:
        networkidle_reason = "platform-readiness"
    elif detail_surface:
        networkidle_reason = "detail-surface"
    else:
        networkidle_reason = None
    require_networkidle = bool(
        listing_override is not None or traversal_active or detail_surface
    )
    return {
        "listing_override": listing_override,
        "require_networkidle": require_networkidle,
        "networkidle_reason": networkidle_reason,
        "navigation_wait_until": "domcontentloaded",
    }


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


def _resolve_http_browser_escalation_policy(surface: str | None) -> dict[str, bool]:
    normalized_surface = str(surface or "").strip().lower()
    group = surface_group(normalized_surface)
    return {
        "js_shell_without_detail_signals": True,
        "missing_detail_signals": bool(group and normalized_surface.endswith("_detail")),
        "listing_shell_without_listing_signals": bool(
            group and normalized_surface.endswith("_listing")
        ),
    }


def resolve_platform_runtime_policy(
    url: str,
    html: str = "",
    *,
    surface: str | None = None,
) -> dict[str, Any]:
    family = detect_platform_family(url, html)
    config = platform_config_for_family(family)
    return {
        "family": family,
        "requires_browser": bool(config.requires_browser) if config else False,
        "proxy_policy": config.proxy_policy if config else None,
        "http_browser_escalation": _resolve_http_browser_escalation_policy(surface),
    }
