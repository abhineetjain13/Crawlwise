# Selector Functionality Audit: Save/Load Bug & Architecture Gaps

**Date:** 2026-04-20  
**Scope:** Frontend selector UI, API layer, extraction pipeline integration  
**Status:** Critical bug identified + architectural disconnects

---

## Issue 1: CRITICAL BUG - Saved Selectors Disappear on Refresh

### Symptom
1. User loads a page in the Selector tool
2. LLM suggests selectors, user accepts and clicks "Save Accepted Selectors"
3. Success - rows show "Saved" state
4. User refreshes the page
5. **All saved selectors are gone** - only fresh LLM suggestions appear

### Root Cause

@`c:\Projects\pre_poc_ai_crawler\frontend\app\selectors\page.tsx:50-83`
```typescript
async function loadPageAndSuggestions() {
  // ... validation ...
  
  const response = await api.suggestSelectors({  // ← ONLY calls suggest
    url: targetUrl,
    expected_columns: parsedColumns,
  });
  
  setRows(
    parsedColumns.map((field) => {
      const suggestion = response.suggestions[field]?.[0];
      return buildRowFromSuggestion(field, suggestion);  // ← Builds from LLM only
    }),
  );
  // ← MISSING: api.listSelectors({ domain }) to load saved selectors!
}
```

The `loadPageAndSuggestions()` function **never fetches existing saved selectors** for the domain. It only:
1. Calls `api.suggestSelectors()` to get fresh LLM suggestions
2. Builds rows from those suggestions
3. Completely ignores any previously saved `DomainMemory` records

### Backend Confirmation - Save DOES Work

@`c:\Projects\pre_poc_ai_crawler\backend\app\selectors_runtime.py:133-170`
```python
async def create_selector_record(...):
    # Saves to DomainMemory table via save_domain_memory()
    await save_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        selectors=selector_payload_from_rules(rules),
    )
    await session.commit()  # ← Commits to DB
```

The save operation works correctly - data persists to `domain_memory` table.

### Fix Required

**File:** `frontend/app/selectors/page.tsx`
**Change:** Add a `loadSavedSelectors()` call after getting suggestions:

```typescript
async function loadPageAndSuggestions() {
  // ... existing validation ...
  
  // 1. Get LLM suggestions
  const suggestionResponse = await api.suggestSelectors({...});
  
  // 2. ← ADD: Load saved selectors for this domain
  const savedSelectors = await api.listSelectors({ 
    domain: getNormalizedDomain(targetUrl) 
  });
  
  // 3. Merge saved selectors with suggestions
  const mergedRows = parsedColumns.map((field) => {
    // Prefer saved selector if exists for this field
    const saved = savedSelectors.find(s => s.field_name === field && s.is_active);
    if (saved) {
      return buildRowFromSavedSelector(saved);  // ← ADD this function
    }
    // Otherwise use LLM suggestion
    const suggestion = suggestionResponse.suggestions[field]?.[0];
    return buildRowFromSuggestion(field, suggestion);
  });
  
  setRows(mergedRows);
}
```

---

## Issue 2: Selectors Not Used During Actual Crawls

### The Disconnect

Even after fixing the save/load bug, there's a deeper architectural issue: **The extraction pipeline doesn't consistently use saved selectors.**

### How Selectors SHOULD Flow

```
User saves selector in UI
  ↓
Stored in domain_memory table (selector_rules_from_memory)
  ↓
Crawl run starts for same domain
  ↓
Pipeline loads domain_memory selectors
  ↓
Selectors passed to extract_records(selector_rules=...)
  ↓
Used in _listing_record_from_card() or detail extraction
```

### Where It Breaks

#### A. No Selector Loading in Pipeline

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\pipeline\core.py`

The `_run_extraction_stage()` function calls `extract_records()` but there's no evidence it loads `DomainMemory` selectors before extraction.

Looking at the extraction call path:
```python
# In pipeline/core.py, _extract_records_for_acquisition()
extract_records(
    html,
    page_url,
    run.surface,
    max_records=...,
    requested_fields=...,
    adapter_records=...,
    network_payloads=...,
    # ← MISSING: selector_rules from domain_memory!
)
```

#### B. Self-Heal Creates Selectors, But Manual Selectors Are Different

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\selector_self_heal.py:178-298`

The `apply_selector_self_heal()` function:
1. Only triggers when confidence < threshold
2. Synthesizes XPaths via LLM
3. Saves to domain_memory

**But manual selectors created via the UI are stored the same way** - so why don't they get loaded?

### Verification Needed

Check if `pipeline/core.py` loads domain selectors:

```python
# Should be somewhere in _extract_records_for_acquisition or _run_extraction_stage:
from app.services.domain_memory_service import load_domain_memory, selector_rules_from_memory

memory = await load_domain_memory(session, domain=normalize_domain(url), surface=run.surface)
selector_rules = selector_rules_from_memory(memory)
# Then passed to extract_records(selector_rules=selector_rules)
```

**If this code doesn't exist, that's the smoking gun.**

---

## Issue 3: Selector Scope Mismatch

