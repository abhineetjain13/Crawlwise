from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from playwright_stealth import Stealth

if TYPE_CHECKING:
    from app.services.acquisition.session_context import SessionContext


def _language_overrides(session_context: SessionContext | None) -> tuple[str, str]:
    locale = "en-US"
    if session_context is not None:
        locale = str(session_context.fingerprint.locale or locale)
    primary = locale.split("-", 1)[0] or "en"
    if primary == locale:
        fallback = "en"
    else:
        fallback = primary
    return locale, fallback


def _platform_override(session_context: SessionContext | None) -> str:
    if session_context is None:
        return "Win32"
    return str(session_context.fingerprint.platform or "Win32")


def _user_agent_override(session_context: SessionContext | None) -> str | None:
    if session_context is None:
        return None
    user_agent = str(session_context.fingerprint.user_agent or "").strip()
    if not user_agent:
        return None
    if not _supports_sec_ch_ua(user_agent):
        return None
    return user_agent


def _supports_sec_ch_ua(user_agent: str | None) -> bool:
    if not user_agent:
        return True
    return bool(re.search(r"\bChrome/\d+", user_agent))


def build_browser_stealth(
    *,
    session_context: SessionContext | None = None,
) -> Stealth:
    languages = _language_overrides(session_context)
    user_agent = _user_agent_override(session_context)
    return Stealth(
        chrome_runtime=True,
        navigator_languages_override=languages,
        navigator_platform_override=_platform_override(session_context),
        navigator_user_agent_override=user_agent,
        navigator_vendor_override="Google Inc.",
        sec_ch_ua=_supports_sec_ch_ua(user_agent),
    )


async def apply_browser_stealth(
    context,
    *,
    session_context: SessionContext | None = None,
) -> bool:
    stealth = build_browser_stealth(session_context=session_context)
    await stealth.apply_stealth_async(context)
    return True


async def probe_browser_automation_surfaces(page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const chromeObject = window.chrome;
          const runtime = chromeObject && chromeObject.runtime;
          const plugins = navigator.plugins ? Array.from(navigator.plugins).map((plugin) => plugin.name) : [];
          const glCanvas = document.createElement('canvas');
          const gl = glCanvas.getContext('webgl') || glCanvas.getContext('experimental-webgl');
          let webglVendor = null;
          let webglRenderer = null;
          if (gl) {
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (debugInfo) {
              webglVendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
              webglRenderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
            }
          }
          return {
            navigator_webdriver: navigator.webdriver,
            chrome_present: Boolean(chromeObject),
            chrome_runtime_present: Boolean(runtime),
            navigator_languages: Array.isArray(navigator.languages) ? [...navigator.languages] : [],
            navigator_platform: navigator.platform || null,
            navigator_vendor: navigator.vendor || null,
            navigator_plugins_length: plugins.length,
            webgl_vendor: webglVendor,
            webgl_renderer: webglRenderer,
          };
        }
        """
    )


def summarize_probe_delta(
    plain: dict[str, Any],
    stealth: dict[str, Any],
) -> dict[str, Any]:
    changed: dict[str, dict[str, Any]] = {}
    for key in sorted(set(plain) | set(stealth)):
        plain_value = plain.get(key)
        stealth_value = stealth.get(key)
        if plain_value != stealth_value:
            changed[key] = {
                "plain": plain_value,
                "stealth": stealth_value,
            }
    return {
        "changed_keys": changed,
        "navigator_webdriver_cleared": bool(plain.get("navigator_webdriver"))
        and stealth.get("navigator_webdriver") in (False, None),
        "chrome_runtime_added": not bool(plain.get("chrome_runtime_present"))
        and bool(stealth.get("chrome_runtime_present")),
    }
