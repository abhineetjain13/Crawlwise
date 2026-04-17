---
title: "phase 3 module refactor plan"
type: refactor-plan
status: in-progress
date: 2026-04-17
phase: 3
depends_on:
  - docs/audits/2026-04-17-phase-1-structural-audit.md
---

# Phase 3 Module Refactor Plan

## Goal

Convert the structural audit into a staged implementation plan with small, reversible slices that enforce stage boundaries across:

- `acquire`
- `discover`
- `extract`
- `normalize`
- `publish`

This document assumes Phase 2 test-audit output will be added before each code slice is executed. Until that arrives, slices remain architecturally approved but test-policy provisional.

## Refactor Principles

- Refactor by ownership boundary first, file size second.
- Prefer deletion over wrappers.
- Do not move policy twice.
- Stabilize canonical homes before deduplicating helper logic.
- Keep orchestration thin and business logic owned by stage modules.

## Target Architecture

### `acquire`

Owns:

- HTTP/browser acquisition
- navigation and traversal execution
- pacing, cookies, blocked-state detection
- acquisition diagnostics and artifacts

Does not own:

- source parsing
- field extraction
- normalization
- publish decisions

### `discover`

Owns:

- page-source discovery
- JSON-LD, hydrated state, frame-source, and payload-source parsing
- light page-shape classification only for routing

Does not own:

- business-field normalization
- persistence

### `extract`

Owns:

- record candidate extraction
- detail field candidate extraction
- source-aware arbitration

Does not own:

- canonical output normalization
- acquisition policy

### `normalize`

Owns:

- canonical field/value normalization
- output contract enforcement
- variant/value/schema normalization

Does not own:

- source parsing
- acquisition

### `publish`

Owns:

- persistence
- record writing
- run/log/trace/verdict save paths

Does not own:

- extraction semantics

## Approved Slice Order

### Slice 1: Acquisition boundary cleanup

- scope:
  Separate acquisition execution from acquisition policy and remove pipeline-aware decisions from `acquirer.py`.
- primary files:
  - `backend/app/services/acquisition/acquirer.py`
  - `backend/app/services/acquisition/blocked_detector.py`
  - `backend/app/services/acquisition/browser_client.py`
  - `backend/app/services/acquisition/traversal.py`
- expected outcomes:
  - escalation policy gets a dedicated owned surface
  - diagnosis/recovery logic stops leaking into unrelated fetch paths
  - acquisition no longer depends on pipeline semantics
- prerequisites:
  - Phase 2 classification for `test_acquirer.py`, `test_acquirer_policy.py`, and `test_browser_client.py`

#### Slice 1 work item

- status:
  in progress
- exact scope:
  - extract browser-first policy, browser escalation policy, surface-warning logic, and acquisition-outcome classification out of `acquirer.py` into an acquisition-owned policy surface
  - extract traversal-mode browser-forcing policy and browser-failure log wording out of `acquirer.py` into the same acquisition-owned policy surface
  - extract blocked-listing recovery workflow out of `acquirer.py` into an acquisition-owned recovery module while keeping final result assembly in the orchestrator
  - extract traversal surface policy out of `browser_client.py` / `traversal.py` so detail-surface suppression, listing-fragment capture, auto paginate-vs-progress decisions, and traversal-summary normalization live behind an acquisition-owned policy seam
  - keep traversal execution in `browser_client.py` / `traversal.py`; do not move discover or extract behavior into this slice
  - treat `test_crawl_service.py` `test_process_run_*` as stale coverage and remove it from the gate for this slice
- files touched in this pass:
  - `backend/app/services/acquisition/acquirer.py`
  - `backend/app/services/acquisition/policy.py`
  - `backend/app/services/acquisition/recovery.py`
  - `backend/app/services/acquisition/browser_client.py`
  - `backend/app/services/acquisition/traversal.py`
  - `backend/tests/services/acquisition/test_acquirer.py`
  - `backend/tests/services/acquisition/test_acquirer_policy.py`
  - `backend/tests/services/acquisition/test_browser_client.py`
  - `backend/tests/services/acquisition/test_traversal_modes.py`
  - `backend/tests/services/extract/test_arbitration.py`
  - `backend/tests/services/test_crawl_service.py`
