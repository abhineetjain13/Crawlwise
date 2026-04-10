from __future__ import annotations

import pytest

from app.models.crawl import CrawlRun
from app.models.crawl_settings import CrawlRunSettings
from app.services._batch_runtime import _resolve_run_urls


def _make_run(*, run_type: str, url: str = "", settings: dict | None = None) -> CrawlRun:
    return CrawlRun(
        user_id=1,
        run_type=run_type,
        url=url,
        status="pending",
        surface="ecommerce_detail",
        settings=settings or {},
    )


def test_resolve_run_urls_prefers_batch_settings_urls() -> None:
    run = _make_run(
        run_type="batch",
        url="https://example.com/fallback",
        settings={"urls": [" https://example.com/a ", "https://example.com/b"]},
    )

    assert _resolve_run_urls(run, CrawlRunSettings.from_value(run.settings)) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_resolve_run_urls_uses_csv_content_for_csv_runs() -> None:
    run = _make_run(
        run_type="csv",
        settings={"csv_content": "https://example.com/a\nhttps://example.com/b"},
    )

    assert _resolve_run_urls(run, CrawlRunSettings.from_value(run.settings)) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_resolve_run_urls_falls_back_to_direct_url_for_empty_batch_urls() -> None:
    run = _make_run(
        run_type="batch",
        url="https://example.com/fallback",
        settings={"urls": []},
    )

    assert _resolve_run_urls(run, CrawlRunSettings.from_value(run.settings)) == [
        "https://example.com/fallback",
    ]


def test_resolve_run_urls_raises_without_any_url_source() -> None:
    run = _make_run(run_type="crawl")

    with pytest.raises(ValueError, match="No URL provided"):
        _resolve_run_urls(run, CrawlRunSettings.from_value(run.settings))
