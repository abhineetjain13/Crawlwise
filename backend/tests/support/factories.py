from __future__ import annotations

from collections.abc import Mapping

from app.models.crawl import CrawlRecord, CrawlRun


def make_crawl_run(
    *,
    user_id: int,
    url: str = "https://example.com",
    surface: str = "ecommerce_detail",
    run_type: str = "crawl",
    status: str = "completed",
    settings: Mapping[str, object] | None = None,
    requested_fields: list[str] | None = None,
    result_summary: Mapping[str, object] | None = None,
) -> CrawlRun:
    return CrawlRun(
        user_id=user_id,
        run_type=run_type,
        url=url,
        surface=surface,
        status=status,
        settings=dict(settings or {}),
        requested_fields=list(requested_fields or []),
        result_summary=dict(result_summary or {}),
    )


def make_crawl_record(
    *,
    run_id: int,
    source_url: str = "https://example.com/item",
    data: Mapping[str, object] | None = None,
    raw_data: Mapping[str, object] | None = None,
    discovered_data: Mapping[str, object] | None = None,
    source_trace: Mapping[str, object] | None = None,
    raw_html_path: str | None = None,
    **overrides,
) -> CrawlRecord:
    return CrawlRecord(
        run_id=run_id,
        source_url=source_url,
        data=dict(data or {}),
        raw_data=dict(raw_data or {}),
        discovered_data=dict(discovered_data or {}),
        source_trace=dict(source_trace or {}),
        raw_html_path=raw_html_path,
        **overrides,
    )
