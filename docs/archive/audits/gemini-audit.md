Section 1–8: Dimension Scores
Dimension: D1. SOLID / DRY / KISS
Floor: 6/10 | Ceiling: 9/10 | Score: 7.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM app/services/acquisition/browser_page_flow.py → BrowserAcquisitionResultBuilder.build (approx lines 62-126):
This method acts as a massive God Function orchestrating network capture closure, block classification, HTML sizing, screenshot capture, listing artifact extraction, and dict mapping. It violates SRP.
Breaks SRP/KISS by mixing domain logic (what to capture) with pipeline orchestration (how to capture it).
Production failure mode: Modifying any single artifact capture flow risks breaking the entire browser finalization pipeline.
Verification: rg -n "async def build\(self\)" app/services/acquisition/browser_page_flow.py
Verdict: The codebase generally adheres well to single-responsibility bounds, especially post-refactor in the extraction pipelines (detail_tiers.py). However, the browser acquisition finalization path remains a structural choke point that needs decoupling.
Dimension: D2. Configuration Hygiene
Floor: 7/10 | Ceiling: 9/10 | Score: 8.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM app/services/acquisition/browser_identity.py → _is_version_coherent (approx lines 105-120):
Hardcoded Chrome major version thresholds (if ua_major < 120: return False) and specific browser brand strings ("chromium", "google chrome", "chrome") embedded directly in the identity generation logic.
Breaks INVARIANTS.md clause regarding configuration separation; magic numbers and strings for browser fingerprinting should live in runtime_settings.py or a dedicated config file.
Production failure mode: As browsers age, this code requires manual patching rather than a dynamic env-var update, risking sudden stealth degradation.
Verification: rg -n "ua_major < 120:" app/services/acquisition/browser_identity.py
Verdict: Excellent use of pydantic_settings and platforms.json overall. The extraction rule configs are wonderfully isolated. Only minor fingerprinting magic strings bleed into business logic.
Dimension: D3. Scalability & Resource Management
Floor: 6/10 | Ceiling: 9/10 | Score: 7.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
HIGH app/core/redis.py → schedule_fail_open (approx lines 62-75):
Fires background tasks using loop.create_task(_runner()) without keeping a strong reference or tracking them in a TaskGroup or registry.
Breaks fundamental Python asyncio safety invariants (tasks can be garbage collected mid-flight, or orphaned during shutdown).
Production failure mode: Under high load, event loop garbage collection can destroy these telemetry/logging tasks before they complete, leading to silent metric drops and memory leaks.
Verification: rg -n "loop.create_task\(_runner\(\)\)" app/core/redis.py
Verdict: Playwright concurrency via SharedBrowserRuntime and its semaphores is highly robust. However, the untracked async task spawning for Redis metrics introduces immediate runtime instability risks.
Dimension: D4. Extraction & Normalisation Pipeline
Floor: 9/10 | Ceiling: 10/10 | Score: 9.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No critical or high violations found.
Verification: rg -n "def validate_record_for_surface" app/services/field_value_core.py (Shows strong schema enforcement).
Verdict: This is a masterclass in extraction tiering. The explicit fallback hierarchy (authoritative -> structured_data -> js_state -> dom) combined with the validate_and_clean surface enforcement guarantees high-fidelity data without schema bleed.
Dimension: D5. Traversal Mode
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
LOW app/services/acquisition/traversal.py → _click_with_retry (approx lines 550-610):
The fallback node.click() JS evaluation executes blindly on the locator without asserting the execution context hasn't been destroyed.
While it catches Exception, it heavily relies on the Playwright bridge not hanging during rapid DOM mutations.
Production failure mode: Intermittent Playwright target closed exceptions during aggressive load-more cycles.
Verification: rg -n "node instanceof HTMLElement && node.click\(\)" app/services/acquisition/traversal.py
Verdict: Traversal handles pagination cycles, domain-escape prevention, and tenant boundary isolation exceptionally well. The only minor risk is the brute-force JS click fallback.
Dimension: D6. Resilience & Error Handling
Floor: 5/10 | Ceiling: 8/10 | Score: 6.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
HIGH app/services/acquisition/browser_page_flow.py → Multiple functions (e.g., _capture_listing_visual_elements):
Uses broad except Exception: blocks that execute logger.debug(..., exc_info=True) and return empty structures.
Breaks ENGINEERING_STRATEGY.md regarding explicit failure handling; Playwright timeouts, target closures, and execution context destruction are collapsed into generic "failed" states.
Production failure mode: Extremely difficult to debug whether an artifact capture failed due to a timeout (expected) or a browser crash (critical system failure).
Verification: rg -n "except Exception:" app/services/acquisition/browser_page_flow.py
Verdict: While the pipeline gracefully recovers from empty records using LLM fallbacks, the browser tier suppresses too many underlying Playwright exceptions, masking infrastructure health.
Dimension: D7. Dead Code & Technical Debt
Floor: 6/10 | Ceiling: 8/10 | Score: 7.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
HIGH tests/test_pipeline_core.py → test_sanitize_llm_existing_values_uses_runtime_max_chars... (approx lines 34-45):
The test suite directly imports and tests private/internal functions (_sanitize_llm_existing_values, _apply_direct_record_llm_fallback) rather than testing the public process_single_url API contract.
Breaks AP-7 (Testing Private Methods).
Production failure mode: Refactoring internal pipeline structures will break tests, actively discouraging future tech debt cleanup.
Verification: rg -n "def test_sanitize_llm_existing_values" tests/test_pipeline_core.py
Verdict: The business code is clean and free of TODOs, but the test suite is tightly coupled to implementation details, violating AP-7 constraints.
Dimension: D8. Acquisition Mode
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM app/services/crawl_fetch_runtime.py → _select_http_fetcher (approx lines 320-322):
Hardcodes the return value to _curl_fetch. The _http_fetch (standard HTTPX) path is completely bypassed for standard requests.
Breaks expected escalation patterns if curl_cffi faces TLS fingerprinting issues that plain HTTPX might bypass, or limits testing environments that lack curl_cffi binaries.
Production failure mode: Wasted code path for HTTPX, and inability to dynamically swap to plain HTTPX if curl_cffi fails locally.
Verification: rg -n "def _select_http_fetcher" app/services/crawl_fetch_runtime.py
Verdict: Acquisition logic is strongly separated from extraction. Proxy threading is correct. The hardcoded fetcher selection is the only structural misstep here.
Section 9: Final Summary
Overall Score: 7.8/10 (previous: N/A, delta: N/A)
Root Cause Findings (architectural — require a plan, not a bug fix):
RC-1: Untracked background task creation in Redis metrics (schedule_fail_open) leading to task orphaning and potential event loop memory leaks. — affects D3.
RC-2: Broad exception swallowing (except Exception) across Playwright boundaries masks critical infrastructure failures. — affects D6.
Leaf Node Findings (isolated bugs — Codex can fix directly):
LN-1: tests/test_pipeline_core.py → Remove direct tests of private functions (_sanitize_llm_existing_values), test via process_single_url.
LN-2: app/services/crawl_fetch_runtime.py → _select_http_fetcher → Implement actual fallback/selection logic between _curl_fetch and _http_fetch.
LN-3: app/services/acquisition/browser_identity.py → Move Chrome version hardcodes (< 120) to crawler_runtime_settings.py.
Genuine Strengths (file-level evidence only, no generic praise):
app/services/extract/detail_tiers.py: Exceptional application of the Strategy/State pattern to separate Extraction Tiers (collect_authoritative_tier, collect_dom_tier). It keeps the build_detail_record flow clean, testable, and strictly enforces precedence.
app/services/network_payload_mapper.py: Outstanding use of JMESPath arrays via _first_non_empty_path to declaratively map XHR/Graphql endpoints to canonical fields without brittle, nested if/else logic.
Section 10: Codex-Ready Work Orders
WORK ORDER RC-1: Track Async Background Tasks Safely
Touches buckets: API + Bootstrap, Crawl Ingestion + Orchestration
Risk: HIGH
Do NOT touch: Core extraction logic or browser contexts.
What is wrong
app/core/redis.py uses loop.create_task(_runner()) inside schedule_fail_open but never retains a strong reference to the task. Python's asyncio garbage collects unreferenced tasks mid-execution, causing silent telemetry drops.
What to do
In app/core/redis.py, create a global module-level set to track background tasks: _BACKGROUND_TASKS = set().
Update schedule_fail_open to add the spawned task to this set:
task = loop.create_task(_runner())
_BACKGROUND_TASKS.add(task)
task.add_done_callback(_BACKGROUND_TASKS.discard)
Ensure thread-safety if this is invoked across loop boundaries (though typical FastAPI usage is single-loop, standard discard on callback is safe).
Acceptance criteria

