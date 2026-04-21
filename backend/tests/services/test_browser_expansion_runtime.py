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
from app.services.acquisition import browser_page_flow, browser_readiness, browser_runtime
from app.services.acquisition.traversal import TraversalResult
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS


@dataclass
class _FakeHandle:
    label: str
    page: "_FakeExpansionPage"
    attributes: dict[str, str]
    tag_name: str = "button"
    actionable: bool = True

    async def evaluate(self, script: str) -> str | dict[str, bool] | None:
        if "pieces" in script:
            return self.label
        if "tagName" in script:
            return self.tag_name
        if "getBoundingClientRect" in script:
            return {"actionable": self.actionable}
        self.page.expanded = True
        return None

    async def inner_text(self) -> str:
        return self.label

    async def get_attribute(self, name: str) -> str | None:
        return self.attributes.get(name)

    async def is_visible(self) -> bool:
        return self.actionable

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
        handles: list[_FakeHandle] = []
        for row in self._page.labels:
            attributes = {
                str(key): str(value)
                for key, value in dict(row.get("attributes", {})).items()
            }
            tag_name = str(row.get("tag_name", "button"))
            if not self._matches_selector(tag_name, attributes):
                continue
            handles.append(
                _FakeHandle(
                    row["label"],
                    self._page,
                    attributes=attributes,
                    tag_name=tag_name,
                    actionable=bool(row.get("actionable", True)),
                )
            )
        return handles

    def _matches_selector(
        self,
        tag_name: str,
        attributes: dict[str, str],
    ) -> bool:
        selector = self._selector
        role = str(attributes.get("role") or "").lower()
        aria_controls = str(attributes.get("aria-controls") or "")
        aria_expanded = str(attributes.get("aria-expanded") or "").lower()
        lowered_tag = tag_name.lower()
        if selector == "summary" or selector == "details > summary":
            return lowered_tag == "summary"
        if selector == "[aria-expanded='false']":
            return aria_expanded == "false"
        if selector == "button[aria-controls]":
            return lowered_tag == "button" and bool(aria_controls)
        if selector == "[role='button'][aria-controls]":
            return role == "button" and bool(aria_controls)
        if selector == "[role='tab'][aria-controls]":
            return role == "tab" and bool(aria_controls)
        if selector == "button":
            return lowered_tag == "button"
        if selector == "[role='button']":
            return role == "button"
        if selector == "a":
            return lowered_tag == "a"
        return False

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
        rendered_listing_cards: list[dict[str, object]] | None = None,
        wait_html_sequence: list[str] | None = None,
        cookie_snapshots: list[list[dict[str, object]]] | None = None,
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
        self.rendered_listing_cards = list(rendered_listing_cards or [])
        self.wait_html_sequence = list(wait_html_sequence or [])
        self.cookie_snapshots = list(cookie_snapshots or [[]])
        self.accessibility = SimpleNamespace(
            snapshot=self._snapshot if accessibility_snapshot is not None else None
        )
        self._accessibility_snapshot = accessibility_snapshot
        self.shadow_flattened = False
        self.context = SimpleNamespace(cookies=self._cookies)

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

    async def _cookies(self, *_args, **_kwargs) -> list[dict[str, object]]:
        return list(self.cookie_snapshots[0] if self.cookie_snapshots else [])

    async def evaluate(self, script: str, arg: Any | None = None) -> Any:
        if "document.querySelectorAll('*')" in script and self.shadow_html is not None:
            self.shadow_flattened = True
            return 1
        if "const cardSelectors" in script:
            return list(self.rendered_listing_cards)
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
        if self.wait_html_sequence:
            next_html = self.wait_html_sequence.pop(0)
            self.base_html = next_html
            self.expanded_html = next_html
        if len(self.cookie_snapshots) > 1:
            self.cookie_snapshots.pop(0)

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
    assert result.browser_diagnostics["detail_expansion"]["reason"] == "missing_detail_content"
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 0
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
async def test_browser_fetch_expands_requested_field_sections_even_when_probe_is_ready() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1><button>Materials</button></body></html>",
        expanded_html="""
        <html><body>
          <h1>Widget Prime</h1>
          <button aria-controls="materials-panel">Materials</button>
          <section id="materials-panel">Full-grain leather upper.</section>
        </body></html>
        """,
        labels=[
            {
                "label": "materials",
                "attributes": {"aria-controls": "materials-panel"},
            }
        ],
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        requested_fields=["materials"],
        runtime_provider=_fake_runtime,
    )

    assert "Full-grain leather upper." in result.html
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 1


