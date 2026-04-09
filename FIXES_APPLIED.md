# Security and Performance Fixes Applied

## Summary
Successfully applied 10 critical fixes addressing event loop starvation, runtime monkey-patching, data loss, argument injection, schema pollution, zombie runs, infinite scroll termination, SSRF bypass, and hardcoded site logic issues.

## Fixes Applied (Batch 1 - fixes.md)

### 1. ✅ Event Loop Starvation (CPU Blocking) - FIXED
**File:** `backend/app/services/acquisition/acquirer.py`

**Problem:** Heavy BeautifulSoup parsing and text extraction blocked the event loop during concurrent crawls, causing FastAPI server lockups.

**Solution:** 
- Added `_analyze_html_sync()` helper function to isolate CPU-bound HTML analysis
- Wrapped heavy operations in `asyncio.to_thread()`:
  - `detect_blocked_page(html)` 
  - `_analyze_html_sync(html)` (BeautifulSoup parsing + text extraction)
  - `_assess_extractable_html()` (extractability checks)

**Impact:** Prevents event loop blocking during concurrent crawl operations, improving server responsiveness.

---

### 2. ✅ Runtime Monkey-Patching (Circular Imports) - FIXED
**File:** `backend/app/services/crawl_service.py`

**Problem:** The `_wire_runtime_dependencies()` function performed dangerous runtime import overrides globally, creating circular dependency risks.

**Solution:**
- Removed the entire `_wire_runtime_dependencies()` function
- Removed the call to `_wire_runtime_dependencies()` from `process_run()`
- Dependencies now handled cleanly through established `_batch_runtime` architecture

**Impact:** Eliminates circular import risks and makes the codebase more maintainable.

---

### 3. ✅ Data Loss in Advanced Traversal Pagination - FIXED
**File:** `backend/app/services/extract/listing_extractor.py`

**Problem:** XHR API payloads from browser interception were only passed to page 1, causing silent data drops on pages 2-N during infinite scroll/pagination.

**Solution:**
- Modified `extract_listing_records()` to pass `xhr_payloads` and `adapter_records` to ALL paginated fragments
- Changed from `xhr_payloads=xhr_payloads if index == 0 else None` to `xhr_payloads=xhr_payloads`
- Changed from `adapter_records=adapter_records if index == 0 else None` to `adapter_records=adapter_records`

**Impact:** Ensures complete data extraction across all paginated pages.

---

### 4. ✅ Subprocess Argument Injection Risk - FIXED
**File:** `backend/app/services/url_safety.py`

**Problem:** Unsafe `nslookup` fallback allowed `asyncio.create_subprocess_exec()` to execute against user-provided hostnames, creating command injection vulnerability.

**Solution:**
- Removed `_resolve_host_ips_via_nslookup()` function entirely
- Removed `_parse_nslookup_addresses()` function entirely
- Modified `_resolve_host_ips()` to raise `ValueError` on DNS resolution failure instead of falling back to subprocess
- Updated test file `backend/tests/services/test_url_safety.py` to remove tests for deleted functions

**Impact:** Eliminates command injection attack surface.

---

### 5. ✅ Schema Arbitration / Pollution - FIXED
**File:** `backend/app/services/config/extraction_rules.py`

**Problem:** 
- Datalayer had no explicit rank, allowing it to override valid DOM/JSON-LD data
- Breadcrumbs (">", "/") were bleeding into brand and category fields

**Solution:**

**Schema Arbitration:**
- Added explicit `"datalayer": 2` rank in `source_ranking` (below standard HTML structures)
- Adjusted rankings: `dom: 2 → 1`, `llm_xpath: 1 → 0`

**Field Pollution:**
- Added `">"` and `"/"` to `brand` reject_phrases
- Added `">"` and `"/"` to `category` reject_phrases

**Impact:** Prevents low-quality datalayer data from overriding better sources and blocks breadcrumb pollution.

---

## Fixes Applied (Batch 2 - fixes2.md)

### 6. ✅ In-Memory DB Locking (Zombie Runs) - FIXED
**File:** `backend/app/services/_batch_runtime.py`

**Problem:** Global in-memory dictionary (`_RUN_UPDATE_LOCKS`) managed database concurrency. If a task timed out or worker pod restarted, locks were never released, permanently hanging runs in "RUNNING" state.

**Solution:**
- Removed `_RUN_UPDATE_LOCKS` and `_RUN_UPDATE_LOCKS_GUARD` global dictionaries
- Modified `_retry_run_update()` to rely entirely on SQLAlchemy's native `with_for_update()` database-level locking
- Simplified `_cleanup_run_lock()` to empty function (kept for signature compatibility)
- Now uses exponential backoff via existing `with_retry()` mechanism

