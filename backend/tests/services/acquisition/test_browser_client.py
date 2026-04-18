from __future__ import annotations

import asyncio
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.services.acquisition import browser_client
from app.services.acquisition import browser_challenge
from app.services.acquisition import browser_pool
from app.services.acquisition import policy
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/listing"
        self.unroute_all = AsyncMock()

    async def route(self, _pattern, _handler) -> None:
        return None

    def on(self, _event, _handler) -> None:
        return None


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.close = AsyncMock()
        self.add_init_script = AsyncMock()

    async def new_page(self) -> _FakePage:
        return self._page


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context

    async def new_context(self, **_kwargs) -> _FakeContext:
        return self._context


@pytest.mark.asyncio
async def test_teardown_page_session_unroutes_before_context_close() -> None:
    page = _FakePage()
    context = _FakeContext(page)

    await browser_client._teardown_page_session(page, context)

    page.unroute_all.assert_awaited_once_with(behavior="ignoreErrors")
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_abort_route_ignores_closed_target_error() -> None:
    route = SimpleNamespace(
        abort=AsyncMock(
            side_effect=PlaywrightError(
                "Route.abort: Target page, context or browser has been closed"
            )
        )
    )

    await browser_client._abort_route(route, "blockedbyclient")

    route.abort.assert_awaited_once_with("blockedbyclient")


@pytest.mark.asyncio
async def test_browser_pool_healthcheck_task_restarts_after_unexpected_crash(
    monkeypatch: pytest.MonkeyPatch,
):
    await browser_pool.reset_browser_pool_state()
    state = browser_pool._browser_pool_state()
    loop = asyncio.get_running_loop()
    restarted = asyncio.Event()

    async def _crash() -> None:
        raise RuntimeError("boom")

    async def _replacement_healthcheck_loop() -> None:
        restarted.set()
        await asyncio.Future()

    monkeypatch.setattr(
        browser_pool,
        "_browser_pool_healthcheck_loop",
        _replacement_healthcheck_loop,
    )

    task = loop.create_task(_crash(), name="browser-pool-healthcheck-test-crash")
    task.add_done_callback(browser_pool._browser_pool_healthcheck_done)
    state.cleanup_task = task

    await asyncio.wait_for(restarted.wait(), timeout=1.0)

    restarted_task = browser_pool._browser_pool_state().cleanup_task
    assert restarted_task is not None
    assert restarted_task is not task
    assert not restarted_task.done()

    restarted_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await restarted_task


