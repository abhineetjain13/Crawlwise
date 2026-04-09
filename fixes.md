These fixes directly address: Event Loop Starvation (Async blocking), Runtime Monkey-Patching (Circular imports), Data Loss (Pagination XHR bug), Argument Injection (Security), and Schema Pollution (Datalayer arbitration).
1. Fix Event Loop Starvation (CPU Blocking)
File: app/services/acquisition/acquirer.py
Fix: Wraps heavy BeautifulSoup parsing and text extraction in asyncio.to_thread to prevent the crawler from locking up the FastAPI server during concurrent runs.
Replace the _try_http function (around line 520) with this:
code
Python
def _analyze_html_sync(html: str) -> tuple[str, int, bool]:
    """Runs heavy CPU-bound HTML analysis synchronously."""
    from bs4 import BeautifulSoup
    from app.services.pipeline_config import JS_GATE_PHRASES
    
    soup = BeautifulSoup(html, "html.parser")
    visible_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    return visible_text, gate_phrases

async def _try_http(
    url: str,
    proxy: str | None,
    surface: str | None,
    *,
    run_id: int,
    traversal_mode: str | None,
    prefer_stealth: bool,
    sleep_ms: int,
    browser_first: bool,
    acquisition_profile: dict[str, object] | None,
    runtime_options,
    host_wait_seconds: float,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> HttpFetchResult | None:
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        curl_started_at = time.perf_counter()
        normalized = _normalize_fetch_result(await _fetch_with_content_type(url, proxy))
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning("curl_cffi acquisition failed for %s: %s", url, exc)
        return None
    html = normalized.text
    platform_family = _detect_platform_family(
        url, "" if normalized.content_type == "json" else html
    )
    diagnostics = _build_curl_diagnostics(
        normalized=normalized,
        blocked=None,
        visible_text="",
        content_len=None,
        gate_phrases=False,
        needs_browser=False,
        adapter_hint=None,
        platform_family=platform_family,
        proxy=proxy,
        prefer_stealth=prefer_stealth,
        traversal_mode=traversal_mode,
        host_wait_seconds=host_wait_seconds,
        memory_prefer_stealth=bool((acquisition_profile or {}).get("prefer_stealth")),
        anti_bot_enabled=runtime_options.anti_bot_enabled,
        memory_browser_first=browser_first,
    )
    diagnostics["curl_final_url"] = normalized.final_url or url
    diagnostics["timings_ms"] = _merge_timing_maps(
        diagnostics.get("timings_ms"), {"curl_fetch_ms": _elapsed_ms(curl_started_at)}
    )
    analysis: dict[str, object] = {
        "curl_diagnostics": diagnostics,
        "curl_result": None,
        "extractability": {
            "has_extractable_data": False,
            "reason": "non_html_response",
        },
        "blocked": None,
        "invalid_surface_page": False,
    }
    if normalized.content_type == "json":
        analysis["curl_result"] = AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type="json",
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            promoted_sources=[],
            diagnostics=diagnostics,
        )
        setattr(normalized, "_acquirer_analysis", analysis)
        return normalized
    
    decision_started_at = time.perf_counter()
    
    # FIX: Offload CPU-bound HTML parsing to prevent Event Loop Starvation
    blocked = await asyncio.to_thread(detect_blocked_page, html)
    visible_text, gate_phrases = await asyncio.to_thread(_analyze_html_sync, html)
    content_len = _content_html_length(html)
    
    visible_len = len(visible_text)
    js_shell_detected = (
        content_len >= _JS_SHELL_MIN_CONTENT_LEN
        and visible_len > 0
        and (visible_len / content_len) < _JS_SHELL_VISIBLE_RATIO_MAX
    )
    adapter_hint = await _resolve_adapter_hint(url, html)
    platform_family = _detect_platform_family(url, html)
    
    # FIX: Offload extractability check
    extractability = await asyncio.to_thread(
        _assess_extractable_html, html, url=url, surface=surface, adapter_hint=adapter_hint
    )
    
    invalid_surface_page = _is_invalid_surface_page(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
    )
    diagnostics.update(
        {
            "curl_visible_text_length": len(visible_text),
            "content_len": content_len,
            "curl_blocked": blocked.is_blocked,
            "curl_block_provider": blocked.provider or None,
            "curl_gate_phrases": gate_phrases,
            "curl_adapter_hint": adapter_hint,
            "curl_platform_family": platform_family,
            "invalid_surface_page": invalid_surface_page or None,
            "extractability": extractability,
            "promoted_sources": extractability.get("promoted_sources"),
        }
    )
    diagnostics["timings_ms"] = _merge_timing_maps(
        diagnostics.get("timings_ms"),
        {"browser_decision_ms": _elapsed_ms(decision_started_at)},
    )
    useful = bool(
        html
        and not blocked.is_blocked
        and extractability["has_extractable_data"]
        and normalized.status_code not in {403, 429, 503}
        and not invalid_surface_page
    )
    fallback_eligible = bool(
        html
        and normalized.status_code not in {403, 429, 503}
        and not invalid_surface_page
    )
    analysis.update(
        {
            "blocked": blocked,
            "visible_text": visible_text,
            "content_len": content_len,
            "gate_phrases": gate_phrases,
            "js_shell_detected": js_shell_detected,
            "adapter_hint": adapter_hint,
            "platform_family": platform_family,
            "extractability": extractability,
            "invalid_surface_page": invalid_surface_page,
            "curl_result": AcquisitionResult(
                html=html,
                json_data=normalized.json_data,
                content_type=normalized.content_type,
                method="curl_cffi",
                artifact_path=str(_artifact_path(run_id, url)),
                promoted_sources=list(extractability.get("promoted_sources") or []),
                diagnostics=diagnostics,
            )
            if useful or fallback_eligible
            else None,
        }
    )
    setattr(normalized, "_acquirer_analysis", analysis)
    return normalized
