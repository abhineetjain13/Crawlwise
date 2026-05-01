from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition import (
    browser_capture,
    browser_detail,
    browser_recovery,
    dom_runtime,
)
from app.services.acquisition.browser_capture import BrowserNetworkCapture
from app.services.acquisition import browser_page_flow, browser_readiness, browser_runtime
from app.services.acquisition.traversal import TraversalResult
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS


def test_select_primary_browser_html_prefers_full_rendered_when_traversal_fragment_is_capped() -> None:
    traversal_result = SimpleNamespace(
        activated=True,
        progress_events=1,
        card_count=236,
        stop_reason="target_records_reached",
    )

    html = browser_page_flow._select_primary_browser_html(
        surface="ecommerce_listing",
        traversal_result=traversal_result,
        traversal_html="<html><body><a href='/products/a'>A</a></body></html>",
        rendered_html=(
            "<html><body>"
            "<a href='/products/a'>A</a>"
            "<a href='/products/b'>B</a>"
            "</body></html>"
        ),
        listing_min_items=2,
    )

    assert "products/b" in html


def test_location_interstitial_diagnostics_marks_location_required() -> None:
    html = """
    <html><body>
      <div role="dialog" class="location-modal"><h2>Choose your location</h2><button>Continue</button></div>
    </body></html>
    """
    assert browser_page_flow.location_interstitial_detected(html) is True

    diagnostics = browser_page_flow.build_browser_diagnostics(
        browser_reason="http-escalation",
        browser_outcome="location_required",
        navigation_strategy="domcontentloaded",
        response_missing=False,
        networkidle_timed_out=False,
        networkidle_skip_reason=None,
        readiness_policy={},
        phase_timings_ms={},
        html_bytes=len(html.encode("utf-8")),
        challenge_evidence=[],
        blocked_classification=SimpleNamespace(
            provider_hits=[],
            challenge_element_hits=[],
        ),
        low_content_reason=None,
        readiness_probes=[],
        capture_summary=SimpleNamespace(
            network_payload_count=0,
            malformed_network_payloads=0,
            network_payload_read_failures=0,
            network_payload_read_timeouts=0,
            closed_network_payloads=0,
            skipped_oversized_network_payloads=0,
            dropped_payload_events=0,
        ),
        readiness_diagnostics={},
        expansion_diagnostics={},
        listing_recovery_diagnostics={},
        listing_artifact_diagnostics={},
        interstitial_diagnostics={"location_required": True},
        traversal_result=None,
    )

    assert diagnostics["browser_outcome"] == "location_required"
    assert diagnostics["failure_reason"] == "location_required"
    assert diagnostics["interstitial"]["location_required"] is True


def test_location_interstitial_detects_text_only_fallback() -> None:
    html = """
    <html><body>
      <section>
        <h2>Choose your location</h2>
        <p>Enter zip code to deliver to your area.</p>
      </section>
    </body></html>
    """

    assert browser_page_flow.location_interstitial_detected(html) is True


def test_ready_probe_supports_fast_finalize_for_strong_detail_page() -> None:
    assert browser_page_flow._ready_probe_supports_fast_finalize(
        [
            {
                "is_ready": True,
                "visible_text_length": 5000,
                "structured_data_present": True,
                "detail_hint_count": 4,
            }
        ],
        surface="ecommerce_detail",
        status_code=200,
    ) is True


def test_ready_probe_fast_finalize_rejects_for_forced_block_status() -> None:
    assert browser_page_flow._ready_probe_supports_fast_finalize(
        [
            {
                "is_ready": True,
                "visible_text_length": 5000,
                "structured_data_present": True,
                "detail_hint_count": 4,
            }
        ],
        surface="ecommerce_detail",
        status_code=403,
    ) is False


def test_fast_finalize_accepts_verified_extractability_without_probe_payload() -> None:
    assert browser_page_flow._ready_probe_supports_fast_finalize(
        [],
        surface="ecommerce_detail",
        status_code=200,
        expansion_diagnostics={
            "extractability": {
                "verified": True,
                "matched_requested_fields": ["title", "image_url"],
            }
        },
    ) is True


@pytest.mark.asyncio
async def test_location_interstitial_dismisses_by_safe_text_token() -> None:
    class _MissingLocator:
        async def count(self) -> int:
            return 0

        @property
        def first(self):
            return self

    class _Page:
        url = "https://www.newbalance.com/pd/574-core/ML574V3-40377.html"

        def __init__(self) -> None:
            self.waited = False

        def locator(self, selector: str):
            del selector
            return _MissingLocator()

        async def evaluate(self, script: str, payload: dict[str, object]):
            del script
            assert "Continue" in payload["tokens"]
            return {"status": "dismissed", "selector": "text:continue"}

        async def content(self) -> str:
            return "<html><body></body></html>"

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            del timeout_ms
            self.waited = True

    page = _Page()

    result = await browser_page_flow.dismiss_safe_location_interstitial(page)

    assert result == {"status": "dismissed", "selector": "text:continue"}
    assert page.waited is True


@pytest.mark.asyncio
async def test_location_interstitial_dismissal_counts_before_first_locator() -> None:
    class _FirstLocator:
        async def wait_for(self, **_kwargs) -> None:
            return None

        async def click(self, **_kwargs) -> None:
            return None

    class _Locator:
        @property
        def first(self):
            return _FirstLocator()

        async def count(self) -> int:
            return 1

    class _Page:
        url = "https://example.com/products/widget"

        def __init__(self) -> None:
            self.waited = False

        def locator(self, _selector: str):
            return _Locator()

        async def content(self) -> str:
            return "<html><body></body></html>"

        async def wait_for_timeout(self, _timeout_ms: int) -> None:
            self.waited = True

    result = await browser_page_flow.dismiss_safe_location_interstitial(_Page())

    assert result["status"] == "dismissed"


@pytest.mark.asyncio
async def test_location_interstitial_dismissal_requires_modal_to_clear() -> None:
    html = (
        "<html><body><div role='dialog'>"
        "<h2>Choose your location</h2><button>Continue</button>"
        "</div></body></html>"
    )

    class _FirstLocator:
        async def wait_for(self, **_kwargs) -> None:
            return None

        async def click(self, **_kwargs) -> None:
            return None

    class _Locator:
        @property
        def first(self):
            return _FirstLocator()

        async def count(self) -> int:
            return 1

    class _Page:
        url = "https://example.com/products/widget"

        def locator(self, _selector: str):
            return _Locator()

        async def wait_for_timeout(self, _timeout_ms: int) -> None:
            return None

        async def content(self) -> str:
            return html

        async def evaluate(self, _script: str, _payload: dict[str, object]):
            return {"status": "not_found"}

    result = await browser_page_flow.dismiss_safe_location_interstitial(_Page())

    assert result["status"] == "still_present"
    assert str(result.get("selector") or "")


@dataclass
class _FakeHandle:
    label: str
    page: "_FakeExpansionPage"
    attributes: dict[str, str]
    tag_name: str = "button"
    actionable: bool = True
    inside_main: bool = False
    inside_header: bool = False
    inside_nav: bool = False
    inside_footer: bool = False
    inside_aside: bool = False

    async def evaluate(self, script: str) -> str | dict[str, bool] | None:
        if "pieces" in script:
            return self.label
        if "insideMain" in script:
            return {
                "insideMain": self.inside_main,
                "insideHeader": self.inside_header,
                "insideNav": self.inside_nav,
                "insideFooter": self.inside_footer,
                "insideAside": self.inside_aside,
            }
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
                    inside_main=bool(row.get("inside_main", False)),
                    inside_header=bool(row.get("inside_header", False)),
                    inside_nav=bool(row.get("inside_nav", False)),
                    inside_footer=bool(row.get("inside_footer", False)),
                    inside_aside=bool(row.get("inside_aside", False)),
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
    def __init__(self, page: "_FakeExpansionPage", role: str, name: object) -> None:
        self._page = page
        self._role = role
        self._name = str(name or "").lower()
        self._name_pattern = name if hasattr(name, "search") else None

    @property
    def first(self) -> "_FakeRoleLocator":
        return self

    def nth(self, index: int) -> "_FakeRoleLocator":
        del index
        return self

    async def count(self) -> int:
        return sum(
            1
            for role, name in self._page.role_targets
            if role == self._role and self._matches_name(name)
        )

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return await self.count() > 0

    async def is_disabled(self) -> bool:
        return False

    async def click(self, timeout: int | None = None) -> None:
        del timeout
        if await self.count():
            self._page.expanded = True

    def _matches_name(self, name: str) -> bool:
        if self._name_pattern is not None:
            return bool(self._name_pattern.search(name))
        return name == self._name


