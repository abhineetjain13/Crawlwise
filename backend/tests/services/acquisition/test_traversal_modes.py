from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.acquisition import policy
from app.services.acquisition.traversal import (
    AdvanceResult,
    PaginationTraversalRequest,
    TraversalConfig,
    TraversalRequest,
    TraversalRuntime,
    apply_traversal_mode,
    collect_paginated_html,
    scroll_to_bottom,
)
from app.services.crawl_utils import resolve_traversal_mode


def _plan(surface: str):
    return policy.plan_acquisition(
        SimpleNamespace(url="https://example.com", surface=surface)
    )


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"advanced_enabled": True, "traversal_mode": "auto"}, "auto"),
        ({"advanced_enabled": True, "traversal_mode": "view_all"}, "load_more"),
        ({"advanced_enabled": False, "traversal_mode": "paginate"}, None),
        ({"advanced_enabled": True, "traversal_mode": "paginate"}, "paginate"),
        ({"advanced_enabled": True, "traversal_mode": "scroll"}, "scroll"),
    ],
)
def test_resolve_traversal_mode_contract_matrix(settings: dict, expected: str | None) -> None:
    assert resolve_traversal_mode(settings) == expected


def test_resolve_traversal_mode_unrecognized_mode_is_ignored_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.crawl_utils")
    resolved = resolve_traversal_mode(
        {"advanced_enabled": True, "traversal_mode": "mystery_mode"}
    )
    assert resolved is None
    assert "Unrecognized traversal_mode" in caplog.text


def _make_product_card(index: int) -> str:
    return (
        f'<article class="product-card" data-product-id="{index}">'
        f'<a href="/products/{index}">Product {index}</a>'
        "</article>"
    )


class _FakeButtonOnlyNextLocator:
    def __init__(self, page: _ButtonOnlyPaginationPage) -> None:
        self._page = page

    @property
    def first(self) -> _FakeButtonOnlyNextLocator:
        return self

    async def count(self) -> int:
        return 1 if self._page.has_next else 0

    async def is_visible(self) -> bool:
        return self._page.has_next

    async def click(self, timeout: int | None = None) -> None:
        _ = timeout
        self._page.advance()


class _MissingLocator:
    @property
    def first(self) -> _MissingLocator:
        return self

    async def count(self) -> int:
        return 0

    async def is_visible(self) -> bool:
        return False


class _ButtonOnlyPaginationPage:
    def __init__(self) -> None:
        self.url = "https://example.com/products"
        self.page_index = 0
        self.wait_for_load_state_calls: list[tuple[str, int]] = []
        self.pages = [
            [_make_product_card(1), _make_product_card(2)],
            [_make_product_card(3), _make_product_card(4)],
            [_make_product_card(5), _make_product_card(6)],
        ]

    @property
    def has_next(self) -> bool:
        return self.page_index < len(self.pages) - 1

    def advance(self) -> None:
        if self.has_next:
            self.page_index += 1

    def locator(self, selector: str):
        if selector == "button.next":
            return _FakeButtonOnlyNextLocator(self)
        return _MissingLocator()

    async def content(self) -> str:
        cards = "".join(self.pages[self.page_index])
        return (
            f"<html><body><section data-page='{self.page_index + 1}'>"
            f"{cards}</section></body></html>"
        )

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        raise AssertionError(
            f"Button-only pagination should not call goto (got {url}, {wait_until}, {timeout})"
        )

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.wait_for_load_state_calls.append((state, timeout))


class _FragmentFriendlyPaginationPage(_ButtonOnlyPaginationPage):
    async def content(self) -> str:
        cards = "".join(self.pages[self.page_index])
        noise = "MARKETING_BLOB " * 5000
        return (
            f"<html><body><header>{noise}</header>"
            f"<section data-page='{self.page_index + 1}'>{cards}</section>"
            f"<footer>{noise}</footer></body></html>"
        )

    async def evaluate(self, script: str, arg=None):
        if "const seen = new Set();" in script:
            cards = []
            for card_html in self.pages[self.page_index]:
                href = card_html.split('href="', 1)[1].split('"', 1)[0]
                cards.append({"html": card_html, "identity": href})
            return {
                "cards": cards,
                "container_signature": f"page-{self.page_index + 1}",
            }
        if "knownSigs" in script:
            return []
        return ""


