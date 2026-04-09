6. Remove In-Memory DB Locking (Fixes Zombie Runs)
File: app/services/_batch_runtime.py
Problem: The crawler uses a global, in-memory dictionary (_RUN_UPDATE_LOCKS) to manage database concurrency. If a task times out or a worker pod restarts, the lock is never released, permanently hanging the run in the "RUNNING" state.
Fix: Rely entirely on SQLAlchemy's native database-level locking (with_for_update) and the existing with_retry exponential backoff, removing the memory leak.
Replace the locking logic (around line 52) by deleting _RUN_UPDATE_LOCKS and replacing _retry_run_update and _cleanup_run_lock:
code
Python
# DELETE THESE TWO LINES ENTIRELY:
# _RUN_UPDATE_LOCKS: dict[int, asyncio.Lock] = {}
# _RUN_UPDATE_LOCKS_GUARD = asyncio.Lock()

async def _retry_run_update(
    session: AsyncSession,
    run_id: int,
    mutate,
) -> None:
    """Safely update a run using DB-level row locks (FOR UPDATE) and exponential backoff."""
    async def _load_run_for_update(
        retry_session: AsyncSession, target_run_id: int
    ) -> CrawlRun | None:
        bind = retry_session.bind
        if bind is not None and bind.dialect.name != "sqlite":
            result = await retry_session.execute(
                select(CrawlRun)
                .where(CrawlRun.id == target_run_id)
                .with_for_update()
            )
            return result.scalar_one_or_none()
        return await retry_session.get(CrawlRun, target_run_id)

    async def _operation(retry_session: AsyncSession) -> None:
        retry_run = await _load_run_for_update(retry_session, run_id)
        if retry_run is None:
            return
        await mutate(retry_session, retry_run)

    # Directly use the DB retry mechanism without the broken in-memory lock
    await with_retry(session, _operation)

async def _cleanup_run_lock(run_id: int) -> None:
    # Intentionally left empty as the in-memory lock dict has been removed.
    # Kept to preserve the function signature used in the finally block.
    pass
7. Enforce Strict Field Validation (Fixes Schema Pollution)
File: app/services/normalizers.py (If this file wasn't fully provided, here is the function to replace/create)
Problem: The pipeline selects the "highest ranked" extraction source (like a DataLayer), but doesn't validate if the content is garbage (e.g. brand: "Home > Privacy Policy").
Fix: Add a strict canonical validation gate. If a high-ranked source fails these rules, the pipeline will naturally fall back to the next-highest source (like JSON-LD or DOM).
Update or replace validate_value in your normalizers file:
code
Python
import re

def validate_value(field_name: str, value: object) -> object | None:
    """Strict canonical validation gate. Rejects garbage strings so fallbacks can win."""
    if value in (None, "", [], {}):
        return None
        
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        lowered = text.lower()
        
        # 1. Global noise rejection
        if lowered in {"null", "undefined", "n/a", "none", "nan"}:
            return None
            
        # 2. Field-specific strict rules
        if field_name == "brand":
            if len(text) > 60: return None
            if ">" in text or "/" in text: return None # Rejects breadcrumbs
            if "cookie" in lowered or "privacy" in lowered: return None
            
        elif field_name == "color":
            if len(text) > 40: return None
            if re.search(r"[{};]|rgb\(|rgba\(|#\w{3,6}", lowered): return None # Rejects CSS
            if "cookie" in lowered or "select" in lowered: return None
            
        elif field_name == "availability":
            if len(text) > 50: return None
            if re.search(r"dimension\d+|metric\d+", lowered): return None # Rejects GA metrics
            
        elif field_name == "category":
            if len(text) > 150: return None
            if "cookie" in lowered or "sign in" in lowered: return None
            
        return text

    return value
8. Fix Infinite Scroll & Load More Termination
File: app/services/acquisition/traversal.py
Problem: scroll_to_bottom and click_load_more blindly wait cooperative_sleep_ms, which often isn't long enough for SPAs, or wastes time if the network is fast.
Fix: Inject Playwright's networkidle state wait, so it accurately waits for XHR requests to finish fetching new items.
Update the scroll_to_bottom loop (around line 431) and click_load_more loop (around line 557). Locate the await cooperative_sleep_ms(...) lines and replace them with this block:
code
Python
# FIX: Wait for network idle to ensure XHRs for new items complete, 
        # falling back to the cooperative sleep if it times out.
        if hasattr(page, "wait_for_load_state"):
            try:
                from playwright.async_api import TimeoutError as PwTimeoutError
                await page.wait_for_load_state("networkidle", timeout=max(request_delay_ms, config.scroll_wait_min_ms))
            except (PwTimeoutError, Exception):
                await cooperative_sleep_ms(
                    max(request_delay_ms, config.scroll_wait_min_ms),
                    checkpoint=checkpoint,
                )
        else:
            await cooperative_sleep_ms(
                max(request_delay_ms, config.scroll_wait_min_ms),
                checkpoint=checkpoint,
            )
(Apply the above snippet right after await perform_scroll(...) and right after await button.click() in their respective functions).
9. Harden Browser Context Against SSRF Bypass
File: app/services/acquisition/browser_client.py
Problem: The page.route("**/*") interceptor correctly blocks non-public URLs for standard requests, but malicious sites can bypass this using Service Workers to make requests from the background.
Fix: Explicitly disable Service Workers in the browser context.
Modify the _context_kwargs function (around line 697):
code
Python
def _context_kwargs(prefer_stealth: bool, *, browser_channel: str | None = None) -> dict:
    if browser_channel:
        kwargs = {
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "viewport": {"width": 1365, "height": 900},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "color_scheme": "light",
            "user_agent": _STEALTH_USER_AGENT,
            "service_workers": "block", # FIX: Prevent Service Worker SSRF bypasses
        }
        return kwargs
    kwargs = {
        "java_script_enabled": True,
        "ignore_https_errors": True,
        "bypass_csp": True,
        "locale": "en-US",
        "timezone_id": "UTC",
        "viewport": {"width": 1365, "height": 900},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "color_scheme": "light",
        "service_workers": "block", # FIX: Prevent Service Worker SSRF bypasses
    }
    if prefer_stealth:
        kwargs["user_agent"] = _STEALTH_USER_AGENT
    return kwargs
10. Remove Dangerous Hardcoded Site URL Synthesis
File: app/services/extract/listing_extractor.py
Problem: The generic extractor contains hardcoded logic specifically for UltiPro (_synthesize_ultipro_detail_url). If a non-Ultipro URL accidentally matches the pattern, it will completely mangle the extracted URL. Site-specific logic belongs in Adapters.
Fix: Remove the hardcoded dispatch table and function entirely.
Find and replace this block (around line 737) to remove the hack:
code
Python
def _synthesize_job_detail_url(item: dict, *, page_url: str) -> str:
    if not isinstance(item, dict):
        return ""
    # FIX: Removed dangerous hardcoded _JOB_URL_SYNTHESIS_STRATEGIES dispatch.
    # Site-specific URL synthesis must be handled by proper Adapters (e.g. SaaSHRAdapter).
    return _default_job_detail_url_synthesis(item, page_url=page_url)

def _clean_identifier(value: object) -> str:
    return " ".join(str(value or "").split()).strip()

def _default_job_detail_url_synthesis(item: dict, *, page_url: str) -> str:
    del item, page_url
    return ""

# DELETE THESE ENTIRELY:
# def _synthesize_ultipro_detail_url(...)
# def _detect_platform_family_from_url(...)
# _JOB_URL_SYNTHESIS_STRATEGIES = {"ultipro_ukg": _synthesize_ultipro_detail_url}