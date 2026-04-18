from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.pipeline.rendering import _render_fallback_node_markdown


def test_render_fallback_node_markdown_preserves_raw_href_query_string() -> None:
    soup = BeautifulSoup(
        '<div><a href="/products/widget?variant=1%2F2&amp;utm_source=test">Widget</a></div>',
        "html.parser",
    )

    rendered = _render_fallback_node_markdown(
        soup.div,
        page_url="https://example.com/collection",
    )

    assert (
        rendered
        == "[Widget](https://example.com/products/widget?variant=1%2F2&utm_source=test)"
    )
