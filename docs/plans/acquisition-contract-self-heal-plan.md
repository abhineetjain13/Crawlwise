# Plan: Acquisition Contract Self-Heal

**Created:** 2026-04-30
**Agent:** Codex
**Status:** CLOSED
**Touches buckets:** acquisition, orchestration, review/domain memory, frontend, tests, docs

## Goal

Persist successful acquisition paths as editable domain run-profile contracts so future crawls avoid known-bad engine/order regressions, can reuse safe browser cookies through curl handoff, and expose only useful XPath learning signals to users.

## Acceptance Criteria

- [x] Successful acquisition + extraction autosaves an acquisition contract in `DomainRunProfile`.
- [x] Future domain/surface runs use the saved contract unless explicit run settings override it.
- [x] A real Chrome contract skips Patchright until stale.
- [x] A cookie-backed contract tries curl handoff first, then proven browser fallback.
- [x] Repeated quality failures mark the contract stale and return to normal auto policy.
- [x] Learning tab shows only successful XPath winners, not duplicate extracted data.
- [x] `python -m pytest tests -q` exits 0.

## Do Not Touch

- `publish/*` — no downstream compensation for acquisition or extraction bugs.
- `detail_extractor.py` detail candidate architecture — out of scope.
- Generic LLM paths — unrelated.

## Slices

### Slice 0: Contract Tests Before Implementation
**Status:** DONE
**Files:** backend and frontend focused tests
**What:** Add failing coverage for contract autosave, real Chrome preference, curl handoff, stale fallback, explicit override, and XPath-only learning output.
**Verify:** Focused tests fail for missing behavior before implementation.

### Slice 1: Profile Contract Shape
**Status:** DONE
**Files:** run profile schemas/types/UI and profile normalization
**What:** Add backward-compatible `acquisition_contract` to saved run profiles and Run Config.
**Verify:** Profile API and UI tests pass for old and new profile shapes.

### Slice 2: Autosave From Successful Runs
**Status:** DONE
**Files:** pipeline orchestration and domain run profile service
**What:** Autosave contract after quality success only; do not save blocked, empty, zero-normalized, or rejected-detail attempts.
**Verify:** Autosave tests pass.

### Slice 3: Runtime Contract Application
**Status:** DONE
**Files:** run creation/acquisition runtime
**What:** Apply saved contract before acquisition, try curl cookie handoff first when enabled, and prefer proven browser engine.
**Verify:** Runtime contract tests pass.

### Slice 4: Staleness And Recovery
**Status:** DONE
**Files:** pipeline/domain run profile service
**What:** Count quality failures, mark stale after threshold, and rewrite contract on recovery success.
**Verify:** Staleness tests pass.

### Slice 5: Learning Tab XPath Cleanup
**Status:** DONE
**Files:** review recipe API and run screen UI
**What:** Return/render only successful XPath winners in Learning.
**Verify:** Backend and frontend learning tests pass.

## Doc Updates Required

- [x] `docs/BUSINESS_LOGIC.md` — acquisition contract behavior and reset ownership.
- [x] `docs/INVARIANTS.md` — learned acquisition path contract.
- [x] `docs/backend-architecture.md` — runtime flow description changed.

## Notes

- Host memory remains short-lived block/success telemetry.
- `DomainRunProfile` is the editable saved contract.
- Cookie memory remains engine-scoped and poison-filtered.
- Focused backend verification: `28 passed, 11 warnings`.
- Focused frontend learning verification: `3 passed, 22 skipped`.
- Full backend verification: `1098 passed, 4 skipped, 11 warnings`.
- Closure check: field contract is explicit user fields plus limited ecommerce defaults (`price`, `title`, `image_url`); successful domain acquisition/selector paths are reused until explicit override/reset or stale acquisition-quality failure.
