"""Tests for targeted fragment capture in scroll/load-more traversal.

Verifies that _capture_fragment extracts card-level HTML instead of full page
content, deduplicates by card identity, and falls back to container diff when
card selectors match nothing.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.services.acquisition.traversal import (
    TraversalRuntime,
    apply_traversal_mode,
)

# ---------------------------------------------------------------------------
# Fake Playwright page that simulates page.evaluate() with card selectors.
# ---------------------------------------------------------------------------

class FakeFragmentPage:
    """Simulates a Playwright page for fragment-capture tests.

    - ``cards_per_step``: list of card sets returned per evaluate call to
      _JS_EXTRACT_CARDS.  Each entry is a list of {html, identity} dicts.
    - ``boilerplate_kb``: size in KB of nav/footer/boilerplate HTML that
      would be returned by page.content() — used to prove we never
      capture it.
    """

    def __init__(
        self,
        *,
        cards_per_step: list[list[dict]] | None = None,
        container_diff_items: list[list[dict]] | None = None,
        boilerplate_kb: int = 500,
    ):
        self.url = "https://example.com/products"
        self._cards_per_step = list(cards_per_step or [])
        self._container_diff_items = list(container_diff_items or [])
        self._evaluate_call_index = 0
        self._boilerplate = "X" * (boilerplate_kb * 1024)

    async def evaluate(self, script: str, arg=None):
        """Route JS snippets to the appropriate fake data."""
        if "container_signature" in script:
            # _JS_EXTRACT_CARDS
            if self._cards_per_step:
                cards = self._cards_per_step.pop(0)
            else:
                cards = []
            return {"cards": cards, "container_signature": "MAIN:20"}
        if "knownSigs" in script:
            # _JS_CONTAINER_DIFF
            if self._container_diff_items:
                return self._container_diff_items.pop(0)
            return []
        # scroll-related evaluates — return harmless defaults
        return {"target": "window", "scrolled": True}

    async def content(self):
        return f"<html><body>{self._boilerplate}</body></html>"

    async def wait_for_load_state(self, *a, **kw):
        pass

    def locator(self, _sel: str):
        return _FakeLocator()


class _FakeLocator:
    @property
    def first(self):
        return self

    async def count(self):
        return 0

    async def is_visible(self):
        return False


def _make_card(index: int, *, identity: str | None = None) -> dict:
    """Build a fake card dict as _JS_EXTRACT_CARDS would return."""
    href = identity or f"/product/{index}"
    return {
        "html": f'<div class="product-card"><a href="{href}">Product {index}</a><span class="price">$10</span></div>',
        "identity": href,
    }


async def _run_fragment_capture_case(
    page: FakeFragmentPage,
    *,
    traversal_attr: str,
    traversal_mode: str,
    traversal_count: int,
    capture_calls: int,
    page_content: str,
    traversal_result: dict,
):
    import app.services.acquisition.traversal as traversal_mod

    original_traversal = getattr(traversal_mod, traversal_attr)

    async def fake_traversal(
        page, max_scrolls, *, config=None, request_delay_ms=0,
        cooperative_sleep_ms=None, snapshot_listing_page_metrics=None,
        capture_dom_fragment=None, checkpoint=None,
    ):
        for i in range(capture_calls):
            if capture_dom_fragment:
                await capture_dom_fragment(page, i + 1)
        return traversal_result

    setattr(traversal_mod, traversal_attr, fake_traversal)
    try:
        return await apply_traversal_mode(
            page,
            "ecommerce_listing",
            traversal_mode,
            traversal_count,
            runtime=TraversalRuntime(
                page_content_with_retry=AsyncMock(return_value=page_content),
                wait_for_surface_readiness=AsyncMock(),
                wait_for_listing_readiness=AsyncMock(),
                peek_next_page_signal=AsyncMock(return_value=None),
                click_and_observe_next_page=AsyncMock(return_value=""),
                has_load_more_control=AsyncMock(return_value=False),
                dismiss_cookie_consent=AsyncMock(),
                pause_after_navigation=AsyncMock(),
                expand_all_interactive_elements=AsyncMock(return_value={}),
                flatten_shadow_dom=AsyncMock(),
                cooperative_sleep_ms=AsyncMock(),
                snapshot_listing_page_metrics=AsyncMock(return_value={}),
            ),
            max_pages=1,
            request_delay_ms=0,
        )
    finally:
        setattr(traversal_mod, traversal_attr, original_traversal)


# ---------------------------------------------------------------------------
# Acceptance test: 500KB boilerplate × 20 scrolls < 1MB, all cards present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_targeted_capture_stays_under_1mb_with_20_scroll_steps():
    """A page with 500KB boilerplate scrolled 20 times must capture < 1MB
    of fragment bytes, and all unique cards must be present in the output."""
    unique_cards_per_step = 5
    total_steps = 20
    # Build card sets: each step returns 5 new unique cards
    cards_per_step = []
    for step in range(total_steps + 2):  # +2 for initial + final captures
        base = step * unique_cards_per_step
        cards_per_step.append([_make_card(base + i) for i in range(unique_cards_per_step)])

    page = FakeFragmentPage(cards_per_step=cards_per_step, boilerplate_kb=500)
    result = await _run_fragment_capture_case(
        page,
        traversal_attr="scroll_to_bottom",
        traversal_mode="scroll",
        traversal_count=total_steps,
        capture_calls=total_steps,
        page_content=page._boilerplate,
        traversal_result={
            "mode": "scroll",
            "attempted": True,
            "attempt_count": total_steps,
            "steps": [],
            "stop_reason": "max_scrolls_reached",
        },
    )

    assert result.html is not None
    html_bytes = len(result.html.encode("utf-8", errors="ignore"))

    # Must stay under 1MB despite 500KB boilerplate being available.
    assert html_bytes < 1_000_000, f"Fragment bytes {html_bytes} exceeded 1MB"

    # All unique cards must be present (initial + 20 steps + final = 22 batches × 5).
    # We check for a representative sample of product identities.
    for product_id in [0, 10, 50, 99, 109]:
        assert f"/product/{product_id}" in result.html, (
            f"Product {product_id} missing from output"
        )

    assert result.summary["captured_fragment_bytes"] < 1_000_000


@pytest.mark.asyncio
async def test_card_identity_dedup_prevents_virtualized_duplicates():
    """When a virtualized grid returns overlapping cards across steps,
    duplicates should be suppressed by identity (href)."""
    # Step 1: cards 0-4.  Step 2: cards 3-7 (overlap at 3,4).
    step1 = [_make_card(i) for i in range(5)]
    step2 = [_make_card(i) for i in range(3, 8)]
    step3 = [_make_card(i) for i in range(6, 11)]

    # initial + step1 + step2 + step3 + final = 5 evaluate calls
    page = FakeFragmentPage(cards_per_step=[step1, step1, step2, step3, step3])
    result = await _run_fragment_capture_case(
        page,
        traversal_attr="scroll_to_bottom",
        traversal_mode="scroll",
        traversal_count=3,
        capture_calls=3,
        page_content="<html></html>",
        traversal_result={
            "mode": "scroll",
            "attempted": True,
            "attempt_count": 3,
            "steps": [],
            "stop_reason": "max_scrolls_reached",
        },
    )

    assert result.html is not None
    # Cards 0-10 should each appear exactly once.
    for i in range(11):
        count = result.html.count(f'href="/product/{i}"')
        assert count == 1, f"Product {i} appeared {count} times (expected 1)"


@pytest.mark.asyncio
async def test_container_diff_fallback_when_no_card_selectors_match():
    """When CARD_SELECTORS match nothing, fall back to DOM diff of the
    listing container's new children."""
    # No cards from selector extraction — empty card lists.
    # Container diff returns new children on each step.
    diff_step1 = [
        {"html": '<div class="custom-item">Item A</div>', "sig": "div:Item A"},
        {"html": '<div class="custom-item">Item B</div>', "sig": "div:Item B"},
    ]
    diff_step2 = [
        {"html": '<div class="custom-item">Item C</div>', "sig": "div:Item C"},
    ]

    page = FakeFragmentPage(
        cards_per_step=[[], [], [], []],  # no card matches
        container_diff_items=[diff_step1, diff_step2, [], []],
        boilerplate_kb=500,
    )
    result = await _run_fragment_capture_case(
        page,
        traversal_attr="scroll_to_bottom",
        traversal_mode="scroll",
        traversal_count=2,
        capture_calls=2,
        page_content="<html></html>",
        traversal_result={
            "mode": "scroll",
            "attempted": True,
            "attempt_count": 2,
            "steps": [],
            "stop_reason": "max_scrolls_reached",
        },
    )

    assert result.html is not None
    assert "Item A" in result.html
    assert "Item B" in result.html
    assert "Item C" in result.html
    # Boilerplate should NOT appear — we never fell through to page.content().
    assert "XXXXX" not in result.html


@pytest.mark.asyncio
async def test_load_more_uses_targeted_capture():
    """Load-more mode should also use targeted card capture, not full page."""
    cards = [_make_card(i) for i in range(3)]

    # initial capture + per-step + final = 4 evaluate calls
    page = FakeFragmentPage(
        cards_per_step=[cards, cards[:1], [_make_card(3)], cards[:1]],
        boilerplate_kb=500,
    )
    result = await _run_fragment_capture_case(
        page,
        traversal_attr="click_load_more",
        traversal_mode="load_more",
        traversal_count=1,
        capture_calls=1,
        page_content="<html></html>",
        traversal_result={
            "mode": "load_more",
            "attempted": True,
            "attempt_count": 1,
            "steps": [],
            "stop_reason": "no_load_more_control",
        },
    )

    assert result.html is not None
    # Boilerplate never captured.
    html_bytes = len(result.html.encode("utf-8"))
    assert html_bytes < 10_000, f"Expected slim output, got {html_bytes} bytes"
    assert "Product 0" in result.html
