---
title: "refactor: Decompose God Files — extract/service.py, listing_extractor.py, browser_client.py"
type: refactor
status: phase-a-in-progress
date: 2026-04-11
---

# ♻️ refactor: Decompose God Files — extract/service.py, listing_extractor.py, browser_client.py

## Overview

Three files account for **11,274 lines** — 29% of the entire backend — in just 3 files. Every pipeline change touches them, every session loses context, every edit has blast radius across unrelated concerns. This plan decomposes each into focused modules under 500 lines, with zero behavior change and full test-suite verification between each step.

**Current state:**

| File | Lines | Target |
|------|-------|--------|
| `app/services/extract/service.py` | 5,167 | ~450 (public API + orchestrators) |
| `app/services/extract/listing_extractor.py` | 3,524 | ~400 (entry point + dispatch) |
| `app/services/acquisition/browser_client.py` | 2,583 | ~500 (core fetch + pool) |

---

## Pre-Flight Checks (Before Any Decomposition)

These must be done before the first file is touched. They prevent test churn multiplying during the refactor.

### Pre-1: Full test suite green

```powershell
cd backend
$env:PYTHONPATH='.'
pytest tests -q --tb=short
# Must show 0 failures before proceeding
```

If failures exist, fix or quarantine each one before starting. A red suite during a refactor is undebuggable.

### Pre-2: Introduce `__init__.py` in both packages

Both `app/services/extract/` and `app/services/acquisition/` currently lack `__init__.py`. Without one, every file in the package is implicitly importable — which is exactly what the decomposition is trying to fix. Each package gets a minimal `__init__.py` that re-exports only the public surface:

```python
# app/services/extract/__init__.py
from app.services.extract.service import (
    extract_candidates,
    candidate_source_rank,
)
from app.services.extract.candidate_processing import (
    coerce_field_candidate_value,
    finalize_candidate_row,
    sanitize_field_value,
    sanitize_field_value_with_reason,
)
```

```python
# app/services/acquisition/__init__.py
from app.services.acquisition.browser_client import (
    BrowserResult,
    fetch_rendered_html,
    expand_all_interactive_elements,
)
from app.services.acquisition.browser_pool import (
    BrowserPool,
    reset_browser_pool_state,
    browser_pool_snapshot,
    shutdown_browser_pool,
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool_sync,
)
```

This creates a stable, inspectable public API and makes it obvious when a new module's function should be exported vs. remain package-private.

### Pre-3: Static import check baseline

```bash
python -m py_compile app/services/extract/service.py
python -m py_compile app/services/extract/listing_extractor.py
python -m py_compile app/services/acquisition/browser_client.py
ruff check app/services/ --select F
```

Record baseline output. After each extraction step, re-run and diff — any new `F811` (redefinition) or `F401` (unused import) is a regression introduced by the move.

### Pre-4: Verify `asyncio.to_thread()` wraps BeautifulSoup parsing

In `services/pipeline/stages.py` and `services/pipeline/utils.py`, confirm CPU-bound `BeautifulSoup()` calls are wrapped in `asyncio.to_thread()`. Relocating extract code can accidentally strip this wrapper. Document the current call sites before moving code.

```bash
grep -n "to_thread\|BeautifulSoup" backend/app/services/pipeline/stages.py backend/app/services/pipeline/utils.py
```

---

## Phase A — `extract/service.py` (5,167 → ~200 lines)

**External callers (production):** `pipeline/core.py`, `pipeline/llm_integration.py`, `field_decision.py`
**Public API to preserve:** `extract_candidates`, `coerce_field_candidate_value`, `candidate_source_rank`, `finalize_candidate_row`, `sanitize_field_value`, `sanitize_field_value_with_reason`
**Private symbols tested by name (require import-path update):** 10 in `test_extract.py`, 3 in `test_dynamic_field_schema_noise.py`, 1 in `test_field_arbitration.py`

### Step A-1: Extract `variant_extractor.py`

**Why first:** The variant cluster (lines ~1,148–1,578) is the largest cohesive group and has **zero external callers** — no test imports privates from this range. It is entirely exercised through `extract_candidates`. Lowest risk extraction.

**Functions to move (~35 functions, ~1,271 lines):**

