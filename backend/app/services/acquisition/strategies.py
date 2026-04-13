"""Acquisition strategy protocol and composable chain.

.. warning:: **NOT CALLED IN PRODUCTION** (BUG-03)

   ``AcquisitionChain`` and all strategy classes defined here are
   never invoked by the live ``acquire()`` orchestrator.  The production
   path calls ``_acquire_once()`` which directly dispatches to
   ``_try_http()`` / ``_try_browser()`` in ``acquirer.py``.

   Any fix applied here has **no effect** on live behaviour.
   See ``acquirer._acquire_once()`` for the real acquisition path.

Decomposes the monolithic ``_acquire_once`` waterfall into pluggable
strategy classes.  A new acquisition backend (e.g. BrightData, Zyte)
can be added by implementing :class:`AcquisitionStrategy` and inserting
it into the chain — no changes to the core ``acquire()`` orchestrator.

The default chain preserves the existing curl → Playwright waterfall.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.services.config.platform_registry import browser_first_platform_families

if TYPE_CHECKING:
    from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult

logger = logging.getLogger(__name__)
PLATFORM_BROWSER_POLICIES = frozenset(
    family.strip().lower()
    for family in browser_first_platform_families()
    if family and family.strip()
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AcquisitionStrategy(Protocol):
    """A single acquisition method (HTTP, browser, third-party API, etc.).

    ``acquire`` should return ``None`` if this strategy cannot handle the
    request or failed irrecoverably — the chain will try the next strategy.
    """

    @property
    def name(self) -> str:
        """Human-readable strategy label for diagnostics."""
        ...

    async def acquire(
        self,
        request: "AcquisitionRequest",
        *,
        proxy: str | None = None,
    ) -> "AcquisitionResult | None":
        """Attempt to acquire a page.

        Return ``None`` to signal that the next strategy in the chain
        should be tried.
        """
        ...


# ---------------------------------------------------------------------------
# Chain executor
# ---------------------------------------------------------------------------


class AcquisitionChain:
    """Executes an ordered list of :class:`AcquisitionStrategy` instances.

    Strategies are tried in order.  The first non-``None`` result wins.
    If all strategies return ``None``, the chain returns ``None``.
    """

    def __init__(self, strategies: list[AcquisitionStrategy]) -> None:
        self._strategies = list(strategies)

    async def execute(
        self,
        request: "AcquisitionRequest",
        *,
        proxy: str | None = None,
    ) -> "AcquisitionResult | None":
        for strategy in self._strategies:
            logger.debug(
                "Trying acquisition strategy %s for %s", strategy.name, request.url
            )
            result = await strategy.acquire(request, proxy=proxy)
            if result is not None:
                logger.debug(
                    "Strategy %s succeeded for %s (method=%s)",
                    strategy.name,
                    request.url,
                    getattr(result, "method", "?"),
                )
                return result
            logger.debug(
                "Strategy %s returned None for %s, trying next",
                strategy.name,
                request.url,
            )
        return None

    @property
    def strategy_names(self) -> list[str]:
        return [s.name for s in self._strategies]


# ---------------------------------------------------------------------------
# Default strategy implementations (wrappers around existing code)
# ---------------------------------------------------------------------------


class HttpStrategy:
    """Wraps the existing ``_try_http`` (curl_cffi) acquisition path."""

    @property
    def name(self) -> str:
        return "http_curl"

    async def acquire(
        self,
        request: "AcquisitionRequest",
        *,
        proxy: str | None = None,
    ) -> "AcquisitionResult | None":
        # Lazy import to avoid circular dependencies
        from app.services.acquisition.acquirer import _try_http

        try:
            return await _try_http(request, proxy=proxy)
        except Exception:
            logger.debug("HttpStrategy failed for %s", request.url, exc_info=True)
            return None


class BrowserStrategy:
    """Wraps the existing ``_try_browser`` (Playwright) acquisition path."""

    @property
    def name(self) -> str:
        return "browser_playwright"

    async def acquire(
        self,
        request: "AcquisitionRequest",
        *,
        proxy: str | None = None,
    ) -> "AcquisitionResult | None":
        from app.services.acquisition.acquirer import _try_browser

        try:
            return await _try_browser(request, proxy=proxy)
        except Exception:
            logger.debug("BrowserStrategy failed for %s", request.url, exc_info=True)
            return None


class AdapterRecoveryStrategy:
    """Wraps ``try_blocked_adapter_recovery`` for platform-specific fallback."""

    @property
    def name(self) -> str:
        return "adapter_recovery"

    async def acquire(
        self,
        request: "AcquisitionRequest",
        *,
        proxy: str | None = None,
    ) -> "AcquisitionResult | None":
        from app.services.adapters.registry import try_blocked_adapter_recovery

        try:
            result = await try_blocked_adapter_recovery(
                request.url,
                request.surface,
                proxy_list=[proxy] if proxy else None,
            )
            if result and result.records:
                return result
            return None
        except Exception:
            logger.debug(
                "AdapterRecoveryStrategy failed for %s", request.url, exc_info=True
            )
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_default_chain(
    *,
    browser_first: bool = False,
    platform_family: str | None = None,
) -> AcquisitionChain:
    """Build the default acquisition chain matching the existing waterfall.

    Browser-first ordering is enabled when the caller sets
    ``browser_first=True`` or when ``platform_family`` matches
    ``PLATFORM_BROWSER_POLICIES``. Callers that already resolved the target's
    platform family should prefer passing it here instead of duplicating the
    policy lookup around ``build_default_chain``.
    """
    normalized_family = str(platform_family or "").strip().lower()
    use_browser_first = browser_first or (
        normalized_family in PLATFORM_BROWSER_POLICIES
    )
    if use_browser_first:
        return AcquisitionChain(
            [
                BrowserStrategy(),
                HttpStrategy(),
                AdapterRecoveryStrategy(),
            ]
        )
    return AcquisitionChain(
        [
            HttpStrategy(),
            BrowserStrategy(),
            AdapterRecoveryStrategy(),
        ]
    )