class _NoTimeoutRoleLocator(_FakeRoleLocator):
    async def is_visible(self) -> bool:
        return await self.count() > 0


class _WaitingRoleLocator(_FakeRoleLocator):
    def __init__(self, page: "_FakeExpansionPage", role: str, name: str) -> None:
        super().__init__(page, role, name)
        self.wait_for_calls: list[tuple[str | None, int | None]] = []

    async def wait_for(
        self,
        *,
        state: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.wait_for_calls.append((state, timeout))
        if await self.count() == 0:
            raise TimeoutError("not visible")


class _FakePageContext:
    def __init__(self, page: "_FakeExpansionPage") -> None:
        self._page = page

    async def cookies(self, *_args, **_kwargs) -> list[dict[str, object]]:
        return await self._page._cookies(*_args, **_kwargs)

    async def close(self) -> None:
        await self._page._close_context()

    async def new_page(self) -> "_FakeExpansionPage":
        warm_page = _FakeExpansionPage(base_html=self._page.base_html)
        self._page.spawned_pages.append(warm_page)
        return warm_page

    def on(self, event_name: str, callback: Any) -> None:
        self._page.listeners.setdefault(f"context:{event_name}", []).append(callback)

    def remove_listener(self, event_name: str, callback: Any) -> None:
        key = f"context:{event_name}"
        listeners = self._page.listeners.get(key)
        if not listeners:
            return
        self._page.listeners[key] = [
            listener for listener in listeners if listener is not callback
        ]


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
        rendered_listing_fragments: list[str] | None = None,
        wait_html_sequence: list[str] | None = None,
        cookie_snapshots: list[list[dict[str, object]]] | None = None,
        content_blocker: asyncio.Event | None = None,
        content_block_after_calls: int = 0,
        ignore_content_cancellation: bool = False,
        content_entered: asyncio.Event | None = None,
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
        self.rendered_listing_fragments = list(rendered_listing_fragments or [])
        self.wait_html_sequence = list(wait_html_sequence or [])
        self.cookie_snapshots = list(cookie_snapshots or [[]])
        self.content_blocker = content_blocker
        self.content_block_after_calls = max(0, int(content_block_after_calls))
        self.ignore_content_cancellation = ignore_content_cancellation
        self.content_entered = content_entered
        self.content_calls = 0
        self.context_close_calls = 0
        self.page_close_calls = 0
        self.spawned_pages: list[_FakeExpansionPage] = []
        self.accessibility = SimpleNamespace(
            snapshot=self._snapshot if accessibility_snapshot is not None else None
        )
        self._accessibility_snapshot = accessibility_snapshot
        self.shadow_flattened = False
        self.context = _FakePageContext(self)

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

    async def _close_context(self) -> None:
        self.context_close_calls += 1
        if self.content_blocker is not None:
            self.content_blocker.set()

    async def close(self) -> None:
        self.page_close_calls += 1
        if self.content_blocker is not None:
            self.content_blocker.set()

    async def evaluate(self, script: str, arg: Any | None = None) -> Any:
        if "document.querySelectorAll('*')" in script and self.shadow_html is not None:
            self.shadow_flattened = True
            return 1
        if "const selectors = Array.isArray(args?.selectors)" in script:
            return list(self.rendered_listing_fragments)
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
        self.content_calls += 1
        if self.content_entered is not None:
            self.content_entered.set()
        if (
            self.content_blocker is not None
            and self.content_calls > self.content_block_after_calls
            and not self.content_blocker.is_set()
        ):
            while not self.content_blocker.is_set():
                try:
                    await self.content_blocker.wait()
                except asyncio.CancelledError:
                    if not self.ignore_content_cancellation:
                        raise
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


async def _page_markdown_via_browser_fetch(
    html: str | None = None,
    *,
    page: _FakeExpansionPage | None = None,
    surface: str = "ecommerce_detail",
    accessibility_snapshot: dict[str, object] | None = None,
) -> str:
    page = page or _FakeExpansionPage(
        base_html=str(html or ""),
        accessibility_snapshot=accessibility_snapshot,
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface=surface,
        runtime_provider=_fake_runtime,
    )
    return result.page_markdown


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

    async def _fake_runtime(**_kwargs):
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
    assert result.browser_diagnostics["detail_expansion"]["status"] == "attempted"
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 0
    assert page.goto_calls == ["domcontentloaded"]
    assert page.wait_timeout_calls == []
    assert "networkidle" not in page.load_state_calls


@pytest.mark.asyncio
async def test_browser_fetch_closes_unexpected_popup_pages() -> None:
    popup_page = _FakeExpansionPage(base_html="<html><body>popup</body></html>")

    class _PopupPage(_FakeExpansionPage):
        async def goto(
            self,
            url: str,
            wait_until: str | None = None,
            timeout: int | None = None,
        ) -> Any:
            response = await super().goto(url, wait_until=wait_until, timeout=timeout)
            for callback in list(self.listeners.get("context:page", [])):
                callback(popup_page)
            await asyncio.sleep(0)
            return response

    page = _PopupPage(
        base_html="""
        <html>
          <head>
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Product","name":"Widget Prime"}
            </script>
          </head>
          <body>
            <h1>Widget Prime</h1>
            <p>Price Reviews Product details Shipping</p>
          </body>
        </html>
        """,
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["browser_outcome"] == "usable_content"
    assert popup_page.page_close_calls == 1


@pytest.mark.asyncio
async def test_browser_fetch_fast_paths_ready_listing_cards_without_networkidle() -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html="<html><body><article class='product-card'>A</article></body></html>",
        selector_counts={selector: 3 for selector in selectors[:1]},
        card_count=3,
    )
    page.card_selectors = set(selectors)

    async def _fake_runtime(**_kwargs):
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
async def test_browser_fetch_listing_does_not_treat_product_titles_as_extractable_fields() -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html="""
        <html>
          <body>
            <section class="product-card-grid">
              <article class="product-card">
                <h2>Batman Wayne Industries</h2>
                <p>Relaxed fit cotton shirt with oversized graphic print.</p>
              </article>
              <article class="product-card">
                <h2>Venom Pure Destruction</h2>
                <p>Heavyweight jersey shirt with all-over print.</p>
              </article>
            </section>
          </body>
        </html>
        """,
        selector_counts={selector: 2 for selector in selectors[:1]},
        card_count=2,
    )
    page.card_selectors = set(selectors)

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["detail_expansion"]["reason"] == "non_detail_surface"


@pytest.mark.asyncio
async def test_browser_fetch_listing_skips_detail_extractability_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selectors = list(CARD_SELECTORS.get("ecommerce") or [])
    page = _FakeExpansionPage(
        base_html="<html><body><article class='product-card'>A</article></body></html>",
        selector_counts={selector: 3 for selector in selectors[:1]},
        card_count=3,
    )
    page.card_selectors = set(selectors)

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    def _unexpected_extractability(*args, **kwargs):
        raise AssertionError("listing settle should not probe detail extractability")

    monkeypatch.setattr(
        browser_page_flow,
        "requested_content_extractability",
        _unexpected_extractability,
    )

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["detail_expansion"]["reason"] == "non_detail_surface"


@pytest.mark.asyncio
async def test_browser_fetch_attempts_implicit_networkidle_for_unmatched_spa_listing(
    patch_settings,
) -> None:
    patch_settings(
        browser_navigation_optimistic_wait_ms=25,
        browser_spa_implicit_networkidle_timeout_ms=250,
    )
    page = _FakeExpansionPage(base_html="<html><body>Loading</body></html>")
    probe_results = iter(
        [
            {
                "url": "https://example.com/spa/listing",
                "surface": "ecommerce_listing",
                "is_ready": False,
                "detail_like": False,
                "structured_data_present": True,
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
                "structured_data_present": True,
                "visible_text_length": 24,
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
                "structured_data_present": True,
                "visible_text_length": 260,
                "detail_hint_count": 0,
                "listing_card_count": 0,
                "matched_listing_selectors": 0,
                "h1_present": False,
            },
        ]
    )
    async def _fake_runtime(**_kwargs):
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


