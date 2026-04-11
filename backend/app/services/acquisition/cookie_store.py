from __future__ import annotations

import json
import logging
import re
import time
from json import loads as parse_json
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.services.config.extraction_rules import COOKIE_POLICY

logger = logging.getLogger(__name__)


def _log_for_pytest(level: int, message: str, *args: object) -> None:
    if logger.propagate or logger.handlers:
        logger.log(level, message, *args)
        return
    root_logger = logging.getLogger()
    root_logger.log(level, message, *args)

_COOKIE_OVERRIDE_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_COOKIE_OVERRIDE_PLACEHOLDERS = {
    "your-domain.com",
    "www.your-domain.com",
}


def validate_cookie_policy_config(policy: dict[str, object] | None = None) -> None:
    raw_policy = policy if isinstance(policy, dict) else COOKIE_POLICY
    overrides = raw_policy.get("domain_overrides", {})
    if overrides in (None, ""):
        return
    if not isinstance(overrides, dict):
        raise ValueError("COOKIE_POLICY domain_overrides must be a dict")
    for override_domain, override_values in overrides.items():
        normalized = str(override_domain or "").strip().lower().lstrip(".")
        if not normalized:
            raise ValueError("COOKIE_POLICY domain_overrides cannot contain an empty domain")
        if normalized in _COOKIE_OVERRIDE_PLACEHOLDERS:
            raise ValueError(
                f"COOKIE_POLICY domain_overrides contains placeholder domain {override_domain!r}"
            )
        if not _COOKIE_OVERRIDE_DOMAIN_RE.fullmatch(normalized):
            raise ValueError(
                f"COOKIE_POLICY domain_overrides contains malformed domain {override_domain!r}"
            )
        if not isinstance(override_values, dict):
            raise ValueError(
                f"COOKIE_POLICY domain_overrides[{override_domain!r}] must be a dict"
            )


def cookie_policy_for_domain(domain: str) -> dict[str, object]:
    normalized = str(domain or "").strip().lower().lstrip(".")
    policy = dict(COOKIE_POLICY)
    overrides = COOKIE_POLICY.get("domain_overrides", {})
    if not isinstance(overrides, dict):
        return policy
    for override_domain, override_values in overrides.items():
        candidate = str(override_domain or "").strip().lower().lstrip(".")
        if not candidate or not isinstance(override_values, dict):
            continue
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            policy.update(override_values)
    return policy


def cookie_store_path(domain: str) -> Path | None:
    normalized = str(domain or "").strip().lower()
    if not normalized:
        return None
    safe = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in normalized)
    if not safe:
        return None
    return Path(settings.cookie_store_dir) / f"{safe}.json"


def session_cookie_store_path(domain: str, session_identity: str) -> Path | None:
    """Cookie store path keyed by domain AND session identity.

    This ensures different proxy/fingerprint sessions never share persisted
    cookies on disk.
    """
    normalized = str(domain or "").strip().lower()
    identity = str(session_identity or "").strip()
    if not normalized or not identity:
        return None
    safe_domain = "".join(
        ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in normalized
    )
    safe_identity = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in identity
    )
    if not safe_domain or not safe_identity:
        return None
    return Path(settings.cookie_store_dir) / f"{safe_domain}__{safe_identity}.json"


def filter_persistable_cookies(payload: object, *, domain: str) -> list[dict]:
    if not isinstance(payload, list):
        return []
    filtered: list[dict] = []
    for cookie in payload:
        if not isinstance(cookie, dict):
            continue
        if is_persistable_cookie(cookie, domain=domain):
            filtered.append(cookie)
    return filtered


def load_cookies_for_context(domain: str) -> list[dict]:
    path = cookie_store_path(domain)
    if path is None or not path.exists():
        return []
    try:
        payload = parse_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return []
    return filter_persistable_cookies(payload, domain=domain)


def load_cookies_for_http(domain: str) -> dict[str, str]:
    policy = cookie_policy_for_domain(domain)
    if not bool(policy.get("reuse_in_http_client", True)):
        return {}
    cookies = load_cookies_for_context(domain)
    http_cookies: dict[str, str] = {}
    for cookie in cookies:
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if name and value:
            http_cookies[name] = value
    return http_cookies


def save_cookies_payload(payload: object, *, domain: str) -> None:
    path = cookie_store_path(domain)
    if path is None:
        return
    filtered = filter_persistable_cookies(payload, domain=domain)
    if not filtered:
        if path.exists():
            path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    Path(tmp_path).replace(path)