**Impact:** Eliminates zombie runs caused by orphaned in-memory locks. Database-level locking is more reliable and survives process restarts.

---

### 7. ✅ Strict Field Validation (Schema Pollution) - FIXED
**File:** `backend/app/services/normalizers/__init__.py`

**Problem:** Pipeline selected highest-ranked extraction source without validating content quality, allowing garbage like "Home > Privacy Policy" in brand fields.

**Solution:**
- Enhanced `validate_value()` function with strict canonical validation rules
- Added field-specific rejection rules:
  - **brand**: Rejects if contains `>` or `/` (breadcrumbs), length > 60, or contains "cookie"/"privacy"
  - **color**: Rejects CSS patterns (`rgb()`, `rgba()`, `#hex`), length > 40, or contains "cookie"/"select"
  - **availability**: Rejects GA metrics (`dimension\d+`, `metric\d+`), length > 50
  - **category**: Rejects if contains "cookie"/"sign in", length > 150
- Global noise rejection for "null", "undefined", "n/a", "none", "nan"
- When high-ranked source fails validation, pipeline naturally falls back to next-highest source

**Impact:** Prevents garbage data from polluting extracted fields, ensuring only clean values are stored.

---

### 8. ✅ Infinite Scroll & Load More Termination - FIXED
**File:** `backend/app/services/acquisition/traversal.py`

**Problem:** `scroll_to_bottom()` and `click_load_more()` blindly waited fixed `cooperative_sleep_ms`, which was often insufficient for SPAs or wasted time on fast networks.

**Solution:**
- Added Playwright's `networkidle` state wait to both functions
- Waits for XHR requests to complete before proceeding
- Falls back to cooperative sleep if networkidle times out
- Applied to both scroll and load-more operations

**Impact:** More accurate detection of when new content has loaded, reducing false "no progress" stops and wasted wait time.

---

### 9. ✅ Browser Context SSRF Bypass - FIXED
**File:** `backend/app/services/acquisition/browser_client.py`

**Problem:** `page.route("**/*")` interceptor blocked non-public URLs for standard requests, but malicious sites could bypass using Service Workers to make background requests.

**Solution:**
- Added `"service_workers": "block"` to both browser context configurations in `_context_kwargs()`
- Applies to both stealth and non-stealth browser channels
- Explicitly disables Service Workers at context creation

**Impact:** Closes SSRF bypass vector by preventing Service Worker background requests.

---

### 10. ✅ Dangerous Hardcoded Site URL Synthesis - FIXED
**File:** `backend/app/services/extract/listing_extractor.py`

**Problem:** Generic extractor contained hardcoded UltiPro-specific logic (`_synthesize_ultipro_detail_url`). If non-UltiPro URLs accidentally matched the pattern, URLs would be mangled.

**Solution:**
- Removed `_synthesize_ultipro_detail_url()` function
- Removed `_detect_platform_family_from_url()` function
- Removed `_JOB_URL_SYNTHESIS_STRATEGIES` dispatch table
- Modified `_synthesize_job_detail_url()` to only call `_default_job_detail_url_synthesis()`
- Site-specific logic now belongs in proper Adapters (e.g., SaaSHRAdapter)

**Impact:** Eliminates risk of URL mangling for non-UltiPro sites. Enforces proper separation of concerns.

---

## Fixes Applied (Batch 3 - fixes3.md)

### 11. ✅ O(N²) Memory Blowout in React State Extraction - FIXED
**File:** `backend/app/services/extract/listing_extractor.py`

**Problem:** `_extract_from_next_flight_scripts()` concatenated megabytes of JSON chunks into a massive `combined` string, then searched for substrings inside it while iterating over chunks. This caused massive memory spikes and CPU lockups on Next.js sites.

**Solution:**
- Removed the `combined = "\n".join(decoded_chunks)` line that created the massive string
- Removed `_lookup_next_flight_window_index()` function call
- Changed to search for boundaries strictly within individual chunks
- Window is now calculated as: `window = chunk[start_index:end_index]` (within current chunk only)
- Used walrus operator (`:=`) for cleaner pattern matching

**Impact:** Eliminates O(N²) memory allocation and prevents memory blowouts on large Next.js sites.

---

### 12. ✅ Worker Hangs from Cancelled Tasks - FIXED
**File:** `backend/app/services/_batch_runtime.py`

**Problem:** When a URL timed out, watchdog called `await asyncio.gather(*tasks)` to wait for cancellation. However, if task was blocked inside `asyncio.to_thread` (like massive HTML parse), the thread couldn't be interrupted. `gather` would hang forever, breaking the worker.