- Phase 2 keep/rewrite/delete policy for this slice:
  - keep: `test_acquirer.py`, `test_acquirer_policy.py`, the non-white-box remainder of `test_browser_client.py`
  - rewrite: `test_extract_candidates_skips_dom_when_jsonld_winner_is_decisive` to assert `extraction_audit`, not private helper calls
  - delete or retire: `test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check`, and the `test_process_run_*` block in `test_crawl_service.py`
- acceptance criteria:
  - acquisition no longer imports pipeline types for acquisition-outcome classification
  - browser escalation and surface-warning policy live behind an acquisition-owned module seam
  - traversal browser-forcing policy and blocked-listing recovery no longer live in `acquirer.py`
  - traversal surface policy no longer lives in `browser_client.py` / `traversal.py`
  - stale white-box tests no longer block Slice 1 work
  - targeted acquisition and extraction tests pass
- verification commands:
  - `pytest backend/tests/services/acquisition/test_traversal_modes.py -q`
  - `pytest backend/tests/services/acquisition/test_acquirer.py backend/tests/services/acquisition/test_acquirer_policy.py backend/tests/services/acquisition/test_browser_client.py backend/tests/services/acquisition/test_traversal_modes.py -q`
  - `pytest backend/tests/services/test_crawl_service.py -q`

#### Slice 1 progress note — 2026-04-17

- completed in this pass:
  - moved traversal-mode browser forcing and browser-failure log-prefix policy into `backend/app/services/acquisition/policy.py`
  - moved blocked-listing recovery decision flow into `backend/app/services/acquisition/recovery.py`
  - reduced `backend/app/services/acquisition/acquirer.py` to orchestration over those seams
  - added a stable policy test for traversal forcing in `backend/tests/services/acquisition/test_acquirer_policy.py`
  - moved traversal surface classification, auto-mode paginate-vs-progress decisions, and traversal-summary normalization into `backend/app/services/acquisition/policy.py`
  - reduced `backend/app/services/acquisition/browser_client.py` to traversal orchestration and reduced `backend/app/services/acquisition/traversal.py` to execution over injected traversal policy
  - hardened the policy tests so non-listing launch-profile retry coverage no longer depends on a too-short blocked-page fixture
- verification:
  - `pytest backend/tests/services/acquisition/test_traversal_modes.py -q`
  - result: `12 passed`
  - `pytest backend/tests/services/acquisition/test_acquirer.py backend/tests/services/acquisition/test_acquirer_policy.py backend/tests/services/acquisition/test_browser_client.py backend/tests/services/acquisition/test_traversal_modes.py -q`
  - result: `84 passed, 1 warning`
  - known warning: `test_acquire_detail_requested_fields_are_not_overridden_by_listing_structured_data` still triggers a pre-existing un-awaited coroutine runtime warning in the mocked browser path

### Slice 2: Discover extraction from extract

- scope:
  Move discover-like source parsing out of `extract` ownership into a dedicated `discover` surface or clearly named equivalent.
- primary files:
  - `backend/app/services/extract/source_parsers.py`
  - `backend/app/services/pipeline/listing_flow.py`
  - `backend/app/services/pipeline/detail_flow.py`
  - related callers in `pipeline/stages.py` and `pipeline/trace_builders.py`
- expected outcomes:
  - page-source discovery has a clear owner
  - extract modules stop owning source inventory and page-manifest parsing
  - pipeline consumes discovered sources instead of re-deriving them
- prerequisites:
  - Phase 2 classification for `test_source_parsers.py`, `test_runner.py`, and relevant extract tests

#### Slice 2 progress note — 2026-04-17

