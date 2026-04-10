from __future__ import annotations

from app.services.config.extraction_rules import EXTRACTION_RULES

_ACQUISITION_GUARDS = EXTRACTION_RULES.get("acquisition_guards", {})

JOB_REDIRECT_SHELL_TITLES = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_titles", [])
)
JOB_REDIRECT_SHELL_CANONICAL_URLS = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_canonical_urls", [])
)
JOB_REDIRECT_SHELL_HEADINGS = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_headings", [])
)
JOB_ERROR_PAGE_TITLES = frozenset(_ACQUISITION_GUARDS.get("job_error_page_titles", []))
JOB_ERROR_PAGE_HEADINGS = frozenset(
    _ACQUISITION_GUARDS.get("job_error_page_headings", [])
)
