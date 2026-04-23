# Plan: India Domain Memory And Agentic Self-Heal

**Created:** 2026-04-23
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** 1, 2, 3, 6, frontend

## Goal

Turn the partially implemented India/domain-recipe workflow into a decision-complete self-healing system that future agents can execute without rediscovering the architecture. Done means the app has one coherent domain-memory workspace for learned selectors, learned acquisition defaults, and learned cookies; the crawl UI makes the first exploratory run intentionally expensive and editable while repeat runs stay quick; completed runs expose enough acquisition and extraction evidence for the user to improve future runs; and reset behavior separates crawl artifacts/runtime data from learned domain memory.

## Review Snapshot

This review was completed during plan drafting so the next agent does not need to re-audit the same entry points before implementing:

- Already implemented:
  - `DomainRunProfile` persistence and lookup exist in [backend/app/models/crawl.py](/c:/Projects/pre_poc_ai_crawler/backend/app/models/crawl.py:540), [backend/app/services/domain_run_profile_service.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/domain_run_profile_service.py:1), and [backend/app/api/crawls.py](/c:/Projects/pre_poc_ai_crawler/backend/app/api/crawls.py:224).
  - Crawl Studio already has `Quick` and `Advanced` form shaping plus saved-profile auto-load in [frontend/components/crawl/crawl-config-screen.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/components/crawl/crawl-config-screen.tsx:113).
  - Completed runs already expose a first-pass domain recipe panel in [frontend/components/crawl/crawl-run-screen.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/components/crawl/crawl-run-screen.tsx:161) backed by [backend/app/services/review/__init__.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/review/__init__.py:337).
- Confirmed gaps:
  - The domain-recipe payload still returns empty affordance buckets and only derives `browser_required`; it does not expose acquisition-learning inputs such as timings, mode choice, escalation path, or reusable interaction hints.
  - The completed-run workflow saves selectors and run profiles, but it does not let the user keep/reject extracted fields in a way that teaches future extraction behavior.
  - The Domain Memory page is selector-only in [frontend/app/selectors/manage/page.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/app/selectors/manage/page.tsx:23); it does not show saved run profiles, cookies, or compact per-domain learning state.
  - Reset is still one destructive action in [frontend/components/layout/app-shell.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/components/layout/app-shell.tsx:319) and [backend/app/services/dashboard_service.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/dashboard_service.py:87); learned memory is not separable from crawl data/artifacts.
  - Cookie persistence is run-scoped and unconditional in [backend/app/services/acquisition/cookie_store.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/cookie_store.py:60) and [backend/app/services/acquisition/browser_runtime.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/browser_runtime.py:391); it is not domain memory and it rewrites even when the normalized state is unchanged.

## Acceptance Criteria

- [x] The implementation includes a documented review slice for the current India domain recipes behavior with concrete findings, file owners, and explicit follow-on decisions.
- [x] Domain memory becomes a single product surface composed from separate persistence owners:
  - selectors remain domain-and-surface scoped
  - acquisition defaults remain domain-and-surface scoped
  - cookies become domain-scoped acquisition memory
- [x] Crawl Studio preserves the first-run versus repeat-run split:
  - exploratory setup remains visible and editable
  - quick mode remains the repeat-run path with saved defaults
  - explicit user edits still win for the current run
- [x] Completed runs expose acquisition-learning evidence:
  - actual mode used
  - escalation strategy used
  - time/cost signals from run summary
  - editable saved acquisition profile
- [x] Completed runs expose extraction-learning evidence:
  - used selectors
  - keep/reject field decisions
  - selector promotion and selector rejection paths that affect future runs
- [x] Domain Memory UI shows compact per-domain memory across selectors, saved run profile, and saved cookies without requiring the user to navigate separate tools for the common workflow.
- [x] Reset behavior is split into two explicit actions:
  - reset crawl data/artifacts/runtime state
  - reset learned domain memory only