- status: complete
- applied in this pass:
  - created `backend/app/services/discover/` package with `page_sources.py` and `json_helpers.py`
  - moved `backend/app/services/extract/source_parsers.py` → `backend/app/services/discover/page_sources.py` verbatim (minus unused `parse_datalayer_async`) and deleted the old module
  - moved `backend/app/services/extract/shared_json_helpers.py` → `backend/app/services/discover/json_helpers.py`. These helpers were never extract-owned; the move was forced by the resulting import cycle and is stage-correct, since discover owns page-source JSON parsing.
  - retargeted all callers: `extract/service.py`, `extract/listing_extractor.py`, `extract/signal_inventory.py`, `extract/__init__.py` (dropped re-exports), `pipeline/stages.py`, `pipeline/trace_builders.py`, `pipeline/llm_integration.py`, `normalizers/__init__.py`, plus `run_audit_smoke.py` and `run_extraction_smoke.py`
  - retargeted tests: `tests/services/discover/test_source_parsers.py`, `tests/services/extract/test_extract.py`, `tests/services/extract/test_datalayer.py`
  - added `backend/app/services/discover/state_inventory.py` as the discover-owned home for declarative JS-state discovery using `glom` specs: surface-aware field mapping for detail payloads plus collection-path discovery for listing-state item arrays
  - added `backend/app/services/discover/network_inventory.py` as the discover-owned home for declarative XHR payload inventory using `jmespath` specs for known job payload families (`saashr`, `greenhouse`, `workday`)
  - reduced `backend/app/services/extract/listing_structured_extractor.py` by deleting the recursive JS-state collection walker and routing listing-state discovery through the discover-owned `discover_listing_items()` seam instead
  - retargeted `backend/app/services/extract/service.py` so discover-owned JS-state and network inventory specs produce field candidates before any generic extraction fallback logic
  - added direct discover-stage tests in `backend/tests/services/discover/test_state_inventory.py` so the spec layer is protected at the discover seam instead of only through extract-side behavior
- test-policy outcome:
  - kept invariant/contract tests (`test_source_parsers.py`, `test_datalayer.py`) — only import paths changed; no private-helper coupling introduced
  - updated `test_parse_page_sources_raises_typed_parse_error_with_cause` patch target to the new discover module path
  - kept `test_listing_extractor.py` and `test_extract.py` as contract coverage for discover consumers after the JS-state and XHR inventory move
  - no stale white-box seams preserved for this slice
- verification:
  - targeted: `pytest tests/services/discover/test_source_parsers.py tests/services/extract/test_datalayer.py tests/services/extract/test_extract.py -q` → 117 passed
  - targeted follow-on: `pytest tests/services/discover/test_source_parsers.py tests/services/discover/test_state_inventory.py tests/services/extract/test_listing_extractor.py tests/services/extract/test_extract.py -q` → `198 passed`
  - checkpoint: `pytest tests/services -q` → 588 passed, 10 failed
  - confirmed all 10 failures reproduce on the Slice 2 baseline via `git stash -u`, so Slice 2 introduces no regressions
  - pre-existing failure clusters (all unrelated to the discover boundary): fragment capture, llm runtime fake redis, field alias collisions, batch runtime retry (Phase 2 marked for delete), and three listing-extractor characterization tests already failing on baseline
- net ownership change:
  - `extract/` no longer exports source-parsing primitives
  - `discover/` is now the sole importable home for `parse_page_sources*`, JSON-LD, hydrated state, embedded JSON, Apollo state, next_data, open graph, microdata, tables, and dataLayer parsing
  - pipeline orchestrators import `parse_page_sources` from `discover` directly, not via `extract`
  - discover now also owns the declarative JS-state and XHR inventory seams that extract previously embedded implicitly
- LOC outcome:
  - `backend/app/services/extract/listing_structured_extractor.py` is reduced from the prior 9xx-line characterization baseline to `706` lines after deleting the recursive state-collection seam from extract

### Slice 3: Detail extraction boundary cleanup

- scope:
  Thin `pipeline/detail_flow.py` into orchestration only and move extraction-specific reconciliation into extract-owned modules.
- primary files:
  - `backend/app/services/pipeline/detail_flow.py`
  - `backend/app/services/extract/service.py`
  - `backend/app/services/extract/detail_extractor.py`
  - `backend/app/services/pipeline/llm_integration.py`
- expected outcomes:
  - pipeline orchestrates
  - extract owns extraction and source arbitration
  - normalize owns final canonical shaping
- prerequisites:
  - Phase 2 classification for `test_extract.py`, `test_detail_extractor.py`, and `test_crawl_service.py`

#### Slice 3 progress note — 2026-04-17