class _VirtualizedScrollPage:
    def __init__(self, *, steps: int, cards_per_step: int) -> None:
        self.url = "https://example.com/virtualized"
        self._steps = steps
        self._cards_per_step = cards_per_step
        self._visible_step = -1
        self._scroll_calls = 0
        self.wait_for_load_state_calls: list[tuple[str, int]] = []

    def _cards_for_visible_step(self) -> list[dict[str, str]]:
        if self._visible_step < 0:
            return []
        start = self._visible_step * self._cards_per_step
        return [
            {
                "html": _make_product_card(start + offset),
                "identity": f"/products/{start + offset}",
            }
            for offset in range(self._cards_per_step)
        ]

    def snapshot_metrics(self) -> dict[str, object]:
        cards = self._cards_for_visible_step()
        identities = [card["identity"] for card in cards]
        count = len(cards)
        return {
            "link_count": count,
            "cardish_count": count,
            "text_length": count * 40,
            "html_length": count * 120,
            "identity_count": count,
            "identities": identities,
            "dom_signature": f"visible-step-{self._visible_step}",
        }

    async def evaluate(self, script: str, arg=None):
        if "const seen = new Set();" in script:
            return {
                "cards": self._cards_for_visible_step(),
                "container_signature": f"visible-step-{self._visible_step}",
            }
        if "knownSigs" in script:
            return []
        if "return Math.max(root.scrollHeight" in script:
            return 1000 + max(self._visible_step, 0) * 100
        if "forceProbe" in script:
            self._scroll_calls += 1
            if self._visible_step < self._steps - 1:
                self._visible_step += 1
            return {"target": "window"}
        raise AssertionError(f"Unexpected evaluate script: {script[:80]!r}")

    async def content(self) -> str:
        return "<html><body>unused fallback</body></html>"

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.wait_for_load_state_calls.append((state, timeout))


class _ConnectionLostScrollPage:
    def __init__(self) -> None:
        self.url = "https://example.com/disconnected"
        self.wait_for_load_state_calls: list[tuple[str, int]] = []

    async def evaluate(self, script: str, arg=None):
        if "return Math.max(root.scrollHeight" in script:
            return 1000
        if "forceProbe" in script:
            return {"target": "window"}
        raise AssertionError(f"Unexpected evaluate script: {script[:80]!r}")

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.wait_for_load_state_calls.append((state, timeout))
        raise ConnectionResetError("network connection lost")


@pytest.mark.asyncio
async def test_paginate_mode_collects_three_button_only_pages_without_duplicates():
    page = _ButtonOnlyPaginationPage()

    async def _page_content_with_retry(current_page, checkpoint=None) -> str:
        _ = checkpoint
        return await current_page.content()

    async def _advance_button_only_page(current_page, *, checkpoint=None) -> AdvanceResult:
        _ = checkpoint
        button = current_page.locator("button.next").first
        if not await button.count():
            return AdvanceResult()
        await button.click()
        return AdvanceResult(url=current_page.url, already_navigated=True)

    result = await collect_paginated_html(
        PaginationTraversalRequest(
            page=page,
            plan=_plan("ecommerce_listing"),
            surface="ecommerce_listing",
            max_pages=5,
            request_delay_ms=0,
            runtime=TraversalRuntime(
                page_content_with_retry=AsyncMock(side_effect=_page_content_with_retry),
                wait_for_surface_readiness=AsyncMock(return_value={"ready": True}),
                wait_for_listing_readiness=AsyncMock(return_value={"ready": True}),
                peek_next_page_signal=AsyncMock(return_value=None),
                has_load_more_control=AsyncMock(return_value=False),
                dismiss_cookie_consent=AsyncMock(),
                pause_after_navigation=AsyncMock(),
                expand_all_interactive_elements=AsyncMock(return_value={}),
                flatten_shadow_dom=AsyncMock(),
                cooperative_sleep_ms=AsyncMock(),
                snapshot_listing_page_metrics=AsyncMock(return_value={}),
                advance_next_page_fn=_advance_button_only_page,
            ),
        )
    )

    assert result.summary["pages_collected"] == 3
    assert "goto_next_page" in {step["action"] for step in result.summary["steps"]}
    assert result.summary["stop_reason"] == "no_next_page"
    assert result.html is not None
    assert result.html.count("PAGE BREAK:") == 3
    for product_id in range(1, 7):
        assert result.html.count(f'href="/products/{product_id}"') == 1