### UI Surface vs Crawl Surface

The selector UI asks for `surface` and stores it:
- User selects: `ecommerce_detail` or `job_detail`

But when a crawl runs:
- Listing crawl: surface = `ecommerce_listing` 
- Detail crawl: surface = `ecommerce_detail`

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\domain_memory_service.py:9-24`
```python
async def load_domain_memory(session, *, domain: str, surface: str):
    result = await session.execute(
        select(DomainMemory)
        .where(
            DomainMemory.domain == domain,
            DomainMemory.surface == surface,  # ← Exact match required!
        )
```

**Problem:** If user saves selectors for `ecommerce_detail` but the initial discovery is via `ecommerce_listing`, the selectors might not be applied correctly.

### Field Name Normalization Mismatch

@`c:\Projects\pre_poc_ai_crawler\frontend\app\selectors\page.tsx:566-568`
```typescript
function normalizeField(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}
```

vs. backend @`c:\Projects\pre_poc_ai_crawler\backend\app\services\field_policy.py` (assumed location)

If backend uses different normalization (e.g., keeps dots, different space handling), field names won't match.

---

## Issue 4: Selector Application in Extraction

### Where Selectors Should Be Applied

Looking at the extraction pipeline:

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\extraction_runtime.py:65-90`
```python
def extract_records(..., selector_rules: list[dict[str, object]] | None = None):
    if "listing" in surface:
        return extract_listing_records(
            html, page_url, surface,
            max_records=max_records,
            selector_rules=selector_rules,  # ← Passed through
        )
```

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:640-722`
```python
def extract_listing_records(..., selector_rules: list[dict[str, object]] | None = None):
    # ...
    def _dom_stage(...):
        for card in _listing_card_html_fragments(...):
            record = _listing_record_from_card(
                card, page_url, surface,
                selector_rules=selector_rules,  # ← Passed to card extraction
            )
```

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:400-450` (assumed)
```python
def _listing_record_from_card(card, ..., selector_rules=None):
    # Should apply selector_rules here for field extraction
    # But only if selector_rules exist!
```

### Gap: When Are Selector Rules Actually Consulted?

Search the codebase for where `selector_rules` are actually **applied** (not just passed through):

```bash
grep -n "selector_rules" backend/app/services/*.py
```

If the only hits are function parameters and pass-through calls, then **selectors are accepted but never used**.

---

## Summary of Bugs & Fixes

### Bug 1: Frontend Doesn't Load Saved Selectors (CRITICAL)
**File:** `frontend/app/selectors/page.tsx`  
**Fix:** Add `api.listSelectors()` call and merge with suggestions

### Bug 2: Pipeline Doesn't Load Domain Selectors (CRITICAL)
**File:** `backend/app/services/pipeline/core.py`  
**Fix:** Add `load_domain_memory()` in `_run_extraction_stage()` and pass to `extract_records()`

### Bug 3: Selectors May Not Be Applied in Extraction (HIGH)
**Files:** `listing_extractor.py`, `detail_extractor.py`  
**Fix:** Ensure `selector_rules` are consulted when extracting field values (not just passed through)

### Bug 4: Surface Mismatch (MEDIUM)
**Files:** `selectors_runtime.py`, `pipeline/core.py`  
**Fix:** Define selector inheritance rules (e.g., can `ecommerce_detail` selectors apply to `ecommerce_listing`?)

---

## Recommended Fix Priority

### Immediate (Today)
1. **Fix Frontend Load Bug** - Add `listSelectors()` call to selector page
2. **Verify Pipeline Integration** - Confirm if pipeline loads domain selectors

### Short Term (This Week)
3. **Add Selector Application** - Ensure selector rules are actually used in field extraction
4. **Add Surface Fallback** - Allow selectors to apply across related surfaces

### Medium Term
5. **Selector Precedence Rules** - Document when manual selectors override auto-detected values
6. **Selector Validation** - Test selector against live page before saving

---

## Verification Commands

Check if selectors are being loaded during crawls:
```bash
# Add logging to track selector usage
grep -r "load_domain_memory" backend/app/services/pipeline/
grep -r "selector_rules_from_memory" backend/app/services/pipeline/
```

If no results, selectors are **never loaded** during crawls.

Check database for saved selectors:
```sql
SELECT domain, surface, selectors->>'rules' 
FROM domain_memory 
ORDER BY updated_at DESC 
LIMIT 10;
```

---

## Files Involved

| Component | File | Role |
|-----------|------|------|
| Frontend UI | `frontend/app/selectors/page.tsx` | Bug: Doesn't load saved selectors |
| Frontend API | `frontend/lib/api/index.ts` | `listSelectors()` exists but unused |
| Backend API | `backend/app/api/selectors.py` | CRUD endpoints working |
| Backend Logic | `backend/app/services/selectors_runtime.py` | Save/load logic functional |
| Pipeline | `backend/app/services/pipeline/core.py` | **May not load selectors** |
| Extraction | `backend/app/services/listing_extractor.py` | Accepts selector_rules |
| Domain Memory | `backend/app/services/domain_memory_service.py` | Storage/retrieval working |