@pytest.mark.asyncio
async def test_expand_detail_content_if_needed_skips_aom_when_page_is_already_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_aom(*args, **kwargs):
        raise AssertionError("AOM expansion should be skipped")

    monkeypatch.setattr(
        browser_runtime,
        "expand_interactive_elements_via_accessibility",
        _unexpected_aom,
    )

    diagnostics = await browser_runtime.expand_detail_content_if_needed(
        _FakeExpansionPage(base_html="<html><body><h1>Widget Prime</h1></body></html>"),
        surface="ecommerce_detail",
        readiness_probe={"is_ready": True, "detail_like": True},
    )

    assert diagnostics["aom"]["status"] == "skipped"
    assert diagnostics["aom"]["reason"] == "not_needed"


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_skips_blocked_commerce_actions() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {"label": "add to cart"},
            {
                "label": "materials",
                "attributes": {"aria-controls": "materials-panel"},
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["materials"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["materials"]


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_scans_past_non_expandable_early_candidates() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {"label": "add to cart"},
            {"label": "materials", "actionable": False},
            {
                "label": "materials",
                "attributes": {"aria-controls": "materials-panel"},
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["materials"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["materials"]


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
async def test_browser_fetch_populates_page_markdown_for_existing_markdown_view() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html>
          <body>
            <header>Brand header</header>
            <main>
              <h1>Widget Prime</h1>
              <p>Built for long mileage.</p>
              <a href="/products/widget/specs">View specs</a>
            </main>
          </body>
        </html>
        """,
        accessibility_snapshot={
            "role": "document",
            "children": [
                {"role": "heading", "name": "Widget Prime"},
                {"role": "link", "name": "View specs"},
            ],
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

    assert "Widget Prime" in result.page_markdown
    assert "Built for long mileage." in result.page_markdown
    assert "Visible links:" in result.page_markdown
    assert "SEMANTIC ACCESSIBILITY SNAPSHOT" in result.page_markdown


@pytest.mark.asyncio
async def test_browser_fetch_captures_rendered_listing_cards_artifact() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html>
          <body>
            <article class="product-card">
              <a href="/products/widget-prime"><h2>Widget Prime</h2></a>
              <div class="price">$19.99</div>
              <img src="/images/widget-prime.jpg" alt="Widget Prime" />
            </article>
          </body>
        </html>
        """,
        rendered_listing_cards=[
            {
                "title": "Widget Prime",
                "url": "https://example.com/products/widget-prime",
                "price": "$19.99",
                "image_url": "https://example.com/images/widget-prime.jpg",
                "brand": "",
            }
        ],
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.artifacts["rendered_listing_cards"] == [
        {
            "title": "Widget Prime",
            "url": "https://example.com/products/widget-prime",
            "price": "$19.99",
            "image_url": "https://example.com/images/widget-prime.jpg",
            "brand": "",
        }
    ]


@pytest.mark.asyncio
async def test_generate_page_markdown_tolerates_nodes_with_missing_attrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_beautifulsoup = browser_page_flow.BeautifulSoup

    def _broken_attr_soup(*args, **kwargs):
        soup = original_beautifulsoup(*args, **kwargs)
        broken = soup.select_one("div")
        assert broken is not None
        broken.attrs = None
        return soup

    monkeypatch.setattr(browser_page_flow, "BeautifulSoup", _broken_attr_soup)

    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(
            base_html="<html><body><div class='hero'>Widget Prime</div></body></html>"
        ),
        html="<html><body><div class='hero'>Widget Prime</div></body></html>",
    )

    assert "Widget Prime" in markdown


@pytest.mark.asyncio
async def test_generate_page_markdown_prefers_main_content_over_open_dialog_noise() -> None:
    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(
            base_html="""
            <html>
              <body>
                <div role="dialog" aria-label="Category menu">
                  <p>WOMAN MAN KIDS BEST SELLERS TOPS SHIRTS</p>
                </div>
                <main>
                  <h1>Widget Prime</h1>
                  <p>Built for long mileage.</p>
                </main>
              </body>
            </html>
            """
        ),
        html="""
        <html>
          <body>
            <div role="dialog" aria-label="Category menu">
              <p>WOMAN MAN KIDS BEST SELLERS TOPS SHIRTS</p>
            </div>
            <main>
              <h1>Widget Prime</h1>
              <p>Built for long mileage.</p>
            </main>
          </body>
        </html>
        """,
    )

    assert "Widget Prime" in markdown
    assert "Built for long mileage." in markdown
    assert "BEST SELLERS" not in markdown


@pytest.mark.asyncio
async def test_generate_page_markdown_falls_back_to_body_when_main_is_too_narrow() -> None:
    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(
            base_html="""
            <html>
              <body>
                <main>
                  <h1>Widget Prime</h1>
                  <p>Built for long mileage with a stable midsole and grippy outsole.</p>
                </main>
                <section>
                  <p>Support, returns, and care instructions live outside the main container.</p>
                  <a href="/support/returns">Returns and exchanges</a>
                </section>
              </body>
            </html>
            """
        ),
        html="""
        <html>
          <body>
            <main>
              <h1>Widget Prime</h1>
              <p>Built for long mileage with a stable midsole and grippy outsole.</p>
            </main>
            <section>
              <p>Support, returns, and care instructions live outside the main container.</p>
              <a href="/support/returns">Returns and exchanges</a>
            </section>
          </body>
        </html>
        """,
    )

    assert "Widget Prime" in markdown
    assert "Support, returns, and care instructions live outside the main container." in markdown
    assert "Returns and exchanges -> /support/returns" in markdown


@pytest.mark.asyncio
async def test_generate_page_markdown_falls_back_to_body_when_main_omits_relevant_links() -> None:
    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(
            base_html="""
            <html>
              <body>
                <main>
                  <h1>Widget Prime</h1>
                  <p>Built for long mileage with a stable midsole and grippy outsole.</p>
                  <p>Breathable mesh upper with protective rand and reinforced heel counter.</p>
                </main>
                <aside>
                  <p>Support and care guidance lives outside the main container.</p>
                  <a href="/support/care">Care instructions</a>
                </aside>
              </body>
            </html>
            """
        ),
        html="""
        <html>
          <body>
            <main>
              <h1>Widget Prime</h1>
              <p>Built for long mileage with a stable midsole and grippy outsole.</p>
              <p>Breathable mesh upper with protective rand and reinforced heel counter.</p>
            </main>
            <aside>
              <p>Support and care guidance lives outside the main container.</p>
              <a href="/support/care">Care instructions</a>
            </aside>
          </body>
        </html>
        """,
    )

    assert "Support and care guidance lives outside the main container." in markdown
    assert "Care instructions -> /support/care" in markdown


