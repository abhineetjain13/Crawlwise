# Platform-family resolver for advisory diagnostics and future family adapters.
from __future__ import annotations

from urllib.parse import urlparse

from app.services.pipeline_config import PLATFORM_FAMILY_RULES


def resolve_platform_family(url: str, html: str = "") -> str | None:
    normalized_url = str(url or "").strip().lower()
    normalized_html = str(html or "").lower()
    domain = urlparse(normalized_url).netloc.lower().replace("www.", "")

    domain_rules = PLATFORM_FAMILY_RULES.get("domain_rules", {})
    for family, patterns in domain_rules.items():
        if any(pattern and pattern in domain for pattern in _normalize_patterns(patterns)):
            return str(family)

    url_rules = PLATFORM_FAMILY_RULES.get("url_contains_rules", {})
    for family, patterns in url_rules.items():
        if any(pattern and pattern in normalized_url for pattern in _normalize_patterns(patterns)):
            return str(family)

    html_rules = PLATFORM_FAMILY_RULES.get("html_contains_rules", {})
    for family, patterns in html_rules.items():
        if any(pattern and pattern in normalized_html for pattern in _normalize_patterns(patterns)):
            return str(family)

    generic_rules = PLATFORM_FAMILY_RULES.get("generic_rules", {})
    jobs_tokens = _normalize_patterns(generic_rules.get("jobs_url_tokens", []))
    if any(token and token in normalized_url for token in jobs_tokens):
        return "generic_jobs"

    commerce_tokens = _normalize_patterns(generic_rules.get("commerce_url_tokens", []))
    if any(token and token in normalized_url for token in commerce_tokens):
        return "generic_commerce"

    return None


def _normalize_patterns(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value or "").strip().lower() for value in values if str(value or "").strip()]