```
_sync_selected_variant_root_fields
_sanitize_structured_variant_output
_merge_product_attributes_into_candidates
_sanitize_product_attributes
_reconcile_variant_bundle
_merge_variant_axis_values
_first_candidate_row
_row_source_label
_normalized_variant_rows_payload
_normalized_selected_variant_payload
_normalized_variant_axes_payload
_is_meaningful_variant_record
_variant_record_fingerprint
_find_matching_variant_index
_merge_variant_records
_choose_default_variant
_collect_variant_axis_values
_is_noisy_product_attribute_entry
```

**New file:** `app/services/extract/variant_extractor.py`

**Import update in `service.py`:**
```python
from app.services.extract.variant_extractor import (
    _reconcile_variant_bundle,
    _sync_selected_variant_root_fields,
    _sanitize_product_attributes,
    _merge_product_attributes_into_candidates,
    # ... all moved functions
)
```

**Verification after A-1:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
```

### Step A-2: Extract `field_classifier.py`

**Functions to move (~11 functions, lines ~2,109–2,175):**

```
_field_name_preference
_dynamic_field_name_is_noisy
_should_skip_jsonld_block
_dynamic_field_name_is_schema_slug_noise   # tested by test_dynamic_field_schema_noise.py
_dynamic_field_name_is_valid               # tested by test_dynamic_field_schema_noise.py
_dynamic_value_is_bare_ticker_symbol       # tested by test_dynamic_field_schema_noise.py
_dynamic_field_name_is_valid
_canonical_structured_key
_field_alias_tokens
_normalized_field_token
```

**New file:** `app/services/extract/field_classifier.py`

**Import-path update required in:**
- `tests/services/extract/test_dynamic_field_schema_noise.py` — change import path from `service` to `field_classifier`

**Note:** `field_decision.py` already imports `candidate_source_rank`, `finalize_candidate_row`, `sanitize_field_value_with_reason` from `service.py`. After moving field classifier functions, `field_decision.py` may be able to import directly from `field_classifier.py` — audit and update.

**Verification after A-2:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
```

### Step A-3: Extract `candidate_processing.py`

> **Renamed from `candidate_coercion.py`** — this module owns coerce + sanitize + finalize logic. "Coercion" understates the scope. `candidate_processing` matches the existing `field_decision.py` naming pattern.

**Functions to move (~25 functions, lines ~1,890–2,109):**

```
_finalize_candidate_rows          # tested by test_extract.py (import-path update required)
sanitize_field_value              # PUBLIC
sanitize_field_value_with_reason  # PUBLIC
finalize_candidate_row            # PUBLIC
_normalize_embedded_cents_value
_normalize_html_rich_text         # tested by test_extract.py (import-path update required)
_candidate_value_fingerprint
_preferred_display_candidate_value
_display_candidate_priority
_source_labels
_normalized_candidate_value
_comparable_candidate_value
_normalized_candidate_text
coerce_field_candidate_value      # PUBLIC
_dispatch_string_field_coercer    # tested by test_extract.py (import-path update required)
_pick_best_nested_candidate
_parse_json_like_value
_resolve_candidate_url            # tested by test_extract.py (import-path update required)
```

**New file:** `app/services/extract/candidate_processing.py`

> **No re-export shims in `service.py`.** The callers of these public functions are limited and enumerable (4 non-test files). Update them directly to import from `candidate_processing` — shim layers add permanent indirection to avoid 6 import-line changes:
> - `app/services/pipeline/core.py` → import `coerce_field_candidate_value` from `candidate_processing`
> - `app/services/pipeline/llm_integration.py` → import `coerce_field_candidate_value` from `candidate_processing`
> - `app/services/extract/field_decision.py` → import `finalize_candidate_row`, `sanitize_field_value_with_reason` from `candidate_processing`
> - `tests/services/test_crawl_service.py` → import `sanitize_field_value` from `candidate_processing`

**Import-path updates required in `test_extract.py`:**
```python
# Before:
from app.services.extract.service import _finalize_candidate_rows, _normalize_html_rich_text, ...
# After:
from app.services.extract.candidate_processing import _finalize_candidate_rows, _normalize_html_rich_text, ...
```

> **Public-name promotion:** Before moving `_finalize_candidate_rows` and `_dispatch_string_field_coercer` across the module boundary, rename them to `finalize_candidate_rows` and `dispatch_string_field_coercer` (remove leading underscore). Cross-module imports of underscored names violate Python's encapsulation convention and break pyright/mypy. Update all callsites (both production and test imports) to use the public name.