- [x] Cookie persistence writes only when the normalized cookie/local-storage state differs from the already saved domain cookie memory and is reused by acquisition on future runs for the same domain.
- [x] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.

## Do Not Touch

- `backend/app/services/detail_extractor.py` variant-candidate architecture beyond already-owned selector trace usage. This plan must not re-open AP-12 work.
- Generic shared acquisition/extraction paths with site-name hardcoding. No India-domain special cases in shared runtime.
- LLM provider/runtime ownership. LLM stays optional and out of the primary self-heal loop.
- Existing selector CRUD semantics in `backend/app/services/selectors_runtime.py` except where required for reject/deactivate behavior.

## Locked Decisions

### 1. Memory Architecture

- The product surface is one "Domain Memory" workspace, but storage stays typed and separated.
- Keep `DomainMemory` as the owner of selector rules for normalized `(domain, surface)`.
- Keep `DomainRunProfile` as the owner of acquisition/run defaults for normalized `(domain, surface)`.
- Add a dedicated domain cookie memory owner keyed by normalized domain only.
- Do not overload `DomainMemory.selectors` with cookies.
- Do not move run profile JSON into selector rows or selector payloads.

### 2. First-Run Versus Repeat-Run Contract

- Keep the existing `Quick` and `Advanced` split rather than inventing a third crawl mode.
- `Advanced` is the paid setup cost path: richer diagnostics, selector editing, and acquisition tuning.
- `Quick` is the repeat-run path: saved defaults plus minimal controls.
- Future work should improve copy and defaults, not re-architect the form again.

### 3. Completed-Run Learning Contract

- The completed-run Domain Recipe panel is the primary learning workflow.
- Acquisition learning is saved into `DomainRunProfile`.
- Extraction learning is driven from actual used selector traces and field decisions from the completed run.
- Keep/reject decisions are field-local and must not mutate unrelated fields.
- Rejecting a selector-backed field must not silently delete data; it should either deactivate or explicitly demote the offending selector rule for future runs.
- Promotion and rejection act only on the normalized `(domain, surface)` memory scope.

### 4. Cookie Memory Contract

- Cookies are acquisition memory, not run artifacts.
- Cookie persistence is domain-scoped because reuse is driven by host acquisition, not by surface semantics.
- Persist only normalized cookies and local-storage rows that survive existing cookie policy checks.
- Skip writes when the normalized state fingerprint is unchanged.
- Domain cookie memory must be reusable by browser acquisition before navigation on future runs for the same domain.

### 5. Reset Contract

- Replace the current single reset flow with two backend endpoints and two UI buttons.
- `Reset Crawl Data` clears runs, records, logs, review artifacts tied to runs, artifacts, runtime caches, and run-scoped temporary cookie files.
- `Reset Domain Memory` clears selectors, domain run profiles, domain cookie memory, and domain-level review/learning state.
- The two reset actions must have distinct confirmations and success messages.

### 6. Delete / Simplify Requirement

This plan is not allowed to be additive-only. Implementation must remove or simplify at least these existing pain points:

- delete the one-button global reset UX
- delete unconditional cookie rewrites for unchanged state
- delete the selector-only framing of the Domain Memory page
- delete any duplicate domain-memory loading paths that bypass the new composite workspace contract

## Slices

### Slice 1: Lock Review Findings For India Domain Recipes
**Status:** DONE
**Files:** `docs/plans/india-domain-recipes-plan.md`, `backend/app/services/review/__init__.py`, `frontend/components/crawl/crawl-run-screen.tsx`, `frontend/components/crawl/crawl-config-screen.tsx`, `frontend/app/selectors/manage/page.tsx`, `backend/app/services/acquisition/cookie_store.py`, `backend/app/services/dashboard_service.py`
**What:** Convert the review snapshot above into implementation-ready notes inside the plan as code changes land. The first agent executing this plan must preserve the findings and append concrete status notes instead of re-reviewing the same files from scratch.
**Verify:** Review snapshot still matches code before moving to Slice 2; any conflict is written in `Notes`.