def test_kill_orphaned_browser_processes_uses_registry_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_dir = browser_pool.Path("backend/.codex-test-browser-pool") / uuid4().hex
    try:
        record = browser_pool._BrowserProcessRecord(
            record_id="dead-owner-browser",
            owner_pid=111,
            owner_create_time=1.0,
            browser_pid=222,
            browser_create_time=2.0,
        )
        browser_pool._BROWSER_PROCESS_REGISTRY_DIR = registry_dir
        browser_pool._write_browser_process_record(record)

        killed: list[int] = []

        class _FakeBrowserProcess:
            pid = 222

            def name(self) -> str:
                return "chromium"

        def _fake_process_matches_create_time(pid: int, expected_create_time: float):
            if (pid, expected_create_time) == (111, 1.0):
                return None
            if (pid, expected_create_time) == (222, 2.0):
                return _FakeBrowserProcess()
            return None

        def _fake_kill_browser_process_tree(process) -> int:
            killed.append(process.pid)
            return 1

        monkeypatch.setattr(browser_pool.os, "getpid", lambda: 333)
        monkeypatch.setattr(
            browser_pool,
            "_process_matches_create_time",
            _fake_process_matches_create_time,
        )
        monkeypatch.setattr(
            browser_pool,
            "_kill_browser_process_tree",
            _fake_kill_browser_process_tree,
        )

        browser_pool._kill_orphaned_browser_processes()

        assert killed == [222]
        assert list(registry_dir.glob("*.json")) == []
    finally:
        shutil.rmtree(registry_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_wait_for_challenge_resolution_treats_content_read_failure_as_unsuccessful() -> None:
    class _BrokenPage:
        async def content(self):
            raise PlaywrightError("content failed")

    ok, state, reasons = await browser_challenge._wait_for_challenge_resolution(
        _BrokenPage()
    )

    assert ok is False
    assert state == "page_content_unavailable"
    assert reasons == ["page_content_read_failed"]


def test_assess_challenge_signals_waits_on_weak_markers() -> None:
    original = browser_challenge.detect_blocked_page
    browser_challenge.detect_blocked_page = lambda _html: SimpleNamespace(
        is_blocked=False,
        provider=None,
    )
    try:
        assessment = browser_challenge._assess_challenge_signals(
            "<html><body><h1>One more step</h1>" + ("x" * 3000) + "</body></html>"
        )
    finally:
        browser_challenge.detect_blocked_page = original

    assert assessment.should_wait is True
    assert assessment.state == "waiting_unresolved"


@pytest.mark.asyncio
async def test_fetch_rendered_html_retries_profile_after_playwright_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = browser_client.BrowserResult(html="<html><body>ok</body></html>")
    attempts = iter(
        [
            PlaywrightTimeoutError("nav timeout"),
            result,
        ]
    )

    async def _fake_attempt(_pw, _attempt):
        current = next(attempts)
        if isinstance(current, Exception):
            raise current
        return current

    monkeypatch.setattr(
        browser_client,
        "_browser_launch_profiles",
        lambda *_args, **_kwargs: [
            {"label": "p1", "channel": None},
            {"label": "p2", "channel": None},
        ],
    )
    monkeypatch.setattr(browser_client, "_fetch_rendered_html_attempt", _fake_attempt)

    output = await browser_client._fetch_rendered_html_with_fallback(
        SimpleNamespace(),
        browser_client.BrowserRenderRequest(
            target=SimpleNamespace(),
            url="https://example.com",
            plan=policy.plan_acquisition(
                SimpleNamespace(url="https://example.com", surface="ecommerce_detail")
            ),
            proxy=None,
            surface="ecommerce_detail",
            traversal_mode=None,
            max_pages=1,
            max_scrolls=1,
            prefer_stealth=False,
            request_delay_ms=0,
            runtime_options=BrowserRuntimeOptions(retry_launch_profiles=True),
        ),
    )

    assert output is result
    assert output.diagnostics["attempted_browser_profiles"] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_fetch_rendered_html_falls_back_after_not_implemented_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = browser_client.BrowserResult(html="<html><body>ok</body></html>")
    attempts = iter(
        [
            NotImplementedError(),
            result,
        ]
    )

    async def _fake_attempt(_pw, _attempt):
        current = next(attempts)
        if isinstance(current, Exception):
            raise current
        return current

    monkeypatch.setattr(
        browser_client,
        "_browser_launch_profiles",
        lambda *_args, **_kwargs: [
            {"label": "system_chrome", "channel": "chrome"},
            {"label": "bundled_chromium", "channel": None},
        ],
    )
    monkeypatch.setattr(browser_client, "_fetch_rendered_html_attempt", _fake_attempt)

    output = await browser_client._fetch_rendered_html_with_fallback(
        SimpleNamespace(),
        browser_client.BrowserRenderRequest(
            target=SimpleNamespace(),
            url="https://example.com",
            plan=policy.plan_acquisition(
                SimpleNamespace(url="https://example.com", surface="ecommerce_detail")
            ),
            proxy=None,
            surface="ecommerce_detail",
            traversal_mode=None,
            max_pages=1,
            max_scrolls=1,
            prefer_stealth=False,
            request_delay_ms=0,
            runtime_options=BrowserRuntimeOptions(retry_launch_profiles=True),
        ),
    )

    assert output is result
    assert output.diagnostics["browser_launch_profile"] == "bundled_chromium"
    assert output.diagnostics["attempted_browser_profiles"] == [
        "system_chrome",
        "bundled_chromium",
    ]
    assert output.diagnostics["system_chrome_attempted"] is True
    assert output.diagnostics["bundled_chromium_attempted"] is True


@pytest.mark.asyncio
async def test_apply_browser_stealth_uses_session_fingerprint_overrides() -> None:
    context = SimpleNamespace(add_init_script=AsyncMock())
    session_context = SimpleNamespace(
        fingerprint=SimpleNamespace(
            locale="en-GB",
            platform="MacIntel",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
    )

    applied = await browser_client.apply_browser_stealth(
        context,
        session_context=session_context,
    )

    assert applied is True
    context.add_init_script.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_browser_automation_surfaces_returns_page_evaluation() -> None:
    expected = {
        "navigator_webdriver": False,
        "chrome_present": True,
        "chrome_runtime_present": True,
    }
    page = SimpleNamespace(evaluate=AsyncMock(return_value=expected))

    result = await browser_client.probe_browser_automation_surfaces(page)

    assert result is expected
    page.evaluate.assert_awaited_once()


def test_record_partial_traversal_progress_tracks_captured_pages() -> None:
    diagnostics: dict[str, object] = {}

    browser_client._record_partial_traversal_progress(
        diagnostics,
        traversal_mode="auto",
        message="paginate:capture page=2 mode=full_page html_length=12345",
    )

    traversal_summary = diagnostics["traversal_summary"]
    assert traversal_summary["attempted"] is True
    assert traversal_summary["mode_used"] == "paginate"
    assert traversal_summary["pages_collected"] == 2
    assert traversal_summary["fallback_used"] is False


@pytest.mark.asyncio
async def test_populate_result_records_blocked_diagnostics_as_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = browser_client.BrowserResult()
    page = SimpleNamespace(url="https://example.com/item")

    async def _fake_collect_frame_sources(_page):
        return (
            "<html><title>Access denied</title><body>"
            + ("captcha gate " * 20)
            + "</body></html>",
            [],
            [],
        )

    monkeypatch.setattr(
        browser_client,
        "_collect_frame_sources",
        _fake_collect_frame_sources,
    )

    await browser_client._populate_result(result, page, [])

    assert result.diagnostics["blocked"] == {
        "is_blocked": True,
        "reason": "blocked_phrase:403_forbidden",
        "provider": "origin",
    }
