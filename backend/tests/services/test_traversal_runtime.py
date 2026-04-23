from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import app.services.acquisition.traversal as traversal_module

from app.services.acquisition.traversal import (
    TraversalResult,
    _click_with_retry,
    _locator_still_resolves,
    count_listing_cards,
    dismiss_overlays_if_needed,
    execute_listing_traversal,
)
from app.services.config.selectors import CARD_SELECTORS, PAGINATION_SELECTORS


@dataclass
class _State:
    html: str
    card_count: int
    scroll_height: int
    client_height: int = 600
    overflow_containers: int = 0
    controls: set[str] | None = None
    role_controls: list[dict[str, Any]] | None = None
    next_href: str | None = None
    next_control_state: dict[str, Any] | None = None


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def count(self) -> int:
        if self._selector in _card_selectors(self._page.surface):
            return int(self._page.state.card_count)
        return int(_selector_group(self._selector) in (self._page.state.controls or set()))

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return await self.count() > 0

    async def is_disabled(self) -> bool:
        return False

    async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        del timeout

    async def click(self, timeout: int | None = None, force: bool = False) -> None:
        del timeout, force
        group = _selector_group(self._selector)
        if group == "load_more":
            self._page.load_more_clicks += 1
            self._page.state = self._page.load_more_states[min(self._page.load_more_clicks, len(self._page.load_more_states) - 1)]
            return
        if group == "next_page":
            next_href = str(self._page.state.next_href or "").strip().lower()
            if next_href and not next_href.startswith(("#", "javascript:")):
                await self._page.goto(self._page.state.next_href or self._page.url)
                return
            self._page.page_index = min(self._page.page_index + 1, len(self._page.paginated_states) - 1)
            self._page.state = self._page.paginated_states[self._page.page_index]

    async def get_attribute(self, name: str) -> str | None:
        if name == "href" and _selector_group(self._selector) == "next_page":
            return self._page.state.next_href
        return None

    async def evaluate(self, script: str) -> Any:
        del script
        if _selector_group(self._selector) == "next_page":
            return dict(self._page.state.next_control_state or {})
        return {}


class _EmptyRoleLocator:
    async def count(self) -> int:
        return 0

    def nth(self, index: int) -> "_EmptyRoleLocator":
        del index
        return self

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return False

    async def is_disabled(self) -> bool:
        return False


class _RoleLocator:
    def __init__(self, page: "_FakePage", matches: list[dict[str, Any]]) -> None:
        self._page = page
        self._matches = matches

    async def count(self) -> int:
        return len(self._matches)

    def nth(self, index: int) -> "_RoleLocator":
        if index >= len(self._matches):
            return _RoleLocator(self._page, [])
        return _RoleLocator(self._page, [self._matches[index]])

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        if not self._matches:
            return False
        return bool(self._matches[0].get("visible", True))

    async def is_disabled(self) -> bool:
        if not self._matches:
            return True
        return bool(self._matches[0].get("disabled", False))

    async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        del timeout

    async def evaluate(self, script: str) -> Any:
        del script
        return None

    async def click(self, timeout: int | None = None, force: bool = False) -> None:
        del timeout, force
        if not self._matches:
            return
        self._page.role_clicks.append(str(self._matches[0].get("name") or ""))


