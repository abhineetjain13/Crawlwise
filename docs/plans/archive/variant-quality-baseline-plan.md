> **Status:** DONE
> **Archived:** 2026-04-23
> **Reason:** verified complete

# Plan: Variant Quality Baseline

**Created:** 2026-04-22
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 3, 4

## Goal

Replace verdict-only commerce acceptance with a 20-target quality baseline that uses existing artifact-backed runs plus stable pending sites, then harden extraction only where the baseline shows real output failures: shell/promo false-successes, missing variants, polluted axes, selected-variant price gaps, and listing chrome noise.

## Acceptance Criteria

- [x] Existing acceptance runner supports a curated 20-target site set with artifact-backed review for prior runs.
- [x] Acceptance reports include `quality_verdict`, `observed_failure_mode`, and `quality_checks`.
- [x] The 13 artifact-backed targets and 7 pending targets can be reviewed through the same runner and produce a frozen quality matrix.
- [x] Extraction rejects shell/promo false-success detail pages and improves variant semantics without adding new public schema.
- [x] Focused tests for harness quality checks and variant semantics pass.

## Do Not Touch

- `frontend/*` — out of scope for this backend quality pass
- Publish/export schema — no public contract changes in this slice
- Per-site adapters — fixes must stay generic

## Slices

### Slice 1: Acceptance Baseline
**Status:** DONE
**Files:** `backend/harness_support.py`, `backend/run_test_sites_acceptance.py`, `backend/tests/test_harness_support.py`, `backend/test_site_sets/*`
**What:** Add the curated 20-target manifest, artifact-backed review path, and quality verdict/check reporting on top of the existing acceptance harness.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q`

### Slice 2: Variant Semantics Hardening
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/js_state_mapper.py`, `backend/app/services/extract/shared_variant_logic.py`, relevant tests
**What:** Tighten detail identity rejection, semantic axis normalization, selected-variant price fill, and generic noisy-axis suppression.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py -q`

### Slice 3: Freeze Matrix And Document
**Status:** DONE
**Files:** acceptance report artifacts, `docs/backend-architecture.md`, `docs/CODEBASE_MAP.md`, this plan file
**What:** Run the curated 20-target baseline, capture the frozen failure matrix, update docs, and mark slices complete.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_test_sites_acceptance.py --site-set commerce_variant_quality_v1 --mode full_pipeline`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — acceptance baseline and quality verdict behavior
- [x] `docs/CODEBASE_MAP.md` — curated site-set manifest path
- [x] `docs/BUSINESS_LOGIC.md` — acceptance truthfulness over verdict-only success

## Notes

- Existing worktree already contains partial acceptance and variant changes; integrate with them rather than resetting.
- Frozen 20-target baseline report: `backend/artifacts/test_sites_acceptance/20260422T170231Z__full_pipeline__test_sites_tail.json`
- Post-fix live spot-check report: `backend/artifacts/test_sites_acceptance/20260422T165953Z__full_pipeline__test_sites_tail.json`
- Additional live failure confirmation for SPA/404/shell cases: `backend/artifacts/test_sites_acceptance/20260422T170118Z__full_pipeline__test_sites_tail.json`
- Refreshed 20-target acceptance report after stale-target replacement and stricter harness quality truth: `backend/artifacts/test_sites_acceptance/20260422T171815Z__full_pipeline__test_sites_tail.json`
- Follow-on harness cleanup in this pass refreshed dead `must_pass` URLs from `TEST_SITES.md`, pinned current artifact-backed runs for the repaired detail sites, hardened same-site wrong-product identity checks, and stopped listing sample windows with no real title/url/price rows from passing as clean output.
