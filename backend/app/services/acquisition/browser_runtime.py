from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserRuntimeOptions:
    anti_bot_enabled: bool = False
    retry_launch_profiles: bool = False
    wait_for_challenge: bool = False
    wait_for_readiness: bool = True
    warm_origin: bool = False


def resolve_browser_runtime_options(acquisition_profile: dict[str, object] | None) -> BrowserRuntimeOptions:
    """Resolve browser runtime options from an acquisition profile.
    Parameters:
        - acquisition_profile (dict[str, object] | None): Optional profile containing browser/runtime flags such as anti-bot and stealth preferences.
    Returns:
        - BrowserRuntimeOptions: Configured runtime options derived from the provided profile."""
    profile = acquisition_profile if isinstance(acquisition_profile, dict) else {}
    anti_bot_enabled = bool(profile.get("anti_bot_enabled"))
    return BrowserRuntimeOptions(
        anti_bot_enabled=anti_bot_enabled,
        retry_launch_profiles=anti_bot_enabled,
        wait_for_challenge=anti_bot_enabled,
        wait_for_readiness=True,
        warm_origin=anti_bot_enabled and bool(profile.get("prefer_stealth")),
    )