class _FakePage:
    def __init__(
        self,
        *,
        surface: str,
        initial_state: _State,
        paginated_states: list[_State] | None = None,
        load_more_states: list[_State] | None = None,
        scroll_states: list[_State] | None = None,
    ) -> None:
        self.surface = surface
        self.state = initial_state
        self.paginated_states = list(paginated_states or [initial_state])
        self.load_more_states = list(load_more_states or [initial_state])
        self.scroll_states = list(scroll_states or [initial_state])
        self.url = "https://example.com/listing"
        self.page_index = 0
        self.scroll_index = 0
        self.load_more_clicks = 0
        self.goto_calls: list[str] = []
        self.load_state_calls: list[str] = []
        self.wait_timeout_calls: list[int] = []
        self.mutation_settle_calls = 0
        self.role_clicks: list[str] = []

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def get_by_role(self, role: str, name: object = None) -> _EmptyRoleLocator | _RoleLocator:
        matches: list[dict[str, Any]] = []
        for control in list(self.state.role_controls or []):
            if str(control.get("role") or "") != role:
                continue
            candidate_name = str(control.get("name") or "")
            if hasattr(name, "search"):
                if not name.search(candidate_name):
                    continue
            elif name is not None and candidate_name != name:
                continue
            matches.append(control)
        if not matches:
            return _EmptyRoleLocator()
        return _RoleLocator(self, matches)

    async def evaluate(self, script: str, arg: Any | None = None) -> Any:
        if "scrollTo({" in script:
            self.scroll_index = min(self.scroll_index + 1, len(self.scroll_states) - 1)
            self.state = self.scroll_states[self.scroll_index]
            return None
        if "querySelectorAll(selector).length" in script:
            selectors = list(arg or [])
            highest = 0
            for selector in selectors:
                if selector in _card_selectors(self.surface):
                    highest = max(highest, int(self.state.card_count))
            return highest
        if "MutationObserver" in script:
            self.mutation_settle_calls += 1
            return {"observed": True}
        return {
            "scroll_height": self.state.scroll_height,
            "client_height": self.state.client_height,
            "overflow_containers": self.state.overflow_containers,
        }

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_timeout_calls.append(timeout_ms)

    async def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        del timeout
        self.load_state_calls.append(state)

    async def content(self) -> str:
        return self.state.html

    async def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
        del wait_until, timeout
        self.goto_calls.append(url)
        self.url = url
        self.page_index = min(self.page_index + 1, len(self.paginated_states) - 1)
        self.state = self.paginated_states[self.page_index]


class _OverlayTestLocator:
    def __init__(self) -> None:
        self.evaluate_calls: list[str] = []

    async def evaluate(self, script: str) -> int:
        self.evaluate_calls.append(script)
        return 1


class _OverlayTestPage:
    def locator(self, selector: str) -> "_OverlayCookieLocator":
        del selector
        return _OverlayCookieLocator()

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        del timeout_ms


class _OverlayCookieLocator:
    @property
    def first(self) -> "_OverlayCookieLocator":
        return self

    async def count(self) -> int:
        return 0

    async def is_visible(self, timeout: int | None = None) -> bool:
        del timeout
        return False


def _selector_group(selector: str) -> str:
    for group, selectors in PAGINATION_SELECTORS.items():
        if selector in selectors:
            return str(group)
    return ""


def _card_selectors(surface: str) -> list[str]:
    group = "jobs" if surface.startswith("job_") else "ecommerce"
    return list(CARD_SELECTORS.get(group) or [])


@pytest.mark.asyncio
async def test_auto_traversal_prefers_paginate_and_collects_multiple_pages() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
            _State(
                html="<div>page-2</div>",
                card_count=5,
                scroll_height=1400,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="auto",
        max_pages=3,
        max_scrolls=2,
    )

    assert result.selected_mode == "paginate"
    assert result.pages_advanced == 1
    assert result.progress_events == 1
    fragments = [fragment for fragment, _ in result.html_fragments]
    assert "page-1" in "\n".join(fragments)
    assert "page-2" in "\n".join(fragments)


@pytest.mark.asyncio
async def test_paginate_traversal_does_not_append_duplicate_html_without_progress() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
            ),
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=2,
        max_scrolls=1,
    )

    assert result.stop_reason == "paginate_no_progress"
    assert [f for f, _ in result.html_fragments] == ["<div>page-1</div>"]


