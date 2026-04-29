Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/traversal.py around lines 209 - 213, The current assignment to deadline_at uses float(timeout_seconds) which can raise ValueError/TypeError for non-numeric input; wrap the conversion in a small try/except (catch ValueError and TypeError) around the float(timeout_seconds) call used in the deadline_at calculation (the timeout_seconds -> deadline_at logic) and on exception treat the value as None (or log a warning) so invalid strings don't crash traversal code; ensure you only call float once and keep the existing > 0 check inside the guarded block.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/traversal.py around lines 271 - 280, The _run_scroll_traversal function accepts max_scrolls but never uses it; update the loop bound that currently uses crawler_runtime_settings.traversal_max_iterations_cap so it respects the smaller of the two limits (max_scrolls and crawler_runtime_settings.traversal_max_iterations_cap) and handles None appropriately (e.g., treat None as "no local limit" or use the cap). Modify the iteration logic in _run_scroll_traversal to compute an effective_max = min(filtered cap, max_scrolls) and use effective_max when deciding to stop scrolling, ensuring the function signature's max_scrolls parameter actually limits iterations.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py around lines 125 - 135, Export list missing constants: add DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES and DETAIL_LONG_TEXT_SOURCE_RANKS to the module's __all__ so they are publicly exported. Locate the __all__ declaration in extraction_rules.py and append the two symbol names (DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES, DETAIL_LONG_TEXT_SOURCE_RANKS) to the tuple/list of exported identifiers, ensuring the names match the defined constants exactly and preserve existing formatting and ordering conventions.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py around lines 376 - 396, SEMANTIC_SECTION_LABEL_SKIP_TOKENS is defined but not exported; add "SEMANTIC_SECTION_LABEL_SKIP_TOKENS" to the module's __all__ list so it becomes part of the public API. Locate the __all__ declaration in extraction_rules.py and append the identifier (as a string) to the tuple/list there (keeping formatting consistent with other exports) and run tests/type-checks to confirm no import breakage; ensure you reference the exact symbol name SEMANTIC_SECTION_LABEL_SKIP_TOKENS when updating __all__.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py around lines 310 - 330, The module defines constants LISTING_PRICE_NODE_SELECTORS, LISTING_PROMINENT_TITLE_TAGS, and JSON_RECORD_LIST_KEYS but they are not exported via __all__; update the module's __all__ to include these three symbols so they are publicly available (add "LISTING_PRICE_NODE_SELECTORS", "LISTING_PROMINENT_TITLE_TAGS", and "JSON_RECORD_LIST_KEYS" to the existing __all__ tuple/list).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 282 - 287, The function _detail_price_context_uses_cents currently declares an unused keyword-only parameter record; remove the unused parameter from the signature (change def _detail_price_context_uses_cents(page_url: str) -> bool) and update all call sites that pass record (e.g., any calls like _detail_price_context_uses_cents(page_url=..., record=...)) to stop passing that argument so behavior is unchanged; if the parameter is intended for future use instead, add a short clarifying comment inside _detail_price_context_uses_cents explaining why record is present.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_dashboard_service.py at line 214, The test contains a flaky assertion that assumes PostgreSQL sequence reset (assert next_run.id == 1); update the test in backend/tests/services/test_dashboard_service.py to avoid relying on sequence values—either remove the id equality assertion or replace it with a stable check (e.g., assert next_run.id is not None or assert next_run.id > 0, or assert other deterministic fields/state of the created run). If sequence reset is truly required for the test, explicitly reset the relevant sequence in the test setup/teardown instead of depending on DELETE behavior.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 98 - 107, sanitize_detail_long_text compares cleaned_text.lower() to the raw DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES which can miss matches; create a normalized module-level frozenset (e.g., low_signal_long_text_values) by applying clean_text(value).lower() to each value in DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES (like how low_signal_title_values is built), then update sanitize_detail_long_text to check cleaned_text.lower() in low_signal_long_text_values instead of DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES; reference sanitize_detail_long_text, DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES, and the new low_signal_long_text_values when making the change.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Header and navigation expand controls are now skipped even when they are valid detail toggles.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 273-273

2. possible bug: Importing a nonexistent helper breaks module loading at runtime.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 30-30

3. possible bug: Counting raw storage-state iterables can consume them and change later behavior.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 464-464

4. logic error: Refactoring marker loading can silently discard valid challenge signatures when the config shape is not a mapping.
   Path: backend/app/services/acquisition/runtime.py
   Lines: 722-722

5. logic error: Pagination now accumulates card counts across pages instead of tracking the current page count.
   Path: backend/app/services/acquisition/traversal.py
   Lines: 694-694

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.