def is_persistable_cookie(cookie: dict, *, domain: str) -> bool:
    policy = cookie_policy_for_domain(domain)
    name = str(cookie.get("name") or "").strip()
    if not name:
        return False
    cookie_domain = str(cookie.get("domain") or "").strip()
    cookie_url = str(cookie.get("url") or "").strip()
    if not cookie_domain and not cookie_url:
        return False
    if cookie_domain and not cookie_domain_matches(cookie_domain, domain):
        return False
    if not cookie_domain:
        try:
            extracted_domain = str(urlparse(cookie_url).hostname or "").strip().lower()
        except ValueError:
            extracted_domain = ""
        if extracted_domain and not cookie_domain_matches(extracted_domain, domain):
            return False
    expires = cookie_expiry(cookie)
    now = time.time()
    if expires is None:
        return bool(policy.get("persist_session_cookies", False))
    if expires <= now:
        return False
    raw_max_ttl = policy.get("max_persisted_ttl_seconds", 0)
    try:
        max_ttl = int(raw_max_ttl or 0)
    except (TypeError, ValueError):
        _log_for_pytest(
            logging.WARNING,
            "Invalid cookie policy value for %s: %r",
            "max_persisted_ttl_seconds",
            raw_max_ttl,
        )
        max_ttl = 0
    if max_ttl > 0 and expires - now > max_ttl:
        return False
    if cookie_name_explicitly_allowed(name, policy):
        return True
    if cookie_name_blocked(name, policy):
        return False
    return True


def cookie_name_explicitly_allowed(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    allowed_names = {
        str(value).strip().lower()
        for value in policy.get("allowed_cookie_names", [])
        if str(value).strip()
    }
    return normalized in allowed_names


def cookie_name_allowed(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    allowed_names = {
        str(value).strip().lower()
        for value in policy.get("allowed_cookie_names", [])
        if str(value).strip()
    }
    harvest_names = {
        str(value).strip().lower()
        for value in policy.get("harvest_cookie_names", [])
        if str(value).strip()
    }
    if normalized in allowed_names or normalized in harvest_names:
        return True
    harvest_prefixes = [
        str(value).strip().lower()
        for value in policy.get("harvest_name_prefixes", [])
        if str(value).strip()
    ]
    if any(normalized.startswith(prefix) for prefix in harvest_prefixes):
        return True
    harvest_contains = [
        str(value).strip().lower()
        for value in policy.get("harvest_name_contains", [])
        if str(value).strip()
    ]
    return any(fragment in normalized for fragment in harvest_contains)


def cookie_name_blocked(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return True
    blocked_prefixes = [str(value).strip().lower() for value in policy.get("blocked_name_prefixes", []) if str(value).strip()]
    if any(normalized.startswith(prefix) for prefix in blocked_prefixes):
        return True
    blocked_substrings = [str(value).strip().lower() for value in policy.get("blocked_name_contains", []) if str(value).strip()]
    return any(fragment in normalized for fragment in blocked_substrings)


def cookie_expiry(cookie: dict) -> float | None:
    raw_expires = cookie.get("expires")
    if raw_expires in (None, "", -1):
        return None
    try:
        return float(raw_expires)
    except (TypeError, ValueError):
        return None


def cookie_domain_matches(cookie_domain: str, requested_domain: str) -> bool:
    cookie_host = str(cookie_domain or "").strip().lower().lstrip(".")
    requested_host = str(requested_domain or "").strip().lower().lstrip(".")
    if not cookie_host or not requested_host:
        return False
    return cookie_host == requested_host or requested_host.endswith(f".{cookie_host}")


# ---------------------------------------------------------------------------
# Session-scoped cookie persistence
# ---------------------------------------------------------------------------


def load_session_cookies_for_context(
    domain: str, session_identity: str
) -> list[dict]:
    """Load Playwright-format cookies scoped to a specific session identity."""
    path = session_cookie_store_path(domain, session_identity)
    if path is None or not path.exists():
        return []
    try:
        payload = parse_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return []
    return filter_persistable_cookies(payload, domain=domain)


def load_session_cookies_for_http(
    domain: str, session_identity: str
) -> dict[str, str]:
    """Load HTTP-format cookies scoped to a specific session identity."""
    policy = cookie_policy_for_domain(domain)
    if not bool(policy.get("reuse_in_http_client", True)):
        return {}
    cookies = load_session_cookies_for_context(domain, session_identity)
    return {
        str(c.get("name") or "").strip(): str(c.get("value") or "").strip()
        for c in cookies
        if str(c.get("name") or "").strip() and str(c.get("value") or "").strip()
    }


def save_session_cookies_payload(
    payload: object, *, domain: str, session_identity: str
) -> None:
    """Save cookies to a session-scoped store file."""
    path = session_cookie_store_path(domain, session_identity)
    if path is None:
        return
    filtered = filter_persistable_cookies(payload, domain=domain)
    if not filtered:
        if path.exists():
            path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    Path(tmp_path).replace(path)


def discard_session_cookies(domain: str, session_identity: str) -> None:
    """Remove persisted cookies for an invalidated session."""
    path = session_cookie_store_path(domain, session_identity)
    if path is not None and path.exists():
        path.unlink(missing_ok=True)