@pytest.mark.asyncio
async def test_paginate_traversal_stops_when_card_count_stays_zero() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1 chrome</div>",
            card_count=0,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
        ),
        paginated_states=[
            _State(
                html="<div>page-1 chrome</div>",
                card_count=0,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
            _State(
                html="<div>page-2 different chrome</div>",
                card_count=0,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=3",
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=3,
        max_scrolls=1,
    )

    assert result.stop_reason == "paginate_no_progress"
    assert result.progress_events == 0
    assert result.pages_advanced == 0


@pytest.mark.asyncio
async def test_paginate_traversal_blocks_off_domain_links() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://ads.example.net/promo",
        ),
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=2,
        max_scrolls=1,
    )

    assert result.stop_reason == "paginate_off_domain"
    assert [f for f, _ in result.html_fragments] == ["<div>page-1</div>"]
    assert page.goto_calls == []


@pytest.mark.asyncio
async def test_paginate_traversal_logs_explicit_stop_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://ads.example.net/promo",
        ),
    )

    with caplog.at_level("INFO"):
        result = await execute_listing_traversal(
            page,
            surface="ecommerce_listing",
            traversal_mode="paginate",
            max_pages=2,
            max_scrolls=1,
        )

    assert result.stop_reason == "paginate_off_domain"
    assert "stop_reason=paginate_off_domain" in caplog.text


@pytest.mark.asyncio
async def test_paginate_traversal_waits_for_navigation_transition() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
            _State(
                html="<div>page-2</div>",
                card_count=4,
                scroll_height=1500,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=2,
        max_scrolls=1,
    )

    assert result.pages_advanced == 1
    assert "domcontentloaded" in page.load_state_calls
    assert "networkidle" in page.load_state_calls


@pytest.mark.asyncio
async def test_auto_traversal_prefers_paginate_for_spa_next_button() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=2500,
            client_height=600,
            controls={"next_page"},
            next_href="#",
            next_control_state={
                "raw_href": "#",
                "has_click_handler": True,
                "pagination_container": True,
                "pagination_text": True,
                "sibling_page_numbers": True,
                "is_button_like": False,
            },
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=2500,
                client_height=600,
                controls={"next_page"},
                next_href="#",
                next_control_state={
                    "raw_href": "#",
                    "has_click_handler": True,
                    "pagination_container": True,
                    "pagination_text": True,
                    "sibling_page_numbers": True,
                    "is_button_like": False,
                },
            ),
            _State(
                html="<div>page-2</div>",
                card_count=5,
                scroll_height=2800,
                client_height=600,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="auto",
        max_pages=2,
        max_scrolls=2,
    )

    assert result.selected_mode == "paginate"
    assert result.pages_advanced == 1
    assert result.progress_events == 1
    assert [f for f, _ in result.html_fragments] == ["<div>page-1</div>", "<div>page-2</div>"]


@pytest.mark.asyncio
async def test_auto_traversal_prefers_paginate_for_numeric_arrow_button() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1800,
            client_height=600,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
            next_control_state={
                "raw_href": "https://example.com/listing?page=2",
                "has_click_handler": False,
                "pagination_container": True,
                "pagination_text": False,
                "sibling_page_numbers": True,
                "follows_current_page": True,
                "arrow_only": True,
                "is_button_like": True,
            },
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1800,
                client_height=600,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
                next_control_state={
                    "raw_href": "https://example.com/listing?page=2",
                    "has_click_handler": False,
                    "pagination_container": True,
                    "pagination_text": False,
                    "sibling_page_numbers": True,
                    "follows_current_page": True,
                    "arrow_only": True,
                    "is_button_like": True,
                },
            ),
            _State(
                html="<div>page-2</div>",
                card_count=5,
                scroll_height=2100,
                client_height=600,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="auto",
        max_pages=2,
        max_scrolls=2,
    )

    assert result.selected_mode == "paginate"
    assert result.pages_advanced == 1
    assert result.progress_events == 1


@pytest.mark.asyncio
async def test_looks_like_paginate_control_rejects_plain_href_without_pagination_signals() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1800,
            controls={"next_page"},
            next_href="https://example.com/products/widget",
            next_control_state={
                "raw_href": "https://example.com/products/widget",
                "has_click_handler": False,
                "pagination_container": False,
                "pagination_text": False,
                "sibling_page_numbers": False,
                "follows_current_page": False,
                "arrow_only": False,
                "is_button_like": False,
            },
        ),
    )

    locator = page.locator(PAGINATION_SELECTORS["next_page"][0]).first

    assert await traversal_module._looks_like_paginate_control(locator) is False


