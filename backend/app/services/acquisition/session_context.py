# Session-Proxy-Fingerprint affinity: binds a proxy IP, dynamically generated
# browser fingerprint, and isolated cookie jar into a single SessionContext.
#
# When a proxy dies the entire SessionContext is discarded (cookies included).
# A single HTTP session maintains the exact same IP, UA, and TLS fingerprint
# across its lifespan.
from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fingerprint generation (browserforge)
# ---------------------------------------------------------------------------

try:
    from browserforge.fingerprints import FingerprintGenerator

    _fingerprint_generator = FingerprintGenerator(browser="chrome", os="windows")
    _BROWSERFORGE_AVAILABLE = True
except Exception:  # pragma: no cover – optional dependency
    _fingerprint_generator = None
    _BROWSERFORGE_AVAILABLE = False
    logger.debug("browserforge not available; using static fingerprint fallback")


# Well-known Chrome impersonation profiles for curl_cffi.  The chosen profile
# is bound to the session for its entire lifetime so the TLS fingerprint stays
# consistent across retries.
_CURL_IMPERSONATION_PROFILES: list[str] = [
    "chrome110",
    "chrome116",
    "chrome123",
    "chrome131",
]


@dataclass
class BrowserFingerprint:
    """Immutable browser identity generated per session."""

    user_agent: str
    viewport_width: int = 1365
    viewport_height: int = 900
    device_scale_factor: float = 1.0
    is_mobile: bool = False
    has_touch: bool = False
    locale: str = "en-US"
    timezone_id: str = "UTC"
    color_scheme: str = "light"
    platform: str = "Win32"
    # Extra HTTP headers from the fingerprint (sec-ch-ua, etc.)
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def identity_hash(self) -> str:
        """Short stable hash for diagnostics / pool keying."""
        raw = (
            f"{self.user_agent}|"
            f"{self.viewport_width}x{self.viewport_height}|"
            f"{self.device_scale_factor}|"
            f"{self.locale}|"
            f"{self.timezone_id}|"
            f"{self.platform}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


def generate_fingerprint() -> BrowserFingerprint:
    """Generate a realistic browser fingerprint using browserforge.

    Falls back to a randomized static fingerprint when browserforge is
    unavailable.
    """
    if _BROWSERFORGE_AVAILABLE and _fingerprint_generator is not None:
        try:
            fp = _fingerprint_generator.generate()
            nav = fp.navigator
            screen = fp.screen
            headers = dict(fp.headers) if isinstance(fp.headers, dict) else {}

            # Remove headers that Playwright or curl_cffi will set themselves
            stripped = {
                k: v
                for k, v in headers.items()
                if k.lower()
                not in {
                    "user-agent",
                    "accept",
                    "accept-encoding",
                    "upgrade-insecure-requests",
                }
            }

            return BrowserFingerprint(
                user_agent=str(getattr(nav, "userAgent", "") or ""),
                viewport_width=int(getattr(screen, "width", 1365) or 1365),
                viewport_height=int(getattr(screen, "height", 900) or 900),
                device_scale_factor=float(getattr(screen, "devicePixelRatio", 1) or 1),
                is_mobile=False,  # Crawling always desktop
                has_touch=False,
                locale=str(getattr(nav, "language", "en-US") or "en-US"),
                platform=str(getattr(nav, "platform", "Win32") or "Win32"),
                extra_headers=stripped,
            )
        except Exception:
            logger.debug(
                "browserforge generation failed; using fallback", exc_info=True
            )

    # Fallback: randomized static fingerprint
    return _generate_fallback_fingerprint()


def _generate_fallback_fingerprint() -> BrowserFingerprint:
    """Produce a fingerprint without browserforge via weighted random selection."""
    ua_variants = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    ]
    viewport_variants = [
        (1920, 1080),
        (1536, 864),
        (1440, 900),
        (1366, 768),
        (1280, 720),
        (1600, 900),
    ]
    ua = random.choice(ua_variants)
    vw, vh = random.choice(viewport_variants)
    return BrowserFingerprint(
        user_agent=ua,
        viewport_width=vw,
        viewport_height=vh,
        device_scale_factor=random.choice([1.0, 1.25, 1.5]),
        locale=random.choice(["en-US", "en-GB", "en"]),
        platform="Win32" if "Windows" in ua else "MacIntel",
    )


