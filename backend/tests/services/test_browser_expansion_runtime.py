from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition.browser_capture import BrowserNetworkCapture
from app.services.acquisition import browser_page_flow, browser_runtime
from app.services.acquisition.traversal import TraversalResult
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS


@dataclass
class _FakeHandle:
    label: str
    page: "_FakeExpansionPage"
    actionable: bool = True

    async def evaluate(self, script: str) -> str | dict[str, bool] | None:
        if "pieces" in script:
            return self.label
        if "getBoundingClientRect" in script:
            return {"actionable": self.actionable}
        self.page.expanded = True
        return None

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def click(self, timeout: int | None = None) -> None:
        del timeout
        self.page.expanded = True


class _FakeLocator:
    def __init__(self, page: "_FakeExpansionPage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def element_handles(self) -> list[_FakeHandle]:
        if "button" not in self._selector and "summary" not in self._selector:
            return []
        return [
            _FakeHandle(
                row["label"],
                self._page,
                actionable=bool(row.get("actionable", True)),
            )
            for row in self._page.labels
        ]

    async def count(self) -> int:
        if self._selector in self._page.selector_counts:
            return int(self._page.selector_counts[self._selector])
        if self._selector in self._page.card_selectors:
            return int(self._page.card_count)
        return 0

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return await self.count() > 0

    async def is_disabled(self) -> bool:
        return False

    async def click(self, timeout: int | None = None) -> None:
        del timeout
        self._page.expanded = True


class _FakeRoleLocator:
    def __init__(self, page: "_FakeExpansionPage", role: str, name: str) -> None:
        self._page = page
        self._role = role
        self._name = name.lower()

    @property
    def first(self) -> "_FakeRoleLocator":
        return self

    async def count(self) -> int:
        return int((self._role, self._name) in self._page.role_targets)

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return await self.count() > 0

    async def is_disabled(self) -> bool:
        return False

    async def click(self, timeout: int | None = None) -> None:
        del timeout
        if (self._role, self._name) in self._page.role_targets:
            self._page.expanded = True


class _FakeExpansionPage:
    def __init__(
        self,
        *,
        base_html: str,
        expanded_html: str | None = None,
        labels: list[dict[str, object]] | None = None,
        selector_counts: dict[str, int] | None = None,
        card_count: int = 0,
        accessibility_snapshot: dict[str, object] | None = None,
        role_targets: set[tuple[str, str]] | None = None,
        goto_failures: dict[str, Exception] | None = None,
        response_events: list[Any] | None = None,
        wait_for_selector_error: Exception | None = None,
        shadow_html: str | None = None,
    ) -> None:
        self.base_html = base_html
        self.expanded_html = expanded_html or base_html
        self.shadow_html = shadow_html
        self.labels = list(labels or [])
        self.selector_counts = dict(selector_counts or {})
        self.card_count = int(card_count)
        self.expanded = False
        self.url = "https://example.com/products/widget"
        self.wait_timeout_calls: list[int] = []
        self.load_state_calls: list[str] = []
        self.card_selectors = set()
        self.role_targets = set(role_targets or set())
        self.goto_calls: list[str] = []
        self.goto_failures = dict(goto_failures or {})
        self.response_events = list(response_events or [])
        self.wait_for_selector_error = wait_for_selector_error
        self.wait_for_selector_calls: list[tuple[str, str | None, int | None]] = []
        self.listeners: dict[str, list[Any]] = {}
        self.accessibility = SimpleNamespace(
            snapshot=self._snapshot if accessibility_snapshot is not None else None
        )
        self._accessibility_snapshot = accessibility_snapshot
        self.shadow_flattened = False

    async def _snapshot(self) -> dict[str, object] | None:
        return self._accessibility_snapshot

    def on(self, event_name: str, callback: Any) -> None:
        self.listeners.setdefault(event_name, []).append(callback)

    def remove_listener(self, event_name: str, callback: Any) -> None:
        listeners = self.listeners.get(event_name)
        if not listeners:
            return
        self.listeners[event_name] = [
            listener for listener in listeners if listener is not callback
        ]

    async def goto(
        self,
        url: str,
        wait_until: str | None = None,
        timeout: int | None = None,
    ) -> Any:
        del timeout
        self.url = url
        strategy = str(wait_until or "")
        self.goto_calls.append(strategy)
        if strategy in self.goto_failures:
            raise self.goto_failures[strategy]
        for callback in list(self.listeners.get("response", [])):
            for response in self.response_events:
                callback(response)
        return SimpleNamespace(status=200, headers={"content-type": "text/html"})

    async def evaluate(self, script: str, arg: Any | None = None) -> Any:
        if "document.querySelectorAll('*')" in script and self.shadow_html is not None:
            self.shadow_flattened = True
            return 1
        if "querySelectorAll(selector).length" in script:
            selectors = list(arg or [])
            return max(
                (
                    int(self.selector_counts.get(selector, 0))
                    for selector in selectors
                ),
                default=0,
            )
        if "MutationObserver" in script:
            return {"observed": True}
        return None

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_timeout_calls.append(timeout_ms)

    async def wait_for_load_state(
        self,
        state: str,
        timeout: int | None = None,
    ) -> None:
        del timeout
        self.load_state_calls.append(state)

    async def wait_for_selector(
        self,
        selector: str,
        *,
        state: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.wait_for_selector_calls.append((selector, state, timeout))
        if self.wait_for_selector_error is not None:
            raise self.wait_for_selector_error

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def get_by_role(self, role: str, *, name: str, exact: bool = True) -> _FakeRoleLocator:
        del exact
        return _FakeRoleLocator(self, role, name)

    async def content(self) -> str:
        html = self.expanded_html if self.expanded else self.base_html
        if self.shadow_flattened and self.shadow_html is not None:
            return self.shadow_html
        return html

    async def screenshot(self, *, path: str | Path | None = None, **kwargs) -> bytes:
        del kwargs
        payload = b"fake-png"
        if path is not None:
            Path(path).write_bytes(payload)
        return payload


class _FakeRuntime:
    def __init__(self, page: _FakeExpansionPage) -> None:
        self._page = page

    @asynccontextmanager
    async def page(self, **_kwargs):
        yield self._page


@pytest.mark.asyncio
async def test_browser_fetch_fast_paths_ready_detail_without_extra_waits() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html>
          <head>
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Product","name":"Widget Prime"}
            </script>
          </head>
          <body>
            <h1>Widget Prime</h1>
            <div>Description</div>
          </body>
        </html>
        """,
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["phase_timings_ms"]["optimistic_wait"] == 0
    assert result.browser_diagnostics["phase_timings_ms"]["networkidle_wait"] == 0
    assert result.browser_diagnostics["phase_timings_ms"]["readiness_wait"] == 0
    assert result.browser_diagnostics["networkidle_skip_reason"] == "fast_path_ready"
    assert result.browser_diagnostics["detail_expansion"]["reason"] == "already_ready"
    assert page.wait_timeout_calls == []
    assert "networkidle" not in page.load_state_calls


@pytest.mark.asyncio
async def test_browser_fetch_fast_paths_ready_listing_cards_without_networkidle() -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html="<html><body><article class='product-card'>A</article></body></html>",
        selector_counts={selector: 3 for selector in selectors[:1]},
        card_count=3,
    )
    page.card_selectors = set(selectors)

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["phase_timings_ms"]["networkidle_wait"] == 0
    assert result.browser_diagnostics["detail_expansion"]["reason"] == "non_detail_surface"
    assert page.wait_timeout_calls == []
    assert page.load_state_calls == []


@pytest.mark.asyncio
async def test_browser_fetch_attempts_implicit_networkidle_for_unmatched_spa_listing() -> None:
    original_optimistic_wait_ms = (
        crawler_runtime_settings.browser_navigation_optimistic_wait_ms
    )
    original_implicit_networkidle_timeout_ms = (
        crawler_runtime_settings.browser_spa_implicit_networkidle_timeout_ms
    )
    try:
        crawler_runtime_settings.browser_navigation_optimistic_wait_ms = 25
        crawler_runtime_settings.browser_spa_implicit_networkidle_timeout_ms = 250
        page = _FakeExpansionPage(base_html="<html><body>Loading</body></html>")

        probe_results = iter(
            [
                {
                    "url": "https://example.com/spa/listing",
                    "surface": "ecommerce_listing",
                    "is_ready": False,
                    "detail_like": False,
                    "structured_data_present": False,
                    "visible_text_length": 20,
                    "detail_hint_count": 0,
                    "listing_card_count": 0,
                    "matched_listing_selectors": 0,
                    "h1_present": False,
                },
                {
                    "url": "https://example.com/spa/listing",
                    "surface": "ecommerce_listing",
                    "is_ready": False,
                    "detail_like": False,
                    "structured_data_present": False,
                    "visible_text_length": 24,
                    "detail_hint_count": 0,
                    "listing_card_count": 0,
                    "matched_listing_selectors": 0,
                    "h1_present": False,
                },
                {
                    "url": "https://example.com/spa/listing",
                    "surface": "ecommerce_listing",
                    "is_ready": True,
                    "detail_like": False,
                    "structured_data_present": False,
                    "visible_text_length": 260,
                    "detail_hint_count": 0,
                    "listing_card_count": 0,
                    "matched_listing_selectors": 0,
                    "h1_present": False,
                },
            ]
        )

        async def _fake_runtime():
            return _FakeRuntime(page)

        original_probe_browser_readiness = browser_runtime.probe_browser_readiness
        try:
            async def _fake_probe_browser_readiness(*args, **kwargs):
                del args, kwargs
                return next(probe_results)

            browser_runtime.probe_browser_readiness = _fake_probe_browser_readiness
            result = await browser_runtime.browser_fetch(
                "https://example.com/spa/listing",
                5,
                surface="ecommerce_listing",
                runtime_provider=_fake_runtime,
            )
        finally:
            browser_runtime.probe_browser_readiness = original_probe_browser_readiness

        assert result.browser_diagnostics["phase_timings_ms"]["optimistic_wait"] >= 0
        assert result.browser_diagnostics["phase_timings_ms"]["networkidle_wait"] >= 0
        assert page.wait_timeout_calls == [25]
        assert page.load_state_calls == ["networkidle"]
        assert result.browser_diagnostics["networkidle_skip_reason"] is None
    finally:
        crawler_runtime_settings.browser_navigation_optimistic_wait_ms = (
            original_optimistic_wait_ms
        )
        crawler_runtime_settings.browser_spa_implicit_networkidle_timeout_ms = (
            original_implicit_networkidle_timeout_ms
        )


@pytest.mark.asyncio
async def test_probe_browser_readiness_uses_visible_text_fallback_for_unmatched_listing() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body>" + ("Catalog entry " * 40) + "</body></html>",
    )

    probe = await browser_runtime.probe_browser_readiness(
        page,
        url="https://example.com/catalog",
        surface="ecommerce_listing",
        listing_override=None,
    )

    assert probe["listing_card_count"] == 0
    assert probe["matched_listing_selectors"] == 0
    assert probe["visible_text_length"] >= (
        int(crawler_runtime_settings.browser_readiness_visible_text_min) * 2
    )
    assert probe["is_ready"] is True


@pytest.mark.asyncio
async def test_browser_fetch_bounds_response_capture_workers_under_burst_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        def __init__(self, index: int) -> None:
            self.url = f"https://example.com/api/{index}"
            self.headers = {"content-type": "application/json"}
            self.request = SimpleNamespace(method="GET")
            self.status = 200

    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        response_events=[_FakeResponse(index) for index in range(200)],
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    async def _fake_read_network_payload_body(response, **_kwargs):
        return browser_runtime.NetworkPayloadReadResult(
            body=f'{{"id": "{response.url}"}}'.encode("utf-8"),
            outcome="ok",
        )

    create_task_calls = 0
    original_create_task = browser_runtime.asyncio.create_task

    def _counting_create_task(coro):
        nonlocal create_task_calls
        create_task_calls += 1
        return original_create_task(coro)

    monkeypatch.setattr(browser_runtime.asyncio, "create_task", _counting_create_task)
    monkeypatch.setattr(
        browser_runtime,
        "should_capture_network_payload",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        browser_runtime,
        "read_network_payload_body",
        _fake_read_network_payload_body,
    )
    monkeypatch.setattr(
        browser_runtime,
        "classify_network_endpoint",
        lambda **kwargs: {"type": "api", "family": "generic"},
    )

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert create_task_calls == browser_runtime._NETWORK_CAPTURE_WORKERS
    assert len(result.network_payloads) == browser_runtime._MAX_CAPTURED_NETWORK_PAYLOADS
    assert (
        result.browser_diagnostics["dropped_network_payload_events"]
        >= 200 - browser_runtime._NETWORK_CAPTURE_QUEUE_SIZE
    )


@pytest.mark.asyncio
async def test_browser_fetch_expands_detail_accordions_before_collecting_html() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><details><summary>Specifications</summary></details></body></html>",
        expanded_html="""
        <html><body>
          <details open><summary>Specifications</summary>
            <div class="product-features">Rubber outsole, reinforced toe cap.</div>
          </details>
        </body></html>
        """,
        labels=[{"label": "product specifications"}, {"label": "share"}],
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert "Rubber outsole" in result.html
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 1
    assert result.browser_diagnostics["detail_expansion"]["expanded_elements"] == [
        "product specifications"
    ]


@pytest.mark.asyncio
async def test_browser_fetch_flattens_shadow_dom_before_serializing_html() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><shop-product></shop-product></body></html>",
        shadow_html=(
            "<html><body><shop-product></shop-product>"
            "<section class='specifications'>Shadow DOM specifications</section>"
            "</body></html>"
        ),
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert page.shadow_flattened is True
    assert "Shadow DOM specifications" in result.html


@pytest.mark.asyncio
async def test_browser_fetch_uses_aom_expansion_when_dom_keyword_scan_misses() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1><div>Overview</div></body></html>",
        expanded_html="""
        <html><body>
          <h1>Widget Prime</h1>
          <div>Overview</div>
          <section>Specifications</section>
          <div>Rubber outsole, reinforced toe cap.</div>
        </body></html>
        """,
        labels=[{"label": "share"}],
        accessibility_snapshot={
            "role": "document",
            "children": [
                {"role": "tab", "name": "Product specifications"},
                {"role": "button", "name": "Share"},
            ],
        },
        role_targets={("tab", "product specifications")},
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert "Rubber outsole" in result.html
    assert result.browser_diagnostics["detail_expansion"]["dom"]["clicked_count"] == 0
    assert result.browser_diagnostics["detail_expansion"]["aom"]["clicked_count"] == 1
    assert result.browser_diagnostics["detail_expansion"]["reason"] == "missing_detail_content"


@pytest.mark.asyncio
async def test_browser_fetch_aom_expansion_respects_interaction_cap() -> None:
    original_limit = crawler_runtime_settings.detail_aom_expand_max_interactions
    crawler_runtime_settings.detail_aom_expand_max_interactions = 1
    try:
        page = _FakeExpansionPage(
            base_html="<html><body><h1>Widget Prime</h1><div>Overview</div></body></html>",
            expanded_html="""
            <html><body>
              <h1>Widget Prime</h1>
              <div>Specifications</div>
              <div>Rubber outsole, reinforced toe cap.</div>
            </body></html>
            """,
            labels=[{"label": "share"}],
            accessibility_snapshot={
                "role": "document",
                "children": [
                    {"role": "tab", "name": "Product specifications"},
                    {"role": "tab", "name": "Product dimensions"},
                ],
            },
            role_targets={("tab", "product specifications")},
        )

        async def _fake_runtime():
            return _FakeRuntime(page)

        result = await browser_runtime.browser_fetch(
            "https://example.com/products/widget",
            5,
            surface="ecommerce_detail",
            runtime_provider=_fake_runtime,
        )

        assert "Rubber outsole" in result.html
        assert result.browser_diagnostics["detail_expansion"]["aom"]["limit"] == 1
        assert result.browser_diagnostics["detail_expansion"]["aom"]["clicked_count"] == 1
        assert result.browser_diagnostics["detail_expansion"]["aom"]["attempted"] is True
    finally:
        crawler_runtime_settings.detail_aom_expand_max_interactions = original_limit


@pytest.mark.asyncio
async def test_expand_detail_content_if_needed_skips_non_detail_like_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_dom_expand(*args, **kwargs):
        raise AssertionError("DOM expansion should be skipped")

    monkeypatch.setattr(
        browser_runtime,
        "expand_all_interactive_elements",
        _unexpected_dom_expand,
    )

    diagnostics = await browser_runtime.expand_detail_content_if_needed(
        _FakeExpansionPage(base_html="<html><body></body></html>"),
        surface="ecommerce_detail",
        readiness_probe={"is_ready": False, "detail_like": False},
    )

    assert diagnostics["status"] == "skipped"
    assert diagnostics["reason"] == "not_detail_like"


@pytest.mark.asyncio
async def test_listing_card_signal_count_avoids_heuristic_card_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def _fake_count_listing_cards(page, *, surface: str, allow_heuristic: bool = True) -> int:
        del page, surface
        calls.append(bool(allow_heuristic))
        return 9 if allow_heuristic else 0

    monkeypatch.setattr(browser_runtime, "count_listing_cards", _fake_count_listing_cards)
    monkeypatch.setattr(
        browser_runtime,
        "CARD_SELECTORS",
        {"ecommerce": [".product-card"], "jobs": [".job-card"]},
    )

    count = await browser_runtime.listing_card_signal_count(
        _FakeExpansionPage(base_html="<html><body></body></html>"),
        surface="ecommerce_listing",
    )

    assert count == 0
    assert calls == [False]


@pytest.mark.asyncio
async def test_browser_capture_close_drains_inflight_response_callbacks() -> None:
    class _FakeResponse:
        url = "https://example.com/api/product"
        headers = {"content-type": "application/json"}
        request = SimpleNamespace(method="GET")
        status = 200

    class _LateDispatchPage:
        def __init__(self) -> None:
            self.listener = None

        def on(self, event_name: str, callback: Any) -> None:
            assert event_name == "response"
            self.listener = callback

        def remove_listener(self, event_name: str, callback: Any) -> None:
            assert event_name == "response"
            self.listener = None
            asyncio.get_running_loop().call_soon(callback, _FakeResponse())

    async def _fake_read_payload_body(response, **_kwargs):
        del response
        return browser_runtime.NetworkPayloadReadResult(
            body=b'{"id":"captured"}',
            outcome="ok",
        )

    capture = BrowserNetworkCapture(
        surface="ecommerce_detail",
        should_capture_payload=lambda **_kwargs: True,
        classify_endpoint=lambda **_kwargs: {"type": "api", "family": "generic"},
        read_payload_body=_fake_read_payload_body,
    )
    page = _LateDispatchPage()
    capture.attach(page)

    summary = await capture.close(page)

    assert summary.network_payload_count == 1
    assert summary.payloads[0]["body"]["id"] == "captured"


@pytest.mark.asyncio
async def test_browser_capture_decodes_react_server_component_payloads() -> None:
    class _RscResponse:
        def __init__(self) -> None:
            self.url = "https://example.com/products/widget"
            self.status = 200
            self.headers = {"content-type": "text/x-component"}
            self.request = SimpleNamespace(method="GET")

        async def body(self) -> bytes:
            return (
                b'0:["$","$L1",null,{"title":"Trail Runner","price":"109.00"}]\n'
                b'1:{"product":{"title":"Trail Runner","sku":"TRAIL-1"}}\n'
            )

    page = _FakeExpansionPage(base_html="<html><body></body></html>")
    capture = BrowserNetworkCapture(surface="ecommerce_detail")
    capture.attach(page)

    listeners = page.listeners.get("response") or []
    assert listeners
    listeners[0](_RscResponse())

    summary = await capture.close(page)

    assert summary.network_payload_count == 1
    assert summary.malformed_network_payloads == 0
    assert isinstance(summary.payloads[0]["body"], list)
    assert summary.payloads[0]["body"][0][3]["title"] == "Trail Runner"
    assert summary.payloads[0]["body"][1]["product"]["sku"] == "TRAIL-1"


@pytest.mark.asyncio
async def test_browser_capture_close_uses_bounded_queue_join_timeout() -> None:
    original_timeout_ms = crawler_runtime_settings.browser_capture_queue_join_timeout_ms
    crawler_runtime_settings.browser_capture_queue_join_timeout_ms = 50
    try:
        capture = BrowserNetworkCapture(
            surface="ecommerce_detail",
            should_capture_payload=lambda **_kwargs: True,
            classify_endpoint=lambda **_kwargs: {"type": "api", "family": "generic"},
            read_payload_body=lambda *_args, **_kwargs: browser_runtime.NetworkPayloadReadResult(
                body=b'{"id":"captured"}',
                outcome="ok",
            ),
        )
        page = _FakeExpansionPage(base_html="<html><body></body></html>")
        capture.attach(page)

        async def _stalled_join() -> None:
            await asyncio.sleep(1)

        capture._queue.join = _stalled_join  # type: ignore[method-assign]

        started_at = asyncio.get_running_loop().time()
        summary = await capture.close(page)
        elapsed = asyncio.get_running_loop().time() - started_at

        assert summary.network_payload_count == 0
        assert elapsed < 0.5
    finally:
        crawler_runtime_settings.browser_capture_queue_join_timeout_ms = original_timeout_ms


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_respects_small_interaction_cap() -> None:
    original_limit = crawler_runtime_settings.detail_expand_max_interactions
    crawler_runtime_settings.detail_expand_max_interactions = 1
    try:
        page = _FakeExpansionPage(
            base_html="<html><body></body></html>",
            labels=[
                {"label": "product details"},
                {"label": "product dimensions"},
            ],
        )
        diagnostics = await browser_runtime.expand_all_interactive_elements(
            page,
            surface="ecommerce_detail",
        )

        assert diagnostics["limit"] == 1
        assert diagnostics["clicked_count"] == 1
        assert diagnostics["expanded_elements"] == ["product details"]
    finally:
        crawler_runtime_settings.detail_expand_max_interactions = original_limit


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_skips_non_actionable_candidates() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {"label": "product details", "actionable": False},
            {"label": "product specifications", "actionable": True},
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["product specifications"]


def test_classify_browser_outcome_marks_empty_category_as_low_content_shell() -> None:
    html = "<html><body><h1>Empty category</h1></body></html>"

    outcome = browser_runtime.classify_browser_outcome(
        html=html,
        html_bytes=len(html.encode("utf-8")),
        blocked=False,
    )

    assert outcome == "low_content_shell"
    assert browser_runtime.classify_low_content_reason(
        html,
        html_bytes=len(html.encode("utf-8")),
    ) == "empty_terminal_page"


def test_build_failed_browser_diagnostics_marks_page_closed_explicitly() -> None:
    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=RuntimeError("Target closed"),
    )

    assert diagnostics["browser_outcome"] == "navigation_failed"
    assert diagnostics["failure_kind"] == "page_closed"
    assert diagnostics["failure_stage"] == "navigation"


def test_build_failed_browser_diagnostics_marks_timeout_explicitly() -> None:
    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=TimeoutError("navigation timeout"),
    )

    assert diagnostics["browser_outcome"] == "render_timeout"
    assert diagnostics["failure_kind"] == "timeout"


@pytest.mark.asyncio
async def test_browser_fetch_logs_non_usable_outcomes(caplog: pytest.LogCaptureFixture) -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Empty category</h1></body></html>")

    async def _fake_runtime():
        return _FakeRuntime(page)

    with caplog.at_level("WARNING", logger=browser_page_flow.logger.name):
        result = await browser_runtime.browser_fetch(
            "https://example.com/empty",
            5,
            surface="ecommerce_listing",
            runtime_provider=_fake_runtime,
        )

    assert result.browser_diagnostics["browser_outcome"] == "low_content_shell"
    assert any(
        "Browser acquisition outcome=low_content_shell url=https://example.com/empty"
        in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_wait_for_listing_readiness_treats_only_playwright_timeout_as_recoverable() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        wait_for_selector_error=PlaywrightTimeoutError("listing readiness timeout"),
    )

    diagnostics = await browser_runtime._wait_for_listing_readiness(
        page,
        override={
            "platform": "example",
            "selectors": [".listing-card"],
            "max_wait_ms": 250,
        },
    )

    assert diagnostics["status"] == "timed_out"
    assert diagnostics["attempted_selectors"] == [".listing-card"]


@pytest.mark.asyncio
async def test_wait_for_listing_readiness_propagates_browser_closure() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        wait_for_selector_error=PlaywrightError(
            "Target page, context or browser has been closed"
        ),
    )

    with pytest.raises(PlaywrightError, match="closed"):
        await browser_runtime._wait_for_listing_readiness(
            page,
            override={
                "platform": "example",
                "selectors": [".listing-card"],
                "max_wait_ms": 250,
            },
        )


@pytest.mark.asyncio
async def test_browser_fetch_records_navigation_timing_when_fallback_navigation_fails() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body>Widget</body></html>",
        goto_failures={
            "networkidle": PlaywrightTimeoutError("primary timeout"),
            "domcontentloaded": PlaywrightError("secondary fallback failed"),
            "commit": PlaywrightError("fallback failed"),
        },
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    with pytest.raises(PlaywrightError, match="fallback failed") as excinfo:
        await browser_runtime.browser_fetch(
            "https://example.com/products/widget",
            5,
            surface="ecommerce_detail",
            browser_reason="http-escalation",
            runtime_provider=_fake_runtime,
        )

    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=excinfo.value,
    )

    assert page.goto_calls == ["networkidle", "domcontentloaded", "commit"]
    assert diagnostics["navigation_strategy"] == "commit"
    assert diagnostics["phase_timings_ms"]["navigation"] >= 0


@pytest.mark.asyncio
async def test_browser_fetch_surfaces_traversal_fragment_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>"
            "</body></html>"
        ),
        selector_counts={".product-card": 2},
        card_count=2,
    )
    page.url = "https://example.com/collections/widgets"

    async def _fake_runtime():
        return _FakeRuntime(page)

    async def _fake_execute_listing_traversal(*args, **kwargs):
        del args, kwargs
        return TraversalResult(
            requested_mode="paginate",
            selected_mode="paginate",
            activated=True,
            progress_events=1,
            pages_advanced=1,
            card_count=2,
            html_fragments=[
                ("<div data-traversal-cards='true'><article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article></div>", False),
                ("<div data-traversal-cards='true'><article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article></div>", False),
            ],
        )

    monkeypatch.setattr(
        browser_runtime,
        "execute_listing_traversal",
        _fake_execute_listing_traversal,
    )

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["traversal_fragment_count"] == 2
    assert result.browser_diagnostics["traversal_html_bytes"] == sum(
        len(fragment.encode("utf-8"))
        for fragment in [
            "<div data-traversal-cards='true'><article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article></div>",
            "<div data-traversal-cards='true'><article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article></div>",
        ]
    )
    assert 'data-traversal-fragment="1"' in result.html
    assert 'data-traversal-fragment="2"' in result.html