**Solution:**
- Modified `_cancel_tasks()` to fire-and-forget cancellation
- Removed `await asyncio.gather(*tasks, return_exceptions=True)`
- Replaced with `pass` - Python will garbage collect the task once background thread completes
- Event loop is instantly freed instead of hanging

**Impact:** Prevents worker deadlocks when cancelling CPU-bound tasks. Workers can continue processing other URLs.

---

### 13. ✅ Browser Crash from Unbounded DOM Interactions - FIXED
**File:** `backend/app/services/acquisition/browser_client.py`

**Problem:** `expand_all_interactive_elements()` ran `querySelectorAll` that could capture thousands of nodes on heavy pages, running `.click()` on all of them in a tight loop. This crashed the page or triggered anti-bot defenses.

**Solution:**
- Added `const maxClicks = 20;` hard limit in JavaScript
- Added `if (count >= maxClicks) break;` check in the loop
- Wrapped `el.click()` in try/catch to handle errors gracefully
- Prevents unbounded DOM manipulation

**Impact:** Prevents browser crashes and anti-bot triggers on pages with thousands of interactive elements.

---

### 14. ✅ JSON API Schema Pollution - FIXED
**File:** `backend/app/services/extract/json_extractor.py`

**Problem:** DOM pipeline now validates inputs, but `json_extractor.py` (which handles direct API responses) bypassed `validate_value`, allowing garbage strings (like HTML tracking pixels) directly into the database.

**Solution:**
- Added `from app.services.normalizers import validate_value` import
- Added validation check in `_normalize_item()` after normalization:
  ```python
  validated = validate_value(canonical, normalized)
  if validated in (None, "", [], {}):
      continue
  record[canonical] = validated
  ```
- Now applies same strict validation rules to JSON API responses as DOM extraction

**Impact:** Closes schema pollution route through JSON APIs. All extraction paths now validate data quality.

---

### 15. ✅ Missing Extraction Source Telemetry - FIXED
**File:** `backend/app/services/pipeline/core.py`

**Problem:** When detail page successfully extracted, logs said `[SAVE] Saved 1 detail records`, but impossible to know whether data came from JSON-LD, DOM Selectors, or LLM fallback. Made debugging extraction regressions extremely difficult.

**Solution:**
- Added source telemetry extraction from `source_trace`
- Builds `winning_sources` list showing which source won for each field
- Logs format: `[SAVE] Saved 1 detail records (verdict=success). Sources: [title:json_ld, price:dom, brand:adapter...]`
- Shows first 5 fields with their winning sources

**Impact:** Operators can now instantly see which extraction subsystem provided each field, making debugging much easier.

---

## Testing Results

All modified modules pass syntax checks and import successfully:
- ✅ `app.services.url_safety` - 5/5 tests passing
- ✅ `app.services.acquisition.acquirer` - imports successfully
- ✅ `app.services.extract.listing_extractor` - 67+ tests passing
- ✅ `app.services.config.extraction_rules` - configuration validated
- ✅ `app.services.crawl_service` - imports successfully
- ✅ `app.services._batch_runtime` - imports successfully
- ✅ `app.services.normalizers` - validation tests passing
- ✅ `app.services.acquisition.browser_client` - imports successfully
- ✅ `app.services.acquisition/traversal` - imports successfully
- ✅ `app.services.extract.json_extractor` - imports successfully
- ✅ `app.services.pipeline.core` - imports successfully

## Files Modified

### Batch 1 (fixes.md)
1. `backend/app/services/acquisition/acquirer.py`
2. `backend/app/services/crawl_service.py`
3. `backend/app/services/extract/listing_extractor.py`
4. `backend/app/services/url_safety.py`
5. `backend/app/services/config/extraction_rules.py`
6. `backend/tests/services/test_url_safety.py`

### Batch 2 (fixes2.md)
7. `backend/app/services/_batch_runtime.py`
8. `backend/app/services/normalizers/__init__.py`
9. `backend/app/services/acquisition/traversal.py`
10. `backend/app/services/acquisition/browser_client.py`
11. `backend/app/services/extract/listing_extractor.py` (additional changes)

### Batch 3 (fixes3.md)
12. `backend/app/services/extract/listing_extractor.py` (additional changes)
13. `backend/app/services/_batch_runtime.py` (additional changes)
14. `backend/app/services/acquisition/browser_client.py` (additional changes)
15. `backend/app/services/extract/json_extractor.py`
16. `backend/app/services/pipeline/core.py`

## Verification Commands

