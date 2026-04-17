---
title: "backend refactor program tracker"
type: refactor-program
status: in-progress
date: 2026-04-17
supersedes:
  - docs/plans/2026-04-16-architectural-refactor-tracker.md
---

# Backend Refactor Program Tracker

## Mission

This tracker is the long-lived control document for the backend cleanup effort. Its job is to keep daily work anchored to one program with a clear sequence, evidence log, and stop/go criteria so we do not restart the analysis from zero each day.

Primary goals:

- remove code bloat and duplicated strategy logic
- eliminate stale tests that preserve bad behavior
- enforce strict stage boundaries across `acquire -> discover -> extract -> normalize -> publish`
- drive the codebase toward `SOLID`, `DRY`, `KISS`, and `YAGNI`
- spend premium agent compute only where repo-grounded judgment or implementation is actually needed

## Operating Rules

### Architecture rules

- Every module must have one primary reason to change.
- Stage boundaries are real boundaries, not naming suggestions.
- Shared helpers must move to explicit owned modules, not generic `utils` dumping grounds.
- Delete dead seams and duplicate strategy paths instead of preserving them behind wrappers.
- Config should describe behavior; config must not become another behavior engine.

### Test rules

- Existing tests are not automatically correct.
- Tests that lock in bugs, dead seams, or internal structure are allowed to be rewritten or deleted.
- We keep invariant tests and contract tests.
- We rewrite characterization tests only when they still protect intended behavior.
- We avoid adding new tests that couple to private helpers unless there is no better seam.

### Compute rules

- Cheap external AI gets the first pass for bounded file audits and proposal generation.
- Local tools produce the evidence pack before any external AI review.
- Codex is reserved for repo-grounded synthesis, conflict resolution, implementation, and verification.
- If Gemini or Claude output conflicts with local evidence, local evidence wins.

## Workflow

### Phase 1: Local structural audit

Purpose:
Build a trustworthy map of size, complexity, duplication, coupling, and ownership violations using local tools that external AI cannot run.

Outputs:

- hotspot inventory by file and function
- duplication inventory by responsibility area
- dependency and ownership notes by module
- evidence-backed shortlist of god modules
- candidate target boundaries for `acquire`, `discover`, `extract`, `normalize`, `publish`

Required tools:

- `rg`
- `ruff`
- `radon`
- `mypy`
- targeted `pytest`
- ad hoc repo queries and metrics scripts when needed

Definition of done:

- top hotspot modules identified with evidence
- each hotspot tagged as `orchestrator`, `mixed-responsibility`, `duplicate-strategy`, or `stale-seam`
- first-pass extraction boundaries proposed for each hotspot

### Phase 2: Test audit

Purpose:
Stop stale tests from blocking the refactor or preserving bad behavior.

Outputs:

- test inventory by area
- classification of tests into:
  - `invariant`
  - `contract`
  - `characterization`
  - `coupled-to-internals`
  - `obsolete`
- rewrite/delete recommendations
- module-specific regression strategy for each refactor slice

Definition of done:

- every hotspot module has a matching test strategy
- high-friction stale tests are identified before structural changes start
- we know which tests are safe to trust and which need replacement

### Phase 3: Module-wise refactor plan

Purpose:
Convert the audit into a staged implementation program with small, reversible slices.

Outputs:

- target architecture by stage
- ordered refactor slices
- acceptance criteria per slice
- rollback and verification plan per slice
- dependency notes so we do not refactor in the wrong order

Definition of done:

- each slice has a clear owner, target files, tests, and completion criteria
- no slice mixes unrelated boundaries
- no slice depends on unverified assumptions from stale tests

### Phase 4: Execution with external-AI prepass

Purpose:
Use free/cheap models where they help, while keeping final technical decisions grounded in the repo.

External-AI policy:

- Gemini first pass:
  - bounded file audits
  - responsibility violation review
  - duplication pattern review
  - naming and boundary suggestions
  - stale-test suspicion review
- Claude first pass when file bundle is small enough:
  - concentrated module review
  - test rewrite proposal
  - refactor sequence proposal
- Codex:
  - validates proposals against repo evidence
  - resolves contradictions
  - updates the plan
  - performs implementation and verification when approved

Definition of done:

- every substantial slice has either:
  - a local-evidence-only basis, or
  - an external proposal that has been checked against local evidence

## Program Backlog

### Track A: Structural audit

- [ ] Produce file-size and complexity leaderboard for backend services
- [ ] Produce duplication shortlist across acquisition, pipeline, extract, config, and adapters
- [ ] Map actual stage ownership violations against `acquire/discover/extract/normalize/publish`
- [ ] Identify dead seams, duplicate strategies, and wrapper indirection worth deleting
- [ ] Record recommended hotspot order

### Track B: Test audit

- [ ] Identify god test files and private-helper-heavy test suites
- [ ] Classify tests by trust level and purpose
- [ ] Mark tests that preserve wrong behavior or deleted seams
- [ ] Define replacement tests at stable public seams
- [ ] Create a per-slice verification matrix

### Track C: Refactor slices

- [ ] Acquisition boundary cleanup
- [ ] Discover boundary extraction and ownership cleanup
- [ ] Extract boundary cleanup
- [ ] Normalize boundary cleanup
- [ ] Publish/persistence boundary cleanup
- [ ] Cross-cutting config consolidation
- [ ] Adapter and platform strategy deduplication

