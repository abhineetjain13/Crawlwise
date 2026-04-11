# Backend Structural Consolidation Plan: Noise Ownership, Package Boundaries, and 5k+ LOC Reduction

## Summary

This plan replaces the narrower restructuring plan. The primary concern is not just package cleanup. The primary concern is that **noise reduction, sanitization, normalization, and extraction arbitration are fragmented across too many layers**, which creates both correctness failures and sustained code growth.

The refactor must therefore do two things in parallel:

- **Restructure package boundaries and god modules** so ownership is explicit and imports are controlled.
- **Collapse duplicated noise/normalization/arbitration logic into a single coherent path** so the codebase stops re-implementing the same concern in multiple places.

This document is the tracker for that work. The parallel god-file decomposition plan remains active, but all future decomposition must conform to the rules below.

## Implementation Snapshot

Completed in the initial structural pass:

- saved this tracker in `docs/plans/`
- updated `desired-backend-architecture.md` to encode shared normalization/noise ownership
- aligned `extract/__init__.py` to the current package-surface policy with deferred candidate-processing note
- aligned `acquisition/__init__.py` to the current package-surface policy with deferred browser-pool note
- verified `py_compile` passes for `pipeline/__init__.py`, `extract/__init__.py`, and `acquisition/__init__.py`
- verified `python -W error` import of `app.services.acquisition.traversal` does not raise a `SyntaxWarning`

Completed in the current Slice 1 pass:

- expanded `extract/noise_policy.py` to own shared social-host suppression, listing noise-group detection, reusable noise-container stripping, site-chrome detection, and noisy product-attribute rejection
- removed local generic-noise wrappers from `listing_extractor.py`, `variant_extractor.py`, `detail_extractor.py`, and `variant_builder.py`
- moved generic UI-noise stripping into `extract/noise_policy.py` and removed the remaining local implementation from `field_type_classifier.py`
- aligned `CLAUDE.md` and `docs/INVARIANTS.md` with explicit canonical-output and no-schema-pollution requirements for listing/detail extraction
- added direct shared-noise regression coverage in `backend/tests/services/extract/test_noise_policy.py`
- removed the dead `backend/app/services/knowledge_base/` directory after confirming it only contained stale bytecode
- cleared the structural import-hygiene gate by removing dead imports and making the pipeline verdict facade use a public `compute_verdict()` symbol

Open baseline blockers discovered during verification:

- `ruff check backend/app/services/ --select F401,F811 -q` now passes after config/extract/pipeline cleanup
- targeted regression gates now pass:
  - `pytest backend/tests/services/extract/test_noise_policy.py -q --tb=short`
  - `pytest backend/tests/services/extract/test_detail_extractor.py -q --tb=short`
  - `pytest backend/tests/services/test_schema_service.py -q --tb=short`
  - `pytest backend/tests/services/test_llm_runtime.py -q --tb=short`
- `pytest backend/tests -q --tb=short --ignore=backend/tests/e2e` still needs a fresh full-suite verification pass; the last known baseline timeout was in `backend/tests/services/acquisition/test_http_client.py`

These blockers are baseline cleanup items for Track A, not regressions introduced by the package-surface changes above.

## Architectural Decisions To Lock Before Implementation

- `extract/` and `acquisition/` use **strict package APIs**. External callers import from package `__init__.py`, not internal submodules.
- `pipeline/` remains a **small public facade**, not a new god package.
- Listing and detail remain **separate pipelines**, but they share consolidated low-level infrastructure where the concern is generic:
  - noise policy
  - candidate sanitization
  - field arbitration
  - normalization primitives
- There is **one normalization/config ownership model**, not separate overlapping normalization configs per mode.
  - Shared canonical normalization and noise rules live in one place.
  - Listing/detail may have surface-specific overrides only where behavior genuinely differs.
- This refactor is **structural first, behavioral second**.
- No new API routes, no deprecation shims, no `_deprecated` directories, no “temporary” renamed duplicates.

## Target State

The desired backend architecture is valid only if it is expanded with the following rule:

- **Noise reduction and normalization are first-class architecture concerns**, not helper logic scattered across extract, semantic, listing, pipeline, and normalizers.

Target ownership after refactor:

- `acquisition/`: fetch/render/block/traversal only
- `extract/`: candidate generation and field resolution only
- `pipeline/`: orchestration, verdicts, persistence, review traces only
- `normalizers/`: canonical field-level normalization primitives only
- `config/`: single source of truth for shared rules
- consolidated internal ownership inside `extract/`:
  - noise policy
  - candidate processing
  - field arbitration
  - listing extraction orchestration
  - detail extraction orchestration

## Phase 1: Structural Restructuring Before Further Decomposition

### 1. Package surface enforcement
Status: in progress

- Verify `pipeline/__init__.py` stays small and typed.
- Align `extract/__init__.py` and `acquisition/__init__.py` to the desired public surface without exporting future modules early.
- Add comments for deferred exports only where the owning file does not yet exist.
- Audit all production imports and redirect them to approved package surfaces or direct owning submodules according to package policy.