**Verification after A-3:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
pytest tests/services/test_crawl_service.py -q  # uses sanitize_field_value
```

### Step A-4: Extract `dom_extraction.py`

**Functions to move (~20 functions, lines ~1,704–1,890):**

```
_scope_adapter_records_for_url
_scoped_semantic_payload
_scoped_url_key
_scoped_record_identifiers
_extract_label_value_from_text    # tested by test_extract.py (import-path update)
_label_value_pattern              # tested by test_extract.py (import-path update)
_label_value_variants
_dom_pattern
_extract_dom_node_value
_build_label_value_text_sources
_deep_get_all_aliases
_append_source_candidates
_extract_breadcrumb_category
_breadcrumb_item_matches_title
_strip_tracking_query_params
_looks_like_asset_url
```

**New file:** `app/services/extract/dom_extraction.py`

**Verification after A-4:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
```

### Step A-5: Verify `service.py` target

After A-1 through A-4, `service.py` retains:
- Public functions: `extract_candidates`, `candidate_source_rank`
- The `_collect_candidates` orchestrator and its 8 `_collect_*` subfunctions (~230 lines)
- The `_filter_candidates` and `_finalize_candidates` orchestrators (~190 lines)
- Top-level constants and the salary regex builder (~50 lines)

**Realistic target: `service.py` ≤ 450 lines.** A 200-line target is not achievable while retaining the collection/filter/finalize orchestrators, which are the core logic that belongs in `service.py`. Do not attempt to extract these orchestrators further — they are the public API's orchestration logic, not a god file problem.

**Final verification for Phase A:**
```bash
ruff check app/services/ --select F
pytest tests/ -q --tb=short --ignore=tests/e2e
python run_extraction_smoke.py
```

---

## Phase B — `listing_extractor.py` (3,524 → ~400 lines)

**External callers (production):** `pipeline/core.py` only
**Public API to preserve:** `extract_listing_records`, `is_listing_like_record`
**Private symbols tested by name:** `_harvest_product_url_from_item` (1 test file), `_extract_card_color` (1 test file)

### Step B-0: Consolidate URL classifiers into `listing_quality.py` (prerequisite)

`listing_extractor.py` contains private copies of functions already in `listing_quality.py`:
```
_is_merchandising_record
_looks_like_category_url
_looks_like_detail_record_url
_looks_like_facet_or_filter_url
_looks_like_listing_hub_url
```

Additionally, `is_listing_like_record` (currently private to `listing_extractor.py`) belongs alongside `is_meaningful_listing_record` and `has_meaningful_listing_set` in `listing_quality.py` — that file already owns listing record quality/classification.

**Actions:**
1. Move `is_listing_like_record` into `listing_quality.py` and make it public
2. Replace the 5 internal duplicate callsites in `listing_extractor.py` with imports from `listing_quality`
3. Delete the local private copies from `listing_extractor.py`

This removes ~200 lines before B-1 begins. **Do not proceed to B-1 until B-0 is verified.**

> **Important:** This eliminates the need for a separate `listing_record_filter.py`. All URL classification, signal detection, and record quality logic lives in `listing_quality.py`. Do not create `listing_record_filter.py`.

### Step B-1: Extract `listing_card_extractor.py`

**Why:** The card DOM parsing cluster (~lines 2,125–3,524, ~1,400 lines) is the largest cohesive block. It is a self-contained concern: given a BeautifulSoup node, extract a card record.

**Functions to move:**

```
_auto_detect_cards
_score_card_candidate
_extract_from_card
_extract_ecommerce_card_fields
_extract_job_card_fields
_extract_card_color        # tested by test_extraction_fixes.py (import-path update)
_harvest_product_url_from_item  # tested by test_listing_url_harvest.py (import-path update)
_extract_card_image
_extract_card_price
_infer_card_availability
_compact_card_record
(all remaining _extract_from_card_* helpers)
```

**New file:** `app/services/extract/listing_card_extractor.py`

**Import-path updates required:**
- `tests/test_extraction_fixes.py`: `from app.services.extract.listing_card_extractor import _extract_card_color`
- `tests/services/extract/test_listing_url_harvest.py`: `from app.services.extract.listing_card_extractor import _harvest_product_url_from_item`

