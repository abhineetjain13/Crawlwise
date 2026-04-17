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

### Program scope rules

- No new capability lands during this refactor program unless it reduces line count, deletes a seam, or enforces a stage boundary.
- Enhancements pulled in from `EXTRACTION_ENHANCEMENT_SPEC.md` are split into two buckets: in-program boundary fixes (folded into Track C) and deferred post-stabilization capabilities (tracked in their own section below).
- Deferred capabilities stay deferred until Tracks A–C are closed and the stage boundary targets hold end-to-end. Each deferred item is re-reviewed against the final boundaries before it is scheduled.

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

- [x] Produce file-size and complexity leaderboard for backend services
- [x] Produce duplication shortlist across acquisition, pipeline, extract, config, and adapters
- [x] Map actual stage ownership violations against `acquire/discover/extract/normalize/publish`
- [x] Identify dead seams, duplicate strategies, and wrapper indirection worth deleting
- [x] Record recommended hotspot order

### Track B: Test audit

- [x] Identify god test files and private-helper-heavy test suites
- [x] Classify tests by trust level and purpose
- [x] Mark tests that preserve wrong behavior or deleted seams
- [x] Define replacement tests at stable public seams
- [x] Create a per-slice verification matrix

### Track C: Refactor slices

- [x] Acquisition boundary cleanup
  - [x] Move HTML signal grading, listing-link heuristics, and promoted iframe discovery out of `backend/app/services/acquisition/acquirer.py` into `backend/app/services/discover/signal_inventory.py`
  - [x] Keep promoted-source fetch execution, browser escalation, artifact persistence, and failure diagnostics under the acquire owner
  - [x] Remove direct DOM parsing ownership from `acquirer.py` so acquisition consumes discover-owned signal assessments instead of performing them inline
- [x] Discover boundary extraction and ownership cleanup
  - [x] Move page-source discovery out of `extract/source_parsers.py` into a dedicated `backend/app/services/discover/` package (spec §1.1 / §1.2)
  - [x] Replace nested JS-state collection/field mapping with discover-owned declarative `glom` specs (spec §1.2)
  - [x] Replace ad hoc XHR payload dict-walking with discover-owned declarative `jmespath` specs (spec §2.2)
- [x] Extract boundary cleanup
  - [x] Move detail-field arbitration and reconciliation out of `backend/app/services/pipeline/detail_flow.py` into `backend/app/services/extract/detail_reconciliation.py`
  - [x] Delete the pipeline-owned `_merge_record_fields()` wrapper so record-merge arbitration is extract-owned
  - [x] Reassess `backend/app/services/pipeline/llm_integration.py` separately; do not move it unless the resulting review/publish seam is cleaner than the current orchestration seam
- [x] Normalize boundary cleanup
  - [x] Partition `FIELD_ALIASES` by surface to stop ecommerce/job cross-pollution (spec §1.3)
  - [x] Fix Shopify cent-format price normalization under the normalize owner, not inside extract (spec §1.2)
- [x] Publish/persistence boundary cleanup
- [x] Cross-cutting config consolidation
  - [x] Move cookie persistence policy out of `config/extraction_rules.py` into `backend/app/services/acquisition/cookie_policy.py`
  - [x] Move field-alias filtering and requested-field alias policy out of `config/field_mappings.py` into `backend/app/services/field_alias_policy.py`
  - [x] Consolidate repeated title/merge/value noise heuristics behind `backend/app/services/extract/noise_policy.py`
  - [x] Move platform runtime-policy helpers out of `config/platform_registry.py` into `backend/app/services/platform_policy.py`
- [x] Adapter and platform strategy deduplication
  - [x] Consolidate platform fingerprinting into a single family-based detector scoped to the minimum required families (spec §2.1, bounded by Invariant 29)
  - [x] Delete stale family-aware adapter domain arrays now that `platforms.json` is the canonical routing owner

### Track D: External AI leverage

- [ ] Standardize the evidence pack format for Gemini/Claude uploads
- [ ] Create reusable prompts for module audit, stale-test review, and boundary review
- [x] Record accepted vs rejected external proposals with rationale

## Deferred Post-Stabilization Capabilities

These items come from `EXTRACTION_ENHANCEMENT_SPEC.md` and are explicitly deferred until the refactor program closes. They are listed here so they are not lost, not so they are implemented now. The retired Invariant 28 previously forbade these; the current program treats them as a planned follow-on, not a forbidden reintroduction.