@pytest.mark.asyncio
async def test_probe_browser_readiness_does_not_fast_path_listing_on_visible_text_alone() -> None:
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
    assert probe["is_ready"] is False


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

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _fake_read_network_payload_body(response, **_kwargs):
        return browser_runtime.NetworkPayloadReadResult(
            body=f'{{"id": "{response.url}"}}'.encode("utf-8"),
            outcome="ok",
        )

    create_task_calls = 0
    original_create_task = browser_capture.asyncio.create_task

    def _counting_create_task(coro):
        nonlocal create_task_calls
        code = getattr(coro, "cr_code", None)
        if getattr(code, "co_name", "") == "_capture_worker":
            create_task_calls += 1
        return original_create_task(coro)

    monkeypatch.setattr(browser_capture.asyncio, "create_task", _counting_create_task)
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

    async def _fake_runtime(**_kwargs):
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

    async def _fake_runtime(**_kwargs):
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
async def test_browser_fetch_skips_detail_expansion_when_requested_section_is_already_extractable() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <h1>Widget Prime</h1>
          <section>
            <h2>FEATURES &amp; BENEFITS</h2>
            <p>Responsive foam and carbon plate propulsion.</p>
          </section>
        </body></html>
        """,
        labels=[
            {
                "label": "new",
                "attributes": {"aria-controls": "nav-new"},
            }
        ],
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        requested_fields=["Features & Benefits"],
        runtime_provider=_fake_runtime,
    )

    assert "Responsive foam and carbon plate propulsion." in result.html
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 0
    assert (
        result.browser_diagnostics["detail_expansion"]["reason"]
        == "requested_content_already_extractable"
    )


@pytest.mark.asyncio
async def test_browser_fetch_expands_requested_dom_pattern_content_without_heading_sections() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <main>
            <h1>Widget Prime</h1>
            <button aria-controls="materials-panel">Materials</button>
            <div id="materials-panel">
              <div class="material-composition">Full-grain leather upper.</div>
            </div>
          </main>
        </body></html>
        """,
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        requested_fields=["materials"],
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 0
    assert (
        result.browser_diagnostics["detail_expansion"]["reason"]
        == "requested_content_already_extractable"
    )
    assert result.browser_diagnostics["detail_expansion"]["extractability"]["matched_requested_fields"] == [
        "materials"
    ]


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

    assert diagnostics["status"] == "attempted"
    assert diagnostics["reason"] == "missing_detail_content"
    assert diagnostics["clicked_count"] == 0
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

    async def _fake_runtime(**_kwargs):
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

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert "Widget Prime" in result.page_markdown
    assert "Built for long mileage." in result.page_markdown
    assert "Visible links:" not in result.page_markdown
    assert "SEMANTIC ACCESSIBILITY SNAPSHOT" in result.page_markdown


@pytest.mark.asyncio
async def test_browser_fetch_captures_rendered_listing_fragments_artifact() -> None:
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
        rendered_listing_fragments=[
            """
            <article class="product-card">
              <a href="/products/widget-prime"><h2>Widget Prime</h2></a>
              <div class="price">$19.99</div>
              <img src="/images/widget-prime.jpg" alt="Widget Prime" />
            </article>
            """
        ],
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.artifacts["rendered_listing_fragments"] == [
        """
            <article class="product-card">
              <a href="/products/widget-prime"><h2>Widget Prime</h2></a>
              <div class="price">$19.99</div>
              <img src="/images/widget-prime.jpg" alt="Widget Prime" />
            </article>
            """.strip()
    ]


@pytest.mark.asyncio
async def test_browser_fetch_ignores_non_string_rendered_listing_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><article><a href='/products/widget'>Widget</a></article></body></html>",
        selector_counts={".product-card": 1},
        card_count=1,
    )
    page.url = "https://example.com/collections/widgets"

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _bad_fragments(*args, **kwargs):
        del args, kwargs
        return [123, {"html": "<article>bad</article>"}, " <article>good</article> "]

    monkeypatch.setattr(browser_page_flow, "capture_rendered_listing_fragments", _bad_fragments)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.artifacts["rendered_listing_fragments"] == ["<article>good</article>"]


