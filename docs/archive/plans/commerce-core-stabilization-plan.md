> **Status:** DONE
> **Archived:** 2026-04-23
> **Reason:** verified complete

# Plan: Commerce Core Stabilization and Modularity Pass

**Created:** 2026-04-22
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 2, 3, 4

## Goal

Stabilize the commerce-only crawl path without a big-bang rewrite. This plan adds a curated browser-heavy commerce regression gate, makes acceptance/audit surfaces authoritative, tightens shared listing candidate quality selection so utility chrome stops winning, and improves browser-runtime evidence when traversal and rendered extraction diverge.

## Acceptance Criteria

- [x] Commerce acceptance runs can use a curated browser-heavy site set with bucketed expectations and explicit surfaces.
- [x] Explicit acceptance surfaces are never silently overridden by URL inference.
- [x] Generic commerce listing extraction rejects utility/noise-leading candidate sets that previously produced false-positive successes.
- [x] Browser-heavy commerce failures emit actionable diagnostics for the failing stage and rendered/traversal evidence counts.
- [x] Focused pytest coverage passes for harness, browser runtime, and commerce listing regressions.

## Do Not Touch

- `frontend/*` — out of scope for this pass
- `app/services/llm_*` — LLM behavior is not part of commerce-core stabilization
- `app/services/review/*` — review workflows are not being refactored here

## Slices

### Slice 1: Commerce Gate And Acceptance Authority
**Status:** DONE
**Files:** `docs/plans/ACTIVE.md`, `backend/run_test_sites_acceptance.py`, `backend/harness_support.py`, `backend/tests/test_harness_support.py`, `backend/test_site_sets/commerce_browser_heavy.json`
**What:** Add a standalone commerce plan pointer, create a curated browser-heavy commerce acceptance set, preserve explicit surfaces, and capture audit output rich enough to flag utility-chrome false successes.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q`

### Slice 2: Shared Listing Candidate Quality Selection
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/extract/listing_candidate_ranking.py`, `backend/tests/services/test_crawl_engine.py`
**What:** Keep `listing_extractor.py` orchestration-focused while moving commerce-quality filtering and candidate-set scoring into shared extraction helpers. Reject support/help/shipping/CTA rows when they outrank or fully replace real products.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py -q -k "listing"`

### Slice 3: Browser-Heavy Commerce Handoff Diagnostics
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_recovery.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/browser_page_flow.py`, `backend/tests/services/test_browser_expansion_runtime.py`
**What:** Improve rendered-card capture for multi-anchor commerce cards, expose rendered/traversal evidence counts, and report browser failure stage/timeout phase explicitly so hangs and zero-row browser listings are diagnosable.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py -q`

### Slice 4: Commerce Regression Pass
**Status:** DONE
**Files:** `docs/backend-architecture.md`, `docs/CODEBASE_MAP.md`, `docs/BUSINESS_LOGIC.md`
**What:** Re-run focused commerce verification, update canonical docs with acceptance authority and shared extraction ownership boundaries, and leave the gate wired for follow-on browser-heavy site remediation.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py tests/services/test_crawl_engine.py tests/services/test_browser_expansion_runtime.py -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — document curated commerce acceptance gating and browser diagnostics fields
- [x] `docs/CODEBASE_MAP.md` — include the curated commerce site-set asset
- [x] `docs/BUSINESS_LOGIC.md` — note explicit-surface authority in acceptance/harness flows

## Notes

- This is a separate standalone plan and intentionally does not modify the Zara/remediation plan.
- Initial curated commerce set is based on the 2026-04-22 browser-heavy audit plus Desertcart as a named repro.
- Nykaa remains a named repro from user reports, but no stable repo-local acceptance URL exists yet; keep it tracked separately until a canonical URL is pinned.
- Slice 1 verification: `python -m pytest tests/test_harness_support.py -q`
- Slice 2 verification: shared listing-candidate regressions are covered in `tests/services/test_crawl_engine.py`
- Slice 3 verification: stage-aware browser failure diagnostics and rendered evidence counters are covered in `tests/services/test_browser_expansion_runtime.py`
- Slice 4 smoke verification: `run_test_sites_acceptance.py --site-set commerce_browser_heavy --mode full_pipeline --limit 3` now exercises the manifest-driven gate and correctly flags `Practice Software Testing Detail` as `detail_identity_mismatch` instead of a false pass. Remaining work is to fix that upstream detail extraction path and then expand the commerce batch beyond the initial smoke subset.
- 2026-04-22 follow-up tightened the acceptance gate and browser tail behavior in the owner modules: unbucketed acceptance rows now fail unless they end in `success`, utility-only rendered titles such as `Make Offer / Details` are rejected upstream in listing extraction instead of being reclassified in harness reporting, and rendered/visual browser artifact capture is bounded with dedicated phase timings so heavy listing pages such as Nykaa/FirstCry-class repros cannot spend most of the run inside an opaque post-render capture stall. Verification passed with `pytest tests/test_harness_support.py tests/services/test_crawl_engine.py tests/services/test_browser_expansion_runtime.py -q`.
