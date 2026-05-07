Problem 1 — load_host_protection_policy Is Called Up To 4 Times Per Page
File: crawl_fetch_runtime.py

Trace a single blocked-then-browser-escalated request:

python
# Call 1 — at top of fetch_page()
learned_host_policy = await load_host_protection_policy(url, **host_policy_kwargs)

# Call 2 — inside _run_browser_attempts() when host_policy is None
active_host_policy = host_policy or await load_host_protection_policy(context.url)

# Call 3 — inside _handle_http_result() before invoking browser
host_policy=await load_host_protection_policy(result.final_url or ...)

# Call 4 — inside fetch_page() after http chain exhausted → browser fallback
browser_host_policy = await load_host_protection_policy(context.url, ttl_seconds=...)
This is a repeated async I/O hit (Redis/Postgres/memory store — whatever backs HostProtectionPolicy) for the same URL within the same request. The policy does not change between call 1 and call 4 because nothing has run yet that would update it. The result from call 1 is passed through _invoke_run_browser_attempts → _run_browser_attempts → active_host_policy = host_policy or .... But in _handle_http_result, the caller does not pass the already-loaded policy — it reloads fresh.

Fix: Load once in fetch_page(), store in context.host_policy, pass it to every downstream function. Kill calls 2, 3, and 4 in the non-reload paths. Only reload after a note_host_hard_block() write (i.e., after a real block is recorded, so the next engine check sees the updated state).

Time wasted: 3 extra async I/O round-trips per blocked request. On a 5-second acquisition with Redis at 1–2ms latency this is noise. On a slow datastore or high concurrency this compounds.

Problem 2 — The Navigation Fallback Cascade Does Three goto() Calls Sequentially With Full Timeout Each
File: browser_page_flow.py, navigate_browser_page_impl()

text
Attempt 1: goto(url, wait_until="networkidle",   timeout=goto_timeout_ms)
           → TimeoutError / PlaywrightError
Attempt 2: goto(url, wait_until="domcontentloaded", timeout=fallback_timeout)
           → TimeoutError / PlaywrightError  
Attempt 3: goto(url, wait_until="commit",         timeout=fallback_timeout_ms)
           → raises or succeeds
Each failed goto() consumes its full timeout before raising PlaywrightTimeoutError. If goto_timeout_ms is 20s, attempt 1 alone burns 20 seconds before falling back to attempt 2. This means a page that requires commit-level wait can spend 40+ seconds just navigating before any content is read.

The logic for when to use networkidle vs domcontentloaded already exists — it's in readiness_policy["navigation_wait_until"]. But if networkidle is selected and the site doesn't settle, you burn the full timeout.

Fix: The primary timeout for networkidle should be min(total_timeout × 0.4, networkidle_cap_ms) — not the full timeout. The remaining budget is for content expansion and artifact capture. Right now, if networkidle times out, there may be no timeout left for the readiness probes at all.

Time wasted: Up to goto_timeout_ms (likely 15–30s) on sites that don't fully settle — burning the entire acquisition budget on navigation alone before even reading a byte.

Problem 3 — settle_browser_page_impl() Calls get_page_html Up To 5 Times
File: browser_page_flow.py, settle_browser_page_impl()

python
# Probe 1: after_navigation
current_probe = await _cached_probe(refresh_html=True)

# Probe 2: after_optimistic_wait (if not ready after probe 1)
current_probe = await _cached_probe(refresh_html=True)

# Probe 3: after_networkidle (if still not ready after probe 2)
current_probe = await _cached_probe(refresh_html=True)

# Probe 4: after_platform_readiness (if readiness_override exists)
current_probe = await _cached_probe(refresh_html=True)

# Probe 5: after_detail_expansion (if expansion clicked anything)
current_probe = await _cached_probe(refresh_html=True)
Each refresh_html=True call inside _cached_probe calls get_page_html_impl(page) which serializes the entire DOM via Playwright's page.content(). On a product detail page, that's serializing a 400–800KB DOM string 5 times.

The caching is partially working — cached_html and cached_analysis are stored and reused when refresh_html=False. But every probe that transitions a state refreshes. On a slow site that takes all 4 wait phases before becoming ready, you serialize the DOM 5 times just in settle(), then again in serialize_browser_page_content_impl().

Fix: The cached_analysis from the last probe should be passed directly into serialize_browser_page_content_impl as prefetched_html + prefetched_analysis. This is already half-done (prefetched_html was added in the latest commit) but the prefetched_analysis companion was not. Remove the final DOM serialization in serialize() on the non-traversal path since cached_html from settle is identical to what serialize() would read.

Actual time wasted: Each page.content() call on a real page is 20–100ms. 5 calls = 100–500ms wasted in serialization alone, before any parsing.

