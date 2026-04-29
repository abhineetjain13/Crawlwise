Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_proxy_config.py around lines 57 - 60, The condition in browser_proxy_config.py that currently reads `if userinfo or ":" in userinfo` is incorrect; replace it with a single clear check depending on intent—if any userinfo should be redacted then use `if userinfo`, otherwise if only credentials should be redacted use `if ":" in userinfo`; update the conditional guarding the existing `return "REDACTED"` (working with variables raw_proxy and userinfo) so the colon test is not short-circuited and the logic is unambiguous.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_stage_runner.py around lines 139 - 145, The current logic calls context() inside a suppress(TypeError) which only silences TypeError; if context() raises other exceptions it will propagate and prevent the fallback to closing the context. Update the callsite around page/context (the block assigning context = context() in browser_stage_runner.py) to catch broad exceptions (e.g., except Exception) instead of only TypeError so any error from invoking context() is handled; ensure you preserve existing behavior by leaving context as-is on failure and proceed to check context.close via the existing context_close logic (optionally log the caught exception for debugging).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 47 - 51, The needs_price condition currently only considers record.get("price") and misses low-signal prices nested in selected_variant or variants; update the needs_price expression in this module to also call _detail_price_value_is_low_signal on selected_variant.get("price") and on any variant.get("price") (or aggregate with any(...) over variants) so that low-signal nested prices trigger backfill, or alternatively remove the later redundant low-signal checks (lines checking selected_variant and variants) and keep a single authoritative check in needs_price; locate and update the needs_price assignment and ensure it references _detail_price_value_is_low_signal, selected_variant, and variants consistently.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/selectors_runtime.py around lines 184 - 187, Validate and normalize the limit before applying it to the query: convert limit to int and ensure it's non-negative (similar to the existing offset check) and either raise a clear ValueError when limit < 0 or treat negative values as no limit; then only call query = query.limit(int(limit)) when the validated limit is not None and >= 0. Apply this change around the existing query/offset/limit handling (the variables query, offset, limit in selectors_runtime.py) so negative limits are rejected or ignored consistently.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Moving pagination into the service can change summary results if the service does not preserve the old slicing semantics.
   Path: backend/app/api/selectors.py
   Lines: 53-53

2. logic error: Diagnostics always claim stealth is disabled even when the browser is using a shaped profile.
   Path: backend/app/services/acquisition/browser_diagnostics.py
   Lines: 63-63

3. null pointer: A failed fingerprint clone can now trigger a NoneType attribute error instead of falling back safely.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 1032-1032

4. possible bug: Accessibility snapshot cancellation is swallowed, preventing normal task cancellation.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 1189-1189

5. possible bug: Narrowing the network-idle exception handler can break the existing timeout fallback path.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 641-641

6. logic error: Early browser launch failures are reported with incorrect diagnostics.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1192-1192

7. resource leak: A synchronous failure before the cleanup path can leak browser resources.
   Path: backend/app/services/acquisition/browser_stage_runner.py
   Lines: 33-33

8. logic error: _storage_state_entry_count now only counts Collection values, changing iterable handling.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 476-476

9. logic error: _extract_cx_config_object() can truncate valid Oracle HCM config objects whenever a string value contains braces.
   Path: backend/app/services/adapters/oracle_hcm.py
   Lines: 242-242

10. logic error: _extract_job_id_from_url() is now restricted to CandidateExperience job URLs.
   Path: backend/app/services/adapters/oracle_hcm.py
   Lines: 281-281

11. possible bug: The Oracle HCM config regex can fail to match valid page configuration blobs.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 150-150

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.