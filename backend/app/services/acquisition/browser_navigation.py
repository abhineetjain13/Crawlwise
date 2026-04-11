from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.services.acquisition.browser_challenge import _retryable_browser_error_reason
from app.services.acquisition.browser_readiness import _cooperative_page_wait
from app.services.config.crawl_runtime import (
    BROWSER_ERROR_RETRY_ATTEMPTS,
    BROWSER_ERROR_RETRY_DELAY_MS,
    BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
    BROWSER_NAVIGATION_LOAD_TIMEOUT_MS,
    BROWSER_NAVIGATION_MIN_COMMIT_WAIT_MS,
    BROWSER_NAVIGATION_MIN_FINAL_COMMIT_TIMEOUT_MS,
    BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
    ORIGIN_WARM_PAUSE_MS,
)
from app.services.exceptions import BrowserNavigationError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


def _navigation_strategies(
    *, browser_channel: str | None = None
) -> list[tuple[str, int]]:
    if browser_channel:
        return [
            ("domcontentloaded", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
            ("commit", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
        ]
    return [
        ("load", BROWSER_NAVIGATION_LOAD_TIMEOUT_MS),
        ("domcontentloaded", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
    ]


def _shortened_navigation_strategies() -> list[tuple[str, int]]:
    return [
        ("domcontentloaded", 12000),
        ("commit", 8000),
    ]


def _classify_profile_failure_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, PlaywrightTimeoutError) or "timeout" in text:
        return "timeout"
    if "browser_navigation_error:" in text:
        return "navigation_error"
    return "generic_error"


def _should_shorten_navigation_after_profile_failure(reason: str | None) -> bool:
    return reason in {"timeout", "navigation_error"}


def _navigation_attempts(
    strategies: list[tuple[str, int]] | None = None,
) -> list[tuple[str, int]]:
    configured = list(strategies or _navigation_strategies())
    attempts: list[tuple[str, int]] = [
        (wait_until, timeout)
        for wait_until, timeout in configured
        if wait_until in {"commit", "domcontentloaded"}
    ]
    if not attempts:
        attempts.append(
            ("domcontentloaded", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS)
        )
    if not any(wait_until == "commit" for wait_until, _timeout in attempts):
        attempts.append(
            (
                "commit",
                min(
                    BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
                    max(
                        BROWSER_NAVIGATION_MIN_COMMIT_WAIT_MS,
                        BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
                    ),
                ),
            )
        )
    max_commit_timeout = max(
        (
            int(timeout)
            for wait_until, timeout in attempts
            if wait_until == "commit"
        ),
        default=0,
    )
    final_commit_timeout = max(
        BROWSER_NAVIGATION_MIN_FINAL_COMMIT_TIMEOUT_MS,
        max_commit_timeout,
    )
    if final_commit_timeout > max_commit_timeout:
        attempts.append(("commit", final_commit_timeout))
    return attempts


async def _goto_with_fallback(
    page,
    url: str,
    *,
    surface: str | None = None,
    strategies: list[tuple[str, int]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    del surface
    strategies = strategies or _navigation_strategies()
    navigation_attempts = _navigation_attempts(strategies)
    browser_error_retries = max(0, BROWSER_ERROR_RETRY_ATTEMPTS)

    for attempt in range(browser_error_retries + 1):
        try:
            if checkpoint is not None:
                await checkpoint()
            last_navigation_error: PlaywrightError | None = None
            for wait_until, timeout in navigation_attempts:
                try:
                    await page.goto(url, wait_until=wait_until, timeout=timeout)
                    last_navigation_error = None
                    break
                except (PlaywrightTimeoutError, TimeoutError) as exc:
                    last_navigation_error = exc
                    logger.debug(
                        "goto(%s, attempt=%d, wait_until=%s, timeout=%d) timed out",
                        url,
                        attempt,
                        wait_until,
                        timeout,
                    )
                    continue
            if last_navigation_error is not None:
                raise last_navigation_error
            browser_error_reason = await _retryable_browser_error_reason(page)
            if browser_error_reason is not None:
                if attempt >= browser_error_retries:
                    raise BrowserNavigationError(
                        f"browser_navigation_error:{browser_error_reason}"
                    )
                logger.debug(
                    "goto(%s) landed on transient browser error page (%s); retrying",
                    url,
                    browser_error_reason,
                )
                await _cooperative_page_wait(
                    page,
                    BROWSER_ERROR_RETRY_DELAY_MS,
                    checkpoint=checkpoint,
                )
                continue

            for wait_until, timeout in strategies:
                if wait_until == "load" and hasattr(page, "wait_for_load_state"):
                    try:
                        await page.wait_for_load_state(
                            wait_until,
                            timeout=min(timeout, BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS),
                        )
                    except PlaywrightError:
                        pass
            return
        except PlaywrightError as exc:
            logger.debug("goto(%s, attempt=%d) failed: %s", url, attempt, exc)
            if attempt >= browser_error_retries:
                raise


async def _warm_origin(
    page,
    origin_url: str,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    try:
        await page.goto(
            origin_url,
            wait_until="domcontentloaded",
            timeout=BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
        )
        await _cooperative_page_wait(page, ORIGIN_WARM_PAUSE_MS, checkpoint=checkpoint)
        try:
            await page.mouse.move(240, 180)
            await page.evaluate("window.scrollBy(0, 120)")
        except PlaywrightError:
            logger.debug("Origin warm mouse/scroll interaction failed", exc_info=True)
    except PlaywrightError:
        logger.debug("Origin warm navigation failed for %s", origin_url, exc_info=True)