- [ ] Extraction confidence scorer (spec §4.1) — used only as a fallback gate, not as a field-selection mechanism (preserves Invariant 6)
- [ ] LLM-powered selector synthesizer for self-healing extraction (spec §4.2)
- [ ] `domain_memory` table and cached synthesized selectors (spec §4.3)
- [ ] Confidence-gated LLM fallback wiring in the extraction service (spec §4)
- [ ] Telemetry for JS-state hit rate, XHR intercept hit rate, confidence score, and LLM synthesis cost (spec §Monitoring)

Gate conditions:

- No deferred item starts while any Track C slice is still open.
- Each deferred item must be re-reviewed against the final stage boundaries before it is scheduled.
- Any deferred item that would re-entangle stage ownership must be redesigned, not smuggled in.

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
- Retired Invariant 28 (deleted subsystems stay deleted) so that domain memory, LLM selector synthesis, and confidence scoring can be reintroduced as a planned follow-on rather than being treated as forbidden.
- Split `EXTRACTION_ENHANCEMENT_SPEC.md` into in-program boundary fixes (folded into Track C) and deferred post-stabilization capabilities (tracked in their own section). Stabilization is not short-circuited by enhancements.
- Added a program scope gate: no new capability lands during this refactor unless it reduces line count, deletes a seam, or enforces a stage boundary.

## Phase 1 Findings

### 2026-04-17 Initial structural audit

#### File-size leaderboard

Top service files by size from the initial local scan:

| Rank | File | Lines | Audit note |
|---|---|---:|---|
| 1 | `backend/app/services/acquisition/acquirer.py` | 2917 | primary P0 hotspot; acquisition policy, escalation, diagnosis, and recovery remain combined |
| 2 | `backend/app/services/config/extraction_rules.py` | 2179 | oversized config/policy surface; likely carrying behavior through config ownership |
| 3 | `backend/app/services/acquisition/traversal.py` | 1925 | traversal strategies and heuristics are concentrated in one owner |
| 4 | `backend/app/services/extract/variant_builder.py` | 1701 | variant extraction, reconciliation, and normalization likely mixed |
| 5 | `backend/app/services/acquisition/browser_client.py` | 1544 | browser fetch/runtime concerns still large even after prior decomposition |
| 6 | `backend/app/services/extract/listing_card_extractor.py` | 1458 | card-specific extraction remains large but appears more cohesive than the P0 files |
| 7 | `backend/app/services/llm_runtime.py` | 1421 | large runtime owner, but not yet on the critical refactor path for stage separation |
| 8 | `backend/app/services/normalizers/__init__.py` | 1340 | normalization is still concentrated in a single package entry file |
| 9 | `backend/app/services/extract/service.py` | 1300 | detail candidate orchestration remains oversized |
| 10 | `backend/app/services/extract/source_parsers.py` | 944 | discover-like ownership is still embedded in extract |

#### Highest-complexity functions

Top complexity findings from `radon`:

| Rank | File | Function | Complexity | Working interpretation |
|---|---|---|---:|---|
| 1 | `backend/app/services/extract/listing_quality.py` | `assess_listing_record_quality` | 90 | quality, filtering, and policy likely collapsed into one decision engine |
| 2 | `backend/app/services/acquisition/browser_client.py` | `_fetch_rendered_html_attempt` | 64 | fetch orchestration still mixes runtime setup, navigation, readiness, and fallback |
| 3 | `backend/app/services/normalizers/__init__.py` | `validate_value` | 60 | normalization contract is too centralized |
| 4 | `backend/app/services/extract/listing_item_normalizer.py` | `_normalize_listing_value` | 55 | normalization logic likely mixed with source-aware extraction assumptions |
| 5 | `backend/app/services/acquisition/blocked_detector.py` | `detect_blocked_page` | 54 | blocked detection is carrying too many policy branches |
| 6 | `backend/app/services/acquisition/acquirer.py` | `_browser_escalation_decision` | 49 | escalation policy is a clear extraction candidate |
| 7 | `backend/app/services/pipeline/detail_flow.py` | `extract_detail` | 44 | pipeline orchestration still owns too much detail extraction behavior |
| 8 | `backend/app/services/extract/semantic_support.py` | `_build_semantic_rows` | 42 | semantic extraction logic is large and probably under-factored |
| 9 | `backend/app/services/extract/listing_structured_extractor.py` | `_normalize_ld_item` | 42 | structured extraction and normalization still overlap |
| 10 | `backend/app/services/acquisition/traversal.py` | `collect_paginated_html` | 40 | traversal policy and execution remain entangled |