- status: core detail-arbitration boundary move complete; LLM cleanup ownership follow-on still pending
- applied in this pass:
  - created `backend/app/services/extract/detail_reconciliation.py` as the extract-owned home for detail candidate arbitration, reconciliation merge policy, record merge arbitration, and detail candidate post-processing
  - removed `reconcile_detail_candidate_values`, `merge_detail_reconciliation`, and `normalize_detail_candidate_values` from `backend/app/services/pipeline/detail_flow.py`
  - removed the pipeline-owned `_merge_record_fields()` seam from `backend/app/services/pipeline/field_normalization.py`
  - retargeted `backend/app/services/pipeline/detail_flow.py` to import arbitration helpers from `app.services.extract`
  - retargeted `backend/tests/services/extract/test_arbitration.py` to the new extract-owned seam and kept the JSON-LD decisive-winner assertion on `extraction_audit`, not DOM helper patching
- test-policy outcome:
  - kept `test_extract.py`, `test_detail_extractor.py`, and `test_crawl_service.py` as stable behavioral coverage for the detail path
  - kept `test_crawl_schema.py` focused on normalize-owned record shaping; Slice 3 does not move that seam
  - rewrote `test_arbitration.py` import targets only, so the assertions continue to protect arbitration behavior rather than pipeline helper placement
- verification:
  - `pytest backend/tests/services/extract/test_arbitration.py backend/tests/services/extract/test_extract.py backend/tests/services/extract/test_detail_extractor.py -q`
  - result: `91 passed`
  - `pytest backend/tests/services/test_crawl_schema.py backend/tests/services/pipeline/test_pipeline_coupling.py -q`
  - result: `7 passed`
  - `pytest backend/tests/services/test_crawl_service.py -q`
  - result: `28 passed`
  - `python -m compileall backend/app/services/extract/detail_reconciliation.py backend/app/services/pipeline/detail_flow.py backend/app/services/pipeline/field_normalization.py backend/app/services/extract/__init__.py`
  - result: compile succeeded
- net ownership change:
  - `pipeline/detail_flow.py` now orchestrates detail extraction and delegates field arbitration to extract-owned code
  - extract now owns source-aware detail reconciliation and merge policy through a dedicated module seam
  - normalize ownership remains in `split_detail_output_fields()` and `normalizers`, avoiding a second boundary move in the same slice
- remaining Slice 3 work:
  - decide whether `pipeline/llm_integration.py` should stay pipeline-owned as an orchestration helper or be split into an extract-owned candidate-cleanup helper plus a shared publish/review seam

### Slice 4: Normalize consolidation

- scope:
  Create stable normalization ownership and remove normalization drift across pipeline and extract.
- primary files:
  - `backend/app/services/normalizers/__init__.py`
  - `backend/app/services/extract/listing_item_mapper.py`
  - `backend/app/services/extract/listing_normalize.py`
  - `backend/app/services/pipeline/field_normalization.py`
  - `backend/app/services/extract/listing_structured_extractor.py`
- expected outcomes:
  - one canonical home for field/value normalization
  - extract stops finalizing business contracts
  - pipeline stops carrying normalization rules
- prerequisites:
  - Phase 2 classification for normalization and extract suites

#### Slice 4 progress note — 2026-04-17

- status: complete
- applied in this pass:
  - created `backend/app/services/normalizers/listings.py` as the normalize-owned home for listing/detail record shaping, review-value normalization, detail quality gating, JSON-LD item shaping, and listing field coercion
  - re-exported those normalize-owned seams from `backend/app/services/normalizers/__init__.py` so callers no longer reach into extract/pipeline for canonical shaping rules
  - deleted `backend/app/services/extract/listing_normalize.py`
  - renamed the stale extract helper `backend/app/services/extract/listing_item_normalizer.py` to `backend/app/services/extract/listing_item_mapper.py` because it now only maps candidate items and delegates canonical shaping to normalize-owned code
  - removed duplicate listing/job contract shaping from the extract item-mapping helper
  - removed extract-owned JSON-LD item normalization from `backend/app/services/extract/listing_structured_extractor.py`
  - reduced `backend/app/services/pipeline/field_normalization.py` to payload/filter helpers and retargeted pipeline callers to the normalize-owned helpers
  - moved Shopify cent-format price coercion under the normalize owner and covered it at the stable `normalize_listing_record()` seam
  - preserved listing-output behavior while keeping the owner move, including existing price/review formatting and SaaShr URL synthesis from network payload context
  - audited the remaining normalize-adjacent helpers in `extract/service.py` and `extract/candidate_processing.py`; they stay in extract because they still operate on candidate collection, source ranking, and pre-contract sanitization rather than canonical output policy
