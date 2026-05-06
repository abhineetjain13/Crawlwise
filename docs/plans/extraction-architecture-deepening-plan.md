# Plan: Extraction Architecture Deepening

**Created:** 2026-05-06
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Extraction, Acquisition + Browser Runtime, Crawl Ingestion + Orchestration, Publish + Persistence, LLM Admin + Runtime, architecture tests

## Goal

Refactor the extraction architecture around deeper owners, with extraction quality first. Done means tier execution, listing candidate quality, extraction/public config, acquisition policy, pipeline result/failure handling, and architecture guardrails each have clearer interfaces and stronger locality.

## Acceptance Criteria

- [x] Detail extraction tier execution has one clear owner and preserves field-by-field candidate arbitration.
- [x] Listing candidate admission/ranking has one clear owner for quality rules.
- [x] Extraction/public-record config is grouped by concept inside `app/services/config/*`.
- [x] Acquisition callers depend on an explicit acquisition policy interface, not raw fetch-runtime knobs.
- [x] Pipeline result/failure handling uses public typed interfaces.
- [x] Architecture guardrails reflect the refactored contracts and remove obsolete debt allowances.
- [x] `python -m pytest tests -q` exits 0.

## Do Not Touch

- `backend/app/services/detail_extractor.py` candidate arbitration — correct field-by-field system per `docs/INVARIANTS.md` Rule 3.
- `backend/app/services/publish/*` — no downstream extraction-quality compensation.
- `backend/app/services/pipeline/persistence.py` — no persistence-side repair for extraction bugs.
- Archived audit docs — stale by project rule.

## Slices

### Slice 1: Detail Tier Execution Refactor
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/extract/detail_tiers.py`, focused detail extraction tests
**What:** Make `detail_tiers.py` the owner for tier sequencing, DOM skip decision, DOM build transition, and early/DOM finalization transition. Preserve `_add_sourced_candidate`, `_materialize_record`, source priority, and structured-object candidate merging.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py -q`

### Slice 2: Listing Candidate Quality Owner
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/extract/listing_candidate_ranking.py`, listing extraction tests
**What:** Consolidate listing admission, support signals, utility rejection, dedupe key, and candidate-set scoring into one listing candidate module.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_listing_extractor*.py -q`

### Slice 3: Extraction/Public Config Interfaces
**Status:** DONE
**Files:** `backend/app/services/config/field_mappings.py`, `backend/app/services/config/extraction_rules.py`, config consumers, structure tests
**What:** Keep config data under `app/services/config/*`, but expose concept-owned interfaces for field aliases, variant policy, public-record policy, JS-state mapping, detail policy, and listing policy.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_config_imports.py tests/services/test_structure.py tests/services/test_field_value_core.py -q`

### Slice 4: Acquisition Policy Interface
**Status:** DONE
**Files:** `backend/app/services/acquisition/acquirer.py`, `backend/app/services/crawl_fetch_runtime.py`, acquisition tests
**What:** Replace raw fetch-runtime knob plumbing with an explicit acquisition policy object used by callers and translated inside acquisition.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py tests/services/test_browser_context.py -q`

### Slice 5: Pipeline Result and Failure Interface
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/services/pipeline/types.py`, `backend/app/services/pipeline/runtime_helpers.py`, `backend/app/services/_batch_runtime.py`, `backend/app/services/crawl_service.py`, structure tests
**What:** Remove tuple result compatibility and private failure-helper reach-in. Use public typed result and failure APIs.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py tests/services/test_batch_runtime.py tests/services/test_structure.py -q`

### Slice 6: Architecture Guardrails
**Status:** DONE
**Files:** `backend/tests/services/test_structure.py`, docs updated by earlier slices
**What:** Update guardrails to enforce the refactored module contracts and remove obsolete allowlist entries/budgets after slices land.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py -q`

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — if files move or ownership changes.
- [x] `docs/ENGINEERING_STRATEGY.md` — if a new anti-pattern or guardrail emerges.
- [ ] `docs/INVARIANTS.md` — only if extraction contracts change.
- [x] `docs/backend-architecture.md` — if public backend module interfaces change.

## Notes

- User-selected priority from architecture candidates: 2, 3, 4, 5, 1, 6. Saved here as Slice 1 through Slice 6.
- Active plan at start was complete, so this plan becomes current active work.
- Slice 1 verified with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py -q` on 2026-05-06: 274 passed, 1 skipped.
- Slice 2 verified with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_listing_identity_regressions.py tests/services/test_job_platform_adapters.py -q` on 2026-05-06: 188 passed.
- Slice 3 moved public-record policy, variant policy, and JS-state field specs out of `field_mappings.py`. Verified with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_config_imports.py tests/services/test_structure.py tests/services/test_field_value_core.py -q` on 2026-05-06: 92 passed. Extra JS-state regression check: `tests/services/test_detail_extractor_structured_sources.py -q`, 138 passed, 1 skipped.
- Slice 4 added `AcquisitionPolicy` as the caller-facing policy object and kept raw fetch-runtime knob translation inside acquisition. Verified with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_acquirer.py tests/services/test_crawl_fetch_runtime.py tests/services/test_browser_context.py -q` on 2026-05-06: 167 passed.
- Slice 5 removed tuple result compatibility and replaced private failure-helper imports with the public `mark_run_failed` API. Slice 6 removed obsolete private-import allowlist entries and moved selector priority config into `app/services/config/*`. Verified with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py tests/services/test_batch_runtime.py tests/services/test_structure.py tests/services/test_crawl_service.py -q` on 2026-05-06: 93 passed.
- Final backend verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` on 2026-05-06: 1316 passed, 4 skipped.
- Frontend repo tests passed with `cd frontend; npm test -- --run` on 2026-05-06: 81 passed.
