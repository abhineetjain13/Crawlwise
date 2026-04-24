Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_identity.py around lines 732 - 740, In _normalize_timezone_id, the function may return an invalid timezone string when neither the candidate nor the alias exist in pytz.all_timezones_set; update the logic in _normalize_timezone_id to return None for any value that is not a valid pytz timezone: lookup alias via _TIMEZONE_ALIASES, compute candidate, and if neither candidate nor alias is present in pytz.all_timezones_set then return None (only return the timezone string when it is found in pytz.all_timezones_set).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_identity.py around lines 1250 - 1264, The patched Intl.DateTimeFormat replacement doesn't preserve the native constructor's identity (properties like toString, static descriptors, symbols, length/name), so fingerprinting can detect it; update the replacement (the NativeDateTimeFormat / Intl.DateTimeFormat block that creates a Proxy and then sets Intl.DateTimeFormat.prototype and supportedLocalesOf) to copy all own property descriptors and symbol-keyed properties from NativeDateTimeFormat to the new Intl.DateTimeFormat function (except prototype), bind/copy supported static methods (e.g., supportedLocalesOf) and set Intl.DateTimeFormat.toString to NativeDateTimeFormat.toString bound to NativeDateTimeFormat; also copy configurable attributes (use Object.getOwnPropertyNames and Object.getOwnPropertySymbols + Object.defineProperty with original descriptors) and ensure the prototype assignment remains NativeDateTimeFormat.prototype so instanceof/constructor behavior is preserved.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_page_flow.py around lines 592 - 596, The current extraction converts response.browser_navigation_strategy with str(...) which turns an explicit None into the string "None"; change the logic in browser_page_flow.py where navigation_strategy is set so you retrieve the attribute into a temporary (e.g., val = getattr(response, "browser_navigation_strategy", None)) and only call str(val) and assign to navigation_strategy when val is not None (otherwise keep the existing navigation_strategy or use the fallback), ensuring you don't accept the literal "None" as a valid strategy.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_runtime.py around lines 1084 - 1085, allow_storage_state is left True even when _proxy_rotation_mode(proxy_profile) returns "rotating", which lets cookies/localStorage persist across rotated sessions; change the initialization of allow_storage_state to respect whether the proxy requires a fresh browser (e.g., set allow_storage_state = not _proxy_requires_fresh_browser_state(proxy_profile)) or add conditional logic where proxy_rotation_mode is checked (the same area that skips origin warmup) to force disabling storage reuse for rotating proxies; update any related persistence/load code to use this flag and add a short comment in the block referencing _proxy_rotation_mode and _proxy_requires_fresh_browser_state to clarify intent.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_runtime.py around lines 910 - 914, The CancelledError handler currently logs "Timed out closing browser context..." which wrongly implies a timeout; in the except asyncio.CancelledError block in browser_runtime.py change the logger.warning call to a distinct message such as "Browser context close was cancelled" (and remove or adapt the _browser_close_timeout_seconds() interpolation since cancellation is not a timeout). Keep this change local to the except asyncio.CancelledError branch (leave the TimeoutError handler message unchanged) and update the logger.warning invocation accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/host_protection_memory.py around lines 170 - 171, The proxy_used parameter in note_host_soft_block (and similarly in note_host_hard_block) is accepted but never used; either remove the unused parameter or include it in the persisted note. Update note_host_soft_block to add proxy_used into the note payload that's saved (e.g., include "proxy_used": proxy_used in the dict/object passed to the persistence call inside HostProtectionMemory.note_host_soft_block) or, if persistence isn't needed, remove the proxy_used parameter and all forwarded usages to avoid dead args.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/block_signatures.py at line 107, The mapping entry '"ips.js": "kasada_ips_script"' is too generic and can produce false positives; update the block_signatures mapping so the key targets Kasada-specific CDN/path patterns (e.g., a regex including known Kasada CDN domains or the full CDN path) instead of the generic filename "ips.js", and ensure the signature name "kasada_ips_script" remains associated with that more specific pattern so detection only matches true Kasada assets.

- Verify each finding against the current code and only fix it if needed.

In @backend/run_browser_surface_probe.py at line 135, The current identity_run_id is generated with int(datetime.now(UTC).timestamp()) which only has second-level precision and can collide for multiple runs in the same second; update the generation in run_browser_surface_probe.py where identity_run_id is assigned (identity_run_id, datetime.now, UTC) to use higher-resolution time or append a random/UUID suffix (e.g., multiply timestamp to milliseconds or use datetime.now(UTC).timestamp()*1000, or combine datetime.now(UTC).microsecond or uuid4()) so IDs are unique across rapid invocations.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_proxy_bridge.py around lines 69 - 84, Concurrent calls to start() can race because the initial guard checks self._server/self._server_url before either assignment; protect the critical section by adding and using an asyncio.Lock (e.g., self._start_lock) around the code that creates/assigns self._server and self._server_url inside start() so only one coroutine can create the server; ensure lock is created in the class initializer and used as "async with self._start_lock:" to cover the check, creation (asyncio.start_server), socket inspection, port extraction, assignment to self._server/self._server_url, and counter increments.

- Verify each finding against the current code and only fix it if needed.