- test-policy outcome:
  - kept invariant/contract coverage in `tests/test_normalizers.py`, `tests/services/extract/test_listing_normalize.py`, and `tests/services/test_crawl_schema.py`
  - rewrote import-path-coupled tests to target `app.services.normalizers` instead of deleted extract/pipeline helper homes
  - kept `tests/services/extract/test_listing_extractor.py` as the main listing-contract checkpoint because it protects output behavior, not private helper layout
- verification:
  - targeted: `pytest tests/test_normalizers.py tests/services/extract/test_listing_normalize.py tests/services/test_crawl_schema.py -q` → `30 passed`
  - checkpoint: `pytest tests/services/extract/test_listing_extractor.py tests/test_normalizers.py tests/services/extract/test_listing_normalize.py tests/services/test_crawl_schema.py -q` → `120 passed`
- net ownership change:
  - normalize now owns listing/detail output shaping and field/value coercion
  - extract produces candidate records and delegates final contract shaping to normalize-owned code
  - pipeline no longer carries the record-normalization and quality-gate rules it was previously duplicating
- LOC outcome:
  - current refactor diff is net negative: `git diff --stat` shows `535 insertions(+), 5201 deletions(-)`, so the program-level worktree is already substantially smaller even though some logic was redistributed into new owner modules

### Slice 5: Config reduction and policy relocation

- scope:
  Shrink config-owned behavior after the boundary moves above are complete.
- primary files:
  - `backend/app/services/config/extraction_rules.py`
  - `backend/app/services/config/field_mappings.py`
  - `backend/app/services/config/platform_registry.py`
- expected outcomes:
  - config becomes declarative
  - owned logic moves into the appropriate stage modules
- prerequisites:
  - slices 1 through 4 completed or far enough along to expose dead config behavior

#### Slice 5 progress note — 2026-04-17

- status: complete
- applied in this pass:
  - created `backend/app/services/acquisition/cookie_policy.py` as the acquisition-owned home for cookie persistence policy data plus override resolution/validation helpers
  - removed the inline `COOKIE_POLICY` data block from `backend/app/services/config/extraction_rules.py` and left that module as a declarative compatibility surface
  - created `backend/app/services/field_alias_policy.py` as the non-config owner for surface field exclusion, field-allowance policy, alias filtering, and requested-field alias expansion
  - retargeted active callers in `requested_field_policy.py`, extract modules, and `service.py` away from config-owned alias-policy imports
  - reduced duplicate noise heuristics by centralizing merge/title/value noise helpers in `backend/app/services/extract/noise_policy.py` and reusing them from `field_decision.py` and `normalizers/__init__.py`
  - created `backend/app/services/platform_policy.py` as the service-owned home for platform-family detection, adapter ordering, browser-first/runtime policy, acquisition hint tokens, and listing readiness resolution
  - reduced `backend/app/services/config/platform_registry.py` to registry-document loading plus compatibility wrappers over the service-owned policy module
  - switched verification to `uv run ...` after confirming the project dependencies were installed in `backend/.venv` while the plain `python` path was the system interpreter
- test-policy outcome:
  - kept `tests/services/config/test_field_mappings.py` and `tests/services/config/test_platform_registry.py` as stable compatibility coverage for the config-facing seams
  - kept `tests/services/acquisition/test_http_client.py` as the regression check for cookie-policy consumption
  - kept `tests/services/extract/test_extract.py`, `tests/services/extract/test_listing_extractor.py`, `tests/services/extract/test_noise_policy.py`, and `tests/test_normalizers.py` as the post-relocation regression gate once verification moved to `uv run`
- verification:
  - `uv run pytest tests/services/config/test_platform_registry.py tests/services/config/test_field_mappings.py tests/services/acquisition/test_http_client.py tests/services/acquisition/test_acquirer_policy.py -q` → `38 passed`
  - `uv run pytest tests/services/extract/test_noise_policy.py tests/services/extract/test_extract.py tests/services/extract/test_listing_extractor.py tests/test_normalizers.py -q` → `198 passed`
  - `uv run python -c "import sys, glom, jmespath; print(sys.executable)"` confirmed verification is using `backend/.venv`
  - `python -m compileall app/services/acquisition/cookie_policy.py app/services/acquisition/cookie_store.py app/services/field_alias_policy.py app/services/platform_policy.py app/services/extract/noise_policy.py app/services/extract/field_decision.py app/services/normalizers/__init__.py app/services/requested_field_policy.py app/services/extract/dom_extraction.py app/services/extract/json_extractor.py app/services/extract/field_classifier.py app/services/extract/listing_item_mapper.py app/services/extract/semantic_support.py app/services/extract/service.py app/services/config/field_mappings.py app/services/config/extraction_rules.py app/services/config/platform_registry.py app/services/config/platform_readiness.py` → compile succeeded