@pytest.mark.asyncio
async def test_paginate_mode_uses_targeted_fragments_for_listing_pages():
    page = _FragmentFriendlyPaginationPage()

    async def _page_content_with_retry(current_page, checkpoint=None) -> str:
        _ = checkpoint
        return await current_page.content()

    async def _advance_button_only_page(current_page, *, checkpoint=None) -> AdvanceResult:
        _ = checkpoint
        button = current_page.locator("button.next").first
        if not await button.count():
            return AdvanceResult()
        await button.click()
        return AdvanceResult(url=current_page.url, already_navigated=True)

    result = await collect_paginated_html(
        PaginationTraversalRequest(
            page=page,
            plan=_plan("ecommerce_listing"),
            surface="ecommerce_listing",
            max_pages=2,
            request_delay_ms=0,
            runtime=TraversalRuntime(
                page_content_with_retry=AsyncMock(side_effect=_page_content_with_retry),
                wait_for_surface_readiness=AsyncMock(return_value={"ready": True}),
                wait_for_listing_readiness=AsyncMock(return_value={"ready": True}),
                peek_next_page_signal=AsyncMock(return_value=None),
                has_load_more_control=AsyncMock(return_value=False),
                dismiss_cookie_consent=AsyncMock(),
                pause_after_navigation=AsyncMock(),
                expand_all_interactive_elements=AsyncMock(return_value={}),
                flatten_shadow_dom=AsyncMock(),
                cooperative_sleep_ms=AsyncMock(),
                snapshot_listing_page_metrics=AsyncMock(return_value={}),
                advance_next_page_fn=_advance_button_only_page,
            ),
        )
    )

    assert result.html is not None
    assert "MARKETING_BLOB" not in result.html
    assert result.summary["pages_collected"] == 2
    for product_id in range(1, 5):
        assert result.html.count(f'href="/products/{product_id}"') == 1


@pytest.mark.asyncio
async def test_collect_paginated_html_emits_progress_logs():
    page = _ButtonOnlyPaginationPage()
    progress_logger = AsyncMock()

    async def _page_content_with_retry(current_page, checkpoint=None) -> str:
        _ = checkpoint
        return await current_page.content()

    async def _advance_button_only_page(current_page, *, checkpoint=None) -> AdvanceResult:
        _ = checkpoint
        button = current_page.locator("button.next").first
        if not await button.count():
            return AdvanceResult()
        await button.click()
        return AdvanceResult(url=current_page.url, already_navigated=True)

    await collect_paginated_html(
        PaginationTraversalRequest(
            page=page,
            plan=_plan("ecommerce_listing"),
            surface="ecommerce_listing",
            max_pages=2,
            request_delay_ms=0,
            runtime=TraversalRuntime(
                page_content_with_retry=AsyncMock(side_effect=_page_content_with_retry),
                wait_for_surface_readiness=AsyncMock(return_value={"ready": True}),
                wait_for_listing_readiness=AsyncMock(return_value={"ready": True}),
                peek_next_page_signal=AsyncMock(return_value=None),
                has_load_more_control=AsyncMock(return_value=False),
                dismiss_cookie_consent=AsyncMock(),
                pause_after_navigation=AsyncMock(),
                expand_all_interactive_elements=AsyncMock(return_value={}),
                flatten_shadow_dom=AsyncMock(),
                cooperative_sleep_ms=AsyncMock(),
                snapshot_listing_page_metrics=AsyncMock(return_value={}),
                advance_next_page_fn=_advance_button_only_page,
                progress_logger=progress_logger,
            ),
        )
    )

    messages = [call.args[0] for call in progress_logger.await_args_list]
    assert any(message.startswith("paginate:capture page=1") for message in messages)
    assert any(message.startswith("paginate:advance_in_place page=2") for message in messages)