@pytest.mark.asyncio
async def test_paginate_traversal_stops_before_recording_block_challenge() -> None:
    challenge_html = """
    <html>
      <head><title>Just a moment...</title></head>
      <body>
        <main>Checking your browser before accessing Cloudflare protected content.</main>
        <div id="cf-challenge-running">Just a moment...</div>
      </body>
    </html>
    """
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
            _State(
                html=challenge_html,
                card_count=0,
                scroll_height=900,
                controls=set(),
            ),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=2,
        max_scrolls=1,
    )

    assert result.stop_reason == "paginate_blocked"
    assert result.pages_advanced == 0
    assert result.progress_events == 0
    assert [f for f, _ in result.html_fragments] == ["<div>page-1</div>"]


@pytest.mark.asyncio
async def test_auto_traversal_chooses_load_more_when_button_present() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>before</div>",
            card_count=2,
            scroll_height=900,
            controls={"load_more"},
        ),
        load_more_states=[
            _State(html="<div>before</div>", card_count=2, scroll_height=900, controls={"load_more"}),
            _State(html="<div>after</div>", card_count=5, scroll_height=1200, controls=set()),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="auto",
        max_pages=2,
        max_scrolls=2,
    )

    assert result.selected_mode == "load_more"
    assert result.load_more_clicks == 1
    assert result.progress_events == 1
    assert result.card_count == 5
    assert [f for f, _ in result.html_fragments] == ["<div>before</div>", "<div>after</div>"]
    assert "networkidle" in page.load_state_calls


@pytest.mark.asyncio
async def test_auto_traversal_chooses_scroll_from_page_signals() -> None:
    page = _FakePage(
        surface="job_listing",
        initial_state=_State(
            html="<div>jobs</div>",
            card_count=2,
            scroll_height=2500,
            client_height=600,
            controls=set(),
        ),
        scroll_states=[
            _State(html="<div>jobs</div>", card_count=2, scroll_height=2500, client_height=600, controls=set()),
            _State(html="<div>jobs more</div>", card_count=6, scroll_height=3400, client_height=600, controls=set()),
            _State(html="<div>jobs done</div>", card_count=6, scroll_height=3400, client_height=600, controls=set()),
        ],
    )

    result = await execute_listing_traversal(
        page,
        surface="job_listing",
        traversal_mode="auto",
        max_pages=2,
        max_scrolls=3,
    )

    assert result.selected_mode == "scroll"
    assert result.scroll_iterations >= 1
    assert result.progress_events >= 1
    assert result.card_count == 6
    assert [f for f, _ in result.html_fragments][:2] == [
        "<div>jobs</div>",
        "<div>jobs more</div>",
    ]


@pytest.mark.asyncio
async def test_auto_traversal_falls_back_to_scroll_when_auto_detection_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(
        surface="job_listing",
        initial_state=_State(
            html="<div>jobs</div>",
            card_count=2,
            scroll_height=2500,
            client_height=600,
            controls=set(),
        ),
        scroll_states=[
            _State(html="<div>jobs</div>", card_count=2, scroll_height=2500, client_height=600, controls=set()),
            _State(html="<div>jobs more</div>", card_count=6, scroll_height=3400, client_height=600, controls=set()),
        ],
    )

    async def _detect_none(*args, **kwargs):
        del args, kwargs
        return None

    async def _scroll_signals(*args, **kwargs):
        del args, kwargs
        return True

    monkeypatch.setattr(traversal_module, "_detect_auto_mode", _detect_none)
    monkeypatch.setattr(traversal_module, "_has_scroll_signals", _scroll_signals)

    result = await execute_listing_traversal(
        page,
        surface="job_listing",
        traversal_mode="auto",
        max_pages=2,
        max_scrolls=2,
    )

    assert result.selected_mode == "scroll"
    assert result.stop_reason != "no_mode_detected"
    assert result.scroll_iterations >= 1


