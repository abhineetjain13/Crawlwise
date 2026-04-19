from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import settings
from app.services.acquisition.browser_identity import (
    build_playwright_context_options,
    create_browser_identity,
)
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
    raise RuntimeError("Failed to launch browser for surface probe")


async def _probe_context(context, *, target_url: str) -> dict[str, object]:
    page = await context.new_page()
    try:
        await page.goto(target_url, wait_until="domcontentloaded")
        diagnostics = await page.evaluate(
            """() => ({
                url: window.location.href,
                title: document.title,
                webdriver: navigator.webdriver,
                userAgent: navigator.userAgent,
                language: navigator.language,
                languages: navigator.languages,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory ?? null,
                hasChromeObject: typeof window.chrome !== "undefined",
                screen: {
                    width: window.screen.width,
                    height: window.screen.height,
                },
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight,
                },
            })"""
        )
        return dict(diagnostics or {})
    finally:
        await page.close()


def _delta(plain: dict[str, object], generated: dict[str, object]) -> dict[str, object]:
    changed: dict[str, object] = {}
    for key in sorted(set(plain) | set(generated)):
        if plain.get(key) != generated.get(key):
            changed[key] = {"plain": plain.get(key), "generated": generated.get(key)}
    return changed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://example.com/",
        help="Public URL used for the browser-surface probe.",
    )
    args = parser.parse_args()
    generated_identity = create_browser_identity()
    async with async_playwright() as pw:
        launch_profile, browser_channel, browser = await _launch_probe_browser(pw)
        try:
            plain_context = await browser.new_context(
                bypass_csp=False,
                service_workers="block",
            )
            generated_context = await browser.new_context(
                **build_playwright_context_options(generated_identity)
            )
            try:
                plain = await _probe_context(plain_context, target_url=args.url)
                generated = await _probe_context(generated_context, target_url=args.url)
            finally:
                await plain_context.close()
                await generated_context.close()
        finally:
            await browser.close()
    print(
        json.dumps(
            {
                "launch_profile": launch_profile,
                "browser_channel": browser_channel,
                "generated_identity": {
                    "user_agent": generated_identity.user_agent,
                    "viewport": generated_identity.viewport,
                    "locale": generated_identity.locale,
                    "device_scale_factor": generated_identity.device_scale_factor,
                    "has_touch": generated_identity.has_touch,
                    "is_mobile": generated_identity.is_mobile,
                    "extra_http_headers": generated_identity.extra_http_headers,
                },
                "plain": plain,
                "generated": generated,
                "delta": _delta(plain, generated),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