2. Remove Runtime Monkey-Patching
File: app/services/crawl_service.py
Fix: Removes the highly dangerous _wire_runtime_dependencies function that overrides imports globally, relying instead on the established _batch_runtime architecture.
Replace the entire file with this safely-scoped version:
code
Python
from __future__ import annotations
from collections.abc import Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, ProxyPoolExhausted
from app.services.shared_acquisition import acquire, run_adapter, try_blocked_adapter_recovery
from app.services._batch_runtime import (
    _build_acquisition_profile,
    _build_url_metrics,
    _count_run_records,
    _finalize_url_metrics,
    _handle_run_control_signal,
    _merge_run_acquisition_metrics,
    _run_control_checkpoint,
    _sleep_with_checkpoint,
    process_run as _batch_process_run,
)
from app.services.crawl_crud import (
    active_jobs,
    commit_llm_suggestions,
    commit_selected_fields,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
)
from app.services.crawl_utils import parse_csv_urls
from app.services.db_utils import with_retry
from app.services.crawl_state import (
    ACTIVE_STATUSES,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    TERMINAL_STATUSES,
    normalize_status,
    set_control_request,
    update_run_status,
)

# Compatibility exports for tests
_COMPAT_EXPORTS = (
    active_jobs,
    commit_llm_suggestions,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
)

async def _load_run_with_normalized_status(
    retry_session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    retry_run = await retry_session.get(CrawlRun, run_id)
    if retry_run is None:
        raise ValueError("Run not found")
    return retry_run, normalize_status(retry_run.status)

async def _run_control_update(
    session: AsyncSession,
    run: CrawlRun,
    operation: Callable[[AsyncSession, CrawlRun, CrawlStatus], Awaitable[None]],
) -> CrawlRun:
    async def _wrapped(retry_session: AsyncSession) -> None:
        retry_run, current = await _load_run_with_normalized_status(retry_session, run.id)
        await operation(retry_session, retry_run, current)

    await with_retry(session, _wrapped)
    await session.refresh(run)
    return run

async def process_run(session: AsyncSession, run_id: int) -> None:
    # FIX: Runtime monkeypatching removed. Dependencies are handled cleanly by imports.
    await _batch_process_run(session, run_id)

async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.RUNNING:
            raise ValueError(f"Cannot pause run in state: {retry_run.status}")
        set_control_request(retry_run, CONTROL_REQUEST_PAUSE)

    return await _run_control_update(session, run, _operation)

async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state: {retry_run.status}")
        update_run_status(retry_run, CrawlStatus.RUNNING)
        set_control_request(retry_run, None)

    return await _run_control_update(session, run, _operation)

async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Cannot kill run in terminal state: {retry_run.status}")
        if current == CrawlStatus.RUNNING:
            set_control_request(retry_run, CONTROL_REQUEST_KILL)
        else:
            update_run_status(retry_run, CrawlStatus.KILLED)
            set_control_request(retry_run, None)

    return await _run_control_update(session, run, _operation)

async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)
3. Fix Data Loss in Advanced Traversal Pagination
File: app/services/extract/listing_extractor.py
Fix: Ensures XHR API payloads from the browser interception layer are passed to pages 2-N in an infinite scroll or pagination loop, curing silent data drops.
Replace the extract_listing_records function (around line 46):
code
Python
def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    xhr_payloads: list[dict] | None = None,
    adapter_records: list[dict] | None = None,
) -> list[dict]:
    page_fragments = _split_paginated_html_fragments(html)
    if len(page_fragments) > 1:
        merged_records: list[dict] = []
        for index, fragment in enumerate(page_fragments):
            merged_records.extend(
                _extract_listing_records_single_page(
                    fragment,
                    surface,
                    target_fields,
                    page_url=page_url,
                    max_records=max_records,
                    # FIX: Pass payloads to all paginated fragments to prevent data loss
                    xhr_payloads=xhr_payloads,
                    adapter_records=adapter_records,
                )
            )
            if len(merged_records) >= max_records:
                break
        return _dedupe_listing_records(merged_records)[:max_records]

    return _extract_listing_records_single_page(
        html,
        surface,
        target_fields,
        page_url=page_url,
        max_records=max_records,
        xhr_payloads=xhr_payloads,
        adapter_records=adapter_records,
    )