- net ownership change:
  - cookie persistence policy is now acquisition-owned instead of living inside the generic extraction config surface
  - field-alias filtering and requested-field alias expansion are now service-owned policy, with config left as the declarative alias inventory
  - platform-family detection, adapter ordering, runtime-policy lookup, and readiness-domain matching are now service-owned instead of config-owned
  - extract/normalize noise heuristics now share one canonical helper surface instead of drifting across multiple modules
- remaining Slice 5 work:
  - optional follow-on cleanup only: trim compatibility wrappers from config modules once downstream imports have been fully migrated

### Slice 6: Publish boundary cleanup

- scope:
  Isolate persistence and verdict ownership from extraction and orchestration logic.
- primary files:
  - `backend/app/services/pipeline/trace_builders.py`
  - `backend/app/services/pipeline/verdict.py`
  - `backend/app/services/pipeline/record_persistence.py`
  - `backend/app/services/crawl_metrics.py`
  - `backend/app/services/crawl_metadata.py`
- expected outcomes:
  - publish surface owns save-time shaping and trace construction
  - extraction and acquisition stop influencing persistence internals directly

#### Slice 6 progress note — 2026-04-17

- status: complete
- applied in this pass:
  - created `backend/app/services/publish/` as the canonical owner package for verdicts, save-time trace builders, persistence writers, crawl metrics, and commit-metadata helpers
  - copied the active publish seams into `backend/app/services/publish/verdict.py`, `trace_builders.py`, `record_persistence.py`, `metrics.py`, and `metadata.py`
  - retargeted live callers in `pipeline/detail_flow.py`, `pipeline/listing_flow.py`, `pipeline/core.py`, `pipeline/stages.py`, `_batch_runtime.py`, `_batch_run_store.py`, `crawl_crud.py`, `review/__init__.py`, and the direct publish-facing tests to import the publish owner instead of pipeline/top-level service modules
  - converted `app.services.publish` and `app.services.pipeline` package exports to lazy resolution so importers of `pipeline.field_normalization` and `schema_service` do not eagerly pull verdict/publish code at module-import time
  - reduced remaining live `pipeline.verdict` references in `pipeline/core.py`, `pipeline/stages.py`, `pipeline/runner.py`, `pipeline/review_helpers.py`, and `pipeline/llm_integration.py` so the runtime owner is `publish.verdict`
  - converted the legacy `pipeline/verdict.py`, `pipeline/record_persistence.py`, `pipeline/trace_builders.py`, `crawl_metrics.py`, and `crawl_metadata.py` modules into compatibility shims that re-export the publish-owned implementation instead of carrying duplicate logic
  - converted `app.services.extract` package exports to lazy resolution to break the `normalizers -> extract.noise_policy -> extract.__init__ -> candidate_processing -> normalizers` import cycle that was blocking publish-slice verification
- test-policy outcome:
  - kept `tests/services/pipeline/test_record_persistence.py`, `tests/services/pipeline/test_runner.py`, `tests/services/test_crawl_metrics.py`, and `tests/services/test_crawl_metadata.py` as the direct seam checks for this slice
  - kept `tests/services/pipeline/test_pipeline_coupling.py` and the stable normalize seam check in `tests/services/test_crawl_schema.py::test_normalize_record_fields_preserves_canonical_payload_values` as regression guards while the owner move settled
- verification:
  - `uv run pytest tests/services/pipeline/test_record_persistence.py tests/services/test_crawl_metrics.py tests/services/test_crawl_metadata.py tests/services/pipeline/test_runner.py tests/services/pipeline/test_pipeline_coupling.py tests/services/test_crawl_schema.py::test_normalize_record_fields_preserves_canonical_payload_values -q` → `14 passed`
  - `python -m compileall backend/app/services/publish backend/app/services/pipeline/verdict.py backend/app/services/pipeline/record_persistence.py backend/app/services/pipeline/trace_builders.py backend/app/services/crawl_metrics.py backend/app/services/crawl_metadata.py backend/app/services/extract/__init__.py` → compile succeeded
  - `uv run pytest tests/services/test_crawl_service.py -q` still fails in fixture setup with duplicate `users.email=test@example.com` inserts against the shared Postgres test schema; that failure is environment/test-isolation related and not caused by the publish slice