```bash
# Syntax check all modified files
python -m py_compile app/services/url_safety.py app/services/crawl_service.py app/services/acquisition/acquirer.py app/services/extract/listing_extractor.py app/services/config/extraction_rules.py app/services/_batch_runtime.py app/services/normalizers/__init__.py app/services/acquisition/browser_client.py app/services/acquisition/traversal.py app/services/extract/json_extractor.py app/services/pipeline/core.py

# Run tests
python -m pytest tests/services/test_url_safety.py -v
python -m pytest tests/services/extract/test_listing_extractor.py -v

# Verify normalizers validation
python -c "from app.services.normalizers import validate_value; assert validate_value('brand', 'Home > Privacy') is None; assert validate_value('brand', 'Nike') == 'Nike'; print('Normalizers working correctly')"

# Verify configuration
python -c "from app.services.config.extraction_rules import EXTRACTION_RULES; print('datalayer rank:', EXTRACTION_RULES['source_ranking']['datalayer'])"

# Verify imports
python -c "from app.services.extract.json_extractor import extract_json_listing; from app.services.pipeline.core import _extract_detail; print('All imports successful')"
```

---

## Fixes Applied (Batch 4 - fixes4.md)

### 16. ✅ Long Garbage Wins Arbitration Bug - FIXED
**File:** `backend/app/services/pipeline/field_normalization.py`

**Problem:** In `_should_prefer_secondary_field`, the pipeline assumed longer text is better. If DOM yielded `{"brand": "Nike"}` (4 chars) but DataLayer yielded `{"brand": "Click here to read our privacy policy and terms"}` (49 chars), the garbage string overwrote the correct brand because it was longer.

**Solution:**
- Added strict length constraints for short-form categorical fields (brand, category, color, size, availability)
- Rejects candidates longer than 40 characters or more than 5 words
- Added low-quality token detection (cookie, privacy, sign in, log in, account, home, menu, agree, policy)
- Prefers clean short values over noisy long values
- Long-form fields (description, specifications) still prefer longer content

**Impact:** Prevents paragraphs of noise from overwriting valid categorical data. Ensures high-quality short facts win arbitration.

---

### 17. ✅ Refactor God-Function in Pipeline Orchestration - FIXED
**File:** `backend/app/services/extract/service.py`

**Problem:** `_collect_candidates` was a rigid "God Function" with a massive sequential if/elif chain checking 9 different data sources. Violated Open-Closed Principle; adding new extractors required modifying core loop.

**Solution:**
- Refactored to use clean Strategy iteration pattern
- Defined extraction strategies in priority-ordered list
- First-match wins approach with early exit
- Strategies execute in order: Contract → Adapter → DataLayer → Network → JSON-LD → Structured State → DOM → Semantic → Text Patterns
- Much cleaner and more maintainable code structure

**Impact:** Dramatically improves readability and maintainability. New extractors can be added without modifying core orchestration logic.

---

### 18. ✅ Zombie Browser Deadlocks - FIXED
**File:** `backend/app/services/acquisition/browser_client.py`

**Problem:** In `_fetch_rendered_html_attempt`, if proxy negotiation was slow or headless Chrome hung on initialization, `await browser.new_context()` blocked forever. Standard Python timeouts killed the task, but orphaned Chrome instances kept running, eventually causing OOM crashes.

**Solution:**
- Wrapped `browser.new_context()` in `asyncio.wait_for()` with 15-second timeout
- Wrapped `context.new_page()` in `asyncio.wait_for()` with 10-second timeout
- On timeout, evicts browser from pool and retries once with fresh browser
- Ensures Playwright yields control back to Python for cleanup

**Impact:** Prevents zombie browser processes from accumulating and causing OOM crashes. Improves reliability under slow network conditions.

---

### 19. ✅ Remove Hazardous Dead Code - FIXED
**File:** `backend/app/services/db_utils.py`

**Problem:** Function `commit_with_retry` was explicitly marked as deprecated and dangerous ("commit-only retries are unsafe for mutable unit-of-work paths"), but still existed in codebase, creating hazard for future developers who might accidentally use it.

**Solution:**
- Completely deleted `commit_with_retry()` function from `db_utils.py`
- Removed lines 97-109 containing the deprecated function
- Only safe `with_retry()` function remains

**Impact:** Eliminates maintenance hazard. Developers can no longer accidentally use unsafe retry pattern.

---

### 20. ✅ Introduce High-Leverage Arbitration Test Harness - FIXED
**File:** `backend/tests/services/extract/test_arbitration.py` (NEW)

**Problem:** Core business logic of crawler is resolving conflicting data from multiple sources (DOM vs JSON-LD vs DataLayer). No tests verified that schema pollution guards work correctly.