4. Remove Subprocess Arg-Injection Risk
File: app/services/url_safety.py
Fix: Removes the unsafe nslookup fallback which allowed asyncio.create_subprocess_exec to execute against user-provided hostnames.
Replace _resolve_host_ips and completely delete _resolve_host_ips_via_nslookup and _parse_nslookup_addresses (around line 89):
code
Python
async def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    attempts = max(1, int(DNS_RESOLUTION_RETRIES) + 1)
    for attempt in range(1, attempts + 1):
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
            break
        except socket.gaierror as exc:
            if attempt < attempts:
                await asyncio.sleep(max(0, DNS_RESOLUTION_RETRY_DELAY_MS) / 1000)
                continue
            # FIX: Removed the insecure nslookup fallback mechanism.
            raise ValueError(f"Target host could not be resolved: {hostname}") from exc

    resolved: list[str] = []
    seen: set[str] = set()
    for record in records:
        sockaddr = record[4]
        ip_text = str(sockaddr[0] or "").strip()
        if not ip_text or ip_text in seen:
            continue
        seen.add(ip_text)
        resolved.append(ip_text)
    return resolved

# NOTE: Completely delete `def _resolve_host_ips_via_nslookup(hostname: str)` 
# and `def _parse_nslookup_addresses(output: str)` from the file.
5. Fix Schema Arbitration / Pollution
File: app/services/config/extraction_rules.py
Fix: Assigns an explicit rank to datalayer below standard HTML structures, and blocks breadcrumbs (> and /) from bleeding into the brand and category properties.
Replace the source_ranking and field_pollution_rules keys in EXTRACTION_RULES (around line 348):
code
Python
"source_ranking": {
        "contract_xpath": 11,
        "contract_regex": 10,
        "adapter": 9,
        "product_detail": 9,
        "network_intercept": 8,
        "hydrated_state": 7,
        "embedded_json": 7,
        "open_graph": 7,
        "next_data": 7,
        "json_ld": 6,
        "microdata": 5,
        "selector": 4,
        "semantic_section": 3,
        "semantic_spec": 3,
        "datalayer": 2, # FIX: Lower-ranked datalayer stops it from overriding valid DOM/JSON-LD
        "dom_buy_box": 8,
        "dom": 1,
        "llm_xpath": 0,
    },
    "field_pollution_rules": {
        "title": {
            "reject_phrases": [
                "cookie preferences",
                "privacy policy",
                "sign in",
                "log in",
                "add to cart",
            ],
        },
        "brand": {
            "reject_phrases": [
                "cookie",
                "privacy",
                "sign in",
                "log in",
                ">", # FIX: Blocks breadcrumbs from bleeding into brand
                "/", # FIX: Blocks paths from bleeding into brand
            ],
        },
        "category": {
            "reject_phrases": [
                "cookie",
                "privacy",
                "sign in",
                "log in",
                ">", # FIX: Blocks breadcrumbs
                "/", # FIX: Blocks paths
            ],
        },
        "description": {
            "reject_phrases": [
                "cookie preferences",
                "privacy settings",
                "manage cookies",
            ],
        },
    },