@pytest.mark.asyncio
async def test_generate_page_markdown_skips_review_qa_and_payment_noise_on_detail_pages() -> None:
    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(
            base_html="""
            <html>
              <body>
                <main>
                  <h1>7 Cup Food Processor</h1>
                  <p>Elevate your everyday meals with 3 speed options.</p>
                  <section class="reviews-panel">
                    <h2>Reviews</h2>
                    <p>Review this product</p>
                  </section>
                  <section class="questions-panel">
                    <h2>Questions &amp; Answers</h2>
                    <p>Will this shred cooked pork?</p>
                  </section>
                </main>
                <aside class="secure-payment">
                  <p>100% secure payment</p>
                  <p>Affirm available</p>
                </aside>
              </body>
            </html>
            """,
            accessibility_snapshot={
                "role": "document",
                "children": [
                    {"role": "heading", "name": "7 Cup Food Processor"},
                    {"role": "heading", "name": "Reviews"},
                    {"role": "text", "name": "100% secure payment"},
                ],
            },
        ),
        html="""
        <html>
          <body>
            <main>
              <h1>7 Cup Food Processor</h1>
              <p>Elevate your everyday meals with 3 speed options.</p>
              <section class="reviews-panel">
                <h2>Reviews</h2>
                <p>Review this product</p>
              </section>
              <section class="questions-panel">
                <h2>Questions &amp; Answers</h2>
                <p>Will this shred cooked pork?</p>
              </section>
            </main>
            <aside class="secure-payment">
              <p>100% secure payment</p>
              <p>Affirm available</p>
            </aside>
          </body>
        </html>
        """,
        surface="ecommerce_detail",
    )

    assert "7 Cup Food Processor" in markdown
    assert "Elevate your everyday meals with 3 speed options." in markdown
    assert "Reviews" not in markdown
    assert "Questions & Answers" not in markdown
    assert "100% secure payment" not in markdown


