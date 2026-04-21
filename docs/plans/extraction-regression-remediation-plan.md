# Plan: Close Extraction Regressions From Old-to-New Port

**Created:** 2026-04-21
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** 2, 3, 4, 7

## Goal

Fix FM-1 through FM-5 and the still-missing LLM last-resort path without adding new cross-cutting layers. Done means listing extraction ranks candidate sets by quality instead of accepting the first noisy output, detail expansion and DOM-variant handling recover the old app's missing behaviors, protected hosts get paced and challenge recovery before failure, markdown generation stops crashing on complex HTML, and the pipeline gains an opt-in direct-record LLM fallback when deterministic extraction stays weak.

## Acceptance Criteria

- [x] Listing extraction chooses richer rendered-card/DOM results over misleading structured or visual-noise results.
- [x] Thin-listing retry can trigger on low-quality browser extraction, not only on low record count.
- [x] Detail expansion is ordered, field-aware, bounded, and safe against commerce/auth actions.
- [x] DOM variant fallback materializes `variants` rows and accurate `variant_count`.
- [x] Browser challenge recovery waits/retries generically for protected hosts and host pacing is applied in crawl fetches.
- [x] Markdown generation tolerates attr-less nodes in both cleanup passes.
- [x] Direct-record LLM extraction is wired as an opt-in, config-backed fallback with diagnostics and graceful failure.
- [x] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.

## Do Not Touch

- `frontend/*` -- no contract or UX changes required.
- `backend/app/api/*` -- no route shape changes required.
- `backend/app/services/publish/*` -- do not compensate downstream for upstream extraction failures.
- `backend/app/services/adapters/*` -- no site-specific adapter hacks in this pass unless a focused failing test proves the generic path cannot own the fix.

## Slices

### Slice 1: Listing Quality Ranking + Rendered Card Capture
**Status:** COMPLETE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/pipeline/core.py`, related listing/pipeline/browser tests
**What:** Add rendered-card capture, normalize it in extraction, score candidate record sets, and expand thin-listing retry gating to low-quality results.
**Verify:** focused listing/pipeline/browser pytest subset

### Slice 2: Deterministic Detail Expansion + DOM Variants
**Status:** COMPLETE
**Files:** `backend/app/services/acquisition/browser_detail.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/detail_extractor.py`, related tests
**What:** Replace flat selector expansion with ordered bounded queries and materialize DOM fallback variants into row data.
**Verify:** focused browser expansion/detail extraction pytest subset

### Slice 3: Protected Host Pacing + Challenge Recovery + Markdown Hardening
**Status:** COMPLETE
**Files:** `backend/app/services/acquisition/pacing.py`, `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/acquisition/browser_page_flow.py`, related runtime/browser tests
**What:** Apply host pacing in fetch flow, escalate protected-host backoff on challenge signals, add bounded challenge recovery, and harden markdown cleanup.
**Verify:** focused fetch/runtime/browser pytest subset

### Slice 4: Direct-Record LLM Extraction
**Status:** COMPLETE
**Files:** `backend/app/services/llm_tasks.py`, `backend/app/services/llm_runtime.py`, `backend/app/services/llm_config_service.py`, `backend/app/services/config/field_mappings.exports.json`, `backend/app/data/prompts/*`, `backend/app/services/pipeline/core.py`, related LLM/pipeline tests
**What:** Add the prompt task, snapshot/config support, and a gated pipeline fallback that only replaces deterministic output when the result is stronger.
**Verify:** focused LLM/pipeline pytest subset

### Slice 5: Final Verification + Docs
**Status:** COMPLETE
**Files:** `docs/backend-architecture.md`, this plan file, `docs/plans/ACTIVE.md`
**What:** Run full backend suite, update slice statuses, and document stable architecture changes only.
**Verify:** full backend pytest command

## Doc Updates Required

- [x] `docs/backend-architecture.md` -- acquisition/extraction/runtime fallback behavior changes
- [ ] `docs/CODEBASE_MAP.md` -- only if a new long-lived owner file is added
- [ ] `docs/INVARIANTS.md` -- not expected unless a contract truly changes
- [ ] `docs/ENGINEERING_STRATEGY.md` -- not expected unless a new anti-pattern is discovered

## Notes

- Reuse the existing recovery/markdown groundwork from `old-app-recovery-features-plan.md`; this plan closes the remaining failure-report gaps.
- Keep LOC down by extending current owners and shared helpers before considering any new module.
- Final verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` on 2026-04-21.
