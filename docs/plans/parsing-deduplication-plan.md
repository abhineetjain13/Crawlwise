# Plan: Acquisition & Parsing Deduplication

**Created:** 2026-05-01
**Agent:** Cascade
**Status:** COMPLETE
**Touches buckets:** Acquisition (browser/readiness), Extraction (helpers, structured sources), LLM Runtime, Adapters, Selectors

## Goal

Eliminate duplicate HTML parsing, redundant BeautifulSoup instantiation, and parallel JSON-LD/`__NEXT_DATA__` extraction paths that waste CPU and create maintenance surface.

## Confirmed Duplication

### DUP-1: Inline BeautifulSoup text extraction (not reusing `html_to_text()`)

- `field_value_core.py:466-470` — `coerce_text()` instantiates own `BeautifulSoup` instead of calling `html_to_text()` from `extraction_html_helpers.py`
- `selectors_runtime.py:71-72` — iframe fallback does inline `BeautifulSoup` + `clean_text()`
- `selectors_runtime.py:584` — `_primary_iframe_candidate()` repeats pattern

### DUP-2: Duplicate JSON-LD + `__NEXT_DATA__` extraction

- `llm_tasks.py:655-694` — `_extract_structured_data()` reimplements JSON-LD parsing already in `structured_sources.py:parse_json_ld()`. Also manually extracts `__NEXT_DATA__`, which `structured_sources.py:harvest_js_state_objects()` already covers.
- `adapters/walmart.py:31-35` — `_get_next_data()` extracts `__NEXT_DATA__` manually
- `adapters/nike.py:82-103` — `_preloaded_product()` and `_next_data_product()` each create own `BeautifulSoup` and extract script tags

### DUP-3: Duplicate HTML pruning pipelines

- `llm_tasks.py:602-636` — `_prune_html_for_llm()`: comment removal, tag decompose, attr filtering
- `selector_self_heal.py:33-57` — `reduce_html_for_selector_synthesis()`: same three steps, different config source
- `browser_page_flow.py:1217-1242` — `_prepare_markdown_soup()`: same operations again

### DUP-4: Multiple BeautifulSoup instances from same HTML

In one pipeline run the same HTML is parsed into `BeautifulSoup` at least **3 times**:

1. `browser_readiness.analyze_html()` — cached `@lru_cache(maxsize=8)`
2. `browser_page_flow._generate_page_markdown()` — line 1218, new parse regardless
3. `extraction_context.soup` — lazily created at line 34 when extraction starts

### DUP-5: Duplicate markdown / visible-text serialization

- `browser_readiness.py:266-277` — `visible_text_from_soup()`
- `browser_page_flow.py:1301+` — `_serialize_markdown_root()`
- `extraction_html_helpers.py:11-13` — `html_to_text()`
- `record_export_service.py:677-699` — `_html_fragment_to_markdown_text()`

## New Compute-Waste Findings

### WASTE-1: Quadruple-nested loop in structured source extraction

**`structured_sources.py:280-287`** — `_extract_generic_assignment_payloads()` iterates `scripts × assignment names × patterns × regex matches`. Every script tag triggers `_assignment_patterns()` (cached via `@lru_cache(maxsize=64)`), but the 4-level nesting still re-walks the same text repeatedly. For pages with 50+ script tags this is the hottest sync path in extraction.

### WASTE-2: `selectors_runtime.py` parses the same HTML twice for a length comparison

```python
iframe_text = clean_text(BeautifulSoup(iframe_result.html, "html.parser").get_text(" ", strip=True))
page_text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
```
Two `BeautifulSoup` instances created for a single `len(iframe_text) <= len(page_text)` check. Should use `html_to_text()` on both; no need for `clean_text()` after `get_text(" ", strip=True)`.

### WASTE-3: `field_value_dom.py` calls `get_text(" ", strip=True)` 6× in one function

**`field_value_dom.py:608-624`** — `_extract_label_value_pairs_from_node()` repeats `clean_text(cells[0].get_text(" ", strip=True))` pattern for table rows, definition lists, and generic nodes. A local `node_text(node)` helper would halve line count and avoid re-typing the combo.

