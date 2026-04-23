# Shared domain normalisation utility.
#
# Single implementation of INV-MEM-01: domain keys are scheme-stripped and
# www-normalised.  All modules MUST use this instead of local _domain() helpers.
from __future__ import annotations

from urllib.parse import urlparse, urlsplit

_SPECIAL_USE_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
}
_SPECIAL_USE_SUFFIXES = (
    ".example",
    ".invalid",
    ".local",
    ".localhost",
)


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def normalize_domain(url: str) -> str:
    """Return a normalised domain key for Site Memory and selector scoping.

    Rules (per INV-MEM-01):
    - Scheme stripped
    - www. prefix stripped
    - Lowercased
    - Standard ports stripped (:80 for http, :443 for https)
    - Explicit non-standard ports preserved

    Examples:
        https://www.example.com/a  -> example.com
        http://example.com/b       -> example.com
        https://shop.example.com   -> shop.example.com
        http://localhost:3000      -> localhost:3000
    """
    parsed = urlparse(url)
    if not parsed.netloc and parsed.path and not parsed.path.startswith("/"):
        parsed = urlparse(f"//{url}")

    host = (parsed.netloc or "").lower().strip()
    if parsed.hostname:
        hostname = parsed.hostname.lower().strip()
        if parsed.port in {80, 443}:
            host = hostname
        elif parsed.port is not None:
            host = f"{hostname}:{parsed.port}"
        elif not host:
            host = hostname
    elif not host and not parsed.path.startswith("/"):
        host = parsed.path.lower().strip()

    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_host(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        split = urlsplit(text)
        hostname_value = str(split.hostname or "").strip().lower()
        if not hostname_value:
            return str(split.netloc or "").strip().lower()
        if split.port is not None:
            return f"{hostname_value}:{split.port}"
        return hostname_value
    return text


def is_special_use_domain(value: str) -> bool:
    host = normalize_domain(value)
    if not host:
        return True
    hostname_only, _separator, _port = host.partition(":")
    # Ports do not change special-use hostname classification.
    return hostname_only in _SPECIAL_USE_HOSTNAMES or any(
        hostname_only.endswith(suffix) for suffix in _SPECIAL_USE_SUFFIXES
    )
