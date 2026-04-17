from __future__ import annotations

from dataclasses import dataclass, field

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import BrowserResult


@dataclass(slots=True)
class BlockedRecoveryOutcome:
    browser_result: BrowserResult | None = None
    adapter_records: list[dict] = field(default_factory=list)
    adapter_name: str = ""
    adapter_source_type: str = ""


async def recover_blocked_listing_acquisition(
    *,
    url: str,
    proxy: str | None,
    surface: str | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    sleep_ms: int,
    runtime_options: object,
    requested_fields: list[str] | None,
    requested_field_selectors: dict[str, list[dict]] | None,
    checkpoint,
    run_id: int,
    session_context,
    browser_first: bool,
    analysis: dict[str, object],
    try_browser,
) -> BlockedRecoveryOutcome | None:
    from app.services.adapters.registry import try_blocked_adapter_recovery

    blocked = analysis.get("blocked")
    if blocked is None or not getattr(blocked, "is_blocked", False):
        return None
    if surface not in {"ecommerce_listing", "job_listing"}:
        return None
    if browser_first:
        return None

    browser_result = await try_browser(
        url,
        proxy,
        surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        prefer_stealth=prefer_stealth,
        sleep_ms=sleep_ms,
        runtime_options=runtime_options,
        requested_fields=requested_fields,
        requested_field_selectors=requested_field_selectors,
        checkpoint=checkpoint,
        run_id=run_id,
        session_context=session_context,
    )
    if browser_result is None:
        if proxy is not None:
            return None
        recovered = await try_blocked_adapter_recovery(
            url,
            surface or "",
            proxy_list=None,
        )
        if recovered is None or not recovered.records:
            return None
        return BlockedRecoveryOutcome(
            adapter_records=list(recovered.records),
            adapter_name=recovered.adapter_name or "",
            adapter_source_type=recovered.source_type or "",
        )

    if browser_result.html is None or browser_result.html.strip() == "":
        return None

    browser_blocked = detect_blocked_page(browser_result.html)
    if browser_blocked.is_blocked:
        return None

    return BlockedRecoveryOutcome(browser_result=browser_result)
