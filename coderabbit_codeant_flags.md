Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/api/crawls.py around lines 674 - 676, The sleep call using crawler_runtime_settings.cooperative_sleep_poll_ms can raise TypeError/ValueError if the config is None or non-numeric; wrap the conversion in a defensive check (e.g., ensure the value is not None and is numeric, or use a try/except around float(...)) and fall back to a sensible default (use the existing minimum 0.001 seconds) while logging a warning via the module's logger when the config is invalid, and consider whether a separate log-poll interval config should be used instead of cooperative_sleep_poll_ms for websocket log streaming; locate the await asyncio.sleep(...) line and the crawler_runtime_settings.cooperative_sleep_poll_ms reference to implement these changes.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_page_flow.py around lines 1289 - 1294, candidateContainerSelectors may be empty so calling node.closest(candidateContainerSelectors.join(',')) can pass an empty string and throw; update the logic around node.closest in the block handling candidateContainerSelectors/anchorSelector so you first check candidateContainerSelectors.length > 0 (or that join(',') is a non-empty string) before calling node.closest, fall back to using node as the container if none provided, then proceed to compute hintedAnchor and href with the existing hintedAnchor/anchorSelector/toAbsolute logic to avoid the SyntaxError.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py at line 80, The constant CDN_IMAGE_QUERY_PARAMS is defined but not exported; add "CDN_IMAGE_QUERY_PARAMS" to the module's __all__ list so it is included in wildcard imports and public API; update the __all__ sequence (maintain the existing sorting convention used in the file) to include the new symbol alongside the other exported names.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 502 - 507, The code calls float(crawler_runtime_settings.selector_regex_timeout_seconds) directly before regex_lib.finditer which will raise ValueError/TypeError if the setting is None, empty, or non-numeric; update the call site around regex_lib.finditer (the matches variable) to sanitize/validate selector_regex_timeout_seconds first: attempt to coerce it to float in a small try/except, fall back to a safe default (e.g., 0 or None depending on regex_lib API) when conversion fails, and pass that sanitized value into regex_lib.finditer (or handle it by omitting the timeout argument); ensure any conversion exceptions are caught and do not propagate to the finditer call.

These are comments left during a code review. Please review all issues and provide fixes.

1. contract bug: The llm-commit endpoint now uses the manual field-commit contract and logging path.
   Path: backend/app/api/crawls.py
   Lines: 467-467

2. possible bug: Using an unvalidated runtime setting for websocket polling can stall or crash log streaming.
   Path: backend/app/api/crawls.py
   Lines: 674-674

3. integration bug: Moving the integer coercion helper changed its call contract and can break existing callers at runtime.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 20-20

4. type error: Passing an unsupported traversal keyword will crash listing acquisition.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 781-781

5. possible bug: No actionable bug found in the updated integer coercion calls.
   Path: backend/app/services/acquisition/browser_readiness.py
   Lines: 65-65

6. logic error: Replacing the built-in link check with a configurable selector can make listing capture miss valid cards.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 265-265

7. logic error: The new `max_records` parameter is forwarded through browser fetch, but record limiting already happens in traversal.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1117-1117

8. logic error: Using a configurable shutdown timeout can raise `ValueError` if settings become non-numeric.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 785-785

9. possible bug: Eagerly materializing arbitrary iterables can exhaust one-shot inputs and break caller expectations.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 307-307

10. logic error: Pagination traversal ignores the record target when the first page already meets it.
   Path: backend/app/services/acquisition/traversal.py
   Lines: 503-503

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.


fis this bug:
[browser] Dropdown: value "harness" not found in options (components/ui/primitives.tsx:150:13)
[browser] Dropdown: value "harness" not found in options (components/ui/primitives.tsx:150:13)
[browser] Dropdown: value "harness" not found in options (components/ui/