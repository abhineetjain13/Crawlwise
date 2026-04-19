# Crawl Audit Remediation

Date: 2026-04-19

Scope:
- Source audit: external crawl-path audit over the acquisition, traversal, extraction, and self-heal slice
- This file now records remediation status against the current workspace
- Note: the external auditor did not review test files, so its "tests to add" recommendations were not treated as audit-scope requirements

Verification run:
- `pytest backend/tests/services/test_crawl_fetch_runtime.py backend/tests/services/test_traversal_runtime.py backend/tests/services/test_crawl_engine.py backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py`
- Result: `52 passed`

Files changed during remediation:
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/acquisition/traversal.py`
- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/listing_extractor.py`
- `backend/app/services/selector_self_heal.py`
- `backend/tests/services/test_traversal_runtime.py`

## Finding Status

### 1. Paginate Traversal Has No Outer Timeout Budget Guard
Status: Resolved

Applied changes:
- `execute_listing_traversal(...)` now accepts `timeout_seconds` and derives a traversal deadline.
- Scroll, load-more, and paginate loops stop with `budget_exceeded` when the traversal budget is exhausted.
- Internal waits and paginate navigation timeouts are clamped to the remaining traversal budget.
- `browser_fetch(...)` now passes the acquisition timeout into traversal.

Files:
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/acquisition/traversal.py`

### 2. WebPage -> mainEntity -> ItemList JSON-LD Pattern Produces Zero Records
Status: Resolved

Applied changes:
- Listing structured extraction now unwraps `mainEntity` payloads before dispatching by type.
- `ItemList` content nested under `mainEntity` is now harvested the same way as top-level `ItemList`.

Files:
- `backend/app/services/listing_extractor.py`

### 3. `fetch_page(...)` Exception Chain Can Raise `TypeError`
Status: Resolved

Applied changes:
- Removed the unsafe `raise type(last_error)(...)` reconstruction path.
- When browser fallback also fails after HTTP transport failure, the original exception is re-raised and chained from the browser fallback error instead of being replaced.

Files:
- `backend/app/services/crawl_fetch_runtime.py`

### 4. Listing Structured Stage Can Let Raw `js_state` Blobs Short-Circuit DOM Extraction
Status: Resolved

Applied changes:
- Listing structured extraction now skips `js_state` payloads entirely.
- This prevents arbitrary app-state objects from producing false one-record listing results that block DOM extraction.

Files:
- `backend/app/services/listing_extractor.py`

### 5. Self-Heal Gating Silently Accepts Low-Confidence Records When Domain Rules Already Exist
Status: Resolved

Applied changes:
- The stale-rule short-circuit was narrowed.
- Existing selector rules now skip self-heal only when there are no explicitly requested missing fields and the record confidence is at least a soft floor (`0.3`), instead of bypassing self-heal for all low-confidence records.

Files:
- `backend/app/services/selector_self_heal.py`

### 6. `apply_selector_self_heal(...)` Calls `session.flush()` Unconditionally
Status: Resolved

Applied changes:
- Selector self-heal now flushes the session only if synthesized rules were actually persisted.
- This removes an unnecessary failure path when self-heal did not write any selector updates.

Files:
- `backend/app/services/selector_self_heal.py`

### 7. `_detect_auto_mode(...)` Over-Prefers Paginate on Scrollable Listing Pages
Status: Resolved

Applied changes:
- Auto-mode now still prefers explicit `load_more`, but it no longer blindly prefers `paginate` over scroll signals.
- When scroll signals exist, auto-mode prefers scroll if the next-page control is non-navigational (`#`, `javascript:`, or empty) or the page already shows a meaningful number of cards.

Files:
- `backend/app/services/acquisition/traversal.py`

### 8. Embedded JSON Can Block DOM Listing Extraction With a False One-Item Result
Status: Resolved

Applied changes:
- The initial audit recommendation to exclude all `embedded_json` was narrowed because that would regress supported multi-item listing payloads from JS assignments.
- Listing structured extraction now allows embedded JSON only when it has listing-like shape at the source level:
  - multiple embedded payload rows, or
  - explicit `ItemList` / `itemListElement` signals
- Single low-signal embedded detail objects no longer short-circuit DOM listing extraction.

Files:
- `backend/app/services/listing_extractor.py`

## Notes

- The external audit's test-file recommendations were intentionally not copied forward as unresolved action items because the auditor did not inspect the test suite.
- Local verification still used the existing crawl-path tests in this repository after remediation.
- Two existing traversal assertions were updated to match the current tuple-based `html_fragments` shape and current scroll-fragment behavior while preserving the intended coverage.