### 2. Import and warning cleanup
Status: in progress

- Fix the `\d` SyntaxWarning in `acquisition/traversal.py`.
- Run compile/import hygiene checks for `pipeline/__init__.py`, `extract/__init__.py`, and `acquisition/__init__.py`.
- Run `ruff` for `F401` and `F811`.
- Treat any new import drift or warning as a blocker before more decomposition continues.

### 3. Architecture doc correction
Status: completed in initial pass

Update `desired-backend-architecture.md` so it explicitly states:

- one shared normalization/noise-policy ownership model
- strict package API for `extract/` and `acquisition`
- small `pipeline` facade
- deletion-manifest items with live callers move to a later proof-based deletion phase
- listing/detail separation does not justify duplicate normalization or duplicate sanitization stacks

## Slices 1-7: Consolidation Program

### Slice 1: Shared noise-policy extraction
Status: completed

Goal:
Create one reusable owner for generic noise reduction so the system stops re-implementing “noise filtering” in multiple layers.

Scope:
- consolidate UI noise stripping
- consolidate site-chrome detection
- consolidate footer/legal/contact/share/app-store suppression
- consolidate noisy product-attribute rejection
- consolidate generic noise-title rejection

Implementation:
- introduce a single internal `extract` noise-policy module
- move generic predicates out of:
  - `extract/service.py`
  - `listing_extractor.py`
  - `semantic_detail_extractor.py` or its replacement path
  - `variant_extractor.py`
  - duplicated local text-noise helpers where applicable
- keep surface-specific exceptions minimal and config-driven

Acceptance:
- one owner for generic noise predicates
- no duplicate local implementations of the same generic noise rules
- existing regression cases for footer/app-store/contact/share noise remain green

Estimated reduction:
`~800-1200 LOC`

### Slice 2: Single-owner field arbitration
Status: pending

Goal:
Make one module the authority for deciding winning field values and rejecting noisy candidates.

Scope:
- candidate finalization
- sanitization-aware winner selection
- merge preference rules
- rejection reason tracking

Implementation:
- `field_decision.py` becomes the single owner of field winner selection
- candidate generation gathers evidence only
- downstream normalization and merge helpers stop re-deciding “best” values
- remove duplicated preference heuristics from pipeline-level merge code where they duplicate extract-layer arbitration

Acceptance:
- one path decides field winners
- no duplicate “prefer X unless noisy” logic in pipeline and extract layers
- rejection reasons remain observable for debugging

Estimated reduction:
`~700-1000 LOC`

### Slice 3: Decompose and shrink `extract/service.py`
Status: in progress

Goal:
Turn `extract/service.py` into a thin orchestrator instead of a mixed-responsibility god file.

Scope:
- move candidate processing to dedicated module
- move DOM extraction helpers to dedicated module
- move structured/detail helper clusters to dedicated modules
- delete wrappers and duplicate helpers after extraction

Implementation:
- keep `extract_candidates()` and minimal orchestration in `service.py`
- move reusable processing into:
  - candidate-processing module
  - DOM/detail helper module
  - structured-detail helper module
  - shared noise-policy module
- do not just “move code”; delete obsolete wrapper logic and duplicate helper layers

Acceptance:
- `service.py` reduced to orchestrator-scale
- no duplicate sanitize/finalize helpers remain in old and new homes
- public API unchanged except where explicitly planned

Estimated reduction:
`~1200-1800 LOC net`

### Slice 4: Collapse semantic/detail/spec extraction overlap
Status: pending

Goal:
Stop maintaining two competing systems for section/specification/product-attribute extraction.

Scope:
- semantic sections
- specification tables
- product attributes
- content-root/chrome filtering for detail pages

Implementation:
- choose one owner for semantic section/spec extraction
- preferred direction:
  - semantic/detail content extraction stays in one dedicated path under `extract/`
  - duplicate DOM section/spec logic is removed from `service.py`
- if `semantic_detail_extractor.py` is ultimately deleted, its surviving logic must be absorbed into a single non-LLM extract module, not redistributed again

Acceptance:
- one owner for section/spec extraction
- one owner for product-attribute semantic harvesting
- no duplicate chrome-filtered spec/section passes

Estimated reduction:
`~700-1000 LOC`

### Slice 5: Simplify variant and product-attribute cleanup
Status: pending

Goal:
Separate true variant logic from generic attribute sanitization.

Scope:
- variant axes
- selected variant syncing
- product attribute cleanup
- noisy attribute key/value rejection

Implementation:
- `variant_extractor.py` owns variant structure only
- shared noise-policy owns generic noisy-attribute validation
- `service.py` stops duplicating attribute cleanup rules
- selected variant syncing remains in one module only

Acceptance:
- one owner for variant structure
- one owner for noisy attribute rejection
- no repeated product-attribute sanitization paths

Estimated reduction:
`~300-600 LOC`

