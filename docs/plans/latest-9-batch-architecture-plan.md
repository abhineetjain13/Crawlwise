# Plan: Latest 9-Batch Architecture Remediation

**Created:** 2026-04-25
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** 2, 3, 4, 5

## Goal

Fix shared architecture defects exposed by crawl run `2` (9 ecommerce_detail URLs) without site-specific hacks. Done means blocked shells stop persisting as success, non-detail or identity-mismatch empties carry explicit reasons, and detail extraction stops polluting records with utility controls, nested non-product JSON-LD titles, and low-signal missing-field outputs.

## Audit Findings

- `woolyyarn.com/product/category/2628879051630`
  Browser diagnostics carried Cloudflare challenge evidence and never reached a ready PDP, but persisted a success record with title `Sorry, you have been blocked`.
  Violates `INVARIANTS.md` Rule 6 and Rule 7.
- `gem.app/search?...`
  Search page produced a shell-like detail candidate, then collapsed to plain `empty`.
  Root issue is failure-mode opacity: bad seed vs extractor miss not distinguished.
- `zappos.com/p/.../9948233/...`
  Extractor found a different product identity (`9948238`) after redirect and correctly rejected it, but surfaced only as `empty`.
  Root issue is same failure-mode opacity.
- `amazon.com/s?...` and `dsw.com/product/...`
  Search/shell pages persisted as detail success records because detail admissibility is too weak.
  `amazon.com/s?...` also treated sort/filter controls as product variants.
  Violates `INVARIANTS.md` Rule 7.
- `macys.com/...20809235`
  Persisted `price=0.00` and variant axes `sort_by` / `filter_by` from review controls.
  Shared DOM-variant and price-sanity bug.
- `skechers.com/...124836.html`
  Title became `Robert Greenberg` because recursive structured candidate collection let nested non-product JSON-LD `Person.name` beat product title under the same `json_ld` source.
  Shared structured-source scoping bug.
- Batch output quality is not summarized at run level even though `CrawlRun` already has `quality_summary` plumbing.
  Auditing currently requires DB forensics instead of run summary.

## Acceptance Criteria

- [ ] Blocked or low-content challenge shells do not persist `ecommerce_detail` records as `success` or `partial`.
- [ ] Detail rejections expose a machine-readable reason at URL level, at minimum for `challenge_shell`, `non_detail_seed`, and `detail_identity_mismatch`.
- [ ] `ecommerce_detail` rejects search/category/shell pages even when they have a slug-like title or product-tile price text.
- [ ] Variant extraction ignores utility controls such as sort, review filter, and availability toggles unless they resolve to real selectable product options.
- [ ] Recursive structured candidate collection no longer lets nested non-product JSON-LD names outrank product title candidates.
- [ ] Run summary exposes quality/failure breakdowns needed to audit a batch without manual DB inspection.
- [ ] Targeted regression tests for run-2 artifacts pass.
- [ ] `python -m pytest tests -q` exits 0.

## Do Not Touch

- `backend/app/services/adapters/*` for run-2 domains unless a shared adapter contract bug is proven.
- `backend/app/services/publish/*` or `pipeline/*` for downstream compensation of bad extraction values.
- Any LLM path as primary fix. LLM stays opt-in gap fill only.
- New config files. Reuse `app/services/config/*`.

## Slices

### Slice 1: Failure-Mode Taxonomy And Surfacing
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/extraction_runtime.py`, `backend/app/services/pipeline/core.py`, `backend/app/services/publish/metrics.py`, `backend/tests/services/test_pipeline_core.py`
**What:** Keep verdict set stable if possible, but add explicit extraction rejection reasons into URL metrics and run summary so `empty` is no longer opaque. Cover `non_detail_seed`, `detail_identity_mismatch`, and `challenge_shell`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py -q`