#### Coupling observations

Cross-area import scan shows these structural problems:

- `acquisition/acquirer.py` imports `adapters`, `config`, and `pipeline`. Acquisition should not depend on pipeline ownership.
- `pipeline/detail_flow.py` imports `acquisition`, `adapters`, and `extract`. That may be acceptable for orchestration, but the current complexity suggests orchestration is leaking behavior ownership.
- `pipeline/listing_flow.py`, `pipeline/stages.py`, and `pipeline/trace_builders.py` all reach into `acquisition` and `extract`, which indicates stage orchestration and stage-specific business logic are still interleaved.
- `extract/source_parsers.py` remains under `extract`, but functionally it behaves like `discover`. This is a naming and ownership mismatch.
- `pipeline/field_normalization.py` depends on `extract` and `normalizers`, suggesting normalization policy is not yet cleanly isolated.
- `schema_service.py` importing `pipeline` is an inversion risk; schema ownership should not depend on pipeline internals.

#### Duplication signals

Initial duplicate-name and helper-pattern scan found these likely duplication clusters:

- Normalization helpers were spread across `normalizers/__init__.py`, `extract/candidate_processing.py`, `extract/listing_item_mapper.py` (formerly `listing_item_normalizer.py`), `extract/listing_normalize.py`, `extract/listing_structured_extractor.py`, and `pipeline/field_normalization.py`.
- URL and shape heuristics are distributed across `extract/listing_quality.py`, `pipeline/stages.py`, `pipeline/listing_helpers.py`, `acquisition/acquirer.py`, and several adapters.
- Utility helpers such as `_elapsed_ms`, `get_canonical_fields`, and `_build_xpath_tree` exist in multiple owned modules, which indicates missing canonical homes.
- Adapter-local duplication is present by design in some methods like `can_handle` and `extract`, but repeated helpers such as `_clean_text` and `_extract_job_id_from_url` deserve review for consolidation if they express the same rule.

#### Hotspot classification

| File | Classification | Reason |
|---|---|---|
| `backend/app/services/acquisition/acquirer.py` | `mixed-responsibility` | combines acquisition execution, escalation policy, diagnosis, retry, and platform hints |
| `backend/app/services/pipeline/detail_flow.py` | `mixed-responsibility` | pipeline owner is carrying detail extraction logic and reconciliation policy |
| `backend/app/services/extract/source_parsers.py` | `stale-seam` | discover behavior is placed under extract, which obscures the stage model |
| `backend/app/services/config/extraction_rules.py` | `stale-seam` | config appears to be compensating for unclear ownership boundaries |
| `backend/app/services/acquisition/traversal.py` | `duplicate-strategy` | multiple traversal strategies and heuristics are concentrated together |
| `backend/app/services/acquisition/browser_client.py` | `orchestrator` | still too large, but its core problem is overloaded orchestration more than arbitrary duplication |

#### Recommended hotspot order

1. `acquisition/acquirer.py`
   Reason: largest active hotspot and highest architectural leverage for boundary cleanup.
2. `pipeline/detail_flow.py`
   Reason: direct pressure point between pipeline orchestration, extraction, and normalization.
3. `extract/source_parsers.py`
   Reason: likely first concrete `discover` extraction target.
4. `config/extraction_rules.py`
   Reason: should be revisited after boundary cleanup starts so config can be reduced rather than shuffled.
5. `acquisition/traversal.py`
   Reason: important, but should follow acquisition boundary clarification so traversal refactors do not move policy twice.

#### Immediate conclusion

The codebase is no longer just suffering from large files. The dominant issue is boundary confusion:

- `discover` logic is still living under `extract`
- `normalize` logic is still split across extract, pipeline, and normalizers
- acquisition still reaches upward into pipeline-aware decisions

That means the first refactor slices should be organized by stage ownership, not by raw file size alone.

### Phase 2 Findings Imported

Slice 1 is now anchored to these Phase 2 decisions:

- keep:
  - `backend/tests/services/acquisition/test_acquirer.py`
  - `backend/tests/services/acquisition/test_acquirer_policy.py`
  - `backend/tests/services/acquisition/test_traversal_modes.py`
  - `backend/tests/services/acquisition/test_browser_client.py` except the deleted private-helper assertion
