from __future__ import annotations

from app.services.crawl_fetch_runtime import (
    PageFetchResult,
    browser_runtime_snapshot,
    close_shared_http_client,
    fetch_page,
    is_blocked_html,
    shutdown_browser_runtime,
)
from app.services.detail_extractor import extract_detail_records
from app.services.listing_extractor import extract_listing_records


def extract_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> list[dict]:
    if "listing" in surface:
        if adapter_records:
            return [
                {
                    **{
                        key: value
                        for key, value in dict(record).items()
                        if value not in (None, "", [], {})
                    },
                    "_source": str(record.get("_source") or "adapter"),
                }
                for record in list(adapter_records or [])[:max_records]
                if isinstance(record, dict)
            ]
        return extract_listing_records(
            html,
            page_url,
            surface,
            max_records=max_records,
            selector_rules=selector_rules,
        )
    return extract_detail_records(
        html,
        page_url,
        surface,
        requested_fields=requested_fields,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )[:max_records]
