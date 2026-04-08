from __future__ import annotations

import logging

import pytest

from app.services.crawl_utils import resolve_traversal_mode


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


def test_resolve_traversal_mode_unrecognized_mode_falls_back_to_auto_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        resolved = resolve_traversal_mode(
            {"advanced_enabled": True, "traversal_mode": "mystery_mode"}
        )
    assert resolved == "auto"
    assert "Unrecognized traversal_mode" in caplog.text