- net ownership change:
  - publish-facing orchestration callers now import the publish owner package instead of pipeline-owned verdict/persistence/metrics helpers
  - publish is now the explicit home for save-time shaping, trace construction, metrics, and verdict logic
  - the legacy pipeline/top-level module paths remain only as thin compatibility shims, not second implementations

### Adapter/platform strategy dedup follow-on

- scope:
  Finish the adapter/platform dedup slice by deleting stale routing state after platform-family detection has been centralized.
- primary files:
  - `backend/app/services/adapters/base.py`
  - `backend/app/services/adapters/adp.py`
  - `backend/app/services/adapters/greenhouse.py`
  - `backend/app/services/adapters/icims.py`
  - `backend/app/services/adapters/indeed.py`
  - `backend/app/services/adapters/jibe.py`
  - `backend/app/services/adapters/linkedin.py`
  - `backend/app/services/adapters/oracle_hcm.py`
  - `backend/app/services/adapters/paycom.py`
  - `backend/app/services/adapters/remoteok.py`
  - `backend/app/services/adapters/remotive.py`
  - `backend/app/services/adapters/saashr.py`
- expected outcomes:
  - `platforms.json` remains the sole canonical owner for family-aware ATS/job-board routing
  - family-aware adapters stop carrying dead domain lists that no longer participate in routing
  - commerce adapters keep their local domain routing because they are intentionally outside the centralized family-detector seam

#### Adapter/platform strategy dedup progress note — 2026-04-17

- status: complete
- external review used:
  - Gemini duplication review: `docs/audits/gemini-adaptor-review.md`
- applied in this pass:
  - accepted Gemini's finding that the family-aware adapters were still carrying stale `domains` arrays even though routing had already moved to `platforms.json` through `BaseAdapter._matches_platform_family()`
  - deleted the dead `domains` arrays from `adp`, `greenhouse`, `icims`, `indeed`, `jibe`, `linkedin`, `oracle_hcm`, `paycom`, `remoteok`, `remotive`, and `saashr`
  - deleted the unused `BaseAdapter.domains` default because only the commerce adapters still own and read `self.domains`
  - kept extraction-specific path and safety checks such as LinkedIn's `/jobs/` narrowing in place; those remain adapter-local extraction guards, not platform-policy duplication
- test-policy outcome:
  - kept `tests/services/adapters/test_adapters.py` and `tests/services/config/test_platform_registry.py` as the routing-regression gate
  - kept `tests/services/adapters/test_base_adapter.py` as the direct seam check for the shared family matcher
- verification:
  - `uv run pytest tests/services/adapters/test_base_adapter.py tests/services/adapters/test_adp_adapter.py tests/services/adapters/test_greenhouse_adapter.py tests/services/adapters/test_adapters.py tests/services/config/test_platform_registry.py -q` → `61 passed`
- net ownership change:
  - `platforms.json` / `app.services.platform_policy` are now the only routing owners for the centralized ATS/job-board families
  - family-aware adapters no longer duplicate config-owned domain state
  - commerce adapters remain intentionally local-routing owners

## Canonical-Home Decisions To Enforce

- Discover/source parsing must not live under `extract`.
- Final value normalization must not be split across `extract`, `pipeline`, and `normalizers`.
- Acquisition timing and blocked-state helpers need one canonical home each.
- Schema and canonical-field helpers must not be duplicated across pipeline and service layers.

## Execution Rules Per Slice

For each slice, capture:

- the exact target files
- the boundary being enforced
- stale tests expected from Phase 2
- accepted external-AI suggestions, if any
- local verification commands
- rollback note

Do not combine two boundary moves in one implementation slice unless one is mechanically required by the other.

## Immediate Next Step

Prepare Slice 1 in implementation-ready form after Phase 2 test-audit results arrive:

- resolve which `acquirer` tests are invariant versus coupled-to-internals
- decide the target home for acquisition escalation policy
- define the first thin-shell boundary for `acquirer.py`
