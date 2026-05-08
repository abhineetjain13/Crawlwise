# Crawlwise — Surface Inference & Auto-Traversal Refactor Audit

**Scope:** Two audit domains —
1. **Detail vs. Listing inference** — does the system re-infer the extraction surface after the user has already selected one from the UI?
2. **Auto-traversal mode** — previously identified for removal.

All findings reference actual code at commit `5e625c8`.

---

## Part 1 — Does Detail/Listing Inference Actually Exist?

**Short answer: Yes. It exists in two forms — one legitimate, one bloated.**

The surface string (e.g. `"ecommerce_listing"`, `"ecommerce_detail"`) is passed down from the UI → API route → `crawl_service.py` → `extract_records()` in `extraction_runtime.py`. At that point the system _knows_ the surface. The correct behavior would be: `"listing" in surface` → listing path, else → detail path. That is mostly what happens. However, there are **three internal places where the code re-infers or second-guesses the surface** after it has already been received.

---

## Part 2 — Confirmed Inference Bloat Sites

### Site 1 — `extraction_context.py` `_json_ld_listing_confident()`

**File:** `backend/app/services/extraction_context.py`
**Lines:** `_json_ld_listing_confident()`, `collect_structured_source_payloads()`

```python
def _json_ld_listing_confident(payloads: list[dict[str, Any]]) -> bool:
    listing_like = 0
    for payload in payloads:
        if _looks_like_listing_payload(payload):
            listing_like += 1
        if _payload_has_item_list(payload):
            return True
    return listing_like >= max(3, int(crawler_runtime_settings.listing_min_items))
```

**What it does:** Looks at the raw JSON-LD on the page and decides for itself whether this is a "listing" page. If it decides yes, it skips calling `parse_microdata()` and `parse_opengraph()` as fallbacks.

**Why it's wrong:** `collect_structured_source_payloads()` receives no `surface` argument at all. It can't know the user's intent. It re-infers listing-ness purely from DOM signals — **completely ignoring the UI-selected surface.** If a user selects `ecommerce_detail` on a page that happens to have `ItemList` JSON-LD, this function will decide "this looks like a listing" and suppress microdata/opengraph — which are exactly the sources the detail extractor needs.

**Verdict: Inference bloat — partially safe to remove, partially needs surgical fix.**

---

### Site 2 — `extraction_runtime.py` `_has_surface_field_overlap()` + `_raw_json_items()`

**File:** `backend/app/services/extraction_runtime.py`
**Lines:** `_has_surface_field_overlap()`, `_raw_json_items()`

```python
def _has_surface_field_overlap(items: list[object], *, surface: str) -> bool:
    canonical = set(canonical_fields_for_surface(surface))
    ...
    ratio = matching / len(dict_items) if dict_items else 0
    return (
        ratio >= crawler_runtime_settings.raw_json_surface_field_overlap_ratio
        and matching >= crawler_runtime_settings.raw_json_surface_field_overlap_absolute
    )
```

```python
def _raw_json_items(payload: object, *, surface: str) -> list[object]:
    is_listing_surface = "listing" in str(surface or "").lower()
    if isinstance(payload, list):
        if is_listing_surface and not _has_surface_field_overlap(payload, surface=surface):
            return []          # <--- silently kills records
        return list(payload)
```

**What it does:** Even after the surface is passed in, `_raw_json_items()` runs a field-overlap check. If the raw JSON response fields don't look "listing-like enough" (by ratio threshold from `runtime_settings`), it returns an empty list — discarding all records silently.

**Why it's wrong:** The user selected listing surface. The system found a JSON array. But it then second-guesses whether those JSON fields look like a listing and silently drops them. This means: user says "give me listing data", system finds data, then throws it away because the JSON keys don't match an expected vocabulary. The user gets zero records with no error — the worst kind of failure.

The same gating applies in `_best_nested_listing_items()`:
```python
if surface and not _has_surface_field_overlap(payload, surface=surface):
    score = 0
```
A nested list that doesn't match the expected field vocabulary gets score=0 and is ignored, even when it's the only data available.

**Verdict: Inference bloat — this check is wrong in its current form. The surface is already known; a field-overlap gate should be a warning/metric, not a silent discard.**

---

### Site 3 — `extraction_context.py` `collect_structured_source_payloads()` skipping fallback sources

**File:** `backend/app/services/extraction_context.py`
**Lines:** `collect_structured_source_payloads()`

```python
skip_extruct_fallbacks = _json_ld_listing_confident(json_ld_payloads)
...
(
    "microdata",
    [] if skip_extruct_fallbacks else _dict_payloads(parse_microdata(...)),
),
(
    "opengraph",
    [] if skip_extruct_fallbacks else _dict_payloads(parse_opengraph(...)),
),
```

**What it does:** If `_json_ld_listing_confident()` returns True, microdata and opengraph are entirely skipped. The `collect_structured_source_payloads()` function is called from both listing and detail extraction paths. When called for a `detail` surface page that happens to have `ItemList` JSON-LD, microdata/opengraph — which may contain the single-product structured data — are silently discarded.