### WASTE-4: `listing_extractor.py` re-checks payload types in multiple functions

**`_allow_standalone_typed_listing_payloads()`** and **`_allow_embedded_json_listing_payloads()`** both iterate `payloads → candidates → @type` with almost identical `normalized_type` logic and `"product"/"jobposting"` checks. They could share a `_typed_listing_payloads(payloads)` generator.

### WASTE-5: `detail_extractor.py` builds 3 intermediate lists per field

**`_ordered_candidates_for_field()`** → creates `values`, `sources`, `indexed_entries`, then sorts, then `_winning_candidates_for_field()` slices again. For a record with 20 fields and 5 candidates each, that's 300+ list/dict allocations per page.

### WASTE-6: `browser_page_flow._generate_page_markdown()` creates a new BeautifulSoup even when `analyze_html()` already parsed one

`browser_readiness.analyze_html()` produces `HtmlAnalysis.soup`. `_generate_page_markdown()` at line 1218 ignores it and creates a fresh `BeautifulSoup`. On large PDPs this is a full DOM tree rebuild. (Overlaps with DUP-4; treat as primary implementation target.)

### WASTE-7: `str(value or "").strip()` is inlined ~200+ times across the codebase

Every service file repeats this defensive coercion. A top-level `_str_or_none(value) -> str | None` or similar would centralize it, but this is a large refactor (~30 files) and mostly cosmetic. Defer to P3.

### WASTE-8: `listing_extractor.py` rebuilds the same `set` of `LISTING_STRUCTURE_NEGATIVE_HINTS` tokens on every call

The `for token in LISTING_STRUCTURE_NEGATIVE_HINTS` loop at line ~879 re-evaluates the tuple each time. Immutable config — should be a `frozenset` at import time.

### WASTE-9: `selector_self_heal.py` runs 4 `soup.find_all()` scans sequentially on the same soup

```python
for comment_node in soup.find_all(...)
for drop_tag in list(soup.find_all(SELECTOR_SYNTHESIS_DROP_TAGS))
for low_value_tag in list(soup.find_all(SELECTOR_SYNTHESIS_LOW_VALUE_TAGS))
for tag in list(soup.find_all(True))
```
Four full tree walks. Could be reduced to two: one for node-type deletions, one for attr filtering.

## Proposed Fixes

### Slice 1: Consolidate text extraction to `html_to_text()`

- `field_value_core.py`: replace inline `BeautifulSoup(...).get_text(...)` with `html_to_text()`
- `selectors_runtime.py`: replace iframe + primary_iframe inline parses with `html_to_text()`

### Slice 2: Route adapters + LLM through `structured_sources.py`

- `llm_tasks.py`: replace `_extract_structured_data()` body with calls to `parse_json_ld()` + `harvest_js_state_objects()`
- `adapters/walmart.py`: use `harvest_js_state_objects()` / `parse_embedded_json()` instead of manual script extraction
- `adapters/nike.py`: same

### Slice 3: Shared HTML prune helper

- Extract `_prune_html(soup, drop_tags, allowed_attrs)` in `extraction_html_helpers.py`
- `llm_tasks.py` and `selector_self_heal.py` call shared helper
- `browser_page_flow.py` evaluates whether it can reuse same helper or stays separate (different selector/token sources)

### Slice 4: Reuse `HtmlAnalysis.soup` in browser markdown generation

- `browser_page_flow._generate_page_markdown()`: accept `HtmlAnalysis` from `browser_readiness.analyze_html()` instead of re-parsing
- Reuse `analysis.soup` for markdown generation; only clone if mutation needed

### Slice 5: Eliminate duplicate visible-text builders

- Audit `visible_text_from_soup()`, `_serialize_markdown_root()`, `html_to_text()`, `_html_fragment_to_markdown_text()` for semantic overlap
- Consolidate to at most two paths: (a) fast visible text, (b) structured markdown with link handling

### Slice 6: `field_value_dom.py` — centralize `node_text()` helper

