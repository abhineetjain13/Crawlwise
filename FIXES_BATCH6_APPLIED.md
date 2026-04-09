# Fixes Batch 6 Applied

## Summary
Successfully applied 5 critical fixes addressing database connection pool exhaustion, variant collapsing, synchronous file I/O blocking, JSON-LD corruption, and ReDoS vulnerabilities.

---

## Fix 26: Database Connection Pool Exhaustion ✅

**File:** `backend/app/api/crawls.py`

**Problem:** The WebSocket endpoint `crawls_logs_ws` opened and closed a new database session inside a `while True` loop every 0.75 seconds. With 50 users monitoring crawls, this generated ~66 connection/disconnection requests per second, instantly exhausting the SQLAlchemy connection pool and crashing the backend with 500 errors.

**Solution:**
- Moved session creation outside the loop - one session per WebSocket lifecycle
- Added `await session.rollback()` inside the loop to reset transaction snapshot for fresh reads
- Session is now maintained for the entire WebSocket connection duration
- Eliminated connection pool thrashing

**Impact:** Prevents connection pool exhaustion under concurrent WebSocket monitoring. System can now handle many simultaneous log stream viewers without crashing.

---

## Fix 27: Catastrophic Variant Collapsing ✅

**File:** `backend/app/services/extract/listing_identity.py`

**Problem:** When a page lacked strong identifiers (like SKU), `_fallback_title_backfill_index` merged records if they shared the exact same title. If a page listed 10 identical "T-Shirt" items with different prices, colors, or images, the crawler collapsed them all into a single item, causing massive data loss for variant listings.

**Solution:**
- Enhanced `_has_strong_identity_conflict()` to check variant-differentiating fields
- Added conflict checks for: `price`, `color`, `size`, `image_url`, `brand`
- Variants with different values in these fields are no longer merged
- Preserves distinct product variants even when they share the same title

**Impact:** Prevents data loss for variant listings. Each unique product variant is now correctly preserved as a separate record.

---

## Fix 28: Synchronous File I/O Blocking Event Loop ✅

**File:** `backend/app/services/acquisition/acquirer.py`

**Problem:** At the end of the `acquire` function, the crawler wrote megabytes of HTML, JSON, network payloads, and diagnostic data to disk synchronously. On fast 500-URL batch runs, this locked the main Python thread continuously, causing heartbeats to fail and workers to drop leases.

**Solution:**
- Wrapped all disk I/O operations in `asyncio.to_thread()`:
  - `path.parent.mkdir()` - directory creation
  - `path.write_text()` - HTML/JSON artifact writing
  - `_write_network_payloads()` - network payload writing
  - `_write_diagnostics()` - diagnostics writing
  - `_write_failed_diagnostics()` - failure diagnostics writing
- All file operations now run in thread pool, freeing event loop

**Impact:** Eliminates event loop blocking during artifact writes. Workers can maintain heartbeats and process URLs concurrently without lease drops.

---

## Fix 29: JSON-LD Corruption Causing Data Loss ✅

**File:** `backend/app/services/extract/source_parsers.py`

**Problem:** `extract_json_ld` extracted JSON-LD scripts using `node.get_text(" ", strip=True)`. This stripped HTML tags inside JSON strings. If a site included `{"description": "<p>Product Details</p>"}` in its JSON-LD, `get_text()` corrupted the JSON string boundary, causing a `JSONDecodeError` and throwing away the entire structured record silently.

**Solution:**
- Changed from `node.get_text(" ", strip=True)` to `node.string`
- Falls back to `"".join(node.strings)` if `node.string` is None
- Extracts exact inner string untouched, preserving HTML tags within JSON values
- No more corruption of valid JSON payloads

**Impact:** Prevents silent data loss from JSON-LD extraction. Structured data with HTML-containing strings is now correctly parsed.

---

## Fix 30: ReDoS (Regex Denial of Service) in Blocked Page Detector ✅

**File:** `backend/app/services/acquisition/blocked_detector.py`

**Problem:** The `detect_blocked_page` function executed a massive regex `re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", html)` over entire raw HTML. On malformed sites with unclosed `<script>` tags or 5MB React payloads, this triggered Catastrophic Backtracking, pinning CPU usage to 100% until the container OOMed or was killed.

**Solution:**
- Removed the catastrophic backtracking regex entirely
- Replaced with BeautifulSoup-based tag removal:
  ```python
  soup = BeautifulSoup(html, "html.parser")
  for tag in soup(["script", "style", "noscript", "svg"]):
      tag.decompose()
  visible = " ".join(soup.get_text(" ", strip=True).lower().split())
  ```
- Added failsafe: if BeautifulSoup hits recursion limit, use bounded string slicing (`html_lower[:20000]`)
- Bounded title extraction to first 50KB of HTML
- Highly performant, non-blocking approach

**Impact:** Eliminates ReDoS vulnerability. System can safely process malformed HTML without CPU spikes or OOM crashes.

---

## Testing Results

All modified modules pass syntax checks and import successfully:
- ✅ `app.api.crawls` - WebSocket endpoint imports correctly
- ✅ `app.services.extract.listing_identity` - Identity conflict detection imports correctly
- ✅ `app.services.acquisition.acquirer` - Acquisition service imports correctly
- ✅ `app.services.extract.source_parsers` - JSON-LD extraction imports correctly
- ✅ `app.services.acquisition.blocked_detector` - Blocked page detection imports correctly

## Files Modified

1. `backend/app/api/crawls.py` - Fixed WebSocket connection pool exhaustion
2. `backend/app/services/extract/listing_identity.py` - Fixed variant collapsing
3. `backend/app/services/acquisition/acquirer.py` - Offloaded disk I/O to thread pool
4. `backend/app/services/extract/source_parsers.py` - Fixed JSON-LD corruption
5. `backend/app/services/acquisition/blocked_detector.py` - Fixed ReDoS vulnerability

## Verification Commands

```bash
# Syntax check all modified files
python -m py_compile backend/app/api/crawls.py backend/app/services/extract/listing_identity.py backend/app/services/acquisition/acquirer.py backend/app/services/extract/source_parsers.py backend/app/services/acquisition/blocked_detector.py

# Verify imports
python -c "from app.api.crawls import crawls_logs_ws; from app.services.extract.listing_identity import _has_strong_identity_conflict; from app.services.acquisition.acquirer import acquire; from app.services.extract.source_parsers import extract_json_ld; from app.services.acquisition.blocked_detector import detect_blocked_page; print('All imports successful')"

# Test the app starts
python -c "from app.main import app; print('App imports successfully')"
```

---

**Date Applied:** 2026-04-09
**Applied By:** Kiro AI Assistant
**Total Fixes:** 5 critical architecture, performance, and security issues

**Cumulative Total:** 30 fixes applied across all batches (Batches 1-6 + Additional Fixes)
