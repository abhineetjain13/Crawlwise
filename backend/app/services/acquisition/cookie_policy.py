from __future__ import annotations

import re

COOKIE_POLICY = {
    "persist_session_cookies": False,
    "max_persisted_ttl_seconds": 2592000,
    "blocked_name_prefixes": [
        "cf_",
        "__cf",
        "ak_",
        "bm_",
        "dd_",
        "datadome",
        "px",
        "_px",
        "kpsdk",
        "captcha",
    ],
    "blocked_name_contains": [
        "challenge",
        "captcha",
        "datadome",
        "perimeterx",
        "incap",
        "kasada",
        "bot",
    ],
    "harvest_cookie_names": [],
    "harvest_name_prefixes": [],
    "harvest_name_contains": [],
    "blocked_rules_precede_harvest": True,
    "reuse_in_http_client": True,
    "domain_overrides": {},
}

_COOKIE_OVERRIDE_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_COOKIE_OVERRIDE_PLACEHOLDERS = {
    "your-domain.com",
    "www.your-domain.com",
}


def validate_cookie_policy_overrides(policy: dict[str, object]) -> None:
    overrides = policy.get("domain_overrides", {})
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


def resolve_cookie_policy_for_domain(
    policy: dict[str, object],
    domain: str,
) -> dict[str, object]:
    normalized = str(domain or "").strip().lower().lstrip(".")
    resolved_policy = dict(policy)
    overrides = policy.get("domain_overrides", {})
    if not isinstance(overrides, dict):
        return resolved_policy
    for override_domain, override_values in overrides.items():
        candidate = str(override_domain or "").strip().lower().lstrip(".")
        if not candidate or not isinstance(override_values, dict):
            continue
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            resolved_policy.update(override_values)
    return resolved_policy
