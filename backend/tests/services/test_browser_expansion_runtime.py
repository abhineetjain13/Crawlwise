from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import crawl_fetch_runtime


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
    def __init__(self, page: "_FakeExpansionPage") -> None:
        self._page = page

    async def element_handles(self) -> list[_FakeHandle]:
        return [
            _FakeHandle(row["label"], self._page, actionable=bool(row.get("actionable", True)))
            for row in self._page.labels
        ]


class _FakeExpansionPage:
    def __init__(self, labels: list[str] | list[dict[str, object]]) -> None:
        self.labels = labels
        self.expanded = False
        self.url = "https://example.com/products/widget"

    def on(self, event_name: str, callback: Any) -> None:
        del event_name, callback

    async def goto(
        self,
        url: str,
        wait_until: str | None = None,
        timeout: int | None = None,
    ) -> Any:
        del wait_until, timeout
        self.url = url
        return SimpleNamespace(status=200, headers={"content-type": "text/html"})

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        del timeout_ms

    async def wait_for_load_state(
        self,
        state: str,
        timeout: int | None = None,
    ) -> None:
        del state, timeout

    def locator(self, selector: str) -> _FakeLocator:
        del selector
        return _FakeLocator(self)

    async def content(self) -> str:
        if self.expanded:
            return """
            <html><body>
              <details open><summary>Specifications</summary>
                <div class="product-features">Rubber outsole, reinforced toe cap.</div>
              </details>
            </body></html>
            """
        return "<html><body><details><summary>Specifications</summary></details></body></html>"


class _FakeRuntime:
    def __init__(self, page: _FakeExpansionPage) -> None:
        self._page = page

    @asynccontextmanager
    async def page(self):
        yield self._page


@pytest.mark.asyncio
async def test_browser_fetch_expands_detail_accordions_before_collecting_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakeExpansionPage(
        [{"label": "product specifications"}, {"label": "share"}]
    )

    async def _fake_runtime():
        return _FakeRuntime(page)

    monkeypatch.setattr(crawl_fetch_runtime, "_get_browser_runtime", _fake_runtime)

    result = await crawl_fetch_runtime._browser_fetch(
        "https://example.com/products/widget",
        5,
        surface="ecommerce_detail",
    )

    assert "Rubber outsole" in result.html
    assert result.browser_diagnostics["detail_expansion"]["clicked_count"] == 1
    assert result.browser_diagnostics["detail_expansion"]["expanded_elements"] == [
        "product specifications"
    ]


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_respects_small_interaction_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_limit = crawl_fetch_runtime.crawler_runtime_settings.detail_expand_max_interactions
    crawl_fetch_runtime.crawler_runtime_settings.detail_expand_max_interactions = 1
    try:
        page = _FakeExpansionPage(
            [{"label": "product details"}, {"label": "product dimensions"}]
        )
        diagnostics = await crawl_fetch_runtime.expand_all_interactive_elements(
            page,
            surface="ecommerce_detail",
        )

        assert diagnostics["limit"] == 1
        assert diagnostics["clicked_count"] == 1
        assert diagnostics["expanded_elements"] == ["product details"]
    finally:
        crawl_fetch_runtime.crawler_runtime_settings.detail_expand_max_interactions = original_limit


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_skips_non_actionable_candidates() -> None:
    page = _FakeExpansionPage(
        [
            {"label": "product details", "actionable": False},
            {"label": "product specifications", "actionable": True},
        ]
    )

    diagnostics = await crawl_fetch_runtime.expand_all_interactive_elements(
        page,
        surface="ecommerce_detail",
    )

    assert diagnostics["clicked_count"] == 1
    assert diagnostics["expanded_elements"] == ["product specifications"]