schedule_fail_open retains a strong reference to background tasks.

Tasks automatically remove themselves from the set upon completion.

grep -r "loop.create_task" app/core/redis.py shows assignment to a variable and tracking.

python -m pytest tests -q exits 0
What NOT to do
Do not use asyncio.TaskGroup here, as schedule_fail_open is a synchronous wrapper meant to fire-and-forget from synchronous code paths where context managers aren't feasible.
WORK ORDER RC-2: Refine Playwright Exception Handling
Touches buckets: Acquisition + Browser Runtime
Risk: HIGH
Do NOT touch: DOM extractors or LLM paths.
What is wrong
app/services/acquisition/browser_page_flow.py relies on except Exception: to catch Playwright errors during artifact capture (e.g., _capture_listing_visual_elements). This swallows asyncio.CancelledError (if unhandled properly at the boundary) and masks TargetClosedError vs TimeoutError.
What to do
In app/services/acquisition/browser_page_flow.py, import Error and TimeoutError from playwright.async_api.
Locate the except Exception: block in _capture_listing_visual_elements and _capture_listing_artifact_with_timeout.
Change to catch specific exceptions:
except TimeoutError: -> Log as timeout.
except Error as exc: -> Log as Playwright error, checking is_response_closed_error if necessary.
except Exception: -> Keep as absolute fallback, but log explicitly as Unexpected execution error.
Ensure asyncio.CancelledError is always explicitly re-raised if caught.
Acceptance criteria

