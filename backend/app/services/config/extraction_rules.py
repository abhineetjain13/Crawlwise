from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.platform_policy import known_ats_domains

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")


@lru_cache(maxsize=1)
def _static_exports() -> dict[str, Any]:
    return load_export_data(str(_EXPORTS_PATH))


def _acquisition_guard_export(rule_name: str) -> frozenset[object]:
    rules = _static_exports().get("ACQUISITION_GUARDS_RULES", {})
    values = rules.get(rule_name, []) if isinstance(rules, dict) else []
    return frozenset(
        values if isinstance(values, (list, tuple, set, frozenset)) else []
    )


_STATIC_EXPORTS = {
    name: value
    for name, value in _static_exports().items()
    if not name.startswith("_")
}
globals().update(_STATIC_EXPORTS)

LISTING_STRUCTURE_POSITIVE_HINTS = (
    "card",
    "item",
    "listing",
    "product",
    "result",
    "tile",
    "record",
    "entry",
)
LISTING_STRUCTURE_NEGATIVE_HINTS = (
    "nav",
    "menu",
    "header",
    "footer",
    "breadcrumb",
    "toolbar",
    "filter",
    "sort",
    "sidebar",
    "pagination",
)
LISTING_FALLBACK_CONTAINER_SELECTOR = "article, li, div, tr, section, [role='row']"

DYNAMIC_FIELD_NAME_MAX_TOKENS = crawler_runtime_settings.dynamic_field_name_max_tokens
KNOWN_ATS_PLATFORMS = known_ats_domains
MAX_CANDIDATES_PER_FIELD = crawler_runtime_settings.max_candidates_per_field
JOB_REDIRECT_SHELL_TITLES = _acquisition_guard_export("job_redirect_shell_titles")
JOB_REDIRECT_SHELL_CANONICAL_URLS = _acquisition_guard_export(
    "job_redirect_shell_canonical_urls"
)
JOB_REDIRECT_SHELL_HEADINGS = _acquisition_guard_export("job_redirect_shell_headings")
JOB_ERROR_PAGE_TITLES = _acquisition_guard_export("job_error_page_titles")
JOB_ERROR_PAGE_HEADINGS = _acquisition_guard_export("job_error_page_headings")

TITLE_PROMOTION_PREFIXES: tuple[str, ...] = (
    "buy ",
)
TITLE_PROMOTION_SUBSTRINGS: tuple[str, ...] = (
    "apparel for",
)
TITLE_PROMOTION_SEPARATOR: str = "|"

__all__ = sorted(
    [
        *_STATIC_EXPORTS.keys(),
        "DYNAMIC_FIELD_NAME_MAX_TOKENS",
        "JOB_ERROR_PAGE_HEADINGS",
        "JOB_ERROR_PAGE_TITLES",
        "JOB_REDIRECT_SHELL_CANONICAL_URLS",
        "JOB_REDIRECT_SHELL_HEADINGS",
        "JOB_REDIRECT_SHELL_TITLES",
        "KNOWN_ATS_PLATFORMS",
        "LISTING_FALLBACK_CONTAINER_SELECTOR",
        "LISTING_STRUCTURE_NEGATIVE_HINTS",
        "LISTING_STRUCTURE_POSITIVE_HINTS",
        "MAX_CANDIDATES_PER_FIELD",
        "TITLE_PROMOTION_PREFIXES",
        "TITLE_PROMOTION_SEPARATOR",
        "TITLE_PROMOTION_SUBSTRINGS",
    ]
)