**Verification after B-1:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
pytest tests/test_extraction_fixes.py -q
```

### Step B-2: Extract `listing_structured_extractor.py`

**Functions to move (~lines 423–1,244, ~820 lines):**

```
_extract_from_structured_sources
_extract_from_comparison_tables
_extract_comparison_table_column_record
_extract_comparison_table_value
_apply_comparison_table_row
_comparison_table_field_name
_extract_from_json_ld
_extract_ld_records_from_payload
_extract_next_data_payload
_normalize_ld_item
_extract_from_next_data
_extract_items_from_json
_collect_candidate_record_sets
_query_state_data
_try_normalize_array
_looks_like_listing_filter_option
_extract_from_next_flight_scripts
_extract_from_inline_object_arrays
_looks_like_inline_collection_key
_extract_balanced_literal
_lookup_next_flight_window_index
```

**New file:** `app/services/extract/listing_structured_extractor.py`

**Note:** These functions already import from `source_parsers.py`, `listing_identity.py`, `listing_normalize.py` — those imports follow the functions to the new file.

**Verification after B-2:**
```bash
ruff check app/services/extract/ --select F
pytest tests/services/extract/ -q --tb=short
```

### Step B-3: Extract `listing_item_normalizer.py`

**Why:** After B-1 and B-2, the remaining bulk in `listing_extractor.py` is no longer card or structured-source extraction. It is the generic record normalization/product-search cohort used by hydrated arrays and adapter-like payloads. Keeping that logic in `listing_extractor.py` prevents the final shell reduction even after the extraction owners are clean.

**Functions to move:**

```
_normalize_generic_item
_apply_surface_record_contract
_promote_job_salary
_normalize_job_title
_fill_missing_job_identifier
_fill_missing_job_urls
_strip_job_commerce_fields
_preferred_generic_item_values
_extract_generic_job_identifier
_synthesize_job_detail_url
_clean_identifier
_default_job_detail_url_synthesis
_looks_like_listing_variant_option
_normalize_product_search_item
_is_product_search_item
_product_search_base_record
_append_product_search_images
_append_product_search_attributes
_compact_product_search_record
_product_search_detail_url
_product_search_images
_product_search_attribute_map
_product_search_dimensions
_normalize_listing_value
_find_alias_values
_normalized_field_token
_looks_like_product_short_path
_resolve_slug_url
_coerce_nested_text
_coerce_nested_category
```

**New file:** `app/services/extract/listing_item_normalizer.py`

**Compatibility rule:** `listing_extractor.py` may re-export thin wrappers for legacy private helper names that tests or stale callers still import, but ownership lives in `listing_item_normalizer.py`.

### Step B-4: ~~Extract `listing_record_filter.py`~~ — ELIMINATED

> **This step is removed.** The URL classification and listing record quality functions from `listing_extractor.py` now go into `listing_quality.py` (done in B-0). There is no third home for these functions. `listing_quality.py` already owns this cohort:
> - `is_meaningful_listing_record`, `is_meaningful_structured_listing_record`, `has_meaningful_listing_set`, `listing_set_quality`
> - `is_listing_like_record` (moved in B-0)
> - All `_looks_like_*` URL classifiers (moved in B-0)
>
> Remaining signal functions that aren't pure classifiers (`_is_noise_title`, `_estimate_visible_item_count`, `_looks_like_navigation_or_action_title`, etc.) stay inline in `listing_extractor.py` if they are called nowhere else, or move to `listing_quality.py` if they belong to the same classification cohort.

After B-0 and B-1 and B-2, verify `listing_extractor.py` is ≤ 400 lines without a B-3 step. If it exceeds 400 lines, audit what remains and extend B-2 or add a targeted B-3 rather than pre-defining it.

### Step B-5: Slim `listing_extractor.py` to entry-point shell

After B-1 through B-3, `listing_extractor.py` should contain only:
- `extract_listing_records` (public entry point)
- `_extract_listing_records_single_page`
- `_should_run_expensive_listing_fallbacks`
- `_extract_dom_listing_records`
- `_normalize_listing_record_sets` / `_normalize_record_set`
- `_dedupe_listing_records` / `_listing_record_join_key`
- `_split_paginated_html_fragments`
- `_enforce_listing_field_contract`

**Target:** `listing_extractor.py` ≤ 400 lines

**Final verification for Phase B:**
```bash
ruff check app/services/ --select F
pytest tests/ -q --tb=short --ignore=tests/e2e
python run_extraction_smoke.py
```

---

## Phase C — `browser_client.py` (2,583 → ~500 lines)

**External callers (production):** `app/main.py`, `app/tasks.py`, `app/core/metrics.py`, `acquisition/acquirer.py`
**Public API to preserve:** `BrowserPool`, `BrowserResult`, `ChallengeAssessment`, `fetch_rendered_html`, `reset_browser_pool_state`, `expand_all_interactive_elements`, `browser_pool_snapshot`, `shutdown_browser_pool`, `prepare_browser_pool_for_worker_process`, `shutdown_browser_pool_sync`
**Private symbols tested by name:** 21 in `test_browser_client.py`, 2 in `test_browser_config_overrides.py`

> **Note:** `browser_client.py` is the highest-coupling file (21 private imports in tests). Every extraction here requires test-file import updates. Go slower here; verify after each step.

### Step C-1: Remove cookie wrapper duplication

`browser_client.py` contains thin pass-throughs to `cookie_store.py`:
```
_cookie_store_path         → delegates to cookie_store.py
_filter_persistable_cookies → delegates to cookie_store.py
_cookie_policy_for_domain  → delegates to cookie_store.py  (tested by test_browser_client.py)
_cookie_expiry             → delegates to cookie_store.py
_cookie_domain_matches     → delegates to cookie_store.py
```

Replace callsites inside `browser_client.py` with direct `cookie_store` imports. Delete the wrappers. Update `test_browser_client.py` import for `_cookie_policy_for_domain` to point to `cookie_store.py`.

This removes ~50 lines of dead indirection before any structural change.

### Step C-2: Extract `browser_pool.py`

**Functions to move (browser lifecycle management):**

```
_PooledBrowser (class)
BrowserPool (class — PUBLIC)
_browser_pool_state
_acquire_browser
_evict_browser
_evict_idle_or_dead_browsers
_shutdown_browser_pool
_browser_pool_healthcheck_loop
_ensure_browser_pool_maintenance_task
reset_browser_pool_state     # PUBLIC — re-export in browser_client.py
browser_pool_snapshot        # PUBLIC — re-export in browser_client.py
shutdown_browser_pool        # PUBLIC — re-export in browser_client.py
prepare_browser_pool_for_worker_process  # PUBLIC — re-export
shutdown_browser_pool_sync   # PUBLIC — re-export
_browser_pool_key
_browser_is_connected
_close_browser_safe
_check_memory_available
```

**New file:** `app/services/acquisition/browser_pool.py`

**Re-export shims in `browser_client.py`:**
```python
from app.services.acquisition.browser_pool import (
    BrowserPool,
    reset_browser_pool_state,
    browser_pool_snapshot,
    shutdown_browser_pool,
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool_sync,
)
```

**Verification after C-2:**
```bash
ruff check app/services/acquisition/ --select F
pytest tests/services/acquisition/ -q --tb=short
pytest tests/conftest.py -q  # uses reset_browser_pool_state
```

### Step C-3: Extract `browser_challenge.py`

**Functions to move (anti-bot challenge detection):**

```
ChallengeAssessment (dataclass — PUBLIC)
_assess_challenge_signals    # tested by test_browser_client.py (import-path update)
_wait_for_challenge_resolution  # tested by test_browser_client.py (import-path update)
_html_looks_low_value
_page_looks_low_value
_retryable_browser_error_reason  # tested by test_browser_client.py (import-path update)
```

**New file:** `app/services/acquisition/browser_challenge.py`

**Import-path updates in `test_browser_client.py`:**
```python
from app.services.acquisition.browser_challenge import (
    _assess_challenge_signals,
    _wait_for_challenge_resolution,
    _retryable_browser_error_reason,
)
```

**Verification after C-3:**
```bash
ruff check app/services/acquisition/ --select F
pytest tests/services/acquisition/ -q --tb=short
```

### Step C-4: Extract `browser_readiness.py`

> **Renamed from `browser_page_wait.py`** — two-word naming convention matches existing modules (`browser_runtime`, `browser_client`, `session_context`). "Readiness" more accurately names the concern.

**Functions to move (readiness/stability detection):**

```
_wait_for_listing_readiness    # tested by test_browser_client.py AND test_browser_config_overrides.py
_wait_for_surface_readiness    # tested by test_browser_client.py
_snapshot_listing_page_metrics # tested by test_browser_client.py
_listing_metrics_stable
_listing_metrics_look_shell_like
_detail_readiness_selectors
_is_listing_surface
_cooperative_page_wait
_cooperative_sleep_ms
_pause_after_navigation
```

**New file:** `app/services/acquisition/browser_readiness.py`

**Import-path updates in:**
- `tests/services/acquisition/test_browser_client.py` — 5 function imports
- `tests/services/acquisition/test_browser_config_overrides.py` — `_wait_for_listing_readiness`

**Critical — monkeypatch namespace update:** `test_browser_config_overrides.py` patches `browser_client.LISTING_READINESS_MAX_WAIT_MS`. After extraction, update the patch target to `browser_readiness.LISTING_READINESS_MAX_WAIT_MS`. Failure to do this creates a silent test bug where the monkeypatch patches the wrong namespace.

**Verification after C-4:**
```bash
ruff check app/services/acquisition/ --select F
pytest tests/services/acquisition/ -q --tb=short
grep -r "LISTING_READINESS_MAX_WAIT_MS" tests/  # Confirm no stale patch targets
```

### Step C-5: Inline traversal delegates, extract `browser_navigation.py`

**Critical architectural correction:** `_apply_traversal_mode` and `_collect_paginated_html` in `browser_client.py` are **thin wrappers that delegate immediately to `traversal.py`**. The plan originally proposed moving them to `browser_navigation.py`, but that creates a three-hop chain: `browser_client → browser_navigation → traversal`. Instead:

**Action:** Delete the thin wrapper functions from `browser_client.py` and call `traversal.py` functions directly at callsites. `traversal.py` already exports these as public functions.

**Remaining functions for `browser_navigation.py` (pure navigation logic, not traversal delegation):**

```
_goto_with_fallback          # tested by test_browser_client.py (import-path update)
_navigation_strategies
_shortened_navigation_strategies
_classify_profile_failure_reason
_should_shorten_navigation_after_profile_failure
_navigation_attempts
_warm_origin
_maybe_warm_origin
_origin_url
```

**New file:** `app/services/acquisition/browser_navigation.py`

**Import-path updates in `test_browser_client.py`:** ~3 function imports for `_goto_with_fallback` and related navigation helpers.

**Verification after C-5:**
```bash
ruff check app/services/acquisition/ --select F
pytest tests/services/acquisition/ -q --tb=short
```

### Step C-6: Slim `browser_client.py` to core fetch

After C-1 through C-5, `browser_client.py` should contain only:
- `fetch_rendered_html` (PUBLIC — main entry point)
- `_fetch_rendered_html_with_fallback` (tested by test_browser_client.py)
- `_fetch_rendered_html_attempt`
- `BrowserResult` (dataclass — PUBLIC)
- `expand_all_interactive_elements` (PUBLIC)
- `_flatten_shadow_dom`
- `_populate_result`
- `_page_content_with_retry`
- `_collect_frame_sources` (tested by test_browser_client.py)
- `_build_launch_kwargs` (tested by test_browser_client.py)
- `_browser_launch_profiles` (tested by test_browser_client.py)
- `_context_kwargs` (tested by test_browser_client.py)
- `_is_public_browser_request_target` (tested by test_browser_client.py)
- Core cookie functions: `_load_cookies`, `_save_cookies`
- `_warm_origin`, `_maybe_warm_origin`
- `_elapsed_ms`, `_normalize_traversal_summary`

**Target:** `browser_client.py` ≤ 500 lines

**Final verification for Phase C:**
```bash
ruff check app/services/ --select F
pytest tests/ -q --tb=short --ignore=tests/e2e
python run_acquire_smoke.py commerce
python run_acquire_smoke.py jobs
```

---

## Acceptance Criteria

### Functional
- [ ] Full test suite passes with 0 failures after each phase (A, B, C)
- [ ] `python run_extraction_smoke.py` produces identical output before and after all phases
- [ ] `python run_acquire_smoke.py commerce` completes successfully after Phase C
- [ ] No import errors: `ruff check app/ --select F` reports 0 violations

### Structural
- [ ] `service.py` ≤ 500 lines
- [ ] `listing_extractor.py` ≤ 400 lines
- [ ] `browser_client.py` ≤ 500 lines
- [ ] No new file created exceeds 600 lines
- [ ] Public API of all three files is unchanged (all callers still work without updates)

### Quality
- [ ] No private functions duplicated between files (no copy-paste of helpers)
- [ ] Every new module has a clear single-concern name (not `utils.py`, `helpers.py`)
- [ ] `asyncio.to_thread()` wraps are preserved around all BeautifulSoup parsing
- [ ] No cross-module imports of underscored (`_`) names — promoted to public names at move time
- [ ] Both `extract/` and `acquisition/` have `__init__.py` re-exporting the public surface
- [ ] No shim re-exports in original files — callers updated directly
- [ ] `listing_quality.py` is the single home for URL classification and record quality functions

---

## Order of Operations

```
Pre-flight (1 PR): green suite + __init__.py + static baseline + asyncio.to_thread check
  → Phase A: service.py (4 PRs: A-1, A-2, A-3, A-4)
    → Phase B: listing_extractor.py (3 PRs: B-0, B-1, B-2)
      → Phase C: browser_client.py (5 PRs: C-1, C-2, C-3, C-4, C-5)