@pytest.mark.asyncio
async def test_browser_fetch_keeps_empty_successful_listing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><article><a href='/products/widget'>Widget</a></article></body></html>",
        selector_counts={".product-card": 1},
        card_count=1,
    )
    page.url = "https://example.com/collections/widgets"

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _empty_fragments(*args, **kwargs):
        del args, kwargs
        return []

    async def _empty_visuals(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr(browser_page_flow, "capture_rendered_listing_fragments", _empty_fragments)
    monkeypatch.setattr(browser_page_flow, "_capture_listing_visual_elements", _empty_visuals)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.artifacts["rendered_listing_fragments"] == []
    assert result.artifacts["listing_visual_elements"] == []


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
    page = _FakeExpansionPage(
        base_html="<html><body><div class='hero'>Widget Prime</div></body></html>"
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _skip_settle(*args, **kwargs):
        del args, kwargs
        return (
            {"is_ready": True},
            [],
            False,
            "test_override",
            {},
            {"status": "skipped", "reason": "test_override", "clicked_count": 0},
        )

    monkeypatch.setattr(browser_runtime, "_settle_browser_page", _skip_settle)
    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )
    markdown = result.page_markdown

    assert "Widget Prime" in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("html", "surface", "accessibility_snapshot", "present", "absent"),
    [
        (
            """
            <html><body><div role="dialog" aria-label="Category menu"><p>WOMAN MAN KIDS BEST SELLERS TOPS SHIRTS</p></div><main><h1>Widget Prime</h1><p>Built for long mileage.</p></main></body></html>
            """,
            "ecommerce_detail",
            None,
            ("Widget Prime", "Built for long mileage."),
            ("BEST SELLERS",),
        ),
        (
            """
            <html><body><main><h1>Widget Prime</h1><p>Built for long mileage with a stable midsole and grippy outsole.</p></main><section><p>Support, returns, and care instructions live outside the main container.</p><a href="/support/returns">Returns and exchanges</a></section></body></html>
            """,
            "ecommerce_detail",
            None,
            (
                "Widget Prime",
                "Support, returns, and care instructions live outside the main container.",
                "Returns and exchanges",
            ),
            (),
        ),
        (
            """
            <html><body><main><h1>Widget Prime</h1><p>Built for long mileage with a stable midsole and grippy outsole.</p><p>Breathable mesh upper with protective rand and reinforced heel counter.</p></main><aside><p>Support and care guidance lives outside the main container.</p><a href="/support/care">Care instructions</a></aside></body></html>
            """,
            "ecommerce_detail",
            None,
            (
                "Support and care guidance lives outside the main container.",
                "Care instructions",
            ),
            (),
        ),
        (
            """
            <html><body><main><h1>7 Cup Food Processor</h1><p>Elevate your everyday meals with 3 speed options.</p><section class="reviews-panel"><h2>Reviews</h2><p>Review this product</p></section><section class="questions-panel"><h2>Questions &amp; Answers</h2><p>Will this shred cooked pork?</p></section></main><aside class="secure-payment"><p>100% secure payment</p><p>Affirm available</p></aside></body></html>
            """,
            "ecommerce_detail",
            {
                "role": "document",
                "children": [
                    {"role": "heading", "name": "7 Cup Food Processor"},
                    {"role": "heading", "name": "Reviews"},
                    {"role": "text", "name": "100% secure payment"},
                ],
            },
            (
                "7 Cup Food Processor",
                "Elevate your everyday meals with 3 speed options.",
            ),
            ("Reviews", "Questions & Answers", "100% secure payment"),
        ),
        (
            """
            <html><body><main><a href="#main">Skip to main content</a><h1>RUSTIC T-SHIRT WITH BUTTONS</h1><p>Put it in your basket</p><p>Add</p><p>Product Measurements</p><p>Check in-store availability</p><p>Shipping, exchanges and returns</p><p>Composition : 60% cotton, 40% polyester</p></main></body></html>
            """,
            "ecommerce_detail",
            None,
            ("RUSTIC T-SHIRT WITH BUTTONS", "Composition : 60% cotton, 40% polyester"),
            (
                "Skip to main content",
                "Put it in your basket",
                "Product Measurements",
                "Check in-store availability",
                "Shipping, exchanges and returns",
                "Visible links:",
            ),
        ),
        (
            """
            <html><body><main><h1>Widget Prime</h1><p>Product Measurements: Chest 40 in, Length 28 in</p><p>Shipping, exchanges and returns: Free returns within 30 days</p></main></body></html>
            """,
            "ecommerce_detail",
            None,
            (
                "Product Measurements: Chest 40 in, Length 28 in",
                "Shipping, exchanges and returns: Free returns within 30 days",
            ),
            (),
        ),
        (
            """
            <html><body><main><h1>Widget Prime</h1><section class="faq-panel"><h2>Sizing questions</h2><p>Questions about fit are answered in the size guide below.</p></section></main></body></html>
            """,
            "ecommerce_detail",
            None,
            (
                "Sizing questions",
                "Questions about fit are answered in the size guide below.",
            ),
            (),
        ),
    ],
    ids=[
        "prefers-main-content",
        "falls-back-when-main-too-narrow",
        "falls-back-when-links-live-outside-main",
        "skips-review-and-payment-noise",
        "skips-detail-noise",
        "keeps-label-value-lines",
        "preserves-legitimate-faq-content",
    ],
)
async def test_browser_fetch_page_markdown_contract(
    html: str,
    surface: str,
    accessibility_snapshot: dict[str, object] | None,
    present: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    markdown = await _page_markdown_via_browser_fetch(
        html,
        surface=surface,
        accessibility_snapshot=accessibility_snapshot,
    )

    for snippet in present:
        assert snippet in markdown
    for snippet in absent:
        assert snippet not in markdown


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


def test_acquisition_package_exports_interactive_candidate_snapshot() -> None:
    from app.services import acquisition

    assert acquisition.interactive_candidate_snapshot is browser_runtime.interactive_candidate_snapshot


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
async def test_expand_all_interactive_elements_allows_relevant_footer_controls() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "Main menu",
                "attributes": {"aria-controls": "site-menu"},
                "inside_footer": True,
            },
            {
                "label": "Size guide",
                "attributes": {"aria-controls": "size-panel"},
                "inside_footer": True,
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["size"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["size guide"]


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_prioritizes_requested_measurements_over_media_zoom() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "enlarge image rustic t-shirt",
                "attributes": {
                    "aria-label": "Enlarge image rustic t-shirt",
                    "data-qa-action": "media-zoom",
                    "class": "product-detail-image product-detail-view__main-image",
                },
                "tag_name": "button",
            },
            {
                "label": "product measurements",
                "attributes": {
                    "class": "product-detail-actions__action-button",
                    "data-qa-action": "open-interactive-size-guide-accordion",
                },
                "tag_name": "button",
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["product measurements"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["product measurements"]


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_allows_visible_generic_detail_toggle_for_requested_fields() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "details",
                "attributes": {"aria-controls": "details-panel"},
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["materials"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["details"]


@pytest.mark.asyncio
async def test_expand_detail_content_if_needed_attempts_generic_ecommerce_expansion_when_ready() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "shipping and returns",
                "attributes": {"aria-controls": "shipping-panel"},
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_detail_content_if_needed(
        page,
        surface="ecommerce_detail",
        readiness_probe={"is_ready": True, "detail_like": True},
    )

    assert diagnostics["clicked_count"] == 1
    assert page.expanded is True


@pytest.mark.asyncio
async def test_expand_detail_content_if_needed_attempts_ready_job_detail_without_requested_fields() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body></body></html>",
        labels=[
            {
                "label": "responsibilities",
                "attributes": {"aria-controls": "responsibilities-panel"},
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_detail_content_if_needed(
        page,
        surface="job_detail",
        readiness_probe={"is_ready": True, "detail_like": True},
    )

    assert diagnostics["clicked_count"] == 1
    assert page.expanded is True


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

    async def _fake_runtime(**_kwargs):
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
async def test_browser_fetch_does_not_skip_requested_dom_pattern_when_selector_is_empty() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <main>
            <h1>Widget Prime</h1>
            <button aria-controls="specs-panel">Specifications</button>
            <div class="specifications"></div>
          </main>
        </body></html>
        """,
        expanded_html="""
        <html><body>
          <main>
            <h1>Widget Prime</h1>
            <button aria-controls="specs-panel">Specifications</button>
            <div class="specifications">Weight: 2kg</div>
          </main>
        </body></html>
        """,
        labels=[
            {
                "label": "specifications",
                "attributes": {"aria-controls": "specs-panel"},
                "tag_name": "button",
            }
        ],
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        requested_fields=["specifications"],
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 1
    assert "Weight: 2kg" in result.html


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
async def test_expand_detail_content_prefers_requested_section_labels_over_unrelated_nav() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <button aria-controls='nav-new'>New</button>
          <button aria-controls='nav-men'>Men</button>
          <button aria-controls='details-panel'>Details</button>
        </body></html>
        """,
        labels=[
            {
                "label": "new",
                "attributes": {"aria-controls": "nav-new"},
                "tag_name": "button",
            },
            {
                "label": "men",
                "attributes": {"aria-controls": "nav-men"},
                "tag_name": "button",
            },
            {
                "label": "details",
                "attributes": {"aria-controls": "details-panel"},
                "tag_name": "button",
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["Details"],
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["details"]
    assert page.expanded is True


@pytest.mark.asyncio
async def test_expand_detail_content_skips_navigation_anchors_that_match_generic_keywords() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <a href="/returns-and-refunds">Returns &amp; refunds</a>
          <a href="/about-us">About us</a>
          <a href="/careers">Careers</a>
        </body></html>
        """,
        labels=[
            {
                "label": "returns & refunds",
                "attributes": {"href": "/returns-and-refunds"},
                "tag_name": "a",
            },
            {
                "label": "about us",
                "attributes": {"href": "/about-us"},
                "tag_name": "a",
            },
            {
                "label": "careers",
                "attributes": {"href": "/careers"},
                "tag_name": "a",
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["title", "size", "availability"],
    )

    assert diagnostics["clicked_count"] == 0
    assert page.expanded is False


@pytest.mark.asyncio
async def test_expand_detail_content_skips_header_controls_outside_main_content() -> None:
    page = _FakeExpansionPage(
        base_html="""
        <html><body>
          <header><button aria-controls='about-panel'>About</button></header>
          <main><button aria-controls='details-panel'>Details</button></main>
        </body></html>
        """,
        labels=[
            {
                "label": "about",
                "attributes": {"aria-controls": "about-panel"},
                "tag_name": "button",
                "inside_header": True,
            },
            {
                "label": "details",
                "attributes": {"aria-controls": "details-panel"},
                "tag_name": "button",
                "inside_main": True,
            },
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=None,
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["details"]
    assert page.expanded is True


@pytest.mark.asyncio
async def test_expand_detail_content_does_not_match_requested_keywords_from_hidden_probe_only() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><button aria-controls='lifestyle-panel'>Lifestyle</button></body></html>",
        labels=[
            {
                "label": "lifestyle",
                "probe": "details drawer",
                "attributes": {"aria-controls": "lifestyle-panel"},
                "tag_name": "button",
            }
        ],
    )

    diagnostics = await browser_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
        requested_fields=["Details"],
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

    async def _fake_runtime(**_kwargs):
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
    assert page.goto_calls == ["domcontentloaded"]
    assert page.load_state_calls == ["networkidle"]


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

    async def _fake_runtime(**_kwargs):
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
async def test_dom_detail_expansion_stops_after_click_exceeds_time_budget() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        labels=[
            {"label": "Details", "attributes": {"aria-controls": "details"}},
            {"label": "Materials", "attributes": {"aria-controls": "materials"}},
        ],
    )

    async def _snapshot(handle: _FakeHandle) -> dict[str, object]:
        return {
            "probe": handle.label.lower(),
            "label": handle.label.lower(),
            "aria_expanded": "",
            "href": "",
            "aria_controls": handle.attributes.get("aria-controls", ""),
            "data_qa_action": "",
            "class_name": "",
            "tag_name": handle.tag_name,
            "visible": True,
            "actionable": True,
        }

    diagnostics = await browser_detail.expand_all_interactive_elements_impl(
        page,
        surface="ecommerce_detail",
        requested_fields=None,
        detail_expand_selectors=("button",),
        detail_expansion_keywords=lambda *_args, **_kwargs: ("details", "materials"),
        interactive_candidate_snapshot=_snapshot,
        elapsed_ms=lambda _started_at: 999 if page.expanded else 0,
        max_elapsed_ms=10,
    )

    assert diagnostics["status"] == "time_budget_reached"
    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["details"]


@pytest.mark.asyncio
async def test_browser_fetch_aom_expansion_respects_interaction_cap(patch_settings) -> None:
    patch_settings(detail_aom_expand_max_interactions=1)
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

    async def _fake_runtime(**_kwargs):
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


@pytest.mark.asyncio
async def test_expand_interactive_elements_via_accessibility_supports_locators_without_visibility_timeout() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        accessibility_snapshot={
            "role": "document",
            "children": [{"role": "tab", "name": "Product specifications"}],
        },
        role_targets={("tab", "product specifications")},
    )

    def _get_by_role(role: str, *, name: str, exact: bool = True) -> _NoTimeoutRoleLocator:
        del exact
        return _NoTimeoutRoleLocator(page, role, name)

    page.get_by_role = _get_by_role

    diagnostics = await browser_detail.expand_interactive_elements_via_accessibility_impl(
        page,
        surface="ecommerce_detail",
        requested_fields=None,
        detail_expansion_keywords=browser_runtime.detail_expansion_keywords,
        accessibility_expand_candidates=browser_runtime.accessibility_expand_candidates,
        elapsed_ms=browser_runtime._elapsed_ms,
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["product specifications"]


@pytest.mark.asyncio
async def test_expand_interactive_elements_via_accessibility_waits_for_visibility_with_configured_timeout(
    patch_settings,
) -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        accessibility_snapshot={
            "role": "document",
            "children": [{"role": "tab", "name": "Product specifications"}],
        },
        role_targets={("tab", "product specifications")},
    )
    locator = _WaitingRoleLocator(page, "tab", "product specifications")
    patch_settings(detail_expand_visibility_timeout_ms=375)

    def _get_by_role(role: str, *, name: str, exact: bool = True) -> _WaitingRoleLocator:
        del role, name, exact
        return locator

    page.get_by_role = _get_by_role
    diagnostics = await browser_detail.expand_interactive_elements_via_accessibility_impl(
        page,
        surface="ecommerce_detail",
        requested_fields=None,
        detail_expansion_keywords=browser_runtime.detail_expansion_keywords,
        accessibility_expand_candidates=browser_runtime.accessibility_expand_candidates,
        elapsed_ms=browser_runtime._elapsed_ms,
    )

    assert locator.wait_for_calls == [("visible", 375)]
    assert diagnostics["clicked_count"] == 1


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
async def test_listing_card_signal_count_uses_heuristic_card_fallback_after_selector_miss(
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

    assert count == 9
    assert calls == [True]


@pytest.mark.asyncio
async def test_probe_browser_readiness_uses_heuristic_listing_card_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def _fake_count_listing_cards(page, *, surface: str, allow_heuristic: bool = True) -> int:
        del page, surface
        calls.append(bool(allow_heuristic))
        return 12 if allow_heuristic else 0

    monkeypatch.setattr(
        browser_readiness,
        "listing_card_signal_count_impl",
        _fake_count_listing_cards,
    )

    probe = await browser_runtime.probe_browser_readiness(
        _FakeExpansionPage(
            base_html="<html><body><h1>adidas Sneakers</h1><p>Grid loaded</p></body></html>"
        ),
        url="https://example.com/collections/adidas-shoes",
        surface="ecommerce_listing",
    )

    assert probe["is_ready"] is True
    assert probe["listing_card_count"] == 12
    assert calls == [True]


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
async def test_browser_capture_close_uses_bounded_queue_join_timeout(patch_settings) -> None:
    patch_settings(browser_capture_queue_join_timeout_ms=50)
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
async def test_browser_capture_close_cancels_workers_when_sentinel_enqueue_times_out(
    patch_settings,
) -> None:
    patch_settings(browser_capture_queue_join_timeout_ms=50)
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

    markdown = await _page_markdown_via_browser_fetch(page=page)

    assert "Widget Prime" in markdown


@pytest.mark.asyncio
async def test_generate_page_markdown_raises_unexpected_accessibility_errors() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget Prime</h1></body></html>",
        accessibility_snapshot={"role": "document", "children": []},
    )

    async def _broken_snapshot() -> dict[str, object]:
        raise PlaywrightError("locator crashed unexpectedly")

    page.accessibility = SimpleNamespace(snapshot=_broken_snapshot)

    with pytest.raises(PlaywrightError, match="locator crashed unexpectedly"):
        await _page_markdown_via_browser_fetch(page=page)


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_respects_small_interaction_cap(
    patch_settings,
) -> None:
    patch_settings(detail_expand_max_interactions=1)
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


def test_classify_low_content_reason_ignores_empty_phrase_on_contentful_page() -> None:
    html = """
    <html><body>
      <p>Filter summary: 0 results for XXL.</p>
      <article><a href="/products/widget-1">Widget One</a><span>$10</span></article>
      <article><a href="/products/widget-2">Widget Two</a><span>$20</span></article>
      <article><a href="/products/widget-3">Widget Three</a><span>$30</span></article>
      <article><a href="/products/widget-4">Widget Four</a><span>$40</span></article>
      <article><a href="/products/widget-5">Widget Five</a><span>$50</span></article>
    </body></html>
    """

    assert browser_runtime.classify_low_content_reason(
        html,
        html_bytes=len(html.encode("utf-8")),
    ) is None


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
    assert diagnostics["timeout_phase"] == "navigation"


def test_build_failed_browser_diagnostics_preserves_failure_stage() -> None:
    exc = TimeoutError("listing readiness timeout")
    setattr(exc, "browser_failure_stage", "settle")
    setattr(exc, "browser_phase_timings_ms", {"navigation": 420})

    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=exc,
    )

    assert diagnostics["failure_stage"] == "settle"
    assert diagnostics["timeout_phase"] == "settle"
    assert diagnostics["phase_timings_ms"] == {"navigation": 420}


def test_build_failed_browser_diagnostics_marks_unsupported_proxy_explicitly() -> None:
    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=RuntimeError("Browser does not support socks5 proxy authentication"),
    )

    assert diagnostics["browser_outcome"] == "navigation_failed"
    assert diagnostics["failure_kind"] == "unsupported_proxy"


@pytest.mark.asyncio
async def test_browser_fetch_attaches_failure_diagnostics_to_direct_errors() -> None:
    async def _failing_runtime(**_kwargs):
        raise RuntimeError("runtime bootstrap failed")

    with pytest.raises(RuntimeError, match="runtime bootstrap failed") as excinfo:
        await browser_runtime.browser_fetch(
            "https://example.com/products/widget",
            5,
            surface="ecommerce_detail",
            browser_reason="http-escalation",
            runtime_provider=_failing_runtime,
        )

    diagnostics = excinfo.value.browser_diagnostics
    assert diagnostics["browser_outcome"] == "navigation_failed"
    assert diagnostics["failure_kind"] == "navigation_error"


def test_build_failed_browser_diagnostics_uses_exception_proxy_mode() -> None:
    exc = RuntimeError("proxied page failed")
    setattr(exc, "browser_proxy_mode", "page")

    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=exc,
        proxy="http://proxy.example:8080",
    )

    assert diagnostics["browser_proxy_mode"] == "page"


@pytest.mark.asyncio
async def test_browser_fetch_logs_non_usable_outcomes(caplog: pytest.LogCaptureFixture) -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Empty category</h1></body></html>")

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    with caplog.at_level("WARNING", logger=browser_page_flow.logger.name):
        result = await browser_runtime.browser_fetch(
            "https://example.com/empty",
            5,
            surface="ecommerce_listing",
            capture_screenshot=True,
            runtime_provider=_fake_runtime,
        )

    assert result.browser_diagnostics["browser_outcome"] == "low_content_shell"
    assert any(
        "Browser acquisition outcome=low_content_shell url=https://example.com/empty"
        in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_browser_fetch_respects_disabled_screenshot_capture(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Empty category</h1></body></html>")

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    with caplog.at_level("WARNING", logger=browser_page_flow.logger.name):
        result = await browser_runtime.browser_fetch(
            "https://example.com/empty",
            5,
            surface="ecommerce_listing",
            capture_screenshot=False,
            runtime_provider=_fake_runtime,
        )

    assert result.browser_diagnostics["browser_outcome"] == "low_content_shell"
    assert result.browser_diagnostics["phase_timings_ms"]["screenshot_capture"] == 0
    assert not result.artifacts.get("browser_screenshot_path")
    assert not any(
        "Browser acquisition outcome=low_content_shell url=https://example.com/empty"
        in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_browser_fetch_surfaces_rendered_listing_evidence_counts() -> None:
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>"
            "</body></html>"
        ),
        selector_counts={".product-card": 1},
        card_count=1,
        rendered_listing_fragments=[
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a><span>$10</span></article>"
        ],
    )
    page.url = "https://example.com/collections/widgets"

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        runtime_provider=_fake_runtime,
    )

    assert result.browser_diagnostics["rendered_listing_fragment_count"] == 1
    assert result.browser_diagnostics["listing_visual_element_count"] >= 0
    assert result.browser_diagnostics["extractable_listing_evidence"]["rendered_listing_fragments"] == 1


@pytest.mark.asyncio
async def test_browser_fetch_bounds_listing_artifact_capture_time(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    patch_settings,
) -> None:
    patch_settings(browser_artifact_capture_timeout_ms=50)
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a></article>"
            "</body></html>"
        ),
        selector_counts={".product-card": 1},
        card_count=1,
    )
    page.url = "https://example.com/collections/widgets"

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _slow_rendered_listing_fragments(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.2)
        return ["<article><a href='/products/widget-1'>Widget One</a></article>"]

    async def _slow_listing_visual_elements(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.2)
        return [{"tag": "a"}]

    monkeypatch.setattr(
        browser_page_flow,
        "capture_rendered_listing_fragments",
        _slow_rendered_listing_fragments,
    )
    monkeypatch.setattr(
        browser_page_flow,
        "_capture_listing_visual_elements",
        _slow_listing_visual_elements,
    )
    with caplog.at_level("WARNING", logger=browser_page_flow.logger.name):
        result = await browser_runtime.browser_fetch(
            "https://example.com/collections/widgets",
            5,
            surface="ecommerce_listing",
            runtime_provider=_fake_runtime,
        )

    assert result.browser_diagnostics["rendered_listing_fragment_count"] == 0
    assert result.browser_diagnostics["listing_visual_element_count"] == 0
    assert (
        result.browser_diagnostics["phase_timings_ms"]["rendered_listing_fragment_capture"]
        >= 0
    )
    assert (
        result.browser_diagnostics["phase_timings_ms"]["listing_visual_capture"] >= 0
    )
    assert result.browser_diagnostics["listing_artifact_capture"] == {
        "rendered_listing_fragment_capture": {"status": "timeout"},
        "listing_visual_capture": {"status": "timeout"},
    }
    assert any(
        "Timed out during rendered_listing_fragment_capture" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_capture_listing_artifact_with_timeout_reports_playwright_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _boom():
        raise PlaywrightError("Target page, context or browser has been closed")

    with caplog.at_level("DEBUG", logger=browser_page_flow.logger.name):
        artifacts, diagnostics = await browser_page_flow._capture_listing_artifact_with_timeout(
            _boom(),
            stage="listing_visual_capture",
            url="https://example.com/collections/widgets",
        )

    assert artifacts == []
    assert diagnostics == {"status": "closed"}
    assert any(
        "Listing artifact capture Playwright error" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_capture_rendered_listing_fragments_returns_fragment_html() -> None:
    class _RegressionPage:
        async def evaluate(self, script: str, arg: Any | None = None) -> list[str]:
            del arg
            assert "const selectors = Array.isArray(args?.selectors)" in script
            assert "const seenFragments = new Set();" in script
            assert "fragments.push(fragment);" in script
            return [
                "<article><a href='https://example.com/products/widget-one'>Widget One</a><span>$19.99</span></article>"
            ]

    rows = await browser_recovery.capture_rendered_listing_fragments(
        _RegressionPage(),
        surface="ecommerce_listing",
        limit=5,
    )

    assert rows == [
        "<article><a href='https://example.com/products/widget-one'>Widget One</a><span>$19.99</span></article>"
    ]


@pytest.mark.asyncio
async def test_capture_rendered_listing_fragments_ignores_non_listing_surfaces() -> None:
    class _RegressionPage:
        async def evaluate(self, script: str, arg: Any | None = None) -> list[str]:
            raise AssertionError("evaluate should not be called")

    rows = await browser_recovery.capture_rendered_listing_fragments(
        _RegressionPage(),
        surface="ecommerce_detail",
        limit=5,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_emit_challenge_activity_randomizes_mouse_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    move_calls: list[tuple[int, int]] = []
    wheel_calls: list[tuple[int, int]] = []
    wait_calls: list[int] = []

    class _Mouse:
        async def move(self, x: int, y: int) -> None:
            move_calls.append((x, y))

        async def wheel(self, delta_x: int, delta_y: int) -> None:
            wheel_calls.append((delta_x, delta_y))

    class _Page:
        mouse = _Mouse()

        async def evaluate(self, script: str, arg: Any | None = None) -> dict[str, int]:
            del script, arg
            return {"width": 900, "height": 700}

        async def wait_for_timeout(self, delay_ms: int) -> None:
            wait_calls.append(delay_ms)

    random_counter = {"value": 0}

    def _fake_randbelow(limit: int) -> int:
        random_counter["value"] += 1
        return random_counter["value"] % max(1, int(limit))

    monkeypatch.setattr(browser_recovery.secrets, "randbelow", _fake_randbelow)

    await browser_recovery._emit_challenge_activity(_Page())

    assert len(move_calls) == 1 + (
        int(crawler_runtime_settings.challenge_activity_jitter_moves)
        * int(crawler_runtime_settings.challenge_activity_mouse_steps)
    )
    assert all(len(call) == 2 for call in move_calls)
    assert len(set(move_calls)) > 2
    assert wait_calls
    assert wheel_calls == [
        (0, int(crawler_runtime_settings.challenge_activity_scroll_px))
    ]


@pytest.mark.asyncio
async def test_emit_challenge_activity_ignores_negative_scroll(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    wheel_calls: list[tuple[int, int]] = []

    class _Mouse:
        async def move(self, x: int, y: int, *, steps: int) -> None:
            del x, y, steps

        async def wheel(self, delta_x: int, delta_y: int) -> None:
            wheel_calls.append((delta_x, delta_y))

    class _Page:
        mouse = _Mouse()

        async def evaluate(self, script: str, arg: Any | None = None) -> dict[str, int]:
            del script, arg
            return {"width": 900, "height": 700}

        async def wait_for_timeout(self, delay_ms: int) -> None:
            del delay_ms

    monkeypatch.setattr(browser_recovery.secrets, "randbelow", lambda limit: 0)
    patch_settings(challenge_activity_scroll_px=-120)
    await browser_recovery._emit_challenge_activity(_Page())

    assert wheel_calls == []


@pytest.mark.asyncio
async def test_emit_browser_behavior_activity_adds_scroll_physics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    move_calls: list[tuple[int, int]] = []
    wheel_calls: list[tuple[int, int]] = []
    wait_calls: list[int] = []

    class _Mouse:
        async def move(self, x: int, y: int) -> None:
            move_calls.append((x, y))

        async def wheel(self, delta_x: int, delta_y: int) -> None:
            wheel_calls.append((delta_x, delta_y))

    class _Page:
        mouse = _Mouse()

        async def evaluate(self, script: str, arg: Any | None = None) -> dict[str, int]:
            del script, arg
            return {"width": 900, "height": 700}

        async def wait_for_timeout(self, delay_ms: int) -> None:
            wait_calls.append(delay_ms)

    monkeypatch.setattr(browser_recovery.secrets, "randbelow", lambda limit: 0)
    diagnostics = await browser_recovery.emit_browser_behavior_activity(_Page())

    assert diagnostics["enabled"] is True
    assert int(diagnostics["pointer_moves"]) == len(move_calls)
    assert int(diagnostics["scroll_steps"]) == int(
        crawler_runtime_settings.browser_behavior_scroll_steps
    )
    assert len(wheel_calls) == 1 + int(
        crawler_runtime_settings.browser_behavior_scroll_steps
    )
    assert wait_calls


@pytest.mark.asyncio
async def test_type_text_like_human_types_one_character_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed: list[str] = []
    clicks: list[int] = []

    class _Locator:
        async def click(self, *, timeout: int) -> None:
            clicks.append(timeout)

    class _Keyboard:
        async def type(self, value: str) -> None:
            typed.append(value)

    class _Page:
        keyboard = _Keyboard()

        def locator(self, selector: str) -> _Locator:
            assert selector == "input[name=q]"
            return _Locator()

        async def wait_for_timeout(self, delay_ms: int) -> None:
            assert delay_ms >= 0

    monkeypatch.setattr(browser_recovery.secrets, "randbelow", lambda limit: 0)

    diagnostics = await browser_recovery.type_text_like_human(
        _Page(),
        "input[name=q]",
        "shoe",
    )

    assert diagnostics == {"typed_chars": 4}
    assert typed == ["s", "h", "o", "e"]
    assert clicks == [int(crawler_runtime_settings.traversal_click_timeout_ms)]


@pytest.mark.asyncio
async def test_recover_browser_challenge_keeps_original_response_when_retry_stays_blocked() -> None:
    original_response = SimpleNamespace(status=403, name="original")
    retried_response = SimpleNamespace(status=200, name="retried")

    class _Page:
        def __init__(self) -> None:
            self.mouse = None
            self.goto_calls = 0

        async def goto(self, *_args, **_kwargs):
            self.goto_calls += 1
            return retried_response

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    page = _Page()

    async def _get_page_html(_page: Any) -> str:
        return "<html><body>blocked</body></html>"

    async def _classify_blocked_page(_html: str, _status_code: int):
        return SimpleNamespace(blocked=True, provider_hits=[])

    result = await browser_recovery.recover_browser_challenge(
        page,
        url="https://example.com/products/widget",
        response=original_response,
        timeout_seconds=5,
        phase_timings_ms={},
        challenge_wait_max_seconds=1,
        challenge_poll_interval_ms=100,
        navigation_timeout_ms=1000,
        elapsed_ms=lambda _started_at: 0,
        classify_blocked_page=_classify_blocked_page,
        get_page_html=_get_page_html,
    )

    assert result is original_response
    assert page.goto_calls == 1


@pytest.mark.asyncio
async def test_recover_browser_challenge_drops_stale_block_status_after_wait_clear() -> None:
    original_response = SimpleNamespace(status=403, headers={"content-type": "text/html"})
    status_codes: list[int] = []

    class _Page:
        mouse = None

        async def goto(self, *_args, **_kwargs):
            raise AssertionError("retry should not run after challenge clears")

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    async def _get_page_html(_page: Any) -> str:
        return "<html><body>product title $12.00 add to cart</body></html>"

    async def _classify_blocked_page(_html: str, status_code: int):
        status_codes.append(status_code)
        return SimpleNamespace(blocked=len(status_codes) == 1, provider_hits=[])

    result = await browser_recovery.recover_browser_challenge(
        _Page(),
        url="https://example.com/products/widget",
        response=original_response,
        timeout_seconds=5,
        phase_timings_ms={},
        challenge_wait_max_seconds=1,
        challenge_poll_interval_ms=100,
        navigation_timeout_ms=1000,
        elapsed_ms=lambda _started_at: 0,
        classify_blocked_page=_classify_blocked_page,
        get_page_html=_get_page_html,
    )

    assert status_codes == [403, 200]
    assert result is original_response
    assert result.browser_recovered_status == 200
    assert result.headers == original_response.headers


@pytest.mark.asyncio
async def test_recover_browser_challenge_marks_retry_response_without_wrapping() -> None:
    retried_response = SimpleNamespace(
        status=403,
        headers={"content-type": "text/html"},
        url="https://example.com/products/widget",
        request=SimpleNamespace(method="GET"),
        name="retried",
    )

    class _Page:
        mouse = None

        def __init__(self) -> None:
            self.retried = False

        async def goto(self, *_args, **_kwargs):
            self.retried = True
            return retried_response

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    async def _get_page_html(page: Any) -> str:
        return (
            "<html><body>product title $12.00 add to cart</body></html>"
            if page.retried
            else "<html><body>blocked</body></html>"
        )

    async def _classify_blocked_page(html: str, _status_code: int):
        return SimpleNamespace(blocked="blocked" in html, provider_hits=[])

    page = _Page()
    result = await browser_recovery.recover_browser_challenge(
        page,
        url="https://example.com/products/widget",
        response=SimpleNamespace(status=403, headers={"content-type": "text/html"}),
        timeout_seconds=5,
        phase_timings_ms={},
        challenge_wait_max_seconds=1,
        challenge_poll_interval_ms=100,
        navigation_timeout_ms=1000,
        elapsed_ms=lambda _started_at: 0,
        classify_blocked_page=_classify_blocked_page,
        get_page_html=_get_page_html,
    )

    assert result is retried_response
    assert result.browser_recovered_status == 200
    assert result.url == retried_response.url
    assert result.request is retried_response.request
    assert result.name == "retried"
    assert result.browser_navigation_strategy == "domcontentloaded"


@pytest.mark.asyncio
async def test_get_page_html_falls_back_to_outer_html_after_driver_close(
    patch_settings,
) -> None:
    patch_settings(browser_error_retry_attempts=1, browser_error_retry_delay_ms=0)

    class _Page:
        def __init__(self) -> None:
            self.content_calls = 0

        async def content(self) -> str:
            self.content_calls += 1
            raise RuntimeError("Page.content: Connection closed while reading from the driver")

        async def evaluate(self, script: str):
            if "flattenedRoots" in script:
                return 0
            return "<html><body><main><h1>Recovered</h1></main></body></html>"

    html = await dom_runtime.get_page_html(_Page())

    assert "Recovered" in html


@pytest.mark.asyncio
async def test_get_page_html_outer_html_fallback_preserves_doctype(
    patch_settings,
) -> None:
    patch_settings(browser_error_retry_attempts=0, browser_error_retry_delay_ms=0)

    class _Page:
        async def content(self) -> str:
            raise RuntimeError("Page.content: Connection closed while reading from the driver")

        async def evaluate(self, script: str):
            if "flattenedRoots" in script:
                return 0
            return "<!DOCTYPE html><html><body>Recovered</body></html>"

    html = await dom_runtime.get_page_html(_Page())

    assert html.startswith("<!DOCTYPE html>")


@pytest.mark.asyncio
async def test_page_has_location_interstitial_uses_resilient_html_fetch(
    patch_settings,
) -> None:
    patch_settings(browser_error_retry_attempts=0, browser_error_retry_delay_ms=0)

    class _Page:
        url = "https://example.com/product"

        async def content(self) -> str:
            raise RuntimeError("Page.content: Connection closed while reading from the driver")

        async def evaluate(self, script: str):
            if "flattenedRoots" in script:
                return 0
            return (
                "<html><body>"
                "<div role='dialog'>Choose your location to continue</div>"
                "</body></html>"
            )

    detected = await browser_page_flow._page_has_location_interstitial(_Page())

    assert detected is True


def test_browser_diagnostics_preserves_existing_retry_reason_and_timings() -> None:
    diagnostics = browser_runtime.build_browser_diagnostics_contract(
        diagnostics={
            "retry_reason": "empty_extraction",
            "phase_timings_ms": {"navigation": 120},
        },
        retry_reason="",
        phase_timings_ms={"content_serialization": 20},
    )

    assert diagnostics["retry_reason"] == "empty_extraction"
    assert diagnostics["phase_timings_ms"] == {
        "navigation": 120,
        "content_serialization": 20,
    }


def test_browser_diagnostics_contract_clears_stale_nested_outcome_fields() -> None:
    diagnostics = browser_runtime.build_browser_diagnostics_contract(
        diagnostics={
            "browser_reason": "nested",
            "browser_outcome": "location_required",
            "failure_reason": "location_required",
        },
        browser_reason="",
        browser_outcome="",
        failure_reason="",
    )

    assert diagnostics["browser_reason"] is None
    assert diagnostics["browser_outcome"] is None
    assert diagnostics["failure_reason"] is None


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

    async def _fake_runtime(**_kwargs):
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
async def test_origin_warmup_uses_sibling_page_not_active_page() -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Widget</h1></body></html>")

    await browser_runtime._maybe_warm_origin_before_navigation(
        page,
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        browser_reason="http-escalation",
        proxy_profile=None,
        timeout_seconds=5,
        phase_timings_ms={},
    )

    assert page.goto_calls == []
    assert len(page.spawned_pages) == 1
    assert page.spawned_pages[0].goto_calls == ["domcontentloaded"]
    assert page.spawned_pages[0].page_close_calls == 1


@pytest.mark.asyncio
async def test_origin_warmup_runs_for_job_detail() -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Job</h1></body></html>")

    await browser_runtime._maybe_warm_origin_before_navigation(
        page,
        url="https://example.com/jobs/123",
        surface="job_detail",
        browser_reason="http-escalation",
        proxy_profile=None,
        timeout_seconds=5,
        phase_timings_ms={},
    )

    assert page.goto_calls == []
    assert len(page.spawned_pages) == 1


@pytest.mark.asyncio
async def test_origin_warmup_skips_for_listing_surface() -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Products</h1></body></html>")

    await browser_runtime._maybe_warm_origin_before_navigation(
        page,
        url="https://example.com/category/widgets",
        surface="ecommerce_listing",
        browser_reason="http-escalation",
        proxy_profile=None,
        timeout_seconds=5,
        phase_timings_ms={},
    )

    assert page.goto_calls == []
    assert page.spawned_pages == []


@pytest.mark.asyncio
async def test_origin_warmup_skips_for_rotating_proxy_profile() -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Widget</h1></body></html>")

    await browser_runtime._maybe_warm_origin_before_navigation(
        page,
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        browser_reason="http-escalation",
        proxy_profile={"rotation": "rotating"},
        timeout_seconds=5,
        phase_timings_ms={},
    )

    assert page.goto_calls == []
    assert page.spawned_pages == []


@pytest.mark.asyncio
async def test_origin_warmup_runs_without_stealth_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(base_html="<html><body><h1>Widget</h1></body></html>")
    del monkeypatch

    await browser_runtime._maybe_warm_origin_before_navigation(
        page,
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        browser_engine="real_chrome",
        browser_reason="http-escalation",
        proxy_profile=None,
        timeout_seconds=5,
        phase_timings_ms={},
    )

    assert page.spawned_pages


def test_browser_runtime_snapshot_uses_capacity_fallback_for_pooled_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRuntime:
        def snapshot(self) -> dict[str, int | bool]:
            return {
                "ready": True,
                "size": 1,
                "active": 1,
                "queued": 0,
                "capacity": 3,
            }

        async def close(self) -> None:
            return None

    monkeypatch.setattr(browser_runtime, "_DIRECT_BROWSER_RUNTIMES", {"direct": _FakeRuntime()})
    monkeypatch.setattr(browser_runtime, "_PROXIED_BROWSER_RUNTIMES", {"proxy": _FakeRuntime()})

    snapshot = browser_runtime.browser_runtime_snapshot()

    assert snapshot["capacity"] == 6
    assert snapshot["max_size"] == 6


@pytest.mark.asyncio
async def test_browser_fetch_disables_storage_reuse_for_rotating_proxy_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_allow_storage_state: list[bool] = []

    class _StopFetch(Exception):
        pass

    @asynccontextmanager
    async def _fake_page_context():
        raise _StopFetch
        yield

    def _fake_resolve_proxied_page_factory(*args, **kwargs):
        del args
        captured_allow_storage_state.append(bool(kwargs["allow_storage_state"]))
        return _fake_page_context()

    monkeypatch.setattr(
        browser_runtime,
        "_resolve_proxied_page_factory",
        _fake_resolve_proxied_page_factory,
    )

    with pytest.raises(_StopFetch):
        await browser_runtime.browser_fetch(
            "https://example.com/products/widget",
            5,
            proxy="http://proxy.example:8080",
            proxy_profile={"rotation": "rotating"},
            surface="ecommerce_detail",
            proxied_page_factory=lambda **_: None,
        )

    assert captured_allow_storage_state == [False]


@pytest.mark.asyncio
async def test_browser_fetch_recovers_when_commit_navigation_is_interrupted_by_same_url_reload() -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget</h1></body></html>",
        goto_failures={
            "domcontentloaded": PlaywrightTimeoutError("primary timeout"),
            "commit": PlaywrightError(
                'Navigation to "https://example.com/products/widget" is interrupted '
                'by another navigation to "https://example.com/products/widget"'
            ),
        },
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    result = await browser_runtime.browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
        runtime_provider=_fake_runtime,
    )

    assert page.goto_calls == ["domcontentloaded", "commit"]
    assert "domcontentloaded" in page.load_state_calls
    assert result.final_url == "https://example.com/products/widget"
    assert result.status_code == 0


@pytest.mark.asyncio
async def test_browser_fetch_force_closes_context_when_cancelled_mid_stage() -> None:
    content_entered = asyncio.Event()
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget</h1></body></html>",
        content_blocker=asyncio.Event(),
        ignore_content_cancellation=True,
        content_entered=content_entered,
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    task = asyncio.create_task(
        browser_runtime.browser_fetch(
            "https://example.com/products/widget",
            5,
            surface="ecommerce_detail",
            runtime_provider=_fake_runtime,
        )
    )

    await asyncio.wait_for(content_entered.wait(), timeout=0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)

    assert page.page_close_calls + page.context_close_calls >= 1


@pytest.mark.asyncio
async def test_browser_fetch_force_closes_context_when_stage_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html="<html><body><h1>Widget</h1></body></html>",
        content_blocker=asyncio.Event(),
        content_block_after_calls=1,
        ignore_content_cancellation=True,
    )

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    remaining_timeouts = iter([5.0, 0.05, 0.05, 0.05])
    monkeypatch.setattr(
        browser_runtime,
        "remaining_timeout_factory",
        lambda _deadline: (lambda: next(remaining_timeouts, 0.05)),
    )

    with pytest.raises(TimeoutError, match="Browser settle stage exceeded") as excinfo:
        await asyncio.wait_for(
            browser_runtime.browser_fetch(
                "https://example.com/products/widget",
                5,
                surface="ecommerce_detail",
                browser_reason="http-escalation",
                runtime_provider=_fake_runtime,
            ),
            timeout=0.5,
        )

    diagnostics = browser_runtime.build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=excinfo.value,
    )

    assert page.page_close_calls + page.context_close_calls >= 1
    assert diagnostics["failure_stage"] == "settle"
    assert diagnostics["browser_outcome"] == "render_timeout"


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

    async def _fake_runtime(**_kwargs):
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

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _fake_execute_listing_traversal(*args, **kwargs):
        del args, kwargs
        return TraversalResult(
            requested_mode="paginate",
            selected_mode="paginate",
            activated=True,
            stop_reason="next_page_not_found",
            progress_events=0,
            card_count=5,
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

    async def _fake_runtime(**_kwargs):
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
    assert "Widget Two" in result.artifacts["full_rendered_html"]


@pytest.mark.asyncio
async def test_browser_fetch_runs_listing_recovery_when_thin_listing_retry_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        base_html=(
            "<html><body>"
            "<button>View all</button>"
            "<article class='product-card'><a href='/products/widget-1'>Widget One</a></article>"
            "</body></html>"
        ),
    )
    page.url = "https://example.com/collections/widgets"
    calls = {"count": 0}

    async def _fake_runtime(**_kwargs):
        return _FakeRuntime(page)

    async def _fake_recover_listing_page_content(*args, **kwargs):
        del args, kwargs
        calls["count"] += 1
        return {
            "status": "recovered",
            "clicked_count": 1,
            "actions_taken": ["view_all"],
        }

    monkeypatch.setattr(
        browser_runtime,
        "recover_listing_page_content",
        _fake_recover_listing_page_content,
    )

    result = await browser_runtime.browser_fetch(
        "https://example.com/collections/widgets",
        5,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        listing_recovery_mode="thin-listing retry",
        runtime_provider=_fake_runtime,
    )

    assert calls["count"] == 1
    assert result.browser_diagnostics["listing_recovery"]["status"] == "recovered"
    assert result.browser_diagnostics["listing_recovery"]["requested_mode"] == "thin_listing"