### Slice 6: Normalize normalization config
Status: pending

Goal:
Eliminate the “separate normalization configs by mode” drift pattern.

Scope:
- shared normalization rules
- field aliases
- text cleaning/noise phrases
- canonical field validators
- surface-specific exceptions only where required by behavior

Implementation:
- define one normalization ownership model:
  - canonical rules in `normalizers/` and shared config
  - extract/pipeline call those primitives instead of shadowing them
- audit `config/extraction_rules.py`, `field_mappings.py`, and related config surfaces
- remove overlapping constants and dead config groups
- do not create separate listing-vs-detail normalization stacks unless a rule truly differs

Acceptance:
- one canonical normalization path
- one primary config source for shared normalization/noise rules
- no parallel normalization configs that drift independently

Estimated reduction:
`~500-900 LOC`

### Slice 7: Test deduplication after consolidation
Status: pending

Goal:
Shrink the test surface after logic ownership is consolidated, instead of preserving duplication in tests forever.

Scope:
- extract noise tests
- semantic extractor noise tests
- arbitration tests
- listing noise tests
- duplicated layer-specific tests for the same rule

Implementation:
- create one shared suite around consolidated noise/arbitration behavior
- keep a few end-to-end regression fixtures for listing/detail
- remove repetitive tests that exist only because logic was duplicated across layers

Acceptance:
- shared noise-policy test coverage exists
- regression fixtures for real artifact failures remain
- repeated layer-specific tests are deleted where they no longer test distinct behavior

Estimated reduction:
`~600-1000 LOC`

## Planned Execution Order

### Track A: Structural boundary work
1. Correct `desired-backend-architecture.md`
2. Verify/harden `pipeline/__init__.py`
3. Align `extract/__init__.py`
4. Align `acquisition/__init__.py`
5. Fix `traversal.py` warning
6. Run import/compile/static/test gates

### Track B: Consolidation and LOC reduction
1. Slice 1: shared noise-policy extraction
2. Slice 4: collapse semantic/detail overlap
3. Slice 2: single-owner field arbitration
4. Slice 5: variant/product-attribute cleanup
5. Slice 3: finish `service.py` shrink
6. Slice 6: normalization config consolidation
7. Slice 7: test deduplication

Reason for this order:
- noise and semantic ownership must be settled before service decomposition stabilizes
- arbitration must be unified before pipeline merge logic is simplified
- config cleanup should happen after ownership is known, not before

## Tracker

| Slice | Title | Goal | Target LOC Reduction | Status |
|---|---|---:|---:|---|
| 1 | Shared noise-policy extraction | one owner for generic noise filtering | 800-1200 | Completed |
| 2 | Single-owner field arbitration | one authority for winner selection | 700-1000 | Pending |
| 3 | Shrink `extract/service.py` | orchestrator only | 1200-1800 | In Progress |
| 4 | Collapse semantic/detail overlap | one owner for sections/specs/attrs | 700-1000 | Pending |
| 5 | Variant and attribute cleanup | separate structure from sanitization | 300-600 | Pending |
| 6 | Normalization config consolidation | one normalization ownership model | 500-900 | Pending |
| 7 | Test deduplication | remove duplicated test logic | 600-1000 | Pending |

Conservative total expected reduction:
`~4800 LOC`

Realistic total expected reduction:
`~5600+ LOC`

## Public Interfaces and Package Rules

- `pipeline/__init__.py`
  - remains narrow and typed
  - no return to broad re-export behavior
- `extract/__init__.py`
  - becomes the only external public surface for extract package APIs
  - internal decomposition modules remain internal unless explicitly promoted
- `acquisition/__init__.py`
  - becomes the only external public surface for acquisition package APIs
  - browser-pool exports are deferred until the owning module exists
- no new route surfaces
- no compatibility shims
- no duplicate wrappers kept “temporarily”

## Test and Verification Gates

For every structural phase and every slice completion:

1. Import graph checks
- verify no new broad package imports
- verify no internal import drift that violates package boundaries

2. Compile/import safety
- `python -m py_compile app/services/pipeline/__init__.py`
- `python -m py_compile app/services/extract/__init__.py`
- `python -m py_compile app/services/acquisition/__init__.py`

3. Static hygiene
- `ruff check app/services/ --select F401,F811 -q`

4. Warning gate
- `python -W error -c "import app.services.acquisition.traversal"`

5. Full backend gate
- `pytest tests -q --tb=short --ignore=tests/e2e`

6. Regression fixtures for known failures
- Thomann detail false-positive noise case
- detail zero-record despite strong product signals
- listing path still returns listing records and never detail fallback

## Assumptions and Defaults

- The main concern to solve is architectural duplication of noise reduction and normalization, not just package cleanup.
- Listing/detail remain separate orchestration paths, but they do not get separate duplicate normalization systems.
- The parallel god-file refactor continues, but all future module splits must obey this tracker.
- `desired-backend-architecture.md` should be updated first to reflect this plan before implementation resumes.