```

Never combine steps from different phases into one PR. If a step breaks tests, stop, diagnose, fix before the next step.

---

## New File Inventory

After all phases complete, the extract and acquisition directories will contain:

**`app/services/extract/`** (new modules added):
- `variant_extractor.py` — variant merging, axis detection, reconciliation
- `field_classifier.py` — dynamic field name validation, noise filters
- `candidate_processing.py` — coerce, sanitize, finalize candidate values (replaces `candidate_coercion.py`)
- `dom_extraction.py` — live-tree DOM pattern matching, label-value, breadcrumb, URL resolution (distinct from `source_parsers.py` structured script parsing)
- `listing_card_extractor.py` — DOM card detection, scoring, field extraction
- `listing_structured_extractor.py` — JSON-LD, Next.js, hydrated state extraction
- `__init__.py` — public surface re-exports
- ~~`listing_record_filter.py`~~ — **NOT CREATED** — URL classifiers consolidated into `listing_quality.py`

**`app/services/extract/listing_quality.py`** (extended, not created):
- Absorbs `is_listing_like_record` + 5 URL classifier functions from `listing_extractor.py` (B-0)

**`app/services/acquisition/`** (new modules added):
- `browser_pool.py` — pool lifecycle, health checks, acquire/evict
- `browser_challenge.py` — anti-bot detection, challenge signals, wait-for-resolution
- `browser_readiness.py` — readiness detection, metric snapshots, cooperative sleep (replaces `browser_page_wait.py`)
- `browser_navigation.py` — goto-with-fallback, navigation strategies (excludes traversal delegation — those inline directly to `traversal.py`)
- `__init__.py` — public surface re-exports

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Circular imports between new modules | Import direction must be one-way: new modules must not import from the parent god file after the move |
| Monkeypatched constants with wrong namespace | After each step, grep for `monkeypatch.setattr` targeting old module path and update; especially `LISTING_READINESS_MAX_WAIT_MS` |
| `asyncio.to_thread()` accidentally dropped | Pre-flight baseline + post-phase grep check |
| Test importing moved private by old path | Run full suite after each step; any `ImportError` is a missed import update |
| Accidental behavior change during move | Smoke test comparison before/after each phase |
| Cross-module import of underscored names | Promote to public name at move time; verify with `ruff check --select F401,F811` |
| URL classifiers triplicated | Canonical home is `listing_quality.py`; delete all copies, never create a third file |
| `browser_navigation.py` re-wrapping `traversal.py` | After C-5, verify no wrapper chain: `browser_client → browser_navigation → traversal`; call `traversal` directly |

---

## References

- `docs/ENGINEERING_STRATEGY.md` — Phase 2 roadmap (this plan implements it)
- `docs/INVARIANTS.md` — All 25 invariants must be preserved (especially: no site hardcodes, extraction is first-match, user controls not rewritten)
- `docs/backend-architecture.md` — Pipeline architecture constraints
- `tests/services/extract/test_extract.py` — 2,140-line test file, primary regression guard
- `tests/services/acquisition/test_browser_client.py` — 1,336-line test file, 21 private imports
