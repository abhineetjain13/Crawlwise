from __future__ import annotations

STORAGE_STATE_META_KEY = "_crawler"
STORAGE_STATE_BROWSER_ENGINE_KEY = "browser_engine"
DEFAULT_STORAGE_STATE_ENGINE = "chromium"
DOMAIN_STORAGE_SCOPE_SEPARATOR = "::"
SUPPORTED_STORAGE_STATE_ENGINES = frozenset(
    {
        "chromium",
        "patchright",
        "real_chrome",
    }
)
COOKIE_FIELDS = (
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
    "url",
)
STORAGE_STATE_REPLACE_ATTEMPTS = 3
STORAGE_STATE_REPLACE_RETRY_SECONDS = 0.05
INCLUDE_ORIGIN_STATE_IN_STORAGE = False

__all__ = [
    "COOKIE_FIELDS",
    "DEFAULT_STORAGE_STATE_ENGINE",
    "DOMAIN_STORAGE_SCOPE_SEPARATOR",
    "INCLUDE_ORIGIN_STATE_IN_STORAGE",
    "STORAGE_STATE_BROWSER_ENGINE_KEY",
    "STORAGE_STATE_META_KEY",
    "STORAGE_STATE_REPLACE_ATTEMPTS",
    "STORAGE_STATE_REPLACE_RETRY_SECONDS",
    "SUPPORTED_STORAGE_STATE_ENGINES",
]