@pytest.mark.asyncio
async def test_paginate_click_transition_uses_networkidle_settle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=2500,
            client_height=600,
            controls={"next_page"},
            next_href="#",
            next_control_state={
                "raw_href": "#",
                "has_click_handler": True,
                "pagination_container": True,
                "pagination_text": True,
                "sibling_page_numbers": True,
                "is_button_like": False,
            },
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=2500,
                client_height=600,
                controls={"next_page"},
                next_href="#",
                next_control_state={
                    "raw_href": "#",
                    "has_click_handler": True,
                    "pagination_container": True,
                    "pagination_text": True,
                    "sibling_page_numbers": True,
                    "is_button_like": False,
                },
            ),
            _State(
                html="<div>page-2</div>",
                card_count=5,
                scroll_height=2800,
                client_height=600,
                controls=set(),
            ),
        ],
    )
    settle_timeouts: list[int] = []

    async def _capture_settle(page_arg, *, quiet_window_ms: int, timeout_ms: int):
        del page_arg, quiet_window_ms
        settle_timeouts.append(timeout_ms)
        return {"observed": True}

    monkeypatch.setattr(traversal_module, "wait_for_dom_mutation_settle", _capture_settle)

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=2,
        max_scrolls=1,
    )

    assert result.pages_advanced == 1
    assert settle_timeouts
    assert max(settle_timeouts) >= int(
        traversal_module.crawler_runtime_settings.traversal_settle_networkidle_timeout_ms
    )


@pytest.mark.asyncio
async def test_scroll_traversal_emits_live_events() -> None:
    emitted: list[tuple[str, str]] = []
    page = _FakePage(
        surface="job_listing",
        initial_state=_State(
            html="<div>jobs</div>",
            card_count=2,
            scroll_height=2500,
            client_height=600,
            controls=set(),
        ),
        scroll_states=[
            _State(html="<div>jobs</div>", card_count=2, scroll_height=2500, client_height=600, controls=set()),
            _State(html="<div>jobs more</div>", card_count=6, scroll_height=3400, client_height=600, controls=set()),
            _State(html="<div>jobs done</div>", card_count=6, scroll_height=3400, client_height=600, controls=set()),
        ],
    )

    async def _on_event(level: str, message: str) -> None:
        emitted.append((level, message))

    await execute_listing_traversal(
        page,
        surface="job_listing",
        traversal_mode="scroll",
        max_pages=2,
        max_scrolls=3,
        on_event=_on_event,
    )

    assert emitted[:2] == [
        ("info", "Detected listing layout, pagination: scroll"),
        ("info", "Scroll 1/3 - 2 -> 6 records"),
    ]


@pytest.mark.asyncio
async def test_paginate_traversal_detects_cycle_on_redirect_loop() -> None:
    """If a ?page=999 redirects back to ?page=1, the crawler must stop
    instead of infinite-looping until max_pages is hit."""
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="<div>page-1</div>",
            card_count=2,
            scroll_height=1200,
            controls={"next_page"},
            next_href="https://example.com/listing?page=2",
        ),
        paginated_states=[
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
            # Server redirects ?page=2 back to ?page=1 (cycle)
            _State(
                html="<div>page-1</div>",
                card_count=2,
                scroll_height=1200,
                controls={"next_page"},
                next_href="https://example.com/listing?page=2",
            ),
        ],
    )
    # Simulate the redirect: goto sets url to ?page=2 but the fake page
    # state ends up identical to page-1.  Override url after goto to
    # simulate server-side redirect back to page-1.
    original_goto = page.goto
    async def _redirect_goto(url, **kw):
        await original_goto(url, **kw)
        page.url = "https://example.com/listing"  # redirected back
    page.goto = _redirect_goto

    result = await execute_listing_traversal(
        page,
        surface="ecommerce_listing",
        traversal_mode="paginate",
        max_pages=5,
        max_scrolls=1,
    )

    assert result.stop_reason == "paginate_cycle_detected"
    assert result.pages_advanced == 0


