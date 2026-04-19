from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition import browser_runtime
from app.services.acquisition.traversal import TraversalResult
from app.services.config.runtime_settings import crawler_runtime_settings


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
    ) -> None:
        self.base_html = base_html
        self.expanded_html = expanded_html or base_html
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
        return self.expanded_html if self.expanded else self.base_html

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
    async def page(self):
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
    selectors = list(browser_runtime.CARD_SELECTORS.get("ecommerce") or [])
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
            role_targets={
                ("tab", "product specifications"),
                ("tab", "product dimensions"),
            },
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
            "domcontentloaded": PlaywrightTimeoutError("primary timeout"),
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

    assert page.goto_calls == ["domcontentloaded", "commit"]
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
