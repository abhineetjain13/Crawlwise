from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import settings
from app.services.acquisition.browser_stealth import (
    apply_browser_stealth,
    probe_browser_automation_surfaces,
    summarize_probe_delta,
)
from app.services.acquisition.session_context import create_session_context
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright


async def _launch_probe_browser(pw):
    attempts = [
        {"label": "system_chrome", "channel": "chrome"},
        {"label": "bundled_chromium", "channel": None},
    ]
    last_error: Exception | None = None
    for attempt in attempts:
        launch_kwargs = {"headless": settings.playwright_headless}
        channel = attempt["channel"]
        if channel:
            launch_kwargs["channel"] = channel
        try:
            browser = await pw.chromium.launch(**launch_kwargs)
            return attempt["label"], channel, browser
        except PlaywrightError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to launch browser for stealth probe")


async def _probe_context(context, *, target_url: str) -> dict[str, object]:
    page = await context.new_page()
    try:
        await page.goto(
            target_url,
            wait_until="domcontentloaded",
        )
        result = await probe_browser_automation_surfaces(page)
        result["probe_url"] = page.url
        return result
    finally:
        await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://example.com/",
        help="Public URL used for the browser-surface probe.",
    )
    args = parser.parse_args()
    session_context = create_session_context()
    async with async_playwright() as pw:
        launch_profile, browser_channel, browser = await _launch_probe_browser(pw)
        try:
            base_kwargs = session_context.playwright_context_kwargs(
                browser_channel=browser_channel,
                ignore_https_errors=False,
                bypass_csp=False,
            )
            plain_context = await browser.new_context(**base_kwargs)
            stealth_context = await browser.new_context(**base_kwargs)
            try:
                await apply_browser_stealth(
                    stealth_context,
                    session_context=session_context,
                )
                plain = await _probe_context(plain_context, target_url=args.url)
                stealth = await _probe_context(stealth_context, target_url=args.url)
            finally:
                await plain_context.close()
                await stealth_context.close()
        finally:
            await browser.close()
    print(
        json.dumps(
            {
                "launch_profile": launch_profile,
                "browser_channel": browser_channel,
                "session_identity": session_context.to_diagnostics(),
                "plain": plain,
                "stealth": stealth,
                "delta": summarize_probe_delta(plain, stealth),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