@pytest.mark.asyncio
async def test_is_same_origin_blocks_cross_tenant_paths() -> None:
    """Pagination must not bleed across path-based multi-tenant boundaries."""
    from app.services.acquisition.traversal import _is_same_origin

    assert _is_same_origin(
        "https://myworkdayjobs.com/TenantA/jobs?page=1",
        "https://myworkdayjobs.com/TenantA/jobs?page=2",
    )
    assert not _is_same_origin(
        "https://myworkdayjobs.com/TenantA/jobs?page=1",
        "https://myworkdayjobs.com/TenantB/jobs?page=1",
    )


@pytest.mark.asyncio
async def test_is_same_origin_blocks_cross_tenant_paths_for_workday_subdomains() -> None:
    from app.services.acquisition.traversal import _is_same_origin

    assert _is_same_origin(
        "https://smithnephew.wd5.myworkdayjobs.com/TenantA/jobs?page=1",
        "https://smithnephew.wd5.myworkdayjobs.com/TenantA/jobs?page=2",
    )
    assert not _is_same_origin(
        "https://smithnephew.wd5.myworkdayjobs.com/TenantA/jobs?page=1",
        "https://smithnephew.wd5.myworkdayjobs.com/TenantB/jobs?page=1",
    )


@pytest.mark.asyncio
async def test_is_same_origin_allows_same_tenant_different_pages() -> None:
    from app.services.acquisition.traversal import _is_same_origin

    assert _is_same_origin(
        "https://example.com/listing?page=1",
        "https://example.com/listing?page=2",
    )
    assert not _is_same_origin(
        "https://example.com/listing?page=1",
        "https://other.com/listing?page=2",
    )


@pytest.mark.asyncio
async def test_is_same_origin_allows_same_host_path_changes_outside_tenant_hosts() -> None:
    from app.services.acquisition.traversal import _is_same_origin

    assert _is_same_origin(
        "https://example.com/careers?page=1",
        "https://example.com/jobs?page=2",
    )


@pytest.mark.asyncio
async def test_dismiss_overlays_targets_interceptors_not_structural_tags() -> None:
    page = _OverlayTestPage()
    locator = _OverlayTestLocator()
    result = TraversalResult(requested_mode="paginate")

    await dismiss_overlays_if_needed(page, locator=locator, result=result)

    assert result.overlays_dismissed is True
    assert locator.evaluate_calls
    script = locator.evaluate_calls[0]
    assert "elementsFromPoint" in script
    assert "const tags = ['header', 'footer', 'nav']" not in script


@pytest.mark.asyncio
async def test_count_listing_cards_uses_myntra_card_selector() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="""
            <ul class="results-base">
              <li class="product-base"><a href="/a">A</a></li>
              <li class="product-base"><a href="/b">B</a></li>
              <li class="product-base"><a href="/c">C</a></li>
            </ul>
            """,
            card_count=3,
            scroll_height=1200,
            controls=set(),
        ),
    )

    count = await count_listing_cards(page, surface="ecommerce_listing")

    assert count == 3


@pytest.mark.asyncio
async def test_count_listing_cards_uses_zara_product_grid_selector() -> None:
    page = _FakePage(
        surface="ecommerce_listing",
        initial_state=_State(
            html="""
            <ul class="product-grid">
              <li class="product-grid-product"><a href="/in/en/product-a-p0001.html">A</a></li>
              <li class="product-grid-product"><a href="/in/en/product-b-p0002.html">B</a></li>
            </ul>
            """,
            card_count=12,
            scroll_height=1600,
            controls=set(),
        ),
    )

    count = await count_listing_cards(page, surface="ecommerce_listing")

    assert count == 12