In @docs/audits/browser-hardening-review-2026-04-24.md at line 91, The persisted and surfaced state prefer_proxy is dead; either remove its persistence and diagnostic exposure or wire it into the fetch logic: update the persistence layer and diagnostic code to drop the prefer_proxy key (and any migrations/DB schema and telemetry that set/surface it) OR modify the fetch path functions (e.g., fetchResource, getFetchOptions, HttpClient/ProxyClient instantiation) to read prefer_proxy and route requests through the proxy client or bypass it accordingly; ensure tests and any config UI that set prefer_proxy are updated to match the chosen approach.

- Verify each finding against the current code and only fix it if needed.

In @docs/audits/browser-hardening-review-2026-04-24.md at line 92, The _RECENT_OUTCOME_STATE global currently grows without bounds; replace or wrap it with a bounded cache that enforces a maximum size and LRU eviction (or add a periodic cleanup pass) to prevent memory leaks. Locate the declaration and usages of _RECENT_OUTCOME_STATE and change the implementation to use an LRU-backed map (or add a manager that tracks access timestamps and evicts oldest entries when size > MAX_RECENT_OUTCOMES), ensure concurrent access patterns are preserved, and add tests exercising eviction (e.g., inserting > MAX_RECENT_OUTCOMES and verifying oldest entries are removed) and a configuration constant MAX_RECENT_OUTCOMES for tuning.

- Verify each finding against the current code and only fix it if needed.

In @docs/audits/browser-hardening-review-2026-04-24.md around lines 16 - 17, The smoke test fails because backend/corpora/acceptance_corpus.json is missing; either add the missing acceptance_corpus.json to backend/corpora (commit the canonical test corpus) or update the smoke test process/run_extraction_smoke.py to handle absence by documenting the exclusion and/or skipping the test path when the file is not present (e.g., check for the file and print instructions), and update the repository docs (README or docs/audits/browser-hardening-review-2026-04-24.md) to explain why the corpus is excluded and how to run smoke tests without it.

- Verify each finding against the current code and only fix it if needed.

In @docs/audits/browser-hardening-review-2026-04-24.md at line 93, The document currently contains the placeholder sentence "Code Quality and Tests sections pending chat review"; update the document by either (A) replacing that placeholder with complete "Code Quality" and "Tests" sections that summarize tooling, linting, test coverage, CI gates, and recommended remediation steps, or (B) if those sections are not ready, remove the placeholder sentence and any reference to pending review so the document no longer suggests incomplete content; locate the sentence "Code Quality and Tests sections pending chat review" to apply the change.

- Verify each finding against the current code and only fix it if needed.

In @docs/plans/fingerprint_plan.md around lines 18 - 44, Extend run_browser_surface_probe.py and acquisition/browser_runtime.py behavior to add clear error handling and resilience: implement per-site try/catch around get_browser_runtime(...).page(...) calls with configurable timeouts (page_load_timeout, navigation_timeout) and retries (max_retries, exponential_backoff_ms) and ensure failures are logged with site identifier and error details; treat partial results as valid—record per-site status and still generate a partial report (include fields like site_status, error_message, attempts) while marking overall run as degraded; when both --run-id and explicit proxy flags are provided, validate and fail fast; enforce respectful rate limiting/delay_between_requests_ms between site navigations and provide configuration for retry/backoff, timeout, and rate-limit values so operators can tune them.

- Verify each finding against the current code and only fix it if needed.

In @docs/plans/fingerprint_plan.md around lines 28 - 31, Add robust fallbacks for the site-specific extractors (sannysoft, pixelscan, creepjs) in the runner (not crawl acquisition) by: 1) implementing a validation step (e.g., runner.validateStructure or extractSiteSpecific.validate) that checks expected field names/page structure and detects version changes before attempting structured extraction; 2) if validation fails or required fields are missing, call a fallback captureFullPageDump/runner.captureFullPageDump to save raw HTML/DOM and a screenshot plus full JSON of navigator/headers so data is preserved; 3) ensure extractSiteSpecific (sannysoft/pixelscan/creepjs) functions return clear structured errors and call runner.reportMissingFields with missing-field details; and 4) wire a notifier (e.g., notifier.notifyOperators) to alert ops with context (site, crawler version, validation diff, stored page dump reference) so patterns can be updated.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: The new asyncio exception filter is never installed, so the intended suppression never runs.
   Path: backend/app/core/telemetry.py
   Lines: 111-111

2. possible bug: Installing a process-wide asyncio exception hook during lifespan startup can prevent the application from booting.
   Path: backend/app/main.py
   Lines: 52-52

3. logic error: Unset per-run timeout now falls back to a global default and can change run behavior unexpectedly.
   Path: backend/app/services/_batch_runtime.py
   Lines: 80-80

4. logic error: The new Playwright init script is built but not exposed to callers.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 1102-1102

5. logic error: Navigation strategy can remain stale because the recovered response does not reliably carry the new strategy.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 592-592

6. logic error: Recovered pages can now return an inconsistent response object and lose status normalization.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 83-83

7. possible bug: Successful retry recovery can bypass the wrapper that exposes recovery metadata.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 92-92

8. type error: Wrapping the response changes its runtime type and can break callers that expect the original response object.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 12-12

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.