# ---------------------------------------------------------------------------
# SessionContext — the binding object
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Binds a specific proxy, fingerprint, and isolated cookie jar into an
    affinity group that lives for the entire URL acquisition attempt.

    When a proxy dies (connection refused, timeout, block detection), the
    caller must discard the entire ``SessionContext`` — cookies included —
    and create a fresh one for the next proxy.
    """

    proxy: str | None = None
    fingerprint: BrowserFingerprint = field(default_factory=generate_fingerprint)
    # In-memory isolated cookie jar for this session. Dict of {name: value}
    # suitable for curl_cffi ``cookies=`` kwarg.
    cookies: dict[str, str] = field(default_factory=dict)
    # Playwright cookie list (list[dict]) for ``context.add_cookies()``.
    playwright_cookies: list[dict[str, Any]] = field(default_factory=list)
    # Bound curl_cffi impersonation profile for TLS fingerprint consistency.
    impersonate_profile: str = ""
    # Creation timestamp for diagnostics.
    created_at: float = field(default_factory=time.monotonic)
    # Whether this context has been invalidated (proxy died, etc.).
    invalidated: bool = False
    # Domains whose persisted cookies are associated with this session.
    persisted_domains: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.impersonate_profile:
            self.impersonate_profile = random.choice(_CURL_IMPERSONATION_PROFILES)

    @property
    def user_agent(self) -> str:
        return self.fingerprint.user_agent

    @property
    def identity_key(self) -> str:
        """Unique key for browser pool / diagnostics."""
        proxy_part = self.proxy or "direct"
        return (
            f"{proxy_part}|{self.fingerprint.identity_hash}|{self.impersonate_profile}"
        )

    def invalidate(self) -> None:
        """Mark this session as dead.  Cookies become unusable."""
        self.invalidated = True
        self.cookies.clear()
        self.playwright_cookies.clear()
        logger.debug(
            "SessionContext invalidated: proxy=%s profile=%s",
            self.proxy or "direct",
            self.impersonate_profile,
        )

    def remember_domain(self, domain: str) -> None:
        normalized = str(domain or "").strip().lower().lstrip(".")
        if normalized:
            self.persisted_domains.add(normalized)

    def merge_http_cookies(self, domain_cookies: dict[str, str]) -> None:
        """Merge domain-scoped cookies into the session-isolated jar."""
        self.cookies.update(domain_cookies)

    def merge_playwright_cookies(self, browser_cookies: list[dict]) -> None:
        """Merge Playwright-format cookies into the session-isolated jar."""
        for cookie in browser_cookies:
            key = (cookie.get("name"), cookie.get("domain"))
            for index, existing_cookie in enumerate(self.playwright_cookies):
                existing_key = (
                    existing_cookie.get("name"),
                    existing_cookie.get("domain"),
                )
                if existing_key == key:
                    updated_cookie = dict(existing_cookie)
                    updated_cookie.update(cookie)
                    self.playwright_cookies[index] = updated_cookie
                    break
            else:
                self.playwright_cookies.append(cookie)

    def to_diagnostics(self) -> dict[str, object]:
        """Return a diagnostics-safe snapshot (no cookie values)."""
        return {
            "proxy": bool(self.proxy),
            "impersonate_profile": self.impersonate_profile,
            "user_agent_hash": self.fingerprint.identity_hash,
            "viewport": f"{self.fingerprint.viewport_width}x{self.fingerprint.viewport_height}",
            "device_scale_factor": self.fingerprint.device_scale_factor,
            "locale": self.fingerprint.locale,
            "cookie_count": len(self.cookies) + len(self.playwright_cookies),
            "invalidated": self.invalidated,
            "age_seconds": round(time.monotonic() - self.created_at, 1),
        }

    # ------------------------------------------------------------------
    # Playwright context kwargs generation
    # ------------------------------------------------------------------

    def playwright_context_kwargs(
        self,
        *,
        browser_channel: str | None = None,
        ignore_https_errors: bool = False,
        bypass_csp: bool = False,
    ) -> dict[str, Any]:
        """Build Playwright new_context kwargs using this session's fingerprint."""
        fp = self.fingerprint
        kwargs: dict[str, Any] = {
            "java_script_enabled": True,
            "ignore_https_errors": ignore_https_errors,
            "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
            "device_scale_factor": fp.device_scale_factor,
            "is_mobile": fp.is_mobile,
            "has_touch": fp.has_touch,
            "color_scheme": fp.color_scheme,
            "user_agent": fp.user_agent,
            "service_workers": "block",
        }
        if not browser_channel:
            # Bundled Chromium gets locale/timezone
            kwargs["locale"] = fp.locale
            kwargs["timezone_id"] = fp.timezone_id
        if bypass_csp:
            kwargs["bypass_csp"] = True
        return kwargs

    # ------------------------------------------------------------------
    # curl_cffi kwargs generation
    # ------------------------------------------------------------------

    def curl_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for ``requests.AsyncSession.get()``."""
        kwargs: dict[str, Any] = {
            "impersonate": self.impersonate_profile,
        }
        if self.proxy:
            kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        if self.cookies:
            kwargs["cookies"] = dict(self.cookies)
        return kwargs


def create_session_context(
    proxy: str | None = None,
    *,
    domain_cookies: dict[str, str] | None = None,
    playwright_cookies: list[dict] | None = None,
) -> SessionContext:
    """Factory: build a fresh SessionContext for one acquisition attempt."""
    ctx = SessionContext(proxy=proxy)
    if domain_cookies:
        ctx.merge_http_cookies(domain_cookies)
    if playwright_cookies:
        ctx.merge_playwright_cookies(playwright_cookies)
    return ctx