@pytest.mark.asyncio
async def test_detail_expansion_keywords_include_ecommerce_fallbacks_without_requested_fields() -> None:
    default_keywords = browser_runtime.detail_expansion_keywords("ecommerce_detail")
    requested_keywords = browser_runtime.detail_expansion_keywords(
        "ecommerce_detail",
        requested_fields=["description"],
    )

    assert "shipping" in default_keywords
    assert "shipping" in requested_keywords


@pytest.mark.asyncio
async def test_interactive_candidate_snapshot_excludes_class_names_from_probe() -> None:
    page = _FakeExpansionPage(base_html="<html><body></body></html>")
    handle = _FakeHandle(
        "Care instructions",
        page,
        attributes={
            "class": "btn btn--size-selector utility-token",
            "data-testid": "care-panel-toggle",
        },
    )

    snapshot = await browser_runtime.interactive_candidate_snapshot(handle)

    assert snapshot["class_name"] == "btn btn--size-selector utility-token"
    assert "utility-token" not in str(snapshot["probe"])
    assert "care-panel-toggle" in str(snapshot["probe"])


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_matches_keywords_from_class_names() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "",
                "attributes": {"class": "accordion materials-panel-toggle"},
            }
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
    )

    assert diagnostics["clicked_count"] == 1


@pytest.mark.asyncio
async def test_browser_fetch_records_extractable_sections_after_detail_expansion() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1><button>Materials</button></body></html>",
        expanded_html="""
        <html><body>
          <h1>Widget Prime</h1>
          <div class="accordion-item">
            <button>Materials</button>
            <div class="accordion-item__body">
              <div class="rich-content">Full-grain leather upper.</div>
            </div>
          </div>
        </body></html>
        """,
        labels=[{"label": "materials"}],
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        requested_fields=["materials"],
        runtime_provider=_fake_runtime,
    )

    extractability = result.browser_diagnostics["detail_expansion"]["extractability"]

    assert extractability["verified"] is True
    assert extractability["matched_requested_fields"] == ["materials"]