@pytest.mark.asyncio
async def test_collect_paginated_html_requires_pagination_callback():
    page = _ButtonOnlyPaginationPage()

    async def _page_content_with_retry(current_page, checkpoint=None) -> str:
        _ = checkpoint
        return await current_page.content()

    with pytest.raises(ValueError, match="no pagination callback provided"):
        await collect_paginated_html(
            PaginationTraversalRequest(
                page=page,
                plan=_plan("ecommerce_listing"),
                surface="ecommerce_listing",
                max_pages=2,
                request_delay_ms=0,
                runtime=TraversalRuntime(
                    page_content_with_retry=AsyncMock(side_effect=_page_content_with_retry),
                    wait_for_surface_readiness=AsyncMock(return_value={"ready": True}),
                    wait_for_listing_readiness=AsyncMock(return_value={"ready": True}),
                    peek_next_page_signal=AsyncMock(return_value=None),
                    has_load_more_control=AsyncMock(return_value=False),
                    dismiss_cookie_consent=AsyncMock(),
                    pause_after_navigation=AsyncMock(),
                    expand_all_interactive_elements=AsyncMock(return_value={}),
                    flatten_shadow_dom=AsyncMock(),
                    cooperative_sleep_ms=AsyncMock(),
                    snapshot_listing_page_metrics=AsyncMock(return_value={}),
                ),
            )
        )


@pytest.mark.asyncio
async def test_scroll_mode_preserves_all_cards_from_virtualized_infinite_scroll():
    page = _VirtualizedScrollPage(steps=5, cards_per_step=10)
    metrics = AsyncMock(side_effect=lambda current_page: current_page.snapshot_metrics())

    result = await apply_traversal_mode(
        TraversalRequest(
            page=page,
            plan=_plan("ecommerce_listing"),
            surface="ecommerce_listing",
            traversal_mode="scroll",
            max_scrolls=5,
            max_pages=1,
            request_delay_ms=0,
            runtime=TraversalRuntime(
                page_content_with_retry=AsyncMock(return_value=""),
                wait_for_surface_readiness=AsyncMock(return_value={"ready": True}),
                wait_for_listing_readiness=AsyncMock(return_value={"ready": True}),
                peek_next_page_signal=AsyncMock(return_value=None),
                click_and_observe_next_page=AsyncMock(return_value=""),
                has_load_more_control=AsyncMock(return_value=False),
                dismiss_cookie_consent=AsyncMock(),
                pause_after_navigation=AsyncMock(),
                expand_all_interactive_elements=AsyncMock(return_value={}),
                flatten_shadow_dom=AsyncMock(),
                cooperative_sleep_ms=AsyncMock(),
                snapshot_listing_page_metrics=metrics,
            ),
        )
    )

    assert result.summary["mode"] == "scroll"
    assert result.summary["attempt_count"] == 5
    assert result.summary["pages_collected"] == 5
    assert result.summary["captured_fragment_bytes"] < 1_000_000
    assert result.html is not None
    assert len(result.html.encode("utf-8")) < 1_000_000
    for product_id in range(50):
        assert result.html.count(f'href="/products/{product_id}"') == 1


@pytest.mark.asyncio
async def test_scroll_to_bottom_reports_connection_loss_instead_of_masking_it():
    page = _ConnectionLostScrollPage()

    async def _sleep(*_args, **_kwargs) -> None:
        return None

    async def _metrics(_page) -> dict[str, object]:
        return {
            "link_count": 0,
            "cardish_count": 0,
            "text_length": 0,
            "html_length": 0,
            "identity_count": 0,
            "identities": [],
            "dom_signature": "stable",
        }

    result = await scroll_to_bottom(
        page,
        max_scrolls=1,
        config=TraversalConfig(scroll_wait_min_ms=1234),
        request_delay_ms=0,
        cooperative_sleep_ms=_sleep,
        snapshot_listing_page_metrics=_metrics,
    )

    assert result["mode"] == "scroll"
    assert result["attempted"] is True
    assert result["attempt_count"] == 1
    assert result["stop_reason"] == "network_wait_connection_lost"
    assert result["network_wait_error"]["type"] == "ConnectionResetError"
    assert result["steps"][0]["network_wait_status"] == "connection_lost"
    assert page.wait_for_load_state_calls == [("networkidle", 1234)]