- rewrite:
  - `backend/tests/services/extract/test_arbitration.py::test_extract_candidates_skips_dom_when_jsonld_winner_is_decisive`
    Stable seam: `source_trace["extraction_audit"]`
- delete or retire before acquisition-boundary work:
  - `backend/tests/services/acquisition/test_browser_client.py::test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check`
  - the `test_process_run_*` block in `backend/tests/services/test_crawl_service.py`

### Phase Status

- Phase 1: complete
  Audit record: `docs/audits/2026-04-17-phase-1-structural-audit.md`
- Phase 2: complete
  Audit record: `docs/audits/phase2-test-audit-result.md`
- Phase 3: in progress
  Plan record: `docs/audits/2026-04-17-phase-3-module-refactor-plan.md`

## Next Actions

- [x] Import Phase 2 test-audit findings back into the refactor program tracker
- [x] Turn Slice 1 from the Phase 3 plan into an implementation-ready work item
- [x] Continue Slice 1 by extracting blocked-recovery and traversal-related policy out of `acquirer.py`
- [x] Close Slice 1 by moving discover-owned HTML signal inventory out of `acquirer.py`
  - result: added `backend/app/services/discover/signal_inventory.py` as the canonical home for listing-link heuristics, promoted iframe discovery, and extractability grading signals used for acquisition routing
  - result: `backend/app/services/acquisition/acquirer.py` now consumes `analyze_html_signals()` / `assess_extractable_html()` instead of parsing DOM state inline
  - result: kept proxy rotation, promoted-source fetch execution, browser fallback, artifact persistence, and failure diagnostics in acquisition as acquire-owned concerns
  - external-audit disposition: accepted the Gemini recommendation to evict DOM/source discovery from `acquirer.py`; rejected its proxy-manager split as non-blocking intra-acquire cleanup for a later slice
  - verification: `python -m ruff check backend/app/services/acquisition/acquirer.py backend/app/services/discover/__init__.py backend/app/services/discover/signal_inventory.py`
  - verification: `python -m pytest backend/tests/services/acquisition/test_acquirer.py -q`
- [x] Slice 2 kickoff — move page-source discovery out of `extract/source_parsers.py` into `backend/app/services/discover/`
- [x] Slice 2 follow-on — replace nested JS-state mapping with declarative `glom` specs inside `discover/` (spec §1.2)
  - result: added `backend/app/services/discover/state_inventory.py`, which now owns surface-aware JS-state field specs plus listing collection discovery for nested state payloads
  - result: deleted the recursive listing-state collection walker from `backend/app/services/extract/listing_structured_extractor.py` and retargeted extract callers to consume discover-owned state inventory instead
- [x] Slice 2 follow-on — declarative `jmespath` specs for XHR payload inventory, now that discover owns the seam (spec §2.2)
  - result: added `backend/app/services/discover/network_inventory.py` with discover-owned spec maps for `saashr`, `greenhouse`, and `workday` payload families
  - result: `backend/app/services/extract/service.py` now consumes discover-owned network payload candidates before any generic fallback extraction path
- [x] Slice 3 follow-on — decide whether `pipeline/llm_integration.py` belongs under extract or should instead split into extract-owned candidate cleanup plus shared review/publish helpers
  - result: Gemini boundary review concluded `pipeline/llm_integration.py` and `pipeline/review_helpers.py` have harmful ownership drift and should split between extract-owned LLM candidate cleanup and publish-owned review shaping
  - accepted: move candidate mutation, candidate evidence building, discovered-source packaging, and LLM review-target selection into an extract-owned module because they operate on candidate values, extraction traces, and extraction-stage arbitration
  - accepted with clarification: move review-bucket shaping, deduplication, and discovered-field surfacing into a publish-owned module; rejected Gemini's normalize-owned alternative because these helpers shape downstream review artifacts rather than serving as general canonical normalization seams
  - accepted with guardrail: keep `parse_page_sources()` discover-owned; only move the packaging layer around discovered-source snapshots if it remains an extract-owned consumer over discover data
  - rejected: immediate forced deletion of `pipeline/llm_integration.py`; a thin compatibility shim is acceptable while callers are retargeted during the implementation slice
  - audit record: `docs/audits/2026-04-17-gemini-llm-integration-boundary-review.md`
