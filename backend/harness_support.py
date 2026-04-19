from __future__ import annotations

import html
from pathlib import Path

from app.services.platform_policy import (
    configured_adapter_names,
    detect_platform_family,
    job_platform_families,
    platform_config_for_family,
)
from app.services.adapters.registry import registered_adapters

_DETAIL_HINTS = (
    "/products/",
    "/product/",
    "/p/",
    "/dp/",
    "/job/",
    "/viewjob",
)
_LISTING_HINTS = (
    "/collections",
    "/shop/",
    "/category/",
    "/careers",
    "/jobs",
    "job-search",
    "career-page",
    "jobboard",
    "recruitment",
    "currentopenings",
)
_JOB_LISTING_HINTS = (
    "/jobs",
    "/careers",
    "job-search",
    "career-page",
    "jobboard",
    "recruitment",
    "currentopenings",
    "searchrelation=",
    "mode=location",
    "sortby=",
    "page=",
)


def infer_surface(url: str, explicit_surface: object | None = None) -> str:
    explicit = str(explicit_surface or "").strip().lower()
    if explicit:
        return explicit
    normalized_url = str(url or "").strip().lower()
    family = detect_platform_family(normalized_url)
    if family in job_platform_families():
        if any(token in normalized_url for token in _JOB_LISTING_HINTS):
            return "job_listing"
        if any(token in normalized_url for token in ("/job/", "/viewjob")):
            return "job_detail"
        return "job_listing"
    if any(token in normalized_url for token in _JOB_LISTING_HINTS):
        return "job_listing"
    if any(token in normalized_url for token in _DETAIL_HINTS):
        return "job_detail" if "/job" in normalized_url else "ecommerce_detail"
    if any(token in normalized_url for token in _LISTING_HINTS):
        return "job_listing" if "job" in normalized_url or "career" in normalized_url else "ecommerce_listing"
    return "ecommerce_listing"


def parse_test_sites_markdown(path: Path, *, start_line: int) -> list[dict[str, str]]:
    if not isinstance(start_line, int) or start_line < 1:
        raise ValueError("parse_test_sites_markdown start_line must be an integer >= 1")
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[start_line - 1 :]:
        value = html.unescape(str(line or "").strip())
        if not value or not value.startswith(("http://", "https://")):
            continue
        rows.append({"name": value, "url": value, "surface": infer_surface(value)})
    return rows


def unavailable_configured_adapters() -> set[str]:
    configured = set(configured_adapter_names())
    registered = {adapter.name for adapter in registered_adapters()}
    return configured - registered


def classify_failure_mode(result: dict[str, object]) -> str:
    if result.get("ok"):
        return "success"
    error_text = str(result.get("error") or "").lower()
    if "getaddrinfo failed" in error_text:
        return "dns_or_network_failure"
    if "chrome-error://chromewebdata/" in error_text:
        return "browser_navigation_failure"
    if result.get("blocked"):
        return "blocked"
    family = str(result.get("platform_family") or "").strip().lower()
    config = platform_config_for_family(family)
    expected_adapters = {
        str(name).strip().lower()
        for name in (config.adapter_names if config else [])
        if str(name or "").strip()
    }
    missing_registrations = unavailable_configured_adapters()
    if expected_adapters and expected_adapters.issubset(missing_registrations):
        return "adapter_not_registered"
    if expected_adapters and not result.get("adapter_name"):
        return "adapter_not_matched"
    if family and not expected_adapters and str(result.get("surface") or "").startswith("job_"):
        return "platform_family_without_adapter"
    if _safe_int(result.get("adapter_records")) == 0 and _safe_int(result.get("records")) == 0:
        if str(result.get("surface") or "").endswith("_listing"):
            return "listing_extraction_empty"
        return "detail_extraction_empty"
    return "unknown_failure"


def _safe_int(value: object) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(str(value))
    except (TypeError, ValueError):
        return 0