Playwright TimeoutError and Error are explicitly caught and differentiated.

asyncio.CancelledError is not swallowed.

grep -r "except Exception:" app/services/acquisition/browser_page_flow.py is reduced to only catastrophic fallback paths.

python -m pytest tests -q exits 0
What NOT to do
Do not bubble Playwright errors up to the orchestrator; artifact capture failures should still return empty structures [], but the logging must be precise.
WORK ORDER LN-1: Remove Private Function Tests (AP-7) (single-session fix)
File: tests/test_pipeline_core.py
Function: test_sanitize_llm_existing_values_uses_runtime_max_chars_and_strips_html
Fix: Delete the test entirely. The validation of LLM existing value sanitization is already implicitly covered by test_process_single_url_persists_detail_records_after_self_heal_and_llm_fallback which exercises the full pipeline. Testing _sanitize_llm_existing_values directly violates AP-7.
Test: pytest tests/test_pipeline_core.py passes.
WORK ORDER LN-2: Fix Hardcoded HTTP Fetcher Selection (single-session fix)
File: app/services/crawl_fetch_runtime.py
Function: _select_http_fetcher
Fix: Change return _curl_fetch to a configurable/dynamic approach. Since _curl_fetch is the primary workhorse, at least check if an environment variable or setting forces HTTPX, e.g., return _http_fetch if crawler_runtime_settings.force_httpx else _curl_fetch. (Ensure force_httpx is added to CrawlerRuntimeSettings if applied).
Test: grep -r "def _select_http_fetcher" app/services/crawl_fetch_runtime.py confirms logic evaluates settings.
WORK ORDER LN-3: Extract Chrome Version Magic Numbers (single-session fix)
File: app/services/acquisition/browser_identity.py
Function: _is_version_coherent
Fix: Extract the hardcoded < 120 check to use crawler_runtime_settings.browser_identity_min_chrome_version (default 120). Add this field to CrawlerRuntimeSettings in app/services/config/runtime_settings.py.
Test: grep -r "ua_major <" app/services/acquisition/browser_identity.py returns empty.
ARCHITECTURAL RECOMMENDATIONS
Note: As noted in the audit, CrawlerAI already successfully implements advanced Ghost-Routing (via network_payload_mapper.py), Hydrated State Interception (js_state_mapper.py), and LLM Selector Synthesis (selector_self_heal.py). The following recommendations address the remaining structural gaps found during this specific audit.
Task Registry Pattern for Fire-and-Forget Metrics
Gap: schedule_fail_open fires async tasks into the void, risking garbage collection (RC-1).
Slot: API / Orchestration Boundary.
Pseudocode:
code
Python
_BACKGROUND_TASKS = set()
def fire_background_task(coro):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
Yield: Prevents silent metric/log loss under heavy load, ensuring accurate operational observability without introducing blocking I/O overhead to the crawler.
Typed Exception Taxonomy for Playwright Bounds
Gap: Broad except Exception usage in browser_page_flow.py masks target closures vs JS execution timeouts (RC-2).
Slot: Browser Runtime / Acquisition.
Pseudocode:
code
Python
except asyncio.TimeoutError:
    return [], {"status": "timeout"}
except PlaywrightError as exc:
    if "Target closed" in str(exc):
        return [], {"status": "page_closed"}
    return [], {"status": "playwright_error"}
Yield: Prevents the crawler from retrying indefinitely on pages that intentionally crash the context (bot-traps), yielding higher throughput and better diagnostic accuracy.
Dynamic Fetcher Escalation based on TLS Fingerprint Feedback
Gap: _select_http_fetcher hardcodes curl_cffi, ignoring httpx (LN-2).
Slot: Acquisition / HTTP Client.
Pseudocode:
code
Python
def _select_http_fetcher(context: _FetchRuntimeContext):
    if context.last_error and isinstance(context.last_error, curl_cffi.requests.errors.RequestsError):
        return _http_fetch # Fallback if C-bindings crash
    return _curl_fetch
Yield: Increased resilience. If the upstream server aggressively blocks the specific chrome131 JA3 fingerprint provided by curl_cffi, falling back to standard httpx HTTP/2 profiles might surprisingly bypass simplistic blocks.