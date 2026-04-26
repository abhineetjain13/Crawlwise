r"""
Smoke test for product-intelligence native Google discovery.

Usage:
    cd backend
    set PYTHONPATH=.
    .venv\Scripts\python.exe run_google_native_search_smoke.py "nike air max buy"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from app.core.config import settings
from app.services.acquisition.browser_recovery import (
    emit_browser_behavior_activity,
    type_text_like_human,
)
from app.services.acquisition.browser_runtime import (
    get_browser_runtime,
    shutdown_browser_runtime,
)
from app.services.acquisition.dom_runtime import get_page_html
from app.services.acquisition.runtime import classify_blocked_page_async
from app.services.config.product_intelligence import (
    GOOGLE_NATIVE_BROWSER_ENGINE,
    GOOGLE_NATIVE_HOME_URL,
    GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS,
    GOOGLE_NATIVE_QUERY_PARAM,
    GOOGLE_NATIVE_RESULT_COUNT_PARAM,
    GOOGLE_NATIVE_RESULT_WAIT_MS,
    GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR,
    GOOGLE_NATIVE_SEARCH_URL,
    GOOGLE_NATIVE_SUBMIT_KEY,
)
from app.services.product_intelligence.discovery import _parse_google_native_results
from app.services.product_intelligence.matching import source_domain


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _artifact_dir() -> Path:
    path = settings.artifacts_dir / "google_native_search_smoke" / _utc_stamp()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fallback_search_url(query: str, limit: int) -> str:
    return (
        f"{GOOGLE_NATIVE_SEARCH_URL}?"
        f"{urlencode({GOOGLE_NATIVE_QUERY_PARAM: query, GOOGLE_NATIVE_RESULT_COUNT_PARAM: str(limit)})}"
    )


async def _page_title(page) -> str:
    try:
        return str(await page.title() or "")
    except Exception:
        return ""


async def _run(query: str, *, limit: int, min_results: int, screenshot: bool) -> dict:
    started_at = time.perf_counter()
    artifact_dir = _artifact_dir()
    report_path = artifact_dir / "report.json"
    html_path = artifact_dir / "page.html"
    screenshot_path = artifact_dir / "page.png"
    runtime = await get_browser_runtime(browser_engine=GOOGLE_NATIVE_BROWSER_ENGINE)
    page_status = 0
    typed: dict[str, object] = {"typed_chars": 0}
    behavior: dict[str, object] = {}
    try:
        async with runtime.page(domain=source_domain(GOOGLE_NATIVE_HOME_URL)) as page:
            response = await page.goto(
                GOOGLE_NATIVE_HOME_URL,
                wait_until="domcontentloaded",
                timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
            )
            page_status = int(getattr(response, "status", 0) or 0)
            behavior = await emit_browser_behavior_activity(page)
            typed = await type_text_like_human(
                page,
                GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR,
                query,
            )
            if int(typed.get("typed_chars", 0) or 0) > 0:
                keyboard = getattr(page, "keyboard", None)
                press = getattr(keyboard, "press", None)
                if callable(press):
                    await press(GOOGLE_NATIVE_SUBMIT_KEY)
                    with suppress(Exception):
                        await page.wait_for_load_state(
                            "domcontentloaded",
                            timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
                        )
                    await page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS))
            else:
                response = await page.goto(
                    _fallback_search_url(query, limit),
                    wait_until="domcontentloaded",
                    timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
                )
                page_status = int(getattr(response, "status", page_status) or page_status)
                await page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS))
            html = await get_page_html(page)
            html_path.write_text(html, encoding="utf-8")
            if screenshot:
                with suppress(Exception):
                    await page.screenshot(path=str(screenshot_path), full_page=True)
            classification = await classify_blocked_page_async(html, page_status)
            results = _parse_google_native_results(html, limit=limit)
            result_payload = [
                {
                    "url": result.url,
                    "title": str(result.payload.get("title") or ""),
                    "position": result.payload.get("position"),
                }
                for result in results
            ]
            payload = {
                "ok": bool(not classification.blocked and len(results) >= min_results),
                "query": query,
                "limit": limit,
                "min_results": min_results,
                "status_code": page_status,
                "final_url": str(getattr(page, "url", "") or ""),
                "title": await _page_title(page),
                "html_len": len(html),
                "blocked": bool(classification.blocked),
                "block_outcome": str(classification.outcome or ""),
                "challenge_provider_hits": list(classification.provider_hits or []),
                "challenge_element_hits": list(classification.challenge_element_hits or []),
                "challenge_evidence": list(classification.evidence or [])[:10],
                "behavior": behavior,
                "typed": typed,
                "result_count": len(results),
                "results": result_payload,
                "seconds": round(time.perf_counter() - started_at, 2),
                "artifacts": {
                    "report": str(report_path),
                    "html": str(html_path),
                    "screenshot": str(screenshot_path) if screenshot_path.exists() else "",
                },
            }
            report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
    finally:
        await shutdown_browser_runtime()


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Live smoke for native Google search.")
    parser.add_argument("query", nargs="?", default="nike air max buy")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-results", type=int, default=1)
    parser.add_argument("--screenshot", action="store_true")
    args = parser.parse_args(argv)

    payload = await _run(
        str(args.query),
        limit=max(1, int(args.limit)),
        min_results=max(0, int(args.min_results)),
        screenshot=bool(args.screenshot),
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