**Verdict: Real bug. Conditional source suppression must be surface-aware.**

---

### Site 4 — `extraction_runtime.py` `extract_records()` raw JSON detail bypass

**File:** `backend/app/services/extraction_runtime.py`
**Lines:** `extract_records()` ~L80

```python
json_records = _extract_raw_json_records(...)
if json_records:
    if "listing" in surface:
        return json_records
    return _postprocess_detail_records(
        json_records[:max_records], ...
    )
```

**What it does:** If raw JSON records are found and the surface is NOT listing, it routes them to `_postprocess_detail_records()`. This is _correct_ logic — it respects the user surface. **No inference issue here.** However, `_postprocess_detail_records()` unconditionally calls `repair_ecommerce_detail_record_quality()` regardless of whether the surface is actually `ecommerce_detail` vs. `job_detail` vs. `real_estate_detail`. Minor cross-surface contamination, but low priority.

**Verdict: Correct surface routing, minor surface-specific repair contamination — low priority.**

---

### Site 5 — `detail_identity.py` `listing_detail_like_path()` used as a listing filter

**File:** `backend/app/services/extract/detail_identity.py`
**Called from:** `extraction_runtime.py` `extract_records()` via `best_listing_candidate_set()`

```python
detail_like_url=lambda candidate_url: listing_detail_like_path(
    candidate_url,
    is_job=str(surface or "").startswith("job_"),
),
```

**What it does:** During listing candidate ranking, this lambda checks each candidate URL to see if it _looks like a detail URL_ (e.g., has a product slug). This is **legitimate inference** — it's used as a quality signal to rank and deduplicate listing candidates, not to override the user-selected surface.

**Verdict: Legitimate — keep as is.**

---

## Part 3 — Inference That Is Legitimately Needed

Not all inference should be removed. The following is **correct architecture**:

| Inference location | What it does | Keep? |
|---|---|---|
| `extract_records()` top-level `if "listing" in surface` | Routes to listing vs. detail path | ✅ Keep — this IS the surface dispatch |
| `listing_detail_like_path()` in candidate ranking | Quality signal to filter junk URLs from listing results | ✅ Keep |
| `_listing_items_score()` JSON key scoring | Picks the best nested array when JSON has multiple lists | ✅ Keep — internal to listing path only |
| `_json_ld_listing_confident()` | Decides if microdata/opengraph should be skipped | ❌ Remove or make surface-aware |
| `_has_surface_field_overlap()` gate in `_raw_json_items()` | Discards records if JSON keys don't match expected vocabulary | ❌ Remove silent discard, convert to metric |
| `best_listing_candidate_set()` adapter vs. generic ranking | Picks best candidate set from multiple extraction strategies | ✅ Keep |

---

## Part 4 — Failure Modes When User Selects Wrong Surface

These are real failures the current code produces:

| Wrong selection | What breaks | Symptom |
|---|---|---|
| User picks `listing` on a detail page | `extract_listing_records()` runs, finds no card grid, returns empty | Zero records, silent failure |
| User picks `detail` on a listing page | `extract_detail_records()` runs, finds the first product and treats it as the one product on the page | Returns 1 record instead of 50 |
| User picks `listing` on a JSON-API page with non-standard field names | `_has_surface_field_overlap()` threshold not met → `_raw_json_items()` returns `[]` | Zero records despite valid JSON data present |
| User picks `detail` on a page with strong `ItemList` JSON-LD | `_json_ld_listing_confident()` returns True → microdata/opengraph suppressed → detail fields missing | Partial record: title+URL but no price/description |
| User picks `ecommerce_listing` on a `job_listing` page | Field mapping works but `is_job=False` in `listing_detail_like_path()` → job URL patterns not recognized as valid | Good URLs may be filtered as "structural" non-results |

**None of these produce an error.** They all produce silent partial or empty results. This is the most dangerous failure mode pattern — users think the crawl worked but got garbage.

---

## Part 5 — Dead / Incorrect Code

### Dead Code

| File | Symbol | Why dead |
|---|---|---|
| `detail_extractor.py` | Entire file | 3-line facade that replaces itself with `detail_materializer` via `sys.modules` hack — the file itself is dead, it just proxies |
| `crawl_fetch_runtime.py` | 297 bytes | Extremely small file, likely a stub/shim — verify if any active caller exists |
| `_batch_runtime.py` | Sections referencing `auto` traversal mode | Previously identified auto-traversal surface routing code |

### Incorrect / Misleading Code

| File | Symbol | Issue |
|---|---|---|
| `extraction_context.py` | `collect_structured_source_payloads()` | Returns different sources depending on page DOM, not user intent — callers don't know sources were skipped |
| `extraction_context.py` | `_json_ld_listing_confident()` | Name implies it only applies to listing — but it suppresses detail-useful sources too |
| `extraction_runtime.py` | `_has_surface_field_overlap()` | Returns `True` (meaning "pass") when `canonical` is empty — vacuous truth, always passes for unknown surfaces |
| `extraction_runtime.py` | `_raw_json_items()` | Silent `return []` on failed overlap check — no log, no metric, no error; callers believe there was no data |