@pytest.mark.asyncio
async def test_expand_detail_content_uses_data_qa_action_to_open_size_selector() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><button aria-label='Add to bag'>Add</button></body></html>",
        labels=[
            {
                "label": "add",
                "attributes": {
                    "aria-label": "Add to bag",
                    "data-qa-action": "product-grid-open-size-selector",
                },
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=None,
    )

    assert diagnostics["clicked_count"] == 1
    assert page.expanded is True


@pytest.mark.asyncio
async def test_expand_detail_content_skips_menu_toggles() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><button aria-controls='site-menu'>Open menu</button></body></html>",
        labels=[
            {
                "label": "open menu",
                "attributes": {
                    "aria-controls": "site-menu",
                },
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["materials"],
    )

    assert diagnostics["clicked_count"] == 0
    assert page.expanded is False


@pytest.mark.asyncio
async def test_browser_fetch_waits_for_challenge_recovery_before_settling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><div>challenge</div></body></html>",
        wait_html_sequence=["<html><body><h1>Widget Prime</h1></body></html>"],
        cookie_snapshots=[[], [{"name": "_abck"}]],
    )
    calls = {"count": 0}

    async def _fake_classify_blocked_page_async(_html: str, _status: int):
        calls["count"] += 1
        blocked = calls["count"] == 1
        return SimpleNamespace(
            blocked=blocked,
            outcome="challenge_page" if blocked else "ok",
            evidence=["provider:akamai"] if blocked else [],
            provider_hits=["akamai"] if blocked else [],
            active_provider_hits=[],
            strong_hits=[],
            weak_hits=[],
            title_matches=[],
            challenge_element_hits=[],
        )

    async def _fake_runtime():
        return _FakeRuntime(page)

    monkeypatch.setattr(
        browser_page_flow,
        "classify_blocked_page_async",
        _fake_classify_blocked_page_async,
    )

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert "Widget Prime" in result.html
    assert page.wait_timeout_calls
    assert page.goto_calls == ["networkidle"]


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
async def test_browser_capture_offloads_payload_decoding_to_thread(
) -> None:
    class _JsonResponse:
        def __init__(self) -> None:
            self.url = "https://example.com/api/product"
            self.status = 200
            self.headers = {"content-type": "application/json"}
            self.request = SimpleNamespace(method="GET")

        async def body(self) -> bytes:
            return b'{"id":"captured"}'

    page = _FakeExpansionPage(base_html="<html><body></body></html>")
    capture = BrowserNetworkCapture(surface="ecommerce_detail")
    capture.attach(page)

    listeners = page.listeners.get("response") or []
    assert listeners
    listeners[0](_JsonResponse())

    summary = await capture.close(page)

    assert summary.network_payload_count == 1
    assert summary.payloads[0]["body"]["id"] == "captured"


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
async def test_browser_capture_close_awaits_sentinel_enqueue_when_queue_put_blocks() -> None:
    capture = BrowserNetworkCapture(surface="ecommerce_detail")

    class _Queue:
        def __init__(self) -> None:
            self.put_calls: list[object] = []

        async def join(self) -> None:
            return None

        async def put(self, value: object) -> None:
            self.put_calls.append(value)
            await asyncio.sleep(0)

    fake_queue = _Queue()
    capture._queue = fake_queue  # type: ignore[assignment]
    capture._workers = {asyncio.create_task(asyncio.sleep(0))}

    summary = await capture.close(_FakeExpansionPage(base_html="<html><body></body></html>"))

    assert summary.network_payload_count == 0
    assert fake_queue.put_calls == [None]


@pytest.mark.asyncio
async def test_browser_capture_close_cancels_workers_when_sentinel_enqueue_times_out() -> None:
    original_timeout_ms = crawler_runtime_settings.browser_capture_queue_join_timeout_ms
    crawler_runtime_settings.browser_capture_queue_join_timeout_ms = 50
    try:
        capture = BrowserNetworkCapture(surface="ecommerce_detail")

        class _Queue:
            async def join(self) -> None:
                return None

            async def put(self, value: object) -> None:
                del value
                await asyncio.sleep(1)

        worker = asyncio.create_task(asyncio.sleep(1))
        capture._queue = _Queue()  # type: ignore[assignment]
        capture._workers = {worker}

        summary = await capture.close(_FakeExpansionPage(base_html="<html><body></body></html>"))

        assert summary.network_payload_count == 0
        assert worker.cancelled() or worker.done()
    finally:
        crawler_runtime_settings.browser_capture_queue_join_timeout_ms = original_timeout_ms


@pytest.mark.asyncio
async def test_probe_browser_readiness_skips_listing_queries_for_detail_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_listing_card_count(*args, **kwargs):
        raise AssertionError("listing card count should not run for detail pages")

    async def _unexpected_selector_count(*args, **kwargs):
        raise AssertionError("listing selector count should not run for detail pages")

    monkeypatch.setattr(
        "app.services.acquisition.browser_readiness.listing_card_signal_count_impl",
        _unexpected_listing_card_count,
    )
    monkeypatch.setattr(
        "app.services.acquisition.browser_readiness.count_matching_selectors",
        _unexpected_selector_count,
    )

    probe = await browser_runtime.probe_browser_readiness(
        _FakeExpansionPage(base_html="<html><body><h1>Widget Prime</h1></body></html>"),
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert probe["is_ready"] is False
    assert probe["listing_card_count"] == 0
    assert probe["matched_listing_selectors"] == 0


@pytest.mark.asyncio
async def test_count_matching_selectors_ignores_timeout_misses() -> None:
    class _Locator:
        async def count(self) -> int:
            raise PlaywrightTimeoutError("timed out")

    class _Page:
        def locator(self, selector: str) -> _Locator:
            del selector
            return _Locator()

    matches = await browser_readiness.count_matching_selectors(
        _Page(),
        selectors=[".product-card"],
    )

    assert matches == 0


@pytest.mark.asyncio
async def test_generate_page_markdown_tolerates_slow_accessibility_snapshots() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        accessibility_snapshot={"role": "document", "children": []},
    )

    async def _slow_snapshot() -> dict[str, object]:
        await asyncio.sleep(1)
        return {"role": "document", "children": []}

    page.accessibility = SimpleNamespace(snapshot=_slow_snapshot)

    markdown = await browser_page_flow._generate_page_markdown(
        page,
        html=page.base_html,
    )

    assert "Widget Prime" in markdown


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


def test_classify_browser_outcome_keeps_ready_listing_with_no_pagination_progress_usable() -> None:
    html = """
    <html><body>
      <article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>
      <article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article>
      <article class='product-card'><a href='/products/widget-3'>Widget Three</a><span>$30</span></article>
    </body></html>
    """

    outcome = browser_runtime.classify_browser_outcome(
        html=html,
        html_bytes=len(html.encode("utf-8")),
        blocked=False,
        traversal_result=TraversalResult(
            requested_mode="paginate",
            selected_mode="paginate",
            activated=True,
            stop_reason="next_page_not_found",
            progress_events=0,
            card_count=3,
        ),
    )

    assert outcome == "usable_content"


def test_classify_browser_outcome_keeps_extractable_listing_usable_below_threshold() -> None:
    html = """
    <html><body>
      <article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>
      <article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article>
      <article class='product-card'><a href='/products/widget-3'>Widget Three</a><span>$30</span></article>
    </body></html>
    """

    outcome = browser_runtime.classify_browser_outcome(
        html=html,
        html_bytes=len(html.encode("utf-8")),
        blocked=False,
        traversal_result=TraversalResult(
            requested_mode="paginate",
            selected_mode="paginate",
            activated=True,
            stop_reason="paginate_no_progress",
            progress_events=0,
            card_count=0,
        ),
    )

    assert outcome == "usable_content"


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


@pytest.mark.asyncio
async def test_browser_fetch_keeps_full_rendered_html_when_traversal_makes_no_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>"
            "<article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article>"
            "<article class='product-card'><a href='/products/widget-3'>Widget Three</a><span>$30</span></article>"
            "</body></html>"
        ),
        selector_counts={selectors[0]: 3} if selectors else {},
        card_count=3,
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
            stop_reason="paginate_blocked",
            progress_events=0,
            card_count=0,
            html_fragments=[
                ("<div data-traversal-cards='true'><a href='/privacy'>Privacy notice</a></div>", False),
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

    assert "Widget One" in result.html
    assert "Privacy notice" not in result.html
    assert "traversal_composed_html" in result.artifacts
    assert "Privacy notice" in result.artifacts["traversal_composed_html"]
    assert result.browser_diagnostics["browser_outcome"] == "usable_content"


@pytest.mark.asyncio
async def test_browser_fetch_prefers_rendered_html_when_progress_traversal_fragment_is_thin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>"
            "<article class='product-card'><a href='/products/widget-2'>Widget Two</a><span>$20</span></article>"
            "<article class='product-card'><a href='/products/widget-3'>Widget Three</a><span>$30</span></article>"
            "</body></html>"
        ),
        selector_counts={selectors[0]: 3} if selectors else {},
        card_count=3,
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
            stop_reason="paginate_progressed",
            progress_events=1,
            card_count=0,
            html_fragments=[
                ("<div data-traversal-cards='true'><a href='/products/widget-1'>Widget One</a></div>", False),
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

    assert "Widget Two" in result.html
    assert "traversal_composed_html" in result.artifacts


@pytest.mark.asyncio
async def test_generate_page_markdown_preserves_legitimate_faq_content() -> None:
    markdown = await browser_page_flow._generate_page_markdown(
        _FakeExpansionPage(base_html="<html><body></body></html>"),
        html="""
        <html>
          <body>
            <main>
              <h1>Widget Prime</h1>
              <section class="faq-panel">
                <h2>Sizing questions</h2>
                <p>Questions about fit are answered in the size guide below.</p>
              </section>
            </main>
          </body>
        </html>
        """,
        surface="ecommerce_detail",
    )

    assert "Sizing questions" in markdown
    assert "Questions about fit are answered in the size guide below." in markdown