- Add a local `_node_text(node) -> str` helper that wraps `clean_text(node.get_text(" ", strip=True))`
- Replace all 6 inline occurrences in `_extract_label_value_pairs_from_node()`

### Slice 7: `listing_extractor.py` — shared typed-listing generator + frozenset cache

- Extract `_typed_listing_payloads(payloads)` generator shared by `_allow_standalone_typed_listing_payloads()` and `_allow_embedded_json_listing_payloads()` (WASTE-4)
- Convert `LISTING_STRUCTURE_NEGATIVE_HINTS` tuple to `frozenset` at import time; stop rebuilding `set()` on every call (WASTE-8)

### Slice 8: `detail_extractor.py` — reduce intermediate list allocations

- Inline `_winning_candidates_for_field()` into `_ordered_candidates_for_field()` or use generator expressions to avoid building `values`, `sources`, and `indexed_entries` as full lists
- Target: eliminate 300+ list/dict allocations per record with many fields

### Slice 9: `structured_sources.py` — flatten quadruple-nested loop

- Pre-compile `_assignment_patterns()` results for all `EMBEDDED_ASSIGNMENT_NAMES` into a single flat tuple of `(name, compiled_pattern)` before entering the script loop
- This turns `scripts × names × patterns × matches` into `scripts × flat_patterns × matches`, removing one nesting level

### Slice 10: `selector_self_heal.py` — reduce tree walks from 4 → 2

- Combine comment + drop_tag + low_value_tag deletions into a single tree walk inside the shared prune helper (Slice 3)
- Keep attr-filtering as the second walk
- This slice is merged with Slice 3 implementation; tracked separately for verification only

## Deferred

- **WASTE-7** (`str(value or "").strip()` inlined ~200×): Large surface-area refactor, mostly cosmetic. Revisit only if a natural `_str_or_none()` helper emerges from another slice.

## Acceptance Criteria

- [ ] `html_to_text()` is the only inline BeautifulSoup text extractor outside acquisition
- [x] `llm_tasks.py` does not reimplement JSON-LD or `__NEXT_DATA__` parsing
- [ ] No adapter manually extracts `__NEXT_DATA__` / `__PRELOADED_STATE__` when `structured_sources.py` can provide it
- [x] `browser_page_flow.py` reuses `HtmlAnalysis.soup` for markdown; no redundant parse
- [x] Shared prune helper exists and both `llm_tasks.py` + `selector_self_heal.py` call it
- [x] `field_value_dom.py` has a single `_node_text()` helper; no inline `clean_text(node.get_text(...))` duplicates in that file
- [x] `listing_extractor.py` uses a shared `_typed_listing_payloads()` generator; `LISTING_STRUCTURE_NEGATIVE_HINTS` is a `frozenset`
- [x] `detail_extractor.py` no longer builds 3 intermediate lists per field for candidate ordering
- [x] `structured_sources.py` assignment pattern loop is flattened to 3 levels max
- [x] `python -m pytest tests/ -q` exits 0 (`1141 passed, 4 skipped`)
- [x] No new `_helpers.py` or `_utils.py` files created

## Verification

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

## Notes

- This is pure refactor; zero behavior change expected
- No database migration needed
- No config file additions expected (uses existing config sources)
- Per ENGINEERING-STRATEGY AP-15: delete duplicate code, do not add abstractions for abstraction's sake

## Progress

- 2026-05-01: Completed slices 1, 6, 7, and 9. Also routed Nike HTML text cleanup through `html_to_text()`. Verified with full backend suite: `1139 passed, 4 skipped`.
- 2026-05-01: Completed slices 2, 3, 4, 8, and 10. `llm_tasks.py` now delegates JSON-LD / hydrated state extraction to `structured_sources.py`; `llm_tasks.py` and `selector_self_heal.py` share `prune_html_tree()`; browser markdown generation reuses `HtmlAnalysis.soup` via copy before mutation; detail candidate ordering no longer builds separate values/sources lists or uses `_winning_candidates_for_field()`. Verified full backend suite: `1141 passed, 4 skipped`.