- [x] Slice 3 implementation — move LLM cleanup ownership out of pipeline
  - result: created `backend/app/services/extract/llm_cleanup.py` as the extract-owned home for LLM candidate mutation, candidate evidence building, discovered-source packaging, snapshotting, and review-target selection
  - result: created `backend/app/services/publish/review_shaping.py` as the publish-owned home for discovered-field surfacing, review-bucket deduplication, LLM cleanup review normalization, and cleanup-payload splitting
  - result: retargeted `backend/app/services/pipeline/detail_flow.py` and `backend/app/services/publish/trace_builders.py` to the new owner modules so pipeline remains the caller and publish owns review shaping directly
  - result: deleted the temporary compatibility shims `backend/app/services/pipeline/llm_integration.py` and `backend/app/services/pipeline/review_helpers.py` after retargeting all live imports, so the slice ends with net file-count reduction instead of parked duplicate seams
  - verification: `python -m compileall backend/app/services/extract/llm_cleanup.py backend/app/services/publish/review_shaping.py backend/app/services/pipeline/detail_flow.py backend/app/services/publish/trace_builders.py backend/app/services/adapters/paycom.py`
  - verification: `uv run ruff check app/services/adapters/paycom.py app/services/extract/llm_cleanup.py app/services/publish/review_shaping.py app/services/pipeline/detail_flow.py app/services/publish/trace_builders.py tests/services/pipeline/test_pipeline_coupling.py`
  - verification: `uv run pytest tests/services/pipeline/test_pipeline_coupling.py tests/services/test_crawl_schema.py::test_normalize_record_fields_preserves_canonical_payload_values tests/services/test_crawl_service.py::test_commit_selected_fields_preserves_typed_values_and_refreshes_metadata -q`
  - environment note: the earlier `glom` failure was caused by invoking the global `C:\Python314\python.exe` instead of the project interpreter; the backend environment resolves correctly via `uv run` or `backend/.venv/Scripts/python.exe`
  - extra fix: repaired a pre-existing syntax error in `backend/app/services/adapters/paycom.py` (`lib_config = {} return { ... }`) that was blocking crawl-service test collection under the correct project environment
- [x] Continue Slice 1 by reviewing `blocked_detector.py`, `browser_client.py`, and `traversal.py` for remaining acquisition-policy leakage now that the `acquirer.py` seams are split
  - result: traversal surface classification, auto traversal decisions, and traversal summary normalization moved out of `browser_client.py` / `traversal.py` into `backend/app/services/acquisition/policy.py`
  - note: `blocked_detector.py` remains the owned policy home for blocked-page rules; no higher-leverage boundary move there beat the traversal policy seam in this pass
- [ ] Re-check whether any worthwhile `blocked_detector.py` simplification remains after Slice 1 closes, but do not reopen the seam unless it deletes substantial rule branching
- [x] Slice 4 kickoff — normalize now owns listing/detail record shaping, pipeline quality-gate normalization, and Shopify cent-format money coercion
  - result: created `backend/app/services/normalizers/listings.py` as the canonical owner for record shaping and moved callers in extract/pipeline onto it
  - result: deleted `backend/app/services/extract/listing_normalize.py`, renamed the stale extract helper to `listing_item_mapper.py`, and removed duplicate record/value normalizers from extract/pipeline call sites
  - result: `FIELD_ALIASES` surface partitioning now happens through `get_surface_field_aliases()`, so candidate generation no longer mixes ecommerce/job-only alias vocabularies before shaping
  - result: audited `extract/service.py` and `extract/candidate_processing.py`; no remaining canonical output policy was left there beyond candidate-stage sanitization/ranking
- [x] Slice 3 kickoff — detail-field arbitration is now extract-owned instead of pipeline-owned
  - result: created `backend/app/services/extract/detail_reconciliation.py` and moved detail candidate arbitration, reconciliation merge logic, and record-merge arbitration into it
  - result: deleted duplicate arbitration helpers from `backend/app/services/pipeline/detail_flow.py` and removed `_merge_record_fields()` from `backend/app/services/pipeline/field_normalization.py`
  - verification: `pytest backend/tests/services/extract/test_arbitration.py backend/tests/services/extract/test_extract.py backend/tests/services/extract/test_detail_extractor.py -q`, `pytest backend/tests/services/test_crawl_schema.py backend/tests/services/pipeline/test_pipeline_coupling.py -q`, `pytest backend/tests/services/test_crawl_service.py -q`