Problem 4 — analyze_html() Runs BeautifulSoup Parse On Every Probe
File: browser_page_flow.py → _cached_probe() → analyze_html(cached_html)

python
async def _cached_probe(*, refresh_html: bool = False):
    nonlocal cached_html, cached_analysis
    if refresh_html or cached_html is None:
        cached_html = await get_page_html_impl(page)
        cached_analysis = analyze_html(cached_html or "")   # ← BS4 parse every time html changes
    elif cached_analysis is None:
        cached_analysis = analyze_html(cached_html or "")
analyze_html() runs a full BeautifulSoup parse. On a 500KB detail page that is 30–80ms per call. With 5 refreshes in settle + 1 in _generate_page_markdown + 1 in location_interstitial_detected = 7 BS4 parses of the same document.

cached_analysis IS being stored — so probes that don't refresh reuse it. But every refresh_html=True call re-parses. The result of the final parse in settle is then thrown away and the caller re-parses the same bytes when generating markdown and checking for location interstitials.

Fix: Return cached_analysis from settle_browser_page_impl() alongside cached_html. Pass it into BrowserAcquisitionResultBuilder and into _generate_page_markdown. This eliminates 2–3 redundant parses on the hot path.

Actual time wasted: 60–240ms per acquisition on a detail page.

Problem 5 — _capture_listing_visual_elements Runs Even When Surface Is ecommerce_detail
File: browser_page_flow.py, _capture_listing_artifacts()

python
(listing_visual_elements, listing_visual_capture) = await self._capture_timed_listing_artifact(
    _capture_listing_visual_elements(payload.page, surface=payload.surface),
    stage="listing_visual_capture",
    item_kind="mapping",
)
This fires unconditionally for every surface, then the result is gated later:

python
"listing_visual_elements": (
    listing_visual_elements
    if _capture_status_ok(listing_artifact_diagnostics, "listing_visual_capture")
    else None
),
_capture_listing_visual_elements queries the DOM for visual price candidates, brand selectors, and structural containers — all listing-specific selectors. On a detail page these queries return nothing but still execute, still wait for asyncio.wait_for() timeout if anything hangs, and still serialize results.

Fix: Gate the entire _capture_listing_visual_elements call on surface:

python
if "listing" in str(payload.surface or "").lower():
    (listing_visual_elements, listing_visual_capture) = ...
else:
    listing_visual_elements, listing_visual_capture = [], {"status": "skipped", "reason": "non_listing_surface"}
Time wasted: Typically 10–50ms per detail page fetch — small but completely gratuitous.

Problem 6 — The Optimistic Wait Is Unconditional On Every Surface
File: browser_page_flow.py, settle_browser_page_impl()

python
wait_ms = min(int(timeout_seconds * 1000), int(crawler_runtime_settings.browser_navigation_optimistic_wait_ms))
if wait_ms > 0 and not current_probe["is_ready"]:
    await page.wait_for_timeout(wait_ms)   # ← blocks the whole event loop
    current_probe = await _cached_probe(refresh_html=True)
page.wait_for_timeout() is a wall clock sleep — it does not yield back while waiting for network activity. It just waits. On sites where the page is ready immediately after navigation (fast CDN-cached pages), this fires and adds optimistic_wait_ms of pure delay.

The guard not current_probe["is_ready"] is correct — but is_ready is set by probe_browser_readiness() which has its own bar (visible text, card counts, structured data). Sites that serve full HTML synchronously will pass this bar immediately. The issue is sites that are partially ready — they pass is_ready=True at this point but would have more content after networkidle. The optimistic wait fires on the not ready path — so sites that are already ready skip it. But for sites that are close to ready, this wait fires and just sleeps.

A smarter alternative: Instead of page.wait_for_timeout(), use page.wait_for_function(js_poll, timeout=wait_ms) with a short-circuit condition (e.g., product title selector visible). That way you return as soon as the page is actually ready, not after a fixed sleep. This would convert a fixed 500–2000ms sleep into a 50–300ms actual-readiness wait on most pages.

Time wasted: optimistic_wait_ms milliseconds (likely 500–2000ms) on any not-immediately-ready page, regardless of whether it actually needed that wait.

Problem 7 — _invoke_run_browser_attempts Is a Pure Pass-Through With No Logic
File: crawl_fetch_runtime.py

python
async def _invoke_run_browser_attempts(context, *, reason, requested_fields, listing_recovery_mode,
    capture_page_markdown, capture_screenshot, proxies, host_policy) -> PageFetchResult:
    return await _run_browser_attempts(context, reason=reason, requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode, capture_page_markdown=capture_page_markdown,
        capture_screenshot=capture_screenshot, proxies=proxies, host_policy=host_policy,
    )