### Slice 2: Add Domain Cookie Memory And Dedupe Writes
**Status:** DONE
**Files:** `backend/app/models/crawl.py`, `backend/alembic/versions/*`, `backend/app/services/acquisition/cookie_store.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/domain_utils.py` if needed, `backend/tests/services/test_domain_memory_service.py`, add a focused cookie-memory test file if required
**What:** Introduce a dedicated domain cookie memory owner and route browser acquisition through it. Load domain cookie memory before creating browser contexts. Persist only when the normalized state fingerprint changes. Keep run-scoped temp files only as ephemeral execution cache if still needed, otherwise simplify them away. This slice owns the cookie review/improvement requested by the user.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_domain_memory_service.py tests/services/test_crawl_fetch_runtime.py -q`

### Slice 3: Expose Acquisition Learning Data In The Domain Recipe Payload
**Status:** DONE
**Files:** `backend/app/services/review/__init__.py`, `backend/app/schemas/crawl.py`, `frontend/lib/api/types.ts`, `backend/tests/services/test_review_service.py`, `backend/tests/services/test_crawls_api_domain_recipe.py`
**What:** Extend the domain-recipe payload so the completed-run screen gets acquisition-learning inputs from the run that actually completed:
- saved profile currently in force
- actual fetch method used
- browser escalation reason if any
- timing and strategy summary from `run.result_summary.acquisition_summary`
- affordance hints derived from the successful run instead of empty placeholders
This slice must not invent a new metrics system; it should reuse existing run summary and source trace owners.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_review_service.py tests/services/test_crawls_api_domain_recipe.py -q`

### Slice 4: Add Field Keep/Reject Learning For Future Extraction
**Status:** DONE
**Files:** `backend/app/services/review/__init__.py`, `backend/app/api/crawls.py`, `backend/app/schemas/crawl.py`, `backend/app/services/selectors_runtime.py`, `backend/app/services/domain_memory_service.py`, `frontend/components/crawl/crawl-run-screen.tsx`, `frontend/lib/api/index.ts`, `frontend/lib/api/types.ts`, `backend/tests/services/test_selectors_runtime.py`, `backend/tests/services/test_crawls_api_domain_recipe.py`, `frontend/components/crawl/crawl-run-screen.test.tsx`
**What:** Add explicit keep/reject actions on completed-run field results. The minimal v1 contract is:
- keep can promote or preserve the selector/source that produced the accepted field
- reject on selector-backed fields deactivates or demotes the offending selector for the exact `(domain, surface)`
- reject on non-selector-backed fields is recorded as review feedback but does not fabricate selector changes
- UI must show the actual selector/source used for the field when available
Do not replace the existing review flow; extend it so rejected extraction evidence can teach future runs without downstream hacks.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_selectors_runtime.py tests/services/test_crawls_api_domain_recipe.py -q`

### Slice 5: Rework The Domain Memory Page Into A Compact Learning Workspace
**Status:** DONE
**Files:** `frontend/app/selectors/manage/page.tsx`, `frontend/lib/api/index.ts`, `frontend/lib/api/types.ts`, supporting backend list/read endpoints in `backend/app/api/selectors.py` or `backend/app/api/crawls.py`, `backend/tests/services/test_selectors_api.py`
**What:** Turn Domain Memory into the main compact per-domain workspace. For each domain show:
- selector memory by surface
- saved run profile by surface
- saved domain cookies summary
- recent learned/rejected selector actions if available
Keep the Selector Tool for manual testing; do not duplicate that editor wholesale inside the Domain Memory page. The goal is compact inspection and correction, not a second full selector lab.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_selectors_api.py -q`

