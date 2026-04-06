from __future__ import annotations

from app.api.records import _render_markdown_block


def test_render_markdown_block_preserves_single_blank_lines() -> None:
    value = " First paragraph \n\n\n * Bullet one \n2. Bullet two\n\n Second paragraph "

    rendered = _render_markdown_block(value)

    assert rendered == "First paragraph\n\n- Bullet one\n- Bullet two\n\nSecond paragraph"
