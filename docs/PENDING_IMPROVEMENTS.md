# Pending Improvements

Consolidated from architecture reviews (arch_review.md, arch_review2.md) and frontend audit (FRONTEND_AUDIT_REPORT.md). Items already implemented are not listed.

---

## Backend — High Priority

### 1. Brittle Absolute XPath Generation
**File:** `app/services/xpath_service.py` — `build_absolute_xpath`  
**Issue:** Generates paths like `/html/body/div[1]/main/section/div[3]` which break on any layout change. These pollute selector memory with brittle rules.  
**Fix:** Switch to relative, semantic XPaths based on attributes (e.g. `//div[@id='main-content']//span[@class='price']`). Use closest semantic anchors and unique attribute ranking.  
**Effort:** ~3 days  
**Why deferred:** Requires a new algorithm with heuristic attribute ranking. Current absolute XPaths are a fallback-of-last-resort and don't block extraction.

### 2. LLM HTTP Client Deduplication
**File:** `app/services/llm_runtime.py`  
**Issue:** Four near-identical httpx POST implementations for OpenAI, Groq, Anthropic, and Nvidia. Updating retry/proxy/timeout logic requires touching all four.  
**Fix:** Extract a generic `_execute_llm_request(url, headers, payload, provider)`. Provider-specific functions only build headers and payload formatting.  
**Effort:** ~1 day  
**Why deferred:** LLM integration is config-only today. No active LLM calls in the deterministic pipeline.

### 3. Unbounded Artifact Storage
**File:** `app/services/acquisition/acquirer.py`  
**Issue:** HTML, JSON, and network payload artifacts are written to disk for every crawl with no TTL or pruning. Disk fills up over time.  
**Fix:** Background task to prune artifacts older than N days, or move to S3-compatible object store with lifecycle policies.  
**Effort:** ~2 days  
**Why deferred:** POC-scale. Not a concern until hundreds of crawls per day.

### 4. SQLite Concurrency Limits
**File:** `app/core/database.py`  
**Issue:** SQLite WAL mode will eventually hit `database locked` under high concurrency. The PRAGMA settings help but don't fully solve it.  
**Fix:** Add PostgreSQL connection string support and migration path. Keep SQLite as default for dev/POC.  
**Effort:** ~2 days  
**Why deferred:** Current usage is single-user POC. SQLite is fine for development.

### 5. Pagination Implementation
**File:** `app/services/acquisition/browser_client.py`  
**Issue:** `advanced_mode == "paginate"` returns only the first page. The browser client has scroll and load-more modes working but no actual multi-page navigation.  
**Fix:** Implement next-page link detection, page boundary tracking, and multi-page HTML collection.  
**Effort:** ~3 days  
**Why deferred:** Core extraction works on first-page content. Pagination is a feature enhancement, not a bug.

---

## Backend — Medium Priority

### 6. Magic Numbers in Pipeline Code
**Files:** `crawl_service.py`, `llm_runtime.py`  
**Issue:** Some confidence thresholds (`0.78`, `0.7`) and LLM params (`max_tokens: 1200`, `temperature: 0.1`) are still inline.  
**Fix:** Move to `pipeline_tuning.json` and load via `pipeline_config.py`.  
**Effort:** ~1 day

### 7. Bare Exception Catches in Browser Actions
**File:** `app/services/acquisition/browser_client.py`  
**Issue:** `_dismiss_cookie_consent` and `_scroll_to_bottom` catch `Exception` broadly. Could mask memory leaks or timeout errors.  
**Fix:** Catch `PlaywrightTimeoutError` and `PlaywrightError` specifically. Log and re-raise unexpected exceptions.  
**Effort:** ~0.5 day  
**Note:** Current broad catches are intentional for robustness — cookie consent failure should never abort a crawl.

### 8. Adapter Boilerplate Deduplication
**Files:** `app/services/adapters/*.py`  
**Issue:** All adapters duplicate `soup = BeautifulSoup(html, "html.parser")` and `if surface == X` routing.  
**Fix:** Move HTML parsing and surface routing into `BaseAdapter.extract()`. Subclasses implement `_extract_detail()` and `_extract_listing()` only.  
**Effort:** ~1 day

---

## Frontend — High Priority

### 9. Focus Trap in Preview Modal
**File:** `frontend/app/crawl/page.tsx`  
**Issue:** Preview modal doesn't trap keyboard focus. Users can tab to elements behind the modal.  
**Fix:** Use Radix Dialog component (already in dependencies) or `focus-trap-react`. Ensure Escape closes modal and focus returns to trigger.  
**Effort:** ~4 hours

### 10. Color Contrast Testing
**File:** `frontend/app/globals.css`  
**Issue:** Muted text colors (`--text-muted`) may not meet WCAG 4.5:1 contrast ratio in both light and dark themes.  
**Fix:** Test with WebAIM Contrast Checker. Adjust muted text if needed.  
**Effort:** ~3 hours

### 11. Live Region Announcements for Screen Readers
**File:** `frontend/app/crawl/page.tsx`  
**Issue:** Live log updates are not announced to screen readers.  
**Fix:** Add `aria-live="polite"` and `role="log"` to log container.  
**Effort:** ~1 hour

---

## Frontend — Medium Priority

### 12. Large Component File Split
**File:** `frontend/app/crawl/page.tsx` (~1200+ lines)  
**Issue:** Single file handles config phase, running phase, complete phase, form state, API calls, and polling.  
**Fix:** Split into `components/config-phase.tsx`, `running-phase.tsx`, `complete-phase.tsx`, `hooks/use-crawl-state.ts`.  
**Effort:** ~8 hours

### 13. Heading Hierarchy
**File:** `frontend/components/layout/app-shell.tsx`  
**Issue:** Page title renders as `<div>` instead of `<h1>`. `SectionHeader` uses `<h2>` but there's no `<h1>` on the page.  
**Fix:** Change page title element to `<h1>` in app-shell.  
**Effort:** ~1 hour

### 14. Skip Navigation Link
**File:** `frontend/components/layout/app-shell.tsx`  
**Issue:** No "Skip to main content" link for keyboard users.  
**Fix:** Add visually-hidden skip link at top of layout.  
**Effort:** ~30 minutes

---

## Long-term / Backlog

- Add Lever ATS adapter
- Expand `try_blocked_adapter_recovery()` to additional platforms beyond Shopify
- Add runtime type validation with Zod for API responses in frontend
- Implement actual sitemap XML parsing for category crawls
- Plan migration from SQLite to PostgreSQL for production scale