@pytest.mark.asyncio
async def test_count_listing_cards_falls_back_to_heuristics_when_selectors_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ZeroLocator:
        async def count(self) -> int:
            return 0

    class _SelectorPage:
        def locator(self, selector: str) -> _ZeroLocator:
            del selector
            return _ZeroLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> int | None:
            del arg
            if "querySelectorAll(selector).length" in script:
                return 0
            return None

        async def content(self) -> str:
            return """
            <html>
              <body>
                <section class="results-grid">
                  <article class="product-card">
                    <a href="/products/widget-a"><img src="/a.jpg" alt="A" />Widget A</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-b"><img src="/b.jpg" alt="B" />Widget B</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-c"><img src="/c.jpg" alt="C" />Widget C</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-d"><img src="/d.jpg" alt="D" />Widget D</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-e"><img src="/e.jpg" alt="E" />Widget E</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-f"><img src="/f.jpg" alt="F" />Widget F</a>
                  </article>
                  <article class="product-card">
                    <a href="/products/widget-g"><img src="/g.jpg" alt="G" />Widget G</a>
                  </article>
                </section>
              </body>
            </html>
            """

    monkeypatch.setattr(
        "app.services.acquisition.traversal.CARD_SELECTORS",
        {"ecommerce": [".product-card"], "jobs": [".job-card"]},
    )

    count = await count_listing_cards(_SelectorPage(), surface="ecommerce_listing")

    assert count == 7


@pytest.mark.asyncio
async def test_count_listing_cards_heuristic_rejects_detail_sections_with_support_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ZeroLocator:
        async def count(self) -> int:
            return 0

    class _SelectorPage:
        def locator(self, selector: str) -> _ZeroLocator:
            del selector
            return _ZeroLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> int | None:
            del arg
            if "querySelectorAll(selector).length" in script:
                return 0
            return None

        async def content(self) -> str:
            return """
            <html>
              <body>
                <main>
                  <section class="product-details">
                    <h2>Shipping information</h2>
                    <p>Read the delivery policy and returns process for this product.</p>
                    <a href="/shipping">Shipping policy</a>
                  </section>
                  <section class="product-details">
                    <h2>Warranty</h2>
                    <p>Find the product warranty terms and support instructions here.</p>
                    <a href="/support/warranty">Warranty terms</a>
                  </section>
                  <section class="product-details">
                    <h2>Care guide</h2>
                    <p>Learn how to clean and maintain the product after purchase.</p>
                    <a href="/support/care">Care guide</a>
                  </section>
                </main>
              </body>
            </html>
            """

    monkeypatch.setattr(
        "app.services.acquisition.traversal.CARD_SELECTORS",
        {"ecommerce": [".product-card"], "jobs": [".job-card"]},
    )

    count = await count_listing_cards(_SelectorPage(), surface="ecommerce_listing")

    assert count == 0


@pytest.mark.asyncio
async def test_click_with_retry_uses_mutation_settle_after_js_fallback() -> None:
    class _ClickPage:
        def __init__(self) -> None:
            self.load_state_calls: list[str] = []
            self.wait_timeout_calls: list[int] = []
            self.mutation_settle_calls = 0

        def locator(self, selector: str):
            del selector
            return _OverlayCookieLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> Any:
            del arg
            if "MutationObserver" in script:
                self.mutation_settle_calls += 1
                return {"observed": True}
            return None

        async def wait_for_load_state(
            self,
            state: str,
            timeout: int | None = None,
        ) -> None:
            del timeout
            self.load_state_calls.append(state)

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            self.wait_timeout_calls.append(timeout_ms)

    class _ClickLocator:
        async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
            del timeout

        async def evaluate(self, script: str) -> Any:
            if "scrollIntoView" in script:
                return None
            if "node.click()" in script:
                return None
            return 0

        async def click(self, timeout: int | None = None, force: bool = False) -> None:
            del timeout, force
            raise RuntimeError("intercepted")

    page = _ClickPage()
    locator = _ClickLocator()
    result = TraversalResult(requested_mode="load_more")

    clicked = await _click_with_retry(page, locator, result=result)

    assert clicked is True
    assert result.click_retries == 2
    assert page.mutation_settle_calls == 1
    assert page.wait_timeout_calls == []


