from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserRuntimeOptions:
    hardened_mode: bool = False
    hardened_mode_reason: str = "default"
    retry_launch_profiles: bool = False
    wait_for_challenge: bool = False
    wait_for_readiness: bool = True
    warm_origin: bool = False
    ignore_https_errors: bool = False
    bypass_csp: bool = False

    @property
    def anti_bot_enabled(self) -> bool:
        """Backward-compatible alias for legacy callers/tests."""
        return self.hardened_mode


def resolve_browser_runtime_options(
    acquisition_profile: dict[str, object] | None,
    *,
    browser_first: bool = False,
) -> BrowserRuntimeOptions:
    profile = acquisition_profile if isinstance(acquisition_profile, dict) else {}
    legacy_anti_bot = bool(profile.get("anti_bot_enabled"))
    hardened_mode = bool(browser_first or legacy_anti_bot)
    if browser_first:
        hardened_mode_reason = "browser_first"
    elif legacy_anti_bot:
        hardened_mode_reason = "legacy_profile"
    else:
        hardened_mode_reason = "default"
    return BrowserRuntimeOptions(
        hardened_mode=hardened_mode,
        hardened_mode_reason=hardened_mode_reason,
        retry_launch_profiles=hardened_mode,
        wait_for_challenge=hardened_mode,
        wait_for_readiness=True,
        warm_origin=hardened_mode and bool(profile.get("prefer_stealth")),
        ignore_https_errors=bool(profile.get("ignore_https_errors")),
        bypass_csp=bool(profile.get("bypass_csp")),
    )