### Slice 6: Split Reset Into Crawl Data Reset And Domain Memory Reset
**Status:** DONE
**Files:** `backend/app/api/dashboard.py`, `backend/app/services/dashboard_service.py`, `frontend/components/layout/app-shell.tsx`, add/update focused backend tests in `backend/tests/services/test_dashboard_service.py`
**What:** Replace the single reset action with two explicit flows:
- crawl-data reset
- domain-memory reset
`Reset Domain Memory` must clear selector memory, domain run profiles, domain cookies, and domain learning records without deleting users or LLM config. `Reset Crawl Data` must stop clearing learned memory. Update button labels and confirmation copy to make the difference obvious.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_dashboard_service.py -q`

### Slice 7: Tighten Crawl Studio For First-Run Setup Versus Repeat Runs
**Status:** DONE
**Files:** `frontend/components/crawl/crawl-config-screen.tsx`, `frontend/components/crawl/crawl-config-screen.test.ts`, `frontend/components/crawl/crawl-config-screen.prefill.test.tsx`, `backend/app/services/crawl_crud.py`, `backend/tests/services/test_crawl_service.py`
**What:** Review and refine the existing Quick/Advanced split so it clearly expresses the paid setup cost versus repeat-run contract. The outcome should be:
- Quick mode uses saved profile defaults and minimal controls
- Advanced mode exposes acquisition tuning and selector editing clearly
- the resolved final profile is still snapshotted once at run creation
- no duplicate flags or parallel settings blobs remain after the cleanup
This slice is mainly cleanup and contract hardening, not a full UI rewrite.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_service.py -q`

### Slice 8: Complete The Run-Complete Self-Heal Workflow
**Status:** DONE
**Files:** `frontend/components/crawl/crawl-run-screen.tsx`, `frontend/components/crawl/crawl-run-screen.test.tsx`, any supporting backend endpoints from Slices 3-4
**What:** Finish the Domain Recipe page so the user can:
- see how the crawl succeeded
- edit and save future acquisition defaults
- keep/reject field outputs
- promote or demote used selectors
- understand what will be remembered for future runs
This is the user-visible closure of the architecture. Do not hide learning decisions behind the standalone selector page.
**Verify:** `cd frontend; npm test -- crawl-run-screen.test.tsx crawl-config-screen.test.ts crawl-config-screen.prefill.test.tsx`

### Slice 9: Docs And Closure
**Status:** DONE
**Files:** `docs/backend-architecture.md`, `docs/BUSINESS_LOGIC.md`, `docs/CODEBASE_MAP.md` if storage ownership changes, `docs/INVARIANTS.md` if cookie/domain-memory scope changes, `docs/ENGINEERING_STRATEGY.md` only if a new anti-pattern appears
**What:** Update canonical docs after implementation. Record the final storage owners, reset contract, domain-memory workspace behavior, and cookie-memory rules. Close the plan only after targeted tests and the full backend suite pass.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — add domain cookie memory, composite domain-memory workspace, and split reset behavior
- [x] `docs/BUSINESS_LOGIC.md` — update first-run versus repeat-run workflow and completed-run learning decisions
- [x] `docs/CODEBASE_MAP.md` — update if a new cookie-memory owner or API surface is added
- [x] `docs/INVARIANTS.md` — update if domain-memory scope expands beyond selector memory contracts
- [x] `docs/ENGINEERING_STRATEGY.md` — update only if implementation uncovers a recurring anti-pattern

## Notes

- Execution read order for future agents on this plan only:
  1. [backend/app/services/review/__init__.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/review/__init__.py:337)
  2. [backend/app/services/domain_run_profile_service.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/domain_run_profile_service.py:1)
  3. [backend/app/services/acquisition/cookie_store.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/cookie_store.py:1)
  4. [backend/app/services/acquisition/browser_runtime.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/browser_runtime.py:199)
  5. [backend/app/services/dashboard_service.py](/c:/Projects/pre_poc_ai_crawler/backend/app/services/dashboard_service.py:87)
  6. [frontend/components/crawl/crawl-config-screen.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/components/crawl/crawl-config-screen.tsx:113)
  7. [frontend/components/crawl/crawl-run-screen.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/components/crawl/crawl-run-screen.tsx:161)
  8. [frontend/app/selectors/manage/page.tsx](/c:/Projects/pre_poc_ai_crawler/frontend/app/selectors/manage/page.tsx:23)