@pytest.mark.asyncio
async def test_click_with_retry_stops_when_locator_no_longer_resolves() -> None:
    class _ClickPage:
        url = "https://example.com/listing"

        def locator(self, selector: str):
            del selector
            return _OverlayCookieLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> Any:
            del script, arg
            return None

        async def wait_for_load_state(
            self,
            state: str,
            timeout: int | None = None,
        ) -> None:
            del state, timeout

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            del timeout_ms

    class _StaleLocator:
        def __init__(self) -> None:
            self.detached = False
            self.click_calls = 0

        async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
            del timeout

        async def evaluate(self, script: str) -> Any:
            del script
            self.detached = True
            raise RuntimeError("detached")

        async def count(self) -> int:
            return 0 if self.detached else 1

        async def click(self, timeout: int | None = None, force: bool = False) -> None:
            del timeout, force
            self.click_calls += 1
            raise AssertionError("click should not run once locator is stale")

    page = _ClickPage()
    locator = _StaleLocator()
    result = TraversalResult(requested_mode="load_more")

    clicked = await _click_with_retry(page, locator, result=result)

    assert clicked is False
    assert locator.click_calls == 0
    assert result.click_retries == 0


@pytest.mark.asyncio
async def test_click_with_retry_tolerates_transient_locator_resolution_loss() -> None:
    class _ClickPage:
        url = "https://example.com/listing"

        def locator(self, selector: str):
            del selector
            return _OverlayCookieLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> Any:
            del script, arg
            return None

        async def wait_for_load_state(
            self,
            state: str,
            timeout: int | None = None,
        ) -> None:
            del state, timeout

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            del timeout_ms

    class _TransientLocator:
        def __init__(self) -> None:
            self.count_calls = 0
            self.click_calls = 0

        async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
            del timeout

        async def evaluate(self, script: str) -> Any:
            del script
            raise RuntimeError("transient evaluate failure")

        async def count(self) -> int:
            self.count_calls += 1
            return 0 if self.count_calls == 1 else 1

        async def click(self, timeout: int | None = None, force: bool = False) -> None:
            del timeout, force
            self.click_calls += 1
            return None

    page = _ClickPage()
    locator = _TransientLocator()
    result = TraversalResult(requested_mode="load_more")

    clicked = await _click_with_retry(page, locator, result=result)

    assert clicked is True
    assert locator.click_calls == 1


@pytest.mark.asyncio
async def test_locator_still_resolves_returns_false_after_probe_errors() -> None:
    class _ProbeErrorLocator:
        async def count(self) -> int:
            raise traversal_module._PlaywrightError("transient probe failure")

    assert await _locator_still_resolves(_ProbeErrorLocator()) is False


@pytest.mark.asyncio
async def test_click_with_retry_tolerates_locator_probe_errors() -> None:
    class _ClickPage:
        url = "https://example.com/listing"

        def locator(self, selector: str):
            del selector
            return _OverlayCookieLocator()

        async def evaluate(self, script: str, arg: Any | None = None) -> Any:
            del script, arg
            return None

        async def wait_for_load_state(
            self,
            state: str,
            timeout: int | None = None,
        ) -> None:
            del state, timeout

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            del timeout_ms

    class _ProbeErrorLocator:
        def __init__(self) -> None:
            self.click_calls = 0

        async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
            del timeout

        async def evaluate(self, script: str) -> Any:
            del script
            return None

        async def count(self) -> int:
            raise traversal_module._PlaywrightError("transient probe failure")

        async def click(self, timeout: int | None = None, force: bool = False) -> None:
            del timeout, force
            self.click_calls += 1
            return None

    page = _ClickPage()
    locator = _ProbeErrorLocator()
    result = TraversalResult(requested_mode="load_more")

    clicked = await _click_with_retry(page, locator, result=result)

    assert clicked is True
    assert locator.click_calls == 1
