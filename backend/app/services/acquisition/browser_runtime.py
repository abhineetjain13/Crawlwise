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
    profile = acquisition_profile if isinstance(acquisition_profile, dict) else {}
    anti_bot_enabled = bool(profile.get("anti_bot_enabled"))
    return BrowserRuntimeOptions(
        anti_bot_enabled=anti_bot_enabled,
        retry_launch_profiles=anti_bot_enabled,
        wait_for_challenge=anti_bot_enabled,
        wait_for_readiness=True,
        warm_origin=anti_bot_enabled and bool(profile.get("prefer_stealth")),
    )
