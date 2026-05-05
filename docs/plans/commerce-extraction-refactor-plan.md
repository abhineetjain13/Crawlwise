# Plan: Commerce Extraction Refactor

**Created:** 2026-05-05
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Bucket 3 acquisition, Bucket 4 extraction, Bucket 6 selectors/tests, `services/config/*`, acceptance harness

## Goal

Resolve persistent commerce extraction failures from `bugs_triage.md`, `test-sites-issues/CE1-CE4`, and applicable CodeRabbit/Codeant flags by fixing canonical owners. No site-output patching, no downstream compensation, no hidden LLM replacement.

## Acceptance Criteria

- [x] Applicable CodeRabbit/Codeant flags are fixed or documented as not applicable after code verification.
- [x] Ecommerce public output drops `tags`.
- [x] Public variants are flat rows only: `color`, `size`, `sku`, `price`, `currency`, `url`, `image_url`, `availability`, `stock_quantity`.
- [x] Public output never exposes `selected_variant`, `variant_axes`, `available_sizes`, `option_*`, nested `option_values`, or variant `title`.
- [x] Variant DOM extraction is scoped to PDP form/configurator containers and rejects carousel, delivery, search, quantity, tab, and related-product controls.
- [x] Image dedupe keeps highest-resolution unique product assets and normalizes common CDN resize tokens.
- [x] Long text preserves block boundaries, avoids mid-word truncation, removes UI/policy/FAQ/date/phone/object/list artifacts, and emits features as clean rows.
- [x] Structured price/rating/title/identity guards reject known bad shapes without downstream cleanup.
- [x] CE acceptance manifest exists and covers CE1-CE4 URLs with root-cause invariants.
- [x] `python -m pytest tests -q` exits 0.
- [x] `python run_extraction_smoke.py` and `python run_test_sites_acceptance.py` run or blockers are recorded.

## Do Not Touch

- `publish/*` and `pipeline/persistence.py` — extraction bugs must be fixed upstream.
- LLM runtime — LLM remains explicit, degradable backfill only.
- Frontend files — current frontend dirty work is unrelated.
- Per-domain shims in generic paths — use adapters only when platform ownership already exists.

## Slices

### Slice 1: Plan and guard cleanup
**Status:** COMPLETE
**Files:** `docs/plans/ACTIVE.md`, this plan, correctness/config/test owners from `coderabbit_codeant_flags.md`
**What:** Save plan, update ACTIVE, preserve dirty worktree, fix verified guard issues first: HTTP retry `None` guards, equal-URL identity mismatch, structured-object text parsing, JSON-LD `@graph` dict handling, runtime setting validation, config exports, and low-risk test assertion gaps.
**Verify:** Targeted pytest for touched owners.

### Slice 2: Public contract purge
**Status:** COMPLETE
**Files:** `field_value_core.py`, `detail_record_finalizer.py`, adapter/JS variant producers, `field_mappings.py`, tests
**What:** Drop ecommerce `tags`; enforce flat public variants; delete or quarantine legacy selected/axis/option public fields; add structure tests.
**Verify:** `pytest tests -q -k "variant or field_value_core or structure"`

### Slice 3: Variant scope and axis refactor
**Status:** COMPLETE
**Files:** `detail_dom_extractor.py`, `shared_variant_logic.py`, `variant_record_normalization.py`, `config/extraction_rules.py`
**What:** Scope DOM variants to PDP/product-form roots, reject UI/control/cross-product values, remove positional mismatched merges, stop defaulting random numeric axes to `size`, normalize dict/flavor/color values, and support explicit one-size rows.
**Verify:** `pytest tests -q -k "variant or structured_sources"`

### Slice 4: Image canonicalization
**Status:** COMPLETE
**Files:** `field_value_dom.py`, `detail_record_finalizer.py`, adapter image paths as needed
**What:** Normalize CDN resize params/path tokens, malformed URLs, and Shopify CDN aliases in the single image dedupe owner. Prefer highest-resolution unique product assets and reject related/lifestyle carousel bleed.
**Verify:** `pytest tests -q -k "image or crawl_engine or field_value_dom"`

### Slice 5: Text and section fidelity
**Status:** COMPLETE
**Files:** `field_value_dom.py`, `detail_text_sanitizer.py`, `config/extraction_rules.py`
**What:** Preserve block boundaries, split dash/prose features, stop accordion/tab traversal at active PDP content, truncate at word/sentence boundaries, remove UI/policy/FAQ/date/phone/raw object/list noise, and tighten specs/care/material heading semantics.
**Verify:** `pytest tests -q -k "description or features or sanitiz or field_value_dom"`

### Slice 6: Structured price, rating, identity
**Status:** COMPLETE
**Files:** `field_value_candidates.py`, `field_value_core.py`, `detail_price_extractor.py`, `detail_identity.py`, `config/extraction_rules.py`
**What:** Interpret cents only from confirmed price keys, reject negative/placeholder prices, prefer aggregate ratings, strip SKU-like title prefixes only when corroborated, and enforce parent/variant currency parity.
**Verify:** `pytest tests -q -k "price or rating or identity or field_value_core"`

### Slice 7: Acquisition and acceptance ratchet
**Status:** COMPLETE
**Files:** `backend/test_site_sets/commerce_browser_heavy.json`, `harness_support.py`, `run_test_sites_acceptance.py`, `test-sites-issues/*.md`
**What:** Restore/create CE manifest from CE1-CE4 URLs and root-cause invariants, fix missing manifest path, and update issue trackers only after verified runs.
**Verify:** `python run_test_sites_acceptance.py`

## Doc Updates Required

- [x] `docs/INVARIANTS.md` — existing canonical rules already cover public no-tags/flat-variant/text-image-price ownership.
- [x] `docs/CODEBASE_MAP.md` — existing map already points at `backend/test_site_sets/commerce_browser_heavy.json`.
- [x] `docs/ENGINEERING_STRATEGY.md` — no new cross-cutting anti-pattern doc needed beyond current strategy guidance.
- [x] `docs/plans/ACTIVE.md` — current plan pointer updated to `COMPLETE`.

## Notes

- 2026-05-05: This plan supersedes the unfinished `zyte-delta-architectural-fixes-plan.md`; that plan notes slices as done while code still contains legacy variant paths.
- 2026-05-05: Worktree was dirty before implementation. Preserve existing backend listing/category changes and unrelated frontend edits.
- 2026-05-05: Verified `python -m pytest tests -q` passed (`1294 passed, 4 skipped`).
- 2026-05-05: `python run_extraction_smoke.py` skipped because acceptance corpus path was not provided.
- 2026-05-05: `python run_test_sites_acceptance.py` executed but harness output is blocked by missing `HARNESS_EMAIL`; report saved under `backend/artifacts/test_sites_acceptance/20260505T141604Z__full_pipeline__test_sites_tail.json`.