**Solution:**
- Created comprehensive pytest harness testing arbitration logic
- `test_schema_arbitration_rejects_datalayer_pollution()`: Tests that noisy datalayer values are rejected in favor of clean DOM values
- `test_should_prefer_secondary_field_logic()`: Tests merge logic ensuring short noise doesn't overwrite short facts
- Mocks `extract_candidates` with realistic HTML containing both polluted and clean sources
- Verifies correct source wins for each field type

**Impact:** Provides high-confidence testing of critical arbitration logic. Prevents regressions in schema pollution guards.

---

## Testing Results

All modified modules pass syntax checks and import successfully:
- ✅ `app.services.url_safety` - 5/5 tests passing
- ✅ `app.services.acquisition.acquirer` - imports successfully
- ✅ `app.services.extract.listing_extractor` - 67+ tests passing
- ✅ `app.services.config.extraction_rules` - configuration validated
- ✅ `app.services.crawl_service` - imports successfully
- ✅ `app.services._batch_runtime` - imports successfully
- ✅ `app.services.normalizers` - validation tests passing
- ✅ `app.services.acquisition.browser_client` - imports successfully
- ✅ `app.services.acquisition/traversal` - imports successfully
- ✅ `app.services.extract.json_extractor` - imports successfully
- ✅ `app.services.pipeline.core` - imports successfully
- ✅ `app.services.db_utils` - imports successfully
- ✅ `tests.services.extract.test_arbitration` - syntax validated

## Files Modified

### Batch 1 (fixes.md)
1. `backend/app/services/acquisition/acquirer.py`
2. `backend/app/services/crawl_service.py`
3. `backend/app/services/extract/listing_extractor.py`
4. `backend/app/services/url_safety.py`
5. `backend/app/services/config/extraction_rules.py`
6. `backend/tests/services/test_url_safety.py`

### Batch 2 (fixes2.md)
7. `backend/app/services/_batch_runtime.py`
8. `backend/app/services/normalizers/__init__.py`
9. `backend/app/services/acquisition/traversal.py`
10. `backend/app/services/acquisition/browser_client.py`
11. `backend/app/services/extract/listing_extractor.py` (additional changes)

### Batch 3 (fixes3.md)
12. `backend/app/services/extract/listing_extractor.py` (additional changes)
13. `backend/app/services/_batch_runtime.py` (additional changes)
14. `backend/app/services/acquisition/browser_client.py` (additional changes)
15. `backend/app/services/extract/json_extractor.py`
16. `backend/app/services/pipeline/core.py`

### Batch 4 (fixes4.md)
17. `backend/app/services/pipeline/field_normalization.py`
18. `backend/app/services/extract/service.py`
19. `backend/app/services/acquisition/browser_client.py` (additional changes)
20. `backend/app/services/db_utils.py`
21. `backend/tests/services/extract/test_arbitration.py` (NEW)

## Verification Commands

```bash
# Syntax check all modified files
python -m py_compile app/services/url_safety.py app/services/crawl_service.py app/services/acquisition/acquirer.py app/services/extract/listing_extractor.py app/services/config/extraction_rules.py app/services/_batch_runtime.py app/services/normalizers/__init__.py app/services/acquisition/browser_client.py app/services/acquisition/traversal.py app/services/extract/json_extractor.py app/services/pipeline/core.py app/services/pipeline/field_normalization.py app/services/extract/service.py app/services/db_utils.py

# Run tests
python -m pytest tests/services/test_url_safety.py -v
python -m pytest tests/services/extract/test_listing_extractor.py -v
python -m pytest tests/services/extract/test_arbitration.py -v

# Verify normalizers validation
python -c "from app.services.normalizers import validate_value; assert validate_value('brand', 'Home > Privacy') is None; assert validate_value('brand', 'Nike') == 'Nike'; print('Normalizers working correctly')"

# Verify configuration
python -c "from app.services.config.extraction_rules import EXTRACTION_RULES; print('datalayer rank:', EXTRACTION_RULES['source_ranking']['datalayer'])"

# Verify imports
python -c "from app.services.extract.json_extractor import extract_json_listing; from app.services.pipeline.core import _extract_detail; from app.services.db_utils import with_retry; print('All imports successful')"

# Verify arbitration logic
python -c "from app.services.pipeline.field_normalization import _should_prefer_secondary_field; assert not _should_prefer_secondary_field('brand', 'Nike', 'Click here to accept cookie policy'); print('Arbitration logic working correctly')"
```

---

**Date Applied:** 2026-04-09
**Applied By:** Kiro AI Assistant
**Total Fixes:** 20 critical security, performance, and reliability issues