### Track D: External AI leverage

- [ ] Standardize the evidence pack format for Gemini/Claude uploads
- [ ] Create reusable prompts for module audit, stale-test review, and boundary review
- [ ] Record accepted vs rejected external proposals with rationale

## Initial Hotspot Queue

This queue is based on the current local scan and should be refined in Phase 1.

| Priority | File | Current signal | Working interpretation |
|---|---|---:|---|
| P0 | `backend/app/services/acquisition/acquirer.py` | ~2917 lines, multiple `D/E/F` complexity functions | mixed acquisition policy, surface diagnosis, escalation, recovery, and diagnostics in one owner |
| P0 | `backend/app/services/pipeline/detail_flow.py` | high complexity in detail extraction path | extract and normalization concerns likely mixed inside pipeline orchestration |
| P1 | `backend/app/services/config/extraction_rules.py` | ~2179 lines | config surface may be carrying behavior and policy that belongs in owned modules |
| P1 | `backend/app/services/acquisition/browser_client.py` | very large, historically high coupling | browser runtime, navigation, readiness, and fallback policy likely still too entangled |
| P1 | `backend/app/services/acquisition/traversal.py` | ~1925 lines | likely too many traversal strategies and heuristics in one place |
| P1 | `backend/app/services/extract/variant_builder.py` | ~1701 lines | probable mixed responsibilities across extraction, normalization, and reconciliation |

## Initial Test-Risk Queue

| Priority | File | Current signal | Risk |
|---|---|---:|---|
| P0 | `backend/tests/services/extract/test_listing_extractor.py` | ~2492 lines, ~90 tests | likely locking internal extraction details and duplicate behaviors |
| P0 | `backend/tests/services/extract/test_extract.py` | ~2232 lines, ~80 tests | likely mixes invariants with characterization and private helper coupling |
| P0 | `backend/tests/services/test_crawl_service.py` | ~2374 lines, ~76 tests | likely preserving orchestration quirks and ownership leakage |
| P1 | `backend/tests/services/acquisition/test_acquirer.py` | ~1322 lines, ~46 tests | likely sensitive to implementation detail changes inside acquisition |
| P1 | `backend/tests/services/adapters/test_adapters.py` | ~831 lines, ~44 tests | may freeze registry/order details that should be config-owned |

## Stage Boundary Target

This is the target mental model the refactor should converge toward.

### `acquire`

- fetch bytes or rendered HTML
- handle navigation, pacing, cookies, browser/runtime concerns
- detect blocked or failed acquisition states
- produce acquisition artifacts and diagnostics
- does not decide extraction semantics

### `discover`

- identify page/source candidates
- parse JSON-LD, hydrated state, frame sources, network payload inventories
- classify surface/page shape only as needed for downstream routing
- does not normalize business fields

### `extract`

- convert discovered sources into candidate records or detail field candidates
- apply extraction logic and source-specific arbitration
- does not apply final canonical normalization policy

### `normalize`

- canonicalize field names, values, variants, schemas, and output contracts
- enforce stable output shape
- does not fetch pages or discover sources

### `publish`

- persist records, traces, verdicts, and run state
- emit logs/events/metrics tied to saved outcomes
- does not own extraction logic

## External AI Gate

Before spending premium compute on a hotspot, prepare this evidence pack:

- target file
- nearby collaborators
- size and complexity summary
- main responsibility concerns
- duplicate logic notes
- relevant tests
- known stale-test suspicions
- target boundary we think the file should obey

Cheap-model first-pass is required for:

- single-file or small-bundle audits
- candidate rename/split suggestions
- stale-test suspicion analysis
- review of proposed module boundaries

Cheap-model first-pass is optional for:

- implementation-heavy slices
- cross-module dependency disputes
- cases where the repo evidence already makes the next step obvious

Codex is mandatory for:

- local evidence generation
- conflicting proposal arbitration
- patching code
- test rewrites/deletions
- verification and tracker updates

## Slice Template

Use this template before starting any refactor slice.

### Slice

- scope:
- files:
- boundary being enforced:
- stale tests expected:
- external AI first-pass used:
- local evidence checked:
- acceptance criteria:
- verification commands:
- rollback note:

## Decision Log

### 2026-04-17

- Chosen strategy: evidence-first refactor program, not full-repo AI upload.
- Reason: local tools can establish the real hotspot map and expose stale tests more reliably than a blind external audit.
- Chosen workflow: cheap external AI for bounded audits first, Codex for synthesis and implementation only when necessary.
- Program bias: prefer deletion, simplification, and boundary enforcement over compatibility shims and wrapper layers.

## Next Actions

- [ ] Run the full structural audit and capture findings in this tracker
- [ ] Run the stale-test audit and classify the first hotspot suites
- [ ] Convert findings into the first approved module refactor slice
- [ ] Prepare the reusable Gemini/Claude prompts from the evidence-pack template

## References

- [2026-04-16-architectural-refactor-tracker.md](/C:/Projects/pre_poc_ai_crawler/docs/plans/2026-04-16-architectural-refactor-tracker.md)
- [2026-04-11-refactor-god-file-decomposition-plan.md](/C:/Projects/pre_poc_ai_crawler/docs/plans/2026-04-11-refactor-god-file-decomposition-plan.md)
- [backend-architecture.md](/C:/Projects/pre_poc_ai_crawler/docs/backend-architecture.md)