- The previous contents of this file were stale relative to current code. This version supersedes them.
- `docs/plans/ACTIVE.md` previously pointed at a missing file. The pointer is corrected as part of this planning task because `PLAN_PROTOCOL.md` requires an active-plan target.
- If implementation pressure makes a new cookie-memory table feel too heavy, document the reason in `Notes` before choosing an alternative. Do not silently overload selector memory.
- 2026-04-23: The Domain Memory workspace now groups selector memory with saved domain run profiles in the frontend, backed by `GET /api/crawls/domain-run-profiles`. Domain-scoped cookie memory is still pending and is called out explicitly in the UI instead of being simulated.
- 2026-04-23: Crawl Studio now keeps domain, studio mode, and LLM enablement in the right rail while the detailed crawl settings live in a three-column settings section below the main configuration area.
- 2026-04-23: Implemented the domain-memory backend owners `DomainCookieMemory` and `DomainFieldFeedback`, added Alembic revision `20260423_0014`, and wired browser runtime reuse so later runs load domain-scoped cookie/local-storage state before navigation and only rewrite it when the normalized fingerprint changes.
- 2026-04-23: Completed-run Domain Recipe now exposes acquisition evidence, field-learning rows, and keep/reject actions. Selector-backed rejects deactivate exact saved selectors for the same `(domain, surface)` while non-selector rejects are recorded as feedback without fabricating selector edits.
- 2026-04-23: Domain Memory now shows cookie-memory summaries alongside selectors and saved run profiles, and the app shell reset flow is split into `Reset Crawl Data` and `Reset Domain Memory`.
- 2026-04-23 verification:
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_context.py tests/services/test_review_service.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_dashboard_service.py tests/services/test_selectors_runtime.py tests/services/test_crawl_service.py -q` → pass
  - `cd frontend; npm test -- crawl-run-screen.test.tsx crawl-config-screen.test.ts crawl-config-screen.prefill.test.tsx` → pass
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_test_sites_acceptance.py --site-set commerce_variant_quality_v1 --mode full_pipeline --limit 5` → pass after applying Alembic upgrade
- 2026-04-23: Closed the remaining extraction regressions in `detail_extractor.py` without changing the field-by-field candidate architecture. Structured single-value axes now stay selectable when they are part of real variant identity, and sparse DOM rows no longer overwrite richer selected-variant identity from stronger sources.
- 2026-04-23 final verification:
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` → pass (`626 passed, 4 skipped`)
  - `cd frontend; npm test -- crawl-run-screen.test.tsx crawl-config-screen.test.ts crawl-config-screen.prefill.test.tsx` → pass
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_test_sites_acceptance.py --site-set commerce_variant_quality_v1 --mode full_pipeline --limit 5` → pass, report `artifacts/test_sites_acceptance/20260423T065735Z__full_pipeline__test_sites_tail.json`; remaining Custom Ink/B&H quality notes stay in the manifest’s `tracked_issue` bucket rather than blocking plan completion
- 2026-04-23 follow-up closure:
  - Completed-run UI was tightened so persisted domain-memory concerns now live on `Domain Memory`, while the run screen keeps only post-run `Learning` and `Run Config` tabs.
  - Added `GET /api/crawls/domain-memory/field-feedback` so the Domain Memory workspace can surface recent keep/reject decisions alongside selectors, run profiles, and cookie memory.
  - Hardened artifact-first Belk extraction without site hardcoding:
    - blocked PerimeterX challenge HTML is rejected before detail extraction materializes fake records
    - listing cards now prefer trustworthy image title hints over brand-only or review-count title pollution
  - Focused verification for the follow-up slice:
    - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_detail_extractor_structured_sources.py -q` → pass
    - `cd frontend; npm test -- crawl-run-screen.test.tsx domain-memory-manage-page.test.tsx` → pass