---

## Part 6 — Master Refactor Plan

### Phase 1 — Stop Silent Discards (High Priority, Low Risk)

**Goal:** Make failures loud instead of silent.

**Step 1.1 — `_raw_json_items()` silent discard → logged skip**

```python
# BEFORE
if is_listing_surface and not _has_surface_field_overlap(payload, surface=surface):
    return []

# AFTER
if is_listing_surface and not _has_surface_field_overlap(payload, surface=surface):
    logger.warning(
        "raw_json_surface_field_overlap_failed surface=%s item_count=%d — returning items anyway",
        surface, len(payload),
    )
    return list(payload)  # don't discard; let downstream ranking decide
```

The overlap check is a heuristic — it should never be a silent discard gate. Convert it to a warning metric and remove the `return []`.

**Step 1.2 — Same fix in `_best_nested_listing_items()`**

```python
# BEFORE
if surface and not _has_surface_field_overlap(payload, surface=surface):
    score = 0

# AFTER
if surface and not _has_surface_field_overlap(payload, surface=surface):
    score = max(0, score - 10)  # penalize, don't zero out
```

---

### Phase 2 — Make `collect_structured_source_payloads()` Surface-Aware (Medium Priority, Medium Risk)

**Goal:** Stop suppressing microdata/opengraph on detail pages that happen to have ItemList JSON-LD.

**Step 2.1 — Pass `surface` into `collect_structured_source_payloads()`**

```python
# BEFORE
def collect_structured_source_payloads(context, *, page_url):
    skip_extruct_fallbacks = _json_ld_listing_confident(json_ld_payloads)

# AFTER
def collect_structured_source_payloads(context, *, page_url, surface: str = ""):
    is_listing = "listing" in str(surface or "").lower()
    skip_extruct_fallbacks = is_listing and _json_ld_listing_confident(json_ld_payloads)
```

The one-line guard `is_listing and ...` means: only skip fallback sources if we are actually on a listing surface AND the page confirms it. Detail surfaces never skip microdata/opengraph.

**Step 2.2 — Update all callers of `collect_structured_source_payloads()`** to pass `surface=surface`.

---

### Phase 3 — Remove Auto-Traversal Mode (High Priority, Already Decided)

**Files to modify:**
- `_batch_runtime.py` — remove `auto` mode branches
- Any router/dispatch that produces `surface="auto"` or `traversal_mode="auto"`
- Any `if surface == "auto"` or `if traversal_mode == "auto"` conditionals

**Verification:** After removal, add an assertion at the top of `extract_records()`:
```python
assert surface and surface != "auto", f"Surface must be explicit, got: {surface!r}"
```
This will catch any missed callers during testing.

---

### Phase 4 — `detail_extractor.py` Facade Cleanup (Low Priority, Cosmetic)

The `sys.modules` hack in `detail_extractor.py` is confusing to any future contributor:
```python
_sys.modules[__name__] = _detail_materializer  # replaces itself at import time
```

**Step 4.1:** Update all remaining callers that import from `detail_extractor` to import directly from `extract.detail_materializer`.

**Step 4.2:** Delete `detail_extractor.py`.

This is a cosmetic refactor but removes a module-system hack that obscures the real import graph.

---

### Phase 5 — Add Surface Mismatch Warnings (Future, Low Risk)

Once Phases 1–3 are complete, add a lightweight page-shape vs. surface-shape cross-check as a **warning only** (never a blocker):

```python
def warn_if_surface_mismatch(html: str, surface: str, records: list[dict]) -> None:
    if not records and "listing" in surface:
        # Check if page DOM looks like a detail page
        if _page_likely_detail(html):
            logger.warning("surface_mismatch_suspected: user selected %s but page signals detail", surface)
    elif not records and "detail" in surface:
        if _page_likely_listing(html):
            logger.warning("surface_mismatch_suspected: user selected %s but page signals listing", surface)
```

This gives observability without affecting behavior — operators can alert on this log line.

---

## Summary Priority Matrix

| Phase | Action | Risk | Impact | Files Touched |
|---|---|---|---|---|
| 1a | Remove silent `return []` in `_raw_json_items()` | Low | High — stops zero-record failures on valid JSON | `extraction_runtime.py` |
| 1b | Penalize instead of zero-score in `_best_nested_listing_items()` | Low | Medium | `extraction_runtime.py` |
| 2 | Pass `surface` to `collect_structured_source_payloads()` | Medium | High — fixes detail records on ItemList pages | `extraction_context.py` + callers |
| 3 | Remove auto-traversal mode | Medium | High — already decided | `_batch_runtime.py` + routes |
| 4 | Delete `detail_extractor.py` facade | Low | Low — cosmetic | `detail_extractor.py` + all its callers |
| 5 | Add surface mismatch warning logs | Low | Medium — observability | `extraction_runtime.py` |