- [x] Slice 6 kickoff — publish now has a canonical owner package and live callers import it
  - result: created `backend/app/services/publish/` with publish-owned verdict, trace-builder, record-persistence, metrics, and metadata modules
  - result: retargeted active callers in pipeline, batch runtime, crawl CRUD, review helpers, and publish-facing tests onto `app.services.publish`
  - result: collapsed the legacy `pipeline/*` publish modules and top-level `crawl_metrics.py` / `crawl_metadata.py` into thin compatibility shims so the publish owner is unique
  - result: converted `app.services.extract` exports to lazy loading to remove the `normalizers` ↔ `extract` import cycle that was blocking slice verification
  - verification: `uv run pytest tests/services/pipeline/test_record_persistence.py tests/services/test_crawl_metrics.py tests/services/test_crawl_metadata.py tests/services/pipeline/test_runner.py tests/services/pipeline/test_pipeline_coupling.py tests/services/test_crawl_schema.py::test_normalize_record_fields_preserves_canonical_payload_values -q` → `14 passed`
  - verification: `python -m compileall backend/app/services/publish backend/app/services/pipeline/verdict.py backend/app/services/pipeline/record_persistence.py backend/app/services/pipeline/trace_builders.py backend/app/services/crawl_metrics.py backend/app/services/crawl_metadata.py backend/app/services/extract/__init__.py` → compile succeeded
  - note: `uv run pytest tests/services/test_crawl_service.py -q` still errors in fixture setup with duplicate `test@example.com` inserts against the test DB; not attributable to the publish slice
- [ ] Prepare the reusable Gemini/Claude prompts from the evidence-pack template
- [x] Prepare the reusable Gemini prompt for boundary review
  - result: added `docs/prompts/phase4_boundary_review.md` as the reusable Phase 4 boundary-review template for bounded stage-ownership audits
- [x] Prepare the reusable Gemini prompt for adapter/platform duplication review
  - result: added `docs/prompts/phase4_adapter_platform_duplication_review.md` for the remaining adapter/platform-strategy dedup slice
- [x] Adapter/platform dedup follow-on — thin family-aware adapters now delegate routing to the shared detector instead of repeating domain/HTML fingerprint rules
  - result: added shared `BaseAdapter._matches_platform_family()` and moved `adp`, `icims`, `jibe`, `oracle_hcm`, `paycom`, `saashr`, `greenhouse`, `indeed`, `linkedin`, `remotive`, and `remoteok` onto the canonical platform-family detector
  - result: left commerce adapters and extraction-specific logic untouched so only the minimum required configured families are centralized
  - verification: `uv run pytest tests/services/adapters/test_base_adapter.py tests/services/adapters/test_adp_adapter.py tests/services/adapters/test_greenhouse_adapter.py tests/services/adapters/test_adapters.py tests/services/config/test_platform_registry.py -q`
- [x] Close adapter/platform dedup slice using Gemini follow-up review
  - result: accepted Gemini's dead-code cleanup recommendation from `docs/audits/gemini-adaptor-review.md` and deleted stale `domains` arrays from the family-aware adapters plus the unused `BaseAdapter.domains` default
  - result: kept local `domains` ownership in `amazon.py`, `ebay.py`, and `walmart.py` because those commerce adapters still use direct domain routing and were explicitly out of scope for the family-detector consolidation
  - verification: `uv run pytest tests/services/adapters/test_base_adapter.py tests/services/adapters/test_adp_adapter.py tests/services/adapters/test_greenhouse_adapter.py tests/services/adapters/test_adapters.py tests/services/config/test_platform_registry.py -q`

## References

- [2026-04-16-architectural-refactor-tracker.md](/C:/Projects/pre_poc_ai_crawler/docs/plans/2026-04-16-architectural-refactor-tracker.md)
- [2026-04-11-refactor-god-file-decomposition-plan.md](/C:/Projects/pre_poc_ai_crawler/docs/plans/2026-04-11-refactor-god-file-decomposition-plan.md)
- [backend-architecture.md](/C:/Projects/pre_poc_ai_crawler/docs/backend-architecture.md)
- [2026-04-17-phase-1-structural-audit.md](/C:/Projects/pre_poc_ai_crawler/docs/audits/2026-04-17-phase-1-structural-audit.md)
- [2026-04-17-phase-3-module-refactor-plan.md](/C:/Projects/pre_poc_ai_crawler/docs/audits/2026-04-17-phase-3-module-refactor-plan.md)
- [EXTRACTION_ENHANCEMENT_SPEC.md](/C:/Projects/pre_poc_ai_crawler/EXTRACTION_ENHANCEMENT_SPEC.md)