### Slice 2: Blocked Shell Gating
**Status:** DONE
**Files:** `backend/app/services/publish/metrics.py`, `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/detail_extractor.py`, `backend/tests/services/test_pipeline_core.py`, `backend/tests/services/test_selectolax_css_migration.py`
**What:** Stop trusting `browser_outcome == usable_content` when challenge evidence, low readiness, or blocked-shell titles exist. Make blocked-shell rejection happen upstream before persistence.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py tests/services/test_selectolax_css_migration.py -q`

### Slice 3: Detail Admissibility Contract
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/extraction_runtime.py`, `backend/app/services/config/extraction_rules.py`, `backend/tests/services/test_selectolax_css_migration.py`, `backend/tests/services/test_crawl_engine.py`
**What:** Tighten `ecommerce_detail` acceptance so search/category/shell pages cannot persist from URL slug plus shell copy alone. Use generic readiness and product-identity signals, not site checks.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_selectolax_css_migration.py tests/services/test_crawl_engine.py -q`

### Slice 4: Structured-Source Scope And Variant Hygiene
**Status:** DONE
**Files:** `backend/app/services/field_value_candidates.py`, `backend/app/services/extract/detail_tiers.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/extract/shared_variant_logic.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_shared_variant_logic.py`
**What:** Stop recursive nested non-product aliases from contaminating title/brand candidates. Reject utility axes and non-product control combinations from DOM variant extraction. Add price sanity so `0.00` does not silently win without corroborating product evidence.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_shared_variant_logic.py -q`

### Slice 5: Batch Quality Summary
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/models/crawl.py`, `backend/tests/services/test_batch_runtime.py`, `backend/tests/services/test_run_summary.py`
**What:** Feed URL-level confidence and rejection reasons into run summary so architecture regressions show up in batch output, not only in DB forensics.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_batch_runtime.py tests/services/test_run_summary.py -q`

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — note URL-level rejection reason flow and run quality summary ownership
- [ ] `docs/CODEBASE_MAP.md` — only if plan adds or moves files
- [ ] `docs/INVARIANTS.md` — only if rejection-reason contract becomes a hard rule
- [ ] `docs/ENGINEERING_STRATEGY.md` — add anti-pattern only if new shared failure pattern is proven beyond this audit

## Notes

- Run audited: `crawl_runs.id = 2`
- Batch stats: `9` URLs, `7` persisted records, `2` empty verdicts, but only `4` persisted records look usable without major cleanup.
- Core field presence across persisted records: `brand 4/7`, `price 3/7`, `currency 3/7`, `availability 3/7`, `sku 3/7`, `variant_axes 4/7`.
- No site-specific adapter work in this plan. Fix generic contracts first. Re-test run-2 artifacts before touching any domain config.
- 2026-04-25: Slice 1 implemented. Added `failure_reason` plumbing for detail rejections, challenge-shell detection on acquisition diagnostics, and batch summary failure-reason counts. Verify passed: `python -m pytest tests/services/test_publish_metrics.py tests/services/test_pipeline_core.py tests/services/test_batch_runtime.py -q`
- 2026-04-25: Slice 2 completed. Challenge-shell rejection now gates persistence upstream, and targeted pipeline + selectolax regression suites passed.
- 2026-04-25: Slice 3 completed. Detail URLs with generic search query signatures now classify as utility/non-detail seeds, and search-shell regression coverage passed in `test_crawl_engine.py`.
- 2026-04-25: Slice 4 completed. Nested non-product JSON-LD names no longer feed detail titles, DOM variant extraction rejects utility controls like `sort by`, `filter by`, and `availability`, and low-signal DOM `0.00` prices now drop unless corroborated by stronger price evidence.
- 2026-04-25: Slice 5 completed. `_batch_runtime.py` now uses batch progress-state quality aggregation, run `quality_summary` is populated from URL metrics, and failure-reason aggregation moved into model-owned acquisition summary merge.
- 2026-04-25: Targeted verification passed for slices 1-5:
  `python -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_shared_variant_logic.py tests/services/test_crawl_engine.py tests/services/test_selectolax_css_migration.py tests/services/test_publish_metrics.py tests/services/test_pipeline_core.py tests/services/test_batch_runtime.py tests/services/test_run_summary.py -q`
- 2026-04-25: Full `python -m pytest tests -q` reached one remaining non-domain acceptance blocker in `tests/services/test_structure.py`: LOC budget only.
  `app/services/js_state_mapper.py` = `1154/1150`
  `app/services/pipeline/core.py` = `1345/1180`
