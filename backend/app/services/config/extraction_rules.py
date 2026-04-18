from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config._module_exports import make_getattr, module_dir
from app.services.config.crawl_runtime import (
    DYNAMIC_FIELD_NAME_MAX_TOKENS,
    MAX_CANDIDATES_PER_FIELD,
)
from app.services.platform_policy import known_ats_domains

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")
_DYNAMIC_EXPORTS = {
    "DYNAMIC_FIELD_NAME_MAX_TOKENS": DYNAMIC_FIELD_NAME_MAX_TOKENS,
    "KNOWN_ATS_PLATFORMS": known_ats_domains,
    "MAX_CANDIDATES_PER_FIELD": MAX_CANDIDATES_PER_FIELD,
}


@lru_cache(maxsize=1)
def _static_exports() -> dict[str, Any]:
    return load_export_data(str(_EXPORTS_PATH))


def _acquisition_guard_export(rule_name: str) -> frozenset[object]:
    rules = _static_exports().get("ACQUISITION_GUARDS_RULES", {})
    values = rules.get(rule_name, []) if isinstance(rules, dict) else []
    return frozenset(
        values if isinstance(values, (list, tuple, set, frozenset)) else []
    )


_COMPUTED_EXPORTS = {
    **_DYNAMIC_EXPORTS,
    "JOB_REDIRECT_SHELL_TITLES": lambda: _acquisition_guard_export(
        "job_redirect_shell_titles"
    ),
    "JOB_REDIRECT_SHELL_CANONICAL_URLS": lambda: _acquisition_guard_export(
        "job_redirect_shell_canonical_urls"
    ),
    "JOB_REDIRECT_SHELL_HEADINGS": lambda: _acquisition_guard_export(
        "job_redirect_shell_headings"
    ),
    "JOB_ERROR_PAGE_TITLES": lambda: _acquisition_guard_export(
        "job_error_page_titles"
    ),
    "JOB_ERROR_PAGE_HEADINGS": lambda: _acquisition_guard_export(
        "job_error_page_headings"
    ),
}

__all__ = sorted(
    [
        *(name for name in _static_exports().keys() if not name.startswith("_")),
        *_COMPUTED_EXPORTS.keys(),
    ]
)

__getattr__ = make_getattr(
    module_globals=globals(),
    value_exports=_static_exports,
    dynamic_exports=_COMPUTED_EXPORTS,
    allow_private=False,
    cache=True,
)


def __dir__() -> list[str]:
    return module_dir(globals(), __all__)