This function has zero logic. It is called in 3 places with identical signatures. It exists to route calls to _run_browser_attempts but adds a call frame, an async await, and 12 lines of code for zero functional value. It is a classic thin-wrapper anti-pattern.

Fix: Delete _invoke_run_browser_attempts. Replace all 3 call sites with direct _run_browser_attempts(...) calls. This is a mechanical find-replace.

Execution Flow Visualized
text
fetch_page()
│
├─ load_host_policy ①  ← CALL 1 of 4
│
├─ [browser_first] ─────────────────────────────────────────────────┐
│   └─ _try_browser_http_handoff()                                   │
│         └─ [blocked] → _invoke_run_browser_attempts()  ← WRAPPER  │
│                             └─ _run_browser_attempts()            │
│                                   └─ load_host_policy ②  ← CALL 2 │
│                                                                    │
├─ [http path] ──────────────────────────────────────────────────────┤
│   └─ _run_http_fetch_chain()                                       │
│         └─ per-proxy: curl → timeout → retry                      │
│               └─ _handle_http_result()                            │
│                     └─ load_host_policy ③  ← CALL 3              │
│                     └─ _invoke_run_browser_attempts()  ← WRAPPER  │
│                           └─ _run_browser_attempts()              │
│                                 └─ load_host_policy ④  ← CALL 4   │
│                                                                    │
│   browser_fetch()                                                  │
│     │                                                              │
│     ├─ navigate_browser_page_impl()                                │
│     │    └─ goto(networkidle, 20s) → TIMEOUT ← BURNS FULL BUDGET  │
│     │    └─ goto(domcontentloaded, 15s) → TIMEOUT                 │
│     │    └─ goto(commit, 10s)                                      │
│     │                                                              │
│     ├─ settle_browser_page_impl()                                  │
│     │    └─ get_page_html() × 5  ← DOM SERIALIZE 5×               │
│     │    └─ analyze_html() × 5   ← BS4 PARSE 5×                   │
│     │    └─ wait_for_timeout()   ← FIXED SLEEP                     │
│     │                                                              │
│     └─ BrowserAcquisitionResultBuilder.build()                     │
│          └─ _capture_listing_visual_elements()  ← RUNS ON DETAIL  │
│          └─ analyze_html() AGAIN  ← PARSE #6                      │
└────────────────────────────────────────────────────────────────────┘
Priority Order for Fixes
#	Problem	Time saved per request	Risk
#	Problem	Time saved per request	Risk
1	Navigation fallback consumes full timeout per attempt	15–40s on timeout path	Medium — test all 3 fallback branches
2	get_page_html / analyze_html called 5–7× per page	150–500ms always	Low — mechanical cache threading
3	wait_for_timeout fixed sleep → replace with wait_for_function	500–2000ms on slow sites	Medium — need JS condition per surface
4	load_host_protection_policy called 3–4× per request	3–10ms (I/O)	Low — thread through context
5	_capture_listing_visual_elements runs on detail surface	10–50ms	Low — one surface check guard
6	_invoke_run_browser_attempts thin wrapper	0ms perf, code clarity	Zero — delete and replace
Fix 2 and 5 are mechanical and zero-risk. Fix 1 requires timeout budget math — verify min(total_timeout × 0.4, cap) doesn't starve networkidle-dependent sites. Fix 3 requires JS condition strings to be tested per surface type.

Implementation update - 2026-05-07

Status: implemented for acquisition hot path.

- Host protection policy now loads once into fetch context and reloads only after hard-block writes or blocked browser outcomes.
- Primary `networkidle` navigation is capped by configured budget ratio before falling back to `domcontentloaded` / `commit`.
- Browser settle now uses a short-circuit page readiness wait instead of unconditional `wait_for_timeout`.
- Settled HTML analysis is reused by serialization/finalization where the rendered HTML matches.
- Listing visual capture is skipped for non-listing surfaces.
- Pure browser-runtime serialize/navigation wrappers were removed while keeping the settle wrapper used by tests.

Verification:

- `python -m py_compile app/services/crawl_fetch_runtime.py app/services/acquisition/browser_page_flow.py app/services/acquisition/browser_runtime.py app/services/config/runtime_settings.py`
- `pytest tests/services/test_browser_expansion_runtime.py tests/services/test_crawl_fetch_runtime.py tests/services/test_config_imports.py -q` passed: 247 passed.
- `python run_acquire_smoke.py commerce` passed: 6 ok, 0 failed.
- `pytest tests -q` ran: 1461 passed, 4 skipped, 3 failed. Failures are existing non-acquisition extraction/LOC-budget checks: two `test_crawl_engine.py` extraction expectations and `test_structure.py::test_service_files_stay_under_loc_budget` oversized-file budget.
