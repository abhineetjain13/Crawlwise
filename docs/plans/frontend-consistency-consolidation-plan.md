# Plan: Frontend Consistency Consolidation

**Created:** 2026-04-22
**Agent:** Codex
**Status:** DONE
**Touches buckets:** Frontend app shell and operator surfaces

## Goal

Make the frontend operator surfaces feel like one coherent product by consolidating repeated section shells, headers, and empty/loading treatments into shared UI patterns. Done means the relevant pages use the same structural rhythm with fewer lines of code and without changing the existing color system.

## Acceptance Criteria

- [x] Shared operator-page wrappers replace repeated page section chrome
- [x] Dashboard, runs, jobs, selectors, domain memory, and admin pages use the shared patterns consistently
- [x] Frontend LOC is net negative for the previously clean touched surface files
- [x] `npm run lint` and `npm run build` exit 0 in `frontend`

## Do Not Touch

- `frontend/components/crawl/*` — out of scope for this consolidation slice
- `frontend/app/globals.css` color tokens — user requested no color changes
- `backend/*` — unrelated to frontend consistency work

## Slices

### Slice 1: Shared Page Surface Patterns
**Status:** DONE
**Files:** `frontend/components/ui/patterns.tsx`, relevant frontend page files
**What:** Add or extend shared operator-page wrappers for section framing, headers, and simple stat rows so page files stop hand-rolling the same structure.
**Verify:** touched pages compile and render through existing frontend tests

### Slice 2: Page Refactor
**Status:** DONE
**Files:** `frontend/app/dashboard/page.tsx`, `frontend/app/runs/page.tsx`, `frontend/app/jobs/page.tsx`, `frontend/app/selectors/page.tsx`, `frontend/app/selectors/manage/page.tsx`, `frontend/app/admin/users/page.tsx`, `frontend/app/admin/llm/page.tsx`
**What:** Replace repeated cards, section headers, and summary blocks with the shared patterns while preserving behavior and existing colors.
**Verify:** `npm test`

## Doc Updates Required

- [ ] `docs/frontend-architecture.md` — note the shared operator-page surface patterns if this becomes a stable frontend convention
- [ ] `docs/CODEBASE_MAP.md` — only if files are added or moved
- [ ] `docs/INVARIANTS.md` — no contract change expected
- [ ] `docs/ENGINEERING_STRATEGY.md` — no new anti-pattern expected

## Notes

- User requested consistency and consolidation with net negative LOC.
- No color changes were made in this slice.
- Shared operator-page structure now lives in `frontend/components/ui/patterns.tsx` via `SectionCard`, `SurfaceSection`, and `MutedPanelMessage`.
- Verification:
  - `npm run lint` ✅
  - `npm run build` ✅
- `npm test` still has unrelated pre-existing failures in `components/crawl/shared.test.ts` and `components/crawl/crawl-run-screen.test.tsx`, which were out of scope for this frontend consistency slice.
